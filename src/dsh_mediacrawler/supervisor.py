from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from .artifacts import discover, export_zip
from .artifacts import preview as preview_artifact
from .errors import AdapterError
from .lock import InterProcessLease
from .models import CollectRequest
from .redaction import redact_text
from .settings import Runner, Settings
from .store import RunStore, utc_now

ACTIVE_STATES = {"starting", "running", "stopping"}
SEARCH_PAGE_FLOORS = {
    "xhs": 20,
    "dy": 10,
    "ks": 20,
    "bili": 20,
    "wb": 10,
    "tieba": 10,
    "zhihu": 20,
}
CREATOR_CAP_UNENFORCED = {"dy", "ks", "bili", "wb", "zhihu"}
ATTENTION_RULES = (
    (
        "waiting for scan code login",
        "awaiting_user_login",
        "scan_qrcode",
        "Scan the QR code shown in the isolated browser or QR window.",
    ),
    (
        "by qrcode",
        "awaiting_user_login",
        "scan_qrcode",
        "Scan the QR code shown in the isolated browser or QR window.",
    ),
    (
        "confirmation dialog and accept it",
        "awaiting_browser_confirmation",
        "accept_browser_confirmation",
        "Accept Chrome's remote-debugging confirmation dialog.",
    ),
    (
        "please enable remote debugging",
        "awaiting_browser_setup",
        "enable_remote_debugging",
        "Enable Chrome remote debugging for the configured CDP port.",
    ),
)
ATTENTION_CLEAR_MARKERS = (
    "successfully connected to existing browser",
    "fallback to standard mode",
    "login successful",
    "failed by qrcode",
    "have not found qrcode",
    "login qrcode not found",
    "login failed please confirm",
    "use cache login state",
    "crawler finished",
)


def _new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"mc_{stamp}_{uuid.uuid4().hex[:8]}"


def _bool_arg(value: bool) -> str:
    return "true" if value else "false"


class CrawlerService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.store = RunStore(self.settings.state_dir)
        self._lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._log_sequences: dict[str, int] = {}
        self._leases: dict[str, InterProcessLease] = {}
        self._export_locks: dict[str, asyncio.Lock] = {}

    def _base_readiness(self) -> tuple[bool, list[str]]:
        issues: list[str] = []
        root = self.settings.mediacrawler_root
        if root is None:
            issues.append("Set MEDIACRAWLER_ROOT to the MediaCrawler source directory.")
        elif not root.is_dir():
            issues.append(f"MediaCrawler root does not exist: {root}")
        else:
            for relative in ("main.py", "cmd_arg/arg.py"):
                if not (root / relative).is_file():
                    issues.append(f"Required upstream file is missing: {relative}")
        if (
            self.settings.python_executable
            and not self.settings.python_executable.is_file()
        ):
            issues.append(
                f"MEDIACRAWLER_PYTHON does not exist: {self.settings.python_executable}"
            )
        return not issues, issues

    async def check(self, deep: bool = False) -> dict[str, Any]:
        ready, issues = self._base_readiness()
        runner_kind: str | None = None
        command_available = False
        deep_check: dict[str, Any] | None = None
        if ready:
            runner = self.settings.runner()
            runner_kind = runner.kind
            command_available = Path(runner.command[0]).is_file() or bool(
                shutil.which(runner.command[0])
            )
            if not command_available:
                issues.append(f"Runner executable is unavailable: {runner.command[0]}")
                ready = False
            elif deep:
                deep_check = await self._deep_check(runner)
                if not deep_check["passed"]:
                    ready = False
                    if not deep_check.get("cli_passed"):
                        issues.append(
                            "MediaCrawler CLI --help failed; install its Python dependencies."
                        )
                    if not deep_check.get("browser_probe", {}).get("passed", False):
                        issues.append(
                            "Playwright could not launch an isolated system Chrome profile. "
                            "Install Google Chrome and verify that MediaCrawler's Playwright runtime can launch it."
                        )

        return {
            "ok": True,
            "ready": ready,
            "mediacrawler_root": str(self.settings.mediacrawler_root)
            if self.settings.mediacrawler_root
            else None,
            "state_dir": str(self.settings.state_dir),
            "runner": runner_kind,
            "runner_available": command_available,
            "issues": issues,
            "deep_check": deep_check,
            "supported_platforms": ["xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"],
        }

    async def _deep_check(self, runner: Runner) -> dict[str, Any]:
        process: asyncio.subprocess.Process | None = None
        process_create_time: float | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *runner.command,
                "--help",
                cwd=str(self.settings.mediacrawler_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self._child_env(),
            )
            process_create_time = psutil.Process(process.pid).create_time()
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            output = redact_text(stdout.decode("utf-8", errors="replace"))[-4_000:]
            required = (
                "--platform",
                "--lt",
                "--type",
                "--start",
                "--get_comment",
                "--get_sub_comment",
                "--headless",
                "--save_data_option",
                "--save_data_path",
                "--crawler_max_notes_count",
                "--max_comments_count_singlenotes",
                "--max_concurrency_num",
                "--enable_ip_proxy",
            )
            argument_source = await asyncio.to_thread(
                (self.settings.mediacrawler_root / "cmd_arg" / "arg.py").read_text,
                encoding="utf-8",
                errors="replace",
            )
            contract_text = argument_source + "\n" + output
            missing = [option for option in required if option not in contract_text]
            cli_passed = process.returncode == 0 and not missing
            browser_probe = (
                await self._browser_probe(runner)
                if cli_passed
                else {"passed": False, "skipped": True, "checks": []}
            )
            return {
                "passed": cli_passed and browser_probe["passed"],
                "cli_passed": cli_passed,
                "exit_code": process.returncode,
                "missing_options": missing,
                "output_tail": output if process.returncode or missing else "",
                "browser_probe": browser_probe,
            }
        except TimeoutError:
            if process and process.returncode is None:
                await asyncio.to_thread(
                    self._terminate_pid,
                    process.pid,
                    None,
                    process_create_time,
                )
                await process.wait()
            return {"passed": False, "error": "CLI --help timed out after 30 seconds."}
        except OSError as exc:
            return {"passed": False, "error": redact_text(str(exc))}

    async def _browser_probe(self, runner: Runner) -> dict[str, Any]:
        probe = Path(__file__).with_name("browser_probe.py")
        env = self._child_env()
        root = str(self.settings.mediacrawler_root)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (root, env.get("PYTHONPATH"))))
        process: asyncio.subprocess.Process | None = None
        process_create_time: float | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *runner.command[:-1],
                str(probe),
                cwd=root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            process_create_time = psutil.Process(process.pid).create_time()
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=45)
            output = redact_text(stdout.decode("utf-8", errors="replace"))
            result = next(
                (
                    value
                    for line in reversed(output.splitlines())
                    if isinstance((value := self._parse_json_object(line)), dict)
                ),
                None,
            )
            if result is None:
                return {
                    "passed": False,
                    "checks": [],
                    "error": "Browser probe returned invalid output.",
                    "output_tail": output[-4_000:],
                }
            result["passed"] = bool(result.get("passed")) and process.returncode == 0
            if not result["passed"]:
                result["output_tail"] = output[-4_000:]
            return result
        except TimeoutError:
            if process and process.returncode is None:
                await asyncio.to_thread(
                    self._terminate_pid,
                    process.pid,
                    None,
                    process_create_time,
                )
                await process.wait()
            return {
                "passed": False,
                "checks": [],
                "error": "Browser launch probe timed out after 45 seconds.",
            }
        except OSError as exc:
            return {
                "passed": False,
                "checks": [],
                "error": redact_text(str(exc)),
            }

    @staticmethod
    def _parse_json_object(value: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    async def collect(self, request: CollectRequest) -> dict[str, Any]:
        async with self._lock:
            if request.request_id:
                existing = self.store.by_request_id(request.request_id)
                if existing:
                    if existing.get("fingerprint") != request.fingerprint():
                        raise AdapterError(
                            "REQUEST_ID_CONFLICT",
                            "request_id was already used with different collection parameters.",
                            run_id=existing.get("run_id"),
                        )
                    return self._start_response(existing, idempotent=True)

            ready, issues = self._base_readiness()
            if not ready:
                raise AdapterError(
                    "NOT_READY",
                    "MediaCrawler is not ready: " + " ".join(issues),
                    remediation="Run check(deep=true) after configuring the upstream source and environment.",
                )

            lease = InterProcessLease(self._lease_path())
            if not lease.acquire():
                active = self._peek_active_manifest()
                raise AdapterError(
                    "BUSY",
                    "Another adapter process is starting or running MediaCrawler.",
                    retryable=True,
                    run_id=active.get("run_id") if active else None,
                    remediation="Poll or stop the active run in the other DSH window.",
                )

            global_owner = self._live_global_owner()
            if global_owner:
                lease.release()
                raise AdapterError(
                    "BUSY",
                    "A MediaCrawler process from an earlier adapter host is still running.",
                    retryable=True,
                    run_id=global_owner.get("run_id"),
                    remediation=(
                        "Use the original adapter state directory to inspect or stop the run. "
                        "If that host crashed, stop its recorded crawler process before retrying."
                    ),
                )

            active = self._active_manifest()
            if active:
                lease.release()
                raise AdapterError(
                    "BUSY",
                    "Another MediaCrawler run is active.",
                    retryable=True,
                    run_id=active["run_id"],
                    remediation="Poll or stop the active run before starting another.",
                )

            run_id = _new_run_id()
            now = utc_now()
            warnings = self._scope_warnings(request)
            manifest: dict[str, Any] = {
                "schema_version": 1,
                "run_id": run_id,
                "request_id": request.request_id,
                "fingerprint": request.fingerprint(),
                "request": request.public_dict(),
                "state": "starting",
                "outcome": None,
                "pid": None,
                "process_create_time": None,
                "exit_code": None,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "finished_at": None,
                "cancel_requested": False,
                "error": None,
                "warnings": warnings,
            }
            try:
                self.store.create(manifest)
                self._leases[run_id] = lease
                task = asyncio.create_task(
                    self._run(run_id, request), name=f"mediacrawler-{run_id}"
                )
                self._tasks[run_id] = task
                return self._start_response(manifest, idempotent=False)
            except BaseException:
                self._leases.pop(run_id, None)
                lease.release()
                raise

    def _start_response(
        self, manifest: dict[str, Any], idempotent: bool
    ) -> dict[str, Any]:
        active = manifest["state"] in ACTIVE_STATES
        return {
            "ok": True,
            "run_id": manifest["run_id"],
            "state": manifest["state"],
            "outcome": manifest.get("outcome"),
            "phase": "starting" if active else "completed",
            "attention": None,
            "idempotent_replay": idempotent,
            "poll_after_seconds": 3 if active else None,
            "warnings": manifest.get("warnings", []),
            "next": (
                "Call status with this run_id. Complete QR-code verification in the opened browser if requested."
                if active
                else "The original run is complete; inspect artifacts or export its results."
            ),
        }

    @staticmethod
    def _scope_warnings(request: CollectRequest) -> list[str]:
        warnings: list[str] = []
        if (
            request.mode == "search"
            and request.max_items < SEARCH_PAGE_FLOORS[request.platform]
        ):
            warnings.append(
                f"MediaCrawler fetches full search pages on {request.platform}; the first page can contain up to "
                f"{SEARCH_PAGE_FLOORS[request.platform]} items even though max_items={request.max_items}."
            )
        if request.mode == "creator" and request.platform in CREATOR_CAP_UNENFORCED:
            warnings.append(
                f"The current MediaCrawler {request.platform} creator workflow does not enforce max_items; "
                "the adapter timeout remains the hard run boundary."
            )
        if request.include_nested_comments:
            warnings.append(
                "Some upstream platforms fetch all nested replies for selected first-level comments; "
                "the adapter timeout remains the hard run boundary."
            )
        if request.browser_mode == "existing_cdp":
            warnings.append(
                "existing_cdp reuses a user-controlled Chrome context; upstream cleanup may close that context. "
                "Use it only after explicit user approval."
            )
            if request.headless:
                warnings.append(
                    "headless is ignored when existing_cdp reuses an already-running Chrome context."
                )
        elif request.headless:
            warnings.append(
                "Headless mode cannot display a first-time QR login; use it only when the isolated profile is already authenticated."
            )
        return warnings

    def _lease_path(self) -> Path:
        root = self.settings.mediacrawler_root
        identity = str(root.resolve() if root else "unconfigured")
        if os.name == "nt":
            identity = identity.casefold()
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return Path(tempfile.gettempdir()) / "dsh-mediacrawler-locks" / f"{digest}.lock"

    def _owner_path(self) -> Path:
        return self._lease_path().with_suffix(".owner.json")

    def _live_global_owner(self) -> dict[str, Any] | None:
        path = self._owner_path()
        if not path.is_file():
            return None
        try:
            owner = json.loads(path.read_text(encoding="utf-8"))
            pid = int(owner["pid"])
            data_dir = Path(str(owner["data_dir"]))
            create_time = float(owner["process_create_time"])
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            return None
        if self._pid_matches(pid, data_dir, create_time):
            return owner
        path.unlink(missing_ok=True)
        return None

    def _write_global_owner(
        self, run_id: str, pid: int, process_create_time: float, data_dir: Path
    ) -> None:
        path = self._owner_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        owner = {
            "run_id": run_id,
            "state_dir": str(self.store.state_dir),
            "pid": pid,
            "process_create_time": process_create_time,
            "data_dir": str(data_dir),
        }
        temp = path.with_suffix(f".tmp-{os.getpid()}-{uuid.uuid4().hex}")
        temp.write_text(
            json.dumps(owner, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.chmod(temp, 0o600)
        temp.replace(path)
        os.chmod(path, 0o600)

    def _clear_global_owner(self, run_id: str) -> None:
        path = self._owner_path()
        try:
            owner = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if owner.get("run_id") == run_id:
            path.unlink(missing_ok=True)

    def _peek_active_manifest(self) -> dict[str, Any] | None:
        return next(
            (
                manifest
                for manifest in self.store.all_manifests()
                if manifest.get("state") in ACTIVE_STATES
            ),
            None,
        )

    def _active_manifest(self) -> dict[str, Any] | None:
        for manifest in self.store.all_manifests():
            if manifest.get("state") not in ACTIVE_STATES:
                continue
            run_id = manifest["run_id"]
            task = self._tasks.get(run_id)
            if task is not None and not task.done():
                return manifest
            pid = manifest.get("pid")
            if pid and self._pid_matches(
                int(pid),
                self.store.data_dir(run_id),
                manifest.get("process_create_time"),
            ):
                return manifest
            self.store.update(
                run_id,
                state="completed",
                outcome="orphaned",
                finished_at=utc_now(),
                error="The adapter restarted or the crawler process disappeared before completion.",
            )
        return None

    def _build_command(
        self, request: CollectRequest, data_dir: Path
    ) -> tuple[str, ...]:
        runner = self.settings.runner()
        wrapper = Path(__file__).with_name("upstream_runner.py")
        command = [
            *runner.command[:-1],
            str(wrapper),
            "--platform",
            request.platform,
            "--lt",
            request.login_type,
            "--type",
            request.mode,
            "--start",
            str(request.start_page),
            "--get_comment",
            _bool_arg(request.include_comments),
            "--get_sub_comment",
            _bool_arg(request.include_nested_comments),
            "--headless",
            _bool_arg(request.headless),
            "--save_data_option",
            "jsonl",
            "--crawler_max_notes_count",
            str(request.max_items),
            "--max_comments_count_singlenotes",
            str(request.max_comments_per_item),
            "--max_concurrency_num",
            "1",
            "--save_data_path",
            str(data_dir),
            "--enable_ip_proxy",
            "false",
        ]
        return tuple(command)

    def _launch_spec(self, request: CollectRequest) -> bytes:
        profile_root = self.store.state_dir / "browser_profiles"
        profile_root.mkdir(parents=True, exist_ok=True)
        os.chmod(profile_root, 0o700)
        value = {
            "root": str(self.settings.mediacrawler_root),
            "platform": request.platform,
            "mode": request.mode,
            "query": request.query,
            "targets": list(request.targets),
            "browser_mode": request.browser_mode,
            "browser_profile_template": str(profile_root / "%s_user_data_dir"),
        }
        return (
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )

    def _child_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        return env

    async def _run(self, run_id: str, request: CollectRequest) -> None:
        process: asyncio.subprocess.Process | None = None
        process_create_time: float | None = None
        log_task: asyncio.Task[None] | None = None
        try:
            command = self._build_command(request, self.store.data_dir(run_id))
            kwargs: dict[str, Any] = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            async with self._lock:
                current = self.store.load(run_id)
                if current.get("cancel_requested"):
                    self.store.update(
                        run_id,
                        state="completed",
                        outcome="cancelled",
                        finished_at=utc_now(),
                    )
                    return
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=str(self.settings.mediacrawler_root),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=self._child_env(),
                    **kwargs,
                )
                self._processes[run_id] = process
                process_create_time = psutil.Process(process.pid).create_time()
                self._write_global_owner(
                    run_id,
                    process.pid,
                    process_create_time,
                    self.store.data_dir(run_id),
                )
                if process.stdin is None:
                    raise RuntimeError("Crawler stdin pipe is unavailable")
                process.stdin.write(self._launch_spec(request))
                await process.stdin.drain()
                process.stdin.close()
                self.store.update(
                    run_id,
                    state="running",
                    pid=process.pid,
                    process_create_time=process_create_time,
                    started_at=utc_now(),
                )
            self._append_log(
                run_id,
                f"MediaCrawler started for platform={request.platform} mode={request.mode}.",
            )
            log_task = asyncio.create_task(self._capture_logs(run_id, process))

            timed_out = False
            try:
                await asyncio.wait_for(
                    process.wait(), timeout=request.timeout_minutes * 60
                )
            except TimeoutError:
                timed_out = True
                self._append_log(run_id, "Run timed out; stopping process tree.")
                await asyncio.to_thread(
                    self._terminate_pid,
                    process.pid,
                    self.store.data_dir(run_id),
                    process_create_time,
                )
                await process.wait()

            if log_task:
                await log_task
            current = self.store.load(run_id)
            artifacts = await asyncio.to_thread(discover, self.store.data_dir(run_id))
            record_count = sum(int(item["records"]) for item in artifacts)
            upstream_errors = await asyncio.to_thread(
                self.store.has_upstream_errors, run_id
            )
            warnings = list(current.get("warnings", []))
            if record_count and upstream_errors:
                warnings.append(
                    "MediaCrawler wrote records but also logged upstream errors; the result may be incomplete."
                )
            if timed_out:
                outcome = "timed_out"
                error = "The collection exceeded its timeout and was stopped."
            elif current.get("cancel_requested"):
                outcome = "cancelled"
                error = None
            elif process.returncode != 0:
                outcome = "failed"
                error = f"MediaCrawler exited with code {process.returncode}. Inspect the run logs."
            elif record_count:
                outcome = "data_available"
                error = None
            elif upstream_errors:
                outcome = "failed"
                error = (
                    "MediaCrawler exited without records after logging errors. Inspect the run logs; "
                    "the adapter will not retry automatically."
                )
            else:
                outcome = "no_data"
                error = None
            self.store.update(
                run_id,
                state="completed",
                outcome=outcome,
                exit_code=process.returncode,
                finished_at=utc_now(),
                error=error,
                warnings=warnings,
                upstream_errors_detected=upstream_errors,
                artifact_count=len(artifacts),
                record_count=record_count,
            )
        except asyncio.CancelledError:
            if process and process.returncode is None:
                await asyncio.to_thread(
                    self._terminate_pid,
                    process.pid,
                    self.store.data_dir(run_id),
                    process_create_time,
                )
                await process.wait()
            current = self.store.load(run_id)
            self.store.update(
                run_id,
                state="completed",
                outcome="cancelled" if current.get("cancel_requested") else "orphaned",
                exit_code=process.returncode if process else None,
                finished_at=utc_now(),
                error=None
                if current.get("cancel_requested")
                else "The adapter stopped before the run completed.",
            )
            raise
        except Exception as exc:  # noqa: BLE001 - supervision must always clean up the child
            if process and process.returncode is None:
                await asyncio.to_thread(
                    self._terminate_pid,
                    process.pid,
                    self.store.data_dir(run_id),
                    process_create_time,
                )
                await process.wait()
            self._append_log(
                run_id, f"Adapter start/run error: {redact_text(str(exc))}"
            )
            current = self.store.load(run_id)
            cancelled = bool(current.get("cancel_requested"))
            self.store.update(
                run_id,
                state="completed",
                outcome="cancelled" if cancelled else "failed",
                exit_code=process.returncode if process else None,
                finished_at=utc_now(),
                error=None
                if cancelled
                else "The adapter could not start or supervise MediaCrawler. Inspect the run logs.",
            )
        finally:
            if process and process.returncode is None:
                await asyncio.to_thread(
                    self._terminate_pid,
                    process.pid,
                    self.store.data_dir(run_id),
                    process_create_time,
                )
                await process.wait()
            if log_task and not log_task.done():
                log_task.cancel()
                await asyncio.gather(log_task, return_exceptions=True)
            self._processes.pop(run_id, None)
            self._tasks.pop(run_id, None)
            self._log_sequences.pop(run_id, None)
            self._clear_global_owner(run_id)
            lease = self._leases.pop(run_id, None)
            if lease:
                lease.release()

    def _append_log(self, run_id: str, message: str) -> None:
        sequence = self._log_sequences.get(run_id, 0) + 1
        self._log_sequences[run_id] = sequence
        self.store.append_log(run_id, sequence, message)

    async def _capture_logs(
        self, run_id: str, process: asyncio.subprocess.Process
    ) -> None:
        if process.stdout is None:
            return
        while True:
            raw = await process.stdout.readline()
            if not raw:
                break
            message = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            self._append_log(run_id, message)

    def _pid_matches(
        self, pid: int, data_dir: Path, expected_create_time: float | None = None
    ) -> bool:
        try:
            process = psutil.Process(pid)
            return self._process_matches(process, data_dir, expected_create_time)
        except (psutil.Error, OSError):
            return False

    @staticmethod
    def _process_matches(
        process: psutil.Process,
        data_dir: Path | None,
        expected_create_time: float | None,
    ) -> bool:
        if (
            expected_create_time is not None
            and abs(process.create_time() - expected_create_time) > 0.001
        ):
            return False
        if data_dir is None:
            return True
        command = " ".join(process.cmdline()).lower()
        is_crawler = "main.py" in command or "upstream_runner.py" in command
        return is_crawler and str(data_dir).lower() in command

    @classmethod
    def _terminate_pid(
        cls,
        pid: int,
        data_dir: Path | None = None,
        expected_create_time: float | None = None,
    ) -> bool:
        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return False
        try:
            if not cls._process_matches(parent, data_dir, expected_create_time):
                return False
        except (psutil.Error, OSError):
            return False
        processes = parent.children(recursive=True)
        for process in reversed(processes):
            try:
                process.terminate()
            except psutil.Error:
                pass
        try:
            parent.terminate()
        except psutil.Error:
            pass
        _, alive = psutil.wait_procs([*processes, parent], timeout=5)
        for process in alive:
            try:
                process.kill()
            except psutil.Error:
                pass
        return True

    async def status(self, run_id: str) -> dict[str, Any]:
        manifest = self.store.load(run_id)
        if manifest.get("state") in ACTIVE_STATES:
            task = self._tasks.get(run_id)
            pid = manifest.get("pid")
            if not (task and not task.done()) and not (
                pid
                and self._pid_matches(
                    int(pid),
                    self.store.data_dir(run_id),
                    manifest.get("process_create_time"),
                )
            ):
                manifest = self.store.update(
                    run_id,
                    state="completed",
                    outcome="orphaned",
                    finished_at=utc_now(),
                    error="The adapter restarted or the crawler process disappeared before completion.",
                )
        artifacts = await asyncio.to_thread(discover, self.store.data_dir(run_id))
        record_count = sum(int(item["records"]) for item in artifacts)
        record_counts: dict[str, int] = {}
        for artifact in artifacts:
            record_type = str(artifact["record_type"])
            record_counts[record_type] = record_counts.get(record_type, 0) + int(
                artifact["records"]
            )
        attention = None
        if manifest["state"] in ACTIVE_STATES:
            tail = await asyncio.to_thread(self.store.tail_logs, run_id, 100)
            attention = self._detect_attention(tail)
        phase = (
            attention["phase"]
            if attention
            else (
                manifest["state"] if manifest["state"] in ACTIVE_STATES else "completed"
            )
        )
        return {
            "ok": True,
            "run_id": run_id,
            "state": manifest["state"],
            "outcome": manifest.get("outcome"),
            "phase": phase,
            "attention": attention,
            "created_at": manifest.get("created_at"),
            "started_at": manifest.get("started_at"),
            "finished_at": manifest.get("finished_at"),
            "exit_code": manifest.get("exit_code"),
            "error": manifest.get("error"),
            "warnings": manifest.get("warnings", []),
            "upstream_errors_detected": bool(
                manifest.get("upstream_errors_detected", False)
            ),
            "artifact_count": len(artifacts),
            "record_count": record_count,
            "record_counts": record_counts,
            "poll_after_seconds": 3 if manifest["state"] in ACTIVE_STATES else None,
        }

    @staticmethod
    def _detect_attention(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
        attention = None
        for entry in entries:
            message = str(entry.get("message", ""))
            lowered = message.lower()
            if any(marker in lowered for marker in ATTENTION_CLEAR_MARKERS):
                attention = None
                continue
            for marker, phase, action, instruction in ATTENTION_RULES:
                if marker in lowered:
                    attention = {
                        "required": True,
                        "phase": phase,
                        "action": action,
                        "message": instruction,
                        "since": entry.get("timestamp"),
                    }
        return attention

    async def stop(self, run_id: str) -> dict[str, Any]:
        async with self._lock:
            manifest = self.store.load(run_id)
            if manifest.get("state") == "completed":
                result = await self.status(run_id)
                result["already_stopped"] = True
                return result
            self.store.update(run_id, state="stopping", cancel_requested=True)
            process = self._processes.get(run_id)
            pid = process.pid if process else manifest.get("pid")
            task = self._tasks.get(run_id)

        if pid and (
            process is not None
            or self._pid_matches(
                int(pid),
                self.store.data_dir(run_id),
                manifest.get("process_create_time"),
            )
        ):
            await asyncio.to_thread(
                self._terminate_pid,
                int(pid),
                self.store.data_dir(run_id),
                manifest.get("process_create_time"),
            )
        if task:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=15)
            except TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        else:
            self.store.update(
                run_id,
                state="completed",
                outcome="cancelled",
                finished_at=utc_now(),
                error=None,
            )
            self._clear_global_owner(run_id)
        result = await self.status(run_id)
        result["already_stopped"] = False
        return result

    async def logs(
        self, run_id: str, after: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        if after < 0:
            raise AdapterError("INVALID_REQUEST", "after must be zero or greater.")
        if not 1 <= limit <= 200:
            raise AdapterError("INVALID_REQUEST", "limit must be between 1 and 200.")
        entries, cursor = await asyncio.to_thread(self.store.logs, run_id, after, limit)
        return {
            "ok": True,
            "run_id": run_id,
            "entries": entries,
            "next_cursor": cursor,
        }

    async def artifacts(self, run_id: str) -> dict[str, Any]:
        self.store.load(run_id)
        return {
            "ok": True,
            "run_id": run_id,
            "artifacts": await asyncio.to_thread(discover, self.store.data_dir(run_id)),
        }

    async def preview(
        self, run_id: str, artifact_id: str, offset: int = 0, limit: int = 10
    ) -> dict[str, Any]:
        self.store.load(run_id)
        if offset < 0:
            raise AdapterError("INVALID_REQUEST", "offset must be zero or greater.")
        if not 1 <= limit <= 50:
            raise AdapterError("INVALID_REQUEST", "limit must be between 1 and 50.")
        result = await asyncio.to_thread(
            preview_artifact,
            self.store.data_dir(run_id),
            artifact_id,
            offset,
            limit,
        )
        return {"ok": True, "run_id": run_id, **result}

    async def export(self, run_id: str) -> dict[str, Any]:
        manifest = self.store.load(run_id)
        if manifest.get("state") in ACTIVE_STATES:
            raise AdapterError(
                "RUN_ACTIVE",
                "Wait for the run to complete before exporting it.",
                retryable=True,
                run_id=run_id,
            )
        export_lock = self._export_locks.setdefault(run_id, asyncio.Lock())
        async with export_lock:
            result = await asyncio.to_thread(
                export_zip, self.store.run_dir(run_id), manifest
            )
        return {"ok": True, "run_id": run_id, "export": result}

    async def shutdown(self) -> None:
        owned_ids = set(self._tasks) | set(self._leases)
        for run_id in owned_ids:
            try:
                manifest = self.store.load(run_id)
                if manifest.get("state") in ACTIVE_STATES:
                    await self.stop(run_id)
            except AdapterError:
                continue
        remaining = [task for task in self._tasks.values() if not task.done()]
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)

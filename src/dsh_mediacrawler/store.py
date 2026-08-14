from __future__ import annotations

import json
import os
import re
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import AdapterError
from .redaction import redact_log_message, redact_value

_RUN_ID = re.compile(r"^mc_[0-9]{8}T[0-9]{6}Z_[a-f0-9]{8}$")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class RunStore:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir.expanduser().resolve()
        self.runs_dir = self.state_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_dir, 0o700)
        os.chmod(self.runs_dir, 0o700)

    def run_dir(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise AdapterError("RUN_NOT_FOUND", f"Run not found: {run_id!r}.")
        return self.runs_dir / run_id

    def manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "manifest.json"

    def data_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "data"

    def log_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "logs.jsonl"

    def create(self, manifest: dict[str, Any]) -> None:
        run_dir = self.run_dir(manifest["run_id"])
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "data").mkdir()
        os.chmod(run_dir, 0o700)
        os.chmod(run_dir / "data", 0o700)
        self.save(manifest)

    def save(self, manifest: dict[str, Any]) -> None:
        run_id = str(manifest["run_id"])
        target = self.manifest_path(run_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        sanitized = redact_value(manifest)
        temp = target.with_suffix(f".json.tmp-{os.getpid()}-{uuid.uuid4().hex}")
        temp.write_text(
            json.dumps(sanitized, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(temp, 0o600)
        temp.replace(target)
        os.chmod(target, 0o600)

    def load(self, run_id: str) -> dict[str, Any]:
        path = self.manifest_path(run_id)
        if not path.is_file():
            raise AdapterError("RUN_NOT_FOUND", f"Run not found: {run_id!r}.")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterError(
                "OUTPUT_INVALID", f"Run manifest is unreadable: {run_id!r}."
            ) from exc

    def update(self, run_id: str, **changes: Any) -> dict[str, Any]:
        manifest = self.load(run_id)
        manifest.update(changes)
        manifest["updated_at"] = utc_now()
        self.save(manifest)
        return manifest

    def all_manifests(self) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []
        for path in sorted(self.runs_dir.glob("*/manifest.json"), reverse=True):
            try:
                manifests.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return manifests

    def by_request_id(self, request_id: str) -> dict[str, Any] | None:
        return next(
            (
                manifest
                for manifest in self.all_manifests()
                if manifest.get("request_id") == request_id
            ),
            None,
        )

    def append_log(self, run_id: str, sequence: int, message: str) -> None:
        entry = {
            "sequence": sequence,
            "timestamp": utc_now(),
            "message": redact_log_message(message.rstrip("\r\n")),
        }
        with self.log_path(run_id).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.chmod(self.log_path(run_id), 0o600)

    def logs(
        self, run_id: str, after: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        self.load(run_id)
        path = self.log_path(run_id)
        if not path.is_file():
            return [], after
        entries: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if int(entry.get("sequence", 0)) <= after:
                    continue
                entries.append(entry)
                if len(entries) >= limit:
                    break
        next_cursor = entries[-1]["sequence"] if entries else after
        return entries, int(next_cursor)

    def tail_logs(self, run_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self.load(run_id)
        path = self.log_path(run_id)
        if not path.is_file():
            return []
        entries: deque[dict[str, Any]] = deque(maxlen=limit)
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return list(entries)

    def has_upstream_errors(self, run_id: str) -> bool:
        path = self.log_path(run_id)
        if not path.is_file():
            return False
        markers = (
            "MEDIACRAWLER ERROR",
            "ADAPTER START/RUN ERROR",
            "TRACEBACK",
            "FAILED BY QRCODE",
            "HAVE NOT FOUND QRCODE",
            "LOGIN QRCODE NOT FOUND",
            "LOGIN FAILED PLEASE CONFIRM",
        )
        detected = False
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    message = str(json.loads(line).get("message", "")).upper()
                except json.JSONDecodeError:
                    continue
                if "LOGIN SUCCESSFUL" in message:
                    detected = False
                    continue
                if any(marker in message for marker in markers):
                    detected = True
        return detected

from __future__ import annotations

import asyncio
import json
import sys
import threading
import zipfile
from pathlib import Path

import psutil
import pytest

import dsh_mediacrawler.supervisor as supervisor_module
from dsh_mediacrawler.errors import AdapterError
from dsh_mediacrawler.lock import InterProcessLease
from dsh_mediacrawler.models import CollectRequest
from dsh_mediacrawler.settings import Settings
from dsh_mediacrawler.supervisor import CrawlerService


def search_request(query: str = "normal", **overrides: object) -> CollectRequest:
    values: dict[str, object] = {
        "platform": "xhs",
        "mode": "search",
        "query": query,
        "headless": True,
    }
    values.update(overrides)
    return CollectRequest.create(**values)


@pytest.fixture
def service(tmp_path: Path, fake_mediacrawler_root: Path) -> CrawlerService:
    settings = Settings(
        mediacrawler_root=fake_mediacrawler_root,
        state_dir=tmp_path / "state with spaces",
        python_executable=Path(sys.executable),
    )
    return CrawlerService(settings)


async def wait_for_state(
    service: CrawlerService,
    run_id: str,
    expected: str = "completed",
    timeout: float = 10,
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        result = await service.status(run_id)
        if result["state"] == expected:
            return result
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail(f"run {run_id} did not reach {expected}: {result}")
        await asyncio.sleep(0.03)


@pytest.mark.asyncio
async def test_check_deep_accepts_fake_cli(service: CrawlerService) -> None:
    result = await service.check(deep=True)

    assert result["ok"] is True
    assert result["ready"] is True
    assert result["deep_check"]["passed"] is True


@pytest.mark.asyncio
async def test_normal_run_status_artifacts_preview_and_export(
    service: CrawlerService,
) -> None:
    started = await service.collect(search_request())
    run_id = started["run_id"]

    status = await wait_for_state(service, run_id)
    assert status["outcome"] == "data_available"
    assert status["exit_code"] == 0
    assert status["artifact_count"] == 1
    assert status["record_count"] == 1

    listed = await service.artifacts(run_id)
    assert len(listed["artifacts"]) == 1
    artifact = listed["artifacts"][0]
    assert artifact["relative_path"] == "xhs/search_contents_test.jsonl"
    assert artifact["records"] == 1

    preview = await service.preview(run_id, artifact["artifact_id"])
    assert preview["returned"] == 1
    record = preview["records"][0]
    assert record["id"] == "post-1"
    assert record["cookie"] == "[REDACTED]"
    assert record["nested"]["xsec_token"] == "[REDACTED]"
    assert record["nested"]["token"] == "[REDACTED]"
    assert "url-secret-value" not in record["url"]

    exported = await service.export(run_id)
    export_path = Path(exported["export"]["path"])
    assert export_path.is_file()
    assert exported["export"]["credential_redacted"] is True
    assert exported["export"]["pii_anonymized"] is False
    assert exported["export"]["safe_to_share"] is False
    assert export_path.name.endswith(".credential-redacted.zip")
    assert len(exported["export"]["sha256"]) == 64
    with zipfile.ZipFile(export_path) as archive:
        assert "manifest.json" in archive.namelist()
        data_name = "data/xhs/search_contents_test.jsonl"
        exported_record = json.loads(archive.read(data_name).decode("utf-8"))
    assert exported_record["cookie"] == "[REDACTED]"
    assert exported_record["nested"]["xsec_token"] == "[REDACTED]"
    assert "raw-cookie-value" not in json.dumps(exported_record)
    assert "url-secret-value" not in exported_record["url"]


@pytest.mark.asyncio
async def test_request_id_is_idempotent_and_conflicts_are_rejected(
    service: CrawlerService,
) -> None:
    first = await service.collect(search_request(request_id="repeatable-1"))
    replay = await service.collect(search_request(request_id="repeatable-1"))

    assert replay["run_id"] == first["run_id"]
    assert replay["idempotent_replay"] is True

    with pytest.raises(AdapterError) as caught:
        await service.collect(search_request("different", request_id="repeatable-1"))
    assert caught.value.code == "REQUEST_ID_CONFLICT"
    assert caught.value.run_id == first["run_id"]
    await wait_for_state(service, first["run_id"])


@pytest.mark.asyncio
async def test_only_one_run_can_be_active(service: CrawlerService) -> None:
    first = await service.collect(search_request("hang"))
    await wait_for_state(service, first["run_id"], expected="running")
    try:
        with pytest.raises(AdapterError) as caught:
            await service.collect(search_request("another"))
        assert caught.value.code == "BUSY"
        assert caught.value.retryable is True
        assert caught.value.run_id == first["run_id"]
    finally:
        await service.stop(first["run_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "outcome", "exit_code"),
    [
        ("fail", "failed", 7),
        ("no-data", "no_data", 0),
        ("soft-error", "failed", 0),
        ("qr-error", "failed", 0),
        ("dy-qr-error", "failed", 0),
    ],
)
async def test_failure_and_empty_results_have_distinct_outcomes(
    service: CrawlerService, query: str, outcome: str, exit_code: int
) -> None:
    started = await service.collect(search_request(query))
    status = await wait_for_state(service, started["run_id"])

    assert status["outcome"] == outcome
    assert status["exit_code"] == exit_code
    assert status["artifact_count"] == 0
    assert status["record_count"] == 0


@pytest.mark.asyncio
async def test_partial_results_surface_upstream_errors(
    service: CrawlerService,
) -> None:
    started = await service.collect(search_request("partial-error"))
    status = await wait_for_state(service, started["run_id"])

    assert status["outcome"] == "data_available"
    assert status["record_count"] == 1
    assert status["upstream_errors_detected"] is True
    assert any("may be incomplete" in item for item in status["warnings"])


@pytest.mark.asyncio
async def test_successful_login_clears_the_recoverable_login_error(
    service: CrawlerService,
) -> None:
    started = await service.collect(search_request("recovered-login-error"))
    status = await wait_for_state(service, started["run_id"])

    assert status["outcome"] == "data_available"
    assert status["upstream_errors_detected"] is False
    assert not any("may be incomplete" in item for item in status["warnings"])


@pytest.mark.asyncio
async def test_logs_are_redacted(service: CrawlerService) -> None:
    started = await service.collect(search_request())
    await wait_for_state(service, started["run_id"])

    result = await service.logs(started["run_id"])
    messages = "\n".join(entry["message"] for entry in result["entries"])
    assert "[REDACTED]" in messages
    assert "session-cookie" not in messages
    assert "log-token" not in messages
    assert "query-token" not in messages


@pytest.mark.asyncio
async def test_default_run_uses_a_state_scoped_isolated_profile(
    service: CrawlerService,
) -> None:
    started = await service.collect(search_request())
    await wait_for_state(service, started["run_id"])

    result = await service.logs(started["run_id"])
    messages = "\n".join(entry["message"] for entry in result["entries"])
    expected_profile = service.store.state_dir / "browser_profiles" / "%s_user_data_dir"
    assert "browser_mode_cdp=False" in messages
    assert "browser_channel=chrome" in messages
    assert str(expected_profile) in messages


@pytest.mark.asyncio
async def test_existing_cdp_requires_explicit_opt_in_and_warns(
    service: CrawlerService,
) -> None:
    started = await service.collect(
        search_request(browser_mode="existing_cdp", headless=True)
    )
    await wait_for_state(service, started["run_id"])

    warnings = " ".join(started["warnings"])
    assert "may close that context" in warnings
    assert "headless is ignored" in warnings
    assert "first-time QR login" not in warnings
    result = await service.logs(started["run_id"])
    messages = "\n".join(entry["message"] for entry in result["entries"])
    assert "browser_mode_cdp=True" in messages


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["hang-qr", "hang-dy-qr"])
async def test_status_surfaces_qrcode_attention(
    service: CrawlerService, query: str
) -> None:
    started = await service.collect(search_request(query, headless=False))
    try:
        deadline = asyncio.get_running_loop().time() + 5
        while True:
            status = await service.status(started["run_id"])
            if status["phase"] == "awaiting_user_login":
                break
            if asyncio.get_running_loop().time() >= deadline:
                pytest.fail(f"QR attention was not surfaced: {status}")
            await asyncio.sleep(0.03)
        assert status["attention"]["required"] is True
        assert status["attention"]["action"] == "scan_qrcode"
    finally:
        await service.stop(started["run_id"])


def test_qrcode_failure_clears_attention() -> None:
    entries = [
        {"timestamp": "one", "message": "Begin login bilibili by qrcode"},
        {
            "timestamp": "two",
            "message": "Login bilibili failed by qrcode login method",
        },
    ]

    assert CrawlerService._detect_attention(entries) is None


def test_douyin_login_failure_clears_attention() -> None:
    entries = [
        {"timestamp": "one", "message": "Begin login douyin by qrcode"},
        {"timestamp": "two", "message": "login failed please confirm"},
    ]

    assert CrawlerService._detect_attention(entries) is None


@pytest.mark.asyncio
async def test_preview_rejects_paths_in_place_of_artifact_ids(
    service: CrawlerService,
) -> None:
    started = await service.collect(search_request())
    await wait_for_state(service, started["run_id"])

    with pytest.raises(AdapterError) as caught:
        await service.preview(started["run_id"], "../../manifest.json")
    assert caught.value.code == "ARTIFACT_NOT_FOUND"


@pytest.mark.asyncio
async def test_stop_terminates_hanging_run_and_is_idempotent(
    service: CrawlerService,
) -> None:
    started = await service.collect(search_request("hang"))
    await wait_for_state(service, started["run_id"], expected="running")

    stopped = await service.stop(started["run_id"])
    assert stopped["state"] == "completed"
    assert stopped["outcome"] == "cancelled"
    assert stopped["already_stopped"] is False

    replay = await service.stop(started["run_id"])
    assert replay["state"] == "completed"
    assert replay["outcome"] == "cancelled"
    assert replay["already_stopped"] is True


@pytest.mark.asyncio
async def test_immediate_stop_cannot_race_past_start(service: CrawlerService) -> None:
    started = await service.collect(search_request("hang-immediate"))

    stopped = await service.stop(started["run_id"])

    assert stopped["state"] == "completed"
    assert stopped["outcome"] == "cancelled"


@pytest.mark.asyncio
async def test_shutdown_stops_the_process_tree(service: CrawlerService) -> None:
    started = await service.collect(search_request("hang-shutdown"))
    await wait_for_state(service, started["run_id"], expected="running")
    pid = int(service.store.load(started["run_id"])["pid"])

    await service.shutdown()

    assert not psutil.pid_exists(pid)
    status = await service.status(started["run_id"])
    assert status["outcome"] == "cancelled"


@pytest.mark.asyncio
async def test_sensitive_query_is_not_in_process_command_line(
    service: CrawlerService,
) -> None:
    secret = "never-in-argv"
    started = await service.collect(search_request(f"hang&xsec_token={secret}"))
    await wait_for_state(service, started["run_id"], expected="running")
    pid = int(service.store.load(started["run_id"])["pid"])
    command = " ".join(psutil.Process(pid).cmdline())
    try:
        assert secret not in command
        assert "--keywords" not in command
    finally:
        await service.stop(started["run_id"])


@pytest.mark.asyncio
async def test_zhihu_creator_targets_are_injected_by_wrapper(
    service: CrawlerService,
) -> None:
    request = CollectRequest.create(
        platform="zhihu",
        mode="creator",
        targets=["fail"],
        headless=True,
    )
    started = await service.collect(request)
    status = await wait_for_state(service, started["run_id"])

    assert status["outcome"] == "failed"
    assert any("does not enforce max_items" in item for item in started["warnings"])


@pytest.mark.asyncio
async def test_export_rejects_active_run(service: CrawlerService) -> None:
    started = await service.collect(search_request("hang-export"))
    await wait_for_state(service, started["run_id"], expected="running")
    try:
        with pytest.raises(AdapterError) as caught:
            await service.export(started["run_id"])
        assert caught.value.code == "RUN_ACTIVE"
    finally:
        await service.stop(started["run_id"])


@pytest.mark.asyncio
async def test_export_rejects_runs_over_the_source_size_limit(
    fake_mediacrawler_root: Path, tmp_path: Path
) -> None:
    limited = CrawlerService(
        Settings(
            mediacrawler_root=fake_mediacrawler_root,
            state_dir=tmp_path / "limited-state",
            python_executable=Path(sys.executable),
            max_export_bytes=1,
        )
    )
    started = await limited.collect(search_request())
    await wait_for_state(limited, started["run_id"])

    with pytest.raises(AdapterError) as caught:
        await limited.export(started["run_id"])

    assert caught.value.code == "EXPORT_TOO_LARGE"


@pytest.mark.asyncio
async def test_cancelled_export_holds_lock_until_worker_finishes(
    service: CrawlerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = await service.collect(search_request())
    await wait_for_state(service, started["run_id"])
    worker_started = threading.Event()
    worker_release = threading.Event()

    def slow_export(*_: object) -> dict[str, object]:
        worker_started.set()
        assert worker_release.wait(timeout=5)
        return {"path": "unused"}

    monkeypatch.setattr(supervisor_module, "export_zip", slow_export)
    task = asyncio.create_task(service.export(started["run_id"]))
    assert await asyncio.to_thread(worker_started.wait, 1)
    task.cancel()
    await asyncio.sleep(0.05)

    assert not task.done()
    worker_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_export_respects_cross_process_lease(service: CrawlerService) -> None:
    started = await service.collect(search_request())
    await wait_for_state(service, started["run_id"])
    lease = InterProcessLease(service.store.export_lock_path(started["run_id"]))
    assert lease.acquire()
    try:
        with pytest.raises(AdapterError) as caught:
            await service.export(started["run_id"])
        assert caught.value.code == "EXPORT_BUSY"
    finally:
        lease.release()


@pytest.mark.asyncio
async def test_two_service_instances_share_a_cross_process_lease(
    service: CrawlerService,
) -> None:
    other = CrawlerService(service.settings)
    results = await asyncio.gather(
        service.collect(search_request("hang-first")),
        other.collect(search_request("hang-second")),
        return_exceptions=True,
    )

    started = [result for result in results if isinstance(result, dict)]
    rejected = [result for result in results if isinstance(result, AdapterError)]
    assert len(started) == 1
    assert len(rejected) == 1
    assert rejected[0].code == "BUSY"

    owner = service if started[0]["run_id"] in service._tasks else other
    assert owner.store.load(started[0]["run_id"])["state"] in {
        "starting",
        "running",
    }
    await owner.stop(started[0]["run_id"])


@pytest.mark.asyncio
async def test_services_with_different_state_dirs_lock_the_same_upstream_root(
    service: CrawlerService, tmp_path: Path
) -> None:
    other = CrawlerService(
        Settings(
            mediacrawler_root=service.settings.mediacrawler_root,
            state_dir=tmp_path / "other state",
            python_executable=Path(sys.executable),
        )
    )
    started = await service.collect(search_request("hang-root-lease"))
    await wait_for_state(service, started["run_id"], expected="running")
    try:
        with pytest.raises(AdapterError) as caught:
            await other.collect(search_request("blocked"))
        assert caught.value.code == "BUSY"
    finally:
        await service.stop(started["run_id"])


@pytest.mark.asyncio
async def test_global_owner_registry_survives_an_adapter_lock_loss(
    service: CrawlerService, tmp_path: Path
) -> None:
    other = CrawlerService(
        Settings(
            mediacrawler_root=service.settings.mediacrawler_root,
            state_dir=tmp_path / "crash recovery state",
            python_executable=Path(sys.executable),
        )
    )
    started = await service.collect(search_request("hang-crash-recovery"))
    await wait_for_state(service, started["run_id"], expected="running")
    service._leases[started["run_id"]].release()
    try:
        with pytest.raises(AdapterError) as caught:
            await other.collect(search_request("must-not-start"))
        assert caught.value.code == "BUSY"
        assert caught.value.run_id == started["run_id"]
    finally:
        await service.stop(started["run_id"])


@pytest.mark.asyncio
async def test_other_service_shutdown_does_not_stop_owner_run(
    service: CrawlerService,
) -> None:
    other = CrawlerService(service.settings)
    started = await service.collect(search_request("hang-owner"))
    await wait_for_state(service, started["run_id"], expected="running")
    pid = int(service.store.load(started["run_id"])["pid"])

    await other.shutdown()

    assert psutil.pid_exists(pid)
    assert (await service.status(started["run_id"]))["state"] == "running"
    await service.stop(started["run_id"])


@pytest.mark.asyncio
async def test_oversized_preview_record_advances_cursor(
    service: CrawlerService,
) -> None:
    started = await service.collect(search_request())
    await wait_for_state(service, started["run_id"])
    listed = await service.artifacts(started["run_id"])
    artifact = listed["artifacts"][0]
    path = service.store.data_dir(started["run_id"]) / artifact["relative_path"]
    oversized = {"items": ["x" * 2_000 for _ in range(40)]}
    path.write_text(json.dumps(oversized) + "\n", encoding="utf-8")

    result = await service.preview(
        started["run_id"], artifact["artifact_id"], offset=0, limit=1
    )

    assert result["returned"] == 1
    assert result["next_offset"] == 1
    assert result["records"] == [
        {
            "_preview_truncated": True,
            "reason": "record_exceeds_64_kib_preview_limit",
        }
    ]


@pytest.mark.asyncio
async def test_runs_recovers_recent_run_and_result_combines_preview(
    service: CrawlerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = await service.collect(search_request("recoverable"))
    await wait_for_state(service, started["run_id"])

    calls = 0
    original_discover = service.artifact_index.discover

    def counted_discover(data_dir: Path) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return original_discover(data_dir)

    monkeypatch.setattr(service.artifact_index, "discover", counted_discover)
    recent = await service.runs(limit=1)
    combined = await service.result(started["run_id"], limit=1)

    assert recent["returned"] == 1
    assert recent["runs"][0]["run_id"] == started["run_id"]
    assert recent["runs"][0]["query"] == "recoverable"
    assert combined["outcome"] == "data_available"
    assert combined["artifact_count"] == 1
    assert combined["requested_record_type"] is None
    assert combined["selected_record_type"] == "contents"
    assert combined["sample"]["returned"] == 1
    assert combined["sample"]["records"][0]["title"] == "fixture record"
    assert calls == 1


@pytest.mark.asyncio
async def test_result_can_select_record_type_and_validates_bounds(
    service: CrawlerService,
) -> None:
    started = await service.collect(search_request())
    await wait_for_state(service, started["run_id"])

    missing = await service.result(started["run_id"], record_type="comments")
    assert missing["sample"] is None

    with pytest.raises(AdapterError, match="record_type must be"):
        await service.result(started["run_id"], record_type="secrets")
    with pytest.raises(AdapterError, match="limit must be"):
        await service.runs(limit=0)


@pytest.mark.asyncio
async def test_delete_run_requires_confirmation_and_preserves_browser_profiles(
    service: CrawlerService,
) -> None:
    started = await service.collect(search_request())
    await wait_for_state(service, started["run_id"])

    with pytest.raises(AdapterError) as caught:
        await service.delete_run(started["run_id"])
    assert caught.value.code == "CONFIRMATION_REQUIRED"

    deleted = await service.delete_run(started["run_id"], confirm=True)

    assert deleted["deleted"] is True
    assert deleted["browser_profiles_deleted"] is False
    assert not service.store.run_dir(started["run_id"]).exists()
    assert (service.store.state_dir / "browser_profiles").is_dir()


@pytest.mark.asyncio
async def test_delete_run_rejects_active_run(service: CrawlerService) -> None:
    started = await service.collect(search_request("hang-delete"))
    await wait_for_state(service, started["run_id"], expected="running")
    try:
        with pytest.raises(AdapterError) as caught:
            await service.delete_run(started["run_id"], confirm=True)
        assert caught.value.code == "RUN_ACTIVE"
    finally:
        await service.stop(started["run_id"])


@pytest.mark.asyncio
async def test_cleanup_is_dry_run_by_default_and_deletes_only_when_requested(
    service: CrawlerService,
) -> None:
    started = await service.collect(search_request())
    await wait_for_state(service, started["run_id"])
    service.store.update(
        started["run_id"],
        finished_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
    )

    preview = await service.cleanup(older_than_days=30, keep_latest=0)
    applied = await service.cleanup(older_than_days=30, keep_latest=0, dry_run=False)

    assert preview["dry_run"] is True
    assert preview["candidates"][0]["run_id"] == started["run_id"]
    assert service.store.run_dir(started["run_id"]).exists() is False
    assert applied["deleted"] == [started["run_id"]]
    assert applied["browser_profiles_deleted"] is False


@pytest.mark.asyncio
async def test_cleanup_keep_latest_protects_recent_slots(
    service: CrawlerService,
) -> None:
    started = await service.collect(search_request())
    await wait_for_state(service, started["run_id"])
    service.store.update(
        started["run_id"],
        finished_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
    )

    result = await service.cleanup(older_than_days=30, keep_latest=1)

    assert result["candidates"] == []


def test_pid_creation_time_mismatch_is_never_terminated(
    service: CrawlerService,
) -> None:
    current = psutil.Process()

    terminated = service._terminate_pid(
        current.pid,
        data_dir=None,
        expected_create_time=current.create_time() + 100,
    )

    assert terminated is False

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AdapterError
from .redaction import redact_value, truncate_value

MAX_PREVIEW_BYTES = 64 * 1024
_UPSTREAM_ARTIFACT_NAME = re.compile(
    r"^(search|detail|creator)_(contents|comments|creators|contacts|dynamics)(?:_|$)"
)


def _artifact_id(relative_path: str) -> str:
    return "a_" + hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def _classify(relative_path: str) -> tuple[str, str]:
    match = _UPSTREAM_ARTIFACT_NAME.match(Path(relative_path).stem)
    if match is None:
        return "unknown", "unknown"
    return match.group(1), match.group(2)


def _jsonl_records(path: Path) -> Iterator[tuple[int, Any | None, str | None]]:
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.endswith(b"\n"):
                yield line_number, None, "incomplete_final_line"
                continue
            try:
                text = raw.decode("utf-8")
                yield line_number, json.loads(text), None
            except (UnicodeDecodeError, json.JSONDecodeError):
                yield line_number, None, "invalid_json"


@dataclass(frozen=True, slots=True)
class _IndexEntry:
    identity: tuple[int, int]
    observed_size: int
    observed_mtime_ns: int
    processed_bytes: int
    records: int
    invalid_lines: int
    artifact: dict[str, Any]


class ArtifactIndex:
    """Process-local incremental index for append-only upstream JSONL files."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _IndexEntry] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _scan(
        path: Path,
        size: int,
        offset: int,
        records: int,
        invalid_lines: int,
    ) -> tuple[int, int, int, int]:
        processed_bytes = offset
        incomplete_lines = 0
        with path.open("rb") as handle:
            handle.seek(offset)
            while handle.tell() < size:
                line_start = handle.tell()
                raw = handle.readline(size - line_start)
                if not raw.endswith(b"\n"):
                    incomplete_lines = 1
                    processed_bytes = line_start
                    break
                processed_bytes = handle.tell()
                try:
                    json.loads(raw.decode("utf-8"))
                    records += 1
                except (UnicodeDecodeError, json.JSONDecodeError):
                    invalid_lines += 1
        return processed_bytes, records, invalid_lines, incomplete_lines

    def discover(self, data_dir: Path) -> list[dict[str, Any]]:
        if not data_dir.is_dir():
            return []
        root = data_dir.resolve()
        root_key = str(root)
        artifacts: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for path in sorted(data_dir.rglob("*.jsonl")):
            try:
                if not path.is_file():
                    continue
                resolved = path.resolve()
                relative = resolved.relative_to(root).as_posix()
                stat = resolved.stat()
            except (OSError, ValueError):
                continue
            key = (root_key, relative)
            seen.add(key)
            identity = (int(stat.st_dev), int(stat.st_ino))
            with self._lock:
                cached = self._entries.get(key)
            if (
                cached is not None
                and cached.identity == identity
                and cached.observed_size == stat.st_size
                and cached.observed_mtime_ns == stat.st_mtime_ns
            ):
                artifacts.append(dict(cached.artifact))
                continue

            can_resume = (
                cached is not None
                and cached.identity == identity
                and stat.st_size >= cached.processed_bytes
            )
            offset = cached.processed_bytes if can_resume else 0
            records = cached.records if can_resume else 0
            invalid_lines = cached.invalid_lines if can_resume else 0
            try:
                processed, records, invalid_lines, incomplete = self._scan(
                    resolved, stat.st_size, offset, records, invalid_lines
                )
            except OSError:
                continue
            collection_mode, record_type = _classify(relative)
            artifact = {
                "artifact_id": _artifact_id(relative),
                "relative_path": relative,
                "collection_mode": collection_mode,
                "record_type": record_type,
                "bytes": stat.st_size,
                "records": records,
                "invalid_lines": invalid_lines,
                "incomplete_lines": incomplete,
            }
            entry = _IndexEntry(
                identity=identity,
                observed_size=stat.st_size,
                observed_mtime_ns=stat.st_mtime_ns,
                processed_bytes=processed,
                records=records,
                invalid_lines=invalid_lines,
                artifact=artifact,
            )
            with self._lock:
                self._entries[key] = entry
            artifacts.append(dict(artifact))

        with self._lock:
            for key in tuple(self._entries):
                if key[0] == root_key and key not in seen:
                    self._entries.pop(key, None)
        return artifacts

    def invalidate(self, data_dir: Path) -> None:
        root_key = str(data_dir.resolve())
        with self._lock:
            for key in tuple(self._entries):
                if key[0] == root_key:
                    self._entries.pop(key, None)


def discover(data_dir: Path) -> list[dict[str, Any]]:
    return ArtifactIndex().discover(data_dir)


def resolve_artifact(
    data_dir: Path,
    artifact_id: str,
    *,
    artifacts: list[dict[str, Any]] | None = None,
    index: ArtifactIndex | None = None,
) -> tuple[Path, dict[str, Any]]:
    available = (
        artifacts
        if artifacts is not None
        else (index.discover(data_dir) if index is not None else discover(data_dir))
    )
    artifact = next(
        (item for item in available if item["artifact_id"] == artifact_id),
        None,
    )
    if artifact is None:
        raise AdapterError(
            "ARTIFACT_NOT_FOUND", f"Artifact not found: {artifact_id!r}."
        )
    path = (data_dir / artifact["relative_path"]).resolve()
    try:
        path.relative_to(data_dir.resolve())
    except ValueError as exc:
        raise AdapterError(
            "ARTIFACT_NOT_FOUND", "Artifact path is outside the run."
        ) from exc
    return path, artifact


def preview(
    data_dir: Path,
    artifact_id: str,
    offset: int,
    limit: int,
    *,
    artifacts: list[dict[str, Any]] | None = None,
    index: ArtifactIndex | None = None,
) -> dict[str, Any]:
    path, artifact = resolve_artifact(
        data_dir, artifact_id, artifacts=artifacts, index=index
    )
    records: list[Any] = []
    valid_index = 0
    invalid_lines = 0
    incomplete_lines = 0
    response_bytes = 0
    truncated = False

    for _, value, error in _jsonl_records(path):
        if error == "incomplete_final_line":
            incomplete_lines += 1
            continue
        if error:
            invalid_lines += 1
            continue
        if valid_index < offset:
            valid_index += 1
            continue
        if len(records) >= limit:
            break
        safe_value = truncate_value(redact_value(value))
        encoded = json.dumps(safe_value, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_PREVIEW_BYTES:
            records.append(
                {
                    "_preview_truncated": True,
                    "reason": "record_exceeds_64_kib_preview_limit",
                }
            )
            valid_index += 1
            truncated = True
            break
        if response_bytes + len(encoded) > MAX_PREVIEW_BYTES:
            truncated = True
            break
        records.append(safe_value)
        response_bytes += len(encoded)
        valid_index += 1

    return {
        "artifact": artifact,
        "offset": offset,
        "returned": len(records),
        "next_offset": offset + len(records),
        "records": records,
        "invalid_lines_seen": invalid_lines,
        "incomplete_lines_seen": incomplete_lines,
        "response_truncated": truncated,
    }


def export_zip(
    run_dir: Path,
    manifest: dict[str, Any],
    artifacts: list[dict[str, Any]],
    max_source_bytes: int,
) -> dict[str, Any]:
    data_dir = run_dir / "data"
    source_bytes = sum(int(artifact["bytes"]) for artifact in artifacts)
    if source_bytes > max_source_bytes:
        raise AdapterError(
            "EXPORT_TOO_LARGE",
            f"Run data is {source_bytes} bytes; the export limit is {max_source_bytes} bytes.",
            remediation="Reduce the collection scope or raise DSH_MEDIACRAWLER_MAX_EXPORT_MIB explicitly.",
        )
    export_dir = run_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_dir.chmod(0o700)
    target = export_dir / f"{manifest['run_id']}.credential-redacted.zip"
    temp = export_dir / f".{target.name}.tmp-{uuid.uuid4().hex}"

    try:
        with temp.open("xb") as raw_archive:
            temp.chmod(0o600)
            with zipfile.ZipFile(
                raw_archive, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                safe_manifest = redact_value(manifest)
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        safe_manifest, ensure_ascii=False, indent=2, sort_keys=True
                    ),
                )
                written_source_bytes = 0
                for artifact in artifacts:
                    path, _ = resolve_artifact(
                        data_dir,
                        artifact["artifact_id"],
                        artifacts=artifacts,
                    )
                    with archive.open(
                        f"data/{artifact['relative_path']}", "w"
                    ) as output:
                        for _, value, error in _jsonl_records(path):
                            if error is not None:
                                continue
                            line = (
                                json.dumps(
                                    redact_value(value),
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ).encode("utf-8")
                                + b"\n"
                            )
                            written_source_bytes += len(line)
                            if written_source_bytes > max_source_bytes:
                                raise AdapterError(
                                    "EXPORT_TOO_LARGE",
                                    "Credential-redacted output exceeded the configured export limit.",
                                )
                            output.write(line)
        temp.replace(target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    target.chmod(0o600)
    hasher = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return {
        "path": str(target),
        "bytes": target.stat().st_size,
        "sha256": hasher.hexdigest(),
        "artifact_count": len(artifacts),
        "source_bytes": source_bytes,
        "credential_redacted": True,
        "pii_anonymized": False,
        "safe_to_share": False,
    }

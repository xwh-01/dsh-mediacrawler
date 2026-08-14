from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from collections.abc import Iterator
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


def discover(data_dir: Path) -> list[dict[str, Any]]:
    if not data_dir.is_dir():
        return []
    artifacts: list[dict[str, Any]] = []
    for path in sorted(data_dir.rglob("*.jsonl")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(data_dir.resolve()).as_posix()
        except ValueError:
            continue
        records = 0
        invalid_lines = 0
        incomplete_lines = 0
        for _, value, error in _jsonl_records(resolved):
            if error == "incomplete_final_line":
                incomplete_lines += 1
            elif error:
                invalid_lines += 1
            elif value is not None:
                records += 1
        collection_mode, record_type = _classify(relative)
        artifacts.append(
            {
                "artifact_id": _artifact_id(relative),
                "relative_path": relative,
                "collection_mode": collection_mode,
                "record_type": record_type,
                "bytes": resolved.stat().st_size,
                "records": records,
                "invalid_lines": invalid_lines,
                "incomplete_lines": incomplete_lines,
            }
        )
    return artifacts


def resolve_artifact(data_dir: Path, artifact_id: str) -> tuple[Path, dict[str, Any]]:
    artifact = next(
        (item for item in discover(data_dir) if item["artifact_id"] == artifact_id),
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
    data_dir: Path, artifact_id: str, offset: int, limit: int
) -> dict[str, Any]:
    path, artifact = resolve_artifact(data_dir, artifact_id)
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


def export_zip(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    data_dir = run_dir / "data"
    artifacts = discover(data_dir)
    export_dir = run_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_dir.chmod(0o700)
    target = export_dir / f"{manifest['run_id']}.sanitized.zip"
    temp = export_dir / f".{target.name}.tmp-{uuid.uuid4().hex}"

    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        safe_manifest = redact_value(manifest)
        archive.writestr(
            "manifest.json",
            json.dumps(safe_manifest, ensure_ascii=False, indent=2, sort_keys=True),
        )
        for artifact in artifacts:
            path, _ = resolve_artifact(data_dir, artifact["artifact_id"])
            with archive.open(f"data/{artifact['relative_path']}", "w") as output:
                for _, value, error in _jsonl_records(path):
                    if error is None:
                        line = json.dumps(
                            redact_value(value),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        output.write(line.encode("utf-8") + b"\n")

    temp.chmod(0o600)
    temp.replace(target)
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
        "sanitized": True,
    }

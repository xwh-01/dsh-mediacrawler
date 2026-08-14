from __future__ import annotations

import json
from pathlib import Path

import pytest

import dsh_mediacrawler.artifacts as artifacts_module
from dsh_mediacrawler.artifacts import ArtifactIndex, discover, export_zip


def test_discover_classifies_upstream_jsonl_names(tmp_path: Path) -> None:
    output = tmp_path / "bili" / "jsonl" / "detail_contents_2026-08-14.jsonl"
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps({"id": "one"}) + "\n", encoding="utf-8")

    artifacts = discover(tmp_path)

    assert artifacts[0]["collection_mode"] == "detail"
    assert artifacts[0]["record_type"] == "contents"


def test_discover_classifies_bilibili_creator_side_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "bili" / "jsonl"
    output_dir.mkdir(parents=True)
    for record_type in ("contacts", "dynamics"):
        (output_dir / f"creator_{record_type}_2026-08-14.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )

    artifacts = discover(tmp_path)

    assert {item["record_type"] for item in artifacts} == {"contacts", "dynamics"}
    assert {item["collection_mode"] for item in artifacts} == {"creator"}


def test_discover_marks_nonstandard_jsonl_names_unknown(tmp_path: Path) -> None:
    output = tmp_path / "custom.jsonl"
    output.write_text("{}\n", encoding="utf-8")

    artifacts = discover(tmp_path)

    assert artifacts[0]["collection_mode"] == "unknown"
    assert artifacts[0]["record_type"] == "unknown"


def test_incremental_index_resumes_from_an_incomplete_final_line(
    tmp_path: Path,
) -> None:
    output = tmp_path / "xhs" / "search_contents_test.jsonl"
    output.parent.mkdir(parents=True)
    output.write_bytes(b'{"id":1}\n{"id":')
    index = ArtifactIndex()

    first = index.discover(tmp_path)[0]
    output.write_bytes(output.read_bytes() + b"2}\n")
    second = index.discover(tmp_path)[0]

    assert first["records"] == 1
    assert first["incomplete_lines"] == 1
    assert second["records"] == 2
    assert second["incomplete_lines"] == 0


def test_incremental_index_resets_after_truncation(tmp_path: Path) -> None:
    output = tmp_path / "xhs" / "search_contents_test.jsonl"
    output.parent.mkdir(parents=True)
    output.write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")
    index = ArtifactIndex()
    assert index.discover(tmp_path)[0]["records"] == 2

    output.write_text("{}\n", encoding="utf-8")

    assert index.discover(tmp_path)[0]["records"] == 1


def test_failed_export_removes_temporary_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    output = data_dir / "xhs" / "search_contents_test.jsonl"
    output.parent.mkdir(parents=True)
    output.write_text("{}\n", encoding="utf-8")
    artifacts = discover(data_dir)

    def fail_redaction(_: object) -> object:
        raise RuntimeError("redaction failed")

    monkeypatch.setattr(artifacts_module, "redact_value", fail_redaction)
    with pytest.raises(RuntimeError, match="redaction failed"):
        export_zip(
            tmp_path,
            {"run_id": "mc_20260814T000000Z_12345678"},
            artifacts,
            1024,
        )

    assert list((tmp_path / "exports").glob("*.tmp-*")) == []

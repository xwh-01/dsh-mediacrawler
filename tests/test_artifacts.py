from __future__ import annotations

import json
from pathlib import Path

from dsh_mediacrawler.artifacts import discover


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

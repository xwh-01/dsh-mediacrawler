from __future__ import annotations

import json
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_python_and_dsh_package_versions_match() -> None:
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == package["version"]


def test_dsh_package_includes_the_adapter_and_skill() -> None:
    package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))

    included = set(package["files"])
    assert {
        ".dsh",
        "pyproject.toml",
        "src/dsh_mediacrawler/*.py",
        "cordis.patch.yml",
    } <= included

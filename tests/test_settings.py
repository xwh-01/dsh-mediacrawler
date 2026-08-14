from __future__ import annotations

from pathlib import Path

import pytest

from dsh_mediacrawler.settings import DEFAULT_MAX_EXPORT_BYTES, Settings


def test_default_export_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DSH_MEDIACRAWLER_MAX_EXPORT_MIB", raising=False)

    settings = Settings.from_env(project_root=tmp_path)

    assert settings.max_export_bytes == DEFAULT_MAX_EXPORT_BYTES


def test_export_limit_from_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DSH_MEDIACRAWLER_MAX_EXPORT_MIB", "64")

    settings = Settings.from_env(project_root=tmp_path)

    assert settings.max_export_bytes == 64 * 1024 * 1024


@pytest.mark.parametrize("value", ["zero", "0", "4097"])
def test_invalid_export_limit_is_rejected(
    value: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DSH_MEDIACRAWLER_MAX_EXPORT_MIB", value)

    with pytest.raises(ValueError, match="DSH_MEDIACRAWLER_MAX_EXPORT_MIB"):
        Settings.from_env(project_root=tmp_path)

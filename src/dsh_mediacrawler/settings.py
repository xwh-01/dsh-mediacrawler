from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Runner:
    command: tuple[str, ...]
    kind: str


@dataclass(frozen=True, slots=True)
class Settings:
    mediacrawler_root: Path | None
    state_dir: Path
    python_executable: Path | None = None

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> Settings:
        project_root = project_root or Path(__file__).resolve().parents[2]
        root_value = os.environ.get("MEDIACRAWLER_ROOT", "").strip()
        root = Path(os.path.expandvars(root_value)).expanduser() if root_value else None

        if root is None:
            candidates = (
                project_root.parent / "MediaCrawler-main" / "MediaCrawler-main",
                project_root.parent / "MediaCrawler-main",
                Path.cwd() / "MediaCrawler-main" / "MediaCrawler-main",
                Path.cwd() / "MediaCrawler-main",
            )
            root = next(
                (item for item in candidates if (item / "main.py").is_file()), None
            )

        state_value = os.environ.get("DSH_MEDIACRAWLER_STATE_DIR", "").strip()
        state_dir = (
            Path(os.path.expandvars(state_value)).expanduser()
            if state_value
            else Path.home() / ".dsh-mediacrawler"
        )
        python_value = os.environ.get("MEDIACRAWLER_PYTHON", "").strip()
        python_executable = (
            Path(os.path.expandvars(python_value)).expanduser()
            if python_value
            else None
        )
        return cls(root, state_dir, python_executable)

    @property
    def main_file(self) -> Path | None:
        return self.mediacrawler_root / "main.py" if self.mediacrawler_root else None

    def runner(self) -> Runner:
        if self.main_file is None:
            raise FileNotFoundError("MEDIACRAWLER_ROOT is not configured")

        if self.python_executable is not None:
            return Runner(
                (str(self.python_executable), str(self.main_file)), "configured-python"
            )

        root = self.mediacrawler_root
        assert root is not None
        venv_candidates = (
            root / ".venv" / "Scripts" / "python.exe",
            root / ".venv" / "bin" / "python",
        )
        for candidate in venv_candidates:
            if candidate.is_file():
                return Runner(
                    (str(candidate), str(self.main_file)), "mediacrawler-venv"
                )

        uv = shutil.which("uv")
        if uv:
            return Runner((uv, "run", "python", str(self.main_file)), "uv")
        return Runner((sys.executable, str(self.main_file)), "current-python")

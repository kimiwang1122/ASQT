from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    database_path: Path
    parquet_dir: Path
    raw_dir: Path
    standard_dir: Path
    qlib_dir: Path
    experiment_dir: Path
    logs_dir: Path
    frontend_dir: Path

    def layout(self) -> dict[str, str]:
        return {
            "data_dir": str(self.data_dir),
            "database_path": str(self.database_path),
            "raw_data": str(self.raw_dir),
            "standard_data": str(self.standard_dir),
            "parquet": str(self.parquet_dir),
            "qlib_data": str(self.qlib_dir),
            "experiment": str(self.experiment_dir),
            "logs": str(self.logs_dir),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.environ.get("ASQT_DATA_DIR", project_root / "data")).expanduser().resolve()
    return Settings(
        project_root=project_root,
        data_dir=data_dir,
        database_path=data_dir / "asqt.sqlite3",
        parquet_dir=data_dir / "parquet",
        raw_dir=data_dir / "raw_data",
        standard_dir=data_dir / "standard_data",
        qlib_dir=data_dir / "qlib_data",
        experiment_dir=data_dir / "experiment",
        logs_dir=data_dir / "logs",
        frontend_dir=project_root / "frontend",
    )


def ensure_runtime_dirs(settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    for path in (
        settings.data_dir,
        settings.parquet_dir,
        settings.raw_dir,
        settings.standard_dir,
        settings.qlib_dir,
        settings.experiment_dir,
        settings.logs_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return settings

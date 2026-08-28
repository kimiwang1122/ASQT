from __future__ import annotations

from pathlib import Path

import pandas as pd

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.contracts import MARKET_DAILY_COLUMNS


def market_daily_path(settings: Settings | None = None) -> Path:
    settings = ensure_runtime_dirs(settings or get_settings())
    # Keep parquet under standard_data for tech-design layout clarity.
    path = settings.standard_dir / "market_daily.parquet"
    legacy = settings.parquet_dir / "market_daily.parquet"
    if not path.exists() and legacy.exists():
        return legacy
    return path


def write_market_daily(records: list[dict], settings: Settings | None = None) -> Path:
    settings = ensure_runtime_dirs(settings or get_settings())
    path = settings.standard_dir / "market_daily.parquet"
    frame = pd.DataFrame(records, columns=list(MARKET_DAILY_COLUMNS))
    frame.to_parquet(path, index=False)
    return path


def read_market_daily(
    symbol: str | None = None,
    start: str | None = None,
    end: str | None = None,
    settings: Settings | None = None,
) -> list[dict]:
    path = market_daily_path(settings)
    if not path.exists():
        return []

    frame = pd.read_parquet(path)
    missing = [column for column in MARKET_DAILY_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"market_daily parquet missing columns: {missing}")
    if symbol:
        frame = frame[frame["symbol"] == symbol]
    if start:
        frame = frame[frame["trade_date"] >= start]
    if end:
        frame = frame[frame["trade_date"] <= end]
    frame = frame.sort_values(["trade_date", "symbol"])
    return frame.to_dict(orient="records")

"""Registered record schemas with shared parquet upsert / query."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.contracts import FUNDAMENTAL_SNAPSHOT_COLUMNS, MARKET_DAILY_COLUMNS, MARKET_EVENT_COLUMNS

RECORD_SCHEMAS: dict[str, dict[str, Any]] = {
    "market_daily": {
        "name": "market_daily",
        "columns": MARKET_DAILY_COLUMNS,
        "pk": ("symbol", "trade_date"),
    },
    "market_event": {
        "name": "market_event",
        "columns": MARKET_EVENT_COLUMNS,
        "pk": ("event_id",),
    },
    "fundamental_snapshot": {
        "name": "fundamental_snapshot",
        "columns": FUNDAMENTAL_SNAPSHOT_COLUMNS,
        "pk": ("symbol", "report_period", "metric", "source", "version"),
    },
}


class UnknownRecordSchema(KeyError):
    """Raised when schema is not registered in RECORD_SCHEMAS."""


def get_record_schema(schema: str) -> dict[str, Any]:
    key = str(schema or "").strip()
    if key not in RECORD_SCHEMAS:
        raise UnknownRecordSchema(key)
    return RECORD_SCHEMAS[key]


def record_parquet_path(schema: str, settings: Settings | None = None) -> Path:
    """Parquet under data/standard_data/{schema}.parquet (legacy market_daily fallback)."""
    get_record_schema(schema)
    settings = ensure_runtime_dirs(settings or get_settings())
    path = settings.standard_dir / f"{schema}.parquet"
    if schema == "market_daily":
        legacy = settings.parquet_dir / "market_daily.parquet"
        if not path.exists() and legacy.exists():
            return legacy
    return path


def upsert_records(
    schema: str,
    rows: list[dict],
    settings: Settings | None = None,
) -> Path:
    """Merge by schema PK; leave untouched keys alone. Empty rows are a no-op."""
    spec = get_record_schema(schema)
    settings = ensure_runtime_dirs(settings or get_settings())
    columns = list(spec["columns"])
    pk = list(spec["pk"])
    path = settings.standard_dir / f"{schema}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    incoming = pd.DataFrame(rows or [], columns=columns)
    if incoming.empty:
        return path
    if path.exists():
        existing = pd.read_parquet(path)
        for column in columns:
            if column not in existing.columns:
                existing[column] = None
        existing = existing[columns]
        incoming_keys = incoming[pk].drop_duplicates()
        existing = existing.merge(incoming_keys, on=pk, how="left", indicator=True)
        existing = existing[existing["_merge"] == "left_only"].drop(columns=["_merge"])
        frame = pd.concat([existing, incoming], ignore_index=True)
    else:
        frame = incoming
    frame = frame.drop_duplicates(subset=pk, keep="last")
    sort_cols = [col for col in ("trade_date", "event_date", "symbol", *pk) if col in frame.columns]
    # Preserve stable order: date then symbol when present, else PK order.
    ordered: list[str] = []
    for col in sort_cols:
        if col not in ordered:
            ordered.append(col)
    if ordered:
        frame = frame.sort_values(ordered)
    frame.to_parquet(path, index=False)
    return path


def query_records(
    schema: str,
    *,
    settings: Settings | None = None,
    limit: int | None = None,
    newest_first: bool = False,
    **filters: Any,
) -> list[dict]:
    """Read parquet rows with optional equality / date-range filters."""
    spec = get_record_schema(schema)
    columns = list(spec["columns"])
    path = record_parquet_path(schema, settings)
    if not path.exists():
        return []

    frame = pd.read_parquet(path)
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{schema} parquet missing columns: {missing}")
    frame = frame[columns]

    start = filters.pop("start", None)
    end = filters.pop("end", None)
    date_col = None
    if "trade_date" in frame.columns:
        date_col = "trade_date"
    elif "event_date" in frame.columns:
        date_col = "event_date"
    elif "ann_date" in frame.columns:
        date_col = "ann_date"
    if start is not None and date_col is not None:
        frame = frame[frame[date_col] >= start]
    if end is not None and date_col is not None:
        frame = frame[frame[date_col] <= end]

    for key, value in filters.items():
        if value is None:
            continue
        if key not in frame.columns:
            raise ValueError(f"unknown filter column for {schema}: {key}")
        frame = frame[frame[key] == value]

    if date_col is not None and "symbol" in frame.columns:
        ascending = [not newest_first, True]
        frame = frame.sort_values([date_col, "symbol"], ascending=ascending)
    elif date_col is not None:
        frame = frame.sort_values([date_col], ascending=[not newest_first])
    else:
        pk = list(spec["pk"])
        frame = frame.sort_values(pk)

    if limit is not None:
        frame = frame.head(int(limit))
    return frame.to_dict(orient="records")

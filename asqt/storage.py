from __future__ import annotations

from pathlib import Path

import pandas as pd

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.contracts import MARKET_DAILY_COLUMNS
from asqt.records import query_records, record_parquet_path, upsert_records
from asqt.symbols import infer_instrument_type, split_symbol


def market_daily_span(settings: Settings | None = None) -> tuple[str | None, str | None]:
    path = market_daily_path(settings)
    if not path.exists():
        return None, None
    frame = pd.read_parquet(path, columns=["trade_date"])
    if frame.empty:
        return None, None
    return str(frame["trade_date"].min()), str(frame["trade_date"].max())


def market_daily_path(settings: Settings | None = None) -> Path:
    # Keep parquet under standard_data for tech-design layout clarity.
    return record_parquet_path("market_daily", settings)


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
    *,
    limit: int | None = None,
    newest_first: bool = False,
) -> list[dict]:
    return query_records(
        "market_daily",
        symbol=symbol,
        start=start,
        end=end,
        settings=settings,
        limit=limit,
        newest_first=newest_first,
    )


def _volume_change(current, previous) -> tuple[float | None, str]:
    try:
        cur = float(current)
        prev = float(previous)
    except (TypeError, ValueError):
        return None, "na"
    if prev == 0 or cur != cur or prev != prev:
        return None, "na"
    ratio = (cur - prev) / prev
    if ratio > 0:
        return ratio, "up"
    if ratio < 0:
        return ratio, "down"
    return 0.0, "flat"


def _json_num(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_market_snapshot(
    *,
    trade_date: str | None = None,
    exchange: str | None = None,
    instrument_type: str | None = None,
    code: str | None = None,
    limit: int = 50,
    sort: str = "volume",
    order: str = "desc",
    names: dict[str, str] | None = None,
    settings: Settings | None = None,
) -> dict:
    """Latest-date (or chosen date) Top-N with DoD / YoY volume marks."""
    path = market_daily_path(settings)
    empty = {
        "trade_date": trade_date,
        "min_trade_date": None,
        "max_trade_date": None,
        "matched": 0,
        "returned": 0,
        "limit": limit,
        "sort": sort,
        "order": order,
        "items": [],
    }
    if not path.exists():
        return empty

    frame = pd.read_parquet(path)
    if frame.empty or "trade_date" not in frame.columns:
        return empty

    dates = sorted(frame["trade_date"].astype(str).unique())
    asof = trade_date or dates[-1]
    if asof not in dates:
        return {
            **empty,
            "trade_date": asof,
            "min_trade_date": dates[0],
            "max_trade_date": dates[-1],
        }

    snap = frame[frame["trade_date"].astype(str) == asof].copy()
    parsed = snap["symbol"].map(split_symbol)
    snap["code"] = parsed.map(lambda item: item[0])
    snap["exchange"] = parsed.map(lambda item: item[1])
    snap["instrument_type"] = snap["symbol"].map(infer_instrument_type)
    name_map = names or {}
    snap["name"] = snap["symbol"].map(lambda symbol: name_map.get(str(symbol), ""))

    if exchange:
        snap = snap[snap["exchange"] == exchange.upper()]
    if instrument_type:
        snap = snap[snap["instrument_type"] == instrument_type]
    needle = (code or "").strip().upper()
    if needle:
        code_s = snap["code"].astype(str).str.upper()
        symbol_s = snap["symbol"].astype(str).str.upper()
        name_s = snap["name"].astype(str).str.upper()
        snap = snap[
            code_s.str.contains(needle, regex=False)
            | symbol_s.str.contains(needle, regex=False)
            | name_s.str.contains(needle, regex=False)
        ]

    prev_vol = (
        frame[frame["trade_date"].astype(str) < asof]
        .sort_values("trade_date")
        .groupby("symbol", as_index=False)
        .tail(1)[["symbol", "volume"]]
        .rename(columns={"volume": "prev_volume"})
    )
    yoy_cut = (pd.Timestamp(asof) - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    yoy_vol = (
        frame[frame["trade_date"].astype(str) <= yoy_cut]
        .sort_values("trade_date")
        .groupby("symbol", as_index=False)
        .tail(1)[["symbol", "volume"]]
        .rename(columns={"volume": "yoy_volume"})
    )
    snap = snap.merge(prev_vol, on="symbol", how="left").merge(yoy_vol, on="symbol", how="left")
    dod = [
        _volume_change(row.get("volume"), row.get("prev_volume"))
        for row in snap.to_dict(orient="records")
    ]
    yoy = [
        _volume_change(row.get("volume"), row.get("yoy_volume"))
        for row in snap.to_dict(orient="records")
    ]
    snap = snap.copy()
    snap["volume_dod"] = [item[0] for item in dod]
    snap["volume_dod_dir"] = [item[1] for item in dod]
    snap["volume_yoy"] = [item[0] for item in yoy]
    snap["volume_yoy_dir"] = [item[1] for item in yoy]

    sort_key = {"volume": "volume", "dod": "volume_dod", "yoy": "volume_yoy"}.get(sort, "volume")
    ascending = (order or "desc").lower() == "asc"
    snap = snap.sort_values([sort_key, "symbol"], ascending=[ascending, True], na_position="last")
    matched = int(len(snap))
    snap = snap.head(int(limit))

    items = []
    for row in snap.to_dict(orient="records"):
        items.append(
            {
                "symbol": row["symbol"],
                "code": row["code"],
                "exchange": row["exchange"],
                "instrument_type": row["instrument_type"],
                "name": row.get("name") or None,
                "trade_date": str(row["trade_date"]),
                "open": _json_num(row.get("open")),
                "high": _json_num(row.get("high")),
                "low": _json_num(row.get("low")),
                "close": _json_num(row.get("close")),
                "volume": _json_num(row.get("volume")),
                "amount": _json_num(row.get("amount")),
                "source": row.get("source"),
                "volume_dod": row.get("volume_dod"),
                "volume_dod_dir": row.get("volume_dod_dir"),
                "volume_yoy": row.get("volume_yoy"),
                "volume_yoy_dir": row.get("volume_yoy_dir"),
            }
        )
    return {
        "trade_date": asof,
        "min_trade_date": dates[0],
        "max_trade_date": dates[-1],
        "matched": matched,
        "returned": len(items),
        "limit": int(limit),
        "sort": sort if sort in {"volume", "dod", "yoy"} else "volume",
        "order": "asc" if ascending else "desc",
        "items": items,
    }


def upsert_market_daily(records: list[dict], settings: Settings | None = None) -> Path:
    """Merge by (symbol, trade_date); keep other symbols and dates untouched."""
    return upsert_records("market_daily", records, settings=settings)

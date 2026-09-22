"""Factor pipeline: market rows → data_df → factor_df (optional parquet / SQLite)."""

from __future__ import annotations

from hashlib import sha1
import json
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd

from asqt import factors as F
from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import executemany
from asqt.pit import series_asof as _pit_series_asof
from asqt.symbols import infer_instrument_type

FACTOR_VALUE_COLUMNS = (
    "trade_date",
    "symbol",
    "factor_name",
    "value",
    "model_version",
    "source_run_id",
    "params_hash",
)

_BUILTIN: dict[str, Callable[..., float | None]] = {
    "momentum": lambda hist, **kw: F.momentum(hist, int(kw["lookback"])),
    "ma_gap": lambda hist, **kw: F.ma_gap(hist, int(kw["window"])),
    "volatility": lambda hist, **kw: F.volatility(hist, int(kw["window"])),
    "reversal": lambda hist, **kw: F.reversal(hist, int(kw["lookback"])),
    "volume_z": lambda hist, **kw: F.volume_z(hist, int(kw["window"])),
    "momentum_skip_month": lambda hist, **kw: F.momentum_skip_month(
        hist, int(kw["lookback"]), skip=int(kw.get("skip", 21))
    ),
    "risk_adjusted_momentum": lambda hist, **kw: F.risk_adjusted_momentum(
        hist, lookback=int(kw["lookback"]), vol_window=int(kw["vol_window"])
    ),
    "rule_2560": lambda hist, **kw: F.rule_2560(
        hist,
        ma_fast=int(kw.get("ma_fast", 5)),
        ma_slow=int(kw.get("ma_slow", 25)),
        vol_fast=int(kw.get("vol_fast", 5)),
        vol_slow=int(kw.get("vol_slow", 60)),
        pullback_band=float(kw.get("pullback_band", 0.02)),
    ),
    "rule_yin_arb": lambda hist, **kw: F.rule_yin_arb(
        hist,
        ma_fast=int(kw.get("ma_fast", 10)),
        ma_slow=int(kw.get("ma_slow", 20)),
        burst_lookback=int(kw.get("burst_lookback", 5)),
        burst_ratio=float(kw.get("burst_ratio", 1.8)),
        pullback_band=float(kw.get("pullback_band", 0.025)),
        min_body=float(kw.get("min_body", 0.005)),
        ma_gap_max=float(kw.get("ma_gap_max", 0.03)),
    ),
}


def params_hash(payload: dict[str, Any] | None) -> str:
    """Stable short hash for factor params (avoids same-name window collisions)."""
    if not payload:
        return ""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha1(canonical.encode()).hexdigest()[:12]


def build_data_frame(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group market_daily rows by symbol, sorted by trade_date (asof-ready)."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["symbol"]), []).append(row)
    for symbol in grouped:
        grouped[symbol] = sorted(grouped[symbol], key=lambda item: str(item["trade_date"]))
    return grouped


def series_asof(series: list[dict[str, Any]], asof: str) -> list[dict[str, Any]]:
    """Return bars with trade_date <= asof (PIT; binary search on sorted series)."""
    return _pit_series_asof(series, asof, date_key="trade_date")


def _eval_spec(hist: list[dict[str, Any]], spec: dict[str, Any]) -> float | None:
    compute = spec.get("compute")
    if callable(compute):
        return compute(hist)
    kind = str(spec.get("kind") or "")
    fn = _BUILTIN.get(kind)
    if fn is None:
        raise ValueError(f"unknown factor kind: {kind}")
    return fn(hist, **dict(spec.get("kwargs") or {}))


def _hash_for_spec(spec: dict[str, Any]) -> str:
    if "params_hash" in spec and spec["params_hash"] is not None:
        return str(spec["params_hash"])
    payload = spec.get("params_for_hash")
    if payload is None:
        payload = {"kind": spec.get("kind"), **dict(spec.get("kwargs") or {})}
    return params_hash(payload if isinstance(payload, dict) else {"v": payload})


def compute_factor_frame(
    data: dict[str, list[dict[str, Any]]],
    factor_specs: Sequence[dict[str, Any]],
    *,
    asof: str | None = None,
    dates: Sequence[str] | None = None,
    source_run_id: str = "",
    model_version: str = "p2.4",
    on_progress=None,
) -> list[dict[str, Any]]:
    """Compute factor rows for one asof or a list of dates (no look-ahead)."""
    if asof is None and dates is None:
        raise ValueError("asof or dates required")
    target_dates = [asof] if asof is not None else list(dates or [])
    out: list[dict[str, Any]] = []
    for spec in factor_specs:
        name = str(spec["name"])
        want = spec.get("instrument_type")
        phash = _hash_for_spec(spec)
        eligible = [
            (symbol, series)
            for symbol, series in data.items()
            if not want or infer_instrument_type(symbol) == want
        ]
        total_sym = len(eligible)
        for index, (symbol, series) in enumerate(eligible, 1):
            if on_progress and (index == 1 or index == total_sym or index % 5 == 0):
                on_progress({"done": index, "total": total_sym, "symbol": symbol, "factor": name})
            for trade_date in target_dates:
                hist = series_asof(series, trade_date)
                value = _eval_spec(hist, spec)
                if value is None:
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if number != number:  # NaN
                    continue
                out.append(
                    {
                        "trade_date": trade_date,
                        "symbol": symbol,
                        "factor_name": name,
                        "value": round(number, 10),
                        "model_version": model_version,
                        "source_run_id": source_run_id,
                        "params_hash": phash,
                    }
                )
    return out


def factor_values_path(settings: Settings | None = None) -> Path:
    settings = ensure_runtime_dirs(settings or get_settings())
    return settings.standard_dir / "factor_values.parquet"


def persist_factor_values(
    rows: list[dict[str, Any]],
    settings: Settings | None = None,
) -> Path:
    """Upsert factor rows into data/standard_data/factor_values.parquet."""
    settings = ensure_runtime_dirs(settings or get_settings())
    path = factor_values_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(FACTOR_VALUE_COLUMNS)
    pk = ["trade_date", "symbol", "factor_name", "params_hash"]
    incoming = pd.DataFrame(rows or [], columns=columns)
    if incoming.empty:
        return path
    if path.exists():
        existing = pd.read_parquet(path)
        for column in columns:
            if column not in existing.columns:
                existing[column] = "" if column == "params_hash" else None
        existing = existing[columns]
        keys = incoming[pk].drop_duplicates()
        existing = existing.merge(keys, on=pk, how="left", indicator=True)
        existing = existing[existing["_merge"] == "left_only"].drop(columns=["_merge"])
        frame = pd.concat([existing, incoming], ignore_index=True)
    else:
        frame = incoming
    frame = frame.drop_duplicates(subset=pk, keep="last")
    frame = frame.sort_values(["trade_date", "symbol", "factor_name", "params_hash"])
    frame.to_parquet(path, index=False)
    return path


def write_factor_signals(
    rows: list[dict[str, Any]],
    settings: Settings | None = None,
) -> int:
    """INSERT OR REPLACE into factor_signal (PK includes params_hash)."""
    if not rows:
        return 0
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row["trade_date"]),
            str(row["symbol"]),
            str(row["factor_name"]),
            str(row.get("params_hash") or ""),
        )
        unique[key] = row
    payload = list(unique.values())
    executemany(
        """
        INSERT OR REPLACE INTO factor_signal
            (trade_date, symbol, factor_name, value, model_version, source_run_id, params_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["trade_date"],
                row["symbol"],
                row["factor_name"],
                row["value"],
                row.get("model_version"),
                row.get("source_run_id"),
                str(row.get("params_hash") or ""),
            )
            for row in payload
        ],
        settings=settings,
    )
    return len(payload)


def read_factor_values(
    *,
    trade_date: str | None = None,
    factor_name: str | None = None,
    symbol: str | None = None,
    settings: Settings | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    path = factor_values_path(settings)
    if not path.exists():
        return []
    frame = pd.read_parquet(path)
    for column in FACTOR_VALUE_COLUMNS:
        if column not in frame.columns:
            frame[column] = "" if column == "params_hash" else None
    if trade_date is not None:
        frame = frame[frame["trade_date"] == trade_date]
    if factor_name is not None:
        frame = frame[frame["factor_name"] == factor_name]
    if symbol is not None:
        frame = frame[frame["symbol"] == symbol]
    frame = frame.sort_values(["trade_date", "symbol", "factor_name"], ascending=[False, True, True])
    if limit is not None:
        frame = frame.head(int(limit))
    return frame[list(FACTOR_VALUE_COLUMNS)].to_dict(orient="records")

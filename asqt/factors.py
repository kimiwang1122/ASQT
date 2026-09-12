"""Price/volume factors from market_daily bars (adj_close based)."""

from __future__ import annotations

import math
from typing import Any, Sequence


def adj_close(row: dict[str, Any]) -> float:
    return float(row["close"]) * float(row["adj_factor"])


def closes_asof(hist: Sequence[dict[str, Any]]) -> list[float]:
    return [adj_close(item) for item in hist]


def momentum(hist: Sequence[dict[str, Any]], lookback: int) -> float | None:
    """Return over ``lookback`` sessions: adj_close[t]/adj_close[t-L]-1."""
    if lookback < 1 or len(hist) < lookback + 1:
        return None
    start = adj_close(hist[-(lookback + 1)])
    end = adj_close(hist[-1])
    if start <= 0:
        return None
    return end / start - 1.0


def ma_gap(hist: Sequence[dict[str, Any]], window: int) -> float | None:
    """adj_close / SMA(window) - 1."""
    if window < 1 or len(hist) < window:
        return None
    closes = closes_asof(hist[-window:])
    sma = sum(closes) / window
    if sma <= 0:
        return None
    return closes[-1] / sma - 1.0


def volatility(hist: Sequence[dict[str, Any]], window: int, *, annualize: bool = False) -> float | None:
    """Stdev of daily adj returns over ``window`` days (needs window+1 bars)."""
    if window < 2 or len(hist) < window + 1:
        return None
    closes = closes_asof(hist[-(window + 1) :])
    rets: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev <= 0:
            return None
        rets.append(closes[i] / prev - 1.0)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((item - mean) ** 2 for item in rets) / (len(rets) - 1)
    vol = math.sqrt(var)
    if annualize:
        vol *= math.sqrt(252)
    return vol


def reversal(hist: Sequence[dict[str, Any]], window: int) -> float | None:
    """Short-term reversal score: negative of recent return."""
    mom = momentum(hist, window)
    if mom is None:
        return None
    return -mom


def volume_z(hist: Sequence[dict[str, Any]], window: int) -> float | None:
    """Volume z-score vs trailing mean/stdev over ``window`` (including today)."""
    if window < 2 or len(hist) < window:
        return None
    vols = [float(item.get("volume") or 0) for item in hist[-window:]]
    mean = sum(vols) / len(vols)
    var = sum((item - mean) ** 2 for item in vols) / (len(vols) - 1)
    std = math.sqrt(var)
    if std <= 1e-12:
        return 0.0
    return (vols[-1] - mean) / std


def risk_adjusted_momentum(
    hist: Sequence[dict[str, Any]],
    *,
    lookback: int,
    vol_window: int,
) -> float | None:
    """momentum / volatility; None if undefined."""
    mom = momentum(hist, lookback)
    vol = volatility(hist, vol_window)
    if mom is None or vol is None or vol <= 1e-12:
        return None
    return mom / vol

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


def momentum_skip_month(
    hist: Sequence[dict[str, Any]],
    lookback: int,
    skip: int = 20,
) -> float | None:
    """Return from t-lookback to t-skip (classic 12-1 when lookback=252, skip=21)."""
    if lookback < 1 or skip < 0 or lookback <= skip:
        return None
    if len(hist) < lookback + 1:
        return None
    start = adj_close(hist[-(lookback + 1)])
    end = adj_close(hist[-(skip + 1)])
    if start <= 0:
        return None
    return end / start - 1.0


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


def _sma(values: Sequence[float], window: int, *, end: int) -> float:
    start = end - window
    return sum(values[start:end]) / window


def rule_2560_timeline(
    hist: Sequence[dict[str, Any]],
    *,
    ma_fast: int = 5,
    ma_slow: int = 25,
    vol_fast: int = 5,
    vol_slow: int = 60,
    pullback_band: float = 0.02,
) -> list[tuple[str, float] | None]:
    """Per-bar ("entry"|"hold", score) or None; O(n) rolling windows."""
    n = len(hist)
    out: list[tuple[str, float] | None] = [None] * n
    if ma_fast < 1 or ma_slow < ma_fast or vol_fast < 1 or vol_slow < vol_fast:
        return out
    need = max(ma_slow, vol_slow) + 1
    if n < need:
        return out
    closes = closes_asof(hist)
    vols = [float(item.get("volume") or 0) for item in hist]
    sum_s = sum(closes[need - ma_slow : need])
    sum_f = sum(closes[need - ma_fast : need])
    sum_vs = sum(vols[need - vol_slow : need])
    sum_vf = sum(vols[need - vol_fast : need])
    held = False
    for end in range(need, n + 1):
        if end > need:
            sum_s += closes[end - 1] - closes[end - 1 - ma_slow]
            sum_f += closes[end - 1] - closes[end - 1 - ma_fast]
            sum_vs += vols[end - 1] - vols[end - 1 - vol_slow]
            sum_vf += vols[end - 1] - vols[end - 1 - vol_fast]
        ma_s_now = sum_s / ma_slow
        ma_s_prev = (sum_s - closes[end - 1] + closes[end - 1 - ma_slow]) / ma_slow
        close = closes[end - 1]
        rising = ma_s_now > 0 and ma_s_now > ma_s_prev
        phase: str | None = None
        score: float | None = None
        if held and (not rising or close < ma_s_now):
            held = False
        if not held:
            if rising:
                v_fast = sum_vf / vol_fast
                v_slow = sum_vs / vol_slow
                if v_slow > 0 and v_fast > v_slow:
                    ma_f_now = sum_f / ma_fast
                    ma_f_prev = (sum_f - closes[end - 1] + closes[end - 1 - ma_fast]) / ma_fast
                    golden = ma_f_prev <= ma_s_prev and ma_f_now > ma_s_now
                    pullback = (
                        abs(close / ma_s_now - 1.0) <= pullback_band
                        and max(closes[end - ma_fast : end]) >= ma_s_now
                    )
                    if golden or pullback:
                        held = True
                        phase = "entry"
                        score = v_fast / v_slow
        else:
            phase = "hold"
            score = close / ma_s_now if ma_s_now > 0 else None
        out[end - 1] = (phase, score) if held and phase is not None and score is not None else None
    return out


def rule_2560_state(
    hist: Sequence[dict[str, Any]],
    *,
    ma_fast: int = 5,
    ma_slow: int = 25,
    vol_fast: int = 5,
    vol_slow: int = 60,
    pullback_band: float = 0.02,
) -> tuple[str, float] | None:
    """Return ("entry"|"hold", score) if in a 2560 trade as of last bar.

    Entry (needs VOL5 > VOL60): MA25 rising and (MA5 golden-cross MA25, or close
    in the MA25 pullback band). Hold after entry while close stays on/above MA25
    and MA25 keeps rising. Exit when close falls below MA25 or MA25 stops rising.
    """
    timeline = rule_2560_timeline(
        hist,
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        vol_fast=vol_fast,
        vol_slow=vol_slow,
        pullback_band=pullback_band,
    )
    return timeline[-1] if timeline else None


def rule_2560(
    hist: Sequence[dict[str, Any]],
    *,
    ma_fast: int = 5,
    ma_slow: int = 25,
    vol_fast: int = 5,
    vol_slow: int = 60,
    pullback_band: float = 0.02,
) -> float | None:
    """2560 score while in a trade, else None. See rule_2560_state."""
    state = rule_2560_state(
        hist,
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        vol_fast=vol_fast,
        vol_slow=vol_slow,
        pullback_band=pullback_band,
    )
    return None if state is None else state[1]


def adj_open(row: dict[str, Any]) -> float:
    return float(row["open"]) * float(row["adj_factor"])


def rule_yin_arb_timeline(
    hist: Sequence[dict[str, Any]],
    *,
    ma_fast: int = 10,
    ma_slow: int = 20,
    burst_lookback: int = 5,
    burst_ratio: float = 1.8,
    pullback_band: float = 0.025,
    min_body: float = 0.005,
    ma_gap_max: float = 0.03,
) -> list[float | None]:
    """Per-bar yin-arb score or None; rolling MA so paper grid is O(n) per symbol."""
    n = len(hist)
    out: list[float | None] = [None] * n
    need = max(ma_slow, burst_lookback) + 2
    if ma_fast < 1 or ma_slow < ma_fast or burst_lookback < 2 or n < need:
        return out
    try:
        opens = [adj_open(item) for item in hist]
    except (KeyError, TypeError, ValueError):
        return out
    closes = closes_asof(hist)
    vols = [float(item.get("volume") or 0) for item in hist]
    sum_f = sum(closes[need - ma_fast : need])
    sum_s = sum(closes[need - ma_slow : need])
    for end in range(need, n + 1):
        if end > need:
            sum_f += closes[end - 1] - closes[end - 1 - ma_fast]
            sum_s += closes[end - 1] - closes[end - 1 - ma_slow]
        ma_f = sum_f / ma_fast
        ma_s = sum_s / ma_slow
        ma_f_prev = (sum_f - closes[end - 1] + closes[end - 1 - ma_fast]) / ma_fast
        if ma_f <= 0 or ma_s <= 0 or ma_f <= ma_f_prev:
            continue
        if abs(ma_f / ma_s - 1.0) >= ma_gap_max:
            continue
        close = closes[end - 1]
        prev = closes[end - 2]
        opn = opens[end - 1]
        if opn <= 0 or close <= 0 or close >= opn or close <= prev:
            continue
        if (opn - close) / opn < min_body:
            continue
        if abs(close / ma_f - 1.0) > pullback_band:
            continue
        start = end - burst_lookback
        burst = 0.0
        for j in range(start, end):
            prev_v = vols[j - 1]
            if prev_v > 0:
                burst = max(burst, vols[j] / prev_v)
        if burst < burst_ratio:
            continue
        prior_peak = max(vols[start : end - 1])
        if prior_peak <= 0 or vols[end - 1] >= prior_peak:
            continue
        tightness = 1.0 - abs(close / ma_f - 1.0) / pullback_band
        out[end - 1] = burst * max(0.0, tightness)
    return out


def rule_yin_arb(
    hist: Sequence[dict[str, Any]],
    *,
    ma_fast: int = 10,
    ma_slow: int = 20,
    burst_lookback: int = 5,
    burst_ratio: float = 1.8,
    pullback_band: float = 0.025,
    min_body: float = 0.005,
    ma_gap_max: float = 0.03,
) -> float | None:
    """阴线套利：近 N 日爆量后缩量回踩 MA10，当日阴线且仍收涨。

    绿柱按阴线（收盘<开盘）计；跌幅看实体 (open-close)/open。收盘>昨收 与
    「相对昨收下跌」互斥，故不采用后者。日 K 无 14:50/次日 10:00，信号只打分。
    """
    timeline = rule_yin_arb_timeline(
        hist,
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        burst_lookback=burst_lookback,
        burst_ratio=burst_ratio,
        pullback_band=pullback_band,
        min_body=min_body,
        ma_gap_max=ma_gap_max,
    )
    return timeline[-1] if timeline else None

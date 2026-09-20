"""Objective P/L attribution helpers for lab experiment reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from asqt.strategies import adj_close


def _weekday_name(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%A")


def _month_key(iso: str) -> str:
    return iso[:7]


def _quarter_key(iso: str) -> str:
    y, m = int(iso[:4]), int(iso[5:7])
    return f"{y}-Q{(m - 1) // 3 + 1}"


def label_regimes(
    dates: list[str],
    closes: list[float],
    *,
    ma_fast: int = 20,
    ma_slow: int = 60,
) -> list[str]:
    """Tag each day as trend_up / range / trend_down from MA slope + vol percentile."""
    n = len(dates)
    if n != len(closes) or n == 0:
        return []
    out: list[str] = []
    rets: list[float] = [0.0]
    for i in range(1, n):
        prev = closes[i - 1]
        rets.append((closes[i] / prev - 1.0) if prev else 0.0)
    for i in range(n):
        if i < ma_slow:
            out.append("range")
            continue
        window = closes[i - ma_slow + 1 : i + 1]
        fast = sum(closes[i - ma_fast + 1 : i + 1]) / ma_fast
        slow = sum(window) / ma_slow
        vol_w = rets[max(0, i - 19) : i + 1]
        vol = (sum(r * r for r in vol_w) / max(1, len(vol_w))) ** 0.5
        hist = []
        for j in range(ma_slow, i + 1):
            vw = rets[max(0, j - 19) : j + 1]
            hist.append((sum(r * r for r in vw) / max(1, len(vw))) ** 0.5)
        hist_sorted = sorted(hist)
        rank = hist_sorted.index(min(hist_sorted, key=lambda x: abs(x - vol))) / max(1, len(hist_sorted) - 1)
        gap = (fast / slow - 1.0) if slow else 0.0
        if gap > 0.005 and rank < 0.85:
            out.append("trend_up")
        elif gap < -0.005:
            out.append("trend_down")
        else:
            out.append("range")
    return out


def benchmark_series(
    rows: list[dict[str, Any]],
    dates: list[str],
    *,
    symbol: str = "510300.SH",
) -> tuple[list[float], list[float]]:
    """Return (close levels, nav starting at 1.0) for benchmark symbol on dates."""
    by_date = {
        str(r["trade_date"]): adj_close(r)
        for r in rows
        if str(r.get("symbol")) == symbol
    }
    closes: list[float] = []
    for d in dates:
        closes.append(float(by_date.get(d) or (closes[-1] if closes else 0.0)))
    if not closes or closes[0] <= 0:
        return closes, [1.0] * len(closes)
    base = closes[0]
    nav = [c / base for c in closes]
    return closes, nav


def calendar_buckets(timeline: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Compound daily_return into weekday / month / quarter buckets."""
    buckets: dict[str, dict[str, float]] = {
        "weekday": defaultdict(lambda: 1.0),
        "month": defaultdict(lambda: 1.0),
        "quarter": defaultdict(lambda: 1.0),
    }
    for row in timeline:
        day = str(row["trade_date"])
        r = float(row.get("daily_return") or 0.0)
        buckets["weekday"][_weekday_name(day)] *= 1.0 + r
        buckets["month"][_month_key(day)] *= 1.0 + r
        buckets["quarter"][_quarter_key(day)] *= 1.0 + r
    return {
        kind: {k: round(v - 1.0, 6) for k, v in sorted(vals.items())}
        for kind, vals in buckets.items()
    }


def regime_stats(
    timeline: list[dict[str, Any]],
    regimes: list[str],
) -> dict[str, dict[str, float | int]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for row, reg in zip(timeline, regimes, strict=False):
        groups[reg].append(float(row.get("daily_return") or 0.0))
    out: dict[str, dict[str, float | int]] = {}
    for reg, rets in groups.items():
        if not rets:
            continue
        compounded = 1.0
        for r in rets:
            compounded *= 1.0 + r
        mean = sum(rets) / len(rets)
        out[reg] = {
            "days": len(rets),
            "mean_daily": round(mean, 8),
            "total_return": round(compounded - 1.0, 6),
        }
    return out


def max_drawdown_slice(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    if not timeline:
        return {}
    peak_i = 0
    peak = float(timeline[0]["total_asset"])
    worst = 0.0
    trough_i = 0
    start_i = 0
    for i, row in enumerate(timeline):
        asset = float(row["total_asset"])
        if asset >= peak:
            peak = asset
            peak_i = i
        dd = asset / peak - 1.0 if peak else 0.0
        if dd < worst:
            worst = dd
            trough_i = i
            start_i = peak_i
    return {
        "max_drawdown": round(worst, 6),
        "peak_date": timeline[start_i]["trade_date"],
        "trough_date": timeline[trough_i]["trade_date"],
    }


def build_insight(
    timeline: list[dict[str, Any]],
    market_rows: list[dict[str, Any]],
    *,
    benchmark_symbol: str = "510300.SH",
    holdings_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dates = [str(r["trade_date"]) for r in timeline]
    closes, bench_nav = benchmark_series(market_rows, dates, symbol=benchmark_symbol)
    regimes = label_regimes(dates, closes) if closes else ["range"] * len(dates)
    dd = max_drawdown_slice(timeline)
    dd_regime = None
    if dd.get("trough_date") and dd["trough_date"] in dates:
        dd_regime = regimes[dates.index(str(dd["trough_date"]))]
    return {
        "benchmark_symbol": benchmark_symbol,
        "calendar": calendar_buckets(timeline),
        "regimes": {
            "by_day": [{"trade_date": d, "regime": r} for d, r in zip(dates, regimes, strict=False)],
            "stats": regime_stats(timeline, regimes),
        },
        "drawdown": {**dd, "trough_regime": dd_regime},
        "benchmark_nav": [
            {"trade_date": d, "nav": round(n, 8)} for d, n in zip(dates, bench_nav, strict=False)
        ],
        "holdings": holdings_stats or {},
    }


def _self_check() -> None:
    # ponytail: O(n) MA scan ceiling; upgrade to rolling window cache if n>>1e5
    dates = [f"2024-01-{d:02d}" for d in range(1, 32)]
    closes = [100.0 + i * 0.5 for i in range(31)]
    labels = label_regimes(dates, closes)
    assert len(labels) == 31
    assert labels[-1] in {"trend_up", "range", "trend_down"}
    tl = [
        {"trade_date": dates[i], "daily_return": 0.01 if i % 2 == 0 else -0.005, "total_asset": 1e6 * (1 + i * 0.001)}
        for i in range(31)
    ]
    cal = calendar_buckets(tl)
    assert "weekday" in cal and cal["weekday"]
    print("lab_insight self-check ok")


if __name__ == "__main__":
    _self_check()

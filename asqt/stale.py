"""Stale market-data guard: lag counted in trading sessions, not calendar days."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Sequence
from uuid import uuid4

from asqt.pit import parse_asof

DEFAULT_STALE_MAX_SESSIONS = 5
DEFAULT_STALE_SEVERITY = "warn"  # warn | block


def stale_max_sessions() -> int:
    raw = os.environ.get("ASQT_STALE_MAX_SESSIONS", str(DEFAULT_STALE_MAX_SESSIONS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_STALE_MAX_SESSIONS
    return max(0, value)


def stale_severity() -> str:
    raw = (os.environ.get("ASQT_STALE_SEVERITY") or DEFAULT_STALE_SEVERITY).strip().lower()
    return raw if raw in {"warn", "block"} else DEFAULT_STALE_SEVERITY


def open_trade_dates(calendar: Sequence[dict[str, Any]] | None) -> list[str]:
    if not calendar:
        return []
    dates = [
        str(row.get("trade_date") or "")[:10]
        for row in calendar
        if int(row.get("is_open") or 0) == 1 and str(row.get("trade_date") or "").strip()
    ]
    return sorted({d for d in dates if len(d) == 10})


def trading_session_lag(latest: str, asof: str, open_dates: Sequence[str]) -> int:
    """Count open sessions strictly after ``latest`` up to and including ``asof``.

    ``latest == asof`` → 0. Missing/invalid dates → 0 (caller should treat no-bar separately).
    """
    try:
        latest_s = parse_asof(latest)
        asof_s = parse_asof(asof)
    except Exception:
        return 0
    if latest_s >= asof_s:
        return 0
    return sum(1 for day in open_dates if latest_s < day <= asof_s)


def latest_bar_dates(
    records: Sequence[dict[str, Any]],
    asof: str,
) -> dict[str, str]:
    """Per-symbol latest ``trade_date`` with ``trade_date <= asof``."""
    cutoff = parse_asof(asof)
    out: dict[str, str] = {}
    for row in records or []:
        symbol = str(row.get("symbol") or "").strip()
        day = str(row.get("trade_date") or "")[:10]
        if not symbol or len(day) < 10 or day > cutoff:
            continue
        prev = out.get(symbol)
        if prev is None or day > prev:
            out[symbol] = day
    return out


@dataclass
class StaleReport:
    asof: str
    max_lag: int
    severity: str
    issues: list[dict[str, Any]] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(item.get("severity") == "block" for item in self.issues)

    @property
    def has_stale(self) -> bool:
        return bool(self.issues)


def evaluate_market_staleness(
    *,
    records: Sequence[dict[str, Any]],
    calendar: Sequence[dict[str, Any]] | None,
    asof: str,
    expected_symbols: Sequence[str] | None = None,
    max_lag: int | None = None,
    severity: str | None = None,
) -> StaleReport:
    """Emit ``stale_asof`` issues when latest bar lags asof by more than ``max_lag`` sessions."""
    asof_s = parse_asof(asof)
    lag_limit = stale_max_sessions() if max_lag is None else max(0, int(max_lag))
    sev = (severity or stale_severity()).strip().lower()
    if sev not in {"warn", "block"}:
        sev = DEFAULT_STALE_SEVERITY
    report = StaleReport(asof=asof_s, max_lag=lag_limit, severity=sev)
    opens = open_trade_dates(calendar)
    if not opens:
        return report

    latest = latest_bar_dates(records, asof_s)
    symbols = list(expected_symbols) if expected_symbols else sorted(latest)
    for symbol in symbols:
        symbol_s = str(symbol).strip()
        if not symbol_s:
            continue
        last = latest.get(symbol_s)
        if not last:
            # No bar on/before asof → covered by missing checks elsewhere.
            continue
        lag = trading_session_lag(last, asof_s, opens)
        if lag <= lag_limit:
            continue
        report.issues.append(
            {
                "issue_id": str(uuid4()),
                "dataset": "market_daily",
                "symbol": symbol_s,
                "trade_date": asof_s,
                "check_type": "stale_asof",
                "severity": sev,
                "status": "open",
                "source_a": None,
                "source_b": None,
                "diff": f"latest_bar={last}; lag_sessions={lag}; max_lag={lag_limit}",
            }
        )
    return report

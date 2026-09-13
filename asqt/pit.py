"""Point-in-time (PIT) date windows — no lookahead.

Calendar dates are ISO ``YYYY-MM-DD`` strings. Upper bound is inclusive
(``on_or_before``): a bar/event on ``asof`` is visible; anything after is not.

Undated fields: allowed only in ``live`` mode; ``backtest`` drops them so a
historical run cannot silently ingest undated live profile / news.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Sequence

PitMode = Literal["live", "backtest"]


class PitError(ValueError):
    """Invalid asof / window arguments for PIT helpers."""


def parse_asof(value: str | date | datetime | None) -> str:
    """Normalize to ``YYYY-MM-DD`` or raise ``PitError``."""
    if value is None:
        raise PitError("asof is required")
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    text = text[:10]
    if len(text) < 10:
        raise PitError(f"invalid asof: {value!r}")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise PitError(f"invalid asof: {value!r}") from exc
    return text


def on_or_before(event_date: str | date | datetime | None, asof: str | date | datetime) -> bool:
    """True when ``event_date`` is known by ``asof`` (inclusive). Missing date → False."""
    if event_date is None or str(event_date).strip() == "":
        return False
    try:
        d = parse_asof(event_date)
        cutoff = parse_asof(asof)
    except PitError:
        return False
    return d <= cutoff


def in_closed_window(
    event_date: str | date | datetime | None,
    *,
    start: str | date | datetime,
    end: str | date | datetime,
) -> bool:
    """Inclusive window ``start <= event_date <= end``."""
    if event_date is None or str(event_date).strip() == "":
        return False
    try:
        d = parse_asof(event_date)
        lo = parse_asof(start)
        hi = parse_asof(end)
    except PitError:
        return False
    return lo <= d <= hi


def undated_allowed(mode: PitMode, *, asof: str | date | datetime | None = None) -> bool:
    """Whether rows without a vintage/date may be kept.

    ``backtest``: never. ``live``: yes when asof is omitted or within 1 calendar
    day of UTC today (operational live runs).
    """
    if mode == "backtest":
        return False
    if asof is None:
        return True
    try:
        cutoff = parse_asof(asof)
    except PitError:
        return False
    today = datetime.now(timezone.utc).date()
    return abs((date.fromisoformat(cutoff) - today).days) <= 1


def filter_rows_on_or_before(
    rows: Iterable[dict[str, Any]],
    asof: str | date | datetime,
    *,
    date_key: str = "event_date",
    mode: PitMode = "backtest",
    keep_undated: bool | None = None,
) -> list[dict[str, Any]]:
    """Keep rows with ``date_key <= asof``; undated handled by ``mode`` / ``keep_undated``."""
    cutoff = parse_asof(asof)
    allow_undated = undated_allowed(mode, asof=cutoff) if keep_undated is None else bool(keep_undated)
    out: list[dict[str, Any]] = []
    for row in rows or []:
        raw = row.get(date_key)
        if raw is None or str(raw).strip() == "":
            if allow_undated:
                out.append(row)
            continue
        if on_or_before(raw, cutoff):
            out.append(row)
    return out


def series_asof(series: Sequence[dict[str, Any]], asof: str | date | datetime, *, date_key: str = "trade_date") -> list[dict[str, Any]]:
    """Return bars with ``date_key <= asof`` (binary search; series must be sorted ascending)."""
    if not series:
        return []
    cutoff = parse_asof(asof)
    if str(series[-1].get(date_key) or "") <= cutoff:
        return list(series)
    if str(series[0].get(date_key) or "") > cutoff:
        return []
    lo, hi = 0, len(series)
    while lo < hi:
        mid = (lo + hi) // 2
        if str(series[mid].get(date_key) or "") <= cutoff:
            lo = mid + 1
        else:
            hi = mid
    return list(series[:lo])


def lookback_start(asof: str | date | datetime, lookback_days: int) -> str:
    """Calendar-day lookback start (inclusive) for event windows."""
    if lookback_days < 0:
        raise PitError("lookback_days must be >= 0")
    asof_d = date.fromisoformat(parse_asof(asof))
    return (asof_d - timedelta(days=int(lookback_days))).isoformat()

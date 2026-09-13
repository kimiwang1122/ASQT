"""Fundamental snapshot schema + ann_date PIT (full pull deferred / X3)."""

from __future__ import annotations

from typing import Any

from asqt.pit import on_or_before, parse_asof


def known_fundamental_date(row: dict[str, Any]) -> str | None:
    """Announcement date is the knowability bound; never use report_period alone for PIT."""
    for key in ("ann_date", "asof_date"):
        raw = row.get(key)
        if raw is not None and str(raw).strip():
            try:
                return parse_asof(raw)
            except Exception:
                continue
    return None


def fundamentals_asof(rows: list[dict[str, Any]], asof: str) -> list[dict[str, Any]]:
    """Keep fundamentals with ``ann_date`` (or asof_date) ``<= asof``. No lookahead."""
    cutoff = parse_asof(asof)
    out: list[dict[str, Any]] = []
    for row in rows or []:
        known = known_fundamental_date(row)
        if known is None:
            continue
        if on_or_before(known, cutoff):
            out.append(row)
    return out

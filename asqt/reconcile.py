"""Cross-source daily-bar authentication.

Does not replace the corporate-action catalog. Later phases can ingest a full
event master; this job only checks that stored bars still match a second vendor
and that sub-threshold factor jumps are internally consistent.
"""

from __future__ import annotations

from typing import Any

CLOSE_TOLERANCE = 0.02
ADJ_TOLERANCE = 0.03
SILENT_FACTOR_MIN = 1.03
SILENT_FACTOR_GATE = 1.5
PRICE_FACTOR_ALIGN = 0.20


def compare_market_daily(
    stored: list[dict[str, Any]],
    peer: list[dict[str, Any]],
    *,
    close_tol: float = CLOSE_TOLERANCE,
    adj_tol: float = ADJ_TOLERANCE,
) -> dict[str, Any]:
    left = {(row["symbol"], str(row["trade_date"])[:10]): row for row in stored}
    right = {(row["symbol"], str(row["trade_date"])[:10]): row for row in peer}
    keys = sorted(set(left) & set(right))
    mismatches: list[dict[str, Any]] = []
    for key in keys:
        a, b = left[key], right[key]
        close_rel = _rel(a.get("close"), b.get("close"))
        adj_rel = _rel(a.get("adj_factor"), b.get("adj_factor"))
        fields: list[str] = []
        if close_rel is None or close_rel > close_tol:
            fields.append(f"close stored={a.get('close')} peer={b.get('close')} rel={close_rel}")
        if a.get("adj_factor") is not None and b.get("adj_factor") is not None:
            if adj_rel is None or adj_rel > adj_tol:
                fields.append(f"adj_factor stored={a.get('adj_factor')} peer={b.get('adj_factor')} rel={adj_rel}")
        if fields:
            mismatches.append(
                {
                    "symbol": key[0],
                    "trade_date": key[1],
                    "stored_source": a.get("source"),
                    "peer_source": b.get("source"),
                    "diff": "; ".join(fields),
                }
            )
    stored_n = len(left)
    peer_n = len(right)
    matched = len(keys)
    return {
        "stored_rows": stored_n,
        "peer_rows": peer_n,
        "matched_rows": matched,
        "match_rate": (matched / stored_n) if stored_n else 0.0,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def scan_silent_factor_jumps(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sub-threshold adj jumps: internal price/factor alignment, no announcement table."""
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row.get("symbol")), []).append(row)
    consistent: list[dict[str, Any]] = []
    inconsistent: list[dict[str, Any]] = []
    for symbol, items in by_symbol.items():
        ordered = sorted(items, key=lambda item: str(item.get("trade_date") or ""))
        previous = None
        for row in ordered:
            if previous is None:
                previous = row
                continue
            prev_f = _num(previous.get("adj_factor"))
            curr_f = _num(row.get("adj_factor"))
            prev_c = _num(previous.get("close"))
            curr_c = _num(row.get("close"))
            if None in (prev_f, curr_f, prev_c, curr_c) or prev_f == 0 or curr_c == 0:
                previous = row
                continue
            factor_ratio = curr_f / prev_f
            abs_ratio = factor_ratio if factor_ratio >= 1 else 1 / factor_ratio
            if abs_ratio < SILENT_FACTOR_MIN or abs_ratio >= SILENT_FACTOR_GATE:
                previous = row
                continue
            price_ratio = prev_c / curr_c
            payload = {
                "symbol": symbol,
                "trade_date": row.get("trade_date"),
                "prev_date": previous.get("trade_date"),
                "factor_ratio": round(factor_ratio, 6),
                "price_ratio": round(price_ratio, 6),
            }
            aligned = factor_ratio > 1 and curr_c < prev_c and abs(factor_ratio / price_ratio - 1) <= PRICE_FACTOR_ALIGN
            if aligned:
                consistent.append(payload)
            else:
                inconsistent.append(payload)
            previous = row
    return {
        "consistent_ex_right": consistent,
        "inconsistent_review": inconsistent,
        "consistent_count": len(consistent),
        "inconsistent_count": len(inconsistent),
    }


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _rel(left: Any, right: Any) -> float | None:
    a, b = _num(left), _num(right)
    if a is None or b is None:
        return None
    scale = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / scale


def collapse_adj_scale_mismatches(mismatches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep close mismatches as-is; fold same-symbol adj-only rows into one warn."""
    kept: list[dict[str, Any]] = []
    adj_only: dict[str, list[dict[str, Any]]] = {}
    for item in mismatches:
        diff = str(item.get("diff") or "")
        if "close stored=" in diff:
            kept.append(item)
            continue
        if "adj_factor" in diff:
            adj_only.setdefault(str(item.get("symbol") or ""), []).append(item)
            continue
        kept.append(item)
    for symbol, items in sorted(adj_only.items()):
        dates = sorted(str(row.get("trade_date") or "") for row in items)
        sample = items[0]
        span = dates[0] if len(dates) <= 1 else f"{dates[0]}~{dates[-1]}"
        kept.append(
            {
                "symbol": symbol,
                "trade_date": span,
                "stored_source": sample.get("stored_source"),
                "peer_source": sample.get("peer_source"),
                "diff": f"adj_factor_scale n={len(items)} {sample.get('diff')}",
            }
        )
    return kept

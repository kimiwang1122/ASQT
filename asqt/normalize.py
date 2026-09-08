"""Vendor-agnostic conversion into ASQT market_daily rows."""

from __future__ import annotations

from typing import Any

from asqt.symbols import infer_board, infer_instrument_type, limit_pct


class StandardNormalizer:
    def normalize_market_daily(self, raw_rows: list[dict[str, Any]], source_id: str) -> list[dict[str, Any]]:
        version = f"{source_id}-daily"
        records: list[dict[str, Any]] = []
        for row in raw_rows:
            symbol = str(row.get("symbol") or "")
            trade_date = str(row.get("date") or row.get("trade_date") or "")[:10]
            records.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": _num(row.get("open")),
                    "high": _num(row.get("high")),
                    "low": _num(row.get("low")),
                    "close": _num(row.get("close")),
                    "volume": _int(row.get("volume")),
                    "amount": _num(row.get("amount")),
                    "adj_factor": _num(row.get("adj_factor")),
                    "source": source_id,
                    "version": version,
                    "_preclose": _num(row.get("preclose")),
                    "_tradestatus": row.get("tradestatus"),
                    "_is_st": row.get("isST"),
                    "_name": row.get("name"),
                    "_list_date": _date(row.get("ipoDate") or row.get("list_date")),
                    "_delist_date": _date(row.get("outDate") or row.get("delist_date")),
                    "_status": row.get("status"),
                }
            )
        return records

    def instruments_from_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = row["symbol"]
            is_st = str(row.get("_is_st") or "0").strip() in {"1", "true", "True"}
            status_code = str(row.get("_status") or "1").strip()
            listed = "listed" if status_code in {"1", "listed", ""} else "delisted"
            latest[symbol] = {
                "symbol": symbol,
                "name": row.get("_name") or symbol,
                "instrument_type": infer_instrument_type(symbol),
                "exchange": symbol.split(".")[-1],
                "board": infer_board(symbol),
                "list_date": row.get("_list_date"),
                "delist_date": row.get("_delist_date") or None,
                "status": listed,
                "is_st": int(is_st),
            }
        return list(latest.values())

    def limit_rows_from_daily(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            symbol = row["symbol"]
            preclose = row.get("_preclose")
            pct = limit_pct(symbol)
            limit_up = round(preclose * (1 + pct), 2) if preclose else None
            limit_down = round(preclose * (1 - pct), 2) if preclose else None
            suspended = str(row.get("_tradestatus") or "1").strip() in {"0", "false", "False"}
            out.append(
                {
                    "symbol": symbol,
                    "trade_date": row["trade_date"],
                    "limit_up": limit_up,
                    "limit_down": limit_down,
                    "is_suspended": int(suspended),
                    "reason": "estimated_from_preclose" if preclose else "missing_preclose",
                }
            )
        return out


def _num(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"none", "nan"}:
        return None
    return float(text)


def _int(value: Any) -> int | None:
    number = _num(value)
    if number is None:
        return None
    return int(number)


def _date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().replace("/", "-")
    if text in {"", "None"}:
        return None
    return text[:10]


PLACEHOLDER_ADJ = 1.0
PLACEHOLDER_ADJ_TOL = 1e-6
PLACEHOLDER_MAX_CLOSE_MOVE = 0.25


def _is_placeholder_adj(value: Any) -> bool:
    number = _num(value)
    if number is None:
        return False
    return abs(number - PLACEHOLDER_ADJ) <= PLACEHOLDER_ADJ_TOL


def repair_placeholder_adj_factors(rows: list[dict[str, Any]]) -> int:
    """Carry previous adj_factor when a vendor leaves 1.0 on a quiet day.

    BaoStock ETF hfq often equals unadjusted close on the latest session, so
    adj_factor becomes 1.0 and trips the 2x quality gate. Not a corporate action.
    """
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row.get("symbol") or ""), []).append(row)
    repaired = 0
    for items in by_symbol.values():
        ordered = sorted(items, key=lambda item: str(item.get("trade_date") or ""))
        previous = None
        for row in ordered:
            if previous is not None and _is_placeholder_adj(row.get("adj_factor")) and not _is_placeholder_adj(previous.get("adj_factor")):
                prev_close = _num(previous.get("close"))
                curr_close = _num(row.get("close"))
                if prev_close not in (None, 0) and curr_close not in (None, 0):
                    move = abs(curr_close / prev_close - 1)
                    if move <= PLACEHOLDER_MAX_CLOSE_MOVE:
                        row["adj_factor"] = previous.get("adj_factor")
                        repaired += 1
            previous = row
    return repaired

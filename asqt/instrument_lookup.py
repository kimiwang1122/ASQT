"""Fuzzy instrument search + F10-lite profile (local bars, optional Tushare)."""

from __future__ import annotations

import time
from typing import Any

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import initialize_database, query_all
from asqt.storage import read_market_daily

_F10_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_F10_TTL_S = 600.0


def search_instruments(
    q: str,
    *,
    limit: int = 20,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    needle = str(q or "").strip()
    if not needle:
        return []
    cap = max(1, min(int(limit), 50))
    like = f"%{needle}%"
    rows = query_all(
        """
        SELECT symbol, name, instrument_type, exchange, board, list_date, status, is_st
        FROM instrument_master
        WHERE symbol LIKE ? COLLATE NOCASE
           OR name LIKE ? COLLATE NOCASE
        LIMIT 80
        """,
        (like, like),
        settings=settings,
    )
    ranked = sorted(rows, key=lambda row: _search_rank(row, needle))
    return [_public_hit(row) for row in ranked[:cap]]


def instrument_profile(
    symbol: str,
    *,
    settings: Settings | None = None,
    live: bool = True,
) -> dict[str, Any] | None:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    sid = str(symbol or "").strip().upper()
    if not sid:
        return None
    rows = query_all(
        """
        SELECT symbol, name, instrument_type, exchange, board, list_date, delist_date, status, is_st
        FROM instrument_master
        WHERE UPPER(symbol) = ?
        LIMIT 1
        """,
        (sid,),
        settings=settings,
    )
    if not rows:
        loose = search_instruments(symbol, limit=1, settings=settings)
        if not loose:
            return None
        return instrument_profile(loose[0]["symbol"], settings=settings, live=live)
    inst = dict(rows[0])
    key = str(inst["symbol"])
    tags = [
        str(row["tag"])
        for row in query_all(
            "SELECT tag FROM symbol_tag WHERE symbol = ? ORDER BY tag",
            (key,),
            settings=settings,
        )
    ]
    bars = read_market_daily(symbol=key, settings=settings, limit=8, newest_first=True)
    quote = _quote_from_bars(bars)
    limits = query_all(
        """
        SELECT trade_date, limit_up, limit_down, is_suspended, reason
        FROM limit_suspension
        WHERE symbol = ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (key,),
        settings=settings,
    )
    payload: dict[str, Any] = {
        "instrument": inst,
        "tags": tags,
        "quote": quote,
        "bars": [_public_bar(row) for row in bars[:6]],
        "limit": dict(limits[0]) if limits else None,
        "company": None,
        "valuation": None,
        "financials": [],
        "holders": [],
        "dividends": [],
        "sources": {"local": True, "tushare": False},
    }
    if live:
        extra = _cached_tushare(
            key,
            quote.get("trade_date") if quote else None,
            [row.get("trade_date") for row in bars],
        )
        if extra:
            payload["sources"]["tushare"] = True
            payload.update(extra)
    return payload


def _search_rank(row: dict[str, Any], needle: str) -> tuple[int, str]:
    q = needle.lower()
    symbol = str(row.get("symbol") or "").lower()
    name = str(row.get("name") or "").lower()
    code = symbol.split(".")[0]
    if q == symbol or q == code:
        rank = 0
    elif symbol.startswith(q) or code.startswith(q):
        rank = 1
    elif name == q:
        rank = 2
    elif q in name:
        rank = 3
    else:
        rank = 4
    return rank, symbol


def _public_hit(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row["symbol"],
        "name": row.get("name") or "",
        "instrument_type": row.get("instrument_type") or "",
        "exchange": row.get("exchange") or "",
        "board": row.get("board") or "",
        "list_date": row.get("list_date"),
        "status": row.get("status") or "",
        "is_st": int(row.get("is_st") or 0),
    }


def _public_bar(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_date": row.get("trade_date"),
        "open": _num(row.get("open")),
        "high": _num(row.get("high")),
        "low": _num(row.get("low")),
        "close": _num(row.get("close")),
        "volume": _num(row.get("volume")),
        "amount": _num(row.get("amount")),
    }


def _quote_from_bars(bars: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bars:
        return None
    last = bars[0]
    prev = bars[1] if len(bars) > 1 else None
    close = _num(last.get("close"))
    prev_close = _num(prev.get("close")) if prev else None
    chg = None
    if close is not None and prev_close and prev_close > 0:
        chg = close / prev_close - 1.0
    return {
        "trade_date": last.get("trade_date"),
        "open": _num(last.get("open")),
        "high": _num(last.get("high")),
        "low": _num(last.get("low")),
        "close": close,
        "volume": _num(last.get("volume")),
        "amount": _num(last.get("amount")),
        "change_pct": chg,
    }


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cached_tushare(
    symbol: str,
    asof: str | None,
    dates: list[Any] | None = None,
) -> dict[str, Any] | None:
    now = time.monotonic()
    hit = _F10_CACHE.get(symbol)
    if hit and now - hit[0] < _F10_TTL_S:
        return hit[1]
    extra = _tushare_f10(symbol, asof, dates)
    if extra:
        _F10_CACHE[symbol] = (now, extra)
        if len(_F10_CACHE) > 64:
            oldest = min(_F10_CACHE, key=lambda key: _F10_CACHE[key][0])
            _F10_CACHE.pop(oldest, None)
    return extra


def _tushare_f10(
    symbol: str,
    asof: str | None,
    dates: list[Any] | None = None,
) -> dict[str, Any] | None:
    try:
        from asqt.adapters.tushare_source import TushareAdapter

        adapter = TushareAdapter()
        adapter._token_value()
    except Exception:  # noqa: BLE001
        return None
    compact = str(asof or "").replace("-", "")
    company = _first(
        _safe_query(
            adapter,
            "stock_company",
            {"ts_code": symbol},
            "ts_code,chairman,manager,reg_capital,setup_date,province,city,employees,website,main_business,introduction",
        )
    ) or _first(
        _safe_query(
            adapter,
            "fund_basic",
            {"ts_code": symbol},
            "ts_code,name,management,custodian,fund_type,found_date,list_date,issue_amount,status",
        )
    )
    valuation = _latest_daily_basic(adapter, symbol, [compact, *(dates or [])])
    financials = _safe_query(
        adapter,
        "fina_indicator",
        {"ts_code": symbol},
        "ts_code,end_date,roe,roa,grossprofit_margin,netprofit_margin,debt_to_assets,eps,bps",
    )[:4]
    holders = _safe_query(
        adapter,
        "top10_holders",
        {"ts_code": symbol},
        "ts_code,ann_date,end_date,holder_name,hold_amount,hold_ratio",
    )[:10]
    dividends = _safe_query(
        adapter,
        "dividend",
        {"ts_code": symbol},
        "ts_code,end_date,ann_date,div_proc,cash_div,stk_div",
    )[:8]
    if not any([company, valuation, financials, holders, dividends]):
        return None
    return {
        "company": company,
        "valuation": valuation,
        "financials": financials,
        "holders": holders,
        "dividends": dividends,
    }


def _latest_daily_basic(adapter: Any, symbol: str, dates: list[Any]) -> dict[str, Any] | None:
    fields = "ts_code,trade_date,pe,pe_ttm,pb,ps,dv_ratio,turnover_rate,total_mv,circ_mv,volume_ratio"
    seen: set[str] = set()
    for raw in dates:
        day = str(raw or "").replace("-", "").strip()
        if not day or day in seen:
            continue
        seen.add(day)
        row = _first(
            _safe_query(adapter, "daily_basic", {"ts_code": symbol, "trade_date": day}, fields)
        )
        if row:
            return row
    return None


def _safe_query(adapter: Any, api: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
    try:
        rows = adapter._query(api, params, fields)
    except Exception:  # noqa: BLE001
        return []
    return [row for row in rows if isinstance(row, dict)]


def _first(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None

"""Market event normalize / asof / upsert / query (fixture + Tushare).

Pilot strategy ``stock_holder_increase_follow`` lives in ``strategies.py``
(near-N-day net holder increase + optional momentum filter via selector; draft lifecycle).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.contracts import MARKET_EVENT_COLUMNS
from asqt.db import executemany, initialize_database, query_all
from asqt.pit import in_closed_window, lookback_start, on_or_before, parse_asof
from asqt.pit import filter_rows_on_or_before
from asqt.records import query_records, record_parquet_path, upsert_records

EVENT_TYPE_HOLDER_INCREASE = "holder_increase"
EVENT_TYPE_HOLDER_DECREASE = "holder_decrease"
HOLDER_TRADE_TYPES = frozenset({EVENT_TYPE_HOLDER_INCREASE, EVENT_TYPE_HOLDER_DECREASE})

DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "market_events.json"


def holder_net_in_window(
    events: Sequence[dict[str, Any]],
    symbol: str,
    asof: str,
    lookback_days: int,
) -> float | None:
    """Sum signed holder trade values with ``start <= event_date <= asof``.

    ``start = asof - lookback_days`` (calendar days). Uses only
    ``holder_increase`` / ``holder_decrease``; no lookahead past ``asof``.
    Returns None when no matching events fall in the window.
    """
    if lookback_days < 0:
        return None
    try:
        asof_text = parse_asof(asof)
        start_text = lookback_start(asof_text, int(lookback_days))
    except Exception:
        return None
    want = str(symbol or "").strip()
    total = 0.0
    hit = False
    for row in events or []:
        if str(row.get("symbol") or "").strip() != want:
            continue
        if str(row.get("event_type") or "").strip() not in HOLDER_TRADE_TYPES:
            continue
        event_date = str(row.get("event_date") or "")[:10]
        if not in_closed_window(event_date, start=start_text, end=asof_text):
            continue
        value = row.get("value")
        if value is None:
            continue
        total += float(value)
        hit = True
    if not hit:
        return None
    return total


def _iso_date(value: Any) -> str:
    text = str(value or "").strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]


def _num(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"none", "nan"}:
        return None
    return float(text)


def _payload_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def make_event_id(
    *,
    event_type: str,
    symbol: str,
    event_date: str,
    actor: str | None,
    value: float | None,
    source: str,
) -> str:
    raw = "|".join(
        [
            str(event_type or "").strip(),
            str(symbol or "").strip(),
            str(event_date or "").strip(),
            str(actor or "").strip(),
            "" if value is None else f"{float(value):.8g}",
            str(source or "").strip(),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def normalize_event(row: dict[str, Any], *, default_source: str | None = None) -> dict[str, Any]:
    """Normalize a raw or partial event into the market_event contract."""
    source = str(row.get("source") or default_source or "").strip() or "unknown"
    symbol = str(row.get("symbol") or row.get("ts_code") or "").strip()
    event_date = _iso_date(row.get("event_date") or row.get("ann_date") or row.get("date"))
    asof_date = _iso_date(row.get("asof_date") or event_date)
    event_type = str(row.get("event_type") or "").strip()
    actor = row.get("actor")
    if actor is None:
        actor = row.get("holder_name")
    actor_text = None if actor is None else str(actor).strip() or None
    value = _num(row.get("value"))
    if value is None and row.get("change_vol") is not None:
        value = _num(row.get("change_vol"))
    version = str(row.get("version") or f"{source}-event").strip()
    event_id = str(row.get("event_id") or "").strip()
    if not event_id:
        event_id = make_event_id(
            event_type=event_type,
            symbol=symbol,
            event_date=event_date,
            actor=actor_text,
            value=value,
            source=source,
        )
    if not event_type:
        raise ValueError("event_type is required")
    if not symbol:
        raise ValueError("symbol is required")
    if not event_date:
        raise ValueError("event_date is required")
    if not asof_date:
        asof_date = event_date
    return {
        "event_id": event_id,
        "event_type": event_type,
        "symbol": symbol,
        "event_date": event_date,
        "asof_date": asof_date,
        "actor": actor_text,
        "value": value,
        "payload_json": _payload_text(row.get("payload_json") if "payload_json" in row else row.get("payload")),
        "source": source,
        "version": version,
    }


def normalize_holder_trade_row(raw: dict[str, Any], *, source_id: str = "tushare") -> dict[str, Any]:
    """Map Tushare stk_holdertrade row → market_event."""
    in_de = str(raw.get("in_de") or raw.get("trade_type") or "").strip().upper()
    if in_de in {"IN", "增持"}:
        event_type = EVENT_TYPE_HOLDER_INCREASE
        sign = 1.0
    elif in_de in {"DE", "减持"}:
        event_type = EVENT_TYPE_HOLDER_DECREASE
        sign = -1.0
    else:
        raise ValueError(f"unknown holder trade in_de={in_de!r}")
    change = _num(raw.get("change_vol"))
    value = None if change is None else abs(change) * sign
    ann = _iso_date(raw.get("ann_date") or raw.get("event_date"))
    payload = {
        "holder_type": raw.get("holder_type"),
        "in_de": in_de,
        "change_vol": raw.get("change_vol"),
        "change_ratio": raw.get("change_ratio"),
        "after_share": raw.get("after_share"),
        "after_ratio": raw.get("after_ratio"),
        "avg_price": raw.get("avg_price"),
        "total_share": raw.get("total_share"),
        "begin_date": _iso_date(raw.get("begin_date")) or None,
        "close_date": _iso_date(raw.get("close_date")) or None,
    }
    return normalize_event(
        {
            "event_type": event_type,
            "symbol": raw.get("ts_code") or raw.get("symbol"),
            "event_date": ann,
            "asof_date": ann,
            "actor": raw.get("holder_name") or raw.get("actor"),
            "value": value,
            "payload": payload,
            "source": source_id,
            "version": f"{source_id}-stk_holdertrade",
        }
    )


def events_asof(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    mode: str = "backtest",
) -> list[dict[str, Any]]:
    """Keep events known by ``asof`` (prefer ``asof_date``, else ``event_date``). No lookahead."""
    cutoff = parse_asof(asof)
    out: list[dict[str, Any]] = []
    for row in rows or []:
        known = row.get("asof_date") or row.get("event_date")
        if known is None or str(known).strip() == "":
            # Undated: only live mode may keep (via filter helper policy).
            kept = filter_rows_on_or_before([row], cutoff, date_key="event_date", mode=mode)  # type: ignore[arg-type]
            if kept:
                out.append(row)
            continue
        if on_or_before(known, cutoff):
            out.append(row)
    return out


def _sync_sqlite(rows: list[dict[str, Any]], settings: Settings) -> None:
    if not rows:
        return
    initialize_database(settings)
    cols = list(MARKET_EVENT_COLUMNS)
    placeholders = ", ".join("?" for _ in cols)
    col_sql = ", ".join(cols)
    executemany(
        f"INSERT OR REPLACE INTO market_event ({col_sql}) VALUES ({placeholders})",
        [[row.get(col) for col in cols] for row in rows],
        settings=settings,
    )


def upsert_events(
    rows: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
    default_source: str | None = None,
) -> Path:
    """Normalize, write parquet via records, mirror to SQLite."""
    settings = ensure_runtime_dirs(settings or get_settings())
    normalized = [normalize_event(row, default_source=default_source) for row in (rows or [])]
    path = upsert_records("market_event", normalized, settings=settings)
    _sync_sqlite(normalized, settings)
    return path


def query_events(
    *,
    settings: Settings | None = None,
    symbol: str | None = None,
    event_type: str | None = None,
    source: str | None = None,
    start: str | None = None,
    end: str | None = None,
    asof: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    newest_first: bool = True,
    fuzzy_symbol: bool = True,
) -> list[dict[str, Any]]:
    """Query market events. Prefer SQLite (indexed); fall back to parquet."""
    settings = settings or get_settings()
    initialize_database(settings)
    where, params = _event_filter_sql(
        symbol=symbol,
        event_type=event_type,
        source=source,
        start=start,
        end=end,
        asof=asof,
        fuzzy_symbol=fuzzy_symbol,
    )
    order = "event_date DESC, symbol ASC" if newest_first else "event_date ASC, symbol ASC"
    sql = f"SELECT * FROM market_event {where} ORDER BY {order}"
    bind: list[object] = list(params)
    if limit is not None:
        sql += " LIMIT ?"
        bind.append(int(limit))
        if offset:
            sql += " OFFSET ?"
            bind.append(max(0, int(offset)))
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        bind.append(max(0, int(offset)))
    rows = query_all(sql, tuple(bind), settings=settings)
    if rows or _sqlite_event_count(settings) > 0:
        return rows
    # Parquet fallback for environments that only wrote records.
    return _query_events_parquet(
        settings=settings,
        symbol=symbol,
        event_type=event_type,
        source=source,
        start=start,
        end=end,
        asof=asof,
        limit=limit,
        offset=offset,
        newest_first=newest_first,
        fuzzy_symbol=fuzzy_symbol,
    )


def count_events(
    *,
    settings: Settings | None = None,
    symbol: str | None = None,
    event_type: str | None = None,
    source: str | None = None,
    start: str | None = None,
    end: str | None = None,
    asof: str | None = None,
    fuzzy_symbol: bool = True,
) -> int:
    """Count matching events without pagination truncation."""
    settings = settings or get_settings()
    initialize_database(settings)
    where, params = _event_filter_sql(
        symbol=symbol,
        event_type=event_type,
        source=source,
        start=start,
        end=end,
        asof=asof,
        fuzzy_symbol=fuzzy_symbol,
    )
    rows = query_all(
        f"SELECT COUNT(*) AS c FROM market_event {where}",
        tuple(params),
        settings=settings,
    )
    total = int(rows[0]["c"]) if rows else 0
    if total or _sqlite_event_count(settings) > 0:
        return total
    return len(
        _query_events_parquet(
            settings=settings,
            symbol=symbol,
            event_type=event_type,
            source=source,
            start=start,
            end=end,
            asof=asof,
            limit=None,
            offset=0,
            newest_first=False,
            fuzzy_symbol=fuzzy_symbol,
        )
    )


def _sqlite_event_count(settings: Settings) -> int:
    rows = query_all("SELECT COUNT(*) AS c FROM market_event", settings=settings)
    return int(rows[0]["c"]) if rows else 0


def _event_filter_sql(
    *,
    symbol: str | None,
    event_type: str | None,
    source: str | None,
    start: str | None,
    end: str | None,
    asof: str | None,
    fuzzy_symbol: bool,
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if event_type:
        clauses.append("event_type = ?")
        params.append(str(event_type).strip())
    if source:
        clauses.append("source = ?")
        params.append(str(source).strip())
    if start:
        clauses.append("event_date >= ?")
        params.append(str(start).strip()[:10])
    if end:
        clauses.append("event_date <= ?")
        params.append(str(end).strip()[:10])
    if asof:
        clauses.append("event_date <= ?")
        params.append(str(asof).strip()[:10])
    if symbol:
        needle = str(symbol).strip()
        if fuzzy_symbol:
            clauses.append("UPPER(symbol) LIKE ?")
            params.append(f"%{needle.upper()}%")
        else:
            clauses.append("symbol = ?")
            params.append(needle)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def _query_events_parquet(
    *,
    settings: Settings,
    symbol: str | None,
    event_type: str | None,
    source: str | None,
    start: str | None,
    end: str | None,
    asof: str | None,
    limit: int | None,
    offset: int,
    newest_first: bool,
    fuzzy_symbol: bool,
) -> list[dict[str, Any]]:
    rows = query_records(
        "market_event",
        settings=settings,
        symbol=None if fuzzy_symbol else symbol,
        event_type=event_type,
        source=source,
        start=start,
        end=end,
        limit=None,
        newest_first=newest_first,
    )
    if fuzzy_symbol and symbol:
        needle = str(symbol).strip().upper()
        if needle:
            rows = [row for row in rows if needle in str(row.get("symbol") or "").upper()]
    if asof:
        rows = events_asof(rows, asof)
    start_i = max(0, int(offset or 0))
    if limit is not None:
        return rows[start_i : start_i + int(limit)]
    if start_i:
        return rows[start_i:]
    return rows


def list_event_types(*, settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    initialize_database(settings)
    db_rows = query_all(
        "SELECT DISTINCT event_type FROM market_event WHERE event_type IS NOT NULL AND event_type != '' ORDER BY event_type",
        settings=settings,
    )
    if db_rows or _sqlite_event_count(settings) > 0:
        return [str(row["event_type"]) for row in db_rows]
    rows = query_records("market_event", settings=settings, newest_first=False)
    seen: list[str] = []
    for row in rows:
        et = str(row.get("event_type") or "").strip()
        if et and et not in seen:
            seen.append(et)
    return sorted(seen)


def import_events_from_json(
    path: str | Path | None = None,
    *,
    rows: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Import fixture / JSON rows into market_event."""
    settings = ensure_runtime_dirs(settings or get_settings())
    loaded: list[dict[str, Any]]
    source_path: str | None = None
    if rows is not None:
        loaded = list(rows)
    else:
        fixture = Path(path) if path else DEFAULT_FIXTURE_PATH
        if not fixture.is_file():
            raise FileNotFoundError(f"event fixture not found: {fixture}")
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            loaded = list(payload.get("events") or payload.get("rows") or [])
        elif isinstance(payload, list):
            loaded = list(payload)
        else:
            raise ValueError("fixture must be a list or {events|rows: [...]}")
        source_path = str(fixture)
    out_path = upsert_events(loaded, settings=settings, default_source="fixture")
    return {
        "imported": len(loaded),
        "parquet": str(out_path),
        "path": str(record_parquet_path("market_event", settings)),
        "source_path": source_path,
    }


def pull_holder_trade_events(
    *,
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    settings: Settings | None = None,
    adapter: Any | None = None,
) -> dict[str, Any]:
    """Fetch Tushare stk_holdertrade and upsert as market_event."""
    settings = ensure_runtime_dirs(settings or get_settings())
    if adapter is None:
        from asqt.adapters.tushare_source import TushareAdapter

        adapter = TushareAdapter()
    raw_rows = adapter.fetch_stk_holdertrade(
        symbols=symbols or [],
        start=start,
        end=end,
    )
    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for raw in raw_rows:
        try:
            events.append(normalize_holder_trade_row(raw, source_id=getattr(adapter, "source_id", "tushare")))
        except ValueError as exc:
            errors.append({"symbol": str(raw.get("ts_code") or ""), "error": str(exc)[:300]})
    path = upsert_events(events, settings=settings)
    unique_ids = {str(row.get("event_id") or "") for row in events if row.get("event_id")}
    stored = count_events(settings=settings)
    meta = dict(getattr(adapter, "last_holdertrade_meta", {}) or {})
    return {
        "source": "tushare",
        "schema": "market_event",
        "fetched": len(raw_rows),
        "upserted": len(events),
        "unique_in_batch": len(unique_ids),
        "stored_total": stored,
        "deduped_in_batch": max(0, len(events) - len(unique_ids)),
        "range_start": meta.get("start"),
        "range_end": meta.get("end"),
        "requests": meta.get("requests"),
        "chunks": meta.get("chunks"),
        "chunk_hits_limit": meta.get("chunk_hits_limit") or [],
        "day_hits_limit": meta.get("day_hits_limit") or [],
        "default_lookback_days": meta.get("default_lookback_days"),
        "persisted": {"sqlite": "market_event", "parquet": "market_event"},
        "errors": errors + list(getattr(adapter, "last_errors", []) or []),
        "parquet": str(path),
        "path": str(record_parquet_path("market_event", settings)),
    }

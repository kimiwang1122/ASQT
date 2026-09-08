"""P1 pull: adapter → raw → normalize → parquet → quality gate."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha1
import inspect
import json
from uuid import uuid4

from asqt.config import Settings, get_settings
from asqt.contracts import MARKET_DAILY_COLUMNS
from asqt.db import execute, executemany, initialize_database, query_all
from asqt.normalize import StandardNormalizer, repair_placeholder_adj_factors
from asqt.quality import ContractQualityChecker
from asqt.rawstore import write_raw_json
from asqt.session import session_asof_date
from asqt.storage import market_daily_path, market_daily_span, read_market_daily, upsert_market_daily


def resolve_append_window(
    *,
    max_trade_date: str | None,
    today: str,
    overlap_days: int = 1,
) -> dict:
    if not max_trade_date:
        return {"ok": False, "reason": "no_stored_bars", "start": None, "end": today, "max_trade_date": None}
    start_d = date.fromisoformat(max_trade_date) - timedelta(days=max(0, int(overlap_days) - 1))
    end_d = date.fromisoformat(today)
    if start_d > end_d:
        return {
            "ok": False,
            "reason": "already_current",
            "start": max_trade_date,
            "end": today,
            "max_trade_date": max_trade_date,
        }
    return {
        "ok": True,
        "reason": "append",
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
        "max_trade_date": max_trade_date,
    }


def _fetch_pct(done: int, total: int) -> int:
    if total <= 0:
        return 1
    if done <= 0:
        return 1
    return min(90, max(1, round(done * 90 / total)))


def _fetch_market_daily(adapter, symbols: list[str], start: str, end: str, on_progress=None) -> list:
    fetch = adapter.fetch_market_daily

    def report(done: int, total: int, symbol: str | None = None) -> None:
        if not on_progress:
            return
        on_progress(
            {
                "stage": "fetch",
                "done": done,
                "total": total,
                "symbol": symbol or "",
                "pct": _fetch_pct(done, total),
            }
        )

    if on_progress:
        report(0, len(symbols), None)
    try:
        params = inspect.signature(fetch).parameters
    except (TypeError, ValueError):
        params = {}
    if "on_progress" in params:
        return fetch(symbols, start, end, on_progress=report)
    return fetch(symbols, start, end)


def pull_daily_append(
    symbols: list[str],
    *,
    settings: Settings | None = None,
    adapter=None,
    source: str = "baostock",
    today: str | None = None,
    overlap_days: int = 1,
    run_check: bool = True,
    on_progress=None,
) -> dict:
    settings = settings or get_settings()
    initialize_database(settings)
    _min_date, max_date = market_daily_span(settings)
    window = resolve_append_window(
        max_trade_date=max_date,
        today=today or session_asof_date(),
        overlap_days=overlap_days,
    )
    if not window["ok"]:
        return {
            "skipped": True,
            "reason": window["reason"],
            "start": window["start"],
            "end": window["end"],
            "max_trade_date": window["max_trade_date"],
            "normalized_rows": 0,
        }
    result = pull_daily(
        symbols,
        window["start"],
        window["end"],
        settings=settings,
        adapter=adapter,
        source=source,
        run_check=run_check,
        on_progress=on_progress,
    )
    result["skipped"] = False
    result["reason"] = window["reason"]
    result["max_trade_date_before"] = window["max_trade_date"]
    return result


def pull_daily(
    symbols: list[str],
    start: str,
    end: str,
    *,
    settings: Settings | None = None,
    adapter=None,
    source: str = "baostock",
    run_check: bool = True,
    on_progress=None,
) -> dict:
    settings = settings or get_settings()
    initialize_database(settings)
    if adapter is None:
        adapter = build_adapter(source)

    started = datetime.now(timezone.utc).isoformat()
    raw_rows = _fetch_market_daily(adapter, symbols, start, end, on_progress=on_progress)
    joined = "-".join(symbols)
    raw_stem = f"{start}_{end}_{joined}".replace(".", "")
    if len(raw_stem) > 80:
        raw_stem = f"{start}_{end}_{len(symbols)}n_{sha1(joined.encode()).hexdigest()[:12]}"
    raw_path = write_raw_json(
        getattr(adapter, "source_id", "unknown"),
        "market_daily",
        {"start": start, "end": end, "symbols": symbols, "rows": raw_rows},
        settings=settings,
        stem=raw_stem,
    )
    source_id = getattr(adapter, "source_id", "unknown")
    normalizer = StandardNormalizer()
    normalized = normalizer.normalize_market_daily(raw_rows, source_id)
    stored = read_market_daily(settings=settings)
    merged = {(row["symbol"], row["trade_date"]): dict(row) for row in stored}
    for row in normalized:
        key = (row["symbol"], row["trade_date"])
        merged[key] = {**merged.get(key, {}), **row}
    repair_placeholder_adj_factors(list(merged.values()))
    contract_rows = []
    for row in normalized:
        repaired = merged[(row["symbol"], row["trade_date"])]
        contract_rows.append({key: repaired.get(key) for key in MARKET_DAILY_COLUMNS})
    parquet_path = upsert_market_daily(contract_rows, settings=settings)
    instruments = normalizer.instruments_from_rows(normalized)
    limits = normalizer.limit_rows_from_daily(normalized)
    _upsert_source(adapter, settings)
    _upsert_instruments(instruments, settings)
    _upsert_limits(limits, settings)
    calendar_rows: list[dict] = []
    if hasattr(adapter, "fetch_trade_calendar"):
        calendar_rows = adapter.fetch_trade_calendar(start, end)
        _upsert_calendar(calendar_rows, settings)

    stored = read_market_daily(settings=settings)
    check = None
    if run_check:
        check_end = min(end, session_asof_date())
        check = ContractQualityChecker().check(
            "market_daily",
            records=[row for row in stored if start <= row["trade_date"] <= end and row["symbol"] in set(symbols)],
            instruments=query_all("SELECT * FROM instrument_master", settings=settings),
            calendar=query_all(
                "SELECT * FROM trade_calendar WHERE market = 'CN' AND trade_date >= ? AND trade_date <= ?",
                (start, check_end),
                settings=settings,
            ),
            expected_symbols=symbols,
        )
        persist_quality_result(check, settings=settings)

    execute(
        """
        INSERT OR REPLACE INTO market_data_file
            (dataset, file_path, row_count, min_trade_date, max_trade_date, data_version)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "market_daily",
            str(parquet_path),
            len(stored),
            min((row["trade_date"] for row in stored), default=None),
            max((row["trade_date"] for row in stored), default=None),
            f"{source_id}-daily",
        ),
        settings=settings,
    )
    finished = datetime.now(timezone.utc).isoformat()
    execute(
        """
        INSERT INTO task_run (run_id, task_name, status, started_at, finished_at, message)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            "pull_daily",
            "success" if not check or check["trade_allowed"] else "blocked",
            started,
            finished,
            f"symbols={symbols} rows={len(contract_rows)} raw={raw_path}",
        ),
        settings=settings,
    )
    return {
        "source_id": source_id,
        "raw_path": str(raw_path),
        "parquet": str(market_daily_path(settings)),
        "normalized_rows": len(contract_rows),
        "quality": check,
    }


def build_adapter(source: str):
    if source == "baostock":
        from asqt.adapters.baostock_source import BaoStockAdapter

        return BaoStockAdapter()
    if source == "akshare":
        from asqt.adapters.akshare_source import AkShareAdapter

        return AkShareAdapter()
    if source == "tushare":
        from asqt.adapters.tushare_source import TushareAdapter

        return TushareAdapter()
    raise ValueError(f"unknown data source: {source}")


def check_market_daily(*, settings: Settings | None = None, expected_symbols: list[str] | None = None) -> dict:
    settings = settings or get_settings()
    initialize_database(settings)
    asof = session_asof_date()
    result = ContractQualityChecker().check(
        "market_daily",
        records=read_market_daily(settings=settings),
        instruments=query_all("SELECT * FROM instrument_master", settings=settings),
        calendar=query_all(
            "SELECT * FROM trade_calendar WHERE market = 'CN' AND trade_date <= ?",
            (asof,),
            settings=settings,
        ),
        expected_symbols=expected_symbols,
    )
    persist_quality_result(result, settings=settings)
    return result


def persist_quality_result(result: dict, *, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    execute("DELETE FROM quality_issue WHERE dataset = ? AND status = 'open'", ("market_daily",), settings=settings)
    issues = result.get("issues") or []
    if issues:
        executemany(
            """
            INSERT INTO quality_issue
                (issue_id, dataset, symbol, trade_date, check_type, severity, status, source_a, source_b, diff)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["issue_id"],
                    item["dataset"],
                    item.get("symbol"),
                    item.get("trade_date"),
                    item["check_type"],
                    item["severity"],
                    item["status"],
                    item.get("source_a"),
                    item.get("source_b"),
                    item.get("diff"),
                )
                for item in issues
            ],
            settings=settings,
        )
    if result.get("trade_allowed", True):
        execute(
            "UPDATE alert SET status = 'closed' WHERE category = 'quality' AND status = 'open'",
            settings=settings,
        )
    else:
        execute(
            """
            INSERT INTO alert (alert_id, level, category, status, title, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                "high",
                "quality",
                "open",
                "质量闸门阻断交易",
                f"block_issues={result.get('issue_count')}",
            ),
            settings=settings,
        )


def reconcile_daily(
    symbols: list[str],
    start: str,
    end: str,
    *,
    settings: Settings | None = None,
    peer_source: str = "auto",
    peer_adapter=None,
) -> dict:
    """Authenticate stored bars against a second vendor. Does not rewrite parquet."""
    from asqt.reconcile import compare_market_daily, scan_silent_factor_jumps

    settings = settings or get_settings()
    initialize_database(settings)
    stored = [
        row
        for row in read_market_daily(settings=settings)
        if start <= row["trade_date"] <= end and row["symbol"] in set(symbols)
    ]
    groups: dict[str, list[str]] = {}
    if peer_adapter is not None:
        groups[getattr(peer_adapter, "source_id", peer_source or "peer")] = list(symbols)
    elif peer_source != "auto":
        groups[peer_source] = list(symbols)
    else:
        by_symbol: dict[str, set[str]] = {}
        for row in stored:
            by_symbol.setdefault(row["symbol"], set()).add(str(row.get("source") or ""))
        for symbol in symbols:
            sources = by_symbol.get(symbol, set())
            peer = "akshare" if sources == {"baostock"} else "baostock"
            groups.setdefault(peer, []).append(symbol)

    peer_rows: list[dict] = []
    raw_paths: list[str] = []
    peer_errors: list[dict] = []
    started = datetime.now(timezone.utc).isoformat()
    normalizer = StandardNormalizer()
    for source_id, group in groups.items():
        adapter = peer_adapter or build_adapter(source_id)
        _upsert_source(adapter, settings)
        raw_rows = adapter.fetch_market_daily(group, start, end)
        peer_errors.extend(getattr(adapter, "last_errors", []) or [])
        joined = "-".join(group)
        stem = f"reconcile_{start}_{end}_{source_id}"
        if len(joined) <= 40:
            stem = f"{stem}_{joined.replace('.', '')}"
        else:
            stem = f"{stem}_{len(group)}n_{sha1(joined.encode()).hexdigest()[:12]}"
        raw_path = write_raw_json(
            getattr(adapter, "source_id", source_id),
            "market_daily_reconcile",
            {"start": start, "end": end, "symbols": group, "rows": raw_rows},
            settings=settings,
            stem=stem,
        )
        raw_paths.append(str(raw_path))
        peer_rows.extend(normalizer.normalize_market_daily(raw_rows, getattr(adapter, "source_id", source_id)))

    comparison = compare_market_daily(stored, peer_rows)
    silent = scan_silent_factor_jumps(stored)
    report = {
        "start": start,
        "end": end,
        "symbols": len(symbols),
        "peer_groups": {key: len(val) for key, val in groups.items()},
        "raw_paths": raw_paths,
        "peer_errors": peer_errors[:50],
        "peer_error_count": len(peer_errors),
        "comparison": {
            "stored_rows": comparison["stored_rows"],
            "peer_rows": comparison["peer_rows"],
            "matched_rows": comparison["matched_rows"],
            "match_rate": comparison["match_rate"],
            "mismatch_count": comparison["mismatch_count"],
        },
        "silent_factor_jumps": {
            "consistent_count": silent["consistent_count"],
            "inconsistent_count": silent["inconsistent_count"],
        },
        "mismatches": comparison["mismatches"][:200],
        "inconsistent_review": silent["inconsistent_review"][:200],
        "consistent_ex_right_sample": silent["consistent_ex_right"][:50],
    }
    persist_reconcile_result(report, comparison["mismatches"], silent["inconsistent_review"], settings=settings)
    execute(
        """
        INSERT INTO task_run (run_id, task_name, status, started_at, finished_at, message)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            "reconcile_daily",
            "success" if not comparison["mismatches"] and not silent["inconsistent_review"] else "review",
            started,
            datetime.now(timezone.utc).isoformat(),
            f"matched={comparison['matched_rows']} mismatch={comparison['mismatch_count']} silent_inconsistent={silent['inconsistent_count']}",
        ),
        settings=settings,
    )
    logs = settings.logs_dir
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = logs / f"reconcile_{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def persist_reconcile_result(
    report: dict,
    mismatches: list[dict],
    inconsistent: list[dict],
    *,
    settings: Settings,
) -> None:
    execute(
        "DELETE FROM quality_issue WHERE dataset = ? AND status = 'open'",
        ("market_daily_reconcile",),
        settings=settings,
    )
    from asqt.reconcile import collapse_adj_scale_mismatches

    rows = []
    for item in collapse_adj_scale_mismatches(mismatches)[:500]:
        rows.append(
            (
                str(uuid4()),
                "market_daily_reconcile",
                item.get("symbol"),
                item.get("trade_date"),
                "cross_source",
                "warn",
                "open",
                item.get("stored_source"),
                item.get("peer_source"),
                item.get("diff"),
            )
        )
    for item in inconsistent[:200]:
        rows.append(
            (
                str(uuid4()),
                "market_daily_reconcile",
                item.get("symbol"),
                item.get("trade_date"),
                "cross_source",
                "warn",
                "open",
                "adj_factor",
                "unadj_close",
                f"silent_jump_inconsistent factor_ratio={item.get('factor_ratio')} price_ratio={item.get('price_ratio')}",
            )
        )
    if rows:
        executemany(
            """
            INSERT INTO quality_issue
                (issue_id, dataset, symbol, trade_date, check_type, severity, status, source_a, source_b, diff)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
            settings=settings,
        )


def _upsert_source(adapter, settings: Settings) -> None:
    source_id = getattr(adapter, "source_id", "unknown")
    execute(
        """
        INSERT OR REPLACE INTO data_source
            (source_id, name, purpose, auth_status, quota, cost, owner, priority, health_status, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            source_id,
            {"baostock": "BaoStock", "akshare": "AkShare（东方财富等）", "tushare": "Tushare"}.get(source_id, source_id),
            "primary daily bars" if source_id == "baostock" else (
                "cross-source peer" if source_id == "tushare" else "backup daily bars"
            ),
            "ok",
            "free" if source_id != "tushare" else "token",
            "0 CNY" if source_id != "tushare" else "account",
            "asqt-maintainer",
            10 if source_id == "baostock" else (15 if source_id == "tushare" else 20),
            "healthy",
        ),
        settings=settings,
    )


def _upsert_instruments(rows: list[dict], settings: Settings) -> None:
    if not rows:
        return
    executemany(
        """
        INSERT OR REPLACE INTO instrument_master
            (symbol, name, instrument_type, exchange, board, list_date, delist_date, status, is_st, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        [
            (
                row["symbol"],
                row["name"],
                row["instrument_type"],
                row["exchange"],
                row.get("board"),
                row.get("list_date"),
                row.get("delist_date"),
                row["status"],
                row["is_st"],
            )
            for row in rows
        ],
        settings=settings,
    )


def _upsert_limits(rows: list[dict], settings: Settings) -> None:
    if not rows:
        return
    executemany(
        """
        INSERT OR REPLACE INTO limit_suspension
            (symbol, trade_date, limit_up, limit_down, is_suspended, reason)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["symbol"],
                row["trade_date"],
                row.get("limit_up"),
                row.get("limit_down"),
                row["is_suspended"],
                row.get("reason"),
            )
            for row in rows
        ],
        settings=settings,
    )


def _upsert_calendar(rows: list[dict], settings: Settings) -> None:
    if not rows:
        return
    open_dates = [row["trade_date"] for row in rows if int(row.get("is_open") or 0) == 1]
    prev_map: dict[str, str | None] = {}
    next_map: dict[str, str | None] = {}
    for index, day in enumerate(open_dates):
        prev_map[day] = open_dates[index - 1] if index else None
        next_map[day] = open_dates[index + 1] if index + 1 < len(open_dates) else None
    last_open = None
    forthcoming = list(open_dates)
    for row in rows:
        if int(row.get("is_open") or 0) == 1:
            last_open = row["trade_date"]
            if forthcoming and forthcoming[0] == row["trade_date"]:
                forthcoming = forthcoming[1:]
        row["prev_trade_date"] = prev_map.get(row["trade_date"]) if int(row.get("is_open") or 0) == 1 else last_open
        if int(row.get("is_open") or 0) == 1:
            row["next_trade_date"] = next_map.get(row["trade_date"])
        else:
            row["next_trade_date"] = forthcoming[0] if forthcoming else None
        row["open_time"] = "09:30" if int(row.get("is_open") or 0) == 1 else None
        row["close_time"] = "15:00" if int(row.get("is_open") or 0) == 1 else None
    executemany(
        """
        INSERT OR REPLACE INTO trade_calendar
            (trade_date, market, is_open, open_time, close_time, prev_trade_date, next_trade_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["trade_date"],
                row.get("market") or "CN",
                int(row.get("is_open") or 0),
                row.get("open_time"),
                row.get("close_time"),
                row.get("prev_trade_date"),
                row.get("next_trade_date"),
            )
            for row in rows
        ],
        settings=settings,
    )

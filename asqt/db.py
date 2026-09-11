from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.contracts import TABLE_COLUMNS
from asqt.symbols import split_symbol


SCHEMA_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS data_source (
        source_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        purpose TEXT NOT NULL,
        auth_status TEXT NOT NULL,
        quota TEXT,
        cost TEXT,
        owner TEXT,
        priority INTEGER NOT NULL DEFAULT 100,
        health_status TEXT NOT NULL DEFAULT 'unknown',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS instrument_master (
        symbol TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        instrument_type TEXT NOT NULL,
        exchange TEXT NOT NULL,
        board TEXT,
        list_date TEXT,
        delist_date TEXT,
        status TEXT NOT NULL,
        is_st INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trade_calendar (
        trade_date TEXT NOT NULL,
        market TEXT NOT NULL,
        is_open INTEGER NOT NULL,
        open_time TEXT,
        close_time TEXT,
        prev_trade_date TEXT,
        next_trade_date TEXT,
        PRIMARY KEY (trade_date, market)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS limit_suspension (
        symbol TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        limit_up REAL,
        limit_down REAL,
        is_suspended INTEGER NOT NULL DEFAULT 0,
        reason TEXT,
        PRIMARY KEY (symbol, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS factor_signal (
        trade_date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        factor_name TEXT NOT NULL,
        value REAL NOT NULL,
        model_version TEXT,
        source_run_id TEXT,
        PRIMARY KEY (trade_date, symbol, factor_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_data_file (
        dataset TEXT NOT NULL,
        file_path TEXT NOT NULL,
        row_count INTEGER NOT NULL,
        min_trade_date TEXT,
        max_trade_date TEXT,
        data_version TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (dataset, file_path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quality_issue (
        issue_id TEXT PRIMARY KEY,
        dataset TEXT NOT NULL,
        symbol TEXT,
        trade_date TEXT,
        check_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        status TEXT NOT NULL,
        source_a TEXT,
        source_b TEXT,
        diff TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS data_sync_run (
        run_id TEXT PRIMARY KEY,
        trigger TEXT NOT NULL,
        status TEXT NOT NULL,
        source TEXT,
        start_date TEXT,
        end_date TEXT,
        max_trade_date_before TEXT,
        max_trade_date_after TEXT,
        normalized_rows INTEGER,
        quality_ok INTEGER,
        trade_allowed INTEGER,
        issue_count INTEGER,
        fail_reason TEXT,
        detail TEXT,
        inflight INTEGER,
        progress_pct INTEGER,
        progress_done INTEGER,
        progress_total INTEGER,
        progress_symbol TEXT,
        started_at TEXT,
        finished_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS data_sync_lock (
        lock_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        holder TEXT,
        acquired_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS research_run (
        run_id TEXT PRIMARY KEY,
        strategy_id TEXT NOT NULL,
        status TEXT NOT NULL,
        inflight INTEGER,
        progress_pct INTEGER,
        progress_done INTEGER,
        progress_total INTEGER,
        progress_label TEXT,
        fail_reason TEXT,
        detail TEXT,
        started_at TEXT,
        finished_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS strategy_version (
        strategy_id TEXT NOT NULL,
        version TEXT NOT NULL,
        status TEXT NOT NULL,
        parameter_set_id TEXT,
        code_version TEXT,
        risk_config TEXT,
        effective_date TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (strategy_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS target_position (
        target_id TEXT PRIMARY KEY,
        trade_date TEXT NOT NULL,
        strategy_id TEXT NOT NULL,
        strategy_version TEXT NOT NULL,
        symbol TEXT NOT NULL,
        target_weight REAL NOT NULL,
        target_amount REAL,
        target_volume INTEGER,
        reason TEXT,
        data_version TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS standard_order (
        order_id TEXT PRIMARY KEY,
        idem_key TEXT NOT NULL UNIQUE,
        trade_date TEXT NOT NULL,
        strategy_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL CHECK(side IN ('BUY', 'SELL')),
        quantity INTEGER NOT NULL,
        price_type TEXT NOT NULL,
        limit_price REAL,
        valid_date TEXT NOT NULL,
        risk_tags TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS execution_fill (
        fill_id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL,
        broker_order_id TEXT,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        filled_qty INTEGER NOT NULL,
        filled_price REAL NOT NULL,
        fee REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        trade_time TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_snapshot (
        account_id TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        cash REAL NOT NULL,
        market_value REAL NOT NULL,
        total_asset REAL NOT NULL,
        position_detail TEXT NOT NULL,
        reconcile_diff TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (account_id, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_run (
        run_id TEXT PRIMARY KEY,
        task_name TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        message TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alert (
        alert_id TEXT PRIMARY KEY,
        level TEXT NOT NULL,
        category TEXT NOT NULL,
        status TEXT NOT NULL,
        title TEXT NOT NULL,
        detail TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS operation_audit (
        audit_id TEXT PRIMARY KEY,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT,
        reason TEXT,
        before_state TEXT,
        after_state TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_setting (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
)

# Columns that may be missing on databases created before the baseline hardening pass.
_DATA_SOURCE_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("quota", "TEXT"),
    ("cost", "TEXT"),
    ("owner", "TEXT"),
)
_DATA_SYNC_RUN_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("inflight", "INTEGER"),
    ("progress_pct", "INTEGER"),
    ("progress_done", "INTEGER"),
    ("progress_total", "INTEGER"),
    ("progress_symbol", "TEXT"),
)


def connect(settings: Settings | None = None) -> sqlite3.Connection:
    settings = ensure_runtime_dirs(settings or get_settings())
    conn = sqlite3.connect(settings.database_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _migrate_schema(conn: sqlite3.Connection) -> None:
    existing = _existing_columns(conn, "data_source")
    for column, col_type in _DATA_SOURCE_EXTRA_COLUMNS:
        if column not in existing:
            conn.execute(f"ALTER TABLE data_source ADD COLUMN {column} {col_type}")
    if "data_sync_run" in {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }:
        sync_cols = _existing_columns(conn, "data_sync_run")
        for column, col_type in _DATA_SYNC_RUN_EXTRA_COLUMNS:
            if column not in sync_cols:
                conn.execute(f"ALTER TABLE data_sync_run ADD COLUMN {column} {col_type}")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS data_sync_run_one_inflight
        ON data_sync_run(inflight) WHERE inflight = 1
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS research_run_one_inflight
        ON research_run(inflight) WHERE inflight = 1
        """
    )


def initialize_database(settings: Settings | None = None) -> Path:
    settings = ensure_runtime_dirs(settings or get_settings())
    with connect(settings) as conn:
        for statement in SCHEMA_SQL:
            conn.execute(statement)
        _migrate_schema(conn)
        conn.commit()
    return settings.database_path


def table_columns(table: str, settings: Settings | None = None) -> list[str]:
    with connect(settings) as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row["name"] for row in rows]


def assert_contract_schema(settings: Settings | None = None) -> None:
    """Raise AssertionError if required contract columns are missing."""
    for table, expected in TABLE_COLUMNS.items():
        actual = set(table_columns(table, settings=settings))
        missing = [column for column in expected if column not in actual]
        if missing:
            raise AssertionError(f"{table} missing columns: {missing}")


def execute(sql: str, params: Iterable[object] = (), settings: Settings | None = None) -> None:
    with connect(settings) as conn:
        conn.execute(sql, tuple(params))
        conn.commit()


def executemany(sql: str, rows: Iterable[Iterable[object]], settings: Settings | None = None) -> None:
    with connect(settings) as conn:
        conn.executemany(sql, [tuple(row) for row in rows])
        conn.commit()


def query_all(sql: str, params: Iterable[object] = (), settings: Settings | None = None) -> list[dict]:
    with connect(settings) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(row) for row in rows]


QUALITY_SORT_COLUMNS = {
    "created_at": "q.created_at",
    "symbol": "q.symbol",
    "exchange": "upper(substr(q.symbol, instr(q.symbol, '.') + 1))",
    "trade_date": "q.trade_date",
    "check_type": "q.check_type",
    "severity": "q.severity",
    "status": "q.status",
}


def _quality_issue_status_filter(status: str) -> tuple[str, tuple[object, ...]]:
    key = (status or "open").strip().lower()
    if key == "all":
        return "1=1", ()
    if key == "closed":
        return "q.status = ?", ("closed",)
    return "q.status != ?", ("closed",)


def _quality_issue_filters(
    *,
    status: str,
    trade_date: str | None,
    severity: str | None,
    code: str | None,
) -> tuple[str, tuple[object, ...]]:
    clauses: list[str] = []
    params: list[object] = []
    status_sql, status_params = _quality_issue_status_filter(status)
    clauses.append(status_sql)
    params.extend(status_params)
    date_key = (trade_date or "").strip()
    if date_key:
        clauses.append("q.trade_date = ?")
        params.append(date_key)
    severity_key = (severity or "").strip().lower()
    if severity_key:
        clauses.append("q.severity = ?")
        params.append(severity_key)
    code_key = (code or "").strip()
    if code_key:
        clauses.append(
            "instr(lower(ifnull(q.symbol, '') || ' ' || ifnull(i.name, '')), lower(?)) > 0"
        )
        params.append(code_key)
    return " AND ".join(clauses), tuple(params)


def list_quality_issues(
    *,
    page: int = 1,
    page_size: int = 20,
    status: str = "open",
    trade_date: str | None = None,
    severity: str | None = None,
    code: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    settings: Settings | None = None,
) -> dict:
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    where, params = _quality_issue_filters(
        status=status,
        trade_date=trade_date,
        severity=severity,
        code=code,
    )
    sort_key = (sort or "created_at").strip().lower()
    sort_col = QUALITY_SORT_COLUMNS.get(sort_key, "q.created_at")
    sort_dir = "ASC" if (order or "desc").strip().lower() == "asc" else "DESC"
    from_sql = "FROM quality_issue q LEFT JOIN instrument_master i ON i.symbol = q.symbol"
    total = query_all(
        f"SELECT COUNT(*) AS c {from_sql} WHERE {where}",
        params,
        settings=settings,
    )[0]["c"]
    pages = max(1, (total + page_size - 1) // page_size) if total else 1
    if page > pages:
        page = pages
    offset = (page - 1) * page_size
    items = query_all(
        f"""
        SELECT q.issue_id, q.dataset, q.symbol, q.trade_date, q.check_type, q.severity, q.status,
               q.source_a, q.source_b, q.diff, q.created_at, q.updated_at
        {from_sql}
        WHERE {where}
        ORDER BY {sort_col} {sort_dir}, q.issue_id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, page_size, offset),
        settings=settings,
    )
    from asqt.quality import format_issue_diff

    for item in items:
        code, exchange = split_symbol(item.get("symbol") or "")
        item["code"] = code or None
        item["exchange"] = exchange or None
        item["diff_label"] = format_issue_diff(item.get("diff"), check_type=item.get("check_type"))
    status_key = (status or "open").strip().lower()
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "status": "all" if status_key == "all" else ("closed" if status_key == "closed" else "open"),
        "trade_date": (trade_date or "").strip() or None,
        "severity": (severity or "").strip().lower() or None,
        "code": (code or "").strip() or None,
        "sort": sort_key if sort_key in QUALITY_SORT_COLUMNS else "created_at",
        "order": "asc" if sort_dir == "ASC" else "desc",
    }


def close_quality_issue(issue_id: str, *, settings: Settings | None = None) -> dict | None:
    rows = query_all(
        "SELECT issue_id, status, severity FROM quality_issue WHERE issue_id = ?",
        (issue_id,),
        settings=settings,
    )
    if not rows:
        return None
    execute(
        "UPDATE quality_issue SET status = 'closed', updated_at = CURRENT_TIMESTAMP WHERE issue_id = ?",
        (issue_id,),
        settings=settings,
    )
    rows[0]["status"] = "closed"
    return rows[0]

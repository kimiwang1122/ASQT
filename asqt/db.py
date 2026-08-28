from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.contracts import TABLE_COLUMNS


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
)

# Columns that may be missing on databases created before the baseline hardening pass.
_DATA_SOURCE_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("quota", "TEXT"),
    ("cost", "TEXT"),
    ("owner", "TEXT"),
)


def connect(settings: Settings | None = None) -> sqlite3.Connection:
    settings = ensure_runtime_dirs(settings or get_settings())
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _migrate_schema(conn: sqlite3.Connection) -> None:
    existing = _existing_columns(conn, "data_source")
    for column, col_type in _DATA_SOURCE_EXTRA_COLUMNS:
        if column not in existing:
            conn.execute(f"ALTER TABLE data_source ADD COLUMN {column} {col_type}")


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


def query_all(sql: str, params: Iterable[object] = (), settings: Settings | None = None) -> list[dict]:
    with connect(settings) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(row) for row in rows]

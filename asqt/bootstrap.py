from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from asqt.config import Settings, get_settings
from asqt.db import connect, initialize_database
from asqt.storage import market_daily_path, read_market_daily, write_market_daily


DEMO_MARKET_DAILY = [
    {
        "symbol": "000001.SZ",
        "trade_date": "2026-08-20",
        "open": 11.20,
        "high": 11.46,
        "low": 11.12,
        "close": 11.38,
        "volume": 124000000,
        "amount": 1406000000.0,
        "adj_factor": 1.0,
        "source": "demo",
        "version": "demo-20260826",
    },
    {
        "symbol": "000001.SZ",
        "trade_date": "2026-08-21",
        "open": 11.38,
        "high": 11.55,
        "low": 11.31,
        "close": 11.42,
        "volume": 103000000,
        "amount": 1178000000.0,
        "adj_factor": 1.0,
        "source": "demo",
        "version": "demo-20260826",
    },
    {
        "symbol": "510300.SH",
        "trade_date": "2026-08-20",
        "open": 4.08,
        "high": 4.13,
        "low": 4.06,
        "close": 4.11,
        "volume": 880000000,
        "amount": 3611000000.0,
        "adj_factor": 1.0,
        "source": "demo",
        "version": "demo-20260826",
    },
    {
        "symbol": "510300.SH",
        "trade_date": "2026-08-21",
        "open": 4.11,
        "high": 4.15,
        "low": 4.09,
        "close": 4.12,
        "volume": 790000000,
        "amount": 3257000000.0,
        "adj_factor": 1.0,
        "source": "demo",
        "version": "demo-20260826",
    },
]


def seed_demo(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    initialize_database(settings)
    existing: list[dict] = []
    current_path = market_daily_path(settings)
    if current_path.exists():
        existing = read_market_daily(settings=settings)
    skip_market = len(existing) > len(DEMO_MARKET_DAILY)
    if skip_market:
        parquet_path = current_path
    else:
        parquet_path = write_market_daily(DEMO_MARKET_DAILY, settings)
    now = datetime.now(timezone.utc).isoformat()

    with connect(settings) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO data_source
                (source_id, name, purpose, auth_status, quota, cost, owner, priority, health_status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                "demo",
                "Demo Local Dataset",
                "baseline acceptance data",
                "local",
                "unlimited-local",
                "0 CNY",
                "asqt-maintainer",
                100,
                "healthy",
            ),
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO instrument_master
                (symbol, name, instrument_type, exchange, board, list_date, status, is_st, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                ("000001.SZ", "平安银行", "stock", "SZ", "main", "1991-04-03", "listed", 0),
                ("510300.SH", "沪深300ETF", "etf", "SH", "broad_index", "2012-05-28", "listed", 0),
            ],
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO trade_calendar
                (trade_date, market, is_open, open_time, close_time, prev_trade_date, next_trade_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-08-20", "CN", 1, "09:30", "15:00", "2026-08-19", "2026-08-21"),
                ("2026-08-21", "CN", 1, "09:30", "15:00", "2026-08-20", "2026-08-24"),
                ("2026-08-22", "CN", 0, None, None, "2026-08-21", "2026-08-24"),
            ],
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO limit_suspension
                (symbol, trade_date, limit_up, limit_down, is_suspended, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("000001.SZ", "2026-08-20", 12.52, 10.24, 0, None),
                ("000001.SZ", "2026-08-21", 12.52, 10.24, 0, None),
                ("510300.SH", "2026-08-20", 4.52, 3.70, 0, None),
                ("510300.SH", "2026-08-21", 4.52, 3.70, 0, None),
            ],
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO factor_signal
                (trade_date, symbol, factor_name, value, model_version, source_run_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("2026-08-21", "000001.SZ", "momentum_20d", 0.12, "demo-factor-v0", "seed-demo"),
        )
        if not skip_market:
            conn.execute(
                """
                INSERT OR REPLACE INTO market_data_file
                    (dataset, file_path, row_count, min_trade_date, max_trade_date, data_version)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "market_daily",
                    str(parquet_path),
                    len(DEMO_MARKET_DAILY),
                    "2026-08-20",
                    "2026-08-21",
                    "demo-20260826",
                ),
            )
        conn.execute(
            """
            INSERT INTO task_run
                (run_id, task_name, status, started_at, finished_at, message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                "seed_demo",
                "success",
                now,
                now,
                "Skipped overwriting existing market_daily" if skip_market else "Demo baseline data seeded",
            ),
        )
        conn.commit()

    market_rows = len(existing) if skip_market else len(DEMO_MARKET_DAILY)
    return {
        "database": str(settings.database_path),
        "parquet": str(parquet_path),
        "layout": settings.layout(),
        "market_daily_rows": market_rows,
        "skipped_market_daily": skip_market,
        "trade_calendar_rows": 3,
        "limit_suspension_rows": 4,
        "factor_signal_rows": 1,
    }

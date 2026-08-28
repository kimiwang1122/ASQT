from __future__ import annotations

import argparse
import json

from asqt.bootstrap import seed_demo
from asqt.config import get_settings
from asqt.db import initialize_database, query_all
from asqt.ports import PORT_NAMES


def cmd_init_db() -> None:
    settings = get_settings()
    path = initialize_database(settings)
    print(
        json.dumps(
            {"database": str(path), "layout": settings.layout()},
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_seed_demo() -> None:
    print(json.dumps(seed_demo(get_settings()), ensure_ascii=False, indent=2))


def cmd_status() -> None:
    settings = get_settings()
    initialize_database(settings)
    result = {
        "database": str(settings.database_path),
        "layout": settings.layout(),
        "ports": list(PORT_NAMES),
        "data_sources": query_all(
            "SELECT source_id, health_status, quota, cost, owner FROM data_source",
            settings=settings,
        ),
        "instruments": query_all(
            "SELECT symbol, instrument_type, status FROM instrument_master",
            settings=settings,
        ),
        "market_files": query_all(
            "SELECT dataset, row_count, min_trade_date, max_trade_date FROM market_data_file",
            settings=settings,
        ),
        "trade_calendar": query_all(
            "SELECT COUNT(*) AS rows FROM trade_calendar",
            settings=settings,
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="asqt")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("seed-demo")
    subparsers.add_parser("status")
    args = parser.parse_args()

    if args.command == "init-db":
        cmd_init_db()
    elif args.command == "seed-demo":
        cmd_seed_demo()
    elif args.command == "status":
        cmd_status()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json

from datetime import date, timedelta

from asqt.bootstrap import seed_demo
from asqt.config import get_settings
from asqt.db import initialize_database, query_all
from asqt.pipeline import check_market_daily, pull_daily, pull_daily_append, reconcile_daily
from asqt.sync import run_sync_job
from asqt.ports import port_entries
from asqt.research_engine import LocalResearchEngine, run_p2_acceptance_suite
from asqt.strategies import STRATEGY_SPECS
from asqt.universe import apply_universe, poc_symbols


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
        "ports": port_entries(),
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
            "SELECT COUNT(*) AS c FROM trade_calendar",
            settings=settings,
        ),
        "open_quality_issues": query_all(
            "SELECT COUNT(*) AS c FROM quality_issue WHERE status = 'open'",
            settings=settings,
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_universe_load() -> None:
    result = apply_universe(get_settings())
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_pull_daily(symbols: list[str], start: str, end: str, source: str) -> None:
    result = pull_daily(symbols, start, end, settings=get_settings(), source=source)
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def cmd_sync_daily(*, source: str, skip_reconcile: bool, overlap_days: int, lookback_days: int) -> None:
    settings = get_settings()
    sync = run_sync_job(trigger="manual", source=source, settings=settings, overlap_days=overlap_days)
    reconcile = None
    if not skip_reconcile and sync.get("status") in {"success", "skipped"}:
        symbols = poc_symbols(settings)
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=lookback_days)).isoformat()
        reconcile = reconcile_daily(symbols, start, end, settings=settings, peer_source="auto")
    print(json.dumps(_jsonable({"sync": sync, "reconcile": reconcile}), ensure_ascii=False, indent=2))


def cmd_reconcile(symbols: list[str], start: str, end: str, peer: str) -> None:
    result = reconcile_daily(symbols, start, end, settings=get_settings(), peer_source=peer)
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def cmd_check_quality() -> None:
    result = check_market_daily(settings=get_settings())
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def cmd_research_backtest(strategy: str) -> None:
    settings = get_settings()
    if strategy == "all":
        result = run_p2_acceptance_suite(settings)
    else:
        spec = STRATEGY_SPECS[strategy]
        result = LocalResearchEngine(settings).run_backtest(strategy, spec["parameter_set_id"], "auto")
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(prog="asqt")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("seed-demo")
    subparsers.add_parser("status")
    subparsers.add_parser("universe-load")
    pull = subparsers.add_parser("pull-daily")
    pull.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="ASQT symbol such as 000001.SZ; repeatable",
    )
    pull.add_argument("--universe", action="store_true", help="use docs/p0 POC universe CSVs")
    pull.add_argument("--source", default="baostock", choices=("baostock", "akshare", "tushare"))
    pull.add_argument("--start", help="YYYY-MM-DD")
    pull.add_argument("--end", help="YYYY-MM-DD")
    pull.add_argument("--append", action="store_true", help="from latest stored bar to today (overlap last day)")
    pull.add_argument("--lookback-days", type=int, help="rolling window ending today")
    pull.add_argument("--overlap-days", type=int, default=1, help="re-fetch this many trailing days on --append")
    subparsers.add_parser("check-quality")
    recon = subparsers.add_parser("reconcile")
    recon.add_argument("--symbol", action="append", dest="symbols")
    recon.add_argument("--universe", action="store_true")
    recon.add_argument("--start", help="YYYY-MM-DD")
    recon.add_argument("--end", help="YYYY-MM-DD")
    recon.add_argument("--lookback-days", type=int, help="rolling window ending today; for cron")
    recon.add_argument("--peer", default="auto", choices=("auto", "baostock", "akshare", "tushare"))
    sync = subparsers.add_parser("sync-daily")
    sync.add_argument("--source", default="baostock", choices=("baostock", "akshare", "tushare"))
    sync.add_argument("--overlap-days", type=int, default=1)
    sync.add_argument("--lookback-days", type=int, default=14, help="reconcile window")
    sync.add_argument("--skip-reconcile", action="store_true")
    research = subparsers.add_parser("research-backtest")
    research.add_argument(
        "--strategy",
        default="all",
        choices=("all", *STRATEGY_SPECS.keys()),
    )
    args = parser.parse_args()

    if args.command == "init-db":
        cmd_init_db()
    elif args.command == "seed-demo":
        cmd_seed_demo()
    elif args.command == "status":
        cmd_status()
    elif args.command == "universe-load":
        cmd_universe_load()
    elif args.command == "pull-daily":
        symbols = list(args.symbols or [])
        if args.universe:
            symbols = poc_symbols(get_settings())
        if not symbols:
            parser.error("provide --symbol and/or --universe")
        if args.append:
            result = pull_daily_append(
                symbols,
                source=args.source,
                overlap_days=args.overlap_days,
            )
            print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))
        elif args.lookback_days:
            end = args.end or date.today().isoformat()
            start = args.start or (date.today() - timedelta(days=args.lookback_days)).isoformat()
            cmd_pull_daily(symbols, start, end, args.source)
        elif args.start and args.end:
            cmd_pull_daily(symbols, args.start, args.end, args.source)
        else:
            parser.error("provide --start/--end, --append, or --lookback-days")
    elif args.command == "sync-daily":
        cmd_sync_daily(
            source=args.source,
            skip_reconcile=args.skip_reconcile,
            overlap_days=args.overlap_days,
            lookback_days=args.lookback_days,
        )
    elif args.command == "check-quality":
        cmd_check_quality()
    elif args.command == "reconcile":
        symbols = list(args.symbols or [])
        if args.universe or not symbols:
            symbols = poc_symbols(get_settings())
        end = args.end or date.today().isoformat()
        if args.start:
            start = args.start
        elif args.lookback_days:
            start = (date.today() - timedelta(days=args.lookback_days)).isoformat()
        else:
            parser.error("provide --start/--end or --lookback-days")
        cmd_reconcile(symbols, start, end, args.peer)
    elif args.command == "research-backtest":
        cmd_research_backtest(args.strategy)


if __name__ == "__main__":
    main()

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
from asqt.research_engine import LocalResearchEngine, LocalStrategyService, run_p2_acceptance_suite
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


def cmd_sync_daily(
    *,
    source: str,
    skip_reconcile: bool,
    overlap_days: int,
    lookback_days: int,
    trigger: str = "manual",
) -> None:
    settings = get_settings()
    kind = (trigger or "manual").strip().lower()
    if kind not in {"manual", "cron", "scheduler"}:
        kind = "manual"
    sync = run_sync_job(trigger=kind, source=source, settings=settings, overlap_days=overlap_days)
    reconcile = None
    if not skip_reconcile and sync.get("status") in {"success", "skipped"}:
        from asqt.reconcile_jobs import run_reconcile_job

        reconcile = run_reconcile_job(
            trigger=kind,
            lookback_days=lookback_days,
            peer_source="auto",
            settings=settings,
        )
    print(json.dumps(_jsonable({"sync": sync, "reconcile": reconcile}), ensure_ascii=False, indent=2))


def cmd_reconcile(symbols: list[str], start: str, end: str, peer: str) -> None:
    result = reconcile_daily(
        symbols,
        start,
        end,
        settings=get_settings(),
        peer_source=peer,
        notify=True,
    )
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


def cmd_paper_admit(strategy: str, reason: str) -> None:
    service = LocalStrategyService(get_settings())
    ids = list(STRATEGY_SPECS) if strategy == "all" else [strategy]
    result = [service.admit_to_paper(item, reason) for item in ids]
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def cmd_paper_run(strategy: str, days: int) -> None:
    from asqt.paper import run_paper_days

    result = run_paper_days(strategy_id=strategy, days=days, settings=get_settings())
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def cmd_paper_daily() -> None:
    from asqt.paper import advance_paper_session

    result = advance_paper_session(trigger="cli", settings=get_settings())
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def cmd_cash_reconcile() -> None:
    from asqt.paper_reconcile_jobs import run_cash_reconcile_job

    result = run_cash_reconcile_job(trigger="manual", settings=get_settings(), notify=True)
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def cmd_tune(strategy: str, grid_json: str | None) -> None:
    from asqt.tune import run_tune

    grid = None
    if grid_json:
        grid = json.loads(grid_json)
        if not isinstance(grid, list):
            raise SystemExit("--grid must be a JSON array of param objects")
    result = run_tune(strategy, grid=grid, settings=get_settings())
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def cmd_paper_reset(strategy: str) -> None:
    from asqt.paper import reset_paper_account

    result = reset_paper_account(strategy_id=strategy, settings=get_settings())
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def cmd_alert_demo(*, live: bool) -> None:
    from asqt.alert_demo import run_alert_demo

    result = run_alert_demo(live=live)
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def cmd_kill_switch(engaged: bool, reason: str) -> None:
    from asqt.ops import set_kill_switch

    print(json.dumps(set_kill_switch(engaged, reason), ensure_ascii=False, indent=2))


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
    sync.add_argument(
        "--trigger",
        default="manual",
        choices=("manual", "cron", "scheduler"),
        help="cron 兜底请用 cron，便于和进程内 auto 区分",
    )
    research = subparsers.add_parser("research-backtest")
    research.add_argument(
        "--strategy",
        default="all",
        choices=("all", *STRATEGY_SPECS.keys()),
    )
    tune = subparsers.add_parser("tune", help="IS grid search → OOS report; does not mutate paper params")
    tune.add_argument("--strategy", required=True, choices=tuple(STRATEGY_SPECS.keys()))
    tune.add_argument(
        "--grid",
        default=None,
        help='JSON array of param objects, e.g. \'[{"lookback":20,"top_k":5}]\'',
    )
    admit = subparsers.add_parser("paper-admit")
    admit.add_argument("--strategy", default="all", choices=("all", *STRATEGY_SPECS.keys()))
    admit.add_argument("--reason", default="admit to paper")
    paper = subparsers.add_parser("paper-run")
    paper.add_argument("--strategy", default="all", choices=("all", *STRATEGY_SPECS.keys()))
    paper.add_argument("--days", type=int, default=20)
    daily = subparsers.add_parser("paper-daily")
    subparsers.add_parser("cash-reconcile")
    reset = subparsers.add_parser("paper-reset")
    reset.add_argument("--strategy", default="all", choices=("all", *STRATEGY_SPECS.keys()))
    kill = subparsers.add_parser("kill-switch")
    kill.add_argument("--on", action="store_true")
    kill.add_argument("--off", action="store_true")
    kill.add_argument("--reason", required=True)
    demo = subparsers.add_parser("alert-demo")
    demo.add_argument(
        "--dry-run",
        action="store_true",
        help="只走隔离库与本地 jsonl，不推飞书",
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
            trigger=args.trigger,
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
    elif args.command == "tune":
        cmd_tune(args.strategy, args.grid)
    elif args.command == "paper-admit":
        cmd_paper_admit(args.strategy, args.reason)
    elif args.command == "paper-run":
        cmd_paper_run(args.strategy, args.days)
    elif args.command == "paper-daily":
        cmd_paper_daily()
    elif args.command == "cash-reconcile":
        cmd_cash_reconcile()
    elif args.command == "paper-reset":
        cmd_paper_reset(args.strategy)
    elif args.command == "kill-switch":
        if args.on == args.off:
            parser.error("provide exactly one of --on or --off")
        cmd_kill_switch(bool(args.on), args.reason)
    elif args.command == "alert-demo":
        cmd_alert_demo(live=not args.dry_run)


if __name__ == "__main__":
    main()

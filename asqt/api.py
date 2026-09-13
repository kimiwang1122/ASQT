from __future__ import annotations

from contextlib import asynccontextmanager
import json
import threading

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from asqt.bootstrap import seed_demo
from asqt.config import get_settings
from asqt.db import initialize_database, list_quality_issues, close_quality_issue, query_all
from asqt.ports import port_entries
from asqt.storage import market_daily_path, read_market_daily, read_market_snapshot
from asqt.research_jobs import (
    ResearchBusy,
    active_research_run,
    get_research_run,
    recover_orphaned_research_runs,
    start_backtest_job,
)
from asqt.factor_jobs import (
    FactorBusy,
    active_factor_run,
    get_factor_run,
    recover_orphaned_factor_runs,
    start_factor_compute_job,
)
from asqt.sync import (
    Busy,
    abort_inflight_sync_runs,
    active_sync_run,
    auto_loop,
    auto_sync_enabled,
    get_sync_run,
    list_sync_runs,
    recover_orphaned_sync_runs,
    scheduler_snapshot,
    start_sync_job,
)

GATE_DENY_MESSAGES = {
    "kill_switch": "急停已打开，不能准入或恢复模拟。请先到交易页关闭急停后再试。",
    "quality_block": "存在未关闭的质量阻断，不能准入或恢复模拟。",
    "missing_experiment": "缺少最近一次回测报告，不能准入或恢复模拟。请先重跑回测。",
    "experiment_not_ok": "最近一次回测未通过，不能准入或恢复模拟。",
    "missing_version_pins": "回测报告缺少参数组或数据版本钉扎，不能准入或恢复模拟。",
    "lifecycle change requires a reason": "改生命周期必须填写原因。",
    "kill switch change requires a reason": "请填写急停原因（不能全是空格）。",
    "clear strategy halt requires a reason": "请填写解除单策略平仓的原因（不能全是空格）。",
    "paper_busy": "模拟盘运行中，请勿重复提交",
}


def _kill_open_reason(settings) -> str | None:
    rows = query_all(
        """
        SELECT title, detail FROM alert
        WHERE category = 'kill_switch' AND status = 'open'
        ORDER BY created_at DESC LIMIT 1
        """,
        settings=settings,
    )
    if not rows:
        return None
    return (rows[0].get("detail") or rows[0].get("title") or "").strip() or None


def http_exc_from_gate(exc: Exception, *, status_code: int, settings=None) -> HTTPException:
    code = str(exc).strip()
    message = GATE_DENY_MESSAGES.get(code)
    extra: dict[str, str] = {}
    if code == "kill_switch":
        reason = _kill_open_reason(settings)
        if reason:
            extra["kill_reason"] = reason
            message = f"{message} 当前原因：{reason}"
    if message is None:
        if "has no version" in code:
            code = "no_version"
            message = "该策略还没有版本，不能改生命周期。请先重跑回测。"
        elif "cannot generate target positions" in code:
            code = "not_orderable"
            message = "当前状态不能生成可下单目标仓。仅「模拟」状态可以。"
        else:
            message = code
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra})



class MockOrderBody(BaseModel):
    symbol: str
    side: str = "BUY"
    quantity: int = Field(default=100, ge=1)
    trade_date: str | None = None


class SyncBody(BaseModel):
    source: str = "baostock"
    overlap_days: int = Field(default=1, ge=1, le=10)


class RecordsUpsertBody(BaseModel):
    rows: list[dict] = Field(default_factory=list)


class RecordsPullBody(BaseModel):
    source: str = "baostock"
    symbols: list[str] | None = None
    overlap_days: int = Field(default=1, ge=1, le=10)
    start: str | None = None
    end: str | None = None
    run_check: bool = True
    today: str | None = None


class LifecycleBody(BaseModel):
    action: str
    reason: str


class KillSwitchBody(BaseModel):
    engaged: bool
    reason: str


class PaperTradingBody(BaseModel):
    enabled: bool
    reason: str = "settings"


class PaperConfigBody(BaseModel):
    initial_cash: float = Field(default=1_000_000, ge=10_000, le=100_000_000)
    commission_per_myriad: float = Field(default=2.5, ge=0, le=50)
    portfolio_drawdown_stop_pct: float = Field(default=12.0, ge=0, le=80)
    strategy_drawdown_stop_pct: float = Field(default=12.0, ge=0, le=80)
    drawdown_warn_pct: float = Field(default=8.0, ge=0, le=80)


class PaperRunBody(BaseModel):
    strategy_id: str = "all"
    strategy_ids: list[str] | None = None
    # Hard ceiling for request validation; runtime still caps to available sessions - 1.
    days: int = Field(default=20, ge=2, le=2000)
    background: bool = True
    mode: str = "sequential"


class PaperHaltClearBody(BaseModel):
    strategy_id: str
    reason: str


class AlertCloseBatchBody(BaseModel):
    alert_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class TagUpsertBody(BaseModel):
    rows: list[dict] = Field(default_factory=list)
    actor: str = "operator"


class PaperOverrideBody(BaseModel):
    strategy_id: str
    symbol: str
    action: str
    weight: float | None = None
    reason: str | None = None
    actor: str = "operator"


class PaperOverrideDeleteBody(BaseModel):
    strategy_id: str
    symbol: str
    actor: str = "operator"
    reason: str | None = None


class EventsImportBody(BaseModel):
    rows: list[dict] | None = None
    path: str | None = None


class EventsPullBody(BaseModel):
    source: str = "tushare"
    symbols: list[str] | None = None
    start: str | None = None
    end: str | None = None


def create_app() -> FastAPI:
    settings = get_settings()
    initialize_database(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        stop = threading.Event()
        _app.state.sync_stop = stop
        recover_orphaned_sync_runs(settings)
        recover_orphaned_research_runs(settings)
        recover_orphaned_factor_runs(settings)
        from asqt.event_jobs import recover_orphaned_event_pull_runs

        recover_orphaned_event_pull_runs(settings)
        from asqt.paper_jobs import recover_orphaned_paper_runs
        from asqt.paper_reconcile_jobs import recover_orphaned_cash_reconcile_runs
        from asqt.reconcile_jobs import recover_orphaned_reconcile_runs

        recover_orphaned_paper_runs(settings)
        recover_orphaned_reconcile_runs(settings)
        recover_orphaned_cash_reconcile_runs(settings)
        if auto_sync_enabled():
            thread = threading.Thread(
                target=auto_loop,
                args=(stop, settings),
                daemon=True,
                name="asqt-sync-auto",
            )
            thread.start()
            _app.state.sync_thread = thread
        yield
        stop.set()

    app = FastAPI(title="ASQT", version="0.1.0", lifespan=lifespan)
    assets_dir = settings.frontend_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(settings.frontend_dir / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "database_exists": settings.database_path.exists(),
            "database_path": str(settings.database_path),
            "market_daily_exists": market_daily_path(settings).exists(),
            "layout": settings.layout(),
        }

    @app.post("/api/admin/bootstrap")
    def bootstrap() -> dict:
        return seed_demo(settings)

    @app.get("/api/status")
    def status() -> dict:
        data_sources = query_all("SELECT COUNT(*) AS c FROM data_source", settings=settings)[0]["c"]
        instruments = query_all("SELECT COUNT(*) AS c FROM instrument_master", settings=settings)[0]["c"]
        files = query_all("SELECT * FROM market_data_file ORDER BY created_at DESC", settings=settings)
        open_quality_blocks = query_all(
            "SELECT COUNT(*) AS c FROM quality_issue WHERE status = 'open' AND severity = 'block'",
            settings=settings,
        )[0]["c"]
        open_quality_warns = query_all(
            "SELECT COUNT(*) AS c FROM quality_issue WHERE status = 'open' AND severity = 'warn'",
            settings=settings,
        )[0]["c"]
        open_quality_issues = open_quality_blocks + open_quality_warns
        raw_tasks = query_all(
            "SELECT * FROM task_run ORDER BY created_at DESC LIMIT 40",
            settings=settings,
        )
        # paper-run is a shadow ledger when paper-run-job already exists; hide it from the overview.
        tasks = []
        for row in raw_tasks:
            if row.get("task_name") == "paper-run":
                continue
            item = dict(row)
            if item.get("task_name") == "paper-run-job" and item.get("status") == "failed":
                try:
                    message = json.loads(item.get("message") or "{}")
                except (TypeError, json.JSONDecodeError):
                    message = {}
                reasons = (message.get("result") or {}).get("incomplete_reasons") or []
                fail = str(message.get("fail_reason") or "")
                if reasons or "急停" in fail or "未完整" in fail:
                    item["status"] = "partial"
            tasks.append(item)
            if len(tasks) >= 5:
                break
        open_alerts = query_all(
            "SELECT COUNT(*) AS c FROM alert WHERE status = 'open'",
            settings=settings,
        )[0]["c"]
        calendar_count = query_all("SELECT COUNT(*) AS c FROM trade_calendar", settings=settings)[0]["c"]
        limit_count = query_all("SELECT COUNT(*) AS c FROM limit_suspension", settings=settings)[0]["c"]
        factor_count = query_all("SELECT COUNT(*) AS c FROM factor_signal", settings=settings)[0]["c"]
        from asqt.ops import kill_engaged, paper_trading_enabled
        from asqt.paper import max_paper_run_days

        return {
            "data_sources": data_sources,
            "instruments": instruments,
            "market_files": files,
            "open_quality_issues": open_quality_issues,
            "open_quality_blocks": open_quality_blocks,
            "open_quality_warns": open_quality_warns,
            "open_alerts": open_alerts,
            "recent_tasks": tasks,
            "trade_calendar_rows": calendar_count,
            "limit_suspension_rows": limit_count,
            "factor_signal_rows": factor_count,
            "kill_switch": kill_engaged(settings),
            "paper_trading": paper_trading_enabled(settings),
            "max_paper_days": max_paper_run_days(settings),
            "ports": port_entries(),
            "layout": settings.layout(),
        }

    @app.get("/api/layout")
    def layout() -> dict:
        return settings.layout()

    @app.get("/api/ports")
    def ports() -> list[dict]:
        return port_entries()

    @app.get("/api/data-sources")
    def data_sources() -> list[dict]:
        return query_all("SELECT * FROM data_source ORDER BY priority, source_id", settings=settings)

    @app.get("/api/instruments")
    def instruments() -> list[dict]:
        return query_all("SELECT * FROM instrument_master ORDER BY symbol", settings=settings)

    @app.get("/api/calendar")
    def calendar(market: str = Query(default="CN")) -> list[dict]:
        return query_all(
            "SELECT * FROM trade_calendar WHERE market = ? ORDER BY trade_date",
            (market,),
            settings=settings,
        )

    @app.get("/api/limit-suspension")
    def limit_suspension(
        symbol: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=5000),
    ) -> list[dict]:
        if symbol:
            rows = query_all(
                "SELECT * FROM limit_suspension WHERE symbol = ? ORDER BY trade_date DESC LIMIT ?",
                (symbol, limit),
                settings=settings,
            )
            return rows
        return query_all(
            "SELECT * FROM limit_suspension ORDER BY trade_date DESC, symbol LIMIT ?",
            (limit,),
            settings=settings,
        )

    @app.get("/api/factors")
    def factors(
        trade_date: str | None = Query(default=None),
        factor_name: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=200),
        limit: int | None = Query(default=None, ge=1, le=5000),
    ) -> dict:
        """List factor_signal rows with fuzzy name/symbol match and pagination.

        ``limit`` is accepted for backward compatibility: when set without an
        explicit page flow, it caps the page size (legacy clients used limit only).
        """
        clauses: list[str] = []
        params: list[object] = []
        if trade_date:
            clauses.append("trade_date = ?")
            params.append(trade_date)
        if factor_name:
            clauses.append("factor_name LIKE ?")
            params.append(f"%{factor_name.strip()}%")
        if symbol:
            clauses.append("symbol LIKE ?")
            params.append(f"%{symbol.strip()}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total_row = query_all(
            f"SELECT COUNT(*) AS c FROM factor_signal {where}",
            tuple(params),
            settings=settings,
        )
        total = int(total_row[0]["c"]) if total_row else 0
        size = int(limit) if limit is not None else int(page_size)
        size = max(1, min(size, 200 if limit is None else 5000))
        pages = max(1, (total + size - 1) // size) if total else 1
        page_n = min(max(1, int(page)), pages)
        offset = (page_n - 1) * size
        items = query_all(
            f"""
            SELECT * FROM factor_signal {where}
            ORDER BY trade_date DESC, symbol, factor_name
            LIMIT ? OFFSET ?
            """,
            tuple(params) + (size, offset),
            settings=settings,
        )
        return {
            "items": items,
            "total": total,
            "page": page_n,
            "pages": pages,
            "page_size": size,
        }

    @app.get("/api/factors/compute/active")
    def factors_compute_active() -> dict:
        return {"active": active_factor_run(settings)}

    @app.get("/api/factors/compute/{run_id}")
    def factors_compute_detail(run_id: str) -> dict:
        row = get_factor_run(run_id, settings=settings)
        if not row:
            raise HTTPException(status_code=404, detail="因子计算任务不存在")
        return row

    @app.post("/api/factors/compute")
    def factors_compute(payload: dict | None = None) -> dict:
        body = payload or {}
        strategy_ids = body.get("strategy_ids")
        strategy_id = body.get("strategy_id") or "all"
        persist_parquet = bool(body.get("persist_parquet", True))
        write_sqlite = bool(body.get("write_sqlite", True))
        try:
            if strategy_ids is not None:
                if not isinstance(strategy_ids, list):
                    raise ValueError("strategy_ids must be a list")
                return start_factor_compute_job(
                    strategy_ids=strategy_ids,
                    persist_parquet=persist_parquet,
                    write_sqlite=write_sqlite,
                    settings=settings,
                    background=True,
                )
            return start_factor_compute_job(
                strategy_id,
                persist_parquet=persist_parquet,
                write_sqlite=write_sqlite,
                settings=settings,
                background=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FactorBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/selectors/preview")
    def selectors_preview(payload: dict | None = None) -> dict:
        """Preview select_targets weights without writing paper/target_position."""
        from asqt.storage import read_market_daily
        from asqt.strategies import STRATEGY_SPECS, weights_for

        body = payload or {}
        strategy_id = str(body.get("strategy_id") or "").strip()
        asof = str(body.get("asof") or "").strip()
        if not strategy_id or strategy_id not in STRATEGY_SPECS:
            raise HTTPException(status_code=400, detail="unknown strategy_id")
        if not asof:
            raise HTTPException(status_code=400, detail="asof required")
        params = body.get("params")
        if params is not None and not isinstance(params, dict):
            raise HTTPException(status_code=400, detail="params must be an object")
        rows = read_market_daily(end=asof, settings=settings)
        limits = query_all(
            "SELECT * FROM limit_suspension WHERE trade_date = ?",
            (asof,),
            settings=settings,
        )
        weights = weights_for(strategy_id, rows, asof, limits=limits, params=params)
        return {
            "strategy_id": strategy_id,
            "asof": asof,
            "weights": weights,
            "gross": round(sum(weights.values()), 10),
            "n": len(weights),
        }

    @app.get("/api/market/daily")
    def market_daily(
        symbol: str | None = Query(default=None),
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=5000),
        newest: bool = Query(default=True),
    ) -> list[dict]:
        return read_market_daily(
            symbol=symbol,
            start=start,
            end=end,
            settings=settings,
            limit=limit,
            newest_first=newest,
        )

    @app.get("/api/records/{schema}")
    def records_query(
        schema: str,
        symbol: str | None = Query(default=None),
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=5000),
        newest: bool = Query(default=True),
    ) -> list[dict]:
        from asqt.records import UnknownRecordSchema, query_records

        try:
            return query_records(
                schema,
                symbol=symbol,
                start=start,
                end=end,
                settings=settings,
                limit=limit,
                newest_first=newest,
            )
        except UnknownRecordSchema as exc:
            raise HTTPException(status_code=404, detail={"code": "unknown_schema", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "bad_filter", "message": str(exc)}) from exc

    @app.post("/api/records/{schema}/upsert")
    def records_upsert(schema: str, body: RecordsUpsertBody) -> dict:
        from asqt.records import UnknownRecordSchema, record_parquet_path, upsert_records

        try:
            path = upsert_records(schema, body.rows, settings=settings)
        except UnknownRecordSchema as exc:
            raise HTTPException(status_code=404, detail={"code": "unknown_schema", "message": str(exc)}) from exc
        return {
            "schema": schema,
            "upserted": len(body.rows),
            "parquet": str(path),
            "path": str(record_parquet_path(schema, settings)),
        }

    @app.post("/api/records/{schema}/pull")
    def records_pull(schema: str, body: RecordsPullBody | None = None) -> dict:
        from asqt.pipeline import build_adapter, pull_daily, pull_daily_append
        from asqt.provider_registry import provider_provides, providers_for
        from asqt.records import UnknownRecordSchema, get_record_schema
        from asqt.universe import poc_symbols

        payload = body or RecordsPullBody()
        try:
            get_record_schema(schema)
        except UnknownRecordSchema as exc:
            raise HTTPException(status_code=404, detail={"code": "unknown_schema", "message": str(exc)}) from exc
        if schema != "market_daily":
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "pull_unsupported",
                    "message": f"pull not implemented for schema={schema}",
                    "providers": providers_for(schema),
                },
            )
        source = (payload.source or "baostock").strip()
        if not provider_provides(source, schema):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "provider_mismatch",
                    "message": f"source={source} does not provide {schema}",
                    "providers": providers_for(schema),
                },
            )
        symbols = [str(item).strip() for item in (payload.symbols or []) if str(item).strip()]
        if not symbols:
            symbols = poc_symbols(settings)
        try:
            adapter = build_adapter(source)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "unknown_source", "message": str(exc)}) from exc
        if payload.start and payload.end:
            result = pull_daily(
                symbols,
                payload.start,
                payload.end,
                settings=settings,
                adapter=adapter,
                source=source,
                run_check=payload.run_check,
            )
        else:
            result = pull_daily_append(
                symbols,
                settings=settings,
                adapter=adapter,
                source=source,
                today=payload.today,
                overlap_days=payload.overlap_days,
                run_check=payload.run_check,
            )
        return {"schema": schema, "source": source, "symbols": len(symbols), **result}

    @app.get("/api/market/snapshot")
    def market_snapshot(
        trade_date: str | None = Query(default=None),
        exchange: str | None = Query(default=None),
        instrument_type: str | None = Query(default=None),
        code: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        sort: str = Query(default="volume"),
        order: str = Query(default="desc"),
    ) -> dict:
        names = {
            row["symbol"]: row.get("name") or ""
            for row in query_all("SELECT symbol, name FROM instrument_master", settings=settings)
        }
        payload = read_market_snapshot(
            trade_date=trade_date,
            exchange=exchange,
            instrument_type=instrument_type,
            code=code,
            limit=limit,
            sort=sort,
            order=order,
            names=names,
            settings=settings,
        )
        return payload

    @app.get("/api/orders")
    def list_orders(limit: int = Query(default=20, ge=1, le=200)) -> list[dict]:
        from asqt.orders import MockOrderService

        return MockOrderService(settings).list_orders(limit=limit)

    @app.post("/api/orders/mock")
    def place_mock_order(body: MockOrderBody) -> dict:
        from asqt.orders import MockOrderService

        try:
            return MockOrderService(settings).place_mock(
                symbol=body.symbol,
                side=body.side,
                quantity=body.quantity,
                trade_date=body.trade_date,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/quality/issues")
    def quality_issues(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        status: str = Query(default="open"),
        trade_date: str | None = Query(default=None),
        severity: str | None = Query(default=None),
        code: str | None = Query(default=None),
        sort: str = Query(default="created_at"),
        order: str = Query(default="desc"),
    ) -> dict:
        return list_quality_issues(
            page=page,
            page_size=page_size,
            status=status,
            trade_date=trade_date,
            severity=severity,
            code=code,
            sort=sort,
            order=order,
            settings=settings,
        )

    @app.post("/api/quality/issues/{issue_id}/close")
    def close_issue(issue_id: str) -> dict:
        row = close_quality_issue(issue_id, settings=settings)
        if row is None:
            raise HTTPException(status_code=404, detail="找不到这条质量问题")
        return {"ok": True, "issue": row}

    @app.get("/api/quality/check")
    def quality_check() -> dict:
        from asqt.pipeline import check_market_daily

        return check_market_daily(settings=settings)

    @app.get("/api/sync/runs")
    def sync_runs(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        status: str = Query(default="all"),
        trigger: str = Query(default="all"),
    ) -> dict:
        return list_sync_runs(
            page=page,
            page_size=page_size,
            status=status,
            trigger=trigger,
            settings=settings,
        )

    @app.get("/api/sync/runs/{run_id}")
    def sync_run_detail(run_id: str) -> dict:
        row = get_sync_run(run_id, settings=settings)
        if not row:
            raise HTTPException(status_code=404, detail="同步记录不存在")
        return row

    @app.get("/api/sync/active")
    def sync_active() -> dict:
        return {"active": active_sync_run(settings=settings), "scheduler": scheduler_snapshot(settings=settings)}

    @app.post("/api/sync/runs")
    def sync_start(body: SyncBody | None = None) -> dict:
        payload = body or SyncBody()
        try:
            return start_sync_job(
                trigger="manual",
                source=payload.source,
                overlap_days=payload.overlap_days,
                settings=settings,
                background=True,
            )
        except Busy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/sync/abort")
    def sync_abort() -> dict:
        ids = abort_inflight_sync_runs(settings)
        return {"aborted": len(ids), "run_ids": ids}

    @app.get("/api/strategies")
    def strategies() -> list[dict]:
        from asqt.research_engine import LocalStrategyService

        return LocalStrategyService(settings).list_versions()

    @app.get("/api/research/experiments")
    def experiments() -> list[dict]:
        import json

        folder = settings.experiment_dir
        if not folder.exists():
            return []
        items = []
        for path in sorted(folder.glob("latest-*.json")):
            items.append(json.loads(path.read_text(encoding="utf-8")))
        return items

    @app.get("/api/research/attribution")
    def attribution(strategy_id: str | None = None) -> dict:
        from asqt.review import LocalReviewService

        review = LocalReviewService(settings)
        try:
            if strategy_id:
                return review.attribute_backtest(strategy_id)
            return review.build_daily_review()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/review")
    def review(trade_date: str | None = None) -> dict:
        from asqt.review import LocalReviewService

        return LocalReviewService(settings).build_daily_review(trade_date)

    @app.get("/api/research/backtest/active")
    def research_backtest_active() -> dict:
        return {"active": active_research_run(settings)}

    @app.get("/api/research/backtest/{run_id}")
    def research_backtest_detail(run_id: str) -> dict:
        row = get_research_run(run_id, settings=settings)
        if not row:
            raise HTTPException(status_code=404, detail="回测任务不存在")
        return row

    @app.post("/api/research/backtest")
    def research_backtest(payload: dict | None = None) -> dict:
        body = payload or {}
        strategy_ids = body.get("strategy_ids")
        strategy_id = body.get("strategy_id") or "all"
        try:
            if strategy_ids is not None:
                if not isinstance(strategy_ids, list):
                    raise ValueError("strategy_ids must be a list")
                return start_backtest_job(
                    strategy_ids=strategy_ids,
                    settings=settings,
                    background=True,
                )
            return start_backtest_job(strategy_id, settings=settings, background=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ResearchBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/strategies/{strategy_id}/lifecycle")
    def strategy_lifecycle(strategy_id: str, body: LifecycleBody) -> dict:
        from asqt.research_engine import LocalStrategyService

        service = LocalStrategyService(settings)
        action = body.action.strip().lower()
        try:
            if action == "paper":
                return service.admit_to_paper(strategy_id, body.reason)
            if action == "pause":
                return service.pause(strategy_id, body.reason)
            if action == "resume":
                return service.resume(strategy_id, body.reason)
            if action == "retire":
                return service.retire(strategy_id, body.reason)
        except PermissionError as exc:
            raise http_exc_from_gate(exc, status_code=403, settings=settings) from exc
        except ValueError as exc:
            raise http_exc_from_gate(exc, status_code=400, settings=settings) from exc
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_action", "message": "动作只能是准入模拟、暂停、恢复或退役。"},
        )

    @app.get("/api/ops/kill-switch")
    def get_kill_switch() -> dict:
        from asqt.ops import kill_engaged

        engaged = kill_engaged(settings)
        return {"engaged": engaged, "reason": _kill_open_reason(settings) if engaged else None}

    @app.post("/api/ops/kill-switch")
    def post_kill_switch(body: KillSwitchBody) -> dict:
        from asqt.ops import set_kill_switch

        try:
            return set_kill_switch(body.engaged, body.reason, settings=settings)
        except ValueError as exc:
            code = str(exc).strip()
            raise HTTPException(
                status_code=400,
                detail={
                    "code": code,
                    "message": GATE_DENY_MESSAGES.get(code, "请填写急停原因（不能全是空格）。"),
                },
            ) from exc

    @app.get("/api/ops/paper-trading")
    def get_paper_trading() -> dict:
        from asqt.ops import paper_trading_enabled

        return {"enabled": paper_trading_enabled(settings)}

    @app.post("/api/ops/paper-trading")
    def post_paper_trading(body: PaperTradingBody) -> dict:
        from asqt.ops import set_paper_trading

        return set_paper_trading(body.enabled, body.reason, settings=settings)

    @app.get("/api/ops/paper-config")
    def get_paper_config() -> dict:
        from asqt.ops import paper_account_config

        return paper_account_config(settings)

    @app.post("/api/ops/paper-config")
    def post_paper_config(body: PaperConfigBody) -> dict:
        from asqt.ops import set_paper_account_config

        try:
            return set_paper_account_config(
                initial_cash=body.initial_cash,
                commission_per_myriad=body.commission_per_myriad,
                portfolio_drawdown_stop_pct=body.portfolio_drawdown_stop_pct,
                strategy_drawdown_stop_pct=body.strategy_drawdown_stop_pct,
                drawdown_warn_pct=body.drawdown_warn_pct,
                settings=settings,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/alerts")
    def list_alerts(
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default="open"),
    ) -> list[dict]:
        from asqt.ops import LocalAlertService

        wanted = (status or "").strip().lower() or None
        if wanted == "all":
            wanted = None
        return LocalAlertService(settings).list_alerts(limit=limit, status=wanted)

    @app.get("/api/alerts/analysis")
    def alert_analysis(limit: int = Query(default=200, ge=1, le=500)) -> dict:
        from asqt.ops import LocalAlertService

        return LocalAlertService(settings).analyze_open_alerts(limit=limit)

    @app.post("/api/alerts/close-batch")
    def close_alerts_batch(payload: AlertCloseBatchBody) -> dict:
        from asqt.ops import LocalAlertService

        if not payload.alert_ids:
            raise HTTPException(status_code=400, detail="alert_ids 不能为空")
        return LocalAlertService(settings).close_alerts(
            payload.alert_ids,
            reason=payload.reason or "batch closed from console",
        )

    @app.post("/api/alerts/{alert_id}/close")
    def close_alert(alert_id: str, body: dict | None = None) -> dict:
        from asqt.ops import LocalAlertService

        reason = None
        if isinstance(body, dict):
            reason = body.get("reason")
        row = LocalAlertService(settings).close_alert(alert_id, reason=reason or "closed from console")
        if not row:
            raise HTTPException(status_code=404, detail="告警不存在")
        return row

    @app.post("/api/paper/run")
    def paper_run(body: PaperRunBody | None = None) -> dict:
        from asqt.paper import PaperBusy
        from asqt.paper_jobs import start_paper_job

        payload = body or PaperRunBody()
        try:
            return start_paper_job(
                strategy_id=payload.strategy_id,
                strategy_ids=payload.strategy_ids,
                days=payload.days,
                mode=payload.mode,
                settings=settings,
                background=payload.background,
            )
        except PaperBusy as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "paper_busy", "message": str(exc)},
            ) from exc
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/paper/run/active")
    def paper_run_active() -> dict:
        from asqt.paper_jobs import active_paper_run

        return {"active": active_paper_run(settings)}

    @app.get("/api/paper/run/{run_id}")
    def paper_run_detail(run_id: str) -> dict:
        from asqt.paper_jobs import get_paper_run

        row = get_paper_run(run_id, settings=settings)
        if not row:
            raise HTTPException(status_code=404, detail="模拟任务不存在")
        return row

    @app.post("/api/paper/reset")
    def paper_reset(body: PaperRunBody | None = None) -> dict:
        from asqt.paper import PaperBusy, reset_paper_account

        payload = body or PaperRunBody()
        try:
            return reset_paper_account(
                strategy_id=payload.strategy_id,
                strategy_ids=payload.strategy_ids,
                settings=settings,
            )
        except PaperBusy as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "paper_busy", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/paper/halt/clear")
    def paper_halt_clear(body: PaperHaltClearBody) -> dict:
        from asqt.paper import PaperBusy, clear_strategy_halt

        try:
            return clear_strategy_halt(
                body.strategy_id,
                body.reason,
                settings=settings,
            )
        except PaperBusy as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "paper_busy", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            code = str(exc).strip()
            raise HTTPException(
                status_code=400,
                detail={
                    "code": code,
                    "message": GATE_DENY_MESSAGES.get(
                        code, "请填写解除单策略平仓的原因（不能全是空格）。"
                    ),
                },
            ) from exc

    @app.post("/api/paper/daily")
    def paper_daily() -> dict:
        from asqt.paper import advance_paper_session

        return advance_paper_session(trigger="api", settings=settings)

    @app.get("/api/ops/tasks")
    def list_ops_tasks(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
        from asqt.scheduler import LocalScheduler

        return LocalScheduler(settings).list_tasks(limit=limit)

    @app.post("/api/ops/tasks/{task_name}")
    def run_ops_task(task_name: str) -> dict:
        from asqt.scheduler import LocalScheduler

        try:
            return LocalScheduler(settings).run_task(task_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/paper/account")
    def paper_account(strategy_id: str) -> dict:
        from asqt.paper import paper_board

        return paper_board(strategy_id, settings)

    @app.get("/api/paper/orders")
    def paper_orders(
        limit: int = Query(default=50, ge=1, le=5000),
        strategy_id: str | None = None,
    ) -> list[dict]:
        from asqt.paper import PaperOrderService

        return PaperOrderService(settings).list_orders(limit=limit, strategy_id=strategy_id)

    @app.get("/api/tags")
    def get_tags(
        tag: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
        source: str | None = Query(default=None),
        limit: int = Query(default=5000, ge=1, le=50_000),
    ) -> list[dict]:
        from asqt.tags import list_tags

        return list_tags(tag=tag, symbol=symbol, source=source, limit=limit, settings=settings)

    @app.post("/api/tags")
    def post_tags(body: TagUpsertBody) -> list[dict]:
        from asqt.tags import upsert_tags

        try:
            return upsert_tags(body.rows, actor=body.actor, settings=settings)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "bad_tag", "message": str(exc)}) from exc

    @app.get("/api/pools/{tag}")
    def get_pool(tag: str) -> list[dict]:
        from asqt.tags import list_pool

        try:
            return list_pool(tag, settings=settings)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "bad_tag", "message": str(exc)}) from exc

    @app.get("/api/paper/overrides")
    def get_paper_overrides(strategy_id: str | None = Query(default=None)) -> list[dict]:
        from asqt.overrides import list_overrides

        return list_overrides(strategy_id=strategy_id, settings=settings)

    @app.put("/api/paper/overrides")
    def put_paper_override(body: PaperOverrideBody) -> dict:
        from asqt.overrides import upsert_override

        try:
            return upsert_override(
                strategy_id=body.strategy_id,
                symbol=body.symbol,
                action=body.action,
                weight=body.weight,
                reason=body.reason,
                actor=body.actor,
                settings=settings,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "bad_override", "message": str(exc)}) from exc

    @app.delete("/api/paper/overrides")
    def delete_paper_override(
        strategy_id: str = Query(...),
        symbol: str = Query(...),
        actor: str = Query(default="operator"),
        reason: str | None = Query(default=None),
    ) -> dict:
        from asqt.overrides import delete_override

        try:
            return delete_override(
                strategy_id=strategy_id,
                symbol=symbol,
                actor=actor,
                reason=reason,
                settings=settings,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "bad_override", "message": str(exc)}) from exc

    @app.get("/api/events")
    def get_events(
        symbol: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
        source: str | None = Query(default=None),
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        asof: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=200),
        limit: int | None = Query(default=None, ge=1, le=50_000),
        newest: bool = Query(default=True),
    ) -> dict:
        from asqt.events import count_events, query_events

        size = int(limit) if limit is not None else int(page_size)
        size = max(1, min(size, 200 if limit is None else 50_000))
        total = count_events(
            settings=settings,
            symbol=symbol,
            event_type=event_type,
            source=source,
            start=start,
            end=end,
            asof=asof,
            fuzzy_symbol=True,
        )
        pages = max(1, (total + size - 1) // size) if total else 1
        page_n = min(max(1, int(page)), pages)
        offset = (page_n - 1) * size
        items = query_events(
            settings=settings,
            symbol=symbol,
            event_type=event_type,
            source=source,
            start=start,
            end=end,
            asof=asof,
            limit=size,
            offset=offset,
            newest_first=newest,
            fuzzy_symbol=True,
        )
        return {
            "items": items,
            "total": total,
            "page": page_n,
            "pages": pages,
            "page_size": size,
        }

    @app.get("/api/events/types")
    def get_event_types() -> list[str]:
        from asqt.events import list_event_types

        return list_event_types(settings=settings)

    @app.post("/api/events/import")
    def post_events_import(body: EventsImportBody | None = None) -> dict:
        from asqt.events import import_events_from_json

        payload = body or EventsImportBody()
        try:
            return import_events_from_json(path=payload.path, rows=payload.rows, settings=settings)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "fixture_missing", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "bad_events", "message": str(exc)}) from exc

    @app.post("/api/events/pull")
    def post_events_pull(body: EventsPullBody | None = None) -> dict:
        from asqt.event_jobs import EventsBusy, start_events_pull_job
        from asqt.provider_registry import provider_provides, providers_for

        payload = body or EventsPullBody()
        source = (payload.source or "tushare").strip()
        if not provider_provides(source, "market_event"):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "provider_mismatch",
                    "message": f"source={source} does not provide market_event",
                    "providers": providers_for("market_event"),
                },
            )
        if source != "tushare":
            raise HTTPException(
                status_code=400,
                detail={"code": "pull_unsupported", "message": f"events pull not implemented for source={source}"},
            )
        try:
            return start_events_pull_job(
                symbols=payload.symbols,
                start=payload.start,
                end=payload.end,
                source=source,
                settings=settings,
                background=True,
            )
        except EventsBusy as exc:
            raise HTTPException(status_code=409, detail={"code": "events_busy", "message": str(exc)}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail={"code": "tushare_token", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "bad_pull", "message": str(exc)}) from exc

    @app.get("/api/events/pull/active")
    def events_pull_active() -> dict:
        from asqt.event_jobs import active_event_pull_run

        return {"active": active_event_pull_run(settings)}

    @app.get("/api/events/pull/{run_id}")
    def events_pull_detail(run_id: str) -> dict:
        from asqt.event_jobs import get_event_pull_run

        row = get_event_pull_run(run_id, settings=settings)
        if not row:
            raise HTTPException(status_code=404, detail="事件拉取任务不存在")
        return row

    return app


app = create_app()

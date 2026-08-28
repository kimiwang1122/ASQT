from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from asqt.bootstrap import seed_demo
from asqt.config import get_settings
from asqt.db import initialize_database, query_all
from asqt.ports import PORT_NAMES
from asqt.storage import market_daily_path, read_market_daily


def create_app() -> FastAPI:
    settings = get_settings()
    initialize_database(settings)

    app = FastAPI(title="ASQT", version="0.1.0")
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
        data_sources = query_all("SELECT * FROM data_source ORDER BY priority, source_id", settings=settings)
        instruments = query_all("SELECT * FROM instrument_master ORDER BY symbol", settings=settings)
        files = query_all("SELECT * FROM market_data_file ORDER BY created_at DESC", settings=settings)
        issues = query_all(
            "SELECT * FROM quality_issue WHERE status != 'closed' ORDER BY created_at DESC",
            settings=settings,
        )
        tasks = query_all("SELECT * FROM task_run ORDER BY created_at DESC LIMIT 5", settings=settings)
        alerts = query_all(
            "SELECT * FROM alert WHERE status != 'closed' ORDER BY created_at DESC",
            settings=settings,
        )
        calendar_count = query_all("SELECT COUNT(*) AS c FROM trade_calendar", settings=settings)[0]["c"]
        limit_count = query_all("SELECT COUNT(*) AS c FROM limit_suspension", settings=settings)[0]["c"]
        factor_count = query_all("SELECT COUNT(*) AS c FROM factor_signal", settings=settings)[0]["c"]
        return {
            "data_sources": len(data_sources),
            "instruments": len(instruments),
            "market_files": files,
            "open_quality_issues": len(issues),
            "open_alerts": len(alerts),
            "recent_tasks": tasks,
            "trade_calendar_rows": calendar_count,
            "limit_suspension_rows": limit_count,
            "factor_signal_rows": factor_count,
            "ports": [{"name": name, "status": "not_wired"} for name in PORT_NAMES],
            "layout": settings.layout(),
        }

    @app.get("/api/layout")
    def layout() -> dict:
        return settings.layout()

    @app.get("/api/ports")
    def ports() -> list[dict]:
        return [{"name": name, "status": "not_wired", "phase": "pre-P0"} for name in PORT_NAMES]

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
    def limit_suspension(symbol: str | None = Query(default=None)) -> list[dict]:
        if symbol:
            return query_all(
                "SELECT * FROM limit_suspension WHERE symbol = ? ORDER BY trade_date",
                (symbol,),
                settings=settings,
            )
        return query_all("SELECT * FROM limit_suspension ORDER BY trade_date, symbol", settings=settings)

    @app.get("/api/factors")
    def factors() -> list[dict]:
        return query_all(
            "SELECT * FROM factor_signal ORDER BY trade_date DESC, symbol, factor_name",
            settings=settings,
        )

    @app.get("/api/market/daily")
    def market_daily(
        symbol: str | None = Query(default=None),
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
    ) -> list[dict]:
        return read_market_daily(symbol=symbol, start=start, end=end, settings=settings)

    @app.get("/api/quality/issues")
    def quality_issues() -> list[dict]:
        return query_all("SELECT * FROM quality_issue ORDER BY created_at DESC", settings=settings)

    return app


app = create_app()

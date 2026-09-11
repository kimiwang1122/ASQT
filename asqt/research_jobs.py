"""Async research backtest jobs with pollable progress."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sqlite3
import threading
from typing import Any
from uuid import uuid4

from asqt.config import Settings, get_settings
from asqt.db import connect, execute, initialize_database, query_all
from asqt.research_engine import LocalResearchEngine
from asqt.storage import read_market_daily
from asqt.strategies import STRATEGY_SPECS

STRATEGY_LABEL = {
    "etf_ma_rotate": "ETF 均线轮动",
    "stock_momentum_topk": "股票动量 TopK",
    "etf_momentum_topk": "ETF 动量 TopK",
}


class ResearchBusy(Exception):
    """Another backtest job is already queued or running."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_research_run(run_id: str, settings: Settings | None = None) -> dict | None:
    rows = query_all("SELECT * FROM research_run WHERE run_id = ?", (run_id,), settings=settings)
    if not rows:
        return None
    return _public_row(rows[0])


def active_research_run(settings: Settings | None = None) -> dict | None:
    rows = query_all(
        """
        SELECT * FROM research_run
        WHERE inflight = 1 OR status IN ('queued', 'running')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        settings=settings,
    )
    return _public_row(rows[0]) if rows else None


def recover_orphaned_research_runs(settings: Settings | None = None) -> int:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    settings = settings or get_settings()
    initialize_database(settings)
    rows = query_all(
        """
        SELECT run_id FROM research_run
        WHERE inflight = 1 OR status IN ('queued', 'running')
        """,
        settings=settings,
    )
    for row in rows:
        _finish(
            row["run_id"],
            status="failed",
            fail_reason="服务重启或代码热加载中断了回测线程，任务并未真正跑完",
            settings=settings,
        )
    return len(rows)


def start_backtest_job(
    strategy_id: str = "all",
    *,
    settings: Settings | None = None,
    background: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    initialize_database(settings)
    if strategy_id != "all" and strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    run_id = _claim(strategy_id, settings)
    if background:
        threading.Thread(
            target=_execute,
            args=(run_id, strategy_id, settings),
            daemon=True,
            name=f"asqt-research-{run_id[:8]}",
        ).start()
    else:
        _execute(run_id, strategy_id, settings)
    return get_research_run(run_id, settings=settings) or {"run_id": run_id, "status": "queued"}


def _claim(strategy_id: str, settings: Settings) -> str:
    run_id = str(uuid4())
    now = _now()
    with connect(settings) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            inflight = conn.execute(
                "SELECT run_id FROM research_run WHERE inflight = 1 LIMIT 1"
            ).fetchone()
            if inflight:
                conn.execute("ROLLBACK")
                raise ResearchBusy(f"已有回测任务进行中：{inflight['run_id']}")
            conn.execute(
                """
                INSERT INTO research_run
                    (run_id, strategy_id, status, inflight, progress_pct, progress_done,
                     progress_total, progress_label, started_at, created_at)
                VALUES (?, ?, 'queued', 1, 0, 0, 0, ?, ?, ?)
                """,
                (run_id, strategy_id, "排队", now, now),
            )
            conn.commit()
        except ResearchBusy:
            raise
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            raise ResearchBusy("已有回测任务进行中") from exc
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return run_id


def _execute(run_id: str, strategy_id: str, settings: Settings) -> None:
    _patch(
        run_id,
        settings,
        status="running",
        progress_label="开始回测",
        started_at=_now(),
    )
    try:
        ids = list(STRATEGY_SPECS) if strategy_id == "all" else (strategy_id,)
        rows = read_market_daily(settings=settings)
        date_steps = max(1, len({str(row["trade_date"]) for row in rows}) - 1)
        grand = date_steps * len(ids)
        engine = LocalResearchEngine(settings)
        reports: list[dict[str, Any]] = []
        for index, sid in enumerate(ids):
            label = STRATEGY_LABEL.get(sid, sid)
            offset = index * date_steps

            def progress(done: int, total: int, text: str, *, _offset: int = offset) -> None:
                _set_progress(run_id, settings, _offset + done, grand, text)

            progress(0, date_steps, f"{label} · 质检")
            report = engine.run_backtest(
                sid,
                STRATEGY_SPECS[sid]["parameter_set_id"],
                "auto",
                progress=progress,
            )
            reports.append(_compact_report(report))
            progress(date_steps, date_steps, f"{label} · 完成")
        _finish(
            run_id,
            status="success" if all(item.get("ok") for item in reports) else "failed",
            detail={"ok": all(item.get("ok") for item in reports), "reports": reports},
            settings=settings,
            progress_pct=100,
            progress_done=grand,
            progress_total=grand,
            progress_label="回测完成" if all(item.get("ok") for item in reports) else "回测未全部通过",
        )
    except Exception as exc:
        _finish(run_id, status="failed", fail_reason=str(exc)[:500], settings=settings)


def _compact_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": report.get("ok"),
        "strategy_id": report.get("strategy_id"),
        "status": report.get("status"),
        "nav": report.get("nav"),
        "metrics": report.get("metrics"),
        "data_version": report.get("data_version"),
        "reason": report.get("reason"),
    }


def _set_progress(run_id: str, settings: Settings, done: int, total: int, label: str) -> None:
    total = max(1, int(total))
    done = max(0, min(int(done), total))
    pct = int(done * 100 / total)
    _patch(
        run_id,
        settings,
        progress_pct=pct,
        progress_done=done,
        progress_total=total,
        progress_label=label[:80],
    )


def _patch(run_id: str, settings: Settings, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    execute(
        f"UPDATE research_run SET {assignments} WHERE run_id = ?",
        (*fields.values(), run_id),
        settings=settings,
    )


def _finish(run_id: str, *, status: str, settings: Settings | None = None, **fields: Any) -> None:
    settings = settings or get_settings()
    payload = dict(fields)
    if "detail" in payload and not isinstance(payload["detail"], str):
        payload["detail"] = json.dumps(payload["detail"], ensure_ascii=False)
    payload["status"] = status
    payload["finished_at"] = _now()
    payload["inflight"] = None
    if status in {"success", "failed"} and payload.get("progress_pct") is None:
        payload["progress_pct"] = 100 if status == "success" else payload.get("progress_pct")
    _patch(run_id, settings, **payload)


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    raw = item.get("detail")
    if isinstance(raw, str) and raw:
        try:
            item["detail"] = json.loads(raw)
        except json.JSONDecodeError:
            pass
    return item


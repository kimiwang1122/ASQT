"""Async paper-run jobs with pollable progress (same shape as research jobs)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import threading
from typing import Any
from uuid import uuid4

from asqt.config import Settings, get_settings
from asqt.db import execute, initialize_database, query_all
from asqt.paper import PaperBusy, PAPER_BUSY_MESSAGE, run_paper_days
from asqt.strategies import STRATEGY_SPECS

STRATEGY_LABEL = {
    "etf_ma_rotate": "ETF 均线轮动",
    "stock_momentum_topk": "股票动量 TopK",
    "etf_momentum_topk": "ETF 动量 TopK",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_paper_run(run_id: str, settings: Settings | None = None) -> dict | None:
    rows = query_all(
        "SELECT * FROM task_run WHERE run_id = ? AND task_name = 'paper-run-job'",
        (run_id,),
        settings=settings,
    )
    if not rows:
        return None
    return _public_row(rows[0])


def active_paper_run(settings: Settings | None = None) -> dict | None:
    rows = query_all(
        """
        SELECT * FROM task_run
        WHERE task_name = 'paper-run-job' AND status IN ('queued', 'running')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        settings=settings,
    )
    return _public_row(rows[0]) if rows else None


def recover_orphaned_paper_runs(settings: Settings | None = None) -> int:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    settings = settings or get_settings()
    initialize_database(settings)
    rows = query_all(
        """
        SELECT run_id FROM task_run
        WHERE task_name = 'paper-run-job' AND status IN ('queued', 'running')
        """,
        settings=settings,
    )
    for row in rows:
        _finish(
            row["run_id"],
            status="failed",
            fail_reason="服务重启或代码热加载中断了模拟线程，任务并未真正跑完",
            settings=settings,
        )
    return len(rows)


def start_paper_job(
    strategy_id: str = "all",
    days: int = 20,
    *,
    settings: Settings | None = None,
    background: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    initialize_database(settings)
    if strategy_id != "all" and strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    if active_paper_run(settings=settings):
        raise PaperBusy(PAPER_BUSY_MESSAGE)
    from asqt.paper import paper_run_locked

    if paper_run_locked(settings=settings):
        raise PaperBusy(PAPER_BUSY_MESSAGE)
    run_id = str(uuid4())
    now = _now()
    execute(
        """
        INSERT INTO task_run (run_id, task_name, status, started_at, finished_at, message)
        VALUES (?, 'paper-run-job', 'queued', ?, NULL, ?)
        """,
        (
            run_id,
            now,
            json.dumps(
                {
                    "strategy_id": strategy_id,
                    "days": days,
                    "progress_pct": 0,
                    "progress_done": 0,
                    "progress_total": 0,
                    "progress_label": "排队",
                },
                ensure_ascii=False,
            ),
        ),
        settings=settings,
    )
    if background:
        threading.Thread(
            target=_execute,
            args=(run_id, strategy_id, days, settings),
            daemon=True,
            name=f"asqt-paper-{run_id[:8]}",
        ).start()
    else:
        _execute(run_id, strategy_id, days, settings)
    return get_paper_run(run_id, settings=settings) or {"run_id": run_id, "status": "queued"}


def _execute(run_id: str, strategy_id: str, days: int, settings: Settings) -> None:
    _patch(
        run_id,
        settings,
        status="running",
        progress_label="开始模拟",
        progress_pct=0,
    )
    try:

        def progress(done: int, total: int, text: str) -> None:
            total = max(1, int(total))
            done = max(0, min(int(done), total))
            _patch(
                run_id,
                settings,
                status="running",
                progress_pct=int(done * 100 / total),
                progress_done=done,
                progress_total=total,
                progress_label=text[:80],
            )

        summary = run_paper_days(
            strategy_id=strategy_id,
            days=days,
            settings=settings,
            progress=progress,
            record_task=False,
        )
        if summary.get("ok"):
            finish_status = "success"
            fail_reason = None
            label = "模拟完成"
        elif summary.get("incomplete_reasons"):
            finish_status = "partial"
            fail_reason = summary.get("detail") or "模拟未完整"
            label = "模拟未完整"
        else:
            finish_status = "failed"
            fail_reason = summary.get("detail") or "模拟失败"
            label = "模拟失败"
        _finish(
            run_id,
            status=finish_status,
            detail=summary,
            fail_reason=fail_reason,
            settings=settings,
            progress_pct=100,
            progress_label=label,
        )
    except PaperBusy as exc:
        _finish(run_id, status="failed", fail_reason=str(exc), settings=settings)
    except Exception as exc:
        _finish(run_id, status="failed", fail_reason=str(exc)[:500], settings=settings)


def _patch(run_id: str, settings: Settings, **fields: Any) -> None:
    row = get_paper_run(run_id, settings=settings) or {}
    message = dict(row.get("message") or {})
    for key in (
        "progress_pct",
        "progress_done",
        "progress_total",
        "progress_label",
        "strategy_id",
        "days",
    ):
        if key in fields and fields[key] is not None:
            message[key] = fields[key]
    status = fields.get("status") or row.get("status") or "running"
    execute(
        """
        UPDATE task_run
        SET status = ?, message = ?, started_at = COALESCE(started_at, ?)
        WHERE run_id = ?
        """,
        (status, json.dumps(message, ensure_ascii=False), _now(), run_id),
        settings=settings,
    )


def _finish(
    run_id: str,
    *,
    status: str,
    settings: Settings,
    fail_reason: str | None = None,
    detail: dict[str, Any] | None = None,
    progress_pct: int | None = None,
    progress_label: str | None = None,
) -> None:
    row = get_paper_run(run_id, settings=settings) or {}
    message: dict[str, Any]
    try:
        message = json.loads(row.get("message") or "{}")
    except (TypeError, json.JSONDecodeError):
        message = {}
    if detail:
        message["result"] = {
            "ok": detail.get("ok"),
            "days": detail.get("days"),
            "window": detail.get("window"),
            "incomplete_reasons": detail.get("incomplete_reasons"),
            "detail": detail.get("detail"),
            "reports": [
                {
                    "strategy_id": item.get("strategy_id"),
                    "sessions": item.get("sessions"),
                    "snapshots": item.get("snapshots"),
                    "incomplete_reason": item.get("incomplete_reason"),
                    "orders": item.get("orders"),
                    "fills": item.get("fills"),
                }
                for item in (detail.get("reports") or [])
            ],
        }
    if fail_reason:
        message["fail_reason"] = fail_reason
    if progress_pct is not None:
        message["progress_pct"] = progress_pct
    if progress_label is not None:
        message["progress_label"] = progress_label
    execute(
        """
        UPDATE task_run
        SET status = ?, finished_at = ?, message = ?
        WHERE run_id = ?
        """,
        (status, _now(), json.dumps(message, ensure_ascii=False), run_id),
        settings=settings,
    )


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {}
    try:
        message = json.loads(row.get("message") or "{}")
    except (TypeError, json.JSONDecodeError):
        message = {}
    return {
        "run_id": row["run_id"],
        "task_name": row.get("task_name"),
        "status": row["status"],
        "strategy_id": message.get("strategy_id"),
        "days": message.get("days"),
        "progress_pct": message.get("progress_pct"),
        "progress_done": message.get("progress_done"),
        "progress_total": message.get("progress_total"),
        "progress_label": message.get("progress_label"),
        "fail_reason": message.get("fail_reason"),
        "detail": message.get("result"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "created_at": row.get("created_at"),
        "message": message,
    }

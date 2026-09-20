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
from asqt.paper import PaperBusy, PaperCancelled, PAPER_BUSY_MESSAGE, run_paper_days
from asqt.strategies import STRATEGY_LABEL

_CANCEL_EVENTS: dict[str, threading.Event] = {}
_CANCEL_REQUESTED: set[str] = set()
_CANCEL_GUARD = threading.Lock()


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


def clear_stale_paper_lock(settings: Settings | None = None) -> bool:
    """Release leftover paper-run lock when no queued/running job exists."""
    from asqt.paper import force_release_paper_run_lock, paper_run_locked

    settings = settings or get_settings()
    if active_paper_run(settings=settings):
        return False
    if not paper_run_locked(settings=settings):
        return False
    force_release_paper_run_lock(settings)
    return True


def cancel_paper_run(
    run_id: str,
    *,
    reason: str = "用户终止跑模拟",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Ask the worker to stop; lock is released when the thread unwinds."""
    settings = settings or get_settings()
    initialize_database(settings)
    row = get_paper_run(run_id, settings=settings)
    if not row:
        raise ValueError("模拟任务不存在")
    if row.get("status") not in {"queued", "running"}:
        return row
    note = str(reason or "用户终止跑模拟")[:500]
    with _CANCEL_GUARD:
        _CANCEL_REQUESTED.add(run_id)
        event = _CANCEL_EVENTS.get(run_id)
    if event:
        event.set()
        _patch(run_id, settings, status="running", progress_label="正在终止")
        message = _message_dict((get_paper_run(run_id, settings=settings) or {}).get("message"))
        message["fail_reason"] = note
        execute(
            "UPDATE task_run SET message = ? WHERE run_id = ?",
            (json.dumps(message, ensure_ascii=False), run_id),
            settings=settings,
        )
        return get_paper_run(run_id, settings=settings) or row
    from asqt.paper import force_release_paper_run_lock

    _finish(
        run_id,
        status="cancelled",
        fail_reason=note,
        settings=settings,
        progress_label="已终止",
    )
    force_release_paper_run_lock(settings)
    return get_paper_run(run_id, settings=settings) or row


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
    from asqt.paper import force_release_paper_run_lock

    force_release_paper_run_lock(settings)
    return len(rows)


def start_paper_job(
    strategy_id: str = "all",
    days: int = 20,
    *,
    strategy_ids: list[str] | None = None,
    mode: str = "sequential",
    settings: Settings | None = None,
    background: bool = True,
    params: dict[str, Any] | None = None,
    parameter_set_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    initialize_database(settings)
    from asqt.lab_params import apply_run_pins
    from asqt.paper import normalize_paper_mode, normalize_paper_targets

    job_key, ids = normalize_paper_targets(strategy_id, strategy_ids)
    run_mode = normalize_paper_mode(mode)
    pin_plan = apply_run_pins(
        ids,
        mode=run_mode,
        lab_params=params,
        parameter_set_id=parameter_set_id,
        settings=settings,
    )
    if active_paper_run(settings=settings):
        raise PaperBusy(PAPER_BUSY_MESSAGE)
    clear_stale_paper_lock(settings=settings)
    from asqt.versioning import run_signature

    start = str(start_date or "").strip() or None
    end = str(end_date or "").strip() or None
    signature = run_signature(
        "paper",
        {
            "strategy_id": job_key,
            "days": int(days),
            "start_date": start,
            "end_date": end,
            "mode": run_mode,
            "pin_mode": pin_plan.get("mode"),
            "pins": {
                sid: pin["parameter_set_id"] for sid, pin in (pin_plan.get("pins") or {}).items()
            },
        },
    )
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
                    "strategy_id": job_key,
                    "days": days,
                    "start_date": start,
                    "end_date": end,
                    "mode": run_mode,
                    "run_signature": signature,
                    "progress_pct": 0,
                    "progress_done": 0,
                    "progress_total": 0,
                    "progress_label": "排队",
                    "lab_pin_mode": pin_plan.get("mode"),
                    "parameter_set_ids": {
                        sid: pin["parameter_set_id"] for sid, pin in (pin_plan.get("pins") or {}).items()
                    },
                },
                ensure_ascii=False,
            ),
        ),
        settings=settings,
    )
    if background:
        threading.Thread(
            target=_execute,
            args=(run_id, job_key, days, settings, run_mode, signature, start, end),
            daemon=True,
            name=f"asqt-paper-{run_id[:8]}",
        ).start()
    else:
        _execute(run_id, job_key, days, settings, run_mode, signature, start, end)
    row = get_paper_run(run_id, settings=settings) or {"run_id": run_id, "status": "queued"}
    row["lab_pin_mode"] = pin_plan.get("mode")
    row["parameter_set_ids"] = {
        sid: pin["parameter_set_id"] for sid, pin in (pin_plan.get("pins") or {}).items()
    }
    return row


def resume_paper_job(
    run_id: str,
    *,
    strategy_id: str = "all",
    days: int = 20,
    strategy_ids: list[str] | None = None,
    mode: str = "sequential",
    settings: Settings | None = None,
) -> dict[str, Any]:
    from asqt.paper import normalize_paper_mode, normalize_paper_targets
    from asqt.versioning import assert_run_signature, run_signature

    settings = settings or get_settings()
    row = get_paper_run(run_id, settings=settings)
    if not row:
        raise ValueError(f"unknown paper run: {run_id}")
    job_key, _ids = normalize_paper_targets(strategy_id, strategy_ids)
    run_mode = normalize_paper_mode(mode)
    actual = run_signature("paper", {"strategy_id": job_key, "days": int(days), "mode": run_mode})
    stored = _message_dict(row.get("message")).get("run_signature") or row.get("run_signature")
    assert_run_signature(stored, actual, run_id=run_id)
    return row


def _execute(
    run_id: str,
    strategy_id: str,
    days: int,
    settings: Settings,
    mode: str = "sequential",
    expected_signature: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    if expected_signature:
        from asqt.versioning import assert_run_signature

        row = get_paper_run(run_id, settings=settings) or {}
        stored = _message_dict(row.get("message")).get("run_signature")
        assert_run_signature(stored, expected_signature, run_id=run_id)
    stop = threading.Event()
    with _CANCEL_GUARD:
        _CANCEL_EVENTS[run_id] = stop
        if run_id in _CANCEL_REQUESTED:
            stop.set()
    current = get_paper_run(run_id, settings=settings) or {}
    if current.get("status") not in {"queued", "running"}:
        return
    try:
        if stop.is_set():
            raise PaperCancelled("用户终止跑模拟")
        _patch(
            run_id,
            settings,
            status="running",
            progress_label="开始模拟" if mode != "parallel" else "并行模拟",
            progress_pct=0,
        )

        def progress(done: int, total: int, text: str) -> None:
            if stop.is_set():
                raise PaperCancelled("用户终止跑模拟")
            total = max(1, int(total))
            done = max(0, min(int(done), total))
            if done in {0, 1, total} or done % 5 == 0 or "halt" in text:
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
            start_date=start_date,
            end_date=end_date,
            settings=settings,
            progress=progress,
            record_task=False,
            mode=mode,
        )
        if stop.is_set():
            raise PaperCancelled("用户终止跑模拟")
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
    except PaperCancelled as exc:
        _finish(
            run_id,
            status="cancelled",
            fail_reason=str(exc)[:500],
            settings=settings,
            progress_label="已终止",
        )
    except PaperBusy as exc:
        _finish(run_id, status="failed", fail_reason=str(exc), settings=settings)
    except Exception as exc:
        _finish(run_id, status="failed", fail_reason=str(exc)[:500], settings=settings)
    finally:
        with _CANCEL_GUARD:
            _CANCEL_EVENTS.pop(run_id, None)
            _CANCEL_REQUESTED.discard(run_id)


def _message_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _patch(run_id: str, settings: Settings, **fields: Any) -> None:
    row = get_paper_run(run_id, settings=settings) or {}
    message = _message_dict(row.get("message"))
    for key in (
        "progress_pct",
        "progress_done",
        "progress_total",
        "progress_label",
        "strategy_id",
        "days",
        "mode",
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
    message = _message_dict(row.get("message"))
    if detail:
        message["result"] = {
            "ok": detail.get("ok"),
            "days": detail.get("days"),
            "mode": detail.get("mode"),
            "window": detail.get("window"),
            "portfolio_cash": detail.get("portfolio_cash"),
            "book_cash": detail.get("book_cash"),
            "funding_universe": detail.get("funding_universe"),
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
        try:
            from asqt.reporting import write_run_tree

            write_run_tree(
                "paper",
                run_id,
                {
                    "ok": detail.get("ok"),
                    "strategy_id": message.get("strategy_id"),
                    "days": detail.get("days") or message.get("days"),
                    "mode": detail.get("mode") or message.get("mode"),
                    "result": message["result"],
                    "status": status,
                },
                settings=settings,
                strategy_id=str(message.get("strategy_id") or ""),
                write_legacy_latest=False,
            )
        except Exception:
            pass
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
        "mode": message.get("mode") or "sequential",
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

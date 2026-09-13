"""Async market-event pull jobs (single-flight) with pollable progress."""

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
from asqt.events import pull_holder_trade_events


class EventsBusy(Exception):
    """Another events pull job is already queued or running."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_event_pull_run(run_id: str, settings: Settings | None = None) -> dict | None:
    rows = query_all("SELECT * FROM event_pull_run WHERE run_id = ?", (run_id,), settings=settings)
    if not rows:
        return None
    return _public_row(rows[0])


def active_event_pull_run(settings: Settings | None = None) -> dict | None:
    rows = query_all(
        """
        SELECT * FROM event_pull_run
        WHERE inflight = 1 OR status IN ('queued', 'running')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        settings=settings,
    )
    return _public_row(rows[0]) if rows else None


def recover_orphaned_event_pull_runs(settings: Settings | None = None) -> int:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    settings = settings or get_settings()
    initialize_database(settings)
    rows = query_all(
        """
        SELECT run_id FROM event_pull_run
        WHERE inflight = 1 OR status IN ('queued', 'running')
        """,
        settings=settings,
    )
    for row in rows:
        _finish(
            row["run_id"],
            status="failed",
            fail_reason="服务重启或代码热加载中断了事件拉取，任务并未真正跑完",
            settings=settings,
        )
    return len(rows)


def start_events_pull_job(
    *,
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    source: str = "tushare",
    settings: Settings | None = None,
    background: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    initialize_database(settings)
    run_id = _claim(settings)
    payload = {
        "source": source,
        "symbols": symbols,
        "start": start,
        "end": end,
    }
    execute(
        "UPDATE event_pull_run SET detail = ? WHERE run_id = ?",
        (json.dumps(payload, ensure_ascii=False), run_id),
        settings=settings,
    )
    if background:
        threading.Thread(
            target=_execute,
            args=(run_id, symbols, start, end, settings),
            daemon=True,
            name=f"asqt-events-pull-{run_id[:8]}",
        ).start()
    else:
        _execute(run_id, symbols, start, end, settings)
    return get_event_pull_run(run_id, settings=settings) or {"run_id": run_id, "status": "queued"}


def _claim(settings: Settings) -> str:
    run_id = str(uuid4())
    now = _now()
    with connect(settings) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            inflight = conn.execute(
                "SELECT run_id FROM event_pull_run WHERE inflight = 1 LIMIT 1"
            ).fetchone()
            if inflight:
                conn.execute("ROLLBACK")
                raise EventsBusy(f"已有事件拉取任务进行中：{inflight['run_id']}")
            conn.execute(
                """
                INSERT INTO event_pull_run
                    (run_id, status, inflight, progress_pct, progress_done,
                     progress_total, progress_label, started_at, created_at)
                VALUES (?, 'queued', 1, 0, 0, 0, ?, ?, ?)
                """,
                (run_id, "排队中", now, now),
            )
            conn.execute("COMMIT")
        except EventsBusy:
            raise
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            raise EventsBusy("已有事件拉取任务进行中") from exc
    return run_id


def _execute(
    run_id: str,
    symbols: list[str] | None,
    start: str | None,
    end: str | None,
    settings: Settings,
) -> None:
    try:
        _patch(
            run_id,
            status="running",
            progress_pct=5,
            progress_label="开始拉取股东增减持",
            settings=settings,
        )
        result = pull_holder_trade_events(
            symbols=symbols,
            start=start,
            end=end,
            settings=settings,
        )
        detail = json.dumps(result, ensure_ascii=False)
        _finish(
            run_id,
            status="success",
            progress_pct=100,
            progress_done=int(result.get("stored_total") or 0),
            progress_total=int(result.get("fetched") or 0),
            progress_label=(
                f"完成 · 抓取 {result.get('fetched')} · 库内 {result.get('stored_total')}"
            ),
            detail=detail,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        _finish(
            run_id,
            status="failed",
            fail_reason=str(exc)[:500],
            progress_label="失败",
            settings=settings,
        )


def _patch(run_id: str, settings: Settings, **fields: Any) -> None:
    if not fields:
        return
    cols = []
    values: list[Any] = []
    for key, value in fields.items():
        cols.append(f"{key} = ?")
        values.append(value)
    values.append(run_id)
    execute(
        f"UPDATE event_pull_run SET {', '.join(cols)} WHERE run_id = ?",
        tuple(values),
        settings=settings,
    )


def _finish(
    run_id: str,
    *,
    status: str,
    settings: Settings,
    fail_reason: str | None = None,
    progress_pct: int | None = None,
    progress_done: int | None = None,
    progress_total: int | None = None,
    progress_label: str | None = None,
    detail: str | None = None,
) -> None:
    fields: dict[str, Any] = {
        "status": status,
        "inflight": None,
        "finished_at": _now(),
    }
    if fail_reason is not None:
        fields["fail_reason"] = fail_reason
    if progress_pct is not None:
        fields["progress_pct"] = progress_pct
    if progress_done is not None:
        fields["progress_done"] = progress_done
    if progress_total is not None:
        fields["progress_total"] = progress_total
    if progress_label is not None:
        fields["progress_label"] = progress_label
    if detail is not None:
        fields["detail"] = detail
    _patch(run_id, settings=settings, **fields)


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    detail = out.get("detail")
    if isinstance(detail, str) and detail.strip().startswith(("{", "[")):
        try:
            out["result"] = json.loads(detail)
        except json.JSONDecodeError:
            out["result"] = None
    else:
        out["result"] = None
    return out

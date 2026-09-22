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
from asqt.strategies import STRATEGY_LABEL, STRATEGY_SPECS


def normalize_backtest_targets(
    strategy_id: str = "all",
    strategy_ids: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Return (job_key, ordered ids). job_key is stored on research_run.strategy_id."""
    if strategy_ids is not None:
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in strategy_ids:
            sid = str(raw or "").strip()
            if not sid or sid in seen:
                continue
            if sid not in STRATEGY_SPECS:
                raise ValueError(f"unknown strategy: {sid}")
            seen.add(sid)
            ordered.append(sid)
        if not ordered:
            raise ValueError("strategy_ids must not be empty")
        if set(ordered) == set(STRATEGY_SPECS):
            return "all", list(STRATEGY_SPECS)
        return ",".join(ordered), ordered
    key = str(strategy_id or "all").strip() or "all"
    if key == "all":
        return "all", list(STRATEGY_SPECS)
    if "," in key:
        return normalize_backtest_targets(strategy_ids=key.split(","))
    if key not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {key}")
    return key, [key]


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
    strategy_ids: list[str] | None = None,
    settings: Settings | None = None,
    background: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    initialize_database(settings)
    job_key, ids = normalize_backtest_targets(strategy_id, strategy_ids)
    from asqt.strategies import CODE_VERSION
    from asqt.versioning import run_signature

    signature = run_signature(
        "research",
        {
            "job_key": job_key,
            "strategy_ids": ids,
            "parameter_set_ids": [STRATEGY_SPECS[sid]["parameter_set_id"] for sid in ids],
            "code_version": CODE_VERSION,
        },
    )
    run_id = _claim(job_key, settings, run_signature=signature)
    if background:
        threading.Thread(
            target=_execute,
            args=(run_id, job_key, settings, signature),
            daemon=True,
            name=f"asqt-research-{run_id[:8]}",
        ).start()
    else:
        _execute(run_id, job_key, settings, signature)
    return get_research_run(run_id, settings=settings) or {"run_id": run_id, "status": "queued"}


def _claim(strategy_id: str, settings: Settings, *, run_signature: str | None = None) -> str:
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
                     progress_total, progress_label, run_signature, started_at, created_at)
                VALUES (?, ?, 'queued', 1, 0, 0, 0, ?, ?, ?, ?)
                """,
                (run_id, strategy_id, "排队", run_signature, now, now),
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


def resume_backtest_job(
    run_id: str,
    *,
    strategy_id: str = "all",
    strategy_ids: list[str] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Refuse resume when the stored run_signature drifts from the new request."""
    from asqt.strategies import CODE_VERSION
    from asqt.versioning import assert_run_signature, run_signature

    settings = settings or get_settings()
    row = get_research_run(run_id, settings=settings)
    if not row:
        raise ValueError(f"unknown research run: {run_id}")
    job_key, ids = normalize_backtest_targets(strategy_id, strategy_ids)
    actual = run_signature(
        "research",
        {
            "job_key": job_key,
            "strategy_ids": ids,
            "parameter_set_ids": [STRATEGY_SPECS[sid]["parameter_set_id"] for sid in ids],
            "code_version": CODE_VERSION,
        },
    )
    assert_run_signature(row.get("run_signature"), actual, run_id=run_id)
    return row


def _execute(run_id: str, strategy_id: str, settings: Settings, expected_signature: str | None = None) -> None:
    if expected_signature:
        from asqt.versioning import assert_run_signature

        row = get_research_run(run_id, settings=settings) or {}
        assert_run_signature(row.get("run_signature"), expected_signature, run_id=run_id)
    _patch(
        run_id,
        settings,
        status="running",
        progress_label="开始回测",
        started_at=_now(),
    )
    try:
        _key, ids = normalize_backtest_targets(strategy_id)
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
        detail = {"ok": all(item.get("ok") for item in reports), "reports": reports}
        from asqt.reporting import write_run_tree

        write_run_tree(
            "backtest",
            run_id,
            {"ok": detail["ok"], "strategy_id": strategy_id, "reports": reports, "job": True},
            settings=settings,
            # Job envelope must not overwrite per-strategy latest (admit reads pins there).
            strategy_id=None,
            write_legacy_latest=False,
            refresh_latest=False,
        )
        _finish(
            run_id,
            status="success" if detail["ok"] else "failed",
            detail=detail,
            settings=settings,
            progress_pct=100,
            progress_done=grand,
            progress_total=grand,
            progress_label="回测完成" if detail["ok"] else "回测未全部通过",
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
        "parameter_set_id": report.get("parameter_set_id"),
        "data_version": report.get("data_version"),
        "reason": report.get("reason"),
    }


def _set_progress(run_id: str, settings: Settings, done: int, total: int, label: str) -> None:
    total = max(1, int(total))
    done = max(0, min(int(done), total))
    pct = int(done * 100 / total)
    if pct == 0 and done < total:
        pct = 1
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


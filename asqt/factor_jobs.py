"""Async factor compute jobs with pollable progress (mirrors research_jobs)."""

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
from asqt.factor_pipeline import (
    build_data_frame,
    compute_factor_frame,
    persist_factor_values,
    write_factor_signals,
)
from asqt.storage import read_market_daily
from asqt.strategies import CODE_VERSION, STRATEGY_SPECS, factor_specs_for

STRATEGY_LABEL = {
    "etf_ma_rotate": "ETF 均线轮动",
    "stock_momentum_topk": "股票动量 TopK",
    "etf_momentum_topk": "ETF 动量 TopK",
    "stock_lowvol_momentum": "股票低波动量",
    "etf_ma_momentum_filter": "ETF 均线动量过滤",
    "stock_short_reversal_topk": "股票短反转 TopK",
    "stock_momentum_volume_confirm": "股票动量量能确认",
    "stock_momentum_skip_month": "股票跳月动量",
    "stock_holder_increase_follow": "股票股东增持跟随",
}


class FactorBusy(Exception):
    """Another factor compute job is already queued or running."""


def normalize_factor_targets(
    strategy_id: str = "all",
    strategy_ids: list[str] | None = None,
) -> tuple[str, list[str]]:
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
        return normalize_factor_targets(strategy_ids=key.split(","))
    if key not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {key}")
    return key, [key]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_factor_run(run_id: str, settings: Settings | None = None) -> dict | None:
    rows = query_all("SELECT * FROM factor_run WHERE run_id = ?", (run_id,), settings=settings)
    if not rows:
        return None
    return _public_row(rows[0])


def active_factor_run(settings: Settings | None = None) -> dict | None:
    rows = query_all(
        """
        SELECT * FROM factor_run
        WHERE inflight = 1 OR status IN ('queued', 'running')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        settings=settings,
    )
    return _public_row(rows[0]) if rows else None


def recover_orphaned_factor_runs(settings: Settings | None = None) -> int:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    settings = settings or get_settings()
    initialize_database(settings)
    rows = query_all(
        """
        SELECT run_id FROM factor_run
        WHERE inflight = 1 OR status IN ('queued', 'running')
        """,
        settings=settings,
    )
    for row in rows:
        _finish(
            row["run_id"],
            status="failed",
            fail_reason="服务重启或代码热加载中断了因子任务，任务并未真正跑完",
            settings=settings,
        )
    return len(rows)


def start_factor_compute_job(
    strategy_id: str = "all",
    *,
    strategy_ids: list[str] | None = None,
    persist_parquet: bool = True,
    write_sqlite: bool = True,
    settings: Settings | None = None,
    background: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    initialize_database(settings)
    job_key, _ids = normalize_factor_targets(strategy_id, strategy_ids)
    run_id = _claim(job_key, settings)
    if background:
        threading.Thread(
            target=_execute,
            args=(run_id, job_key, persist_parquet, write_sqlite, settings),
            daemon=True,
            name=f"asqt-factor-{run_id[:8]}",
        ).start()
    else:
        _execute(run_id, job_key, persist_parquet, write_sqlite, settings)
    return get_factor_run(run_id, settings=settings) or {"run_id": run_id, "status": "queued"}


def _claim(strategy_id: str, settings: Settings) -> str:
    run_id = str(uuid4())
    now = _now()
    with connect(settings) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            inflight = conn.execute(
                "SELECT run_id FROM factor_run WHERE inflight = 1 LIMIT 1"
            ).fetchone()
            if inflight:
                conn.execute("ROLLBACK")
                raise FactorBusy(f"已有因子计算任务进行中：{inflight['run_id']}")
            conn.execute(
                """
                INSERT INTO factor_run
                    (run_id, strategy_id, status, inflight, progress_pct, progress_done,
                     progress_total, progress_label, started_at, created_at)
                VALUES (?, ?, 'queued', 1, 0, 0, 0, ?, ?, ?)
                """,
                (run_id, strategy_id, "排队", now, now),
            )
            conn.commit()
        except FactorBusy:
            raise
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            raise FactorBusy("已有因子计算任务进行中") from exc
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return run_id


def _execute(
    run_id: str,
    strategy_id: str,
    persist_parquet: bool,
    write_sqlite: bool,
    settings: Settings,
) -> None:
    _patch(
        run_id,
        settings,
        status="running",
        progress_label="开始计算因子",
        started_at=_now(),
    )
    try:
        _key, ids = normalize_factor_targets(strategy_id)
        rows = read_market_daily(settings=settings)
        dates = sorted({str(row["trade_date"]) for row in rows})
        if not dates:
            raise ValueError("market_daily is empty")
        grouped = build_data_frame(rows)
        grand = max(1, len(ids))
        all_factors: list[dict[str, Any]] = []
        per_strategy: list[dict[str, Any]] = []
        for index, sid in enumerate(ids):
            label = STRATEGY_LABEL.get(sid, sid)
            _set_progress(run_id, settings, index, grand, f"{label} · 计算")
            factors = compute_factor_frame(
                grouped,
                factor_specs_for(sid, settings=settings),
                dates=dates,
                source_run_id=run_id,
                model_version=CODE_VERSION,
            )
            all_factors.extend(factors)
            per_strategy.append({"strategy_id": sid, "factor_rows": len(factors)})
            _set_progress(run_id, settings, index + 1, grand, f"{label} · 完成")
        sqlite_n = 0
        parquet_path = None
        if write_sqlite:
            sqlite_n = write_factor_signals(all_factors, settings=settings)
        if persist_parquet:
            parquet_path = str(persist_factor_values(all_factors, settings=settings))
        _finish(
            run_id,
            status="success",
            detail={
                "ok": True,
                "factor_rows": len(all_factors),
                "sqlite_rows": sqlite_n,
                "parquet_path": parquet_path,
                "strategies": per_strategy,
            },
            settings=settings,
            progress_pct=100,
            progress_done=grand,
            progress_total=grand,
            progress_label="因子计算完成",
        )
    except Exception as exc:
        _finish(run_id, status="failed", fail_reason=str(exc)[:500], settings=settings)


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
        f"UPDATE factor_run SET {assignments} WHERE run_id = ?",
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

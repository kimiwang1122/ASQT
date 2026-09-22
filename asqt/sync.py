"""Append market daily bars and run quality check, with async + auto trigger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import threading
from uuid import uuid4
from zoneinfo import ZoneInfo

from asqt.config import Settings, get_settings
from asqt.db import connect, execute, initialize_database, query_all
from asqt.pipeline import check_market_daily, pull_daily_append, _iso_minus_days
from asqt.session import session_asof_date
from asqt.storage import market_daily_span
from asqt.universe import poc_symbols
from typing import Any

SHANGHAI = ZoneInfo("Asia/Shanghai")
AUTO_HOUR = 16
AUTO_MINUTE = 30
DEADLINE_HOUR = 18
DEADLINE_MINUTE = 0
CRON_HOUR = 20
CRON_MINUTE = 5
STALE_RUNNING_MINUTES = 120
SYNC_LOCK_ID = "market_daily_sync"

class Busy(Exception):
    """Another sync job is already queued or running."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shanghai_now() -> datetime:
    return datetime.now(SHANGHAI)


def auto_sync_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("ASQT_SYNC_AUTO", "1") != "0"


def build_sync_adapter(source: str):
    from asqt.pipeline import build_adapter

    return build_adapter(source)


def list_sync_runs(
    *,
    page: int = 1,
    page_size: int = 20,
    status: str = "all",
    trigger: str = "all",
    settings: Settings | None = None,
) -> dict:
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    clauses = ["1=1"]
    params: list[object] = []
    status_key = (status or "all").strip().lower()
    if status_key and status_key != "all":
        clauses.append("status = ?")
        params.append(status_key)
    trigger_key = (trigger or "all").strip().lower()
    if trigger_key and trigger_key != "all":
        clauses.append("trigger = ?")
        params.append(trigger_key)
    where = " AND ".join(clauses)
    total = query_all(
        f"SELECT COUNT(*) AS c FROM data_sync_run WHERE {where}",
        params,
        settings=settings,
    )[0]["c"]
    pages = max(1, (total + page_size - 1) // page_size) if total else 1
    if page > pages:
        page = pages
    offset = (page - 1) * page_size
    items = query_all(
        f"""
        SELECT * FROM data_sync_run
        WHERE {where}
        ORDER BY created_at DESC, run_id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, page_size, offset),
        settings=settings,
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "status": status_key,
        "trigger": trigger_key,
        "scheduler": scheduler_snapshot(settings=settings),
        "active": active_sync_run(settings=settings),
    }


def get_sync_run(run_id: str, settings: Settings | None = None) -> dict | None:
    rows = query_all("SELECT * FROM data_sync_run WHERE run_id = ?", (run_id,), settings=settings)
    return rows[0] if rows else None


def active_sync_run(settings: Settings | None = None) -> dict | None:
    _expire_stale_runs(settings)
    rows = query_all(
        """
        SELECT * FROM data_sync_run
        WHERE inflight = 1 OR status IN ('queued', 'running')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        settings=settings,
    )
    return rows[0] if rows else None


def scheduler_snapshot(settings: Settings | None = None) -> dict:
    now = _shanghai_now()
    last_auto = query_all(
        """
        SELECT * FROM data_sync_run
        WHERE trigger = 'auto'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        settings=settings,
    )
    done = _auto_qc_done_today(now, settings=settings)
    return {
        "enabled": auto_sync_enabled(),
        "timezone": "Asia/Shanghai",
        "window": f"{AUTO_HOUR:02d}:{AUTO_MINUTE:02d}",
        "deadline": f"{DEADLINE_HOUR:02d}:{DEADLINE_MINUTE:02d}",
        "cron": f"{CRON_HOUR:02d}:{CRON_MINUTE:02d}",
        "due": _auto_window_open(now) and not done,
        "waiting_for_bars": _auto_window_open(now) and not _deadline_reached(now) and not done,
        "next_at": _next_auto_at(now, done=done).isoformat(),
        "last_auto": last_auto[0] if last_auto else None,
        "morning_manual_note": (
            "上午手工「追加行情」若只拉到昨日 K，不会取消当天 16:30 进程内自动；"
            "只有盖住当日收盘日 K，或 16:30 之后真正跑完的成功/跳过，才算今日自动已完成。"
        ),
        "hot_reload_note": (
            "uvicorn --reload 会打断后台同步/回测/模拟线程；进程重启时未完成任务会被收尸为失败。"
        ),
        "lock_note": (
            f"同步与模拟各有一把 SQLite 租约锁；占用中重复提交返回 409；租约约 {STALE_RUNNING_MINUTES} 分钟过期可接管。"
        ),
        "cron_installed": _cron_installed_hint(),
        "reconcile": _reconcile_snapshot(settings),
        "cash_reconcile": _cash_reconcile_snapshot(settings),
    }


def _reconcile_snapshot(settings: Settings | None = None) -> dict:
    from asqt.reconcile_jobs import reconcile_snapshot

    return reconcile_snapshot(settings=settings)


def _cash_reconcile_snapshot(settings: Settings | None = None) -> dict:
    from asqt.paper_reconcile_jobs import cash_reconcile_snapshot

    return cash_reconcile_snapshot(settings=settings)


def _cron_installed_hint() -> dict[str, Any]:
    """Best-effort: whether the example fallback line appears in the user crontab."""
    import shutil
    import subprocess

    if not shutil.which("crontab"):
        return {"checked": False, "installed": None, "detail": "本机无 crontab 命令"}
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"checked": False, "installed": None, "detail": str(exc)}
    if result.returncode != 0:
        text = (result.stderr or result.stdout or "").strip()
        if "no crontab" in text.lower():
            return {
                "checked": True,
                "installed": False,
                "detail": "当前用户没有 crontab；可参考 scripts/crontab.example",
            }
        return {"checked": False, "installed": None, "detail": text or "crontab -l 失败"}
    body = result.stdout or ""
    hit = (
        "asqt-cron-fallback.sh" in body
        or "sync-daily --trigger cron" in body
        or "asqt reconcile" in body
        or "reconcile --universe" in body
    )
    return {
        "checked": True,
        "installed": hit,
        "detail": "已找到 cron 兜底/对账行" if hit else "未找到 asqt-cron-fallback；见 scripts/crontab.example",
    }


def _enqueue_locked(*, trigger: str, source: str, settings: Settings) -> str:
    """SQLite lease lock: one inflight sync across processes/users/tabs."""
    run_id = str(uuid4())
    now = _now()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=STALE_RUNNING_MINUTES)).isoformat()
    with connect(settings) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            lock = conn.execute(
                "SELECT run_id, expires_at FROM data_sync_lock WHERE lock_id = ?",
                (SYNC_LOCK_ID,),
            ).fetchone()
            if lock and str(lock["expires_at"] or "") > now:
                holder = lock["run_id"]
                conn.execute("ROLLBACK")
                raise Busy(f"已有同步任务进行中：{holder}")
            if lock:
                conn.execute(
                    """
                    UPDATE data_sync_run
                    SET status = 'failed', inflight = NULL, finished_at = ?, fail_reason = ?
                    WHERE run_id = ? AND (inflight = 1 OR status IN ('queued', 'running'))
                    """,
                    (now, "任务超时未结束，锁已被后续任务接管", lock["run_id"]),
                )
                conn.execute(
                    """
                    UPDATE data_sync_lock
                    SET run_id = ?, holder = ?, acquired_at = ?, expires_at = ?
                    WHERE lock_id = ?
                    """,
                    (run_id, trigger, now, expires, SYNC_LOCK_ID),
                )
            else:
                inflight = conn.execute(
                    "SELECT run_id FROM data_sync_run WHERE inflight = 1 LIMIT 1"
                ).fetchone()
                if inflight:
                    conn.execute("ROLLBACK")
                    raise Busy(f"已有同步任务进行中：{inflight['run_id']}")
                conn.execute(
                    """
                    INSERT INTO data_sync_lock (lock_id, run_id, holder, acquired_at, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (SYNC_LOCK_ID, run_id, trigger, now, expires),
                )
            conn.execute(
                """
                INSERT INTO data_sync_run
                    (run_id, trigger, status, source, inflight, started_at, created_at)
                VALUES (?, ?, 'queued', ?, 1, ?, ?)
                """,
                (run_id, trigger, source, now, now),
            )
            conn.commit()
        except Busy:
            raise
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            raise Busy("已有同步任务进行中") from exc
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return run_id


def _release_lock(run_id: str, settings: Settings | None = None) -> None:
    execute(
        "DELETE FROM data_sync_lock WHERE lock_id = ? AND run_id = ?",
        (SYNC_LOCK_ID, run_id),
        settings=settings,
    )


def recover_orphaned_sync_runs(settings: Settings | None = None) -> int:
    """Mark in-flight rows failed after worker restart (uvicorn --reload kills daemon threads)."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    settings = settings or get_settings()
    initialize_database(settings)
    rows = query_all(
        """
        SELECT run_id FROM data_sync_run
        WHERE inflight = 1 OR status IN ('queued', 'running')
        """,
        settings=settings,
    )
    for row in rows:
        _finish(
            row["run_id"],
            status="failed",
            fail_reason="服务重启或代码热加载中断了同步线程，任务并未真正跑完",
            settings=settings,
        )
        _release_lock(row["run_id"], settings)
    return len(rows)


def abort_inflight_sync_runs(
    settings: Settings | None = None,
    *,
    reason: str = "人工重置，结束卡住的同步",
) -> list[str]:
    settings = settings or get_settings()
    initialize_database(settings)
    rows = query_all(
        """
        SELECT run_id FROM data_sync_run
        WHERE inflight = 1 OR status IN ('queued', 'running')
        """,
        settings=settings,
    )
    ids = []
    for row in rows:
        _finish(row["run_id"], status="failed", fail_reason=reason, settings=settings)
        _release_lock(row["run_id"], settings)
        ids.append(row["run_id"])
    return ids


def _abandoned(run_id: str, settings: Settings | None = None) -> bool:
    row = get_sync_run(run_id, settings=settings)
    if not row:
        return True
    if int(row.get("inflight") or 0) != 1:
        return True
    return row.get("status") not in {"queued", "running"}


def _set_progress(
    run_id: str,
    settings: Settings | None = None,
    *,
    pct: int,
    done: int | None = None,
    total: int | None = None,
    symbol: str | None = None,
) -> None:
    fields: dict[str, object] = {"progress_pct": max(0, min(100, int(pct)))}
    if done is not None:
        fields["progress_done"] = int(done)
    if total is not None:
        fields["progress_total"] = int(total)
    if symbol is not None:
        fields["progress_symbol"] = symbol
    _patch(run_id, settings=settings, **fields)


def start_sync_job(
    *,
    trigger: str = "manual",
    source: str = "baostock",
    settings: Settings | None = None,
    adapter=None,
    today: str | None = None,
    overlap_days: int = 1,
    background: bool = True,
) -> dict:
    settings = settings or get_settings()
    initialize_database(settings)
    run_id = _enqueue_locked(trigger=trigger, source=source, settings=settings)
    if background:
        thread = threading.Thread(
            target=_run_guarded,
            kwargs={
                "run_id": run_id,
                "trigger": trigger,
                "source": source,
                "settings": settings,
                "adapter": adapter,
                "today": today,
                "overlap_days": overlap_days,
            },
            daemon=True,
            name=f"asqt-sync-{run_id[:8]}",
        )
        thread.start()
        return {"accepted": True, "run_id": run_id, "status": "queued", "trigger": trigger}
    return _execute_sync(
        run_id=run_id,
        trigger=trigger,
        source=source,
        settings=settings,
        adapter=adapter,
        today=today,
        overlap_days=overlap_days,
    )


def run_sync_job(
    *,
    trigger: str = "manual",
    source: str = "baostock",
    settings: Settings | None = None,
    adapter=None,
    today: str | None = None,
    overlap_days: int = 1,
) -> dict:
    return start_sync_job(
        trigger=trigger,
        source=source,
        settings=settings,
        adapter=adapter,
        today=today,
        overlap_days=overlap_days,
        background=False,
    )


def vendor_asof_ready(
    adapter,
    symbols: list[str],
    asof: str,
) -> dict:
    """Primary source has a daily bar for every symbol on the session as-of date."""
    need = [item for item in symbols if item]
    if not need or not asof:
        return {"ready": False, "have": 0, "need": len(need), "asof": asof}
    try:
        rows = adapter.fetch_market_daily(need, asof, asof)
    except Exception as exc:  # noqa: BLE001
        return {"ready": False, "have": 0, "need": len(need), "asof": asof, "error": str(exc)[:200]}
    have: set[str] = set()
    for row in rows or []:
        symbol = str(row.get("symbol") or "")
        if symbol in need and _row_trade_date(row) == asof:
            have.add(symbol)
    return {"ready": len(have) >= len(need), "have": len(have), "need": len(need), "asof": asof}


def should_auto_run(
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
    adapter=None,
    symbols: list[str] | None = None,
    asof: str | None = None,
    enabled: bool | None = None,
) -> bool:
    if enabled is None:
        enabled = auto_sync_enabled()
    if not enabled:
        return False
    current = now or _shanghai_now()
    if not _auto_window_open(current):
        return False
    if active_sync_run(settings=settings):
        return False
    if _auto_qc_done_today(current, settings=settings):
        return False
    if _deadline_reached(current):
        return True
    asof_date = asof or session_asof_date(current)
    wanted = symbols if symbols is not None else _auto_symbols(settings)
    source = adapter or build_sync_adapter("baostock")
    return bool(vendor_asof_ready(source, wanted, asof_date).get("ready"))


def auto_loop(stop: threading.Event, settings: Settings) -> None:
    while not stop.wait(30):
        try:
            if should_auto_run(settings):
                start_sync_job(trigger="auto", settings=settings, background=True)
        except Busy:
            pass
        except Exception:
            pass
        try:
            from asqt.reconcile_jobs import run_reconcile_job, should_auto_reconcile

            if should_auto_reconcile(settings):
                run_reconcile_job(trigger="auto", settings=settings)
        except Exception:
            pass
        try:
            from asqt.paper_reconcile_jobs import run_cash_reconcile_job, should_auto_cash_reconcile

            if should_auto_cash_reconcile(settings):
                run_cash_reconcile_job(trigger="auto", settings=settings)
        except Exception:
            continue


def _run_guarded(**kwargs) -> None:
    run_id = kwargs.get("run_id")
    settings = kwargs.get("settings")
    try:
        _execute_sync(**kwargs)
    except Exception:
        if run_id and not _abandoned(run_id, settings):
            _finish(run_id, status="failed", fail_reason="同步线程异常退出", settings=settings)
    finally:
        if run_id:
            _release_lock(run_id, settings)


def _execute_sync(
    *,
    run_id: str,
    trigger: str,
    source: str,
    settings: Settings,
    adapter,
    today: str | None,
    overlap_days: int,
) -> dict:
    _patch(run_id, status="running", started_at=_now(), progress_pct=0, settings=settings)
    try:
        symbols = []
        try:
            symbols = poc_symbols(settings)
        except Exception:
            symbols = []
        if not symbols:
            symbols = [
                row["symbol"]
                for row in query_all("SELECT symbol FROM instrument_master ORDER BY symbol", settings=settings)
            ]
        if not symbols:
            return _finish(run_id, status="failed", fail_reason="宇宙名单为空，无法追加", settings=settings)
        _set_progress(run_id, settings, pct=1, done=0, total=len(symbols), symbol="")

        last_done = -99

        def report(info: dict) -> None:
            nonlocal last_done
            if _abandoned(run_id, settings):
                return
            done = int(info.get("done") or 0)
            total = int(info.get("total") or 0)
            if done not in {0, 1, total} and done - last_done < 5:
                return
            last_done = done
            _set_progress(
                run_id,
                settings,
                pct=int(info.get("pct") or 0),
                done=info.get("done"),
                total=info.get("total"),
                symbol=info.get("symbol") or "",
            )

        _before_min, before_max = market_daily_span(settings)
        pull = pull_daily_append(
            symbols,
            settings=settings,
            adapter=adapter or build_sync_adapter(source),
            source=source,
            today=today or session_asof_date(),
            overlap_days=overlap_days,
            run_check=False,
            on_progress=report,
        )
        if _abandoned(run_id, settings):
            return get_sync_run(run_id, settings=settings) or {"run_id": run_id, "status": "failed"}
        _set_progress(run_id, settings, pct=92, done=len(symbols), total=len(symbols), symbol="")
        _after_min, after_max = market_daily_span(settings)
        _patch(
            run_id,
            start_date=pull.get("start"),
            end_date=pull.get("end"),
            max_trade_date_before=before_max or pull.get("max_trade_date_before") or pull.get("max_trade_date"),
            max_trade_date_after=after_max,
            normalized_rows=pull.get("normalized_rows") or 0,
            settings=settings,
        )
        if pull.get("reason") == "no_stored_bars":
            return _finish(
                run_id,
                status="failed",
                fail_reason="本地没有日K，无法追加。请先用 pull-daily --start/--end 做一次历史拉取",
                detail={"pull": _safe(pull)},
                settings=settings,
            )
        if _abandoned(run_id, settings):
            return get_sync_run(run_id, settings=settings) or {"run_id": run_id, "status": "failed"}
        _set_progress(run_id, settings, pct=95, done=len(symbols), total=len(symbols), symbol="")
        asof = today or session_asof_date()
        quality_start = _iso_minus_days(asof, 14)
        pull_start = pull.get("start")
        if pull_start:
            quality_start = min(str(quality_start), _iso_minus_days(str(pull_start), 10))
        quality = check_market_daily(settings=settings, expected_symbols=symbols, start=quality_start)
        issue_count = int(quality.get("issue_count") or 0)
        quality_ok = bool(quality.get("ok"))
        trade_allowed = bool(quality.get("trade_allowed"))
        fail_reason = None
        if not quality_ok or not trade_allowed:
            blocks = [item for item in (quality.get("issues") or []) if item.get("severity") == "block"]
            sample = blocks[0] if blocks else ((quality.get("issues") or [None])[0])
            extra = ""
            if sample:
                extra = f"：{sample.get('check_type')} {sample.get('symbol') or ''} {sample.get('trade_date') or ''}".strip()
            fail_reason = f"质检未通过，阻断 {len(blocks)} 条{extra}"
            status = "quality_failed"
        elif pull.get("skipped"):
            status = "skipped"
        else:
            status = "success"
        if _abandoned(run_id, settings):
            return get_sync_run(run_id, settings=settings) or {"run_id": run_id, "status": "failed"}
        row = _finish(
            run_id,
            status=status,
            quality_ok=1 if quality_ok else 0,
            trade_allowed=1 if trade_allowed else 0,
            issue_count=issue_count,
            fail_reason=fail_reason,
            detail={"pull": _safe(pull), "quality": _quality_summary(quality)},
            max_trade_date_after=after_max,
            settings=settings,
        )
        _write_task_run(row, settings)
        if status in {"success", "skipped"}:
            from asqt.paper import after_market_ready

            paper_follow = after_market_ready(
                asof=after_max or row.get("max_trade_date_after"),
                trigger=str(row.get("trigger") or "manual"),
                settings=settings,
            )
            if paper_follow:
                row = dict(row)
                row["paper_daily"] = paper_follow
        return row
    except Exception as exc:
        if _abandoned(run_id, settings):
            return get_sync_run(run_id, settings=settings) or {"run_id": run_id, "status": "failed"}
        return _finish(run_id, status="failed", fail_reason=str(exc)[:500], settings=settings)
    finally:
        _release_lock(run_id, settings)


def _quality_summary(quality: dict) -> dict:
    issues = list(quality.get("issues") or [])
    blocks = [item for item in issues if item.get("severity") == "block"]
    picked = blocks or issues
    return {
        "ok": quality.get("ok"),
        "trade_allowed": quality.get("trade_allowed"),
        "issue_count": quality.get("issue_count"),
        "block_count": len(blocks),
        "sample": [
            {
                "symbol": item.get("symbol"),
                "trade_date": item.get("trade_date"),
                "check_type": item.get("check_type"),
                "severity": item.get("severity"),
                "diff": (item.get("diff") or "")[:180],
            }
            for item in picked[:5]
        ],
    }


def _safe(value):
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items() if key != "quality"}
    if isinstance(value, list):
        return [_safe(item) for item in value[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _patch(run_id: str, settings: Settings | None = None, **fields) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    execute(
        f"UPDATE data_sync_run SET {assignments} WHERE run_id = ?",
        (*fields.values(), run_id),
        settings=settings,
    )


def _finish(run_id: str, *, status: str, settings: Settings | None = None, **fields) -> dict:
    payload = {key: value for key, value in fields.items()}
    if "detail" in payload and not isinstance(payload["detail"], str):
        payload["detail"] = json.dumps(payload["detail"], ensure_ascii=False)
    payload["status"] = status
    payload["finished_at"] = _now()
    payload["inflight"] = None
    if status in {"success", "skipped"}:
        payload["progress_pct"] = 100
    _patch(run_id, settings=settings, **payload)
    _release_lock(run_id, settings)
    return get_sync_run(run_id, settings=settings) or {"run_id": run_id, "status": status}


def _write_task_run(row: dict, settings: Settings) -> None:
    execute(
        """
        INSERT INTO task_run (run_id, task_name, status, started_at, finished_at, message)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("run_id") or str(uuid4()),
            "sync_daily",
            row.get("status") or "failed",
            row.get("started_at") or _now(),
            row.get("finished_at"),
            (row.get("fail_reason") or row.get("max_trade_date_after") or "")[:300],
        ),
        settings=settings,
    )


def _expire_stale_runs(settings: Settings | None = None) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_RUNNING_MINUTES)).isoformat()
    stale = query_all(
        """
        SELECT run_id FROM data_sync_run
        WHERE status IN ('queued', 'running') AND COALESCE(started_at, created_at) < ?
        """,
        (cutoff,),
        settings=settings,
    )
    for row in stale:
        _finish(row["run_id"], status="failed", fail_reason="任务超时未结束", settings=settings)
        _release_lock(row["run_id"], settings)


def _auto_window_open(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    return _clock_minutes(now) >= AUTO_HOUR * 60 + AUTO_MINUTE


def _deadline_reached(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    return _clock_minutes(now) >= DEADLINE_HOUR * 60 + DEADLINE_MINUTE


def _clock_minutes(now: datetime) -> int:
    return now.hour * 60 + now.minute


def _next_auto_at(now: datetime, *, done: bool = False) -> datetime:
    start = now.replace(hour=AUTO_HOUR, minute=AUTO_MINUTE, second=0, microsecond=0)
    deadline = now.replace(hour=DEADLINE_HOUR, minute=DEADLINE_MINUTE, second=0, microsecond=0)
    if now.weekday() < 5 and not done:
        if now < start:
            return start
        if now < deadline:
            return deadline
        return now.replace(second=0, microsecond=0)
    candidate = start + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.replace(hour=AUTO_HOUR, minute=AUTO_MINUTE, second=0, microsecond=0)


def _row_trade_date(row: dict) -> str:
    return str(row.get("trade_date") or row.get("date") or "")[:10]


def _shanghai_day(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return str(value)[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SHANGHAI).date().isoformat()


def _auto_symbols(settings: Settings | None = None) -> list[str]:
    rows = query_all("SELECT symbol FROM instrument_master ORDER BY symbol", settings=settings)
    symbols = [str(row["symbol"]) for row in rows if row.get("symbol")]
    return symbols or poc_symbols(settings)


def _shanghai_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SHANGHAI)


def _auto_qc_done_today(now: datetime, *, settings: Settings | None = None) -> bool:
    """Stop in-process auto only after today's session asof is covered, or an evening job finished.

    A morning manual pull that only has yesterday's K must not cancel the 16:30 window.
    """
    today = now.date().isoformat()
    asof = session_asof_date(now)
    window_minutes = AUTO_HOUR * 60 + AUTO_MINUTE
    rows = query_all(
        """
        SELECT status, finished_at, created_at, started_at, max_trade_date_after
        FROM data_sync_run
        WHERE status IN ('success', 'skipped')
        """,
        settings=settings,
    )
    for row in rows:
        day = _shanghai_day(row.get("finished_at") or row.get("created_at"))
        if day != today:
            continue
        max_d = str(row.get("max_trade_date_after") or "")[:10]
        if max_d and max_d >= asof:
            return True
        started = _shanghai_dt(row.get("started_at") or row.get("created_at") or row.get("finished_at"))
        if (
            _deadline_reached(now)
            and started
            and started.date().isoformat() == today
            and _clock_minutes(started) >= window_minutes
        ):
            return True
    return False

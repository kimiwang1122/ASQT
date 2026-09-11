"""Post-close cross-source reconcile job (staggered from sync / cron fallback)."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import execute, initialize_database, query_all
from asqt.universe import poc_symbols

SHANGHAI = ZoneInfo("Asia/Shanghai")
# After sync window (16:30–18:00) and before cron fallback (20:05).
RECONCILE_HOUR = 19
RECONCILE_MINUTE = 15
DEFAULT_LOOKBACK_DAYS = 14
TASK_NAME = "reconcile-daily"
# Whole-job budget; peer fetch has its own ASQT_RECONCILE_PEER_TIMEOUT_S (default 600s).
DEFAULT_JOB_TIMEOUT_S = 900


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shanghai_now() -> datetime:
    return datetime.now(SHANGHAI)


def auto_reconcile_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("ASQT_RECONCILE_AUTO", "1") != "0"


def reconcile_window_label() -> str:
    return f"{RECONCILE_HOUR:02d}:{RECONCILE_MINUTE:02d}"


def _job_timeout_s() -> float:
    raw = os.environ.get("ASQT_RECONCILE_TIMEOUT_S", str(DEFAULT_JOB_TIMEOUT_S))
    try:
        return max(60.0, float(raw))
    except ValueError:
        return float(DEFAULT_JOB_TIMEOUT_S)


def reconcile_snapshot(settings: Settings | None = None) -> dict[str, Any]:
    now = _shanghai_now()
    done = _reconcile_done_today(now, settings=settings)
    return {
        "enabled": auto_reconcile_enabled(),
        "timezone": "Asia/Shanghai",
        "window": reconcile_window_label(),
        "lookback_days": DEFAULT_LOOKBACK_DAYS,
        "due": _reconcile_window_open(now) and not done,
        "next_at": _next_reconcile_at(now, done=done).isoformat(),
        "last": _last_reconcile_task(settings=settings),
        "timeout_s": int(_job_timeout_s()),
        "note": (
            f"每个交易日 {reconcile_window_label()} 自动跨源对账（与 16:30 同步、20:05 cron 错开）；"
            "auto peer 优先 Tushare；超时强制失败并飞书告警。"
        ),
    }


def should_auto_reconcile(settings: Settings | None = None) -> bool:
    if not auto_reconcile_enabled():
        return False
    now = _shanghai_now()
    if not _reconcile_window_open(now):
        return False
    if _reconcile_done_today(now, settings=settings):
        return False
    if _reconcile_inflight(settings=settings):
        return False
    return True


def run_reconcile_job(
    *,
    trigger: str = "manual",
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    peer_source: str = "auto",
    settings: Settings | None = None,
    notify: bool = True,
    symbols: list[str] | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FuturesTimeout

    from asqt.pipeline import reconcile_daily

    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    kind = (trigger or "manual").strip().lower() or "manual"
    if _reconcile_inflight(settings=settings):
        return {
            "ok": False,
            "skipped": True,
            "reason": "inflight",
            "trigger": kind,
            "message": "已有跨源对账进行中，跳过本次触发",
        }
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=max(1, int(lookback_days)))).isoformat()
    wanted = list(symbols) if symbols is not None else poc_symbols(settings)
    budget = float(timeout_s) if timeout_s is not None else _job_timeout_s()
    run_id = str(uuid4())
    started = _now()
    execute(
        """
        INSERT INTO task_run (run_id, task_name, status, started_at, finished_at, message)
        VALUES (?, ?, 'running', ?, NULL, ?)
        """,
        (
            run_id,
            TASK_NAME,
            started,
            f"trigger={kind}; window={start}~{end}; peer={peer_source}; timeout={int(budget)}s",
        ),
        settings=settings,
    )
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="asqt-reconcile-job") as pool:
            future = pool.submit(
                reconcile_daily,
                wanted,
                start,
                end,
                settings=settings,
                peer_source=peer_source,
                record_task=False,
                notify=False,
            )
            try:
                report = future.result(timeout=budget)
            except FuturesTimeout as exc:
                raise TimeoutError(f"跨源对账超时（>{int(budget)}s）") from exc
        comparison = report.get("comparison") or {}
        silent = report.get("silent_factor_jumps") or {}
        mismatch = int(comparison.get("mismatch_count") or 0)
        inconsistent = int(silent.get("inconsistent_count") or 0)
        peer_errors = int(report.get("peer_error_count") or 0)
        status = "success" if mismatch == 0 and inconsistent == 0 and peer_errors == 0 else "partial"
        message = _task_message(report, trigger=kind)
        execute(
            """
            UPDATE task_run
            SET status = ?, finished_at = ?, message = ?
            WHERE run_id = ?
            """,
            (status, _now(), message, run_id),
            settings=settings,
        )
        report = dict(report)
        report["task_run_id"] = run_id
        report["task_status"] = status
        report["trigger"] = kind
        report["ok"] = True
        if notify:
            _notify_reconcile(report, settings=settings)
        return report
    except Exception as exc:
        execute(
            """
            UPDATE task_run
            SET status = 'failed', finished_at = ?, message = ?
            WHERE run_id = ?
            """,
            (_now(), f"trigger={kind}; error={str(exc)[:240]}", run_id),
            settings=settings,
        )
        if notify:
            _notify_reconcile_failure(
                settings=settings,
                trigger=kind,
                start=start,
                end=end,
                error=str(exc),
            )
        if isinstance(exc, TimeoutError):
            return {
                "ok": False,
                "task_run_id": run_id,
                "task_status": "failed",
                "trigger": kind,
                "error": str(exc),
                "timed_out": True,
            }
        raise


def _notify_reconcile_failure(
    *,
    settings: Settings,
    trigger: str,
    start: str,
    end: str,
    error: str,
) -> None:
    from asqt.alert_format import encode_alert_detail
    from asqt.ops import LocalAlertService

    alerts = LocalAlertService(settings)
    prior = query_all(
        """
        SELECT alert_id FROM alert
        WHERE status = 'open' AND category = 'reconcile'
          AND title IN ('跨源对账完成', '跨源对账待复核', '跨源对账失败')
        """,
        settings=settings,
    )
    for row in prior:
        alerts.close_alert(str(row["alert_id"]), reason="replaced by newer reconcile result")
    alerts.raise_alert(
        "high",
        "reconcile",
        "跨源对账失败",
        encode_alert_detail(
            {
                "schema": "asqt.alert.v1",
                "kind": "cross_source_reconcile",
                "summary": f"跨源对账失败：{error[:120]}",
                "trigger": trigger,
                "window": f"{start}~{end}",
                "action": "请查看最近任务与 logs；可手动 asqt reconcile --peer tushare 重跑。",
            }
        ),
    )


def _task_message(report: dict[str, Any], *, trigger: str) -> str:
    comparison = report.get("comparison") or {}
    silent = report.get("silent_factor_jumps") or {}
    match_rate = comparison.get("match_rate")
    rate_text = f"{float(match_rate) * 100:.2f}%" if match_rate is not None else "-"
    return (
        f"trigger={trigger}; "
        f"{report.get('start')}~{report.get('end')}; "
        f"匹配 {comparison.get('matched_rows', 0)}/{comparison.get('stored_rows', 0)} "
        f"({rate_text}); "
        f"差异 {comparison.get('mismatch_count', 0)}; "
        f"静默跳变异常 {silent.get('inconsistent_count', 0)}; "
        f"peer错误 {report.get('peer_error_count', 0)}"
    )


def _notify_reconcile(report: dict[str, Any], *, settings: Settings) -> None:
    from asqt.alert_format import encode_alert_detail, public_report_ref
    from asqt.ops import LocalAlertService

    comparison = report.get("comparison") or {}
    silent = report.get("silent_factor_jumps") or {}
    mismatch = int(comparison.get("mismatch_count") or 0)
    inconsistent = int(silent.get("inconsistent_count") or 0)
    peer_errors = int(report.get("peer_error_count") or 0)
    baseline = int(comparison.get("adj_baseline_count") or len(report.get("adj_baselines") or []))
    match_rate = comparison.get("match_rate")
    rate_text = f"{float(match_rate) * 100:.2f}%" if match_rate is not None else "-"
    clean = mismatch == 0 and inconsistent == 0 and peer_errors == 0
    if clean and baseline:
        summary = f"跨源对账完成 · 匹配率 {rate_text} · 因子基准已对齐 {baseline} 标的"
    elif clean:
        summary = f"跨源对账完成 · 匹配率 {rate_text}"
    else:
        summary = f"跨源对账待复核 · 差异 {mismatch} · 静默异常 {inconsistent}"
    title = "跨源对账完成" if clean else "跨源对账待复核"
    payload = {
        "schema": "asqt.alert.v1",
        "kind": "cross_source_reconcile",
        "summary": summary,
        "trigger": report.get("trigger"),
        "window": f"{report.get('start')}~{report.get('end')}",
        "symbols": report.get("symbols"),
        "matched_rows": comparison.get("matched_rows"),
        "stored_rows": comparison.get("stored_rows"),
        "peer_rows": comparison.get("peer_rows"),
        "match_rate": match_rate,
        "match_rate_pct": None if match_rate is None else round(float(match_rate) * 100, 4),
        "mismatch_count": mismatch,
        "adj_baseline_count": baseline,
        "silent_inconsistent": inconsistent,
        "peer_error_count": peer_errors,
        "report": public_report_ref(report.get("report_path")),
        "action": (
            (
                "主源与对照源一致；复权因子绝对水平不同但已按比例对齐，不改库、不挡交易。"
                if baseline
                else "主源与对照源一致，无需处理。"
            )
            if clean
            else "差异已写入质量问题（warn，不挡交易）；可到「数据」页筛选跨源项查看。"
        ),
    }
    alerts = LocalAlertService(settings)
    prior = query_all(
        """
        SELECT alert_id FROM alert
        WHERE status = 'open' AND category = 'reconcile'
          AND title IN ('跨源对账完成', '跨源对账待复核', '跨源对账失败')
        """,
        settings=settings,
    )
    for row in prior:
        alerts.close_alert(str(row["alert_id"]), reason="replaced by newer reconcile result")
    alerts.raise_alert("high", "reconcile", title, encode_alert_detail(payload))


def _reconcile_window_open(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    return (now.hour * 60 + now.minute) >= RECONCILE_HOUR * 60 + RECONCILE_MINUTE


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


STALE_RUNNING_MINUTES = 45


def recover_orphaned_reconcile_runs(settings: Settings | None = None) -> int:
    """Mark stale running/queued reconcile tasks failed (other process may still be live)."""
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    rows = query_all(
        """
        SELECT run_id, started_at, created_at FROM task_run
        WHERE task_name IN ('reconcile-daily', 'reconcile_daily')
          AND status IN ('queued', 'running')
        """,
        settings=settings,
    )
    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - STALE_RUNNING_MINUTES * 60
    recovered = 0
    for row in rows:
        started = row.get("started_at") or row.get("created_at")
        try:
            parsed = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age_ts = parsed.astimezone(timezone.utc).timestamp()
        except ValueError:
            age_ts = 0
        if age_ts > cutoff:
            continue
        execute(
            """
            UPDATE task_run
            SET status = 'failed', finished_at = ?, message = COALESCE(message, '') || ?
            WHERE run_id = ? AND status IN ('queued', 'running')
            """,
            (_now(), f"; orphaned stale >{STALE_RUNNING_MINUTES}m", row["run_id"]),
            settings=settings,
        )
        recovered += 1
    return recovered


def _reconcile_done_today(now: datetime, *, settings: Settings | None = None) -> bool:
    today = now.date().isoformat()
    rows = query_all(
        """
        SELECT status, finished_at, started_at, created_at
        FROM task_run
        WHERE task_name IN ('reconcile-daily', 'reconcile_daily')
          AND status IN ('success', 'partial')
        ORDER BY COALESCE(finished_at, started_at, created_at) DESC
        LIMIT 20
        """,
        settings=settings,
    )
    for row in rows:
        day = _shanghai_day(row.get("finished_at") or row.get("started_at") or row.get("created_at"))
        if day == today:
            return True
    return False


def _reconcile_inflight(*, settings: Settings | None = None) -> bool:
    rows = query_all(
        """
        SELECT COUNT(*) AS c FROM task_run
        WHERE task_name IN ('reconcile-daily', 'reconcile_daily')
          AND status IN ('queued', 'running')
        """,
        settings=settings,
    )
    return int(rows[0]["c"] if rows else 0) > 0


def _last_reconcile_task(*, settings: Settings | None = None) -> dict[str, Any] | None:
    rows = query_all(
        """
        SELECT * FROM task_run
        WHERE task_name IN ('reconcile-daily', 'reconcile_daily')
        ORDER BY COALESCE(finished_at, started_at, created_at) DESC
        LIMIT 1
        """,
        settings=settings,
    )
    return rows[0] if rows else None


def _next_reconcile_at(now: datetime, *, done: bool = False) -> datetime:
    start = now.replace(hour=RECONCILE_HOUR, minute=RECONCILE_MINUTE, second=0, microsecond=0)
    if now.weekday() < 5 and not done and now < start:
        return start
    if now.weekday() < 5 and not done and now >= start:
        return now.replace(second=0, microsecond=0)
    candidate = start + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.replace(hour=RECONCILE_HOUR, minute=RECONCILE_MINUTE, second=0, microsecond=0)

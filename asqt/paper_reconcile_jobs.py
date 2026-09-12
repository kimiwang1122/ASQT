"""Post-close paper cash reconcile job (staggered after cross-source reconcile)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import execute, initialize_database, query_all
from asqt.strategies import STRATEGY_SPECS

SHANGHAI = ZoneInfo("Asia/Shanghai")
# After cross-source (19:15) and before cron fallback (20:05).
CASH_RECONCILE_HOUR = 19
CASH_RECONCILE_MINUTE = 45
TASK_NAME = "cash-reconcile"
STALE_RUNNING_MINUTES = 30
STRATEGY_LABEL = {
    "etf_ma_rotate": "ETF 均线轮动",
    "stock_momentum_topk": "股票动量 TopK",
    "etf_momentum_topk": "ETF 动量 TopK",
    "stock_lowvol_momentum": "股票低波动量",
    "etf_ma_momentum_filter": "ETF 均线动量过滤",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shanghai_now() -> datetime:
    return datetime.now(SHANGHAI)


def auto_cash_reconcile_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("ASQT_CASH_RECONCILE_AUTO", "1") != "0"


def cash_reconcile_window_label() -> str:
    return f"{CASH_RECONCILE_HOUR:02d}:{CASH_RECONCILE_MINUTE:02d}"


def cash_reconcile_snapshot(settings: Settings | None = None) -> dict[str, Any]:
    now = _shanghai_now()
    done = _cash_reconcile_done_today(now, settings=settings)
    return {
        "enabled": auto_cash_reconcile_enabled(),
        "timezone": "Asia/Shanghai",
        "window": cash_reconcile_window_label(),
        "due": _cash_reconcile_window_open(now) and not done,
        "next_at": _next_cash_reconcile_at(now, done=done).isoformat(),
        "last": _last_cash_reconcile_task(settings=settings),
        "note": (
            f"每个交易日 {cash_reconcile_window_label()} 自动财务对账（与 19:15 跨源、20:05 cron 错开）；"
            "结果写入最近任务并推送飞书。"
        ),
    }


def should_auto_cash_reconcile(settings: Settings | None = None) -> bool:
    if not auto_cash_reconcile_enabled():
        return False
    now = _shanghai_now()
    if not _cash_reconcile_window_open(now):
        return False
    if _cash_reconcile_done_today(now, settings=settings):
        return False
    if _cash_reconcile_inflight(settings=settings):
        return False
    return True


def run_cash_reconcile_job(
    *,
    trigger: str = "manual",
    settings: Settings | None = None,
    notify: bool = True,
    strategy_ids: list[str] | None = None,
) -> dict[str, Any]:
    from asqt.paper import paper_board

    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    kind = (trigger or "manual").strip().lower() or "manual"
    if _cash_reconcile_inflight(settings=settings):
        return {
            "ok": False,
            "skipped": True,
            "reason": "inflight",
            "trigger": kind,
            "message": "已有财务对账进行中，跳过本次触发",
        }
    ids = list(strategy_ids) if strategy_ids is not None else list(STRATEGY_SPECS)
    run_id = str(uuid4())
    started = _now()
    execute(
        """
        INSERT INTO task_run (run_id, task_name, status, started_at, finished_at, message)
        VALUES (?, ?, 'running', ?, NULL, ?)
        """,
        (run_id, TASK_NAME, started, f"trigger={kind}; strategies={len(ids)}"),
        settings=settings,
    )
    try:
        books: list[dict[str, Any]] = []
        for sid in ids:
            board = paper_board(sid, settings)
            summary = board.get("summary") or {}
            reconcile = board.get("reconcile") or {}
            sessions = int(summary.get("sessions") or 0)
            if sessions <= 0 or not reconcile.get("checks"):
                books.append(
                    {
                        "strategy_id": sid,
                        "strategy_label": STRATEGY_LABEL.get(sid, sid),
                        "skipped": True,
                        "ok": True,
                        "reason": "尚无账本",
                        "asof": None,
                    }
                )
                continue
            books.append(
                {
                    "strategy_id": sid,
                    "strategy_label": STRATEGY_LABEL.get(sid, sid),
                    "skipped": False,
                    "ok": bool(reconcile.get("ok")),
                    "asof": reconcile.get("asof") or summary.get("window_end"),
                    "initial_cash": reconcile.get("initial_cash"),
                    "peak_asset": reconcile.get("peak_asset"),
                    "actual_cash": reconcile.get("actual_cash"),
                    "expected_cash": reconcile.get("expected_cash"),
                    "cash_diff": reconcile.get("cash_diff"),
                    "market_value": reconcile.get("market_value"),
                    "end_asset": reconcile.get("end_asset"),
                    "qty_mismatches": len(reconcile.get("qty_mismatches") or []),
                    "failed_checks": [
                        row.get("name")
                        for row in (reconcile.get("checks") or [])
                        if not row.get("ok")
                    ],
                }
            )
        checked = [item for item in books if not item.get("skipped")]
        mismatches = [item for item in checked if not item.get("ok")]
        skipped = [item for item in books if item.get("skipped")]
        if not checked:
            status = "success"
            summary_text = f"财务对账跳过 · 无可用账本（{len(skipped)}）"
        elif not mismatches:
            status = "success"
            summary_text = f"财务对账通过 · {len(checked)}/{len(checked)}"
        else:
            status = "partial"
            bad = "、".join(item["strategy_label"] for item in mismatches[:3])
            summary_text = f"财务对账不一致 · {len(mismatches)}/{len(checked)}（{bad}）"
        message = (
            f"trigger={kind}; checked={len(checked)}; ok={len(checked) - len(mismatches)}; "
            f"mismatch={len(mismatches)}; skipped={len(skipped)}"
        )
        execute(
            """
            UPDATE task_run
            SET status = ?, finished_at = ?, message = ?
            WHERE run_id = ?
            """,
            (status, _now(), message, run_id),
            settings=settings,
        )
        report = {
            "ok": status == "success",
            "task_run_id": run_id,
            "task_status": status,
            "trigger": kind,
            "summary": summary_text,
            "checked": len(checked),
            "mismatch_count": len(mismatches),
            "skipped_count": len(skipped),
            "books": books,
        }
        if notify:
            _notify_cash_reconcile(report, settings=settings)
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
            _notify_cash_reconcile_failure(settings=settings, trigger=kind, error=str(exc))
        raise


def recover_orphaned_cash_reconcile_runs(settings: Settings | None = None) -> int:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    rows = query_all(
        """
        SELECT run_id, started_at, created_at FROM task_run
        WHERE task_name = ?
          AND status IN ('queued', 'running')
        """,
        (TASK_NAME,),
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


def _notify_cash_reconcile(report: dict[str, Any], *, settings: Settings) -> None:
    from asqt.alert_format import encode_alert_detail
    from asqt.ops import LocalAlertService

    status = str(report.get("task_status") or "")
    checked = int(report.get("checked") or 0)
    clean = status == "success"
    all_skipped = clean and checked == 0
    if all_skipped:
        title = "财务对账跳过"
    elif clean:
        title = "财务对账通过"
    else:
        title = "财务对账不一致"
    books = report.get("books") or []
    lines_preview = []
    for item in books:
        if item.get("skipped"):
            lines_preview.append(f"{item.get('strategy_label')}：尚无账本")
            continue
        if item.get("ok"):
            lines_preview.append(
                f"{item.get('strategy_label')}：通过（现金差额 {item.get('cash_diff')}）"
            )
        else:
            fails = "、".join(item.get("failed_checks") or []) or "检查项"
            lines_preview.append(
                f"{item.get('strategy_label')}：不一致（{fails}；现金差额 {item.get('cash_diff')}）"
            )
    if all_skipped:
        action = "尚无模拟账本，未做现金/持仓核对；请先跑模拟后再对账。"
    elif clean:
        action = "成交回推现金/持仓与账本一致，无需处理。"
    else:
        action = "请到交易页「财务对账」核对不一致账本；不一致不自动急停。"
    payload = {
        "schema": "asqt.alert.v1",
        "kind": "cash_reconcile",
        "summary": report.get("summary"),
        "trigger": report.get("trigger"),
        "checked": report.get("checked"),
        "mismatch_count": report.get("mismatch_count"),
        "skipped_count": report.get("skipped_count"),
        "books": books,
        "book_lines": lines_preview,
        "action": action,
    }
    alerts = LocalAlertService(settings)
    prior = query_all(
        """
        SELECT alert_id FROM alert
        WHERE status = 'open' AND category = 'cash_reconcile'
          AND title IN ('财务对账通过', '财务对账不一致', '财务对账失败', '财务对账跳过')
        """,
        settings=settings,
    )
    for row in prior:
        alerts.close_alert(str(row["alert_id"]), reason="replaced by newer cash reconcile result")
    alerts.raise_alert("high", "cash_reconcile", title, encode_alert_detail(payload))


def _notify_cash_reconcile_failure(*, settings: Settings, trigger: str, error: str) -> None:
    from asqt.alert_format import encode_alert_detail
    from asqt.ops import LocalAlertService

    alerts = LocalAlertService(settings)
    prior = query_all(
        """
        SELECT alert_id FROM alert
        WHERE status = 'open' AND category = 'cash_reconcile'
          AND title IN ('财务对账通过', '财务对账不一致', '财务对账失败', '财务对账跳过')
        """,
        settings=settings,
    )
    for row in prior:
        alerts.close_alert(str(row["alert_id"]), reason="replaced by newer cash reconcile result")
    alerts.raise_alert(
        "high",
        "cash_reconcile",
        "财务对账失败",
        encode_alert_detail(
            {
                "schema": "asqt.alert.v1",
                "kind": "cash_reconcile",
                "summary": f"财务对账失败：{error[:120]}",
                "trigger": trigger,
                "action": "请查看最近任务；可手动 asqt cash-reconcile 重跑。",
            }
        ),
    )


def _cash_reconcile_window_open(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    return (now.hour * 60 + now.minute) >= CASH_RECONCILE_HOUR * 60 + CASH_RECONCILE_MINUTE


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


def _cash_reconcile_done_today(now: datetime, *, settings: Settings | None = None) -> bool:
    today = now.date().isoformat()
    rows = query_all(
        """
        SELECT status, finished_at, started_at, created_at
        FROM task_run
        WHERE task_name = ?
          AND status IN ('success', 'partial')
        ORDER BY COALESCE(finished_at, started_at, created_at) DESC
        LIMIT 20
        """,
        (TASK_NAME,),
        settings=settings,
    )
    for row in rows:
        day = _shanghai_day(row.get("finished_at") or row.get("started_at") or row.get("created_at"))
        if day == today:
            return True
    return False


def _cash_reconcile_inflight(*, settings: Settings | None = None) -> bool:
    rows = query_all(
        """
        SELECT COUNT(*) AS c FROM task_run
        WHERE task_name = ? AND status IN ('queued', 'running')
        """,
        (TASK_NAME,),
        settings=settings,
    )
    return int(rows[0]["c"] if rows else 0) > 0


def _last_cash_reconcile_task(*, settings: Settings | None = None) -> dict[str, Any] | None:
    rows = query_all(
        """
        SELECT * FROM task_run
        WHERE task_name = ?
        ORDER BY COALESCE(finished_at, started_at, created_at) DESC
        LIMIT 1
        """,
        (TASK_NAME,),
        settings=settings,
    )
    return rows[0] if rows else None


def _next_cash_reconcile_at(now: datetime, *, done: bool = False) -> datetime:
    start = now.replace(hour=CASH_RECONCILE_HOUR, minute=CASH_RECONCILE_MINUTE, second=0, microsecond=0)
    if now.weekday() < 5 and not done and now < start:
        return start
    if now.weekday() < 5 and not done and now >= start:
        return now.replace(second=0, microsecond=0)
    candidate = start + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.replace(hour=CASH_RECONCILE_HOUR, minute=CASH_RECONCILE_MINUTE, second=0, microsecond=0)

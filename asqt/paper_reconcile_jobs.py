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
    "stock_short_reversal_topk": "股票短反转 TopK",
    "stock_momentum_volume_confirm": "股票动量量能确认",
    "stock_momentum_skip_month": "股票跳月动量",
    "stock_holder_increase_follow": "股票股东增持跟随",
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
            "含现金/持仓回推、组合本金份额与净资产合计校验；结果写入最近任务并推送飞书。"
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
    from asqt.ops import paper_account_config
    from asqt.paper import paper_admitted_ids, paper_board, portfolio_book_cash_map

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
        portfolio_cash = float(paper_account_config(settings)["initial_cash"])
        # Expect shares among books that actually have sessions (this-run funding model).
        active_ids = []
        boards_by_id: dict[str, dict[str, Any]] = {}
        for sid in ids:
            board = paper_board(sid, settings)
            boards_by_id[sid] = board
            summary = board.get("summary") or {}
            if int(summary.get("sessions") or 0) > 0 and (board.get("reconcile") or {}).get("checks"):
                active_ids.append(sid)
        universe = active_ids or paper_admitted_ids(settings) or list(ids)
        cash_map = portfolio_book_cash_map(settings, universe=universe)
        books: list[dict[str, Any]] = []
        for sid in ids:
            board = boards_by_id.get(sid) or paper_board(sid, settings)
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
            book = _validate_paper_book(
                strategy_id=sid,
                summary=summary,
                reconcile=reconcile,
                expected_share=cash_map.get(sid),
                portfolio_cash=portfolio_cash,
                funding_universe_size=len(universe),
            )
            books.append(book)
        checked = [item for item in books if not item.get("skipped")]
        book_mismatches = [item for item in checked if not item.get("ok")]
        skipped = [item for item in books if item.get("skipped")]
        portfolio = _validate_paper_portfolio(
            books=checked,
            portfolio_cash=portfolio_cash,
            universe=universe,
            cash_map=cash_map,
        )
        mismatches = list(book_mismatches)
        if portfolio.get("ok") is False:
            mismatches.append(
                {
                    "strategy_id": "__portfolio__",
                    "strategy_label": "组合资金",
                    "skipped": False,
                    "ok": False,
                    "failed_checks": list(portfolio.get("failed_checks") or []),
                }
            )

        if not checked:
            status = "success"
            summary_text = f"财务对账跳过 · 无可用账本（{len(skipped)}）"
        elif not mismatches:
            status = "success"
            nav = portfolio.get("nav")
            summary_text = (
                f"财务对账通过 · {len(checked)}/{len(checked)}；组合净资产 {float(nav):.2f}"
                if nav is not None
                else f"财务对账通过 · {len(checked)}/{len(checked)}"
            )
        else:
            status = "partial"
            labels = [item["strategy_label"] for item in book_mismatches[:3]]
            if portfolio.get("ok") is False:
                labels = (labels + ["组合资金"])[:3]
            bad = "、".join(labels) if labels else "组合资金"
            summary_text = f"财务对账不一致 · {len(mismatches)} 项（{bad}）"
        message = (
            f"trigger={kind}; checked={len(checked)}; "
            f"book_ok={len(checked) - len(book_mismatches)}; "
            f"book_mismatch={len(book_mismatches)}; skipped={len(skipped)}; "
            f"portfolio_ok={portfolio.get('ok')}; deployed={portfolio.get('deployed')}; "
            f"nav={portfolio.get('nav')}"
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
            "portfolio": portfolio,
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


def _approx(a: float, b: float, *, abs_tol: float = 0.05, rel: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= max(abs_tol, abs(float(b)) * rel)


def _validate_paper_book(
    *,
    strategy_id: str,
    summary: dict[str, Any],
    reconcile: dict[str, Any],
    expected_share: float | None,
    portfolio_cash: float,
    funding_universe_size: int,
) -> dict[str, Any]:
    failed: list[str] = []
    initial = float(summary.get("initial_cash") or 0)
    end_asset = float(summary.get("end_asset") or 0)
    cash = float(summary.get("cash") or 0)
    market_value = float(summary.get("market_value") or 0)
    peak = float(summary.get("peak_asset") or 0)
    total_return = float(summary.get("total_return") or 0)
    peak_return = float(summary.get("peak_return") or 0)

    if not bool(reconcile.get("ok")):
        failed.extend(
            [
                str(row.get("name") or "对账项")
                for row in (reconcile.get("checks") or [])
                if not row.get("ok")
            ]
            or ["财务回推"]
        )
    if reconcile.get("qty_mismatches"):
        failed.append("持仓数量")

    if expected_share is not None and not _approx(initial, expected_share, abs_tol=0.02):
        failed.append("本金份额")
    if not _approx(end_asset, cash + market_value, abs_tol=0.05):
        failed.append("净资产恒等式")
    if initial > 0 and not _approx(total_return, end_asset / initial - 1.0, abs_tol=1e-6):
        failed.append("累计收益")
    if initial > 0 and not _approx(peak_return, peak / initial - 1.0, abs_tol=1e-6):
        failed.append("峰值收益")
    if peak + 1e-9 < end_asset:
        failed.append("峰值资产")
    # Guard against legacy full-cash books when portfolio is shared across N>1.
    if (
        funding_universe_size > 1
        and expected_share is not None
        and expected_share < portfolio_cash * 0.9
        and initial >= portfolio_cash * 0.95
    ):
        failed.append("本金未均分")

    return {
        "strategy_id": strategy_id,
        "strategy_label": STRATEGY_LABEL.get(strategy_id, strategy_id),
        "skipped": False,
        "ok": not failed,
        "asof": reconcile.get("asof") or summary.get("window_end"),
        "initial_cash": initial,
        "expected_share": expected_share,
        "peak_asset": peak,
        "actual_cash": reconcile.get("actual_cash"),
        "expected_cash": reconcile.get("expected_cash"),
        "cash_diff": reconcile.get("cash_diff"),
        "market_value": market_value,
        "end_asset": end_asset,
        "total_return": total_return,
        "qty_mismatches": len(reconcile.get("qty_mismatches") or []),
        "failed_checks": failed,
    }


def _validate_paper_portfolio(
    *,
    books: list[dict[str, Any]],
    portfolio_cash: float,
    universe: list[str],
    cash_map: dict[str, float],
) -> dict[str, Any]:
    failed: list[str] = []
    if not books:
        return {
            "ok": True,
            "portfolio_cash": portfolio_cash,
            "funding_universe": universe,
            "deployed": 0.0,
            "nav": 0.0,
            "funding_complete": False,
            "failed_checks": [],
        }
    deployed = round(sum(float(item.get("initial_cash") or 0) for item in books), 4)
    nav = round(sum(float(item.get("end_asset") or 0) for item in books), 4)
    active_ids = {str(item.get("strategy_id")) for item in books}
    expected_deployed = round(
        sum(float(cash_map.get(sid) or 0) for sid in active_ids if sid in cash_map),
        4,
    )
    funding_complete = active_ids >= set(universe) and len(universe) > 0
    if expected_deployed > 0 and not _approx(deployed, expected_deployed, abs_tol=0.05):
        failed.append("已部署本金合计")
    if funding_complete and not _approx(deployed, portfolio_cash, abs_tol=0.05):
        failed.append("组合本金合计")
    # Detect old 5× full-cash inflation: NAV near N * portfolio.
    n = max(1, len(universe))
    if n > 1 and nav > portfolio_cash * (n * 0.75):
        failed.append("净资产疑似满额加总")
    if funding_complete and not (portfolio_cash * 0.4 <= nav <= portfolio_cash * 1.8):
        failed.append("组合净资产异常")
    return {
        "ok": not failed,
        "portfolio_cash": portfolio_cash,
        "funding_universe": universe,
        "deployed": deployed,
        "expected_deployed": expected_deployed,
        "nav": nav,
        "funding_complete": funding_complete,
        "failed_checks": failed,
    }


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
            share = item.get("expected_share")
            share_txt = f"；份额 {share}" if share is not None else ""
            lines_preview.append(
                f"{item.get('strategy_label')}：通过（现金差额 {item.get('cash_diff')}{share_txt}）"
            )
        else:
            fails = "、".join(item.get("failed_checks") or []) or "检查项"
            lines_preview.append(
                f"{item.get('strategy_label')}：不一致（{fails}；现金差额 {item.get('cash_diff')}）"
            )
    portfolio = report.get("portfolio") or {}
    if portfolio:
        port_status = "通过" if portfolio.get("ok") else "不一致"
        fails = "、".join(portfolio.get("failed_checks") or [])
        lines_preview.append(
            f"组合资金：{port_status} · 本金 {portfolio.get('portfolio_cash')} · "
            f"已部署 {portfolio.get('deployed')} · 净资产 {portfolio.get('nav')}"
            + (f"（{fails}）" if fails else "")
        )
    if all_skipped:
        action = "尚无模拟账本，未做现金/持仓核对；请先跑模拟后再对账。"
    elif clean:
        action = "成交回推与组合本金份额校验通过，无需处理。"
    else:
        action = "请到交易页「财务对账」核对；本金未均分请重置后重跑模拟；不一致不自动急停。"
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
        "portfolio": portfolio,
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

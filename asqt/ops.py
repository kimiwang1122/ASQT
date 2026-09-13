"""Kill switch, local alerts, and Feishu webhook fan-out."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import execute, initialize_database, query_all

KILL_CATEGORY = "kill_switch"
PAPER_TRADING_CATEGORY = "paper_trading"
# Defaults kept for backward-compatible imports; runtime reads paper_account_config().
DRAWDOWN_STOP = -0.12
DRAWDOWN_WARN = -0.08
DEFAULT_PORTFOLIO_DRAWDOWN_STOP = 0.12
DEFAULT_STRATEGY_DRAWDOWN_STOP = 0.12
DEFAULT_DRAWDOWN_WARN = 0.08
PAPER_CASH_KEY = "paper.initial_cash"
PAPER_COMMISSION_KEY = "paper.commission_rate"
PAPER_PORTFOLIO_PEAK_KEY = "paper.portfolio_peak"
PAPER_DD_PORTFOLIO_STOP_KEY = "paper.portfolio_drawdown_stop"
PAPER_DD_STRATEGY_STOP_KEY = "paper.strategy_drawdown_stop"
PAPER_DD_WARN_KEY = "paper.drawdown_warn"
DEFAULT_PAPER_CASH = 1_000_000.0
DEFAULT_PAPER_COMMISSION = 0.00025


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def quality_gate(settings: Settings | None = None) -> dict[str, Any]:
    rows = query_all(
        "SELECT COUNT(*) AS c FROM quality_issue WHERE status = 'open' AND severity = 'block'",
        settings=settings,
    )
    blocks = int(rows[0]["c"]) if rows else 0
    return {"trade_allowed": blocks == 0, "block_count": blocks, "source": "quality_issue"}


class LocalAlertService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = ensure_runtime_dirs(settings or get_settings())
        initialize_database(self.settings)

    def raise_alert(
        self,
        level: str,
        category: str,
        title: str,
        detail: str | None = None,
        *,
        status: str = "open",
    ) -> dict[str, Any]:
        alert_id = str(uuid4())
        now = _now()
        execute(
            """
            INSERT INTO alert
                (alert_id, level, category, status, title, detail, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (alert_id, level, category, status, title, detail, now, now),
            settings=self.settings,
        )
        row = {
            "alert_id": alert_id,
            "level": level,
            "category": category,
            "status": status,
            "title": title,
            "detail": detail,
            "created_at": now,
            "updated_at": now,
        }
        self._fanout(row)
        return row

    def list_alerts(
        self,
        limit: int = 50,
        *,
        status: str | None = "open",
    ) -> list[dict[str, Any]]:
        from asqt.alert_format import hydrate_alert_row

        limit = max(1, min(200, int(limit)))
        if status:
            rows = query_all(
                """
                SELECT * FROM alert
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
                settings=self.settings,
            )
        else:
            rows = query_all(
                "SELECT * FROM alert ORDER BY created_at DESC LIMIT ?",
                (limit,),
                settings=self.settings,
            )
        hydrated: list[dict[str, Any]] = []
        for row in rows:
            upgraded = hydrate_alert_row(row, settings=self.settings)
            if upgraded.get("detail") != row.get("detail"):
                execute(
                    "UPDATE alert SET detail = ?, updated_at = ? WHERE alert_id = ?",
                    (upgraded.get("detail"), _now(), row["alert_id"]),
                    settings=self.settings,
                )
            hydrated.append(upgraded)
        return hydrated

    def close_alert(self, alert_id: str, *, reason: str | None = None) -> dict[str, Any] | None:
        rows = query_all(
            "SELECT * FROM alert WHERE alert_id = ?",
            (alert_id,),
            settings=self.settings,
        )
        if not rows:
            return None
        execute(
            "UPDATE alert SET status = 'closed', updated_at = ?, detail = COALESCE(?, detail) WHERE alert_id = ?",
            (_now(), reason, alert_id),
            settings=self.settings,
        )
        rows[0]["status"] = "closed"
        return rows[0]

    def close_alerts(
        self,
        alert_ids: list[str],
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        ids = [str(item).strip() for item in alert_ids if str(item).strip()]
        closed = 0
        missing: list[str] = []
        for alert_id in ids:
            row = self.close_alert(alert_id, reason=reason)
            if row:
                closed += 1
            else:
                missing.append(alert_id)
        return {"ok": True, "closed": closed, "missing": missing, "requested": len(ids)}

    def analyze_open_alerts(self, *, limit: int = 200) -> dict[str, Any]:
        rows = self.list_alerts(limit=limit, status="open")
        kill_on = kill_engaged(self.settings)
        groups_map: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = f"{row.get('category')}|{row.get('title')}|{row.get('level')}"
            bucket = groups_map.setdefault(
                key,
                {
                    "key": key,
                    "category": row.get("category"),
                    "title": row.get("title"),
                    "level": row.get("level"),
                    "items": [],
                },
            )
            bucket["items"].append(row)

        groups: list[dict[str, Any]] = []
        noise_ids: list[str] = []
        state_ids: list[str] = []
        signal_ids: list[str] = []

        for bucket in groups_map.values():
            items = sorted(
                bucket["items"],
                key=lambda item: str(item.get("created_at") or ""),
                reverse=True,
            )
            category = str(bucket["category"] or "")
            level = str(bucket["level"] or "")
            title = str(bucket["title"] or "")
            ids = [str(item["alert_id"]) for item in items]
            latest = items[0]
            if category == PAPER_TRADING_CATEGORY and level == "info":
                kind = "state"
                keep = ids[:1]
                noise = ids[1:]
                advice = "模拟开关状态提示，不是故障；若开关本意就是开着，可保留。"
                state_ids.extend(ids)
            elif category in {KILL_CATEGORY, "drawdown"} and len(ids) > 1:
                kind = "dup"
                keep = ids[:1]
                noise = ids[1:]
                advice = f"同主题重复 {len(ids)} 条，建议只留最新 1 条，其余视为噪音。"
                signal_ids.extend(keep)
                noise_ids.extend(noise)
            elif category == "drawdown" and level == "critical" and not kill_on:
                kind = "stale"
                keep = []
                noise = ids
                advice = "急停已解除，这些回撤急停记录已过期，可一键关闭。"
                noise_ids.extend(noise)
            elif category == KILL_CATEGORY and not kill_on:
                kind = "stale"
                keep = []
                noise = ids
                advice = "急停当前为关，残留急停告警可关闭。"
                noise_ids.extend(noise)
            elif level in {"critical", "high"}:
                kind = "actionable"
                keep = ids
                noise = []
                advice = "高等级告警，请确认当前风险后再关闭。"
                signal_ids.extend(keep)
            else:
                kind = "info"
                keep = ids[:1]
                noise = ids[1:]
                advice = "一般提示；重复项可清理。"
                signal_ids.extend(keep)
                noise_ids.extend(noise)

            groups.append(
                {
                    "key": bucket["key"],
                    "category": category,
                    "title": title,
                    "level": level,
                    "count": len(ids),
                    "kind": kind,
                    "keep_ids": keep,
                    "noise_ids": noise,
                    "all_ids": ids,
                    "latest_at": latest.get("created_at"),
                    "detail_sample": latest.get("detail"),
                    "advice": advice,
                }
            )

        groups.sort(key=lambda item: (-_level_rank(item["level"]), -int(item["count"])))
        open_count = len(rows)
        noise_count = len(dict.fromkeys(noise_ids))
        state_count = len(dict.fromkeys(state_ids))
        signal_count = len(dict.fromkeys(signal_ids))
        if open_count == 0:
            verdict = "当前无开放告警。"
        elif noise_count and signal_count:
            verdict = (
                f"开放 {open_count} 条：有效关注约 {signal_count} 条，"
                f"重复/过期噪音 {noise_count} 条"
                + (f"，状态提示 {state_count} 条" if state_count else "")
                + "。建议先清噪音，再处理高等级。"
            )
        elif noise_count:
            verdict = f"开放 {open_count} 条，主要为重复或过期噪音（{noise_count}），可一键清理。"
        else:
            verdict = f"开放 {open_count} 条，暂无明显重复噪音；请按级别逐条确认。"

        return {
            "open_count": open_count,
            "signal_count": signal_count,
            "noise_count": noise_count,
            "state_count": state_count,
            "kill_engaged": kill_on,
            "verdict": verdict,
            "noise_ids": list(dict.fromkeys(noise_ids)),
            "groups": groups,
            "analyzed_at": _now(),
        }

    def _fanout(self, row: dict[str, Any]) -> None:
        from asqt.adapters.feishu_alert import post_feishu_alert

        remote_meta = post_feishu_alert(row)
        payload = dict(row)
        payload["remote"] = remote_meta
        line = json.dumps(payload, ensure_ascii=False)
        local = self.settings.logs_dir / "alerts.jsonl"
        remote = self.settings.logs_dir / "alerts_remote.jsonl"
        local.parent.mkdir(parents=True, exist_ok=True)
        with local.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        with remote.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _level_rank(level: str | None) -> int:
    return {"critical": 3, "high": 2, "info": 1}.get(str(level or ""), 0)


def kill_engaged(settings: Settings | None = None) -> bool:
    rows = query_all(
        "SELECT COUNT(*) AS c FROM alert WHERE category = ? AND status = 'open'",
        (KILL_CATEGORY,),
        settings=settings,
    )
    return int(rows[0]["c"] if rows else 0) > 0


def set_kill_switch(
    engaged: bool,
    reason: str,
    *,
    actor: str = "operator",
    settings: Settings | None = None,
) -> dict[str, Any]:
    if not (reason or "").strip():
        raise ValueError("kill switch change requires a reason")
    settings = settings or get_settings()
    initialize_database(settings)
    before = "on" if kill_engaged(settings) else "off"
    alerts = LocalAlertService(settings)
    if engaged:
        if not kill_engaged(settings):
            alerts.raise_alert("critical", KILL_CATEGORY, "kill switch on", reason)
    else:
        open_rows = query_all(
            """
            SELECT alert_id FROM alert
            WHERE status = 'open' AND category IN (?, 'drawdown')
            """,
            (KILL_CATEGORY,),
            settings=settings,
        )
        for row in open_rows:
            alerts.close_alert(row["alert_id"], reason=reason)
    after = "on" if kill_engaged(settings) else "off"
    execute(
        """
        INSERT INTO operation_audit
            (audit_id, actor, action, target_type, target_id, reason, before_state, after_state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(uuid4()), actor, "kill_switch", "system", "kill_switch", reason, before, after),
        settings=settings,
    )
    return {"engaged": after == "on", "reason": reason, "before": before, "after": after}


def paper_trading_enabled(settings: Settings | None = None) -> bool:
    rows = query_all(
        "SELECT COUNT(*) AS c FROM alert WHERE category = ? AND status = 'open'",
        (PAPER_TRADING_CATEGORY,),
        settings=settings,
    )
    return int(rows[0]["c"] if rows else 0) > 0


def set_paper_trading(
    enabled: bool,
    reason: str = "settings",
    *,
    actor: str = "operator",
    settings: Settings | None = None,
) -> dict[str, Any]:
    if not (reason or "").strip():
        reason = "settings"
    settings = settings or get_settings()
    initialize_database(settings)
    before = "on" if paper_trading_enabled(settings) else "off"
    alerts = LocalAlertService(settings)
    if enabled:
        if not paper_trading_enabled(settings):
            alerts.raise_alert("info", PAPER_TRADING_CATEGORY, "paper trading on", reason)
    else:
        open_rows = query_all(
            "SELECT alert_id FROM alert WHERE category = ? AND status = 'open'",
            (PAPER_TRADING_CATEGORY,),
            settings=settings,
        )
        for row in open_rows:
            alerts.close_alert(row["alert_id"], reason=reason)
    after = "on" if paper_trading_enabled(settings) else "off"
    execute(
        """
        INSERT INTO operation_audit
            (audit_id, actor, action, target_type, target_id, reason, before_state, after_state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(uuid4()), actor, "paper_trading", "system", "paper_trading", reason, before, after),
        settings=settings,
    )
    return {"enabled": after == "on", "reason": reason, "before": before, "after": after}


def maybe_drawdown_halt(
    *,
    peak: float,
    total_asset: float,
    cash: float | None = None,
    market_value: float | None = None,
    initial_cash: float | None = None,
    account_id: str | None = None,
    strategy_id: str | None = None,
    trade_date: str | None = None,
    already_halted: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Evaluate strategy-level flatten vs portfolio-level global kill.

    Strategy drawdown only marks that book for liquidation (no global kill).
    Global kill engages only when combined paper NAV drawdown hits the portfolio line.
    """
    from asqt.alert_format import build_drawdown_payload, encode_alert_detail

    settings = settings or get_settings()
    cfg = paper_account_config(settings)
    strategy_stop = -abs(float(cfg["strategy_drawdown_stop"]))
    portfolio_stop = -abs(float(cfg["portfolio_drawdown_stop"]))
    warn_line = -abs(float(cfg["drawdown_warn"]))

    if peak <= 0:
        book_dd = 0.0
    else:
        book_dd = total_asset / peak - 1.0
    alerts = LocalAlertService(settings)
    common = {
        "dd": book_dd,
        "peak": peak,
        "total_asset": total_asset,
        "cash": cash,
        "market_value": market_value,
        "initial_cash": initial_cash,
        "account_id": account_id,
        "strategy_id": strategy_id,
        "trade_date": trade_date,
    }
    strategy_halt = bool(already_halted) or book_dd <= strategy_stop
    if strategy_halt and not already_halted:
        open_stop = query_all(
            """
            SELECT COUNT(*) AS c FROM alert
            WHERE category = 'drawdown' AND status = 'open' AND level = 'critical'
              AND detail LIKE ?
            """,
            (f"%{strategy_id or account_id or ''}%",),
            settings=settings,
        )
        # One critical strategy-halt alert per book (detail carries strategy_id).
        if int(open_stop[0]["c"] if open_stop else 0) == 0:
            alerts.raise_alert(
                "critical",
                "drawdown",
                "strategy drawdown halt",
                encode_alert_detail(
                    build_drawdown_payload(**common, kind="strategy_stop")
                ),
            )

    portfolio = update_portfolio_drawdown(settings)
    portfolio_halt = False
    if portfolio["dd"] <= portfolio_stop and not kill_engaged(settings):
        set_kill_switch(
            True,
            (
                f"portfolio drawdown stop {portfolio['dd']:.4f} <= {portfolio_stop}"
                f" (nav={portfolio['total_asset']:.2f}, peak={portfolio['peak']:.2f})"
            ),
            actor="risk",
            settings=settings,
        )
        open_port = query_all(
            """
            SELECT COUNT(*) AS c FROM alert
            WHERE category = 'drawdown' AND status = 'open' AND level = 'critical'
              AND title = 'max drawdown stop'
            """,
            settings=settings,
        )
        if int(open_port[0]["c"] if open_port else 0) == 0:
            port_payload = build_drawdown_payload(
                dd=portfolio["dd"],
                peak=portfolio["peak"],
                total_asset=portfolio["total_asset"],
                cash=None,
                market_value=None,
                initial_cash=None,
                account_id="paper:portfolio",
                strategy_id="portfolio",
                trade_date=trade_date,
                kind="stop",
            )
            alerts.raise_alert(
                "critical",
                "drawdown",
                "max drawdown stop",
                encode_alert_detail(port_payload),
            )
        portfolio_halt = True

    if book_dd <= warn_line and not strategy_halt:
        open_warn = query_all(
            """
            SELECT COUNT(*) AS c FROM alert
            WHERE category = 'drawdown' AND status = 'open' AND level = 'high'
              AND title = 'max drawdown warning'
              AND detail LIKE ?
            """,
            (f"%{strategy_id or account_id or ''}%",),
            settings=settings,
        )
        # One warn per book (same scoping as strategy halt), so sibling strategies
        # still notify Feishu when each crosses the line.
        if int(open_warn[0]["c"] if open_warn else 0) == 0:
            alerts.raise_alert(
                "high",
                "drawdown",
                "max drawdown warning",
                encode_alert_detail(build_drawdown_payload(**common, kind="warn")),
            )

    return {
        "halt": portfolio_halt or strategy_halt,
        "strategy_halt": strategy_halt,
        "portfolio_halt": portfolio_halt or kill_engaged(settings),
        "dd": book_dd,
        "portfolio_dd": portfolio["dd"],
        "portfolio_nav": portfolio["total_asset"],
        "portfolio_peak": portfolio["peak"],
    }


def update_portfolio_drawdown(settings: Settings | None = None) -> dict[str, Any]:
    """Sum latest paper book NAVs and track a portfolio peak for global kill."""
    settings = settings or get_settings()
    initialize_database(settings)
    from asqt.research_engine import LocalStrategyService
    from asqt.strategies import STRATEGY_SPECS

    versions = LocalStrategyService(settings)
    total = 0.0
    for sid in STRATEGY_SPECS:
        current = versions.current_version(sid)
        if not current or current.get("status") != "paper":
            continue
        rows = query_all(
            """
            SELECT total_asset FROM account_snapshot
            WHERE account_id = ?
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (f"paper:{sid}",),
            settings=settings,
        )
        if rows:
            total += float(rows[0]["total_asset"] or 0)
    peak_raw = _setting_value(PAPER_PORTFOLIO_PEAK_KEY, "0", settings)
    try:
        peak = float(peak_raw)
    except (TypeError, ValueError):
        peak = 0.0
    peak = max(peak, total, 0.0)
    now = _now()
    execute(
        """
        INSERT INTO runtime_setting (setting_key, setting_value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = excluded.updated_at
        """,
        (PAPER_PORTFOLIO_PEAK_KEY, str(peak), now),
        settings=settings,
    )
    dd = total / peak - 1.0 if peak > 0 else 0.0
    return {"total_asset": round(total, 4), "peak": round(peak, 4), "dd": dd}


def reset_portfolio_peak(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    initialize_database(settings)
    execute(
        """
        INSERT INTO runtime_setting (setting_key, setting_value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = excluded.updated_at
        """,
        (PAPER_PORTFOLIO_PEAK_KEY, "0", _now()),
        settings=settings,
    )


def _setting_value(key: str, default: str, settings: Settings | None = None) -> str:
    initialize_database(settings)
    rows = query_all(
        "SELECT setting_value FROM runtime_setting WHERE setting_key = ?",
        (key,),
        settings=settings,
    )
    if not rows:
        return default
    return str(rows[0]["setting_value"])


def _parse_ratio_setting(raw: str, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value < 0:
        value = abs(value)
    if value > 1:
        value = value / 100.0
    return value


def paper_account_config(settings: Settings | None = None) -> dict[str, Any]:
    cash_raw = _setting_value(PAPER_CASH_KEY, str(DEFAULT_PAPER_CASH), settings)
    rate_raw = _setting_value(PAPER_COMMISSION_KEY, str(DEFAULT_PAPER_COMMISSION), settings)
    try:
        initial_cash = float(cash_raw)
    except (TypeError, ValueError):
        initial_cash = DEFAULT_PAPER_CASH
    try:
        commission_rate = float(rate_raw)
    except (TypeError, ValueError):
        commission_rate = DEFAULT_PAPER_COMMISSION
    portfolio_stop = _parse_ratio_setting(
        _setting_value(PAPER_DD_PORTFOLIO_STOP_KEY, str(DEFAULT_PORTFOLIO_DRAWDOWN_STOP), settings),
        DEFAULT_PORTFOLIO_DRAWDOWN_STOP,
    )
    strategy_stop = _parse_ratio_setting(
        _setting_value(PAPER_DD_STRATEGY_STOP_KEY, str(DEFAULT_STRATEGY_DRAWDOWN_STOP), settings),
        DEFAULT_STRATEGY_DRAWDOWN_STOP,
    )
    warn = _parse_ratio_setting(
        _setting_value(PAPER_DD_WARN_KEY, str(DEFAULT_DRAWDOWN_WARN), settings),
        DEFAULT_DRAWDOWN_WARN,
    )
    return {
        "initial_cash": initial_cash,
        "commission_rate": commission_rate,
        "commission_per_myriad": round(commission_rate * 10_000, 6),
        "portfolio_drawdown_stop": portfolio_stop,
        "strategy_drawdown_stop": strategy_stop,
        "drawdown_warn": warn,
        "portfolio_drawdown_stop_pct": round(portfolio_stop * 100, 4),
        "strategy_drawdown_stop_pct": round(strategy_stop * 100, 4),
        "drawdown_warn_pct": round(warn * 100, 4),
    }


def set_paper_account_config(
    *,
    initial_cash: float,
    commission_per_myriad: float,
    portfolio_drawdown_stop_pct: float | None = None,
    strategy_drawdown_stop_pct: float | None = None,
    drawdown_warn_pct: float | None = None,
    actor: str = "operator",
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    initialize_database(settings)
    cash = float(initial_cash)
    myriad = float(commission_per_myriad)
    if cash < 10_000 or cash > 100_000_000:
        raise ValueError("初始资金需在 10,000 到 100,000,000 之间")
    if myriad < 0 or myriad > 50:
        raise ValueError("佣金万分之需在 0 到 50 之间")
    rate = round(myriad / 10_000, 10)

    def _pct_to_ratio(name: str, pct: float) -> float:
        value = float(pct)
        if value < 0 or value > 80:
            raise ValueError(f"{name}需在 0 到 80 之间")
        return round(value / 100.0, 10)

    before = paper_account_config(settings)
    port_pct = (
        before["portfolio_drawdown_stop_pct"]
        if portfolio_drawdown_stop_pct is None
        else portfolio_drawdown_stop_pct
    )
    strat_pct = (
        before["strategy_drawdown_stop_pct"]
        if strategy_drawdown_stop_pct is None
        else strategy_drawdown_stop_pct
    )
    warn_pct = before["drawdown_warn_pct"] if drawdown_warn_pct is None else drawdown_warn_pct
    port_ratio = _pct_to_ratio("组合回撤急停", port_pct)
    strat_ratio = _pct_to_ratio("单策略回撤平仓", strat_pct)
    warn_ratio = _pct_to_ratio("回撤预警", warn_pct)
    if warn_ratio > strat_ratio:
        raise ValueError("回撤预警不能深于单策略回撤平仓线")
    if strat_ratio > port_ratio:
        # allow equal; only reject if strategy stop is looser than portfolio? 
        # Actually strategy can equal portfolio. If strategy > portfolio (e.g. 15% vs 12%),
        # strategy never halts before portfolio — OK. If strategy < portfolio, strategy flattens first — OK.
        pass
    now = _now()
    pairs = (
        (PAPER_CASH_KEY, str(cash)),
        (PAPER_COMMISSION_KEY, str(rate)),
        (PAPER_DD_PORTFOLIO_STOP_KEY, str(port_ratio)),
        (PAPER_DD_STRATEGY_STOP_KEY, str(strat_ratio)),
        (PAPER_DD_WARN_KEY, str(warn_ratio)),
    )
    for key, value in pairs:
        execute(
            """
            INSERT INTO runtime_setting (setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = excluded.updated_at
            """,
            (key, value, now),
            settings=settings,
        )
    after = paper_account_config(settings)
    execute(
        """
        INSERT INTO operation_audit
            (audit_id, actor, action, target_type, target_id, reason, before_state, after_state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            actor,
            "paper_config",
            "system",
            "paper_config",
            "settings",
            json.dumps(before, ensure_ascii=False),
            json.dumps(after, ensure_ascii=False),
        ),
        settings=settings,
    )
    return after


# Keep old constant names resolving via config for call sites that still import them.
def drawdown_stop_line(settings: Settings | None = None) -> float:
    return -abs(float(paper_account_config(settings)["portfolio_drawdown_stop"]))


def drawdown_warn_line(settings: Settings | None = None) -> float:
    return -abs(float(paper_account_config(settings)["drawdown_warn"]))


FLATTEN_INCOMPLETE_TITLE = "flatten incomplete"


def maybe_flatten_incomplete_alert(
    *,
    strategy_id: str,
    account_id: str,
    trade_date: str,
    positions: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Raise/refresh one open alert while a halted book still holds unsellable lots."""
    settings = settings or get_settings()
    open_qty = sum(int((item or {}).get("qty") or 0) for item in (positions or {}).values())
    if open_qty <= 0:
        return None
    symbols = sorted(
        f"{symbol}:{int(item.get('qty') or 0)}"
        for symbol, item in (positions or {}).items()
        if int((item or {}).get("qty") or 0) > 0
    )
    detail = json.dumps(
        {
            "schema": "asqt.alert.v1",
            "kind": "flatten_incomplete",
            "summary": f"{strategy_id} 未完成平仓，仍持有 {open_qty} 股",
            "strategy_id": strategy_id,
            "account_id": account_id,
            "trade_date": trade_date,
            "open_qty": open_qty,
            "positions": symbols,
            "action": "跌停/停牌等导致当日无法卖出；下一交易日继续强平。",
        },
        ensure_ascii=False,
    )
    existing = query_all(
        """
        SELECT alert_id FROM alert
        WHERE status = 'open' AND category = 'drawdown' AND title = ?
          AND detail LIKE ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (FLATTEN_INCOMPLETE_TITLE, f"%{strategy_id}%"),
        settings=settings,
    )
    alerts = LocalAlertService(settings)
    if existing:
        execute(
            "UPDATE alert SET detail = ?, updated_at = ? WHERE alert_id = ?",
            (detail, _now(), existing[0]["alert_id"]),
            settings=settings,
        )
        rows = query_all(
            "SELECT * FROM alert WHERE alert_id = ?",
            (existing[0]["alert_id"],),
            settings=settings,
        )
        return rows[0] if rows else None
    return alerts.raise_alert("high", "drawdown", FLATTEN_INCOMPLETE_TITLE, detail)


def close_flatten_incomplete_alerts(
    *,
    strategy_id: str,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    rows = query_all(
        """
        SELECT alert_id FROM alert
        WHERE status = 'open' AND category = 'drawdown' AND title = ?
          AND detail LIKE ?
        """,
        (FLATTEN_INCOMPLETE_TITLE, f"%{strategy_id}%"),
        settings=settings,
    )
    alerts = LocalAlertService(settings)
    for row in rows:
        alerts.close_alert(row["alert_id"], reason=f"{strategy_id} flatten complete")
    return len(rows)


STRATEGY_HALT_TITLE = "strategy drawdown halt"


def close_strategy_halt_alerts(
    *,
    strategy_id: str,
    reason: str,
    settings: Settings | None = None,
) -> int:
    """Close open strategy-halt / flatten-incomplete alerts for one book."""
    settings = settings or get_settings()
    rows = query_all(
        """
        SELECT alert_id FROM alert
        WHERE status = 'open' AND category = 'drawdown'
          AND title IN (?, ?)
          AND detail LIKE ?
        """,
        (STRATEGY_HALT_TITLE, FLATTEN_INCOMPLETE_TITLE, f"%{strategy_id}%"),
        settings=settings,
    )
    alerts = LocalAlertService(settings)
    for row in rows:
        alerts.close_alert(row["alert_id"], reason=reason)
    return len(rows)

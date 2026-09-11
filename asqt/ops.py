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
DRAWDOWN_STOP = -0.12
DRAWDOWN_WARN = -0.08


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

    def list_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        return query_all(
            "SELECT * FROM alert ORDER BY created_at DESC LIMIT ?",
            (limit,),
            settings=self.settings,
        )

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
            "SELECT alert_id FROM alert WHERE category = ? AND status = 'open'",
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
    settings: Settings | None = None,
) -> dict[str, Any]:
    if peak <= 0:
        return {"halt": False, "dd": 0.0}
    dd = total_asset / peak - 1.0
    alerts = LocalAlertService(settings)
    if dd <= DRAWDOWN_STOP and not kill_engaged(settings):
        set_kill_switch(
            True,
            f"max drawdown stop {dd:.4f} <= {DRAWDOWN_STOP}",
            actor="risk",
            settings=settings,
        )
        alerts.raise_alert("critical", "drawdown", "max drawdown stop", f"dd={dd:.6f}")
        return {"halt": True, "dd": dd}
    if dd <= DRAWDOWN_WARN:
        open_warn = query_all(
            "SELECT COUNT(*) AS c FROM alert WHERE category = 'drawdown' AND status = 'open' AND level = 'high'",
            settings=settings,
        )
        if int(open_warn[0]["c"] if open_warn else 0) == 0:
            alerts.raise_alert("high", "drawdown", "max drawdown warning", f"dd={dd:.6f}")
    return {"halt": False, "dd": dd}


PAPER_CASH_KEY = "paper.initial_cash"
PAPER_COMMISSION_KEY = "paper.commission_rate"
DEFAULT_PAPER_CASH = 1_000_000.0
DEFAULT_PAPER_COMMISSION = 0.00025


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
    return {
        "initial_cash": initial_cash,
        "commission_rate": commission_rate,
        "commission_per_myriad": round(commission_rate * 10_000, 6),
    }


def set_paper_account_config(
    *,
    initial_cash: float,
    commission_per_myriad: float,
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
    before = paper_account_config(settings)
    now = _now()
    for key, value in ((PAPER_CASH_KEY, str(cash)), (PAPER_COMMISSION_KEY, str(rate))):
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

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
    settings: Settings | None = None,
) -> dict[str, Any]:
    from asqt.alert_format import build_drawdown_payload, encode_alert_detail

    if peak <= 0:
        return {"halt": False, "dd": 0.0}
    dd = total_asset / peak - 1.0
    alerts = LocalAlertService(settings)
    common = {
        "dd": dd,
        "peak": peak,
        "total_asset": total_asset,
        "cash": cash,
        "market_value": market_value,
        "initial_cash": initial_cash,
        "account_id": account_id,
        "strategy_id": strategy_id,
        "trade_date": trade_date,
    }
    if dd <= DRAWDOWN_STOP and not kill_engaged(settings):
        set_kill_switch(
            True,
            f"max drawdown stop {dd:.4f} <= {DRAWDOWN_STOP}",
            actor="risk",
            settings=settings,
        )
        open_stop = query_all(
            """
            SELECT COUNT(*) AS c FROM alert
            WHERE category = 'drawdown' AND status = 'open' AND level = 'critical'
            """,
            settings=settings,
        )
        if int(open_stop[0]["c"] if open_stop else 0) == 0:
            alerts.raise_alert(
                "critical",
                "drawdown",
                "max drawdown stop",
                encode_alert_detail(build_drawdown_payload(**common, kind="stop")),
            )
        return {"halt": True, "dd": dd}
    if dd <= DRAWDOWN_WARN:
        open_warn = query_all(
            "SELECT COUNT(*) AS c FROM alert WHERE category = 'drawdown' AND status = 'open' AND level = 'high'",
            settings=settings,
        )
        if int(open_warn[0]["c"] if open_warn else 0) == 0:
            alerts.raise_alert(
                "high",
                "drawdown",
                "max drawdown warning",
                encode_alert_detail(build_drawdown_payload(**common, kind="warn")),
            )
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

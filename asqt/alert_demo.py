"""End-to-end Feishu alert rehearsal. Uses an isolated SQLite; does not touch the live paper book."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from asqt.adapters.feishu_alert import DEFAULT_FEISHU_WEBHOOK, feishu_webhook_url
from asqt.config import Settings, ensure_runtime_dirs
from asqt.db import initialize_database, query_all
from asqt.ops import (
    LocalAlertService,
    kill_engaged,
    maybe_drawdown_halt,
    set_kill_switch,
    set_paper_trading,
)


def _settings(root: Path) -> Settings:
    data = root / "data"
    return Settings(
        project_root=root,
        data_dir=data,
        database_path=data / "asqt.sqlite3",
        parquet_dir=data / "parquet",
        raw_dir=data / "raw_data",
        standard_dir=data / "standard_data",
        qlib_dir=data / "qlib_data",
        experiment_dir=data / "experiment",
        logs_dir=data / "logs",
        frontend_dir=root / "frontend",
    )


def run_alert_demo(
    *,
    root: Path | None = None,
    live: bool = True,
    pause_s: float = 1.1,
) -> dict[str, Any]:
    root = Path(root or Path.cwd() / "data" / "alert_demo" / uuid4().hex[:10])
    settings = ensure_runtime_dirs(_settings(root))
    initialize_database(settings)
    previous = os.environ.get("ASQT_FEISHU_WEBHOOK")
    os.environ["ASQT_FEISHU_WEBHOOK"] = DEFAULT_FEISHU_WEBHOOK if live else ""
    alerts = LocalAlertService(settings)
    steps: list[dict[str, Any]] = []
    try:
        steps.append(
            _step(
                "1/8 开场",
                alerts.raise_alert(
                    "high",
                    "ops",
                    "演练开始：完整告警链路",
                    "隔离库演练，不改生产账本、不加真实急停。随后按质检 → 日终模拟 → 回撤预警 → 回撤停机/急停 → 打开模拟(info不进群) → 收尾。",
                ),
            )
        )
        _pause(pause_s)
        steps.append(
            _step(
                "2/8 质检阻断",
                alerts.raise_alert(
                    "high",
                    "quality",
                    "质量闸门 block，禁止新订单",
                    "模拟：开放 block（如缺日 K）。Paper / mock 新单都会 rejected。trade_allowed=false。",
                ),
            )
        )
        _pause(pause_s)
        steps.append(
            _step(
                "3/8 日终模拟失败",
                alerts.raise_alert(
                    "high",
                    "paper_daily",
                    "演练·日终模拟失败",
                    "模拟：当日 K 已同步，但 paper-daily 抛错。生产路径见 after_market_ready。",
                ),
            )
        )
        _pause(pause_s)
        warn = maybe_drawdown_halt(peak=100_000, total_asset=91_500, settings=settings)
        steps.append(_step("4/8 回撤预警 −8%", {"drawdown": warn, "alerts": _last_alert(settings)}))
        _pause(pause_s)
        halt = maybe_drawdown_halt(
            peak=100_000,
            total_asset=87_800,
            cash=10_000,
            market_value=77_800,
            initial_cash=100_000,
            account_id="paper:etf_ma_rotate",
            strategy_id="etf_ma_rotate",
            trade_date="2024-01-02",
            settings=settings,
        )
        steps.append(
            _step(
                "5/8 单策略回撤平仓 −12%（不清全局急停）",
                {
                    "drawdown": halt,
                    "strategy_halt": halt.get("strategy_halt"),
                    "kill_engaged": kill_engaged(settings),
                    "alerts": _open_alerts(settings),
                },
            )
        )
        _pause(pause_s)
        # Demo the portfolio-level kill path separately (total-fund stop).
        set_kill_switch(True, "演练组合回撤急停", actor="demo", settings=settings)
        alerts.raise_alert(
            "critical",
            "drawdown",
            "max drawdown stop",
            "演练：组合资金回撤达线，全局急停。",
        )
        steps.append(
            _step(
                "5b/8 组合回撤急停（全局）",
                {"kill_engaged": kill_engaged(settings), "alerts": _open_alerts(settings)},
            )
        )
        _pause(pause_s)
        info = set_paper_trading(True, "演练打开模拟开关", settings=settings)
        info_row = _last_alert(settings)
        steps.append(
            _step(
                "6/8 打开模拟（info，不进飞书）",
                {"paper_trading": info, "alert": info_row, "feishu_expected": False},
            )
        )
        _pause(pause_s)
        cleared = set_kill_switch(False, "演练结束解除急停", actor="demo", settings=settings)
        _pause(pause_s)
        steps.append(_step("7/8 演练库解除急停", cleared))
        steps.append(
            _step(
                "8/8 收尾",
                alerts.raise_alert(
                    "high",
                    "ops",
                    "演练结束",
                    "飞书应收到：开场、质检、日终失败、回撤预警、急停、回撤停机、收尾。打开模拟为 info，只在本地 jsonl。生产库未改。",
                ),
            )
        )
    finally:
        if previous is None:
            os.environ.pop("ASQT_FEISHU_WEBHOOK", None)
        else:
            os.environ["ASQT_FEISHU_WEBHOOK"] = previous
    remote = settings.logs_dir / "alerts_remote.jsonl"
    pushed = 0
    skipped = 0
    failed = 0
    if remote.exists():
        for line in remote.read_text(encoding="utf-8").splitlines():
            meta = json.loads(line).get("remote") or {}
            if meta.get("skipped"):
                skipped += 1
            elif meta.get("ok"):
                pushed += 1
            else:
                failed += 1
    return {
        "ok": failed == 0,
        "live": live,
        "webhook_configured": live,
        "root": str(root),
        "kill_engaged": kill_engaged(settings),
        "pushed": pushed,
        "skipped": skipped,
        "failed": failed,
        "steps": [{"name": item["name"], "ok": True} for item in steps],
        "alert_count": query_all("SELECT COUNT(*) AS c FROM alert", settings=settings)[0]["c"],
    }


def _step(name: str, payload: Any) -> dict[str, Any]:
    return {"name": name, "payload": payload}


def _pause(seconds: float) -> None:
    if seconds and seconds > 0:
        time.sleep(seconds)


def _last_alert(settings: Settings) -> dict[str, Any] | None:
    rows = query_all("SELECT * FROM alert ORDER BY created_at DESC LIMIT 1", settings=settings)
    return rows[0] if rows else None


def _open_alerts(settings: Settings) -> list[dict[str, Any]]:
    return query_all(
        "SELECT level, category, title, status FROM alert WHERE status = 'open' ORDER BY created_at",
        settings=settings,
    )

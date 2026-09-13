"""Unified risk / admit / order gate — single exit with stable reason codes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from asqt.config import Settings, get_settings
from asqt.db import query_all
from asqt.ops import kill_engaged, quality_gate
from asqt.stale import evaluate_market_staleness, stale_severity
from asqt.storage import read_market_daily

GateDecision = Literal["approve", "reject", "review"]
GatePurpose = Literal["orders", "admit"]

# Stable reason codes (API / UI / alerts). Do not rename lightly.
REASON_QUALITY_BLOCK = "quality_block"
REASON_KILL_SWITCH = "kill_switch"
REASON_STALE_DATA = "stale_data"
REASON_CALENDAR_CLOSED = "calendar_closed"
REASON_NOT_PAPER = "not_paper"
REASON_STRATEGY_HALT = "strategy_halt"
REASON_OVERRIDE_CONFLICT = "override_conflict"
REASON_MISSING_EXPERIMENT = "missing_experiment"
REASON_EXPERIMENT_NOT_OK = "experiment_not_ok"
REASON_MISSING_VERSION_PINS = "missing_version_pins"
REASON_NO_VERSION = "no_version"
REASON_UNKNOWN_STRATEGY = "unknown_strategy"
REASON_OK = "ok"

ORDERABLE = frozenset({"paper"})


@dataclass
class GateResult:
    decision: GateDecision
    reason_code: str
    message: str
    flatten_only: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.decision == "approve"

    @property
    def rejected(self) -> bool:
        return self.decision == "reject"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["approved"] = self.approved
        payload["rejected"] = self.rejected
        return payload


def _reject(code: str, message: str, **details: Any) -> GateResult:
    return GateResult(decision="reject", reason_code=code, message=message, details=details)


def _approve(message: str = "ok", *, flatten_only: bool = False, reason_code: str = REASON_OK, **details: Any) -> GateResult:
    return GateResult(
        decision="approve",
        reason_code=reason_code,
        message=message,
        flatten_only=flatten_only,
        details=details,
    )


def _review(code: str, message: str, **details: Any) -> GateResult:
    return GateResult(decision="review", reason_code=code, message=message, details=details)


def detect_override_conflicts(strategy_id: str, *, settings: Settings | None = None) -> str | None:
    """Return reason_code if paper overrides are inconsistent; else None."""
    from asqt.overrides import list_overrides

    rows = list_overrides(strategy_id=strategy_id, settings=settings)
    for row in rows:
        action = str(row.get("action") or "")
        weight = row.get("weight")
        if action in {"force_in", "cap"} and weight is not None:
            try:
                w = float(weight)
            except (TypeError, ValueError):
                return REASON_OVERRIDE_CONFLICT
            if w > 1.0 + 1e-12 or w < 0:
                return REASON_OVERRIDE_CONFLICT
        if action == "force_in" and (weight is None or float(weight) <= 0):
            return REASON_OVERRIDE_CONFLICT
    return None


def _lifecycle_status(strategy_id: str, settings: Settings) -> str | None:
    rows = query_all(
        """
        SELECT status FROM strategy_version
        WHERE strategy_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (strategy_id,),
        settings=settings,
    )
    if not rows:
        return None
    return str(rows[0].get("status") or "")


def _calendar_open(trade_date: str, settings: Settings) -> bool:
    rows = query_all(
        "SELECT is_open FROM trade_calendar WHERE trade_date = ? AND market = 'CN'",
        (trade_date,),
        settings=settings,
    )
    if not rows:
        return True
    return int(rows[0]["is_open"] or 0) == 1


def _stale_blocked(trade_date: str, settings: Settings) -> bool:
    if stale_severity() != "block":
        return False
    rows = read_market_daily(end=trade_date, settings=settings)
    calendar = query_all(
        "SELECT * FROM trade_calendar WHERE market = 'CN' AND trade_date <= ?",
        (trade_date,),
        settings=settings,
    )
    report = evaluate_market_staleness(records=rows, calendar=calendar, asof=trade_date)
    return report.blocked


def evaluate(
    *,
    purpose: GatePurpose = "orders",
    strategy_id: str | None = None,
    trade_date: str | None = None,
    settings: Settings | None = None,
    book_halted: bool = False,
    require_experiment: bool = False,
    check_overrides: bool = True,
) -> GateResult:
    """Single gate for paper orders and lifecycle admit/resume.

    ``orders``: quality / stale / calendar / lifecycle; kill or book halt → approve+flatten_only.
    ``admit``: quality / kill / experiment pins; kill always rejects admit.
    """
    settings = settings or get_settings()
    sid = (strategy_id or "").strip() or None

    gate = quality_gate(settings)
    if not gate.get("trade_allowed", True):
        return _reject(REASON_QUALITY_BLOCK, "开放质检 block，禁止准入或下单", block_count=gate.get("block_count"))

    if purpose == "admit":
        if kill_engaged(settings):
            return _reject(REASON_KILL_SWITCH, "急停已打开，不能准入或恢复模拟")
        if not sid:
            return _reject(REASON_UNKNOWN_STRATEGY, "strategy_id is required for admit")
        status = _lifecycle_status(sid, settings)
        if status is None:
            return _reject(REASON_NO_VERSION, f"{sid} has no version")
        if require_experiment:
            from asqt.reporting import latest_summary_path

            path = latest_summary_path(sid, kind="backtest", settings=settings)
            if path is None or not path.exists():
                return _reject(REASON_MISSING_EXPERIMENT, "缺少最近一次回测报告")
            import json

            report = json.loads(path.read_text(encoding="utf-8"))
            if not report.get("ok"):
                return _reject(REASON_EXPERIMENT_NOT_OK, "最近一次回测未通过")
            if not report.get("parameter_set_id") or not report.get("data_version"):
                return _reject(REASON_MISSING_VERSION_PINS, "回测报告缺少参数组或数据版本钉扎")
        if check_overrides:
            conflict = detect_override_conflicts(sid, settings=settings)
            if conflict:
                return _review(conflict, "模拟覆盖参数冲突，需人工确认", strategy_id=sid)
        return _approve("admit allowed", strategy_id=sid, lifecycle=status)

    # purpose == orders
    if trade_date and not _calendar_open(trade_date, settings):
        return _reject(REASON_CALENDAR_CLOSED, f"{trade_date} 非开市日", trade_date=trade_date)
    if trade_date and _stale_blocked(trade_date, settings):
        return _reject(REASON_STALE_DATA, "行情过旧，拒绝用过期价撮合", trade_date=trade_date)

    if sid:
        status = _lifecycle_status(sid, settings)
        global_kill = kill_engaged(settings)
        if global_kill or book_halted:
            code = REASON_KILL_SWITCH if global_kill else REASON_STRATEGY_HALT
            return _approve(
                "flatten only",
                flatten_only=True,
                reason_code=code,
                strategy_id=sid,
                lifecycle=status,
            )
        if status not in ORDERABLE:
            return _reject(
                REASON_NOT_PAPER,
                f"{sid} status={status or 'none'} cannot generate target positions",
                strategy_id=sid,
                lifecycle=status,
            )
        if check_overrides:
            conflict = detect_override_conflicts(sid, settings=settings)
            if conflict:
                return _reject(conflict, "模拟覆盖参数非法（权重越界）", strategy_id=sid)

    return _approve("orders allowed", strategy_id=sid, trade_date=trade_date)

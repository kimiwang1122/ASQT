"""Shared alert copy for console list/expand and Feishu push."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from asqt.strategies import STRATEGY_LABEL

TITLE_LABEL = {
    "max drawdown stop": "组合回撤触发急停",
    "strategy drawdown halt": "单策略回撤平仓",
    "flatten incomplete": "未完成平仓",
    "max drawdown warning": "回撤预警",
    "kill switch on": "急停已打开",
    "paper trading on": "模拟交易已开启",
    "日终模拟失败": "日终模拟失败",
    "跨源对账完成": "跨源对账完成",
    "跨源对账待复核": "跨源对账待复核",
    "跨源对账失败": "跨源对账失败",
    "财务对账通过": "财务对账通过",
    "财务对账跳过": "财务对账跳过",
    "财务对账不一致": "财务对账不一致",
    "财务对账失败": "财务对账失败",
}

CATEGORY_LABEL = {
    "kill_switch": "急停",
    "drawdown": "回撤",
    "paper_trading": "模拟开关",
    "paper_daily": "日终模拟",
    "ops": "运维",
    "quality": "质量",
    "reconcile": "跨源对账",
    "cash_reconcile": "财务对账",
}

LEVEL_LABEL = {
    "info": "提示",
    "high": "重要",
    "critical": "严重",
}


def _drawdown_thresholds() -> tuple[float, float, float]:
    from asqt.ops import paper_account_config

    cfg = paper_account_config()
    return (
        -abs(float(cfg["portfolio_drawdown_stop"])),
        -abs(float(cfg["strategy_drawdown_stop"])),
        -abs(float(cfg["drawdown_warn"])),
    )


def public_report_ref(value: Any) -> str | None:
    """Expose report identity without local absolute paths (safe for Feishu / group chat)."""
    text = str(value or "").strip()
    if not text:
        return None
    name = os.path.basename(text.rstrip("/"))
    return name or None


def money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:,.2f}"


def pct(value: Any, *, digits: int = 2, signed: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    text = f"{abs(number) * 100:.{digits}f}%"
    if signed:
        return f"-{text}" if number < 0 else text
    return text


def build_drawdown_payload(
    *,
    dd: float,
    peak: float,
    total_asset: float,
    cash: float | None = None,
    market_value: float | None = None,
    initial_cash: float | None = None,
    account_id: str | None = None,
    strategy_id: str | None = None,
    trade_date: str | None = None,
    kind: str = "stop",
) -> dict[str, Any]:
    portfolio_stop, strategy_stop, drawdown_warn = _drawdown_thresholds()
    if kind == "strategy_stop":
        threshold = strategy_stop
        action = "已触发单策略平仓：清空持仓、禁止买入；未达组合急停线时其他账本继续。"
        summary = f"回撤 {pct(dd)} 触发单策略平仓"
        kind_key = "drawdown_strategy_stop"
    elif kind == "stop":
        threshold = portfolio_stop
        action = "已触发组合急停：全部子账户停止新开仓并清仓。"
        summary = f"回撤 {pct(dd)} 触发组合急停"
        kind_key = "drawdown_stop"
    else:
        threshold = drawdown_warn
        action = f"未达组合急停线 {pct(portfolio_stop)}，请关注回撤与仓位。"
        summary = f"回撤 {pct(dd)} 触及预警"
        kind_key = "drawdown_warn"
    return {
        "schema": "asqt.alert.v1",
        "kind": kind_key,
        "summary": summary,
        "dd": round(float(dd), 8),
        "dd_pct": round(abs(float(dd)) * 100, 4),
        "peak_asset": round(float(peak), 4),
        "total_asset": round(float(total_asset), 4),
        "cash": None if cash is None else round(float(cash), 4),
        "market_value": None if market_value is None else round(float(market_value), 4),
        "initial_cash": None if initial_cash is None else round(float(initial_cash), 4),
        "pnl_vs_peak": round(float(total_asset) - float(peak), 4),
        "pnl_vs_initial": (
            None
            if initial_cash is None
            else round(float(total_asset) - float(initial_cash), 4)
        ),
        "threshold": float(threshold),
        "threshold_pct": abs(float(threshold)) * 100,
        "account_id": account_id,
        "strategy_id": strategy_id,
        "trade_date": trade_date,
        "action": action,
    }


def encode_alert_detail(payload: dict[str, Any] | str | None) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False)


def parse_alert_detail(detail: Any) -> dict[str, Any]:
    raw = "" if detail is None else str(detail).strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    out: dict[str, Any] = {"raw": raw}
    dd_match = re.search(r"dd\s*=\s*(-?[0-9.]+)", raw, re.I)
    if dd_match:
        dd = float(dd_match.group(1))
        out["dd"] = dd
        out["dd_pct"] = abs(dd) * 100
        out["summary"] = f"回撤 {pct(dd)}"
    # Prefer Chinese segments after semicolons for legacy enriched strings.
    parts = [part.strip() for part in re.split(r"[;；]", raw) if part.strip()]
    readable = [part for part in parts if not re.match(r"^dd\s*=", part, re.I)]
    if readable:
        out["legacy_text"] = "；".join(readable)
        if not out.get("summary"):
            out["summary"] = readable[0]
    return out


def title_label(title: str | None) -> str:
    text = str(title or "").strip()
    return TITLE_LABEL.get(text, text or "告警")


def category_label(category: str | None) -> str:
    text = str(category or "").strip()
    return CATEGORY_LABEL.get(text, text or "-")


def level_label(level: str | None) -> str:
    text = str(level or "").strip()
    return LEVEL_LABEL.get(text, text or "-")


def strategy_label(strategy_id: str | None) -> str:
    text = str(strategy_id or "").strip()
    if not text:
        return "-"
    return STRATEGY_LABEL.get(text, text)


def format_alert_summary(row: dict[str, Any]) -> str:
    payload = parse_alert_detail(row.get("detail"))
    if payload.get("summary"):
        return str(payload["summary"])
    if payload.get("legacy_text"):
        return str(payload["legacy_text"])
    title = title_label(row.get("title"))
    if payload.get("dd") is not None:
        kind = str(payload.get("kind") or "")
        if kind.endswith("stop") or row.get("level") == "critical" or "stop" in str(row.get("title") or ""):
            return f"回撤 {pct(payload['dd'])} 触发急停"
        if kind.endswith("warn") or "warning" in str(row.get("title") or ""):
            return f"回撤 {pct(payload['dd'])} 触及预警"
        return f"回撤 {pct(payload['dd'])}"
    raw = str(row.get("detail") or "").strip()
    if re.match(r"^dd\s*=", raw, re.I):
        return title
    return raw or title


def format_alert_full(row: dict[str, Any]) -> str:
    payload = parse_alert_detail(row.get("detail"))
    category = str(row.get("category") or "")
    title = title_label(row.get("title"))
    level = level_label(row.get("level"))
    lines = [
        f"级别：{level}",
        f"类别：{category_label(category)}",
        f"事件：{title}",
    ]
    if payload.get("kind", "").startswith("drawdown") or category == "drawdown" or "drawdown" in str(
        row.get("title") or ""
    ):
        lines.extend(_drawdown_lines(payload, row))
    elif category == "kill_switch" or "kill switch" in str(row.get("title") or ""):
        reason = payload.get("legacy_text") or row.get("detail") or "操作员或风控触发"
        if isinstance(reason, str) and re.match(r"^dd\s*=", reason, re.I):
            reason = "操作员或风控触发"
        lines.extend(
            [
                f"原因：{reason}",
                "影响：解除前不能准入/恢复模拟，也不能继续有效成交。",
            ]
        )
    elif category == "paper_trading":
        reason = payload.get("legacy_text") or row.get("detail") or "settings"
        if reason == "settings":
            reason = "设置页开启模拟交易"
        lines.extend(
            [
                f"原因：{reason}",
                "说明：这是状态提示，不是故障。",
            ]
        )
    elif category == "reconcile" or str(payload.get("kind") or "") == "cross_source_reconcile":
        lines.extend(_reconcile_lines(payload))
    elif category == "cash_reconcile" or str(payload.get("kind") or "") == "cash_reconcile":
        lines.extend(_cash_reconcile_lines(payload))
    else:
        detail = payload.get("legacy_text") or row.get("detail")
        if detail and not (isinstance(detail, str) and re.match(r"^dd\s*=", detail, re.I)):
            if payload.get("schema") == "asqt.alert.v1" and payload.get("summary"):
                lines.append(f"摘要：{payload['summary']}")
            else:
                lines.append(f"说明：{detail}")
        else:
            lines.append("说明：无附加字段。")
    return "\n".join(lines)


def _reconcile_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if payload.get("summary"):
        lines.append(f"摘要：{payload['summary']}")
    if payload.get("window"):
        lines.append(f"窗口：{payload['window']}")
    if payload.get("trigger"):
        lines.append(f"触发：{payload['trigger']}")
    if payload.get("symbols") is not None:
        lines.append(f"标的数：{payload['symbols']}")
    if payload.get("match_rate") is not None:
        lines.append(f"匹配率：{float(payload['match_rate']) * 100:.2f}%")
    elif payload.get("match_rate_pct") is not None:
        lines.append(f"匹配率：{payload['match_rate_pct']}%")
    if payload.get("matched_rows") is not None:
        lines.append(
            f"匹配行：{payload.get('matched_rows')}/{payload.get('stored_rows')}"
            f"（对照 {payload.get('peer_rows')}）"
        )
    if payload.get("mismatch_count") is not None:
        lines.append(f"价差差异：{payload['mismatch_count']}")
    if payload.get("adj_baseline_count"):
        lines.append(f"因子基准已对齐：{payload['adj_baseline_count']} 标的")
    if payload.get("silent_inconsistent") is not None:
        lines.append(f"静默跳变异常：{payload['silent_inconsistent']}")
    if payload.get("peer_error_count") is not None:
        lines.append(f"对照源错误：{payload['peer_error_count']}")
    if payload.get("report_path") or payload.get("report"):
        ref = public_report_ref(payload.get("report") or payload.get("report_path"))
        if ref:
            lines.append(f"报告：{ref}")
    if payload.get("action"):
        lines.append(f"处置：{payload['action']}")
    return lines


def _cash_reconcile_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if payload.get("summary"):
        lines.append(f"摘要：{payload['summary']}")
    if payload.get("trigger"):
        lines.append(f"触发：{payload['trigger']}")
    if payload.get("checked") is not None:
        lines.append(
            f"已核对：{payload['checked']} · 不一致 {payload.get('mismatch_count', 0)}"
            f" · 跳过 {payload.get('skipped_count', 0)}"
        )
    portfolio = payload.get("portfolio") or {}
    if portfolio:
        status = "通过" if portfolio.get("ok") else "不一致"
        lines.append(
            f"组合资金：{status} · 本金 {money(portfolio.get('portfolio_cash'))}"
            f" · 已部署 {money(portfolio.get('deployed'))}"
            f" · 净资产 {money(portfolio.get('nav'))}"
        )
        fails = portfolio.get("failed_checks") or []
        if fails:
            lines.append(f"  组合失败项：{'、'.join(str(x) for x in fails)}")
    for item in payload.get("books") or []:
        label = item.get("strategy_label") or strategy_label(item.get("strategy_id"))
        if item.get("skipped"):
            lines.append(f"{label}：尚无账本")
            continue
        status = "通过" if item.get("ok") else "不一致"
        asof = item.get("asof") or "-"
        share = item.get("expected_share")
        share_txt = f" · 应占份额 {money(share)}" if share is not None else ""
        lines.append(
            f"{label}（{asof}）：{status} · 本金 {money(item.get('initial_cash'))}"
            f"{share_txt}"
            f" · 峰值 {money(item.get('peak_asset'))}"
            f" · 现金 {money(item.get('actual_cash'))}"
            f"（差额 {money(item.get('cash_diff'))}）"
            f" · 市值 {money(item.get('market_value'))}"
            f" · 总资产 {money(item.get('end_asset'))}"
        )
        fails = item.get("failed_checks") or []
        if fails:
            lines.append(f"  失败项：{'、'.join(str(x) for x in fails)}")
        qty = item.get("qty_mismatches")
        if qty:
            lines.append(f"  持仓数量不一致：{qty}")
    if payload.get("action"):
        lines.append(f"处置：{payload['action']}")
    return lines


def format_feishu_text(row: dict[str, Any]) -> str:
    level = level_label(row.get("level"))
    category = category_label(row.get("category"))
    title = title_label(row.get("title"))
    # Scrub absolute paths from structured detail before composing Feishu body.
    detail = row.get("detail")
    payload = parse_alert_detail(detail)
    if payload.get("report_path") or payload.get("report"):
        ref = public_report_ref(payload.get("report") or payload.get("report_path"))
        if ref:
            payload = dict(payload)
            payload["report"] = ref
            payload.pop("report_path", None)
            row = dict(row)
            row["detail"] = encode_alert_detail(payload)
    body = format_alert_full(row)
    # Belt-and-suspenders: never leak local absolute paths in Feishu text.
    body = re.sub(r"(?:/[^\s]+)+/(reconcile_[^\s/]+\.json)", r"\1", body)
    body = re.sub(r"/Users/[^\s]+/(reconcile_[^\s/]+\.json)", r"\1", body)
    return "\n".join(
        [
            f"【ASQT告警】{level} · {category}",
            title,
            "",
            body,
        ]
    )


def hydrate_alert_row(row: dict[str, Any], *, settings: Any = None) -> dict[str, Any]:
    """Upgrade legacy drawdown details with account cash / peak fields when possible."""
    if str(row.get("category") or "") != "drawdown" and "drawdown" not in str(row.get("title") or ""):
        return row
    payload = parse_alert_detail(row.get("detail"))
    if payload.get("peak_asset") is not None and payload.get("total_asset") is not None:
        if payload.get("schema") == "asqt.alert.v1":
            return row
    enriched = _enrich_drawdown_from_snapshots(payload, row, settings=settings)
    if not enriched:
        # Still normalize dd-only detail into structured JSON without inventing money fields.
        if payload.get("dd") is None:
            return row
        kind = "stop" if row.get("level") == "critical" or "stop" in str(row.get("title") or "") else "warn"
        portfolio_stop, _strategy_stop, drawdown_warn = _drawdown_thresholds()
        threshold = portfolio_stop if kind == "stop" else drawdown_warn
        minimal = {
            "schema": "asqt.alert.v1",
            "kind": "drawdown_stop" if kind == "stop" else "drawdown_warn",
            "summary": (
                f"回撤 {pct(payload['dd'])} 触发急停"
                if kind == "stop"
                else f"回撤 {pct(payload['dd'])} 触及预警"
            ),
            "dd": float(payload["dd"]),
            "dd_pct": abs(float(payload["dd"])) * 100,
            "threshold": float(threshold),
            "threshold_pct": abs(float(threshold)) * 100,
            "action": (
                "已触发急停，停止新开仓与继续模拟成交。"
                if kind == "stop"
                else f"未达急停线 {pct(portfolio_stop)}，请关注回撤与仓位。"
            ),
        }
        row = dict(row)
        row["detail"] = encode_alert_detail(minimal)
        return row
    row = dict(row)
    row["detail"] = encode_alert_detail(enriched)
    return row


def _enrich_drawdown_from_snapshots(
    payload: dict[str, Any],
    row: dict[str, Any],
    *,
    settings: Any = None,
) -> dict[str, Any] | None:
    dd = payload.get("dd")
    if dd is None:
        return None
    try:
        from asqt.db import query_all
    except Exception:
        return None
    snaps = query_all(
        """
        SELECT account_id, trade_date, cash, market_value, total_asset, position_detail
        FROM account_snapshot
        ORDER BY trade_date DESC
        LIMIT 5000
        """,
        settings=settings,
    )
    best: tuple[float, dict[str, Any]] | None = None
    target = float(dd)
    for snap in snaps:
        try:
            detail = json.loads(snap.get("position_detail") or "{}")
        except json.JSONDecodeError:
            detail = {}
        peak = float(detail.get("peak_asset") or snap.get("total_asset") or 0)
        total = float(snap.get("total_asset") or 0)
        if peak <= 0:
            continue
        snap_dd = total / peak - 1.0
        err = abs(snap_dd - target)
        if best is None or err < best[0]:
            best = (err, {"snap": snap, "detail": detail, "peak": peak, "total": total, "dd": snap_dd})
    if best is None or best[0] > 0.0005:
        return None
    info = best[1]
    snap = info["snap"]
    detail = info["detail"]
    account_id = str(snap.get("account_id") or "")
    strategy_id = account_id.split(":", 1)[-1] if ":" in account_id else account_id
    kind = "stop" if row.get("level") == "critical" or "stop" in str(row.get("title") or "") else "warn"
    initial = detail.get("initial_cash")
    return build_drawdown_payload(
        dd=float(info["dd"]),
        peak=float(info["peak"]),
        total_asset=float(info["total"]),
        cash=None if snap.get("cash") is None else float(snap["cash"]),
        market_value=None if snap.get("market_value") is None else float(snap["market_value"]),
        initial_cash=None if initial is None else float(initial),
        account_id=account_id or None,
        strategy_id=strategy_id or None,
        trade_date=str(snap.get("trade_date") or "") or None,
        kind=kind,
    )


def _drawdown_lines(payload: dict[str, Any], row: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    strategy_id = payload.get("strategy_id")
    account_id = payload.get("account_id")
    trade_date = payload.get("trade_date")
    if strategy_id:
        lines.append(f"策略：{strategy_label(str(strategy_id))}")
    if account_id:
        lines.append(f"账户：{account_id}")
    if trade_date:
        lines.append(f"成交日：{trade_date}")
    if payload.get("dd") is not None:
        portfolio_stop, strategy_stop, drawdown_warn = _drawdown_thresholds()
        threshold = payload.get("threshold")
        kind = str(payload.get("kind") or "")
        if threshold is not None:
            threshold_text = pct(threshold)
        elif kind.endswith("strategy_stop"):
            threshold_text = pct(strategy_stop)
        elif kind.endswith("stop") or row.get("level") == "critical":
            threshold_text = pct(portfolio_stop)
        else:
            threshold_text = pct(drawdown_warn)
        label = (
            "平仓线"
            if kind.endswith("strategy_stop")
            else "急停线"
            if row.get("level") == "critical" or kind.endswith("stop")
            else "预警线"
        )
        lines.append(f"回撤：{pct(payload['dd'])}（相对账户峰值；{label} {threshold_text}）")
    if payload.get("peak_asset") is not None:
        lines.append(f"账户峰值：{money(payload['peak_asset'])}")
    if payload.get("total_asset") is not None:
        lines.append(f"当前总资产：{money(payload['total_asset'])}")
    if payload.get("cash") is not None:
        lines.append(f"现金：{money(payload['cash'])}")
    if payload.get("market_value") is not None:
        lines.append(f"持仓市值：{money(payload['market_value'])}")
    if payload.get("initial_cash") is not None:
        lines.append(f"本金：{money(payload['initial_cash'])}")
    if payload.get("pnl_vs_peak") is not None:
        lines.append(f"较峰值盈亏：{money(payload['pnl_vs_peak'])}")
    if payload.get("pnl_vs_initial") is not None:
        lines.append(f"较本金盈亏：{money(payload['pnl_vs_initial'])}")
    if payload.get("action"):
        lines.append(f"处置：{payload['action']}")
    elif payload.get("legacy_text"):
        lines.append(f"说明：{payload['legacy_text']}")
    elif payload.get("dd") is not None:
        stop = row.get("level") == "critical" or str(payload.get("kind") or "").endswith("stop")
        lines.append(
            "处置：已触发急停，停止新开仓与继续模拟成交。"
            if stop
            else "处置：未达急停线，请关注回撤与仓位。"
        )
    return lines

"""Minimum QualityChecker: missing, range/OHLC, adj jump, point-in-time."""

from __future__ import annotations

import re
from uuid import uuid4

from asqt.contracts import MARKET_DAILY_COLUMNS


ADJ_WARN_RATIO = 1.5
ADJ_BLOCK_RATIO = 2.0


class ContractQualityChecker:
    def check(
        self,
        dataset: str,
        trade_date: str | None = None,
        *,
        records: list[dict] | None = None,
        instruments: list[dict] | None = None,
        calendar: list[dict] | None = None,
        expected_symbols: list[str] | None = None,
        corporate_actions: list[dict] | None = None,
    ) -> dict:
        if dataset != "market_daily":
            return {
                "ok": True,
                "trade_allowed": True,
                "issues": [],
                "dataset": dataset,
                "trade_date": trade_date,
            }
        rows = list(records or [])
        if trade_date:
            rows = [row for row in rows if row.get("trade_date") == trade_date]
        issues: list[dict] = []
        issues.extend(
            _missing_issues(
                rows,
                calendar,
                expected_symbols,
                trade_date,
                instruments=instruments or [],
            )
        )
        issues.extend(_range_issues(rows))
        issues.extend(_adj_jump_issues(records or [], corporate_actions))
        issues.extend(_point_in_time_issues(rows, instruments or []))
        blocked = any(item["severity"] == "block" for item in issues)
        return {
            "ok": not blocked,
            "trade_allowed": not blocked,
            "dataset": dataset,
            "trade_date": trade_date,
            "issue_count": len(issues),
            "issues": issues,
        }


def _issue(
    check_type: str,
    severity: str,
    *,
    symbol: str | None = None,
    trade_date: str | None = None,
    diff: str,
    source_a: str | None = None,
    source_b: str | None = None,
) -> dict:
    return {
        "issue_id": str(uuid4()),
        "dataset": "market_daily",
        "symbol": symbol,
        "trade_date": trade_date,
        "check_type": check_type,
        "severity": severity,
        "status": "open",
        "source_a": source_a,
        "source_b": source_b,
        "diff": diff,
    }


def _listing_window(instruments: list[dict], by_symbol_dates: dict[str, set[str]]) -> dict[str, tuple[str | None, str | None]]:
    """Effective [list_date, delist_date] per symbol; fall back to first observed bar."""
    meta = {str(item.get("symbol")): item for item in instruments}
    out: dict[str, tuple[str | None, str | None]] = {}
    symbols = set(meta) | set(by_symbol_dates)
    for symbol in symbols:
        row = meta.get(symbol) or {}
        list_date = str(row.get("list_date") or "").strip() or None
        delist_date = str(row.get("delist_date") or "").strip() or None
        if not list_date:
            have = by_symbol_dates.get(symbol) or set()
            list_date = min(have) if have else None
        out[symbol] = (list_date, delist_date)
    return out


def _missing_issues(
    rows: list[dict],
    calendar: list[dict] | None,
    expected_symbols: list[str] | None,
    trade_date: str | None,
    *,
    instruments: list[dict] | None = None,
) -> list[dict]:
    issues: list[dict] = []
    required = ("open", "high", "low", "close", "volume", "amount", "adj_factor")
    for row in rows:
        missing = [name for name in required if row.get(name) is None]
        extra = [name for name in MARKET_DAILY_COLUMNS if name not in row]
        if missing or extra:
            issues.append(
                _issue(
                    "missing",
                    "block",
                    symbol=row.get("symbol"),
                    trade_date=row.get("trade_date"),
                    diff=f"null_or_missing_fields={missing or extra}",
                )
            )
    symbols_present = {row.get("symbol") for row in rows}
    if expected_symbols:
        for symbol in expected_symbols:
            if symbol not in symbols_present:
                issues.append(
                    _issue(
                        "missing",
                        "block",
                        symbol=symbol,
                        trade_date=trade_date,
                        diff="symbol_missing_from_market_daily",
                    )
                )
    if calendar:
        open_dates = [item["trade_date"] for item in calendar if int(item.get("is_open") or 0) == 1]
        if trade_date:
            open_dates = [item for item in open_dates if item == trade_date]
        by_symbol: dict[str, set[str]] = {}
        for row in rows:
            by_symbol.setdefault(str(row.get("symbol")), set()).add(str(row.get("trade_date")))
        windows = _listing_window(instruments or [], by_symbol)
        check_symbols = expected_symbols or list(by_symbol)
        for symbol in check_symbols:
            have = by_symbol.get(str(symbol), set())
            list_date, delist_date = windows.get(str(symbol), (None, None))
            for day in open_dates:
                day_s = str(day)
                if list_date and day_s < list_date:
                    continue
                if delist_date and day_s > delist_date:
                    continue
                if day_s not in have:
                    issues.append(
                        _issue(
                            "missing",
                            "warn",
                            symbol=symbol,
                            trade_date=day,
                            diff="trade_date_missing_on_open_calendar",
                        )
                    )
    return issues


def _range_issues(rows: list[dict]) -> list[dict]:
    issues: list[dict] = []
    for row in rows:
        open_, high, low, close = row.get("open"), row.get("high"), row.get("low"), row.get("close")
        volume, amount = row.get("volume"), row.get("amount")
        if None in (open_, high, low, close):
            continue
        if high < max(open_, close, low) or low > min(open_, close, high):
            issues.append(
                _issue(
                    "range",
                    "block",
                    symbol=row.get("symbol"),
                    trade_date=row.get("trade_date"),
                    diff=f"ohlc_inconsistent o={open_} h={high} l={low} c={close}",
                )
            )
        if min(open_, high, low, close) <= 0:
            issues.append(
                _issue(
                    "range",
                    "block",
                    symbol=row.get("symbol"),
                    trade_date=row.get("trade_date"),
                    diff="non_positive_price",
                )
            )
        if volume is not None and volume < 0:
            issues.append(
                _issue(
                    "range",
                    "block",
                    symbol=row.get("symbol"),
                    trade_date=row.get("trade_date"),
                    diff=f"negative_volume={volume}",
                )
            )
        if amount is not None and amount < 0:
            issues.append(
                _issue(
                    "range",
                    "block",
                    symbol=row.get("symbol"),
                    trade_date=row.get("trade_date"),
                    diff=f"negative_amount={amount}",
                )
            )
    return issues


def _adj_jump_issues(all_rows: list[dict], corporate_actions: list[dict] | None = None) -> list[dict]:
    from asqt.corporate_actions import find_explaining_action, load_corporate_actions
    from asqt.symbols import infer_instrument_type

    actions = list(corporate_actions) if corporate_actions is not None else load_corporate_actions()
    issues: list[dict] = []
    by_symbol: dict[str, list[dict]] = {}
    for row in all_rows:
        by_symbol.setdefault(str(row.get("symbol")), []).append(row)
    for symbol, items in by_symbol.items():
        ordered = sorted(items, key=lambda item: str(item.get("trade_date") or ""))
        previous_factor = None
        previous_row: dict | None = None
        for row in ordered:
            factor = row.get("adj_factor")
            if factor in (None, 0) or previous_factor in (None, 0) or previous_row is None:
                previous_factor = factor
                previous_row = row
                continue
            if find_explaining_action(previous_row, row, actions):
                previous_factor = factor
                previous_row = row
                continue
            ratio = factor / previous_factor
            trade_date = row.get("trade_date")
            # ETF/fund adj feeds often park at 1.0 then jump; keep visible but don't halt trading.
            etf_placeholder = (
                infer_instrument_type(symbol) == "etf"
                and float(previous_factor) == 1.0
                and float(factor) != 1.0
            )
            if ratio >= ADJ_BLOCK_RATIO or ratio <= 1 / ADJ_BLOCK_RATIO:
                issues.append(
                    _issue(
                        "adj_conflict",
                        "warn" if etf_placeholder else "block",
                        symbol=symbol,
                        trade_date=trade_date,
                        diff=f"adj_factor_ratio={ratio:.4f} prev={previous_factor} curr={factor}",
                    )
                )
            elif ratio >= ADJ_WARN_RATIO or ratio <= 1 / ADJ_WARN_RATIO:
                issues.append(
                    _issue(
                        "adj_conflict",
                        "warn",
                        symbol=symbol,
                        trade_date=trade_date,
                        diff=f"adj_factor_ratio={ratio:.4f} prev={previous_factor} curr={factor}",
                    )
                )
            previous_factor = factor
            previous_row = row
    return issues


def _point_in_time_issues(rows: list[dict], instruments: list[dict]) -> list[dict]:
    issues: list[dict] = []
    by_symbol = {item["symbol"]: item for item in instruments}
    for row in rows:
        symbol = row.get("symbol")
        trade_date = str(row.get("trade_date") or "")
        meta = by_symbol.get(str(symbol), {})
        list_date = meta.get("list_date") or ""
        delist_date = meta.get("delist_date") or ""
        if list_date and trade_date and trade_date < list_date:
            issues.append(
                _issue(
                    "point_in_time",
                    "block",
                    symbol=symbol,
                    trade_date=trade_date,
                    diff=f"bar_before_list_date={list_date}",
                    source_a="market_daily",
                    source_b="instrument_master",
                )
            )
        if delist_date and trade_date and trade_date > delist_date:
            issues.append(
                _issue(
                    "point_in_time",
                    "block",
                    symbol=symbol,
                    trade_date=trade_date,
                    diff=f"bar_after_delist_date={delist_date}",
                    source_a="market_daily",
                    source_b="instrument_master",
                )
            )
    return issues


def format_issue_diff(diff: str | None, *, check_type: str | None = None) -> str:
    """Human-readable copy for quality_issue.diff. Raw string stays on the row."""
    text = (diff or "").strip()
    if not text:
        return "-"
    scale = re.search(
        r"adj_factor_scale n=(\d+).*stored=([0-9.]+)\s+peer=([0-9.]+)\s+rel=([0-9.]+)",
        text,
    )
    if scale:
        n, stored, peer, rel = scale.groups()
        pct = float(rel) * 100
        return (
            f"复权因子基准不同（{n} 个交易日）：本地 { _trim_num(stored) }，"
            f"对照源 { _trim_num(peer) }，相对差约 {pct:.1f}%。收盘价已对齐，不阻断交易。"
        )
    silent = re.search(
        r"silent_jump_inconsistent factor_ratio=([0-9.]+)\s+price_ratio=([0-9.]+)",
        text,
    )
    if silent:
        factor_r, price_r = (float(silent.group(1)), float(silent.group(2)))
        return (
            f"复权因子变动约 {(factor_r - 1) * 100:+.1f}%，未复权价比 {price_r:.3f}。"
            "两者对不齐，可能是现金分红或源口径差异，需对照公告。"
        )
    adj = re.search(r"adj_factor stored=([0-9.]+)\s+peer=([0-9.]+)\s+rel=([0-9.]+)", text)
    close = re.search(r"close stored=([0-9.]+)\s+peer=([0-9.]+)\s+rel=([0-9.]+)", text)
    if close and adj:
        return (
            f"收盘价不一致：本地 { _trim_num(close.group(1)) }，对照源 { _trim_num(close.group(2)) }，"
            f"相对差约 {float(close.group(3)) * 100:.1f}%；因子也不一致。"
        )
    if close:
        return (
            f"收盘价不一致：本地 { _trim_num(close.group(1)) }，对照源 { _trim_num(close.group(2)) }，"
            f"相对差约 {float(close.group(3)) * 100:.1f}%。"
        )
    if adj:
        return (
            f"复权因子水平不同：本地 { _trim_num(adj.group(1)) }，对照源 { _trim_num(adj.group(2)) }，"
            f"相对差约 {float(adj.group(3)) * 100:.1f}%。"
        )
    jump = re.search(r"adj_factor_ratio=([0-9.]+)\s+prev=([0-9.]+)\s+curr=([0-9.]+)", text)
    if jump:
        return f"相邻日复权因子从 { _trim_num(jump.group(2)) } 变为 { _trim_num(jump.group(3)) }（倍数 { _trim_num(jump.group(1)) }）。"
    if "trade_date_missing_on_open_calendar" in text:
        return "日历标记开市，但本地没有这一天的日 K。"
    if "symbol_missing_from_market_daily" in text:
        return "宇宙内有这只标的，但行情表里没有它。"
    if text.startswith("null_or_missing_fields="):
        return f"必填字段缺失：{text.split('=', 1)[-1]}"
    if text.startswith("bar_before_list_date="):
        return f"上市前仍有行情（上市日 {text.split('=', 1)[-1]}）。"
    if text.startswith("bar_after_delist_date="):
        return f"退市后仍有行情（退市日 {text.split('=', 1)[-1]}）。"
    if check_type == "cross_source":
        if "adj_factor" in text.lower() and "close" not in text.lower():
            return (
                f"主源与对照源复权因子水平不同（多为基准差异，警告不拦交易）：{text}"
            )
        return (
            f"主源与对照源行情不一致（警告级，不单独阻断交易）：{text}"
        )
    if check_type == "adj_conflict":
        return (
            f"复权因子跳变且无已核实公司行为解释（可在 docs/p0/corporate_actions.csv 补 verified=1）：{text}"
        )
    return text


def _trim_num(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.4f}".rstrip("0").rstrip(".")

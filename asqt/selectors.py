"""TargetSelector: factor_rows + rules → clipped target weights."""

from __future__ import annotations

from typing import Any


def clip_weights(raw: dict[str, float], max_weight: float, gross_limit: float) -> dict[str, float]:
    clipped = {symbol: min(max(weight, 0.0), max_weight) for symbol, weight in raw.items() if weight > 0}
    total = sum(clipped.values())
    if total <= 0:
        return {}
    if total > gross_limit:
        scale = gross_limit / total
        clipped = {symbol: weight * scale for symbol, weight in clipped.items()}
    return {symbol: round(weight, 10) for symbol, weight in sorted(clipped.items())}


def _pass_filter(values: dict[str, float], rule: dict[str, Any]) -> bool:
    name = str(rule["factor"])
    if name not in values:
        return False
    left = float(values[name])
    op = str(rule.get("op") or ">")
    right = float(rule["value"])
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    raise ValueError(f"unknown filter op: {op}")


def eval_filter_expr(values: dict[str, float], expr: Any) -> bool:
    """Evaluate a filter leaf or AND/OR tree.

    Leaf: ``{factor, op, value}``
    AND: ``{all: [nodes...]}`` or a bare list (legacy flat AND)
    OR: ``{any: [nodes...]}``
    """
    if expr is None:
        return True
    if isinstance(expr, list):
        return all(eval_filter_expr(values, node) for node in expr)
    if not isinstance(expr, dict):
        raise ValueError(f"invalid filter expr: {expr!r}")
    if "all" in expr:
        nodes = expr["all"]
        if not isinstance(nodes, list):
            raise ValueError("filter all must be a list")
        return all(eval_filter_expr(values, node) for node in nodes)
    if "any" in expr:
        nodes = expr["any"]
        if not isinstance(nodes, list):
            raise ValueError("filter any must be a list")
        if not nodes:
            return False
        return any(eval_filter_expr(values, node) for node in nodes)
    if "factor" in expr:
        return _pass_filter(values, expr)
    raise ValueError(f"unknown filter node: {sorted(expr)}")


def _is_suspended(
    symbol: str,
    trade_date: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> bool:
    if suspended is not None:
        return (symbol, trade_date) in suspended
    for row in limits or []:
        if row.get("symbol") == symbol and str(row.get("trade_date")) == trade_date:
            return int(row.get("is_suspended") or 0) == 1
    return False


def select_targets(
    factor_rows: list[dict[str, Any]],
    asof: str,
    rules: dict[str, Any],
    *,
    limits: list[dict[str, Any]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    """Pick equal-weight targets from asof factor rows (top_k / filter / clip).

    ``rules`` keys (aligned with STRATEGY_SPECS params):
      score_factor: str | None — rank key; None → equal weight all survivors
      filters: list[{factor, op, value}] — flat AND (legacy)
      filter_expr: AND/OR tree (``all`` / ``any`` / leaf); wins over ``filters``
      top_k: int | None — None keeps all filtered names
      max_weight, gross_limit: float
      ascending: bool — default False (higher score better)
    """
    by_symbol: dict[str, dict[str, float]] = {}
    for row in factor_rows:
        if str(row.get("trade_date")) != asof:
            continue
        symbol = str(row["symbol"])
        by_symbol.setdefault(symbol, {})[str(row["factor_name"])] = float(row["value"])

    filter_expr = rules.get("filter_expr")
    if filter_expr is None and rules.get("filters") is not None:
        filter_expr = list(rules.get("filters") or [])
    score_factor = rules.get("score_factor")
    top_k = rules.get("top_k")
    ascending = bool(rules.get("ascending", False))
    max_weight = float(rules["max_weight"])
    gross_limit = float(rules["gross_limit"])

    scored: list[tuple[float, str]] = []
    survivors: list[str] = []
    for symbol, values in by_symbol.items():
        if _is_suspended(symbol, asof, limits=limits, suspended=suspended):
            continue
        if filter_expr is not None and not eval_filter_expr(values, filter_expr):
            continue
        if score_factor:
            if score_factor not in values:
                continue
            scored.append((float(values[score_factor]), symbol))
        else:
            survivors.append(symbol)

    if score_factor:
        scored.sort(reverse=not ascending)
        if top_k is not None:
            scored = scored[: int(top_k)]
        picked = [symbol for _score, symbol in scored]
    else:
        picked = survivors
        if top_k is not None:
            picked = sorted(picked)[: int(top_k)]

    if not picked:
        return {}
    weight = 1.0 / len(picked)
    return clip_weights({symbol: weight for symbol in picked}, max_weight, gross_limit)

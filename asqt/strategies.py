"""P2 first strategies: one rule (ETF MA) and one A-share TopK."""

from __future__ import annotations

from typing import Any

from asqt.symbols import infer_instrument_type

CODE_VERSION = "p2.1"

ETF_MA_ROTATE = "etf_ma_rotate"
STOCK_MOMENTUM_TOPK = "stock_momentum_topk"

STRATEGY_SPECS: dict[str, dict[str, Any]] = {
    ETF_MA_ROTATE: {
        "kind": "rule",
        "instrument_type": "etf",
        "parameter_set_id": "etf_ma_rotate.w20",
        "params": {"window": 20, "max_weight": 0.20, "gross_limit": 0.95},
    },
    STOCK_MOMENTUM_TOPK: {
        "kind": "topk",
        "instrument_type": "stock",
        "parameter_set_id": "stock_momentum_topk.k5.l20",
        "params": {"lookback": 20, "top_k": 5, "max_weight": 0.10, "gross_limit": 0.95},
    },
}


def adj_close(row: dict[str, Any]) -> float:
    return float(row["close"]) * float(row["adj_factor"])


def asof_rows(rows: list[dict[str, Any]], asof: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row["trade_date"]) <= asof]


def _by_symbol(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["symbol"]), []).append(row)
    for symbol in grouped:
        grouped[symbol] = sorted(grouped[symbol], key=lambda item: str(item["trade_date"]))
    return grouped


def _suspended(limits: list[dict[str, Any]], symbol: str, trade_date: str) -> bool:
    for row in limits:
        if row.get("symbol") == symbol and str(row.get("trade_date")) == trade_date:
            return int(row.get("is_suspended") or 0) == 1
    return False


def _clip_weights(raw: dict[str, float], max_weight: float, gross_limit: float) -> dict[str, float]:
    clipped = {symbol: min(max(weight, 0.0), max_weight) for symbol, weight in raw.items() if weight > 0}
    total = sum(clipped.values())
    if total <= 0:
        return {}
    if total > gross_limit:
        scale = gross_limit / total
        clipped = {symbol: weight * scale for symbol, weight in clipped.items()}
    return {symbol: round(weight, 10) for symbol, weight in sorted(clipped.items())}


def signal_etf_ma_rotate(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, float]:
    spec = dict(STRATEGY_SPECS[ETF_MA_ROTATE]["params"])
    spec.update(params or {})
    window = int(spec["window"])
    snapshot = _by_symbol(asof_rows(rows, asof))
    chosen: list[str] = []
    for symbol, series in snapshot.items():
        if infer_instrument_type(symbol) != "etf":
            continue
        if _suspended(limits or [], symbol, asof):
            continue
        if len(series) < window:
            continue
        closes = [adj_close(item) for item in series[-window:]]
        sma = sum(closes) / window
        if closes[-1] > sma:
            chosen.append(symbol)
    if not chosen:
        return {}
    weight = 1.0 / len(chosen)
    return _clip_weights({symbol: weight for symbol in chosen}, spec["max_weight"], spec["gross_limit"])


def signal_stock_momentum_topk(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, float]:
    spec = dict(STRATEGY_SPECS[STOCK_MOMENTUM_TOPK]["params"])
    spec.update(params or {})
    lookback = int(spec["lookback"])
    top_k = int(spec["top_k"])
    snapshot = _by_symbol(asof_rows(rows, asof))
    scored: list[tuple[float, str]] = []
    for symbol, series in snapshot.items():
        if infer_instrument_type(symbol) != "stock":
            continue
        if _suspended(limits or [], symbol, asof):
            continue
        if len(series) < lookback + 1:
            continue
        start = adj_close(series[-(lookback + 1)])
        end = adj_close(series[-1])
        if start <= 0:
            continue
        scored.append((end / start - 1.0, symbol))
    scored.sort(reverse=True)
    picked = [symbol for _score, symbol in scored[:top_k]]
    if not picked:
        return {}
    weight = 1.0 / len(picked)
    return _clip_weights({symbol: weight for symbol in picked}, spec["max_weight"], spec["gross_limit"])


def factor_rows(
    strategy_id: str,
    rows: list[dict[str, Any]],
    asof: str,
    *,
    source_run_id: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    snapshot = _by_symbol(asof_rows(rows, asof))
    out: list[dict[str, Any]] = []
    if strategy_id == ETF_MA_ROTATE:
        window = int((params or STRATEGY_SPECS[strategy_id]["params"])["window"])
        name = "etf_ma_gap"
        for symbol, series in snapshot.items():
            if infer_instrument_type(symbol) != "etf" or len(series) < window:
                continue
            closes = [adj_close(item) for item in series[-window:]]
            sma = sum(closes) / window
            value = closes[-1] / sma - 1.0 if sma else 0.0
            out.append(_factor(asof, symbol, name, value, source_run_id))
    elif strategy_id == STOCK_MOMENTUM_TOPK:
        lookback = int((params or STRATEGY_SPECS[strategy_id]["params"])["lookback"])
        name = "stock_momentum"
        for symbol, series in snapshot.items():
            if infer_instrument_type(symbol) != "stock" or len(series) < lookback + 1:
                continue
            start = adj_close(series[-(lookback + 1)])
            end = adj_close(series[-1])
            value = end / start - 1.0 if start else 0.0
            out.append(_factor(asof, symbol, name, value, source_run_id))
    return out


def weights_for(strategy_id: str, rows: list[dict[str, Any]], asof: str, **kwargs: Any) -> dict[str, float]:
    if strategy_id == ETF_MA_ROTATE:
        return signal_etf_ma_rotate(rows, asof, **kwargs)
    if strategy_id == STOCK_MOMENTUM_TOPK:
        return signal_stock_momentum_topk(rows, asof, **kwargs)
    raise ValueError(f"unknown strategy: {strategy_id}")


def _factor(trade_date: str, symbol: str, name: str, value: float, run_id: str) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "factor_name": name,
        "value": round(float(value), 10),
        "model_version": CODE_VERSION,
        "source_run_id": run_id,
    }

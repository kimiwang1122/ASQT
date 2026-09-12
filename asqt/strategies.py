"""P2/P2.3 strategies: MA rotate, momentum TopK, low-vol momentum, MA+momentum filter."""

from __future__ import annotations

from typing import Any

from asqt import factors as F
from asqt.symbols import infer_instrument_type

CODE_VERSION = "p2.3"

ETF_MA_ROTATE = "etf_ma_rotate"
STOCK_MOMENTUM_TOPK = "stock_momentum_topk"
ETF_MOMENTUM_TOPK = "etf_momentum_topk"
STOCK_LOWVOL_MOMENTUM = "stock_lowvol_momentum"
ETF_MA_MOMENTUM_FILTER = "etf_ma_momentum_filter"

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
    ETF_MOMENTUM_TOPK: {
        "kind": "topk",
        "instrument_type": "etf",
        "parameter_set_id": "etf_momentum_topk.k3.l40",
        "params": {"lookback": 40, "top_k": 3, "max_weight": 0.20, "gross_limit": 0.95},
    },
    STOCK_LOWVOL_MOMENTUM: {
        "kind": "topk",
        "instrument_type": "stock",
        "parameter_set_id": "stock_lowvol_momentum.k5.l20.v20",
        "params": {
            "lookback": 20,
            "vol_window": 20,
            "top_k": 5,
            "max_weight": 0.10,
            "gross_limit": 0.95,
        },
    },
    ETF_MA_MOMENTUM_FILTER: {
        "kind": "topk",
        "instrument_type": "etf",
        "parameter_set_id": "etf_ma_momentum_filter.k3.m20.l40",
        "params": {
            "ma_window": 20,
            "mom_lookback": 40,
            "top_k": 3,
            "max_weight": 0.20,
            "gross_limit": 0.95,
        },
    },
}


def adj_close(row: dict[str, Any]) -> float:
    return F.adj_close(row)


def asof_rows(rows: list[dict[str, Any]], asof: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row["trade_date"]) <= asof]


def market_by_symbol(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["symbol"]), []).append(row)
    for symbol in grouped:
        grouped[symbol] = sorted(grouped[symbol], key=lambda item: str(item["trade_date"]))
    return grouped


def _by_symbol(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return market_by_symbol(rows)


def suspended_keys(limits: list[dict[str, Any]] | None) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for row in limits or []:
        if int(row.get("is_suspended") or 0) == 1:
            out.add((str(row.get("symbol")), str(row.get("trade_date"))))
    return out


def _series_asof(series: list[dict[str, Any]], asof: str) -> list[dict[str, Any]]:
    if not series:
        return []
    if str(series[-1]["trade_date"]) <= asof:
        return series
    if str(series[0]["trade_date"]) > asof:
        return []
    lo, hi = 0, len(series)
    while lo < hi:
        mid = (lo + hi) // 2
        if str(series[mid]["trade_date"]) <= asof:
            lo = mid + 1
        else:
            hi = mid
    return series[:lo]


def _suspended(limits: list[dict[str, Any]], symbol: str, trade_date: str) -> bool:
    for row in limits:
        if row.get("symbol") == symbol and str(row.get("trade_date")) == trade_date:
            return int(row.get("is_suspended") or 0) == 1
    return False


def _is_suspended(
    symbol: str,
    trade_date: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> bool:
    if suspended is not None:
        return (symbol, trade_date) in suspended
    return _suspended(limits or [], symbol, trade_date)


def _clip_weights(raw: dict[str, float], max_weight: float, gross_limit: float) -> dict[str, float]:
    clipped = {symbol: min(max(weight, 0.0), max_weight) for symbol, weight in raw.items() if weight > 0}
    total = sum(clipped.values())
    if total <= 0:
        return {}
    if total > gross_limit:
        scale = gross_limit / total
        clipped = {symbol: weight * scale for symbol, weight in clipped.items()}
    return {symbol: round(weight, 10) for symbol, weight in sorted(clipped.items())}


def _merged_params(strategy_id: str, params: dict[str, Any] | None) -> dict[str, Any]:
    spec = dict(STRATEGY_SPECS[strategy_id]["params"])
    spec.update(params or {})
    return spec


def signal_etf_ma_rotate(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    spec = _merged_params(ETF_MA_ROTATE, params)
    window = int(spec["window"])
    grouped = market_by_symbol if market_by_symbol is not None else _by_symbol(rows)
    chosen: list[str] = []
    for symbol, series in grouped.items():
        if infer_instrument_type(symbol) != "etf":
            continue
        if _is_suspended(symbol, asof, limits=limits, suspended=suspended):
            continue
        hist = _series_asof(series, asof)
        gap = F.ma_gap(hist, window)
        if gap is not None and gap > 0:
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
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    return _signal_momentum_topk(
        rows,
        asof,
        strategy_id=STOCK_MOMENTUM_TOPK,
        instrument_type="stock",
        limits=limits,
        params=params,
        market_by_symbol=market_by_symbol,
        suspended=suspended,
    )


def signal_etf_momentum_topk(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    return _signal_momentum_topk(
        rows,
        asof,
        strategy_id=ETF_MOMENTUM_TOPK,
        instrument_type="etf",
        limits=limits,
        params=params,
        market_by_symbol=market_by_symbol,
        suspended=suspended,
    )


def _signal_momentum_topk(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    strategy_id: str,
    instrument_type: str,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    spec = _merged_params(strategy_id, params)
    lookback = int(spec["lookback"])
    top_k = int(spec["top_k"])
    grouped = market_by_symbol if market_by_symbol is not None else _by_symbol(rows)
    scored: list[tuple[float, str]] = []
    for symbol, series in grouped.items():
        if infer_instrument_type(symbol) != instrument_type:
            continue
        if _is_suspended(symbol, asof, limits=limits, suspended=suspended):
            continue
        hist = _series_asof(series, asof)
        score = F.momentum(hist, lookback)
        if score is None:
            continue
        scored.append((score, symbol))
    scored.sort(reverse=True)
    picked = [symbol for _score, symbol in scored[:top_k]]
    if not picked:
        return {}
    weight = 1.0 / len(picked)
    return _clip_weights({symbol: weight for symbol in picked}, spec["max_weight"], spec["gross_limit"])


def signal_stock_lowvol_momentum(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    """Rank by momentum/volatility (higher better), take top_k."""
    spec = _merged_params(STOCK_LOWVOL_MOMENTUM, params)
    lookback = int(spec["lookback"])
    vol_window = int(spec["vol_window"])
    top_k = int(spec["top_k"])
    grouped = market_by_symbol if market_by_symbol is not None else _by_symbol(rows)
    scored: list[tuple[float, str]] = []
    for symbol, series in grouped.items():
        if infer_instrument_type(symbol) != "stock":
            continue
        if _is_suspended(symbol, asof, limits=limits, suspended=suspended):
            continue
        hist = _series_asof(series, asof)
        score = F.risk_adjusted_momentum(hist, lookback=lookback, vol_window=vol_window)
        if score is None:
            continue
        scored.append((score, symbol))
    scored.sort(reverse=True)
    picked = [symbol for _score, symbol in scored[:top_k]]
    if not picked:
        return {}
    weight = 1.0 / len(picked)
    return _clip_weights({symbol: weight for symbol in picked}, spec["max_weight"], spec["gross_limit"])


def signal_etf_ma_momentum_filter(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    """ETF universe: require ma_gap > 0, then rank by momentum TopK."""
    spec = _merged_params(ETF_MA_MOMENTUM_FILTER, params)
    ma_window = int(spec["ma_window"])
    mom_lookback = int(spec["mom_lookback"])
    top_k = int(spec["top_k"])
    grouped = market_by_symbol if market_by_symbol is not None else _by_symbol(rows)
    scored: list[tuple[float, str]] = []
    for symbol, series in grouped.items():
        if infer_instrument_type(symbol) != "etf":
            continue
        if _is_suspended(symbol, asof, limits=limits, suspended=suspended):
            continue
        hist = _series_asof(series, asof)
        gap = F.ma_gap(hist, ma_window)
        if gap is None or gap <= 0:
            continue
        score = F.momentum(hist, mom_lookback)
        if score is None:
            continue
        scored.append((score, symbol))
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
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    grouped = market_by_symbol if market_by_symbol is not None else _by_symbol(rows)
    out: list[dict[str, Any]] = []
    spec = _merged_params(strategy_id, params) if strategy_id in STRATEGY_SPECS else dict(params or {})
    if strategy_id == ETF_MA_ROTATE:
        window = int(spec["window"])
        for symbol, series in grouped.items():
            if infer_instrument_type(symbol) != "etf":
                continue
            hist = _series_asof(series, asof)
            value = F.ma_gap(hist, window)
            if value is None:
                continue
            out.append(_factor(asof, symbol, "etf_ma_gap", value, source_run_id))
    elif strategy_id in {STOCK_MOMENTUM_TOPK, ETF_MOMENTUM_TOPK}:
        lookback = int(spec["lookback"])
        name = "stock_momentum" if strategy_id == STOCK_MOMENTUM_TOPK else "etf_momentum"
        want = STRATEGY_SPECS[strategy_id]["instrument_type"]
        for symbol, series in grouped.items():
            if infer_instrument_type(symbol) != want:
                continue
            hist = _series_asof(series, asof)
            value = F.momentum(hist, lookback)
            if value is None:
                continue
            out.append(_factor(asof, symbol, name, value, source_run_id))
    elif strategy_id == STOCK_LOWVOL_MOMENTUM:
        lookback = int(spec["lookback"])
        vol_window = int(spec["vol_window"])
        for symbol, series in grouped.items():
            if infer_instrument_type(symbol) != "stock":
                continue
            hist = _series_asof(series, asof)
            mom = F.momentum(hist, lookback)
            vol = F.volatility(hist, vol_window)
            score = F.risk_adjusted_momentum(hist, lookback=lookback, vol_window=vol_window)
            if mom is not None:
                out.append(_factor(asof, symbol, "stock_momentum", mom, source_run_id))
            if vol is not None:
                out.append(_factor(asof, symbol, "stock_volatility", vol, source_run_id))
            if score is not None:
                out.append(_factor(asof, symbol, "stock_mom_over_vol", score, source_run_id))
    elif strategy_id == ETF_MA_MOMENTUM_FILTER:
        ma_window = int(spec["ma_window"])
        mom_lookback = int(spec["mom_lookback"])
        for symbol, series in grouped.items():
            if infer_instrument_type(symbol) != "etf":
                continue
            hist = _series_asof(series, asof)
            gap = F.ma_gap(hist, ma_window)
            mom = F.momentum(hist, mom_lookback)
            if gap is not None:
                out.append(_factor(asof, symbol, "etf_ma_gap", gap, source_run_id))
            if mom is not None:
                out.append(_factor(asof, symbol, "etf_momentum", mom, source_run_id))
    return out


def weights_for(strategy_id: str, rows: list[dict[str, Any]], asof: str, **kwargs: Any) -> dict[str, float]:
    if strategy_id == ETF_MA_ROTATE:
        return signal_etf_ma_rotate(rows, asof, **kwargs)
    if strategy_id == STOCK_MOMENTUM_TOPK:
        return signal_stock_momentum_topk(rows, asof, **kwargs)
    if strategy_id == ETF_MOMENTUM_TOPK:
        return signal_etf_momentum_topk(rows, asof, **kwargs)
    if strategy_id == STOCK_LOWVOL_MOMENTUM:
        return signal_stock_lowvol_momentum(rows, asof, **kwargs)
    if strategy_id == ETF_MA_MOMENTUM_FILTER:
        return signal_etf_ma_momentum_filter(rows, asof, **kwargs)
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

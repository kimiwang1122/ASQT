"""P2/P2.4 strategies: MA rotate, momentum/reversal TopK, low-vol, volume confirm, skip-month, holder events."""

from __future__ import annotations

from typing import Any

from asqt.factor_pipeline import build_data_frame, compute_factor_frame, series_asof
from asqt.selectors import clip_weights, select_targets

CODE_VERSION = "p2.4"

ETF_MA_ROTATE = "etf_ma_rotate"
STOCK_MOMENTUM_TOPK = "stock_momentum_topk"
ETF_MOMENTUM_TOPK = "etf_momentum_topk"
STOCK_LOWVOL_MOMENTUM = "stock_lowvol_momentum"
ETF_MA_MOMENTUM_FILTER = "etf_ma_momentum_filter"
STOCK_SHORT_REVERSAL_TOPK = "stock_short_reversal_topk"
STOCK_MOMENTUM_VOLUME_CONFIRM = "stock_momentum_volume_confirm"
STOCK_MOMENTUM_SKIP_MONTH = "stock_momentum_skip_month"
STOCK_HOLDER_INCREASE_FOLLOW = "stock_holder_increase_follow"

STRATEGY_SPECS: dict[str, dict[str, Any]] = {
    ETF_MA_ROTATE: {
        "kind": "rule",
        "instrument_type": "etf",
        "parameter_set_id": "etf_ma_rotate.w40",
        "params": {"window": 40, "max_weight": 0.20, "gross_limit": 0.95},
    },
    STOCK_MOMENTUM_TOPK: {
        "kind": "topk",
        "instrument_type": "stock",
        # Human review: prefer k5.l40 over IS-winner k5.l10 (similar OOS, much lower turnover).
        "parameter_set_id": "stock_momentum_topk.k5.l40",
        "params": {"lookback": 40, "top_k": 5, "max_weight": 0.10, "gross_limit": 0.95},
    },
    ETF_MOMENTUM_TOPK: {
        "kind": "topk",
        "instrument_type": "etf",
        "parameter_set_id": "etf_momentum_topk.k2.l20",
        "params": {"lookback": 20, "top_k": 2, "max_weight": 0.20, "gross_limit": 0.95},
    },
    STOCK_LOWVOL_MOMENTUM: {
        "kind": "topk",
        "instrument_type": "stock",
        "parameter_set_id": "stock_lowvol_momentum.k5.l40.v20",
        "params": {
            "lookback": 40,
            "vol_window": 20,
            "top_k": 5,
            "max_weight": 0.10,
            "gross_limit": 0.95,
        },
    },
    ETF_MA_MOMENTUM_FILTER: {
        "kind": "topk",
        "instrument_type": "etf",
        # Human review: prefer k3.m40.l40 (strong IS+OOS, lower turnover) over
        # prior OOS-max k3.m20.l20 which hurt paper (−12.1%).
        "parameter_set_id": "etf_ma_momentum_filter.k3.m40.l40",
        "params": {
            "ma_window": 40,
            "mom_lookback": 40,
            "top_k": 3,
            "max_weight": 0.20,
            "gross_limit": 0.95,
        },
    },
    STOCK_SHORT_REVERSAL_TOPK: {
        "kind": "topk",
        "instrument_type": "stock",
        # Human review: prefer k2.l10 over toxic k5.l5 (TO 0.22→0.08) without
        # needing rebalance_every_n; OOS still slightly positive.
        "parameter_set_id": "stock_short_reversal_topk.k2.l10",
        "params": {"lookback": 10, "top_k": 2, "max_weight": 0.10, "gross_limit": 0.95},
    },
    STOCK_MOMENTUM_VOLUME_CONFIRM: {
        "kind": "topk",
        "instrument_type": "stock",
        "parameter_set_id": "stock_momentum_volume_confirm.k5.l40.vz20",
        "params": {
            "lookback": 40,
            "vol_z_window": 20,
            "min_volume_z": 0.0,
            "top_k": 5,
            "max_weight": 0.10,
            "gross_limit": 0.95,
        },
    },
    STOCK_MOMENTUM_SKIP_MONTH: {
        "kind": "topk",
        "instrument_type": "stock",
        "parameter_set_id": "stock_momentum_skip_month.k5.l252.s21",
        "params": {
            "lookback": 252,
            "skip": 21,
            "top_k": 5,
            "max_weight": 0.10,
            "gross_limit": 0.95,
        },
    },
    STOCK_HOLDER_INCREASE_FOLLOW: {
        "kind": "topk",
        "instrument_type": "stock",
        # Pilot: draft only — do not auto-admit to paper.
        "default_lifecycle": "draft",
        "parameter_set_id": "stock_holder_increase_follow.k5.e20.l20",
        "params": {
            "event_lookback": 20,
            "lookback": 20,
            "min_momentum": 0.0,
            "top_k": 5,
            "max_weight": 0.10,
            "gross_limit": 0.95,
        },
    },
}


def adj_close(row: dict[str, Any]) -> float:
    from asqt import factors as F

    return F.adj_close(row)


def asof_rows(rows: list[dict[str, Any]], asof: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row["trade_date"]) <= asof]


def market_by_symbol(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return build_data_frame(rows)


def _by_symbol(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return market_by_symbol(rows)


def suspended_keys(limits: list[dict[str, Any]] | None) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for row in limits or []:
        if int(row.get("is_suspended") or 0) == 1:
            out.add((str(row.get("symbol")), str(row.get("trade_date"))))
    return out


def _series_asof(series: list[dict[str, Any]], asof: str) -> list[dict[str, Any]]:
    return series_asof(series, asof)


def _clip_weights(raw: dict[str, float], max_weight: float, gross_limit: float) -> dict[str, float]:
    return clip_weights(raw, max_weight, gross_limit)


def _merged_params(strategy_id: str, params: dict[str, Any] | None) -> dict[str, Any]:
    spec = dict(STRATEGY_SPECS[strategy_id]["params"])
    spec.update(params or {})
    return spec


def _resolve_events(
    events: list[dict[str, Any]] | None,
    settings: Any | None = None,
) -> list[dict[str, Any]]:
    if events is not None:
        return list(events)
    from asqt.events import query_events

    return query_events(settings=settings, newest_first=False)


def factor_specs_for(
    strategy_id: str,
    params: dict[str, Any] | None = None,
    *,
    events: list[dict[str, Any]] | None = None,
    settings: Any | None = None,
) -> list[dict[str, Any]]:
    """Factor specs for pipeline compute (aligned with STRATEGY_SPECS)."""
    if strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    spec = _merged_params(strategy_id, params)
    if strategy_id == ETF_MA_ROTATE:
        window = int(spec["window"])
        return [
            {
                "name": "etf_ma_gap",
                "instrument_type": "etf",
                "kind": "ma_gap",
                "kwargs": {"window": window},
                "params_for_hash": {"window": window},
            }
        ]
    if strategy_id in {STOCK_MOMENTUM_TOPK, ETF_MOMENTUM_TOPK}:
        lookback = int(spec["lookback"])
        name = "stock_momentum" if strategy_id == STOCK_MOMENTUM_TOPK else "etf_momentum"
        want = STRATEGY_SPECS[strategy_id]["instrument_type"]
        return [
            {
                "name": name,
                "instrument_type": want,
                "kind": "momentum",
                "kwargs": {"lookback": lookback},
                "params_for_hash": {"lookback": lookback},
            }
        ]
    if strategy_id == STOCK_LOWVOL_MOMENTUM:
        lookback = int(spec["lookback"])
        vol_window = int(spec["vol_window"])
        return [
            {
                "name": "stock_momentum",
                "instrument_type": "stock",
                "kind": "momentum",
                "kwargs": {"lookback": lookback},
                "params_for_hash": {"lookback": lookback},
            },
            {
                "name": "stock_volatility",
                "instrument_type": "stock",
                "kind": "volatility",
                "kwargs": {"window": vol_window},
                "params_for_hash": {"window": vol_window},
            },
            {
                "name": "stock_mom_over_vol",
                "instrument_type": "stock",
                "kind": "risk_adjusted_momentum",
                "kwargs": {"lookback": lookback, "vol_window": vol_window},
                "params_for_hash": {"lookback": lookback, "vol_window": vol_window},
            },
        ]
    if strategy_id == ETF_MA_MOMENTUM_FILTER:
        ma_window = int(spec["ma_window"])
        mom_lookback = int(spec["mom_lookback"])
        return [
            {
                "name": "etf_ma_gap",
                "instrument_type": "etf",
                "kind": "ma_gap",
                "kwargs": {"window": ma_window},
                "params_for_hash": {"window": ma_window},
            },
            {
                "name": "etf_momentum",
                "instrument_type": "etf",
                "kind": "momentum",
                "kwargs": {"lookback": mom_lookback},
                "params_for_hash": {"lookback": mom_lookback},
            },
        ]
    if strategy_id == STOCK_SHORT_REVERSAL_TOPK:
        lookback = int(spec["lookback"])
        return [
            {
                "name": "stock_reversal",
                "instrument_type": "stock",
                "kind": "reversal",
                "kwargs": {"lookback": lookback},
                "params_for_hash": {"lookback": lookback},
            }
        ]
    if strategy_id == STOCK_MOMENTUM_VOLUME_CONFIRM:
        lookback = int(spec["lookback"])
        vol_z_window = int(spec["vol_z_window"])
        return [
            {
                "name": "stock_momentum",
                "instrument_type": "stock",
                "kind": "momentum",
                "kwargs": {"lookback": lookback},
                "params_for_hash": {"lookback": lookback},
            },
            {
                "name": "stock_volume_z",
                "instrument_type": "stock",
                "kind": "volume_z",
                "kwargs": {"window": vol_z_window},
                "params_for_hash": {"window": vol_z_window},
            },
        ]
    if strategy_id == STOCK_MOMENTUM_SKIP_MONTH:
        lookback = int(spec["lookback"])
        skip = int(spec["skip"])
        return [
            {
                "name": "stock_momentum_skip_month",
                "instrument_type": "stock",
                "kind": "momentum_skip_month",
                "kwargs": {"lookback": lookback, "skip": skip},
                "params_for_hash": {"lookback": lookback, "skip": skip},
            }
        ]
    if strategy_id == STOCK_HOLDER_INCREASE_FOLLOW:
        from asqt.events import build_holder_event_index, holder_net_in_window

        event_lookback = int(spec["event_lookback"])
        lookback = int(spec["lookback"])
        # Index once: raw 17万行线性扫在全窗因子任务里会卡数十分钟。
        event_index = build_holder_event_index(_resolve_events(events, settings=settings))

        def _holder_net(hist: list[dict[str, Any]], *, _events=event_index, _n=event_lookback) -> float | None:
            if not hist:
                return None
            return holder_net_in_window(
                _events,
                str(hist[-1]["symbol"]),
                str(hist[-1]["trade_date"]),
                _n,
            )

        out: list[dict[str, Any]] = [
            {
                "name": "stock_holder_net",
                "instrument_type": "stock",
                "compute": _holder_net,
                "params_for_hash": {
                    "event_lookback": event_lookback,
                    "event_type": "holder_net",
                },
            },
            {
                "name": "stock_momentum",
                "instrument_type": "stock",
                "kind": "momentum",
                "kwargs": {"lookback": lookback},
                "params_for_hash": {"lookback": lookback},
            },
        ]
        return out
    raise ValueError(f"unknown strategy: {strategy_id}")


def selector_rules_for(strategy_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Selector rules aligned with STRATEGY_SPECS (top_k / filter / clip)."""
    if strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    spec = _merged_params(strategy_id, params)
    base = {
        "max_weight": float(spec["max_weight"]),
        "gross_limit": float(spec["gross_limit"]),
        "ascending": False,
    }
    if strategy_id == ETF_MA_ROTATE:
        return {
            **base,
            "score_factor": None,
            "filters": [{"factor": "etf_ma_gap", "op": ">", "value": 0}],
            "top_k": None,
        }
    if strategy_id in {STOCK_MOMENTUM_TOPK, ETF_MOMENTUM_TOPK}:
        name = "stock_momentum" if strategy_id == STOCK_MOMENTUM_TOPK else "etf_momentum"
        return {
            **base,
            "score_factor": name,
            "filters": [],
            "top_k": int(spec["top_k"]),
        }
    if strategy_id == STOCK_LOWVOL_MOMENTUM:
        return {
            **base,
            "score_factor": "stock_mom_over_vol",
            "filters": [],
            "top_k": int(spec["top_k"]),
        }
    if strategy_id == ETF_MA_MOMENTUM_FILTER:
        return {
            **base,
            "score_factor": "etf_momentum",
            "filters": [{"factor": "etf_ma_gap", "op": ">", "value": 0}],
            "top_k": int(spec["top_k"]),
        }
    if strategy_id == STOCK_SHORT_REVERSAL_TOPK:
        return {
            **base,
            "score_factor": "stock_reversal",
            "filters": [],
            "top_k": int(spec["top_k"]),
        }
    if strategy_id == STOCK_MOMENTUM_VOLUME_CONFIRM:
        return {
            **base,
            "score_factor": "stock_momentum",
            "filters": [
                {
                    "factor": "stock_volume_z",
                    "op": ">=",
                    "value": float(spec["min_volume_z"]),
                }
            ],
            "top_k": int(spec["top_k"]),
        }
    if strategy_id == STOCK_MOMENTUM_SKIP_MONTH:
        return {
            **base,
            "score_factor": "stock_momentum_skip_month",
            "filters": [],
            "top_k": int(spec["top_k"]),
        }
    if strategy_id == STOCK_HOLDER_INCREASE_FOLLOW:
        filters: list[dict[str, Any]] = [
            {"factor": "stock_holder_net", "op": ">", "value": 0},
        ]
        if spec.get("min_momentum") is not None:
            filters.append(
                {
                    "factor": "stock_momentum",
                    "op": ">=",
                    "value": float(spec["min_momentum"]),
                }
            )
        return {
            **base,
            "score_factor": "stock_holder_net",
            "filters": filters,
            "top_k": int(spec["top_k"]),
        }
    raise ValueError(f"unknown strategy: {strategy_id}")


def _weights_via_pipeline(
    strategy_id: str,
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
    events: list[dict[str, Any]] | None = None,
    settings: Any | None = None,
) -> dict[str, float]:
    grouped = market_by_symbol if market_by_symbol is not None else _by_symbol(rows)
    factors = compute_factor_frame(
        grouped,
        factor_specs_for(strategy_id, params, events=events, settings=settings),
        asof=asof,
        model_version=CODE_VERSION,
    )
    return select_targets(
        factors,
        asof,
        selector_rules_for(strategy_id, params),
        limits=limits,
        suspended=suspended,
    )


def signal_etf_ma_rotate(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    return _weights_via_pipeline(
        ETF_MA_ROTATE,
        rows,
        asof,
        limits=limits,
        params=params,
        market_by_symbol=market_by_symbol,
        suspended=suspended,
    )


def signal_stock_momentum_topk(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    return _weights_via_pipeline(
        STOCK_MOMENTUM_TOPK,
        rows,
        asof,
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
    return _weights_via_pipeline(
        ETF_MOMENTUM_TOPK,
        rows,
        asof,
        limits=limits,
        params=params,
        market_by_symbol=market_by_symbol,
        suspended=suspended,
    )


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
    return _weights_via_pipeline(
        STOCK_LOWVOL_MOMENTUM,
        rows,
        asof,
        limits=limits,
        params=params,
        market_by_symbol=market_by_symbol,
        suspended=suspended,
    )


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
    return _weights_via_pipeline(
        ETF_MA_MOMENTUM_FILTER,
        rows,
        asof,
        limits=limits,
        params=params,
        market_by_symbol=market_by_symbol,
        suspended=suspended,
    )


def signal_stock_short_reversal_topk(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    """Stock universe: rank by short-term reversal (negative recent return) TopK."""
    return _weights_via_pipeline(
        STOCK_SHORT_REVERSAL_TOPK,
        rows,
        asof,
        limits=limits,
        params=params,
        market_by_symbol=market_by_symbol,
        suspended=suspended,
    )


def signal_stock_momentum_volume_confirm(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    """Stock universe: require volume_z >= min, then rank by momentum TopK."""
    return _weights_via_pipeline(
        STOCK_MOMENTUM_VOLUME_CONFIRM,
        rows,
        asof,
        limits=limits,
        params=params,
        market_by_symbol=market_by_symbol,
        suspended=suspended,
    )


def signal_stock_momentum_skip_month(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
) -> dict[str, float]:
    """Stock universe: rank by skip-month momentum (e.g. 12-1) TopK."""
    return _weights_via_pipeline(
        STOCK_MOMENTUM_SKIP_MONTH,
        rows,
        asof,
        limits=limits,
        params=params,
        market_by_symbol=market_by_symbol,
        suspended=suspended,
    )


def signal_stock_holder_increase_follow(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
    events: list[dict[str, Any]] | None = None,
    settings: Any | None = None,
) -> dict[str, float]:
    """Stock universe: near-N-day net holder increase hit + optional momentum filter."""
    return _weights_via_pipeline(
        STOCK_HOLDER_INCREASE_FOLLOW,
        rows,
        asof,
        limits=limits,
        params=params,
        market_by_symbol=market_by_symbol,
        suspended=suspended,
        events=events,
        settings=settings,
    )


def factor_rows(
    strategy_id: str,
    rows: list[dict[str, Any]],
    asof: str,
    *,
    source_run_id: str,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    events: list[dict[str, Any]] | None = None,
    settings: Any | None = None,
) -> list[dict[str, Any]]:
    grouped = market_by_symbol if market_by_symbol is not None else _by_symbol(rows)
    if strategy_id not in STRATEGY_SPECS:
        return []
    return compute_factor_frame(
        grouped,
        factor_specs_for(strategy_id, params, events=events, settings=settings),
        asof=asof,
        source_run_id=source_run_id,
        model_version=CODE_VERSION,
    )


def weights_for(strategy_id: str, rows: list[dict[str, Any]], asof: str, **kwargs: Any) -> dict[str, float]:
    if strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    return _weights_via_pipeline(strategy_id, rows, asof, **kwargs)

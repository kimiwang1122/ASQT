"""P2/P2.4 strategies: MA rotate, momentum/reversal TopK, low-vol, volume confirm, skip-month, holder events, 2560, yin arb."""

from __future__ import annotations

from typing import Any

from asqt.factor_pipeline import build_data_frame, compute_factor_frame, series_asof
from asqt.selectors import _is_suspended, clip_weights, select_targets

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
STOCK_2560 = "stock_2560"
STOCK_YIN_ARB = "stock_yin_arb"

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
    STOCK_2560: {
        "kind": "topk",
        "instrument_type": "stock",
        "parameter_set_id": "stock_2560.k10.f5.s20.vf5.vs90.b30.sl8.tp20",
        "params": {
            "ma_fast": 5,
            "ma_slow": 20,
            "vol_fast": 5,
            "vol_slow": 90,
            "pullback_band": 0.03,
            "top_k": 10,
            "max_weight": 0.10,
            "gross_limit": 0.95,
            "stop_loss": 0.08,
            "take_profit": 0.20,
        },
    },
    STOCK_YIN_ARB: {
        "kind": "topk",
        "instrument_type": "stock",
        "parameter_set_id": "stock_yin_arb.k10.f10.s20.bl5.br180.b25.mg30",
        "params": {
            "ma_fast": 10,
            "ma_slow": 20,
            "burst_lookback": 5,
            "burst_ratio": 1.8,
            "pullback_band": 0.025,
            "min_body": 0.005,
            "ma_gap_max": 0.03,
            "top_k": 10,
            "max_weight": 0.10,
            "gross_limit": 0.95,
            "stop_loss": 0.0,
            "take_profit": 0.0,
        },
    },
}

STRATEGY_LABEL = {
    ETF_MA_ROTATE: "ETF 均线轮动",
    STOCK_MOMENTUM_TOPK: "股票动量 TopK",
    ETF_MOMENTUM_TOPK: "ETF 动量 TopK",
    STOCK_LOWVOL_MOMENTUM: "股票低波动量",
    ETF_MA_MOMENTUM_FILTER: "ETF 均线动量过滤",
    STOCK_SHORT_REVERSAL_TOPK: "股票短反转 TopK",
    STOCK_MOMENTUM_VOLUME_CONFIRM: "股票动量量能确认",
    STOCK_MOMENTUM_SKIP_MONTH: "股票跳月动量",
    STOCK_HOLDER_INCREASE_FOLLOW: "股票股东增持跟随",
    STOCK_2560: "股票2560战法",
    STOCK_YIN_ARB: "股票阴线套利",
}

# (id(grouped), ma/vol params) → (timelines, asof_index). Prefix grouped (tests) misses cache; paper reuses.
_2560_TL_CACHE: dict[tuple[Any, ...], tuple[dict[str, list], dict[str, dict[str, int]]]] = {}
# id(events list) → HolderEventIndex. 复盘逐日 weights 必须复用，否则每天重建 17 万行索引。
_HOLDER_INDEX_CACHE: tuple[int, Any] | None = None


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


def pin_strategy_params(
    strategy_id: str,
    params: dict[str, Any],
    *,
    parameter_set_id: str | None = None,
    settings: Any | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Lab: rewrite in-process STRATEGY_SPECS pin (+ optional strategy_version row).

    Overwrites papered pins intentionally; callers should keep experiment reports.
    """
    if strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    merged = _merged_params(strategy_id, params)
    from asqt.tune import suggest_parameter_set_id

    psid = parameter_set_id or suggest_parameter_set_id(strategy_id, merged)
    STRATEGY_SPECS[strategy_id]["params"] = merged
    STRATEGY_SPECS[strategy_id]["parameter_set_id"] = psid
    if persist:
        from asqt.config import ensure_runtime_dirs, get_settings
        from asqt.db import execute, initialize_database

        cfg = ensure_runtime_dirs(settings or get_settings())
        initialize_database(cfg)
        execute(
            """
            UPDATE strategy_version
            SET parameter_set_id = ?
            WHERE strategy_id = ? AND version = 'v1'
            """,
            (psid, strategy_id),
            settings=cfg,
        )
    return {"strategy_id": strategy_id, "parameter_set_id": psid, "params": merged}


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

        global _HOLDER_INDEX_CACHE
        event_lookback = int(spec["event_lookback"])
        lookback = int(spec["lookback"])
        # Index once: raw 17万行线性扫在全窗因子任务里会卡数十分钟。
        if events is not None:
            cache_key = id(events)
            hit = _HOLDER_INDEX_CACHE
            if hit is not None and hit[0] == cache_key:
                event_index = hit[1]
            else:
                event_index = build_holder_event_index(events)
                _HOLDER_INDEX_CACHE = (cache_key, event_index)
        else:
            event_index = build_holder_event_index(_resolve_events(None, settings=settings))

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
    if strategy_id == STOCK_YIN_ARB:
        kw = {
            "ma_fast": int(spec["ma_fast"]),
            "ma_slow": int(spec["ma_slow"]),
            "burst_lookback": int(spec["burst_lookback"]),
            "burst_ratio": float(spec["burst_ratio"]),
            "pullback_band": float(spec["pullback_band"]),
            "min_body": float(spec["min_body"]),
            "ma_gap_max": float(spec["ma_gap_max"]),
        }
        return [
            {
                "name": "stock_yin_arb",
                "instrument_type": "stock",
                "kind": "rule_yin_arb",
                "kwargs": kw,
                "params_for_hash": kw,
            }
        ]
    if strategy_id == STOCK_2560:
        ma_fast = int(spec["ma_fast"])
        ma_slow = int(spec["ma_slow"])
        vol_fast = int(spec["vol_fast"])
        vol_slow = int(spec["vol_slow"])
        pullback_band = float(spec["pullback_band"])
        return [
            {
                "name": "stock_2560",
                "instrument_type": "stock",
                "kind": "rule_2560",
                "kwargs": {
                    "ma_fast": ma_fast,
                    "ma_slow": ma_slow,
                    "vol_fast": vol_fast,
                    "vol_slow": vol_slow,
                    "pullback_band": pullback_band,
                },
                "params_for_hash": {
                    "ma_fast": ma_fast,
                    "ma_slow": ma_slow,
                    "vol_fast": vol_fast,
                    "vol_slow": vol_slow,
                    "pullback_band": pullback_band,
                },
            }
        ]
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
    if strategy_id == STOCK_2560:
        return {
            **base,
            "score_factor": "stock_2560",
            "filters": [],
            "top_k": int(spec["top_k"]),
        }
    if strategy_id == STOCK_YIN_ARB:
        return {
            **base,
            "score_factor": "stock_yin_arb",
            "filters": [],
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
    held_symbols: list[str] | None = None,
) -> dict[str, float]:
    if strategy_id == STOCK_2560:
        return _weights_stock_2560(
            rows,
            asof,
            limits=limits,
            params=params,
            market_by_symbol=market_by_symbol,
            suspended=suspended,
            held_symbols=held_symbols,
        )
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


def _weights_stock_2560(
    rows: list[dict[str, Any]],
    asof: str,
    *,
    limits: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    market_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    suspended: set[tuple[str, str]] | None = None,
    held_symbols: list[str] | None = None,
) -> dict[str, float]:
    """Sticky 2560: keep prior names until exit; fill free slots from new entries only."""
    from asqt.factors import rule_2560_timeline

    spec = _merged_params(STOCK_2560, params)
    top_k = int(spec["top_k"])
    max_weight = float(spec["max_weight"])
    gross_limit = float(spec["gross_limit"])
    ma_fast = int(spec["ma_fast"])
    ma_slow = int(spec["ma_slow"])
    vol_fast = int(spec["vol_fast"])
    vol_slow = int(spec["vol_slow"])
    pullback_band = float(spec["pullback_band"])
    grouped = market_by_symbol if market_by_symbol is not None else _by_symbol(rows)
    tl_key = (id(grouped), ma_fast, ma_slow, vol_fast, vol_slow, round(pullback_band, 6))
    packed = _2560_TL_CACHE.get(tl_key)
    if packed is None:
        timelines: dict[str, list] = {}
        asof_index: dict[str, dict[str, int]] = {}
        for symbol, series in grouped.items():
            timelines[symbol] = rule_2560_timeline(
                series,
                ma_fast=ma_fast,
                ma_slow=ma_slow,
                vol_fast=vol_fast,
                vol_slow=vol_slow,
                pullback_band=pullback_band,
            )
            asof_index[symbol] = {str(row["trade_date"]): i for i, row in enumerate(series)}
        packed = (timelines, asof_index)
        if len(_2560_TL_CACHE) >= 8:
            _2560_TL_CACHE.clear()
        _2560_TL_CACHE[tl_key] = packed
    timelines, asof_index = packed
    states: dict[str, tuple[str, float]] = {}
    for symbol, index_map in asof_index.items():
        if _is_suspended(symbol, asof, limits=limits, suspended=suspended):
            continue
        idx = index_map.get(str(asof))
        if idx is None:
            continue
        state = timelines[symbol][idx]
        if state is not None:
            states[symbol] = state
    keep: list[str] = []
    for symbol in held_symbols or []:
        if symbol in states and symbol not in keep:
            keep.append(symbol)
        if len(keep) >= top_k:
            break
    slots = top_k - len(keep)
    entries = sorted(
        (
            (score, symbol)
            for symbol, (phase, score) in states.items()
            if phase == "entry" and symbol not in keep
        ),
        reverse=True,
    )
    if not keep and slots == top_k:
        # cold start: TopK among anything currently in a trade (entry or hist-hold)
        ranked = sorted(((score, symbol) for symbol, (_phase, score) in states.items()), reverse=True)
        picked = [symbol for _score, symbol in ranked[:top_k]]
    else:
        picked = keep + [symbol for _score, symbol in entries[:slots]]
    if not picked:
        return {}
    weight = 1.0 / len(picked)
    return clip_weights({symbol: weight for symbol in picked}, max_weight, gross_limit)


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

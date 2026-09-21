"""Paper lab params: solo runs may override; multi/parallel always use defaults."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import execute, initialize_database
from asqt.ops import _setting_value
from asqt.strategies import STRATEGY_SPECS, pin_strategy_params
from asqt.tune import stock_2560_short_id, suggest_parameter_set_id

PAPER_LAB_DEFAULTS_KEY = "paper.lab_defaults"
PAPER_LAB_PRESETS_KEY = "paper.lab_presets"

# Solo-run presets for the ETF MA momentum lab grid (+ reviewed default).
ETF_MA_MOMENTUM_PRESETS: list[dict[str, Any]] = [
    {"ma_window": mw, "mom_lookback": mw, "top_k": k, "max_weight": 0.20, "gross_limit": 0.95}
    for mw in (10, 20, 40)
    for k in (3, 4, 5)
]

# 2560 lab picks from feasible grid (name_cap ≤10%): max-return / stable-OOS / classic.
STOCK_2560_PRESETS: list[dict[str, Any]] = [
    {  # 可行网格收益最高
        "ma_fast": 5,
        "ma_slow": 20,
        "vol_fast": 5,
        "vol_slow": 90,
        "pullback_band": 0.03,
        "top_k": 10,
        "max_weight": 0.10,
        "gross_limit": 0.95,
    },
    {  # OOS 更平（回测样本外接近持平）
        "ma_fast": 5,
        "ma_slow": 25,
        "vol_fast": 5,
        "vol_slow": 90,
        "pullback_band": 0.02,
        "top_k": 8,
        "max_weight": 0.10,
        "gross_limit": 0.95,
    },
    {  # 可行网格第二
        "ma_fast": 5,
        "ma_slow": 20,
        "vol_fast": 5,
        "vol_slow": 90,
        "pullback_band": 0.03,
        "top_k": 8,
        "max_weight": 0.10,
        "gross_limit": 0.95,
    },
    {  # 经典默认（调参前）
        "ma_fast": 5,
        "ma_slow": 25,
        "vol_fast": 5,
        "vol_slow": 60,
        "pullback_band": 0.02,
        "top_k": 5,
        "max_weight": 0.10,
        "gross_limit": 0.95,
    },
    # paper-matched SL/TP grid (2018-01-02→2026-09-18, live held, whole-order reject)
    {
        "ma_fast": 5,
        "ma_slow": 20,
        "vol_fast": 5,
        "vol_slow": 90,
        "pullback_band": 0.03,
        "top_k": 8,
        "max_weight": 0.10,
        "gross_limit": 0.95,
        "stop_loss": 0.08,
        "take_profit": 0.0,
    },
    {
        "ma_fast": 5,
        "ma_slow": 25,
        "vol_fast": 5,
        "vol_slow": 90,
        "pullback_band": 0.02,
        "top_k": 8,
        "max_weight": 0.10,
        "gross_limit": 0.95,
        "stop_loss": 0.04,
        "take_profit": 0.20,
    },
    {
        "ma_fast": 5,
        "ma_slow": 20,
        "vol_fast": 5,
        "vol_slow": 90,
        "pullback_band": 0.03,
        "top_k": 10,
        "max_weight": 0.10,
        "gross_limit": 0.95,
        "stop_loss": 0.08,
        "take_profit": 0.0,
    },
    {
        "ma_fast": 5,
        "ma_slow": 20,
        "vol_fast": 5,
        "vol_slow": 90,
        "pullback_band": 0.03,
        "top_k": 8,
        "max_weight": 0.10,
        "gross_limit": 0.95,
        "stop_loss": 0.06,
        "take_profit": 0.0,
    },
    {
        "ma_fast": 5,
        "ma_slow": 25,
        "vol_fast": 5,
        "vol_slow": 90,
        "pullback_band": 0.02,
        "top_k": 8,
        "max_weight": 0.10,
        "gross_limit": 0.95,
        "stop_loss": 0.08,
        "take_profit": 0.30,
    },
]


def code_default_pin(strategy_id: str) -> dict[str, Any]:
    if strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    spec = STRATEGY_SPECS[strategy_id]
    params = dict(spec["params"])
    return {
        "strategy_id": strategy_id,
        "parameter_set_id": str(spec["parameter_set_id"]),
        "params": params,
        "source": "code",
    }


def load_lab_defaults(*, settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    """Per-strategy default pins: runtime override wins over STRATEGY_SPECS."""
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    out = {sid: code_default_pin(sid) for sid in STRATEGY_SPECS}
    raw = _setting_value(PAPER_LAB_DEFAULTS_KEY, "{}", settings)
    try:
        stored = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        stored = {}
    if not isinstance(stored, dict):
        return out
    for sid, item in stored.items():
        if sid not in STRATEGY_SPECS or not isinstance(item, dict):
            continue
        params = dict(STRATEGY_SPECS[sid]["params"])
        if isinstance(item.get("params"), dict):
            params.update(item["params"])
        # ID is derived from params so a suffix change (e.g. sl/tp) still matches presets.
        psid = suggest_parameter_set_id(sid, params)
        out[sid] = {
            "strategy_id": sid,
            "parameter_set_id": psid,
            "params": params,
            "source": "lab_default",
        }
    return out


def set_lab_default(
    strategy_id: str,
    params: dict[str, Any],
    *,
    parameter_set_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    if strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    merged = dict(STRATEGY_SPECS[strategy_id]["params"])
    merged.update(params or {})
    psid = parameter_set_id or suggest_parameter_set_id(strategy_id, merged)
    current = {}
    raw = _setting_value(PAPER_LAB_DEFAULTS_KEY, "{}", settings)
    try:
        stored = json.loads(raw) if raw else {}
        if isinstance(stored, dict):
            current = stored
    except json.JSONDecodeError:
        current = {}
    current[strategy_id] = {"parameter_set_id": psid, "params": merged}
    _write_json_setting(PAPER_LAB_DEFAULTS_KEY, current, settings=settings)
    return {
        "strategy_id": strategy_id,
        "parameter_set_id": psid,
        "params": merged,
        "source": "lab_default",
    }


def _read_json_setting(key: str, settings: Settings) -> dict[str, Any]:
    raw = _setting_value(key, "{}", settings)
    try:
        stored = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        stored = {}
    return stored if isinstance(stored, dict) else {}


def _write_json_setting(key: str, value: dict[str, Any], *, settings: Settings) -> None:
    execute(
        """
        INSERT INTO runtime_setting (setting_key, setting_value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(setting_key) DO UPDATE SET
          setting_value = excluded.setting_value,
          updated_at = excluded.updated_at
        """,
        (key, json.dumps(value, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        settings=settings,
    )


def param_schema(strategy_id: str) -> list[dict[str, Any]]:
    if strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    fields = []
    for key, value in STRATEGY_SPECS[strategy_id]["params"].items():
        if isinstance(value, bool):
            kind = "bool"
        elif isinstance(value, int) and not isinstance(value, bool):
            kind = "integer"
        else:
            kind = "number"
        fields.append({"key": key, "default": value, "kind": kind})
    return fields


def coerce_params(strategy_id: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    if strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    spec = dict(STRATEGY_SPECS[strategy_id]["params"])
    incoming = raw or {}
    unknown = sorted(str(key) for key in incoming if key not in spec)
    if unknown:
        raise ValueError(f"未知参数: {', '.join(unknown)}")
    out = dict(spec)
    for key, default in spec.items():
        if key not in incoming:
            continue
        val = incoming[key]
        try:
            if isinstance(default, bool):
                out[key] = bool(val)
            elif isinstance(default, int) and not isinstance(default, bool):
                out[key] = int(float(val))
            else:
                out[key] = float(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"参数 {key} 无效") from exc
    return out


def builtin_presets(strategy_id: str) -> list[dict[str, Any]]:
    if strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    pin = code_default_pin(strategy_id)
    rows.append({"parameter_set_id": pin["parameter_set_id"], "params": pin["params"], "source": "builtin"})
    seen.add(pin["parameter_set_id"])
    if strategy_id == "etf_ma_momentum_filter":
        extra = ETF_MA_MOMENTUM_PRESETS
    elif strategy_id == "stock_2560":
        extra = STOCK_2560_PRESETS
    else:
        extra = []
    for params in extra:
        merged = dict(STRATEGY_SPECS[strategy_id]["params"])
        merged.update(params)
        psid = suggest_parameter_set_id(strategy_id, merged)
        if psid in seen:
            continue
        seen.add(psid)
        rows.append({"parameter_set_id": psid, "params": merged, "source": "builtin"})
    return rows


def presets_for(strategy_id: str, *, settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    by_id = {row["parameter_set_id"]: dict(row) for row in builtin_presets(strategy_id)}
    stored = _read_json_setting(PAPER_LAB_PRESETS_KEY, settings).get(strategy_id) or []
    if isinstance(stored, list):
        for item in stored:
            if not isinstance(item, dict) or not item.get("parameter_set_id"):
                continue
            params = coerce_params(strategy_id, item.get("params") if isinstance(item.get("params"), dict) else {})
            psid = str(item["parameter_set_id"])
            by_id[psid] = {"parameter_set_id": psid, "params": params, "source": "custom"}
    defaults = load_lab_defaults(settings=settings).get(strategy_id) or {}
    default_id = str(defaults.get("parameter_set_id") or "")
    out = []
    for row in by_id.values():
        item = dict(row)
        item["editable"] = item.get("source") == "custom"
        item["is_default"] = item["parameter_set_id"] == default_id
        if strategy_id == "stock_2560":
            item["short_id"] = stock_2560_short_id(item["params"])
        else:
            item["short_id"] = item["parameter_set_id"]
        out.append(item)
    out.sort(key=lambda row: (0 if row.get("is_default") else 1, row["parameter_set_id"]))
    return out


def upsert_preset(
    strategy_id: str,
    params: dict[str, Any],
    *,
    replace_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    merged = coerce_params(strategy_id, params)
    psid = suggest_parameter_set_id(strategy_id, merged)
    store = _read_json_setting(PAPER_LAB_PRESETS_KEY, settings)
    rows = [item for item in (store.get(strategy_id) or []) if isinstance(item, dict)]
    drop = {str(replace_id or ""), psid}
    kept = [item for item in rows if str(item.get("parameter_set_id") or "") not in drop]
    kept.append({"parameter_set_id": psid, "params": merged})
    store[strategy_id] = kept
    _write_json_setting(PAPER_LAB_PRESETS_KEY, store, settings=settings)
    return {"strategy_id": strategy_id, "parameter_set_id": psid, "params": merged, "source": "custom", "editable": True}


def delete_preset(
    strategy_id: str,
    parameter_set_id: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    psid = str(parameter_set_id or "").strip()
    if not psid:
        raise ValueError("parameter_set_id is required")
    store = _read_json_setting(PAPER_LAB_PRESETS_KEY, settings)
    rows = [item for item in (store.get(strategy_id) or []) if isinstance(item, dict)]
    kept = [item for item in rows if str(item.get("parameter_set_id") or "") != psid]
    if len(kept) == len(rows):
        builtin_ids = {row["parameter_set_id"] for row in builtin_presets(strategy_id)}
        if psid in builtin_ids:
            raise ValueError("内置参数组不能删除")
        raise ValueError("参数组不存在")
    store[strategy_id] = kept
    _write_json_setting(PAPER_LAB_PRESETS_KEY, store, settings=settings)
    return {"ok": True, "strategy_id": strategy_id, "deleted": psid}


def resolve_run_pins(
    strategy_ids: list[str],
    *,
    mode: str = "sequential",
    lab_params: dict[str, Any] | None = None,
    parameter_set_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Decide which pins apply. Lab override only for solo sequential."""
    settings = ensure_runtime_dirs(settings or get_settings())
    ids = list(strategy_ids)
    if not ids:
        raise ValueError("paper run requires at least one strategy")
    mode_norm = str(mode or "sequential").strip().lower()
    solo = len(ids) == 1 and mode_norm != "parallel"
    defaults = load_lab_defaults(settings=settings)
    if lab_params is not None or parameter_set_id:
        if not solo:
            raise ValueError("实验室改参仅支持单策略顺序模拟；多策略或并行只能使用默认参数组")
        sid = ids[0]
        base = dict(defaults[sid]["params"])
        if lab_params:
            base.update(lab_params)
        # Keep mom_lookback tied to ma_window for this strategy when omitted.
        if sid == "etf_ma_momentum_filter" and "ma_window" in base and "mom_lookback" not in (lab_params or {}):
            base["mom_lookback"] = int(base["ma_window"])
        psid = parameter_set_id or suggest_parameter_set_id(sid, base)
        return {
            "mode": "lab_override",
            "solo": True,
            "pins": {sid: {"parameter_set_id": psid, "params": base}},
        }
    return {
        "mode": "defaults",
        "solo": solo,
        "pins": {
            sid: {
                "parameter_set_id": defaults[sid]["parameter_set_id"],
                "params": dict(defaults[sid]["params"]),
            }
            for sid in ids
            if sid in defaults
        },
    }


def apply_run_pins(
    strategy_ids: list[str],
    *,
    mode: str = "sequential",
    lab_params: dict[str, Any] | None = None,
    parameter_set_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Pin STRATEGY_SPECS (+ DB) before a paper run."""
    settings = ensure_runtime_dirs(settings or get_settings())
    plan = resolve_run_pins(
        strategy_ids,
        mode=mode,
        lab_params=lab_params,
        parameter_set_id=parameter_set_id,
        settings=settings,
    )
    applied = []
    for sid, pin in plan["pins"].items():
        applied.append(
            pin_strategy_params(
                sid,
                pin["params"],
                parameter_set_id=pin["parameter_set_id"],
                settings=settings,
                persist=True,
            )
        )
    plan["applied"] = applied
    return plan

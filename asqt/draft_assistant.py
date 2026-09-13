"""Draft research assistant: read-only analysis, never emits target positions.

GATE-E2: lifecycle stays draft; outputs go to ``decision_log`` with
``source=draft_assistant``. Optional ``llm_fn`` hook; default is a deterministic
rule heuristic so tests need no API key.
"""

from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

from asqt.config import Settings, get_settings
from asqt.db import initialize_database, query_all
from asqt.decision import RATING_REVIEW, decision_from_targets, rating_or_review, weight_to_rating
from asqt.decision_log import record_pending
from asqt.pit import parse_asof
from asqt.reporting import write_run_tree
from asqt.storage import read_market_daily, read_market_snapshot


class DraftWriteForbidden(PermissionError):
    """Raised if a caller tries to route draft-assist into orderable paths."""


def _rule_heuristic(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Map simple return to a portfolio rating without any LLM."""
    if len(bars) < 2:
        return {
            "rating": RATING_REVIEW,
            "action": RATING_REVIEW,
            "weights": {},
            "note": "insufficient bars",
        }
    first = float(bars[0].get("close") or 0)
    last = float(bars[-1].get("close") or 0)
    if first <= 0:
        return {"rating": RATING_REVIEW, "action": RATING_REVIEW, "weights": {}, "note": "bad price"}
    ret = last / first - 1.0
    # Pseudo single-name weight for rating map only — not a target position.
    pseudo_w = max(-0.3, min(0.3, ret))
    rating = weight_to_rating(pseudo_w)
    summary = decision_from_targets({"_probe": pseudo_w})
    return {
        "rating": rating_or_review(rating),
        "action": summary["action"],
        "weights": {},
        "session_return": ret,
        "note": "rule_heuristic",
    }


def analyze_readonly(
    *,
    asof: str,
    symbols: list[str] | None = None,
    strategy_id: str | None = None,
    llm_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Read market data asof and produce a draft decision (no target_position writes)."""
    settings = settings or get_settings()
    initialize_database(settings)
    asof_s = parse_asof(asof)
    syms = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    if not syms:
        snap = read_market_snapshot(asof=asof_s, limit=5, settings=settings)
        syms = [str(item["symbol"]) for item in snap.get("items") or []][:3]

    if strategy_id:
        versions = query_all(
            "SELECT status FROM strategy_version WHERE strategy_id = ? ORDER BY created_at DESC LIMIT 1",
            (strategy_id,),
            settings=settings,
        )
        if versions and str(versions[0].get("status") or "") not in {"draft", "backtest", "candidate", "failed"}:
            raise DraftWriteForbidden(
                f"draft-assist only for research lifecycles; {strategy_id} is {versions[0].get('status')}"
            )

    per_symbol: list[dict[str, Any]] = []
    for symbol in syms:
        bars = read_market_daily(symbol=symbol, end=asof_s, settings=settings, limit=30, newest_first=False)
        bars = [row for row in bars if str(row.get("trade_date")) <= asof_s]
        context = {"symbol": symbol, "asof": asof_s, "bars": bars[-20:]}
        if llm_fn is not None:
            raw = llm_fn(context)
            rating = rating_or_review(raw.get("rating") if isinstance(raw, dict) else None)
            call = {
                "symbol": symbol,
                "rating": rating,
                "action": rating,
                "note": "llm_fn",
                "raw": raw if isinstance(raw, dict) else {"text": str(raw)},
            }
        else:
            call = {"symbol": symbol, **_rule_heuristic(bars)}
        per_symbol.append(call)

    # Aggregate: REVIEW if any REVIEW, else majority-ish via empty weights + notes
    ratings = [item.get("rating") for item in per_symbol]
    if not ratings or RATING_REVIEW in ratings:
        portfolio_rating = RATING_REVIEW
    else:
        portfolio_rating = ratings[0]
    thesis_weights: dict[str, float] = {}
    decision = record_pending(
        strategy_id=strategy_id or "draft_assistant",
        signal_date=asof_s,
        weights=thesis_weights,
        strategy_version="draft",
        data_version=f"draft-{asof_s}",
        settings=settings,
    )
    # Enrich thesis with assistant payload (update via re-record keeps id when pending)
    from asqt.db import execute
    import json

    thesis = {
        "source": "draft_assistant",
        "asof": asof_s,
        "symbols": syms,
        "portfolio_rating": portfolio_rating,
        "per_symbol": per_symbol,
        "writable": False,
        "weights": {},
    }
    execute(
        """
        UPDATE decision_log
        SET rating = ?, action = ?, thesis_json = ?
        WHERE decision_id = ?
        """,
        (portfolio_rating, portfolio_rating, json.dumps(thesis, ensure_ascii=False, default=str), decision["decision_id"]),
        settings=settings,
    )

    run_id = str(uuid4())
    # Guardrail: this module never writes target_position / orders.
    summary = {
        "ok": True,
        "kind": "draft",
        "asof": asof_s,
        "strategy_id": strategy_id or "draft_assistant",
        "decision_id": decision["decision_id"],
        "portfolio_rating": portfolio_rating,
        "symbols": syms,
        "writable": False,
        "emits_targets": False,
        "per_symbol": per_symbol,
    }
    path = write_run_tree(
        "draft",
        run_id,
        summary,
        settings=settings,
        strategy_id=strategy_id or "draft_assistant",
        write_legacy_latest=False,
    )
    summary["experiment_path"] = str(path)
    summary["decision"] = {
        "decision_id": decision["decision_id"],
        "status": "pending",
        "rating": portfolio_rating,
    }
    return summary

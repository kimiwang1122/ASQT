"""GATE-D2: provider_registry priority / optional / fallback chain."""

from __future__ import annotations

from asqt.pipeline import resolve_adapters
from asqt.provider_registry import (
    PROVIDER_REGISTRY,
    fetch_with_fallback,
    list_providers,
    providers_for,
    resolve_provider_chain,
)


def test_gate_d2_priority_and_optional_ordering():
    daily = list_providers(schema="market_daily")
    assert [row["source_id"] for row in daily] == ["baostock", "tushare", "akshare"]
    assert daily[0]["optional"] is False
    assert daily[0]["priority"] == 10
    assert all(row["optional"] for row in daily[1:])

    required_only = providers_for("market_daily", include_optional=False)
    assert required_only == ["baostock"]

    events = providers_for("market_event")
    assert events == ["tushare"]


def test_gate_d2_resolve_chain_preferred_and_fallback():
    chain = resolve_provider_chain("market_daily", preferred="akshare")
    assert chain[0]["source_id"] == "akshare"
    assert [row["source_id"] for row in chain[1:]] == ["baostock", "tushare"]

    calls: list[str] = []

    def fetch(source_id: str) -> str:
        calls.append(source_id)
        if source_id == "baostock":
            raise RuntimeError("primary down")
        return f"ok:{source_id}"

    outcome = fetch_with_fallback("market_daily", fetch)
    assert outcome["ok"] is True
    assert outcome["source_id"] == "tushare"
    assert outcome["fallback_from"] == "baostock"
    assert outcome["tried"] == ["baostock", "tushare"]
    assert outcome["result"] == "ok:tushare"

    adapters = resolve_adapters("market_event")
    assert len(adapters) == 1
    assert adapters[0]["source_id"] == "tushare"
    assert adapters[0]["adapter"].source_id == "tushare"


def test_gate_d2_expand_schema_by_declaration_only():
    """New schema capability is registry declaration — providers_for picks it up."""
    original = dict(PROVIDER_REGISTRY["baostock"])
    try:
        PROVIDER_REGISTRY["baostock"] = {
            **original,
            "provides": tuple(original["provides"]) + ("demo_schema",),
        }
        assert providers_for("demo_schema") == ["baostock"]
        assert "demo_schema" not in providers_for("market_event")
    finally:
        PROVIDER_REGISTRY["baostock"] = original

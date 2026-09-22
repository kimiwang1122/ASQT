"""GATE-A3: symbol normalize / BJ / vendor round-trip."""

from __future__ import annotations

import pytest

from asqt.symbols import (
    from_vendor_code,
    infer_board,
    infer_instrument_type,
    infer_market_from_code,
    limit_pct,
    normalize_symbol,
    to_vendor_code,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("000001.SZ", "000001.SZ"),
        ("000001.sz", "000001.SZ"),
        ("sz.000001", "000001.SZ"),
        ("600000.SH", "600000.SH"),
        ("sh.600000", "600000.SH"),
        ("000001", "000001.SZ"),
        ("600519", "600519.SH"),
        ("300750", "300750.SZ"),
        ("920000.BJ", "920000.BJ"),
        ("bj.920000", "920000.BJ"),
        ("830799", "830799.BJ"),
    ],
)
def test_gate_a3_normalize_matrix(raw, expected):
    assert normalize_symbol(raw) == expected


@pytest.mark.parametrize("bad", [None, "", "   ", "00001", "000001.XX", "xx.000001", "ABCDEF"])
def test_gate_a3_normalize_rejects_invalid(bad):
    with pytest.raises(ValueError):
        normalize_symbol(bad)


def test_gate_a3_vendor_roundtrip_incl_bj():
    assert to_vendor_code("000001.SZ") == "sz.000001"
    assert to_vendor_code("600000.SH") == "sh.600000"
    assert to_vendor_code("920000.BJ") == "bj.920000"
    assert from_vendor_code("bj.920000") == "920000.BJ"


def test_gate_a3_board_and_limit_for_bj():
    assert infer_board("920000.BJ") == "bse"
    assert limit_pct("920000.BJ") == 0.30
    assert infer_board("302132.SZ") == "chinext"
    assert limit_pct("302132.SZ") == 0.20
    assert infer_instrument_type("510300.SH") == "etf"
    assert infer_market_from_code("000001") == "SZ"

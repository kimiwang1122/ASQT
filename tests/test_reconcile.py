from __future__ import annotations

from asqt.pipeline import reconcile_daily
from asqt.reconcile import collapse_adj_scale_mismatches, compare_market_daily, scan_silent_factor_jumps
from tests.test_p1_data import FakeAdapter, _bar, make_settings


def test_collapse_adj_scale_mismatches_one_row_per_symbol():
    mismatches = [
        {
            "symbol": "000001.SZ",
            "trade_date": "2023-01-03",
            "stored_source": "baostock",
            "peer_source": "tushare",
            "diff": "adj_factor stored=102.38 peer=113.936 rel=0.1014",
        },
        {
            "symbol": "000001.SZ",
            "trade_date": "2023-01-04",
            "stored_source": "baostock",
            "peer_source": "tushare",
            "diff": "adj_factor stored=102.38 peer=113.936 rel=0.1014",
        },
        {
            "symbol": "000001.SZ",
            "trade_date": "2023-01-05",
            "stored_source": "baostock",
            "peer_source": "tushare",
            "diff": "close stored=10 peer=12 rel=0.166; adj_factor stored=1 peer=2 rel=0.5",
        },
    ]
    folded = collapse_adj_scale_mismatches(mismatches)
    assert len(folded) == 2
    close_hit = next(item for item in folded if "close stored=" in item["diff"])
    scale_hit = next(item for item in folded if item["diff"].startswith("adj_factor_scale"))
    assert close_hit["trade_date"] == "2023-01-05"
    assert scale_hit["symbol"] == "000001.SZ"
    assert "n=2" in scale_hit["diff"]
    assert "2023-01-03~2023-01-04" == scale_hit["trade_date"]


def test_compare_aligns_constant_adj_baseline():
    """Vendor baseline differs by a constant ratio → no mismatch after scale align."""
    scale = 124.911625 / 139.008
    stored = [
        {
            "symbol": "000001.SZ",
            "trade_date": f"2024-01-0{i}",
            "close": 10.0 + i * 0.01,
            "adj_factor": 124.911625,
            "source": "baostock",
        }
        for i in (2, 3, 4)
    ]
    peer = [
        {
            "symbol": "000001.SZ",
            "trade_date": f"2024-01-0{i}",
            "close": 10.0 + i * 0.01,
            "adj_factor": 139.008,
            "source": "tushare",
        }
        for i in (2, 3, 4)
    ]
    result = compare_market_daily(stored, peer)
    assert result["matched_rows"] == 3
    assert result["mismatch_count"] == 0
    assert result["adj_baseline_count"] == 1
    baseline = result["adj_baselines"][0]
    assert baseline["symbol"] == "000001.SZ"
    assert abs(baseline["scale"] - (124.911625 / 139.008)) < 1e-9
    assert abs(scale - baseline["scale"]) < 1e-9


def test_compare_flags_residual_adj_after_unstable_scale():
    stored = [
        {"symbol": "000001.SZ", "trade_date": "2024-01-02", "close": 10.0, "adj_factor": 1.0, "source": "baostock"},
        {"symbol": "000001.SZ", "trade_date": "2024-01-03", "close": 10.0, "adj_factor": 1.0, "source": "baostock"},
        {"symbol": "000001.SZ", "trade_date": "2024-01-04", "close": 10.0, "adj_factor": 2.0, "source": "baostock"},
    ]
    peer = [
        {"symbol": "000001.SZ", "trade_date": "2024-01-02", "close": 10.0, "adj_factor": 1.0, "source": "tushare"},
        {"symbol": "000001.SZ", "trade_date": "2024-01-03", "close": 10.0, "adj_factor": 1.05, "source": "tushare"},
        {"symbol": "000001.SZ", "trade_date": "2024-01-04", "close": 10.0, "adj_factor": 1.0, "source": "tushare"},
    ]
    result = compare_market_daily(stored, peer)
    assert result["mismatch_count"] >= 1
    assert any("adj_factor" in item["diff"] for item in result["mismatches"])
    # Unstable → not recorded as a clean baseline alignment.
    assert result["adj_baseline_count"] == 0


def test_compare_skips_adj_when_peer_missing_factor():
    stored = [{"symbol": "000001.SZ", "trade_date": "2024-01-02", "close": 10.0, "adj_factor": 1.2, "source": "baostock"}]
    peer = [{"symbol": "000001.SZ", "trade_date": "2024-01-02", "close": 10.0, "adj_factor": None, "source": "tushare"}]
    result = compare_market_daily(stored, peer)
    assert result["mismatch_count"] == 0


def test_compare_flags_close_mismatch_only():
    stored = [
        {"symbol": "000001.SZ", "trade_date": "2024-01-02", "close": 10.0, "adj_factor": 1.0, "source": "baostock"},
        {"symbol": "000001.SZ", "trade_date": "2024-01-03", "close": 10.1, "adj_factor": 1.0, "source": "baostock"},
    ]
    peer = [
        {"symbol": "000001.SZ", "trade_date": "2024-01-02", "close": 10.0, "adj_factor": 1.0, "source": "akshare"},
        {"symbol": "000001.SZ", "trade_date": "2024-01-03", "close": 12.0, "adj_factor": 1.0, "source": "akshare"},
    ]
    result = compare_market_daily(stored, peer)
    assert result["matched_rows"] == 2
    assert result["mismatch_count"] == 1
    assert result["mismatches"][0]["trade_date"] == "2024-01-03"


def test_silent_jump_alignment_without_event_table():
    rows = [
        {"symbol": "300015.SZ", "trade_date": "2023-06-07", "close": 26.05, "adj_factor": 1.0},
        {"symbol": "300015.SZ", "trade_date": "2023-06-08", "close": 19.80, "adj_factor": 1.305},
        {"symbol": "000001.SZ", "trade_date": "2024-10-08", "close": 10.0, "adj_factor": 1.0},
        {"symbol": "000001.SZ", "trade_date": "2024-10-09", "close": 8.0, "adj_factor": 1.0},
    ]
    result = scan_silent_factor_jumps(rows)
    assert result["consistent_count"] == 1
    assert result["consistent_ex_right"][0]["symbol"] == "300015.SZ"
    assert result["inconsistent_count"] == 0


def test_reconcile_pipeline_does_not_rewrite_parquet(tmp_path):
    settings = make_settings(tmp_path)
    stored_adapter = FakeAdapter(
        [
            _bar("000001.SZ", "2024-01-02", close=10),
            _bar("000001.SZ", "2024-01-03", close=10.2),
        ]
    )
    from asqt.pipeline import pull_daily

    pull_daily(["000001.SZ"], "2024-01-02", "2024-01-03", settings=settings, adapter=stored_adapter)
    peer = FakeAdapter(
        [
            _bar("000001.SZ", "2024-01-02", close=10),
            _bar("000001.SZ", "2024-01-03", close=10.21),
        ]
    )
    peer.source_id = "akshare"
    report = reconcile_daily(
        ["000001.SZ"],
        "2024-01-02",
        "2024-01-03",
        settings=settings,
        peer_adapter=peer,
    )
    assert report["comparison"]["matched_rows"] == 2
    assert report["comparison"]["mismatch_count"] == 0
    from asqt.storage import read_market_daily

    kept = read_market_daily(symbol="000001.SZ", settings=settings)
    assert all(row["source"] == "baostock" for row in kept)

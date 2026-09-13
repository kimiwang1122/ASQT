"""GATE-D4 reporting tree + GATE-D5 run signature."""

from __future__ import annotations

from pathlib import Path

import pytest

from asqt.db import initialize_database, query_all
from asqt.reporting import list_latest_experiments, run_dir, write_run_tree
from asqt.research_jobs import resume_backtest_job, start_backtest_job
from asqt.strategies import STOCK_MOMENTUM_TOPK
from asqt.versioning import SignatureMismatch, assert_run_signature, run_signature
from tests.test_p2_research import _seed, _trend_book, make_settings


def test_gate_d4_report_tree_layout(tmp_path: Path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    path = write_run_tree(
        "backtest",
        "run-abc",
        {
            "ok": True,
            "strategy_id": STOCK_MOMENTUM_TOPK,
            "parameter_set_id": "p1",
            "data_version": "dv1",
            "nav": 1.1,
        },
        settings=settings,
        strategy_id=STOCK_MOMENTUM_TOPK,
    )
    assert path.name == "summary.json"
    assert (run_dir("backtest", "run-abc", settings=settings) / "manifest.json").exists()
    assert (settings.experiment_dir / "latest" / "backtest" / f"{STOCK_MOMENTUM_TOPK}.json").exists()
    assert (settings.experiment_dir / f"latest-{STOCK_MOMENTUM_TOPK}.json").exists()

    write_run_tree(
        "paper",
        "paper-1",
        {"ok": True, "strategy_id": STOCK_MOMENTUM_TOPK, "days": 5},
        settings=settings,
        strategy_id=STOCK_MOMENTUM_TOPK,
        write_legacy_latest=False,
    )
    assert (settings.experiment_dir / "paper" / "paper-1" / "summary.json").exists()
    items = list_latest_experiments(settings=settings)
    assert any(item.get("strategy_id") == STOCK_MOMENTUM_TOPK for item in items)


def test_gate_d5_run_signature_stable_and_blocks_drift(tmp_path: Path):
    a = run_signature("paper", {"strategy_id": "s1", "days": 20, "mode": "sequential"})
    b = run_signature("paper", {"mode": "sequential", "days": 20, "strategy_id": "s1"})
    assert a == b
    c = run_signature("paper", {"strategy_id": "s1", "days": 21, "mode": "sequential"})
    assert a != c
    with pytest.raises(SignatureMismatch):
        assert_run_signature(a, c, run_id="r1")

    settings = make_settings(tmp_path)
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    job = start_backtest_job(STOCK_MOMENTUM_TOPK, settings=settings, background=False)
    assert job.get("run_signature")
    same = resume_backtest_job(job["run_id"], strategy_id=STOCK_MOMENTUM_TOPK, settings=settings)
    assert same["run_id"] == job["run_id"]
    with pytest.raises(SignatureMismatch):
        resume_backtest_job(
            job["run_id"],
            strategy_ids=[STOCK_MOMENTUM_TOPK, "etf_ma_rotate"],
            settings=settings,
        )


def test_gate_d5_signature_persisted_on_research_run(tmp_path: Path):
    settings = make_settings(tmp_path)
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    job = start_backtest_job(STOCK_MOMENTUM_TOPK, settings=settings, background=False)
    rows = query_all(
        "SELECT run_signature FROM research_run WHERE run_id = ?",
        (job["run_id"],),
        settings=settings,
    )
    assert rows and rows[0]["run_signature"] == job["run_signature"]

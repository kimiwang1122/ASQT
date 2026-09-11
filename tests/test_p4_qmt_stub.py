from __future__ import annotations

from pathlib import Path

import pytest

from asqt.adapters.qmt_broker import QmtExecutionAdapter
from asqt.paper import PaperBroker


def test_qmt_adapter_unavailable_without_vendor_sdk():
    adapter = QmtExecutionAdapter()
    status = adapter.channel_status()
    assert status["channel_id"] == "qmt"
    assert status["available"] is False
    assert status["reason"] == "q2_pending"
    with pytest.raises(RuntimeError, match="Q2"):
        adapter.submit({"order_id": "x"})
    with pytest.raises(RuntimeError, match="Q2"):
        adapter.cancel("x")
    with pytest.raises(RuntimeError, match="Q2"):
        adapter.query_order("x")


def test_default_execution_channel_remains_paper():
    assert PaperBroker().channel_id == "paper"


def test_asqt_tree_does_not_import_xtquant():
    root = Path(__file__).resolve().parents[1] / "asqt"
    hits = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "xtquant" in text or "xtquant.qmttools" in text:
            hits.append(str(path.relative_to(root.parent)))
    assert hits == []

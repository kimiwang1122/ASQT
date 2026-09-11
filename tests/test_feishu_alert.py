from __future__ import annotations

import json
from urllib.error import URLError

from asqt.adapters.feishu_alert import (
    DEFAULT_FEISHU_WEBHOOK,
    format_feishu_text,
    post_feishu_alert,
    should_push_feishu,
)
from asqt.ops import LocalAlertService
from tests.test_p3_paper import _prepare


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_feishu_formats_text_and_skips_info():
    row = {
        "level": "critical",
        "category": "kill_switch",
        "title": "kill switch on",
        "detail": "api halt",
    }
    text = format_feishu_text(row)
    assert "【ASQT告警】严重 · 急停" in text
    assert "急停已打开" in text
    assert "原因：api halt" in text
    assert should_push_feishu(row) is True
    assert should_push_feishu({"level": "info"}) is False


def test_post_feishu_alert_sends_msg_type_text(monkeypatch):
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=8, context=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse({"code": 0, "msg": "success", "StatusCode": 0})

    monkeypatch.setattr("asqt.adapters.feishu_alert.urllib.request.urlopen", fake_urlopen)
    result = post_feishu_alert(
        {"level": "high", "category": "ops", "title": "paper started", "detail": "p3"},
        webhook=DEFAULT_FEISHU_WEBHOOK,
    )
    assert result["ok"] is True
    assert captured["url"] == DEFAULT_FEISHU_WEBHOOK
    body = captured["body"]
    assert body["msg_type"] == "text"
    text = body["content"]["text"]
    assert "【ASQT告警】重要 · 运维" in text
    assert "事件：paper started" in text
    assert "说明：p3" in text


def test_feishu_drawdown_matches_console_template():
    from asqt.alert_format import build_drawdown_payload, encode_alert_detail, format_alert_full

    detail = encode_alert_detail(
        build_drawdown_payload(
            dd=-0.12,
            peak=100_000,
            total_asset=88_000,
            cash=8_000,
            market_value=80_000,
            initial_cash=100_000,
            account_id="paper:etf_ma_rotate",
            strategy_id="etf_ma_rotate",
            trade_date="2024-03-01",
            kind="stop",
        )
    )
    row = {
        "level": "critical",
        "category": "drawdown",
        "title": "max drawdown stop",
        "detail": detail,
    }
    full = format_alert_full(row)
    text = format_feishu_text(row)
    assert "账户峰值：100,000.00" in full
    assert "当前总资产：88,000.00" in full
    assert full in text
    assert "【ASQT告警】严重 · 回撤" in text


def test_feishu_reconcile_hides_absolute_report_path():
    from asqt.alert_format import encode_alert_detail, format_alert_full, format_feishu_text

    detail = encode_alert_detail(
        {
            "schema": "asqt.alert.v1",
            "kind": "cross_source_reconcile",
            "summary": "跨源对账待复核 · 差异 341",
            "report_path": "/Users/kimi/Documents/ChatGPT/ASQT/data/logs/reconcile_20260911T123848Z.json",
            "mismatch_count": 341,
        }
    )
    row = {
        "level": "high",
        "category": "reconcile",
        "title": "跨源对账待复核",
        "detail": detail,
    }
    text = format_feishu_text(row)
    full = format_alert_full(row)
    assert "/Users/kimi/" not in text
    assert "Documents/ChatGPT" not in text
    assert "报告：reconcile_20260911T123848Z.json" in text
    assert "报告：reconcile_20260911T123848Z.json" in full


def test_post_feishu_alert_failure_does_not_raise(monkeypatch):
    def boom(*_args, **_kwargs):
        raise URLError("down")

    monkeypatch.setattr("asqt.adapters.feishu_alert.urllib.request.urlopen", boom)
    result = post_feishu_alert(
        {"level": "critical", "category": "drawdown", "title": "stop"},
        webhook="https://open.feishu.cn/open-apis/bot/v2/hook/test",
    )
    assert result["ok"] is False
    assert "down" in (result.get("reason") or "")


def test_local_alert_fanout_records_feishu_meta(tmp_path, monkeypatch):
    settings, _engine, _service = _prepare(tmp_path)
    monkeypatch.setattr(
        "asqt.adapters.feishu_alert.post_feishu_alert",
        lambda row, **_kwargs: {"channel": "feishu", "ok": True, "code": 0},
    )
    LocalAlertService(settings).raise_alert("high", "ops", "paper started", "p3")
    remote = (settings.logs_dir / "alerts_remote.jsonl").read_text(encoding="utf-8")
    payload = json.loads(remote.strip().splitlines()[-1])
    assert payload["title"] == "paper started"
    assert payload["remote"]["channel"] == "feishu"
    assert payload["remote"]["ok"] is True


def test_alert_demo_dry_run_isolated(tmp_path):
    from asqt.alert_demo import run_alert_demo
    from asqt.config import Settings
    from asqt.ops import kill_engaged

    result = run_alert_demo(root=tmp_path / "demo", live=False, pause_s=0)
    assert result["ok"] is True
    assert result["live"] is False
    assert result["failed"] == 0
    assert result["kill_engaged"] is False
    assert int(result["alert_count"]) >= 6
    assert result["skipped"] >= 1
    remote = (tmp_path / "demo" / "data" / "logs" / "alerts_remote.jsonl").read_text(encoding="utf-8")
    assert "演练开始" in remote
    assert "质量闸门" in remote
    assert "日终模拟失败" in remote
    assert "max drawdown warning" in remote
    assert "kill switch on" in remote
    assert "max drawdown stop" in remote
    assert "演练结束" in remote
    settings = Settings(
        project_root=tmp_path / "demo",
        data_dir=tmp_path / "demo" / "data",
        database_path=tmp_path / "demo" / "data" / "asqt.sqlite3",
        parquet_dir=tmp_path / "demo" / "data" / "parquet",
        raw_dir=tmp_path / "demo" / "data" / "raw_data",
        standard_dir=tmp_path / "demo" / "data" / "standard_data",
        qlib_dir=tmp_path / "demo" / "data" / "qlib_data",
        experiment_dir=tmp_path / "demo" / "data" / "experiment",
        logs_dir=tmp_path / "demo" / "data" / "logs",
        frontend_dir=tmp_path / "demo" / "frontend",
    )
    assert kill_engaged(settings) is False

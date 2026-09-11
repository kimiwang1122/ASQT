"""Feishu custom-bot webhook. No vendor SDK; JSON POST only."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

import certifi

DEFAULT_FEISHU_WEBHOOK = (
    "https://open.feishu.cn/open-apis/bot/v2/hook/2bfb3ba6-f779-4331-a8d9-f3bc06354176"
)
FEISHU_LEVELS = {"high", "critical"}


def feishu_webhook_url() -> str | None:
    raw = os.environ.get("ASQT_FEISHU_WEBHOOK")
    if raw is not None:
        return raw.strip() or None
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    return DEFAULT_FEISHU_WEBHOOK


def format_feishu_text(row: dict[str, Any]) -> str:
    from asqt.alert_format import format_feishu_text as shared_format

    return shared_format(row)


def should_push_feishu(row: dict[str, Any]) -> bool:
    return str(row.get("level") or "").lower() in FEISHU_LEVELS


def _feishu_ok(parsed: dict[str, Any]) -> bool:
    if "code" in parsed and parsed["code"] not in (0, "0", None):
        return False
    if "StatusCode" in parsed and parsed["StatusCode"] not in (0, "0", None):
        return False
    return True


def post_feishu_alert(row: dict[str, Any], *, webhook: str | None = None) -> dict[str, Any]:
    """Push high/critical alerts. Failures must not break LocalAlertService."""
    last: dict[str, Any] | None = None
    for attempt in range(2):
        last = _post_feishu_once(row, webhook=webhook)
        if last.get("ok") or last.get("skipped") or last.get("code") != 19024:
            return last
        time.sleep(1.2)
    return last or {"channel": "feishu", "ok": False, "reason": "empty"}


def _post_feishu_once(row: dict[str, Any], *, webhook: str | None = None) -> dict[str, Any]:
    url = webhook if webhook is not None else feishu_webhook_url()
    if not url:
        return {"channel": "feishu", "ok": False, "skipped": True, "reason": "no_webhook"}
    if not should_push_feishu(row):
        return {"channel": "feishu", "ok": True, "skipped": True, "reason": "level"}
    body = json.dumps(
        {"msg_type": "text", "content": {"text": format_feishu_text(row)}},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=8,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return {
                "channel": "feishu",
                "ok": _feishu_ok(parsed),
                "http_status": getattr(response, "status", 200),
                "code": parsed.get("code", parsed.get("StatusCode")),
                "msg": parsed.get("msg"),
            }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"channel": "feishu", "ok": False, "reason": str(exc)[:300]}

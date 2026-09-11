#!/usr/bin/env python3
"""One-shot cross-source reconcile for manual / launchd use."""

from __future__ import annotations

import sys

from asqt.config import get_settings
from asqt.reconcile_jobs import run_reconcile_job


def main() -> int:
    print("start reconcile", flush=True)
    report = run_reconcile_job(trigger="manual", settings=get_settings(), notify=True)
    print(
        "done",
        report.get("task_status"),
        report.get("comparison"),
        flush=True,
    )
    print("report_path", report.get("report_path"), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print("failed", exc, flush=True)
        raise

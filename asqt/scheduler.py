"""In-process task runner. Not Redis; SQLite task_run is the ledger."""

from __future__ import annotations

from typing import Any

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import initialize_database, query_all
from asqt.paper import advance_paper_session
from asqt.sync import run_sync_job


class LocalScheduler:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = ensure_runtime_dirs(settings or get_settings())
        initialize_database(self.settings)

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        return query_all(
            "SELECT * FROM task_run ORDER BY created_at DESC LIMIT ?",
            (limit,),
            settings=self.settings,
        )

    def run_task(self, task_name: str) -> dict[str, Any]:
        name = (task_name or "").replace("_", "-")
        if name == "sync-daily":
            return run_sync_job(trigger="scheduler", settings=self.settings)
        if name == "paper-daily":
            return advance_paper_session(trigger="scheduler", settings=self.settings)
        if name == "reconcile-daily":
            from asqt.reconcile_jobs import run_reconcile_job

            return run_reconcile_job(trigger="scheduler", settings=self.settings)
        if name == "cash-reconcile":
            from asqt.paper_reconcile_jobs import run_cash_reconcile_job

            return run_cash_reconcile_job(trigger="scheduler", settings=self.settings)
        raise ValueError(f"unknown task: {task_name}")

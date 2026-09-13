"""Unified experiment / job report tree under ``data/experiment/``.

Layout (GATE-D4)::

    experiment/
      {kind}/{run_id}/manifest.json
      {kind}/{run_id}/summary.json
      latest/{kind}/{strategy_or_key}.json   # pointer copy of summary
      latest-{strategy_id}.json              # legacy flat pointer (admit compat)

Kinds: ``backtest``, ``tune``, ``paper``, ``factor``, ``draft``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from asqt.config import Settings, ensure_runtime_dirs, get_settings

KNOWN_KINDS = ("backtest", "tune", "paper", "factor", "draft")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def experiment_root(settings: Settings | None = None) -> Path:
    settings = ensure_runtime_dirs(settings or get_settings())
    root = settings.experiment_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def run_dir(kind: str, run_id: str, *, settings: Settings | None = None) -> Path:
    kind = str(kind or "").strip()
    run_id = str(run_id or "").strip()
    if kind not in KNOWN_KINDS:
        raise ValueError(f"unknown report kind: {kind}")
    if not run_id:
        raise ValueError("run_id is required")
    path = experiment_root(settings) / kind / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_run_tree(
    kind: str,
    run_id: str,
    summary: dict[str, Any],
    *,
    settings: Settings | None = None,
    strategy_id: str | None = None,
    manifest: dict[str, Any] | None = None,
    write_legacy_latest: bool = True,
) -> Path:
    """Persist summary (+ optional manifest) and refresh latest pointers."""
    folder = run_dir(kind, run_id, settings=settings)
    stamped = dict(summary)
    stamped.setdefault("kind", kind)
    stamped.setdefault("run_id", run_id)
    stamped.setdefault("created_at", _now())
    if strategy_id:
        stamped.setdefault("strategy_id", strategy_id)

    summary_path = folder / "summary.json"
    summary_path.write_text(json.dumps(stamped, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    man = {
        "kind": kind,
        "run_id": run_id,
        "strategy_id": strategy_id or stamped.get("strategy_id"),
        "created_at": stamped["created_at"],
        "summary": "summary.json",
    }
    if manifest:
        man.update(manifest)
    (folder / "manifest.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    key = str(strategy_id or stamped.get("strategy_id") or run_id)
    latest_dir = experiment_root(settings) / "latest" / kind
    latest_dir.mkdir(parents=True, exist_ok=True)
    latest_path = latest_dir / f"{key}.json"
    latest_path.write_text(summary_path.read_text(encoding="utf-8"), encoding="utf-8")

    if write_legacy_latest and kind == "backtest" and key:
        legacy = experiment_root(settings) / f"latest-{key}.json"
        legacy.write_text(summary_path.read_text(encoding="utf-8"), encoding="utf-8")
    if write_legacy_latest and kind == "tune" and key:
        legacy = experiment_root(settings) / f"latest-tune-{key}.json"
        legacy.write_text(summary_path.read_text(encoding="utf-8"), encoding="utf-8")

    return summary_path


def latest_summary_path(
    strategy_id: str,
    *,
    kind: str = "backtest",
    settings: Settings | None = None,
) -> Path | None:
    """Prefer new tree pointer, then legacy flat ``latest-*.json``."""
    sid = str(strategy_id or "").strip()
    if not sid:
        return None
    root = experiment_root(settings)
    modern = root / "latest" / kind / f"{sid}.json"
    if modern.exists():
        return modern
    if kind == "backtest":
        legacy = root / f"latest-{sid}.json"
        if legacy.exists():
            return legacy
    if kind == "tune":
        legacy = root / f"latest-tune-{sid}.json"
        if legacy.exists():
            return legacy
    return None


def list_latest_experiments(*, settings: Settings | None = None) -> list[dict[str, Any]]:
    """List latest backtest summaries (tree first, then legacy flat files)."""
    root = experiment_root(settings)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    tree = root / "latest" / "backtest"
    if tree.exists():
        for path in sorted(tree.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            sid = str(payload.get("strategy_id") or path.stem)
            seen.add(sid)
            items.append(payload)
    for path in sorted(root.glob("latest-*.json")):
        name = path.name
        if name.startswith("latest-tune-"):
            continue
        sid = name[len("latest-") : -len(".json")]
        if sid in seen:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(payload)
        seen.add(sid)
    return items

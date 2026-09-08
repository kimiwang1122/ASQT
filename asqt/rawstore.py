from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from asqt.config import Settings, ensure_runtime_dirs, get_settings


def write_raw_json(
    source_id: str,
    dataset: str,
    payload: dict[str, Any],
    *,
    settings: Settings | None = None,
    stem: str | None = None,
) -> Path:
    settings = ensure_runtime_dirs(settings or get_settings())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = stem or stamp
    path = settings.raw_dir / source_id / dataset / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

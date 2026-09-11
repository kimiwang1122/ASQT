#!/usr/bin/env bash
# Fallback after in-process auto sync (16:30 wait / 18:00 retry).
# Weekdays 20:05 Asia/Shanghai. Same SQLite lock: Busy if auto still running.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export TZ="${TZ:-Asia/Shanghai}"
dow="$(date +%u)"
if [[ "$dow" -ge 6 ]]; then
  exit 0
fi
if [[ -x "$ROOT/.venv/bin/asqt" ]]; then
  ASQT="$ROOT/.venv/bin/asqt"
else
  ASQT="asqt"
fi
# Do not fail the paper catch-up if sync is Busy (uvicorn still holding the lock).
set +e
"$ASQT" sync-daily --trigger cron --skip-reconcile
sync_rc=$?
set -e
"$ASQT" paper-daily
exit "$sync_rc"

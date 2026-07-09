#!/usr/bin/env bash
# Run sync.py (used by Jenkins weekly job).
# Usage:
#   ./scripts/run_sync.sh       # uses JIRA_JQL from .env as-is
#   ./scripts/run_sync.sh 7     # override updated/created >= -7d in JIRA_JQL
#   GOOGLE_SHEETS_TAB_NAME="My Tab" ./scripts/run_sync.sh 7   # local override

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

mkdir -p "$SCRIPT_DIR/logs"

PYTHON="python3"
if [[ ! -d "$SCRIPT_DIR/.vendor/requests" ]]; then
  echo "Missing dependencies. Run once:" >&2
  echo "  python3 -m pip install --target $SCRIPT_DIR/.vendor -r $SCRIPT_DIR/requirements.txt" >&2
  exit 1
fi
export PYTHONPATH="$SCRIPT_DIR/.vendor${PYTHONPATH:+:$PYTHONPATH}"

DAYS="${1:-}"
SHEET_TAB_ARGS=()
if [[ -n "${GOOGLE_SHEETS_TAB_NAME:-}" ]]; then
  SHEET_TAB_ARGS=(--sheet-tab "$GOOGLE_SHEETS_TAB_NAME")
fi

LOG_FILE="$SCRIPT_DIR/logs/sync-$(date +%Y%m%d-%H%M%S).log"
if ! touch "$LOG_FILE" 2>/dev/null; then
  LOG_FILE="/tmp/jira-sheet-sync-$(date +%Y%m%d-%H%M%S).log"
  echo "Note: logging to $LOG_FILE (project logs/ not writable for this user)" >&2
fi

set +o pipefail
{
  echo "=== sync started at $(date -Iseconds) ==="
  if [[ -n "$DAYS" ]]; then
    echo "Days window: -${DAYS}d"
    "$PYTHON" sync.py --days "$DAYS" "${SHEET_TAB_ARGS[@]}"
  else
    "$PYTHON" sync.py "${SHEET_TAB_ARGS[@]}"
  fi
  echo "=== sync finished at $(date -Iseconds) ==="
} 2>&1 | tee "$LOG_FILE"
SYNC_EXIT=${PIPESTATUS[0]}
set -o pipefail
exit "$SYNC_EXIT"

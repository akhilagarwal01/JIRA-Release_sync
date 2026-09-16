#!/usr/bin/env bash
# Append daily COR/LINUX + DEVOPS tasks to DailyTaskLogs.xlsx (weekdays only).
# Usage:
#   ./scripts/run_daily_task_log.sh
#   ./scripts/run_daily_task_log.sh 3          # override lookback days
#   ./scripts/run_daily_task_log.sh --dry-run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

mkdir -p "$SCRIPT_DIR/logs"

PYTHON="python3"
if [[ ! -d "$SCRIPT_DIR/.vendor/requests" ]] || [[ ! -d "$SCRIPT_DIR/.vendor/openpyxl" ]]; then
  echo "Installing Python dependencies into .vendor ..."
  python3 -m pip install --target "$SCRIPT_DIR/.vendor" -r "$SCRIPT_DIR/requirements.txt"
fi
export PYTHONPATH="$SCRIPT_DIR/.vendor${PYTHONPATH:+:$PYTHONPATH}"

ARGS=()
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  ARGS=(--days "$1")
  shift
fi
ARGS+=("$@")

LOG_FILE="$SCRIPT_DIR/logs/daily-task-log-$(date +%Y%m%d-%H%M%S).log"
if ! touch "$LOG_FILE" 2>/dev/null; then
  LOG_FILE="/tmp/daily-task-log-$(date +%Y%m%d-%H%M%S).log"
  echo "Note: logging to $LOG_FILE (project logs/ not writable for this user)" >&2
fi

set +o pipefail
{
  echo "=== daily_task_log started at $(date -Iseconds) ==="
  "$PYTHON" daily_task_log.py "${ARGS[@]}"
  echo "=== daily_task_log finished at $(date -Iseconds) ==="
} 2>&1 | tee "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}
set -o pipefail
exit "$EXIT_CODE"

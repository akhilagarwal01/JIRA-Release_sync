#!/usr/bin/env bash
# One-time: allow Jenkins (runs as SYSTEM) and your user to share DailyTaskLogs.xlsx
# in the project folder.
#
# Usage:
#   bash scripts/setup_daily_log_permissions.sh
#
# What it does:
#   - Project folder: 751 (others can traverse to the xlsx by path)
#   - DailyTaskLogs.xlsx: 666 (owner, group, and Jenkins/SYSTEM can read/write)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKBOOK="$PROJECT_DIR/DailyTaskLogs.xlsx"

chmod 751 "$PROJECT_DIR"
if [[ -f "$WORKBOOK" ]]; then
  chmod 666 "$WORKBOOK"
else
  echo "Workbook not found yet: $WORKBOOK"
  echo "Create it once (run daily_task_log locally) then re-run this script."
fi

echo "Permissions set:"
ls -la "$PROJECT_DIR" | head -1
ls -la "$WORKBOOK" 2>/dev/null || true
echo ""
echo "DAILY_TASK_LOG_WORKBOOK should be:"
echo "  $WORKBOOK"

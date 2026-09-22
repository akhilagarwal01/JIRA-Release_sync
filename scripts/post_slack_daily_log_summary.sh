#!/usr/bin/env bash
# Post daily_task_log upsert summary to Slack (no EnvInject plugin required).
#
# Requires in jira-secrets/.env (do not commit):
#   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
#
# Called automatically from jenkins_daily_task_log.sh when the webhook is set.

set -euo pipefail

WORKSPACE="${WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SECRETS_DIR="${JIRA_SYNC_SECRETS_DIR:-/opt/jira-sheet-sync-secrets}"
PROPS="$WORKSPACE/daily_task_log_slack.properties"

read_env_value() {
  local file="$1" key="$2"
  if [[ ! -f "$file" ]]; then
    return 1
  fi
  grep -E "^${key}=" "$file" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r'
}

WEBHOOK="$(read_env_value "$SECRETS_DIR/.env" SLACK_WEBHOOK_URL || true)"
if [[ -z "$WEBHOOK" ]]; then
  echo "SLACK_WEBHOOK_URL not set — skip Slack summary (add to jira-secrets/.env)." >&2
  exit 0
fi

if [[ ! -f "$PROPS" ]]; then
  echo "Missing $PROPS — run jenkins_daily_task_log.sh first." >&2
  exit 0
fi

DAILY_LOG_LOOKBACK="$(read_env_value "$PROPS" DAILY_LOG_LOOKBACK || echo "?")"
DAILY_LOG_BOARD="$(read_env_value "$PROPS" DAILY_LOG_BOARD || echo "0")"
DAILY_LOG_DEVOPS="$(read_env_value "$PROPS" DAILY_LOG_DEVOPS || echo "0")"
DAILY_LOG_SHEETS="$(read_env_value "$PROPS" DAILY_LOG_SHEETS || echo "n/a")"
DAILY_LOG_RESULT="$(read_env_value "$PROPS" DAILY_LOG_RESULT || echo "n/a")"

BUILD_NUMBER="${BUILD_NUMBER:-local}"
BUILD_URL="${BUILD_URL:-}"
JOB_NAME="${JOB_NAME:-Daily Task Log}"

export SLACK_WEBHOOK="$WEBHOOK"
export SLACK_TEXT
SLACK_TEXT=$(cat <<EOF
:white_check_mark: *${JOB_NAME}* #${BUILD_NUMBER}
• Lookback: ${DAILY_LOG_LOOKBACK} day(s)
• JIRA: ${DAILY_LOG_BOARD} board + ${DAILY_LOG_DEVOPS} DEVOPS
• Excel: ${DAILY_LOG_RESULT}
• Sheet: ${DAILY_LOG_SHEETS}
${BUILD_URL:+<$BUILD_URL/console|Open console>}
EOF
)

python3 - <<'PY'
import json
import os
import urllib.request

payload = json.dumps({"text": os.environ["SLACK_TEXT"]}).encode("utf-8")
req = urllib.request.Request(
    os.environ["SLACK_WEBHOOK"],
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    print("Slack webhook notify:", resp.status)
PY

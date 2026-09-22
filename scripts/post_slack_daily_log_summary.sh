#!/usr/bin/env bash
# Post daily_task_log upsert summary to Slack (no EnvInject plugin required).
#
# Usage in Jenkins (Post-build Execute shell — run only on SUCCESS):
#   export JIRA_SYNC_SECRETS_DIR=/home/akhilagarwal/jira-secrets
#   bash "$WORKSPACE/scripts/post_slack_daily_log_summary.sh"
#
# Requires in secrets .env (optional line):
#   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
#
# Or export SLACK_WEBHOOK_URL in the Jenkins job / credentials before calling.

set -euo pipefail

WORKSPACE="${WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SECRETS_DIR="${JIRA_SYNC_SECRETS_DIR:-/opt/jira-sheet-sync-secrets}"
PROPS="$WORKSPACE/daily_task_log_slack.properties"

if [[ -f "$SECRETS_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$SECRETS_DIR/.env"
  set +a
fi

WEBHOOK="${SLACK_WEBHOOK_URL:-}"
if [[ -z "$WEBHOOK" ]]; then
  echo "SLACK_WEBHOOK_URL not set — skip Slack summary (add to jira-secrets/.env or Jenkins env)." >&2
  exit 0
fi

if [[ ! -f "$PROPS" ]]; then
  echo "Missing $PROPS — run jenkins_daily_task_log.sh first." >&2
  exit 0
fi

set -a
# shellcheck disable=SC1090
source "$PROPS"
set +a

BUILD_NUMBER="${BUILD_NUMBER:-local}"
BUILD_URL="${BUILD_URL:-}"
JOB_NAME="${JOB_NAME:-Daily Task Log}"

export SLACK_WEBHOOK="$WEBHOOK"
SLACK_TEXT=$(cat <<EOF
:white_check_mark: *${JOB_NAME}* #${BUILD_NUMBER}
• Lookback: ${DAILY_LOG_LOOKBACK:-?} day(s)
• JIRA: ${DAILY_LOG_BOARD:-0} board + ${DAILY_LOG_DEVOPS:-0} DEVOPS
• Excel: ${DAILY_LOG_RESULT:-n/a}
• Sheet: ${DAILY_LOG_SHEETS:-n/a}
${BUILD_URL:+<$BUILD_URL/console|Open console>}
EOF
)
export SLACK_TEXT

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
    print("Slack notify:", resp.status)
PY

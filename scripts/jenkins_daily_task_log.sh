#!/usr/bin/env bash
# Jenkins build step for daily_task_log.py (weekday Excel task log).
#
# Secrets (outside Git):
#   $JIRA_SYNC_SECRETS_DIR/.env   — JIRA creds, DAILY_TASK_LOG_* settings, workbook path
#
# Lookback (Jenkins only):
#   Compares today with the previous successful Jenkins build date (or a marker file
#   fallback). If the gap is > 1 calendar day, uses that gap as --days so missed runs
#   after leave are covered (e.g. last success Tue, run Fri → --days 3).
#
# Optional Jenkins Boolean parameter:
#   DRY_RUN        check to print rows without writing DailyTaskLogs.xlsx
#
# Optional env:
#   JIRA_SYNC_SECRETS_DIR   default: /opt/jira-sheet-sync-secrets
#   JENKINS_URL             default: http://localhost:8080 (for lastSuccessfulBuild API)
#   JENKINS_USER / JENKINS_API_TOKEN   optional Basic auth for the Jenkins API

set -euo pipefail

WORKSPACE="${WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SECRETS_DIR="${JIRA_SYNC_SECRETS_DIR:-/opt/jira-sheet-sync-secrets}"
MARKER_FILE="$SECRETS_DIR/.daily_task_log_last_success"
JENKINS_URL="${JENKINS_URL:-http://localhost:8080}"

cd "$WORKSPACE"

if [[ ! -f "$SECRETS_DIR/.env" ]]; then
  echo "Missing $SECRETS_DIR/.env — see JENKINS.md (Daily task log section)" >&2
  exit 1
fi

cp "$SECRETS_DIR/.env" "$WORKSPACE/.env"

if [[ ! -d "$WORKSPACE/.vendor/requests" ]] || [[ ! -d "$WORKSPACE/.vendor/openpyxl" ]]; then
  echo "Installing Python dependencies into .vendor ..."
  python3 -m pip install --target "$WORKSPACE/.vendor" -r "$WORKSPACE/requirements.txt"
fi

weekday_default_lookback() {
  python3 - <<'PY'
from datetime import date

today = date.today()
if today.weekday() == 0:
    print(3)
else:
    print(1)
PY
}

fetch_last_success_date_from_jenkins() {
  local job_name="${JOB_NAME:-}"
  if [[ -z "$job_name" ]]; then
    return 1
  fi

  local encoded_job
  encoded_job=$(python3 - <<PY
import urllib.parse
print(urllib.parse.quote("""$job_name""", safe=""))
PY
)

  local url="${JENKINS_URL%/}/job/${encoded_job}/lastSuccessfulBuild/buildTimestamp?format=yyyy-MM-dd"
  local curl_args=(-fsS "$url")
  if [[ -n "${JENKINS_USER:-}" && -n "${JENKINS_API_TOKEN:-}" ]]; then
    curl_args=(-fsS -u "${JENKINS_USER}:${JENKINS_API_TOKEN}" "$url")
  fi

  local ts
  ts=$(curl "${curl_args[@]}" 2>/dev/null || true)
  if [[ "$ts" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "$ts"
    return 0
  fi
  return 1
}

fetch_last_success_date_from_marker() {
  if [[ -f "$MARKER_FILE" ]]; then
    tr -d '[:space:]' < "$MARKER_FILE"
  fi
}

compute_jenkins_lookback_days() {
  local today last_success gap days
  today=$(date +%Y-%m-%d)

  last_success=$(fetch_last_success_date_from_jenkins || true)
  if [[ -n "$last_success" ]]; then
    echo "Previous successful Jenkins build date: $last_success (from Jenkins API)" >&2
  else
    last_success=$(fetch_last_success_date_from_marker || true)
    if [[ -n "$last_success" ]]; then
      echo "Previous successful run date: $last_success (from marker file)" >&2
    fi
  fi

  if [[ -z "$last_success" ]]; then
    days=$(weekday_default_lookback)
    echo "No previous successful build found; using weekday default lookback: ${days} day(s)" >&2
    echo "$days"
    return
  fi

  gap=$(python3 - <<PY
from datetime import date
last = date.fromisoformat("$last_success")
today = date.fromisoformat("$today")
print((today - last).days)
PY
)

  if [[ "$gap" -le 0 ]]; then
    days=1
    echo "Same-day rebuild; lookback: ${days} day(s)" >&2
  elif [[ "$gap" -eq 1 ]]; then
    days=1
    echo "Last success was yesterday; lookback: ${days} day(s)" >&2
  else
    days=$gap
    echo "Last success was ${gap} calendar day(s) ago; extended lookback: ${days} day(s)" >&2
  fi

  echo "$days"
}

LOOKBACK_DAYS=$(compute_jenkins_lookback_days)

ARGS=("$LOOKBACK_DAYS" --force)
if [[ "${DRY_RUN:-false}" == "true" ]]; then
  ARGS+=(--dry-run)
  echo "DRY_RUN enabled — Excel file will not be modified." >&2
fi

chmod +x "$WORKSPACE/scripts/run_daily_task_log.sh"
bash "$WORKSPACE/scripts/run_daily_task_log.sh" "${ARGS[@]}"

if [[ "${DRY_RUN:-false}" == "true" ]]; then
  echo "Dry run complete — success marker not updated." >&2
  exit 0
fi

date +%Y-%m-%d > "$MARKER_FILE"
echo "Updated success marker: $MARKER_FILE"

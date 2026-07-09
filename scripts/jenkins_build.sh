#!/usr/bin/env bash
# Jenkins build step — run from $WORKSPACE after Git checkout.
#
# Requires secrets outside the repo (never commit these):
#   $JIRA_SYNC_SECRETS_DIR/.env
#   $JIRA_SYNC_SECRETS_DIR/client-secret.json
#   $JIRA_SYNC_SECRETS_DIR/.google-sheets-token.json  (created after first OAuth login)
#
# Optional env (Jenkins job parameters):
#   GOOGLE_SHEETS_TAB_NAME    override worksheet tab; falls back to secrets .env if unset
#   JIRA_SYNC_DAYS=7            override JQL updated/created >= -Nd window
#   JIRA_SYNC_SECRETS_DIR       default: /opt/jira-sheet-sync-secrets

set -euo pipefail

WORKSPACE="${WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SECRETS_DIR="${JIRA_SYNC_SECRETS_DIR:-/opt/jira-sheet-sync-secrets}"
DAYS="${JIRA_SYNC_DAYS:-7}" # number of days to sync

cd "$WORKSPACE"

for f in .env client-secret.json; do
  if [[ ! -f "$SECRETS_DIR/$f" ]]; then
    echo "Missing $SECRETS_DIR/$f — see JENKINS.md" >&2
    exit 1
  fi
done

cp "$SECRETS_DIR/.env" "$WORKSPACE/.env"
if [[ -n "${GOOGLE_SHEETS_TAB_NAME:-}" ]]; then
  # Job parameter overrides secrets .env
  grep -v '^GOOGLE_SHEETS_TAB_NAME=' "$WORKSPACE/.env" > "$WORKSPACE/.env.tmp"
  mv "$WORKSPACE/.env.tmp" "$WORKSPACE/.env"
  export GOOGLE_SHEETS_TAB_NAME
  echo "Sheet tab (from Jenkins): ${GOOGLE_SHEETS_TAB_NAME}"
else
  echo "Sheet tab: using GOOGLE_SHEETS_TAB_NAME from secrets .env"
fi

cp "$SECRETS_DIR/client-secret.json" "$WORKSPACE/client-secret.json"
if [[ -f "$SECRETS_DIR/.google-sheets-token.json" ]]; then
  cp "$SECRETS_DIR/.google-sheets-token.json" "$WORKSPACE/.google-sheets-token.json"
else
  echo "Missing $SECRETS_DIR/.google-sheets-token.json" >&2
  echo "Run sync once manually to complete Google OAuth — see JENKINS.md" >&2
  exit 1
fi

if [[ ! -d "$WORKSPACE/.vendor/requests" ]]; then
  echo "Installing Python dependencies into .vendor ..."
  python3 -m pip install --target "$WORKSPACE/.vendor" -r "$WORKSPACE/requirements.txt"
fi

chmod +x "$WORKSPACE/scripts/run_sync.sh"
bash "$WORKSPACE/scripts/run_sync.sh" "$DAYS"

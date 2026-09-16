#!/usr/bin/env bash
# Jenkins build step for release_mail_draft.py (manual trigger — Gmail draft).
#
# Required Jenkins String parameters:
#   JIRA_ID        e.g. DEVOPS-40011
#   SERVICE_NAME   e.g. CORE | HomePage
#
# Optional Jenkins Boolean parameter:
#   DRY_RUN        check to print email without creating a Gmail draft
#
# Secrets (outside Git):
#   $JIRA_SYNC_SECRETS_DIR/.env
#   $JIRA_SYNC_SECRETS_DIR/client-secret.json
#   $JIRA_SYNC_SECRETS_DIR/.gmail-token.json
#
# Optional env:
#   JIRA_SYNC_SECRETS_DIR   default: /opt/jira-sheet-sync-secrets

set -euo pipefail

WORKSPACE="${WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SECRETS_DIR="${JIRA_SYNC_SECRETS_DIR:-/opt/jira-sheet-sync-secrets}"

cd "$WORKSPACE"

JIRA_ID="${JIRA_ID:-}"
SERVICE_NAME="${SERVICE_NAME:-}"
if [[ -z "$JIRA_ID" || -z "$SERVICE_NAME" ]]; then
  echo "Missing Jenkins parameters JIRA_ID and SERVICE_NAME." >&2
  exit 1
fi

for f in .env client-secret.json .gmail-token.json; do
  if [[ ! -f "$SECRETS_DIR/$f" ]]; then
    echo "Missing $SECRETS_DIR/$f — see JENKINS.md (Release mail draft section)" >&2
    exit 1
  fi
done

cp "$SECRETS_DIR/.env" "$WORKSPACE/.env"
cp "$SECRETS_DIR/client-secret.json" "$WORKSPACE/client-secret.json"
cp "$SECRETS_DIR/.gmail-token.json" "$WORKSPACE/.gmail-token.json"

if [[ ! -d "$WORKSPACE/.vendor/requests" ]]; then
  echo "Installing Python dependencies into .vendor ..."
  python3 -m pip install --target "$WORKSPACE/.vendor" -r "$WORKSPACE/requirements.txt"
fi

ARGS=()
if [[ "${DRY_RUN:-false}" == "true" ]]; then
  ARGS+=(--dry-run)
fi

chmod +x "$WORKSPACE/scripts/run_release_mail_draft.sh"
bash "$WORKSPACE/scripts/run_release_mail_draft.sh" "$JIRA_ID" "$SERVICE_NAME" "${ARGS[@]}"

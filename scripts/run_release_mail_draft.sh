#!/usr/bin/env bash
# Create a Gmail release-notes draft for one JIRA ticket.
#
# Usage:
#   ./scripts/run_release_mail_draft.sh DEVOPS-37773 "CORE | HomePage"
#   ./scripts/run_release_mail_draft.sh DEVOPS-37773 "CORE | HomePage" --dry-run
#
# Jenkins (String parameters JIRA_ID, SERVICE_NAME):
#   bash "$WORKSPACE/scripts/run_release_mail_draft.sh" "${JIRA_ID}" "${SERVICE_NAME}"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

JIRA_ID="${1:-}"
SERVICE_NAME="${2:-}"
if [[ -z "$JIRA_ID" || -z "$SERVICE_NAME" ]]; then
  echo "Usage: $0 JIRA-KEY \"Service Name\" [--dry-run]" >&2
  exit 1
fi
shift 2

PYTHON="python3"
if [[ ! -d "$SCRIPT_DIR/.vendor/requests" ]]; then
  echo "Missing dependencies. Run once:" >&2
  echo "  python3 -m pip install --target $SCRIPT_DIR/.vendor -r $SCRIPT_DIR/requirements.txt" >&2
  exit 1
fi
export PYTHONPATH="$SCRIPT_DIR/.vendor${PYTHONPATH:+:$PYTHONPATH}"

exec "$PYTHON" release_mail_draft.py --jira-id "$JIRA_ID" --service "$SERVICE_NAME" "$@"

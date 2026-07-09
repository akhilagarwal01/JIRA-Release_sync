#!/usr/bin/env python3
"""
Create a Gmail draft with release notes for one JIRA release ticket.

Usage:
  python3 release_mail_draft.py --jira-id DEVOPS-37773 --service "CORE | HomePage"
  python3 release_mail_draft.py --jira-id DEVOPS-37773 --service "CORE | HomePage" --dry-run

Requires the same .env as sync.py (JIRA_* and GOOGLE_OAUTH_CLIENT_SECRETS_FILE).
First Gmail run opens a browser (Gmail API must be enabled in Google Cloud).
Token is saved to .gmail-token.json (separate from the Sheets token).
If signature loading fails after an update, delete .gmail-token.json and run again
to re-approve Gmail settings access.
"""

from __future__ import annotations

import argparse
import base64
import html as html_module
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests
from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Compose drafts + read send-as signature from Gmail settings (your logo there).
GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.settings.basic",
)


# ---------------------------------------------------------------------------
# JIRA helpers
# ---------------------------------------------------------------------------


def jira_get(
    base_url: str,
    email: str,
    token: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """GET one JIRA REST path; exit on error."""
    url = f"{base_url.rstrip('/')}{path}"
    resp = requests.get(
        url,
        auth=(email, token),
        headers={"Accept": "application/json"},
        params=params or {},
        timeout=60,
    )
    if not resp.ok:
        print(f"JIRA error {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)
    return resp.json()


def adf_to_plain_text(node: Any) -> str:
    """Turn JIRA comment body (often ADF JSON) into plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node.strip()
    parts: list[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            if n.get("type") == "text" and "text" in n:
                parts.append(str(n["text"]))
            for v in n.values():
                if isinstance(v, (list, dict)):
                    walk(v)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    walk(node)
    return "".join(parts).strip()


def normalize_spaces(text: str) -> str:
    return " ".join((text or "").split())


def iso_to_yyyy_mm_dd(iso: str) -> str:
    s = (iso or "").strip()
    if "T" in s:
        return s.split("T", 1)[0]
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


def yyyy_mm_dd_to_dd_mm_yyyy(yyyy_mm_dd: str) -> str:
    """2026-05-21 -> 21-05-2026"""
    if len(yyyy_mm_dd) >= 10 and yyyy_mm_dd[4] == "-":
        y, m, d = yyyy_mm_dd[:10].split("-")
        return f"{d}-{m}-{y}"
    return yyyy_mm_dd


def dd_mm_yyyy_to_slash(dd_mm_yyyy: str) -> str:
    """21-05-2026 -> 21/05/2026 (for email subject)."""
    parts = (dd_mm_yyyy or "").strip().split("-")
    if len(parts) == 3:
        return f"{parts[0]}/{parts[1]}/{parts[2]}"
    return dd_mm_yyyy.replace("-", "/")


def escape_html(text: str) -> str:
    return html_module.escape(text or "", quote=False)


def fetch_release_issue(
    base_url: str,
    email: str,
    token: str,
    issue_key: str,
) -> dict[str, Any]:
    """Load one issue with fields we need for the email."""
    fields = "summary,status,updated,issuetype,issuelinks"
    return jira_get(
        base_url,
        email,
        token,
        f"/rest/api/3/issue/{issue_key}",
        params={"fields": fields},
    )


def fetch_all_comments(
    base_url: str,
    email: str,
    token: str,
    issue_key: str,
) -> list[dict[str, Any]]:
    """Paginate through all comments on the issue."""
    out: list[dict[str, Any]] = []
    start_at = 0
    while True:
        data = jira_get(
            base_url,
            email,
            token,
            f"/rest/api/3/issue/{issue_key}/comment",
            params={"startAt": start_at, "maxResults": 100},
        )
        batch = data.get("comments") or []
        out.extend(batch)
        total = int(data.get("total") or len(out))
        start_at += len(batch)
        if start_at >= total or not batch:
            break
    return out


def release_date_from_comments(
    comments: list[dict[str, Any]],
    author: str,
    prefix: str,
    fallback_iso: str,
) -> str:
    """
    Use the newest calendar day that has a matching Saathi-style comment.
    Returns DD-MM-YYYY. Falls back to the issue updated date.
    """
    want_author = author.strip()
    want_prefix = normalize_spaces(prefix).lower()
    days: set[str] = set()

    for c in comments:
        name = ((c.get("author") or {}).get("displayName") or "").strip()
        if name != want_author:
            continue
        text = normalize_spaces(adf_to_plain_text(c.get("body"))).lower()
        if not text.startswith(want_prefix):
            continue
        day = iso_to_yyyy_mm_dd(c.get("created") or "")
        if day:
            days.add(day)

    if days:
        newest = max(days)
        return yyyy_mm_dd_to_dd_mm_yyyy(newest)

    return yyyy_mm_dd_to_dd_mm_yyyy(iso_to_yyyy_mm_dd(fallback_iso))


def parse_linked_task_types(task_type: str) -> set[str]:
    """Comma-separated issue types, e.g. Task,Story (default: Task)."""
    raw = (task_type or "Task").strip()
    parts = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return parts or {"task"}


def linked_tasks(
    fields: dict[str, Any],
    task_type: str,
) -> list[tuple[str, str]]:
    """List of (ticket key, summary) for linked issues of the given type(s)."""
    want_types = parse_linked_task_types(task_type)
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()

    for link in fields.get("issuelinks") or []:
        for side in (link.get("inwardIssue"), link.get("outwardIssue")):
            if not side:
                continue
            key = (side.get("key") or "").strip()
            if not key or key in seen:
                continue
            inner = side.get("fields") or {}
            itype = (inner.get("issuetype") or {}).get("name") or ""
            if itype.strip().lower() not in want_types:
                continue
            summary = (inner.get("summary") or "").strip()
            seen.add(key)
            rows.append((key, summary))

    return rows


# ---------------------------------------------------------------------------
# Email body (HTML tables + signature, like your Gmail draft screenshot)
# ---------------------------------------------------------------------------

# Controls the overall width of both tables.
OVERALL_TABLE_WIDTH = "560px"
TABLE_STYLE = (
    f"border-collapse:collapse;table-layout:fixed;width:{OVERALL_TABLE_WIDTH};max-width:{OVERALL_TABLE_WIDTH};"
    "font-family:Arial,Helvetica,sans-serif;font-size:12px;"
)
CELL = "border:1px solid #000;padding:5px 8px;vertical-align:top;"
HEADER_CELL = (
    "border:1px solid #000;padding:5px 8px;background:#d9d9d9;"
    "font-weight:bold;text-align:center;font-size:12px;"
)
# Product block: 2 columns (label column fixed width — independent of S.No. column).
PRODUCT_LABEL_WIDTH = "168px"
LABEL_CELL = f"{CELL}font-weight:bold;font-style:italic;"
VALUE_CELL = CELL
# Features block: separate table so only S.No. is narrow.
FEATURES_TABLE_STYLE = (
    f"border-collapse:collapse;table-layout:fixed;width:{OVERALL_TABLE_WIDTH};max-width:{OVERALL_TABLE_WIDTH};"
    "font-family:Arial,Helvetica,sans-serif;font-size:12px;margin-top:-1px;"
)
SNoCell = "32px"
SNO_CELL = f"{CELL}text-align:center;padding:4px 2px;font-size:11px;white-space:nowrap;"
SNO_HEADER = f"{HEADER_CELL}padding:4px 2px;font-size:10px;white-space:nowrap;"
TICKET_COL_WIDTH = "50px"
TICKET_CELL = f"{CELL}"
DESCRIPTION_COL_WIDTH = "200px"
DESCRIPTION_CELL = f"{CELL}word-break:break-word;white-space:normal;"


def fetch_gmail_signature_html(gmail_service: Any) -> str:
    """HTML signature from Gmail Settings → send-as (includes your logo)."""
    try:
        result = gmail_service.users().settings().sendAs().list(userId="me").execute()
        entries = result.get("sendAs") or []
        primary = next((e for e in entries if e.get("isPrimary")), None)
        if not primary and entries:
            primary = entries[0]
        if primary:
            return (primary.get("signature") or "").strip()
    except Exception as err:
        print(f"Warning: could not load Gmail signature: {err}", file=sys.stderr)
    return ""


def fallback_signature_html() -> str:
    """Used only if Gmail settings signature is empty."""
    name = os.environ.get("MAIL_SIGNATURE_NAME", "Akhil Agarwal | SDET-2").strip()
    phone = os.environ.get("MAIL_SIGNATURE_PHONE", "9717724148").strip()
    return f"""
<div style="margin-top:16px;font-size:12px;font-family:Arial,Helvetica,sans-serif;">
  <p style="margin:0 0 4px;">Thanks &amp; Regards,</p>
  <p style="margin:0 0 4px;"><strong style="color:#1a73e8;">{escape_html(name)}</strong></p>
  <p style="margin:0;"><strong>M: {escape_html(phone)}</strong></p>
</div>"""


def build_email_html(
    service_name: str,
    devops_ticket: str,
    release_date: str,
    release_type: str,
    release_kind: str,
    features: list[tuple[str, str]],
    signature_html: str,
) -> str:
    """Product table (2 cols) + features table (narrow S.No. only), like your screenshot."""
    feature_rows = ""
    if features:
        for i, (ticket_id, description) in enumerate(features, start=1):
            feature_rows += f"""
    <tr>
      <td style="{SNO_CELL}">{i}</td>
      <td style="{TICKET_CELL}">{escape_html(ticket_id)}</td>
      <td style="{DESCRIPTION_CELL}">{escape_html(description)}</td>
    </tr>"""
    else:
        feature_rows = f"""
    <tr>
      <td colspan="3" style="{CELL}text-align:center;">No linked Task tickets found.</td>
    </tr>"""

    def info_row(label: str, value: str) -> str:
        return f"""
    <tr>
      <td style="{LABEL_CELL}">{escape_html(label)}</td>
      <td style="{VALUE_CELL}">{escape_html(value)}</td>
    </tr>"""

    sig_block = signature_html.strip() or fallback_signature_html()

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#000;">
  <p style="margin:0 0 8px;">Hello Team,</p>
  <p style="margin:0 0 12px;">Please find <strong>{escape_html(service_name)}</strong> released feature listed below:</p>

  <table style="{TABLE_STYLE}" cellpadding="0" cellspacing="0">
    <colgroup>
      <col style="width:{PRODUCT_LABEL_WIDTH};" />
      <col />
    </colgroup>
    <tr>
      <td colspan="2" style="{HEADER_CELL}">Product Release Notes</td>
    </tr>
    {info_row("Product Name", service_name)}
    {info_row("Devops Ticket", devops_ticket)}
    {info_row("Release Date", release_date)}
    {info_row("Release Type (App/Web)", release_type)}
    {info_row("New Release / Patch", release_kind)}
  </table>

  <table style="{FEATURES_TABLE_STYLE}" cellpadding="0" cellspacing="0">
    <colgroup>
      <col style="width:{SNoCell};" />
      <col style="width:{TICKET_COL_WIDTH};" />
      <col style="width:{DESCRIPTION_COL_WIDTH};" />
    </colgroup>
    <tr>
      <td colspan="3" style="{HEADER_CELL}">Features Released</td>
    </tr>
    <tr>
      <td style="{SNO_HEADER}">S.No.</td>
      <td style="{HEADER_CELL}">TicketId</td>
      <td style="{HEADER_CELL}">Description</td>
    </tr>
    {feature_rows}
  </table>

  <div style="margin-top:16px;font-size:12px;">{sig_block}</div>
</body>
</html>"""


def build_email_plain(
    service_name: str,
    devops_ticket: str,
    release_date: str,
    release_type: str,
    release_kind: str,
    features: list[tuple[str, str]],
) -> str:
    """Plain-text fallback for mail clients that do not render HTML."""
    lines = [
        "Hello Team,",
        "",
        f"Please find {service_name} released feature listed below:",
        "",
        "Product Release Notes",
        f"Product Name: {service_name}",
        f"Devops Ticket: {devops_ticket}",
        f"Release Date: {release_date}",
        f"Release Type (App/Web): {release_type}",
        f"New Release / Patch: {release_kind}",
        "",
        "Features Released",
        "S.No. | TicketId | Description",
    ]
    for i, (ticket_id, description) in enumerate(features, start=1):
        lines.append(f"{i} | {ticket_id} | {description}")
    name = os.environ.get("MAIL_SIGNATURE_NAME", "Akhil Agarwal | SDET-2").strip()
    phone = os.environ.get("MAIL_SIGNATURE_PHONE", "9717724148").strip()
    lines.extend(["", "Thanks & Regards,", name, f"M: {phone}", ""])
    return "\n".join(lines)


def build_email_subject(service_name: str, release_date_dd_mm_yyyy: str) -> str:
    """e.g. CORE | DMAAR Release notes | 21/05/2026"""
    return f"{service_name} Release notes | {dd_mm_yyyy_to_slash(release_date_dd_mm_yyyy)}"


# ---------------------------------------------------------------------------
# Gmail draft
# ---------------------------------------------------------------------------

# Real distro + placeholder recipient. Gmail API rejects bare "xxx" in To; use a
# syntactically valid but undeliverable address so send fails until you remove it.
DRAFT_TO_RECIPIENTS = "core-release@paisabazaar.com, xxx@example.invalid"


def gmail_credentials() -> UserCredentials:
    """OAuth for Gmail; uses .gmail-token.json (not the Sheets token file)."""
    secrets = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "").strip()
    if not secrets or not os.path.isfile(secrets):
        print(
            "Set GOOGLE_OAUTH_CLIENT_SECRETS_FILE in .env to your OAuth Desktop JSON.",
            file=sys.stderr,
        )
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    token_path = (
        os.environ.get("GOOGLE_GMAIL_TOKEN_FILE", "").strip()
        or os.path.join(script_dir, ".gmail-token.json")
    )

    creds: UserCredentials | None = None
    if os.path.isfile(token_path):
        creds = UserCredentials.from_authorized_user_file(token_path, list(GMAIL_SCOPES))

    need_save = False
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                need_save = True
            except RefreshError:
                print(
                    "Gmail token scopes are outdated; sign in again in the browser.",
                    file=sys.stderr,
                )
                if os.path.isfile(token_path):
                    os.remove(token_path)
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(secrets, list(GMAIL_SCOPES))
            creds = flow.run_local_server(port=0)
            need_save = True

    if need_save and creds:
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return creds


def build_gmail_service() -> Any:
    creds = gmail_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def create_gmail_draft(
    gmail_service: Any,
    subject: str,
    html_body: str,
    plain_body: str,
) -> str:
    """Create a draft in the user's Gmail; return draft id."""
    service = gmail_service

    message = MIMEMultipart("alternative")
    message.attach(MIMEText(plain_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))
    message["Subject"] = subject
    message["To"] = DRAFT_TO_RECIPIENTS

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )
    return draft.get("id") or ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Build a Gmail draft for a JIRA release ticket.",
    )
    parser.add_argument(
        "--jira-id",
        required=True,
        help="Release ticket key, e.g. DEVOPS-37773",
    )
    parser.add_argument(
        "--service",
        required=True,
        help='Product / service name for the email, e.g. "CORE | HomePage"',
    )
    parser.add_argument(
        "--release-type",
        default=os.environ.get("RELEASE_MAIL_TYPE", "Web"),
        help="App or Web (default: Web)",
    )
    parser.add_argument(
        "--release-kind",
        default=os.environ.get("RELEASE_MAIL_KIND", "New Release"),
        help='e.g. "New Release" or "Patch"',
    )
    parser.add_argument(
        "--linked-type",
        default=os.environ.get("JIRA_LINKED_TASK_TYPE", "Task"),
        help="Linked issue type(s) for Features table (comma-separated, e.g. Task,Story)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the email body only; do not create a Gmail draft",
    )
    args = parser.parse_args()

    base_url = os.environ.get("JIRA_BASE_URL", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    api_token = os.environ.get("JIRA_API_TOKEN", "").strip()
    if not base_url or not email or not api_token:
        print("Missing JIRA_BASE_URL, JIRA_EMAIL, or JIRA_API_TOKEN in .env", file=sys.stderr)
        sys.exit(1)

    issue_key = args.jira_id.strip().upper()
    saathi = os.environ.get("JIRA_RELEASE_COMMENT_AUTHOR", "Saathi").strip()
    prefix = os.environ.get(
        "JIRA_RELEASE_COMMENT_PREFIX",
        "Release has been completed  for",
    ).strip()
    linked_type = args.linked_type.strip()

    issue = fetch_release_issue(base_url, email, api_token, issue_key)
    fields = issue.get("fields") or {}
    comments = fetch_all_comments(base_url, email, api_token, issue_key)

    release_date = release_date_from_comments(
        comments,
        saathi,
        prefix,
        fields.get("updated") or "",
    )
    features = linked_tasks(fields, linked_type)
    if not features:
        link_count = len(fields.get("issuelinks") or [])
        if link_count:
            print(
                f"No linked tickets matched type(s) {linked_type!r} "
                f"({link_count} link(s) on issue; check JIRA_LINKED_TASK_TYPE).",
                file=sys.stderr,
            )

    service_name = args.service.strip()
    release_type = args.release_type.strip()
    release_kind = args.release_kind.strip()

    gmail_service = None
    signature_html = ""
    try:
        gmail_service = build_gmail_service()
        signature_html = fetch_gmail_signature_html(gmail_service)
        if signature_html:
            print("Using signature from Gmail settings.")
        else:
            print("Gmail signature empty; using fallback text signature.", file=sys.stderr)
    except Exception as err:
        hint = "Delete .gmail-token.json in this folder, then run again to re-approve Gmail."
        if args.dry_run:
            print(
                f"Gmail not used for preview ({err}). {hint}",
                file=sys.stderr,
            )
            print("Using fallback signature in release_draft_preview.html.", file=sys.stderr)
        else:
            print(f"Gmail error: {err}", file=sys.stderr)
            print(hint, file=sys.stderr)
            sys.exit(1)

    html_body = build_email_html(
        service_name=service_name,
        devops_ticket=issue_key,
        release_date=release_date,
        release_type=release_type,
        release_kind=release_kind,
        features=features,
        signature_html=signature_html,
    )
    plain_body = build_email_plain(
        service_name=service_name,
        devops_ticket=issue_key,
        release_date=release_date,
        release_type=release_type,
        release_kind=release_kind,
        features=features,
    )
    subject = build_email_subject(service_name, release_date)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    preview_path = os.path.join(script_dir, "release_draft_preview.html")
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(html_body)
    print(f"Subject: {subject}")
    print(f"HTML preview saved: {preview_path}")
    print("---")

    if args.dry_run:
        print("Dry run: no Gmail draft created.")
        return

    if not gmail_service:
        print("Cannot create draft without Gmail authentication.", file=sys.stderr)
        sys.exit(1)
    draft_id = create_gmail_draft(gmail_service, subject, html_body, plain_body)
    print(f"Gmail draft created (id: {draft_id}). Open Gmail → Drafts to review and send.")


if __name__ == "__main__":
    main()

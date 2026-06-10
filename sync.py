#!/usr/bin/env python3
"""
Fetch JIRA issues via JQL and append rows to a Google Sheet.

Columns: S.No., Release date, DevopsId, Summary, status, Linked tasks,
Developer name, Duplicate. Rows are sorted by release date (oldest first); S.No.
continues from the highest number already in the sheet. Header row is bold; data
rows are normal weight.
Duplicate tickets get one row (first release date); later release dates are listed
in the Duplicate column. JQL issues are deduped by key once.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)

SHEET_HEADERS = [
    "S.No.",
    "Release date",
    "DevopsId",
    "Summary",
    "status",
    "Linked tasks",
    "Developer name",
    "Duplicate",
]

SHEET_COLUMN_COUNT = len(SHEET_HEADERS)
RELEASE_DATE_COLUMN_INDEX = 1


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def adf_to_plain_text(node: Any) -> str:
    """JIRA Cloud stores rich text (e.g. comments) as Atlassian Document Format."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node.strip()
    chunks: list[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            if n.get("type") == "text" and "text" in n:
                chunks.append(str(n["text"]))
            for v in n.values():
                if isinstance(v, (list, dict)):
                    walk(v)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    walk(node)
    return "".join(chunks).strip()


def normalize_spaces(text: str) -> str:
    return " ".join((text or "").split())


def jira_updated_date_only(updated: str) -> str:
    """JIRA returns ISO-8601; keep YYYY-MM-DD only."""
    s = (updated or "").strip()
    if not s:
        return ""
    if "T" in s:
        return s.split("T", 1)[0]
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


def sheet_tab_title(range_a1: str) -> str | None:
    range_a1 = range_a1.strip()
    if "!" in range_a1:
        return range_a1.split("!", 1)[0].strip()
    return None


def split_sheet_tab_and_cell(range_a1: str, cell: str) -> str:
    """Build range_a1 for cell (e.g. A1) on the same tab as range_a1."""
    range_a1 = range_a1.strip()
    if "!" in range_a1:
        tab, _ = range_a1.split("!", 1)
        return f"{tab.strip()}!{cell}"
    return cell


def sheet_cell_a1_is_empty(service: Any, spreadsheet_id: str, range_a1: str) -> bool:
    check_range = split_sheet_tab_and_cell(range_a1, "A1")
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=check_range)
        .execute()
    )
    values = result.get("values") or []
    if not values or not values[0]:
        return True
    return not any(str(c).strip() for c in values[0])


def sheet_last_serial_number(service: Any, spreadsheet_id: str, range_a1: str) -> int:
    """Highest S.No. already in column A (0 when the sheet has no data rows yet)."""
    col_range = split_sheet_tab_and_cell(range_a1, "A:A")
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=col_range)
        .execute()
    )
    values = result.get("values") or []
    if not values:
        return 0

    start_idx = 0
    if values[0]:
        first = str(values[0][0]).strip().lower().rstrip(".")
        if first in ("s.no", "s no"):
            start_idx = 1

    max_sno = 0
    for row in values[start_idx:]:
        if not row:
            continue
        try:
            max_sno = max(max_sno, int(str(row[0]).strip()))
        except ValueError:
            continue
    return max_sno


def sheet_data_row_count(service: Any, spreadsheet_id: str, range_a1: str) -> int:
    col_range = split_sheet_tab_and_cell(range_a1, "A:A")
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=col_range)
        .execute()
    )
    return len(result.get("values") or [])


def sheet_has_header_row(service: Any, spreadsheet_id: str, range_a1: str) -> bool:
    check_range = split_sheet_tab_and_cell(range_a1, "A1")
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=check_range)
        .execute()
    )
    values = result.get("values") or []
    if not values or not values[0]:
        return False
    first = str(values[0][0]).strip().lower().rstrip(".")
    return first in ("s.no", "s no")


def sheet_grid_id(service: Any, spreadsheet_id: str, tab_title: str | None) -> int:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = meta.get("sheets") or []
    if tab_title:
        for sheet in sheets:
            props = sheet.get("properties") or {}
            if props.get("title") == tab_title:
                return int(props["sheetId"])
        print(f"Sheet tab not found: {tab_title}", file=sys.stderr)
        sys.exit(1)
    if not sheets:
        print("Spreadsheet has no tabs.", file=sys.stderr)
        sys.exit(1)
    return int((sheets[0].get("properties") or {})["sheetId"])


def apply_release_date_format(
    service: Any,
    spreadsheet_id: str,
    sheet_id: int,
    start_row_index: int,
    end_row_index: int,
) -> None:
    """Format newly appended release dates as YYYY-MM-DD."""
    if start_row_index >= end_row_index:
        return
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row_index,
                            "endRowIndex": end_row_index,
                            "startColumnIndex": RELEASE_DATE_COLUMN_INDEX,
                            "endColumnIndex": RELEASE_DATE_COLUMN_INDEX + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {
                                    "type": "DATE",
                                    "pattern": "yyyy-mm-dd",
                                }
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                }
            ]
        },
    ).execute()


def apply_row_text_bold(
    service: Any,
    spreadsheet_id: str,
    sheet_id: int,
    start_row_index: int,
    end_row_index: int,
    *,
    bold: bool,
) -> None:
    if start_row_index >= end_row_index:
        return
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row_index,
                            "endRowIndex": end_row_index,
                            "startColumnIndex": 0,
                            "endColumnIndex": SHEET_COLUMN_COUNT,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": bold},
                            }
                        },
                        "fields": "userEnteredFormat.textFormat.bold",
                    }
                }
            ]
        },
    ).execute()


def jira_search_issues(
    base_url: str,
    email: str,
    api_token: str,
    jql: str,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """Return raw issues from JIRA enhanced JQL search API (paginated)."""
    base = base_url.rstrip("/")
    url = f"{base}/rest/api/3/search/jql"
    auth = (email, api_token)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    fields = [
        "summary",
        "status",
        "updated",
        "reporter",
        "issuelinks",
    ]
    issues: list[dict[str, Any]] = []
    next_page_token: str | None = None

    while True:
        body: dict[str, Any] = {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields,
        }
        if next_page_token:
            body["nextPageToken"] = next_page_token

        resp = requests.post(url, json=body, auth=auth, headers=headers, timeout=60)
        if not resp.ok:
            print(f"JIRA error {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(1)

        data = resp.json()
        batch = data.get("issues") or []
        issues.extend(batch)

        if data.get("isLast") or not batch:
            break
        next_page_token = (data.get("nextPageToken") or "").strip() or None
        if not next_page_token:
            break

    return issues


def jira_get_issue_comments(
    base_url: str,
    email: str,
    api_token: str,
    issue_key: str,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """All comments for an issue (paginated)."""
    base = base_url.rstrip("/")
    url = f"{base}/rest/api/3/issue/{issue_key}/comment"
    auth = (email, api_token)
    headers = {"Accept": "application/json"}
    out: list[dict[str, Any]] = []
    start_at = 0
    while True:
        resp = requests.get(
            url,
            auth=auth,
            headers=headers,
            params={"startAt": start_at, "maxResults": max_results},
            timeout=60,
        )
        if not resp.ok:
            print(
                f"JIRA comment error {resp.status_code} for {issue_key}: {resp.text}",
                file=sys.stderr,
            )
            sys.exit(1)
        data = resp.json()
        batch = data.get("comments") or []
        out.extend(batch)
        total = int(data.get("total") or len(out))
        start_at += len(batch)
        if start_at >= total or not batch:
            break
    return out


def saathi_release_calendar_days_newest_first(
    comments: list[dict[str, Any]],
    author_display_name: str,
    text_prefix: str,
) -> list[str]:
    """
    Distinct calendar dates (YYYY-MM-DD) with at least one matching Saathi comment,
    newest day first. Several comments on the same day count as one day (release
    date follows the latest comment that day; only one row for that day).
    """
    want_author = (author_display_name or "").strip()
    want_prefix = normalize_spaces(text_prefix).lower()
    days: set[str] = set()
    for c in comments:
        author = ((c.get("author") or {}).get("displayName") or "").strip()
        if author != want_author:
            continue
        plain = adf_to_plain_text(c.get("body"))
        if not normalize_spaces(plain).lower().startswith(want_prefix):
            continue
        created = (c.get("created") or "").strip()
        if not created:
            continue
        day = jira_updated_date_only(created)
        if day:
            days.add(day)
    return sorted(days, reverse=True)


def linked_tasks_column(fields: dict[str, Any], task_type_name: str) -> str:
    """Linked issues whose type name matches (default Task): 'KEY - summary' per line."""
    want = (task_type_name or "Task").strip().lower()
    parts: list[str] = []
    seen: set[str] = set()
    for link in fields.get("issuelinks") or []:
        for linked in (link.get("inwardIssue"), link.get("outwardIssue")):
            if not linked:
                continue
            lk = (linked.get("key") or "").strip()
            if not lk or lk in seen:
                continue
            inner = linked.get("fields") or {}
            itype = (inner.get("issuetype") or {}).get("name") or ""
            if itype.strip().lower() != want:
                continue
            summ = (inner.get("summary") or "").strip()
            seen.add(lk)
            parts.append(f"{lk} - {summ}" if summ else lk)
    return "\n".join(parts)


def duplicate_column_value(release_days_oldest_first: list[str]) -> str:
    """One row per ticket; list later release dates in the Duplicate cell."""
    if len(release_days_oldest_first) <= 1:
        return ""
    lines = ["Yes"]
    for day in release_days_oldest_first[1:]:
        lines.append(f"Ticket reused for release on - {day}")
    return "\n".join(lines)


def issue_to_rows(
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    release_comment_author: str,
    release_comment_prefix: str,
    linked_task_type: str,
) -> list[list[str]]:
    fields = issue.get("fields") or {}
    status = (fields.get("status") or {}).get("name") or ""
    summary = (fields.get("summary") or "").strip()
    key = issue.get("key") or ""
    reporter = (fields.get("reporter") or {}).get("displayName") or ""
    linked_col = linked_tasks_column(fields, linked_task_type)

    release_days = sorted(
        saathi_release_calendar_days_newest_first(
            comments,
            release_comment_author,
            release_comment_prefix,
        )
    )

    def make_row(release_date_source: str, duplicate_mark: str) -> list[str]:
        return [
            jira_updated_date_only(release_date_source),
            key,
            summary,
            status,
            linked_col,
            reporter,
            duplicate_mark,
        ]

    if not release_days:
        return [make_row(fields.get("updated") or "", "")]

    return [make_row(release_days[0], duplicate_column_value(release_days))]


def dedupe_issues_by_key(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One issue payload per key (last wins) so JQL cannot duplicate the same release ticket."""
    by_key: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for issue in issues:
        k = (issue.get("key") or "").strip()
        if not k:
            continue
        by_key[k] = issue
    return list(by_key.values())


def load_google_sheets_credentials() -> Any:
    """
    Service account: set GOOGLE_APPLICATION_CREDENTIALS to the service account JSON.

    OAuth (no sharing with robot email): set GOOGLE_OAUTH_CLIENT_SECRETS_FILE to the
    OAuth 2.0 *Desktop* client JSON from Google Cloud. First run opens a browser; token
    is saved to GOOGLE_OAUTH_TOKEN_FILE (default: .google-sheets-token.json next to this script).
    """
    oauth_secrets = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "").strip()
    if oauth_secrets:
        if not os.path.isfile(oauth_secrets):
            print(
                f"GOOGLE_OAUTH_CLIENT_SECRETS_FILE not found: {oauth_secrets}",
                file=sys.stderr,
            )
            sys.exit(1)
        token_default = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".google-sheets-token.json")
        token_path = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", "").strip() or token_default
        scopes = list(SCOPES)
        creds: UserCredentials | None = None
        if os.path.isfile(token_path):
            creds = UserCredentials.from_authorized_user_file(token_path, scopes)
        need_save = False
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                need_save = True
            else:
                flow = InstalledAppFlow.from_client_secrets_file(oauth_secrets, scopes)
                creds = flow.run_local_server(port=0)
                need_save = True
        if need_save and creds:
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        return creds

    sa_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if sa_path:
        if not os.path.isfile(sa_path):
            print(
                f"GOOGLE_APPLICATION_CREDENTIALS not found: {sa_path}",
                file=sys.stderr,
            )
            sys.exit(1)
        return service_account.Credentials.from_service_account_file(
            sa_path,
            scopes=SCOPES,
        )

    print(
        "Google auth: set GOOGLE_APPLICATION_CREDENTIALS (service account JSON) "
        "or GOOGLE_OAUTH_CLIENT_SECRETS_FILE (OAuth Desktop client JSON).",
        file=sys.stderr,
    )
    sys.exit(1)


def append_to_sheet(
    spreadsheet_id: str,
    range_a1: str,
    creds: Any,
    values: list[list[Any]],
) -> None:
    if not values:
        print("No rows to write.")
        return

    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    prev_rows = sheet_data_row_count(service, spreadsheet_id, range_a1)
    to_write = list(values)
    write_headers = os.environ.get("GOOGLE_SHEETS_WRITE_HEADERS", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    extra = 0
    if write_headers and sheet_cell_a1_is_empty(service, spreadsheet_id, range_a1):
        to_write = [SHEET_HEADERS] + to_write
        extra = 1

    body = {"values": to_write}
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_a1,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()

    sheet_id = sheet_grid_id(service, spreadsheet_id, sheet_tab_title(range_a1))
    if extra:
        apply_row_text_bold(
            service,
            spreadsheet_id,
            sheet_id,
            prev_rows,
            prev_rows + 1,
            bold=True,
        )
    elif sheet_has_header_row(service, spreadsheet_id, range_a1):
        apply_row_text_bold(service, spreadsheet_id, sheet_id, 0, 1, bold=True)

    data_start = prev_rows + extra
    data_end = prev_rows + len(to_write)
    apply_row_text_bold(
        service,
        spreadsheet_id,
        sheet_id,
        data_start,
        data_end,
        bold=False,
    )
    apply_release_date_format(
        service,
        spreadsheet_id,
        sheet_id,
        data_start,
        data_end,
    )

    if extra:
        print(f"Appended header row + {len(values)} data row(s) to the sheet.")
    else:
        print(f"Appended {len(values)} data row(s) to the sheet.")


def apply_jql_created_days(jql: str, days: int) -> str:
    """Replace created >= -Nd in JIRA_JQL (used by Jenkins / run_sync.sh)."""
    pattern = re.compile(r"created\s*>=\s*-\d+d", re.IGNORECASE)
    replacement = f"created >= -{days}d"
    if pattern.search(jql):
        return pattern.sub(replacement, jql)
    return f"{jql.rstrip()}\nAND {replacement}"


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Sync JIRA release tickets to Google Sheets.")
    parser.add_argument(
        "--days",
        type=int,
        metavar="N",
        help="Override JIRA_JQL created >= -Nd (e.g. 4 for Monday, 3 for Thursday).",
    )
    args = parser.parse_args()

    base_url = _require_env("JIRA_BASE_URL")
    email = _require_env("JIRA_EMAIL")
    token = _require_env("JIRA_API_TOKEN")
    sheet_range = os.environ.get("GOOGLE_SHEETS_RANGE", "A:H").strip()

    default_jql = (
        f'updated >= "{(datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")}" '
        "ORDER BY updated DESC"
    )
    jql = os.environ.get("JIRA_JQL", "").strip() or default_jql

    days = args.days
    if days is None:
        env_days = os.environ.get("JIRA_JQL_DAYS", "").strip()
        if env_days.isdigit():
            days = int(env_days)
    if days is not None:
        jql = apply_jql_created_days(jql, days)
        print(f"Using JQL with created >= -{days}d")

    release_author = os.environ.get("JIRA_RELEASE_COMMENT_AUTHOR", "Saathi").strip()
    release_prefix = os.environ.get(
        "JIRA_RELEASE_COMMENT_PREFIX",
        "Release has been completed  for",
    ).strip()
    linked_task_type = os.environ.get("JIRA_LINKED_TASK_TYPE", "Task").strip()

    issues = dedupe_issues_by_key(jira_search_issues(base_url, email, token, jql=jql))
    rows: list[list[str]] = []
    for issue in issues:
        key = (issue.get("key") or "").strip()
        comments = jira_get_issue_comments(base_url, email, token, key) if key else []
        rows.extend(
            issue_to_rows(
                issue,
                comments,
                release_author,
                release_prefix,
                linked_task_type,
            ),
        )

    if not rows:
        print("No issues returned for the current JQL.")
        return

    rows.sort(key=lambda r: r[0])

    sheet_id = _require_env("GOOGLE_SHEETS_SPREADSHEET_ID")
    creds = load_google_sheets_credentials()
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    last_sno = sheet_last_serial_number(service, sheet_id, sheet_range)
    rows = [[last_sno + i, *row] for i, row in enumerate(rows, start=1)]

    append_to_sheet(sheet_id, sheet_range, creds, rows)


if __name__ == "__main__":
    main()

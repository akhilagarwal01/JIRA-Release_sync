# jira-sheet-sync

Sync JIRA ticket statuses to a Google Sheet.

## Setup

1. **Python 3.11+** recommended.

2. **Create a virtualenv and install deps**

   ```bash
   cd ~/Projects/jira-sheet-sync
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Environment variables** — copy `.env.example` to `.env` and fill in:

   - `JIRA_BASE_URL` — e.g. `https://your-domain.atlassian.net`
   - `JIRA_EMAIL` — your Atlassian account email
   - `JIRA_API_TOKEN` — from [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
   - `JIRA_JQL` — optional; default fetches issues updated in the last 7 days. Example: `project = PROJ AND status != Done`
   - `GOOGLE_SHEETS_SPREADSHEET_ID` — from the sheet URL
   - `GOOGLE_SHEETS_RANGE` — e.g. `Sheet1!A:F` (table includes header row 1; new rows append after existing data)
   - `GOOGLE_APPLICATION_CREDENTIALS` — path to a service account JSON key with **Editor** access to the sheet (share the sheet with the service account email)

4. **Google Cloud**

   - Enable **Google Sheets API** for your project.
   - Create a **service account**, download JSON key, set `GOOGLE_APPLICATION_CREDENTIALS` to that file path.
   - Share the target spreadsheet with the service account client email (e.g. `something@project.iam.gserviceaccount.com`) with Editor role.

5. **Sheet layout** — row 1 should be headers:

   | Key | Summary | Status | Updated | Type | Priority |

   The script appends one row per issue returned by JQL (if the same key appears multiple times in one run, only the last row is kept before writing).

## Run

```bash
source .venv/bin/activate
python sync.py
```

Use cron or GitHub Actions to run on a schedule.

## License

MIT

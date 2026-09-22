# Jenkins setup — JIRA → Google Sheet sync

This guide is for running `sync.py` on a **local Jenkins** instance (e.g. `http://localhost:8080`) with code from **Git**. Each team member clones the repo, keeps secrets **outside** Git, and Jenkins checks out the latest code on every build.

---

## What this job does

| Item | Detail |
|------|--------|
| Script | `sync.py` via `scripts/run_sync.sh` |
| Schedule | Every **Monday ~11:00 AM** (`H 11 * * 1`) |
| JQL window | Last **7 days** (`created >= -7d`) |
| Output | Appends release rows to the shared Google Sheet |

---

## 1. Prerequisites

On the machine where Jenkins runs:

- **Python 3.11+** (`python3 --version`)
- **pip** (`python3 -m pip --version`)
- **Jenkins** running locally (`http://localhost:8080`)
- **Git** access to the team repository
- Network access to **JIRA Cloud** and **Google Sheets API**

---

## 2. Clone the repository

```bash
git clone <your-git-repo-url> jira-sheet-sync
cd jira-sheet-sync
```

Example:

```bash
git clone git@github.com:your-org/jira-sheet-sync.git jira-sheet-sync
cd jira-sheet-sync
```

---

## 3. Files that must NOT go in Git

These are listed in `.gitignore` and must stay on each machine only:

| File | Purpose |
|------|---------|
| `.env` | JIRA credentials, sheet ID, JQL |
| `client-secret.json` | Google OAuth Desktop client |
| `.google-sheets-token.json` | Google refresh token (after first login) |
| `.vendor/` | Python packages (installed per machine) |
| `logs/` | Run logs |

**Never commit API tokens or JSON keys to Git.**

---

## 4. One-time secrets setup (each team member)

### 4.1 Create a secrets folder (outside the repo)

Use a fixed path that Jenkins can read. Recommended:

```bash
sudo mkdir -p /opt/jira-sheet-sync-secrets
sudo chown "$USER:$USER" /opt/jira-sheet-sync-secrets
chmod 700 /opt/jira-sheet-sync-secrets
```

> You can use another path; set `JIRA_SYNC_SECRETS_DIR` in the Jenkins job if you do.

### 4.2 Create `.env`

```bash
cp .env.example /opt/jira-sheet-sync-secrets/.env
nano /opt/jira-sheet-sync-secrets/.env
```

Fill in at minimum:

```env
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=<your-atlassian-api-token>

GOOGLE_SHEETS_SPREADSHEET_ID=<spreadsheet-id-from-url>
GOOGLE_SHEETS_RANGE=JIRA_Sheet!A:H

# Relative paths — jenkins_build.sh copies these files next to sync.py before each run
GOOGLE_OAUTH_CLIENT_SECRETS_FILE=client-secret.json
```

Set `JIRA_JQL` as needed (see `.env.example`).

### 4.3 Add Google OAuth client JSON

Download the **OAuth Desktop** client JSON from Google Cloud Console and copy it:

```bash
cp /path/to/client_secret_....json /opt/jira-sheet-sync-secrets/client-secret.json
chmod 600 /opt/jira-sheet-sync-secrets/client-secret.json
```

**Google Cloud checklist:**

1. Enable **Google Sheets API**
2. Create **OAuth 2.0 Client ID** → type **Desktop app**
3. Download JSON → save as `client-secret.json` in the secrets folder

### 4.4 First Google OAuth login (required once)

Jenkins cannot open a browser. Complete OAuth **once** as your user:

```bash
cd jira-sheet-sync

# Install dependencies
python3 -m pip install --target .vendor -r requirements.txt

# Copy secrets into the project for this one-time run
cp /opt/jira-sheet-sync-secrets/.env .env
cp /opt/jira-sheet-sync-secrets/client-secret.json client-secret.json

# Run sync — browser opens for Google sign-in
export PYTHONPATH="$(pwd)/.vendor"
python3 sync.py --days 7
```

After success, copy the token to the secrets folder:

```bash
cp .google-sheets-token.json /opt/jira-sheet-sync-secrets/.google-sheets-token.json
chmod 600 /opt/jira-sheet-sync-secrets/.google-sheets-token.json
```

Jenkins will reuse this refresh token on scheduled runs (no browser needed).

### 4.5 Allow Jenkins to access secrets and your home (if needed)

Jenkins runs as the `jenkins` user. Ensure it can:

1. **Read** `/opt/jira-sheet-sync-secrets/`
2. **Traverse** your home folder if the repo lives under `/home/<user>/`

```bash
# Secrets readable by jenkins
sudo chown -R jenkins:jenkins /opt/jira-sheet-sync-secrets
# OR keep your user and allow group read:
# sudo chgrp jenkins /opt/jira-sheet-sync-secrets
# chmod 750 /opt/jira-sheet-sync-secrets

# If repo is under /home/yourname — allow traverse only
chmod o+x /home/yourname
```

---

## 5. Create the Jenkins job

### 5.1 New Freestyle project

1. Open **http://localhost:8080**
2. **New Item** → name: `JIRA-Sync` → **Freestyle project** → **OK**

### 5.2 Source Code Management (Git)

1. Select **Git**
2. **Repository URL**: your repo URL  
   e.g. `git@github.com:your-org/jira-sheet-sync.git`
3. **Credentials**: add SSH key or username/password if the repo is private
4. **Branches**: `*/main` (or your default branch)

Jenkins will clone/update code into `$WORKSPACE` on each build.

### 5.3 Build triggers (weekly Monday)

Under **Build Triggers**, check **Build periodically**:

```
H 9 * * 1
```

Runs every Monday around 9:00 AM.

### 5.4 Build step — Execute shell

Under **Build Steps** → **Execute shell**, paste:

```bash
bash "$WORKSPACE/scripts/jenkins_build.sh"
```

This script:

1. Copies secrets from `/opt/jira-sheet-sync-secrets` into the workspace
2. Installs Python deps into `.vendor` if missing
3. Runs `scripts/run_sync.sh 7`

**Optional** — custom secrets path or days window:

```bash
export JIRA_SYNC_SECRETS_DIR=/opt/jira-sheet-sync-secrets
export JIRA_SYNC_DAYS=7
bash "$WORKSPACE/scripts/jenkins_build.sh"
```

### 5.5 Save and test

1. Click **Save**
2. Click **Build Now**
3. Open build → **Console Output**

**Success looks like:**

```
Using JQL with created >= -7d
Appended X data row(s) to the sheet.
=== sync finished at ... ===
Finished: SUCCESS
```

---

## 6. Manual run (without waiting for Monday)

- Jenkins UI → job **JIRA-Sync** → **Build Now**

Or from terminal (same as Jenkins, after `git pull`):

```bash
cd jira-sheet-sync
git pull
bash scripts/jenkins_build.sh
```

Or run sync directly:

```bash
bash scripts/run_sync.sh 7
```

---

## 7. Updating code from Git

When someone pushes changes to the repo:

1. Jenkins **Build Now** (or wait for Monday schedule)
2. Jenkins checks out the latest commit automatically
3. No change needed to the job config

If you are **not** using Git in Jenkins and only use a local folder:

```bash
cd /path/to/jira-sheet-sync
git pull
# Jenkins local-path job picks up changes on next build
```

---

## 8. Troubleshooting

### `Permission denied` on `run_sync.sh`

```bash
chmod +x scripts/run_sync.sh scripts/jenkins_build.sh
```

Use `bash` explicitly in Jenkins:

```bash
bash "$WORKSPACE/scripts/jenkins_build.sh"
```

### `ModuleNotFoundError: No module named 'requests'`

Install deps once in the workspace (jenkins_build.sh does this automatically):

```bash
python3 -m pip install --target .vendor -r requirements.txt
```

### Build FAILURE but sheet updated

Usually Jenkins could not write to `logs/`. The script falls back to `/tmp/jira-sheet-sync-*.log`. Check console for:

```
Note: logging to /tmp/jira-sheet-sync-....log
```

If the build still fails, check the full console for the real exit code from `sync.py`.

### `Missing .google-sheets-token.json`

Run the **one-time OAuth** step in [§4.4](#44-first-google-oauth-login-required-once).

### `Missing /opt/jira-sheet-sync-secrets/.env`

Create the secrets folder and files per [§4](#4-one-time-secrets-setup-each-team-member).

### Jenkins cannot clone private Git repo

Add **Credentials** in Jenkins:

1. **Manage Jenkins** → **Credentials** → **Global** → **Add Credentials**
2. SSH username with private key, or username/password
3. Select that credential in the job’s Git configuration

### Google token expired / revoked

Delete the old token and re-run OAuth manually:

```bash
rm /opt/jira-sheet-sync-secrets/.google-sheets-token.json
# Repeat §4.4
```

### Laptop must be on

Local Jenkins only runs when the machine is awake at the scheduled time.

---

## 9. Quick reference

| Setting | Value |
|---------|--------|
| Jenkins URL | `http://localhost:8080` |
| Job name | `JIRA-Sync` |
| Job type | Freestyle project |
| Git branch | `main` (or your default) |
| Cron schedule | `H 9 * * 1` |
| Build command | `bash "$WORKSPACE/scripts/jenkins_build.sh"` |
| Secrets dir | `/opt/jira-sheet-sync-secrets` |
| JQL days window | `7` (last week) |

### Secrets folder layout

```
/opt/jira-sheet-sync-secrets/
├── .env
├── client-secret.json
└── .google-sheets-token.json
```

### Repo scripts

| Script | Purpose |
|--------|---------|
| `scripts/jenkins_build.sh` | Jenkins entry point (Git checkout + secrets + sync) |
| `scripts/jenkins_daily_task_log.sh` | Jenkins daily task log (gap lookback from last success) |
| `scripts/jenkins_release_mail_draft.sh` | Jenkins manual Gmail draft job |
| `scripts/run_sync.sh` | Runs `sync.py`, optional `--days` via argument |
| `scripts/run_daily_task_log.sh` | Runs `daily_task_log.py` (weekday lookback automatic) |
| `scripts/run_release_mail_draft.sh` | Runs `release_mail_draft.py` with JIRA ID + service name |
| `sync.py` | Main JIRA → Sheet sync |
| `daily_task_log.py` | JIRA → local DailyTaskLogs.xlsx |
| `release_mail_draft.py` | JIRA → Gmail draft |

---

## 10. Alternative: local path (no Git in Jenkins)

If you prefer Jenkins to run a fixed folder (your current setup) instead of checking out Git:

**Do not** configure Git SCM. Use **Execute shell**:

```bash
bash /home/akhilagarwal/Documents/jira-sheet-sync/scripts/run_sync.sh 7
```

Pull code manually before builds:

```bash
cd /home/akhilagarwal/Documents/jira-sheet-sync
git pull
```

For team use, the **Git + `$WORKSPACE`** approach in §5 is recommended so everyone runs the same pipeline from the repo.

---

## 11. Jenkins job — Daily task log (Excel)

Local **DailyTaskLogs.xlsx** update on **Monday–Friday**.

### What this job does

| Item | Detail |
|------|--------|
| Script | `daily_task_log.py` via `scripts/jenkins_daily_task_log.sh` |
| Schedule | **Mon–Fri ~6:00 PM** (`H 18 * * 1-5`) — or trigger manually |
| JQL | `DAILY_TASK_LOG_JQL` in secrets `.env` (separate from `JIRA_JQL`) |
| Output | Appends to `DAILY_TASK_LOG_WORKBOOK` (local `.xlsx`) |

### Jenkins-only lookback (missed days / leave)

`jenkins_daily_task_log.sh` checks the **previous successful Jenkins build date**:

| Situation | Lookback |
|-----------|----------|
| First run ever | Mon = **3** days, Tue–Fri = **1** day |
| Last success was **yesterday** | **1** day |
| Last success was **> 1 day** ago (leave, missed runs) | **Calendar gap** in days |

Example: last success **Tuesday**, you are on leave Wed–Thu, job runs **Friday** → gap = **3** → `--days 3` (covers Wed, Thu, Fri window).

Sources (in order):

1. Jenkins API — `lastSuccessfulBuild/buildTimestamp` for this job (`JOB_NAME` is set automatically)
2. Fallback marker file — `$WORKSPACE/.daily_task_log_last_success` (shared Jenkins repo folder)

Local runs via `run_daily_task_log.sh` **do not** use this gap logic (weekday rules only).

Google OAuth is **not** required for this job.

### Secrets `.env` entries (in addition to JIRA creds)

```env
DAILY_TASK_LOG_WORKBOOK=/home/akhilagarwal/Documents/Projects/jira-sheet-sync/DailyTaskLogs.xlsx
DAILY_TASK_LOG_BOARD_PROJECTS=COR,LINUX,ALPINE
DAILY_TASK_LOG_BOARD_TO_STATUSES=UAT/Staging
DAILY_TASK_LOG_JQL=project = DEVOPS AND updated >= -1d ...
DAILY_TASK_LOG_QA_FROM_STATUS=Deployed on dev-int
DAILY_TASK_LOG_QA_TO_STATUSES=Deployed on-FT,QA Signed OFF
```

Use the **project folder** workbook so local runs and Jenkins update the same file:

```env
DAILY_TASK_LOG_WORKBOOK=/home/akhilagarwal/Documents/Projects/jira-sheet-sync/DailyTaskLogs.xlsx
```

One-time permissions (Jenkins freestyle jobs run as **SYSTEM**, not the `jenkins` user):

```bash
bash scripts/setup_daily_log_permissions.sh
```

This sets project folder `751` (traverse for Jenkins) and `DailyTaskLogs.xlsx` `666` (shared read/write).

Alternative (tighter, run build as `jenkins` user): add to Execute shell:

```bash
sudo -u jenkins env JIRA_SYNC_SECRETS_DIR=/home/akhilagarwal/jira-secrets \
  DRY_RUN="${DRY_RUN:-false}" bash "$WORKSPACE/scripts/jenkins_daily_task_log.sh"
```

Requires passwordless sudo for the Jenkins process user → `jenkins` (via `/etc/sudoers.d/`).

### Create the Jenkins job (step by step)

1. **New Item** → name: `JIRA-Daily-Task-Log` → **Freestyle project** → **OK**
2. Check **This project is parameterized**
3. **Add Parameter** → **Boolean Parameter**:
   - Name: `DRY_RUN`
   - Default: unchecked
   - Description: `Check to preview rows without writing DailyTaskLogs.xlsx`
4. **General** → **Use custom workspace** →  
   `/var/lib/jenkins/workspace/JIRA-Release-Sync`  
   (same shared folder as **Pull JIRA-Sync repository** — see §14)
5. **Source Code Management** → **None** (run **Pull JIRA-Sync repository** first)
6. **Build Triggers** → **Build periodically** (optional):

   ```
   H 18 * * 1-5
   ```

7. **Build Steps** → **Execute shell**:

   ```bash
   export JIRA_SYNC_SECRETS_DIR=/home/akhilagarwal/jira-secrets
   bash "$WORKSPACE/scripts/jenkins_daily_task_log.sh"
   ```

8. **Save** → **Build with Parameters** (or **Build Now** if `DRY_RUN` defaults to false)

**Dry run:** check **DRY_RUN** → **Build**. Console prints candidate rows; Excel is not changed and the last-success marker is not updated.

9. Check **Console Output** for a real run:

   ```
   Previous successful Jenkins build date: 2026-09-10
   Last success was 3 calendar day(s) ago; extended lookback: 3 day(s)
   Appended X row(s) to ... → Jul-Sept 26
   ```

**Optional** — if Jenkins API needs auth:

```bash
export JENKINS_URL=http://localhost:8080
export JENKINS_USER=your-jenkins-user
export JENKINS_API_TOKEN=your-api-token
```

### Slack — custom success message (upsert details)

The default **Slack Notification Plugin** message only shows job name and duration.

After each run, `jenkins_daily_task_log.sh` writes:

```
$WORKSPACE/daily_task_log_slack.properties
```

(with lookback, board/DEVOPS counts, rows appended, sheet tab).

#### Option A — Webhook script (no EnvInject plugin) **recommended**

1. In Slack: create an **Incoming Webhook** for `#daily_task_log` (or use your existing app).
2. Add to **`/home/akhilagarwal/jira-secrets/.env`** (never commit):

   ```env
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
   ```

3. **Pull** latest repo, then in **JIRA-Daily-Task-Log** → **Configure**:
   - **Post-build Actions** → **Execute shell** (runs on success only if you tick “Run only if build succeeds”, or use **Conditional** post-build if available):

   ```bash
   export JIRA_SYNC_SECRETS_DIR=/home/akhilagarwal/jira-secrets
   bash "$WORKSPACE/scripts/post_slack_daily_log_summary.sh"
   ```

4. **Optional:** disable or remove the generic **Slack Notifications** post-build step to avoid **two** messages per build.

This posts a rich message with upsert details from the properties file.

#### Option B — Token Macro Plugin (if EnvInject is unavailable)

1. Install **Token Macro Plugin** (search `Token Macro` in **Manage Jenkins** → **Plugins**).
2. Keep **Slack Notifications** post-build; in **Advanced** → **Custom Message**, try:

   ```
   Daily Task Log #${BUILD_NUMBER}
   ${FILE,path=daily_task_log_slack.properties}
   ```

   (Exact macro names vary by version; see Token Macro help in Jenkins.)

#### Option C — EnvInject (if your Jenkins has it)

Search plugins for **EnvInject** or **Inject environment variables**, inject `$WORKSPACE/daily_task_log_slack.properties`, then use `${DAILY_LOG_RESULT}` etc. in Slack custom message. Many local Jenkins installs do not ship this plugin anymore — use Option A instead.

### Manual test (without Jenkins)

```bash
bash scripts/run_daily_task_log.sh --dry-run
```

### DEVOPS QA column

For each DEVOPS release row, the script checks that **you** did **at least one** of:

1. Commented on the ticket, **or**
2. Moved status from `DAILY_TASK_LOG_QA_FROM_STATUS` to one of `DAILY_TASK_LOG_QA_TO_STATUSES`

If **both** are missing, column **QA Check** is set to `QA done by Peer` / `No QA done` (configurable via `DAILY_TASK_LOG_QA_MISSING_NOTE`).

---

## 12. Jenkins job — Release mail draft (manual trigger)

Creates a **Gmail draft** for one DEVOPS release ticket. **No schedule** — run only when you click **Build With Parameters**.

### What this job does

| Item | Detail |
|------|--------|
| Script | `release_mail_draft.py` via `scripts/jenkins_release_mail_draft.sh` |
| Trigger | **Manual only** (Build with Parameters) |
| Parameters | `JIRA_ID`, `SERVICE_NAME`, optional `DRY_RUN` |
| Secrets | `.env`, `client-secret.json`, `.gmail-token.json` |

### One-time: copy Gmail token to secrets

After running `release_mail_draft.py` once locally (browser OAuth):

```bash
cp .gmail-token.json /home/akhilagarwal/jira-secrets/.gmail-token.json
chmod 600 /home/akhilagarwal/jira-secrets/.gmail-token.json
```

Ensure secrets `.env` includes:

```env
GOOGLE_OAUTH_CLIENT_SECRETS_FILE=client-secret.json
```

### Create the Jenkins job (step by step)

1. **New Item** → name: `JIRA-Release-Mail-Draft` → **Freestyle project** → **OK**
2. Check **This project is parameterized**
3. **Add Parameter** → **String Parameter**:
   - Name: `JIRA_ID` — e.g. `DEVOPS-40011`
   - Name: `SERVICE_NAME` — e.g. `CORE | HomePage`
4. **Add Parameter** → **Boolean Parameter** (optional):
   - Name: `DRY_RUN` — Default: unchecked
5. **General** → optional custom workspace (same path as other jobs)
6. **Source Code Management** → Git (same repo) — or skip if using custom workspace
7. **Build Triggers** — leave **empty** (no cron)
8. **Build Steps** → **Execute shell**:

   ```bash
   export JIRA_SYNC_SECRETS_DIR=/home/akhilagarwal/jira-secrets
   bash "$WORKSPACE/scripts/jenkins_release_mail_draft.sh"
   ```

9. **Save** → **Build with Parameters** → enter JIRA ID and service name

### Manual test (without Jenkins)

```bash
bash scripts/run_release_mail_draft.sh DEVOPS-40011 "CORE | HomePage"
bash scripts/run_release_mail_draft.sh DEVOPS-40011 "CORE | HomePage" --dry-run
```

---

## 13. What to commit to GitHub

Commit **code and docs** only. Never commit secrets or local data.

### Commit to Git

| Path | Purpose |
|------|---------|
| `sync.py` | JIRA → Google Sheet sync |
| `daily_task_log.py` | JIRA → Excel daily task log |
| `release_mail_draft.py` | JIRA → Gmail draft |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for secrets `.env` |
| `.gitignore` | Keeps secrets out of Git |
| `JENKINS.md` | Jenkins setup guide |
| `README.md` | Project overview |
| `scripts/jenkins_build.sh` | Sync Jenkins entry point |
| `scripts/jenkins_daily_task_log.sh` | Daily task log Jenkins entry point |
| `scripts/jenkins_release_mail_draft.sh` | Release mail Jenkins entry point |
| `scripts/run_sync.sh` | Local / wrapper for sync |
| `scripts/run_daily_task_log.sh` | Local / wrapper for daily task log |
| `scripts/run_release_mail_draft.sh` | Local / wrapper for release mail |

### Do NOT commit (keep on your machine / in `jira-secrets`)

| Path | Purpose |
|------|---------|
| `.env` | JIRA tokens, JQL, sheet IDs |
| `client-secret.json` | Google OAuth client |
| `.google-sheets-token.json` | Google Sheets refresh token |
| `.gmail-token.json` | Gmail refresh token |
| `service-account.json` | Optional service account |
| `DailyTaskLogs.xlsx` | Local Excel workbook |
| `.vendor/` | Installed Python packages |
| `logs/` | Run logs |

### Push workflow

```bash
cd /home/akhilagarwal/Documents/Projects/jira-sheet-sync
git add sync.py daily_task_log.py release_mail_draft.py requirements.txt \
  .env.example .gitignore JENKINS.md README.md scripts/
git status   # verify no .env or *.json secrets are staged
git commit -m "Add daily task log and release mail Jenkins jobs"
git push origin main
```

On Jenkins: run **Pull JIRA-Sync repository** before other jobs (see §14).

### Jenkins jobs quick reference

| Job | Schedule | Shell command |
|-----|----------|---------------|
| `Pull JIRA-Sync repository` | Manual / upstream | *(Git SCM only — no shell step)* |
| `JIRA-Release-Sync` | Mon + Thu | see §14 |
| `JIRA-Daily-Task-Log` | Mon–Fri 6 PM | see §14 |
| `JIRA-Release-Mail-Draft` | Manual only | see §14 |

---

## 14. Local Jenkins — Pull job + shared workspace (your setup)

You use **two layers**:

1. **`Pull JIRA-Sync repository`** — only runs Git pull into a **shared folder**
2. **All other jobs** — run scripts from that same folder (no Git in those jobs)

### How it works today

| Job | SCM | Workspace folder | Why it works |
|-----|-----|------------------|--------------|
| `Pull JIRA-Sync repository` | Git → GitHub `master` | **`/var/lib/jenkins/workspace/JIRA-Release-Sync`** (custom workspace) | Git checkout lands here |
| `JIRA-Release-Sync` | None | **`/var/lib/jenkins/workspace/JIRA-Release-Sync`** | Job name matches folder → `$WORKSPACE` is correct automatically |
| `JIRA-Release-Mail-Draft` | None | `/var/lib/jenkins/workspace/JIRA-Release-Mail-Draft` | **Wrong folder** — empty unless you fix below |

The sync job works without a custom workspace setting because Jenkins sets  
`WORKSPACE=/var/lib/jenkins/workspace/<job-name>` and your job is named **`JIRA-Release-Sync`**, same path as the Pull job’s custom workspace.

Other jobs (mail draft, daily task log) have **different names** → different empty workspaces → **No such file or directory**.

### Fix for every downstream job (pick one)

#### Option A — Custom workspace (recommended, matches Pull target)

In **Configure** → **Advanced Project Options** → **Use custom workspace**:

```
/var/lib/jenkins/workspace/JIRA-Release-Sync
```

Then **Execute shell** can stay:

```bash
export JIRA_SYNC_SECRETS_DIR=/home/akhilagarwal/jira-secrets
bash "$WORKSPACE/scripts/jenkins_release_mail_draft.sh"
```

Do the same for `JIRA-Daily-Task-Log` and any future jobs.

#### Option B — Hardcode repo path in Execute shell

No Jenkins UI change; use explicit path:

```bash
export JIRA_SYNC_SECRETS_DIR=/home/akhilagarwal/jira-secrets
bash /var/lib/jenkins/workspace/JIRA-Release-Sync/scripts/jenkins_release_mail_draft.sh
```

### Recommended workflow

**Before any downstream job**, get latest code:

1. Run **`Pull JIRA-Sync repository`** → **Build Now**
2. Then run **`JIRA-Release-Sync`**, **`JIRA-Release-Mail-Draft`**, or **`JIRA-Daily-Task-Log`**

**Optional automation** — on each downstream job, under **Build Triggers**:

- Check **Trigger builds remotely** *or* **Build after other projects are built**
- Projects to watch: `Pull JIRA-Sync repository`

Or chain manually: Pull → Sync / Mail / Daily log.

### Execute shell per job (shared workspace)

**JIRA-Release-Sync** (already working):

```bash
export JIRA_SYNC_SECRETS_DIR=/home/akhilagarwal/jira-secrets
bash "$WORKSPACE/scripts/jenkins_build.sh"
```

**JIRA-Release-Mail-Draft** (after Option A or B):

```bash
export JIRA_SYNC_SECRETS_DIR=/home/akhilagarwal/jira-secrets
bash "$WORKSPACE/scripts/jenkins_release_mail_draft.sh"
```

**JIRA-Daily-Task-Log**:

```bash
export JIRA_SYNC_SECRETS_DIR=/home/akhilagarwal/jira-secrets
bash "$WORKSPACE/scripts/jenkins_daily_task_log.sh"
```

### Verify Pull + shared folder

```bash
ls /var/lib/jenkins/workspace/JIRA-Release-Sync/scripts/jenkins_release_mail_draft.sh
ls /var/lib/jenkins/workspace/JIRA-Release-Sync/release_mail_draft.py
```

Both should exist after a successful **Pull** build.

Secrets folder (same for all jobs):

```
/home/akhilagarwal/jira-secrets/
├── .env
├── client-secret.json
├── .google-sheets-token.json    # sync job
├── .gmail-token.json            # release mail job
# Marker for daily task log gap lookback is in the shared workspace:
# /var/lib/jenkins/workspace/JIRA-Release-Sync/.daily_task_log_last_success
```

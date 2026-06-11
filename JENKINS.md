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
| `scripts/run_sync.sh` | Runs `sync.py`, optional `--days` via argument |
| `sync.py` | Main JIRA → Sheet sync |

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

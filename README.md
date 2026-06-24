# job-mail

A free, daily job-finding agent that runs on GitHub Actions and emails you a digest of
new, relevant, visa-friendly job postings every morning at 7 AM Eastern.

**Sources:** The Muse (no key) · Adzuna (free dev key, optional)  
**Cost:** $0 — GitHub Actions free tier + Gmail SMTP  
**Zero runtime LLM calls** — pure Python + stdlib

---

## How it works

1. Fetches up to 50 results per source each morning.
2. Filters by title keyword and target location.
3. Hard-drops roles requiring citizenship / clearance / ITAR.
4. Flags roles that say "no sponsorship" with ⚠️ but keeps them (legal on current work auth).
5. Deduplicates against `seen_jobs.json` (committed to the repo after each run).
6. Writes `digest.md` (committed, keeps history) and sends you an HTML email.

---

## Setup — step by step

### Step 1 — Fork or clone this repo into your own GitHub account

You must own the repo so GitHub Actions can commit back to it.

```
gh repo fork <url>  # or: git clone … then push to a new repo you own
```

### Step 2 — Get a free Adzuna API key (optional but recommended)

1. Go to <https://developer.adzuna.com/signup>
2. Sign up for a **free** developer account.
3. Once logged in, go to **Dashboard → My Apps → Create a new App**.
4. Note your **App ID** and **App Key**.

> Skip this step if you only want The Muse results — the agent runs fine without Adzuna.

### Step 3 — Create a Gmail App Password

Gmail requires an App Password (not your normal password) for SMTP access.

1. Sign in to your Google account at <https://myaccount.google.com>.
2. Enable **2-Step Verification** if it isn't on already  
   (Security → How you sign in to Google → 2-Step Verification).
3. Go to **Security → 2-Step Verification → App passwords** (scroll to the bottom).
4. Choose **Other (custom name)**, type `job-finder`, click **Generate**.
5. Copy the 16-character password shown (you won't see it again).

### Step 4 — Add GitHub Actions secrets

In your repo on GitHub: **Settings → Secrets and variables → Actions → New repository secret**.

Add these secrets:

| Secret name      | Value                                        |
|------------------|----------------------------------------------|
| `MAIL_USERNAME`  | Your Gmail address, e.g. `you@gmail.com`     |
| `MAIL_PASSWORD`  | The 16-char App Password from Step 3         |
| `MAIL_TO`        | Where to send digests (can be same address)  |
| `ADZUNA_APP_ID`  | From Step 2 (omit entirely to skip Adzuna)   |
| `ADZUNA_APP_KEY` | From Step 2 (omit entirely to skip Adzuna)   |

### Step 5 — Enable GitHub Actions (if needed)

Go to your repo's **Actions** tab. If Actions are disabled, click **I understand my
workflows, go ahead and enable them**.

### Step 6 — Test locally before the first scheduled run

```bash
# 1. Clone your repo
git clone https://github.com/YOUR_USERNAME/job-mail.git
cd job-mail

# 2. Create a virtualenv and install deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Run the agent (Adzuna is optional)
export ADZUNA_APP_ID="your-app-id"     # omit to skip Adzuna
export ADZUNA_APP_KEY="your-app-key"
python job_finder.py

# 4. Inspect outputs
cat digest.md
cat email_body.html   # open in a browser to preview the email
cat seen_jobs.json    # shows all URLs that will be deduped next run
```

### Step 7 — Trigger a manual run on GitHub

Go to **Actions → Daily Job Finder → Run workflow → Run workflow**.

Check the run log to confirm sources are fetching, the commit step succeeds, and the
email step sends (or logs "Email secrets not configured" if you skipped Step 4).

---

## Customize

Edit **`config.yaml`** to change:

- `target_keywords` — titles to match
- `target_locations` — cities/regions to include
- `hard_bar_phrases` — phrases that fully exclude a role
- `no_sponsorship_phrases` — phrases that flag a role with ⚠️ but keep it
- `max_results_per_source` — cap per API source per run
- `send_email_on_empty` — set `false` to suppress the "no new roles" email

### Adjust for EST vs EDT

The workflow runs at **11:00 UTC** which equals **7:00 AM EDT** (summer).
After the clocks fall back in November, open `.github/workflows/jobfinder.yml`
and change the cron line to `"0 12 * * *"` for **7:00 AM EST** (winter).

### Add a new job board

1. Open `job_finder.py`.
2. Subclass `JobSource`, implement `name` and `fetch()`.
3. Append an instance to the `sources` list in `main()`.

The filter, dedup, and email steps require no changes.

---

## File reference

| File | Purpose |
|------|---------|
| `job_finder.py` | Main agent script |
| `config.yaml` | All tunable settings |
| `requirements.txt` | Python dependencies |
| `.github/workflows/jobfinder.yml` | GitHub Actions workflow |
| `seen_jobs.json` | Persisted dedup state (auto-committed) |
| `digest.md` | Latest digest (auto-committed, keeps history) |
| `email_body.html` | Transient email file (gitignored) |

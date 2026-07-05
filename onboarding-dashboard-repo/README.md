# Onboarding Attendance Dashboard

Dark-themed, password-gated, searchable dashboard of Zoom onboarding-call attendance (name, join/leave time, total duration per attendee). Data refreshes automatically every day via GitHub Actions and redeploys on Vercel.

## Files

- `index.html` — the dashboard. Fetches `data.json` at load time.
- `data.json` — attendance data. Overwritten automatically by the workflow below (currently seeded with June-July 2026 data).
- `zoom_pull.py` — pulls attendance from the Zoom Reports API and updates `data.json`.
- `requirements.txt` — Python deps for the script (`requests`).
- `.github/workflows/update-attendance.yml` — runs `zoom_pull.py` daily and commits the result.

## 1. Push this to GitHub

Create a new repo on github.com (private is fine), then from this folder:

```bash
git init
git add .
git commit -m "Initial onboarding attendance dashboard"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

## 2. Add your Zoom API credentials as repo secrets

In your repo: **Settings > Secrets and variables > Actions > New repository secret**. Add these three:

- `ZOOM_ACCOUNT_ID`
- `ZOOM_CLIENT_ID`
- `ZOOM_CLIENT_SECRET`

(From your Server-to-Server OAuth app in the Zoom App Marketplace, under **App Credentials**.)

## 3. Check the workflow settings

Open `.github/workflows/update-attendance.yml` and confirm:

- `--host-email` matches the Zoom account that hosts the onboarding calls (currently `events@op.workada.co`).
- `--topic-filter "Onboarding"` matches how your onboarding meetings are named. Leave it blank to pull every meeting for that host.
- The `cron` schedule (`0 6 * * *` = daily at 06:00 UTC) — edit if you want a different frequency.

You can trigger the first run manually instead of waiting for the schedule: go to the **Actions** tab, choose **Update Zoom attendance data**, and click **Run workflow**. Check that `data.json` gets updated and committed.

## 4. Deploy to Vercel (connected to this repo)

1. Go to vercel.com/new and choose **Import Git Repository**.
2. Select this repo.
3. Framework preset: **Other** (it's plain static HTML/JSON, no build step needed).
4. Deploy.

From now on, every push to `main` — including the automated daily commits from GitHub Actions — triggers a new deployment automatically. The URL stays the same across updates.

## Password

The dashboard is protected by a simple client-side password gate (current password: `Workada`). This is a basic deterrent, not real security — the data is not encrypted and someone with technical knowledge could bypass it by reading the page source or requesting `data.json` directly (that file is **not** covered by the password gate, since the browser needs to fetch it before the gate logic can inspect it).

To change the password: compute a new SHA-256 hash (e.g. `python3 -c "import hashlib; print(hashlib.sha256(b'yournewpassword').hexdigest())"`) and replace the `PASSWORD_HASH` constant near the bottom of `index.html`.

If you need real access control (so `data.json` itself isn't publicly fetchable), consider Vercel's Deployment Protection / password protection feature (Pro plan) or making the whole Vercel project private and giving specific people access, instead of relying on the in-page gate.

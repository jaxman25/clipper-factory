# Clipper Factory

![Clipper Factory logo](assets/logos/icon-512.png)

Paste one YouTube link → get 10 vertical shorts → two auto-post per day at
**19:00 and 21:00 EAT** to Instagram Reels and TikTok, with Telegram as a manual fallback.

This project is a full short-form clip pipeline: download, transcribe, score, reframe, caption,
queue, and publish. The dashboard is a Next.js app; the worker is Python; rendering is ffmpeg.

This readme covers what the repo contains, how the system is meant to run, how to set it up, and
the trade-offs that come with a small, free-tier host.

---

## 1. What Clipper Factory is

- **One link in.** Drop a YouTube URL into the dashboard.
- **Ten shorts out.** The worker pulls the source at up to 1080p, transcribes it, scores the best
  windows, reframes them to 9:16, burns word-pop captions, and queues the results.
- **Two posts a day.** Clips are scheduled to 19:00 and 21:00 EAT and published to Instagram Reels
  and TikTok automatically.
- **Telegram fallback.** If a platform rejects a clip, the scheduler forwards it to Telegram so the
  clip is not lost.
- **Dashboard-first.** Generation, caption editing, rescheduling, logs, and settings all live in the
  web app.

---

## 2. Repository map

| Path | Role |
| --- | --- |
| `app/` | Next.js 14 dashboard: landing, generate, queue, settings, logs |
| `components/studio/` | Shared dashboard components |
| `app/api/` | Dashboard API: generate, clips, telegram, settings, logs, health |
| `lib/` | Shared frontend/web utilities: store, time, auth |
| `backend/main.py` | Clip generator: yt-dlp → faster-whisper → viral scoring → render → queue |
| `backend/viral.py` | Scores 30–45s windows on hooks, questions, speech density, and volume spikes |
| `backend/renderer.py` | 9:16 reframe, drum bed, caption burn-in, thumbnails, exportg |
| `backend/captions.py` | Word-pop captions with hook and outro |
| `backend/broll.py` | Pixabay-style B-roll handling for face-less fallbacks |
| `backend/youtube_uploader.py` | YouTube Shorts posting via OAuth2 |
| `scheduler/scheduler.py` | Posting loop and `--run-once` mode for manual or cron use |
| `telegram_bot/bot.py` | Telegram bot with queue, `/postnow`, `/settings`, and optional scheduler |
| `auto-post/instagram.js` | Meta Graph API Reels upload |
| `auto-post/tiktok_auto.py` | Playwright TikTok Studio upload from a saved session |
| `scripts/make_assets.py` | Synthesizes the drum loop, night ambience, and gradient card |
| `scripts/smoke_render.py` | Offline render smoke test |
| `scripts/build-logos.mjs` | Generates the logo pack from a single SVG |

Generated media lives under `ACF_DATA_ROOT` (`/tmp` on Render):

```
/tmp/downloads      source video, deleted after the job
/tmp/exports        <job>/<clip>.mp4, .jpg, metadata.json
/tmp/queue         ready-to-post clips + JSON metadata
/tmp/posted        published clips
/tmp/state         settings, logs, job progress, tiktok auth
```

---

## 3. At a glance: what the dashboard can do

- Start a clip run from a YouTube link, with a choice of clip modes.
- Watch job progress in the panel and in the activity feed.
- View queued and posted clips, with thumbs, durations, viral scores, and schedule.
- Edit captions, reschedule clips, and re-render individual clips.
- Post clips now, or send a clip to Telegram.
- See runtime health, posting slots, timezone, and integration status.
- Manage slots, platforms, captions, hashtags, and integration tokens from settings.

---

## 4. Clip modes

- **Viral moments** — pick the strongest windows from the transcript.
- **Equal slices** — divide the source into evenly spaced clips.
- **Transform** — AI rewrite plus voiceover, producing platform-shaped outputs at roughly
  21s / 30s / 59s. Transform clips also expose AI metadata variants in the queue so titles,
  descriptions, and hashtag sets can be picked and saved.

---

## 5. What a clip looks like

- Vertical 1080×1920.
- Face-aware cropping that follows the speaker; face-less clips get a cinematic fallback.
- Word-pop captions burned in as 2–3 word cards, with a hook and outro baked in.
- Yellow caption cards, drum bed under the speech, and a branded watermark on outputs.

---

## 6. Deployment options

Two broad paths:

- **Free Render deployment** on a small host, with ephemeral disk and a free-tier scheduler.
- **Local development** using project folders instead of `/tmp`, with a separate bot terminal.

This readme focuses on the parts that matter for both: setup, tokens, queue behavior, and the
limits you will hit on a small host.

---

## 7. Tokens and integrations

Only Telegram is required to boot.

| Key | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | BotFather token |
| `TELEGRAM_CHAT_ID` | Where confirmations and alerts go |
| `PIXABAY_API_KEY` | Free B-roll for face-less clips |
| `IG_USER_ID`, `IG_ACCESS_TOKEN` | Instagram Reels publishing |
| `TIKTOK_AUTH_B64` | Base64 of a Playwright TikTok session |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | YouTube Shorts uploads via OAuth2 |
| `YOUTUBE_SERVICE_ACCOUNT` | Alternative to OAuth refresh token |

Tokens can live as env vars or be saved in the dashboard. On Render, env vars are the only permanent
option.

---

## 8. Telegram bot

Commands:

```
/start                 welcome + your chat id
/clip <youtube url>    generate shorts
/queue                 list queue
/postnow [clip-id]     publish a clip now
/settings              slots, integrations, queue health
/cancel                stop the running generation
```

---

## 9. Instagram, TikTok, and YouTube posting

- **Instagram** uses the Meta Graph API and fetches the clip from a public media route.
- **TikTok** uses a Playwright session because there is no free publishing API.
- **YouTube Shorts** uses OAuth2 and uploads the first clip of a run when credentials are set.

If a platform is not configured, the scheduler skips it and keeps the clip queued.

---

## 10. Local development

```bash
npm run dev
python3 telegram_bot/bot.py

# offline smoke test
npm run smoke

# real generation
python3 backend/main.py --url "https://youtu.be/VIDEO_ID" --num-shorts 3
```

For local work, use a project folder instead of `/tmp`:

```bash
export ACF_DATA_ROOT="$PWD"
```

---

## 11. Design notes

- Captions are baked into the video, so they travel to every platform.
- The scheduler is the source of truth for posting times.
- One job at a time is enforced to keep CPU-bound rendering stable.
- The media route is public by design so Meta can fetch published clips.
- Generated assets are synthesized locally so the repo has no hard network dependency for audio.

---

## 12. Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Cold start is slow | Normal on a free host; keep it awake with a health monitor |
| Queue disappears after restart | Ephemeral disk; post clips or download before restart |
| Job fails to start | Credits, lock, spawn error, or missing Python deps |
| TikTok session missing | Re-create the Playwright session |
| Instagram cannot fetch media | Public base URL, awake service, or route/auth mismatch |

---

## 13. Brand and assets

The mark is a film-strip gear with scissors. The logo pack is generated once from
`scripts/build-logos.mjs`; do not hand-edit the raster files.

Current accent: warm brown and dark navy, with gold caption cards in rendered clips.


---

## 1. What is in the box

| Path | Role |
| --- | --- |
| `backend/main.py` | Clip generator: yt-dlp → faster-whisper → viral detector → ffmpeg render → queue |
| `backend/viral.py` | Scores 30–45 s windows on story keywords, questions, delivery density and volume spikes |
| `backend/renderer.py` | 9:16 reframe (MediaPipe face centring), drum bed, ASS caption burn-in, thumbnails |
| `backend/captions.py` | Word-pop captions, hook (0–2 s) and outro (last 2 s) |
| `backend/broll.py` | Pixabay B-roll for face-less fallbacks |
| `backend/youtube_uploader.py` | YouTube Shorts uploader (OAuth2 refresh token or Service Account) |
| `scheduler/scheduler.py` | APScheduler posting loop **and** `--run-once` mode for cron |
| `telegram_bot/bot.py` | `/start /clip /queue /postnow /settings /cancel`, raw-link handling, optional in-process scheduler |
| `auto-post/instagram.js` | Meta Graph API Reels upload |
| `auto-post/tiktok_auto.py` | Playwright TikTok Studio upload with a saved session |
| `app/` | Next.js 14 dashboard: generate, preview, edit captions, drag-to-reschedule, logs |
| `scripts/make_assets.py` | Synthesises the royalty-free drum loop, night ambience and gradient card |
| `scripts/smoke_render.py` | End-to-end render test that needs no network |

Generated media lives under `ACF_DATA_ROOT` (`/tmp` on Render):

```
/tmp/downloads      source video, deleted after the job
/tmp/exports        <job>/<clip>.mp4, .jpg, metadata.json
/tmp/queue         ready-to-post clips + JSON metadata
/tmp/posted        published clips
/tmp/state         settings, logs, job progress, tiktok auth
```

---

## 3. At a glance: what the dashboard can do

| Constraint | What it means here |
| --- | --- |
| **512 MB RAM** | Keep `WHISPER_MODEL=tiny` and `WHISPER_COMPUTE_TYPE=int8`. Rendering is CPU-heavy; one job at a time is enforced by a lock. A full run (Next + bot + whisper + ffmpeg + Chromium) can still exceed 512 MB; if jobs die, the Starter plan ($7/mo) is the reliable option. |
| **Ephemeral disk** | Everything in `/tmp` disappears on deploy/restart/spin-down. Queue clips are lost. Post clips as they are made, or download the ZIP before a restart. |
| **Spin-down after 15 min** | First request takes ~50 s. Keep the service awake with UptimeRobot (section 9). The in-process scheduler needs the service awake. |
| **750 instance hours/month** | One always-awake web service consumes ~744 h, leaving almost nothing for a second free service. Run everything in the one web service. |
| **Render Cron Jobs are not free** | Minimum $1/month per cron job. The free path is `ACF_ENABLE_SCHEDULER=1` inside the bot. Optional paid cron blocks are in `render.yaml` (commented). |
| **No GPU** | Everything is CPU + `tiny` whisper. A 20-minute source takes roughly 5–15 minutes to become 10 shorts. |
| **Datacenter IPs** | YouTube sometimes demands a sign-in. Set `YTDLP_COOKIES` to a `cookies.txt` path (section 8). |

---

## 3. Deploy with a Render Blueprint (one click)

1. Push this repository to GitHub.
2. Render dashboard → **New → Blueprint** → select the repository.
3. Render reads `render.yaml` and shows one **web service** (`clipper-factory`, Free plan, Docker).
4. Fill the `sync: false` secrets (section 4). Only Telegram is strictly required to boot; Instagram/TikTok can be added later.
5. Click **Apply**. The first Docker build installs Node 18, Python, ffmpeg, Chromium and the AI wheels — expect **8–15 minutes**, and a **512 MB build may be tight**. If the build is OOM-killed, retry once; Render's builders occasionally get more headroom. Upgrading temporarily is the only guaranteed fix.
6. When the service is live, open `/api/health`. You should see:

```json
{ "status": "ok", "queue": 0, "time": "2026-10-22T08:00:00.000Z", "timezone": "Africa/Nairobi" }
```

7. Open `/` for the landing page and `/dashboard` for the app (the old `/settings` URL redirects to
   `/dashboard/settings`). If you set `DASHBOARD_USER`/`DASHBOARD_PASSWORD`, the browser asks for them.

### Environment variables

| Key | Required | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | yes | BotFather token |
| `TELEGRAM_CHAT_ID` | yes | Where confirmations and alerts go |
| `PIXABAY_API_KEY` | optional | Free B-roll for face-less clips |
| `IG_USER_ID`, `IG_ACCESS_TOKEN` | optional | Instagram Reels publishing |
| `IG_GRAPH_VERSION` | optional | Defaults to `v21.0` |
| `TIKTOK_AUTH_B64` | optional | Base64 of a Playwright `auth.json` |
| `TIKTOK_HEADLESS` | optional | `1` uploads headlessly (defaults to `1`) |
| `PUBLIC_BASE_URL` | optional | Public origin for IG's video fetch; defaults to `RENDER_EXTERNAL_URL` |
| `YTDLP_COOKIES` | optional | Path to a Netscape-format `cookies.txt` (YouTube block bypass) |
| `WHISPER_MODEL` | optional | `tiny` (default), `base`, … |
| `ACF_ENABLE_SCHEDULER` | optional | `1` posts at 19:00/21:00 inside the bot process |
| `DASHBOARD_USER`, `DASHBOARD_PASSWORD` | optional | HTTP Basic protection for the dashboard |
| `ADMIN_EMAIL` | recommended | Signed-in email that bypasses credits (the owner's address) |
| `NEXTAUTH_SECRET` | yes for login | Session/JWT signing key: `openssl rand -base64 32` |
| `NEXTAUTH_URL` | yes for login | Public origin: `http://localhost:3000` locally, `https://<service>.onrender.com` on Render |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | optional | "Sign in with Google" (Web application OAuth client) |
| `ACF_USERS_FILE` | optional | User/credit store path; defaults to `data/users.json`, set a persistent-disk path on Render |
| `YOUTUBE_CLIENT_ID` | optional | OAuth2 Client ID (Google Cloud Console → YouTube Data API v3) |
| `YOUTUBE_CLIENT_SECRET` | optional | OAuth2 Client Secret |
| `YOUTUBE_REFRESH_TOKEN` | optional | Offline refresh token from the consent flow |
| `YOUTUBE_SERVICE_ACCOUNT` | optional | Full Service Account JSON (alternative to the refresh token) |
| `YOUTUBE_DEFAULT_LANGUAGE` | optional | Defaults to `en` |
| `YOUTUBE_UPLOAD_SCOPE` | optional | Defaults to `https://www.googleapis.com/auth/youtube.upload` |

**All credentials are environment variables.** Nothing secret is ever written to disk:
`TELEGRAM_*`, `PIXABAY_API_KEY`, `IG_*`, `TIKTOK_AUTH_B64`, the `YOUTUBE_*` keys and `YOUTUBE_API_KEY`
must be set on the deployment (Render → **Environment** tab, or `.env` locally) and the process
restarted. There is no `state/settings.json` any more — Render's disk is wiped on every deploy, so the
dashboard's **Settings** page is read-only: it reports which variables the running process can see
(green check / red cross) and the effective values from `config.json`.

---

## 4. Telegram bot setup

1. Open [@BotFather](https://t.me/BotFather) → `/newbot` → choose a name and username.
2. Copy the token (`123456:ABC…`) into `TELEGRAM_BOT_TOKEN`.
3. Start a chat with your bot and send `/start`.
4. The bot replies with your **chat id**. Put it in `TELEGRAM_CHAT_ID`.
5. Restart the service (or redeploy) and send `/settings` — everything should be green.
6. Optional: create a channel, add the bot as an admin, and use the channel id (`-100…`) as
   `TELEGRAM_CHAT_ID` so confirmations are public. Pinning the queue requires pin rights.
7. The in-process scheduler registers its cron triggers at boot. After changing posting times in the
   dashboard, restart the service so the new slots take effect. A 20-second catch-up after boot posts
   one overdue clip when a slot was missed during a restart.

Commands:

```
/start                 welcome + your chat id
/clip <youtube url>    generate shorts (raw links also work)
/queue                 list queue (and pin the list)
/postnow [clip-id]     publish the oldest clip immediately
/settings              slots, integrations, queue health
/cancel                stop the running generation
```

---

## 5. Instagram Reels (Meta Graph API)

1. Convert the Instagram account to **Business or Creator** and link it to a **Facebook Page**.
2. Open the [Graph API Explorer](https://developers.facebook.com/tools/explorer/).
3. Select your app (create one at developers.facebook.com if needed) and request a token with:
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`.
4. Find the Instagram business account id:

```
GET /me/accounts                → page id
GET /{page-id}?fields=instagram_business_account
```

5. Exchange for a long-lived token (60 days) with the Access Token Debugger → **Extend**.
6. Set `IG_USER_ID` (the Instagram business account id) and `IG_ACCESS_TOKEN`.
7. Set `PUBLIC_BASE_URL` only for a custom domain — Render's `RENDER_EXTERNAL_URL` is used otherwise.
8. The Graph API pulls the video from `https://<your-service>/api/media/<clip-id>`, which is public
   and supports HTTP range requests. Account for processing: the scheduler waits up to 5 minutes
   for the Reels container to reach `FINISHED`.

No token? Instagram is skipped with a log line and the clip still goes to TikTok.

---

## 6. TikTok (Playwright)

TikTok has no free publishing API, so the uploader drives **TikTok Studio** in Chromium.

1. On your laptop:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
python3 auto-post/tiktok_auto.py --login
```

A browser opens. Log in manually (2FA/captcha included), wait for the session cookie, and the
script writes `auth.json`.

2. Base64 the file and set it as `TIKTOK_AUTH_B64`:

```bash
base64 -w0 auth.json            # macOS: base64 -i auth.json | tr -d '\n'
```

3. Redeploy so the env var reaches the scheduler. The script materialises the session at
   `/tmp/state/tiktok_auth.json` and uploads headlessly (`TIKTOK_HEADLESS=1`).

Caveats: TikTok changes its DOM and can request a captcha from datacenter IPs. On failure the
scheduler sends the clip to Telegram so you can post it manually. Re-run `--login` when the
session expires.

---

## 7. YouTube OAuth credentials (auto-post to YouTube Shorts)

The generator downloads the source with `yt-dlp`, then the worker auto-posts the first clip to
YouTube Shorts with `backend/youtube_uploader.py`. That uploader needs OAuth2 credentials from the
Google Cloud Console. Follow these steps once per Google account:

### Step 1 — Go to the Google Cloud Console

1. Open a browser and go to: <https://console.cloud.google.com/>
2. Sign in with the **Google account** that owns the YouTube channel you want to post to.
3. Click the **project selector** (top-left, the "▽" or "Select a project" area).
4. Click **New project** and enter a name like `Clipper Factory Auto-Post`.
5. Click **Create**. Remember the **Project ID** (e.g. `clipper-factory-auto-post`) — you will need it in the next step.

### Step 2 — Enable the YouTube Data API v3

1. In the navigation menu (≡ in the top-left), go to **APIs & Services → Library**.
2. Search for **YouTube Data API v3** and open the result.
3. Click **Enable**.

### Step 3 — Set up the OAuth consent screen

The consent screen is what Google shows the user when they first log in and approve your app.

1. In the navigation menu, go to **APIs & Services → OAuth consent screen**.
2. Select **External** (the default). This lets any Google user with YouTube access approve the app.
3. Click **Create**.
4. Fill in the **App registration** form:

   | Field | What to enter |
   | --- | --- |
   | App name | `Clipper Factory Auto-Post` (or any name) |
   | User support email | Your email or the dashboard's contact email |
   | App logo | Optional — a small icon |
   | App domain | Dashboard URL (e.g. `https://your-domain.com`) — optional but recommended |
   | Developer contact information | Your email |

5. Scroll down and click **Save and Continue**.
6. On the **Scopes** screen, the default scope is:

   ```
   https://www.googleapis.com/auth/youtube.readonly
   ```

   Click **Change** and replace it with:

   ```
   https://www.googleapis.com/auth/youtube.upload
   ```

7. Click **Save and Continue**.
8. On the **Test users** screen, click **Add users** and enter the email address of the Google account you used at the start. That account will be the only one allowed to approve the app during testing.
9. Click **Save and Continue**.
10. Review the summary and click **Back to Dashboard**.
11. On the OAuth consent screen page, make sure **Status** is **Testing** (if it says Production, click **Go to Testing**).

### Step 4 — Create OAuth 2.0 Client IDs (Desktop app)

1. In the navigation menu, go to **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth client ID**.
3. If prompted, set **Application type** to **Desktop app**.
4. Give it a name like `Clipper Factory Auto-Post`.
5. Click **Create**.
6. Copy the **Client ID** and **Client secret** into the dashboard's YouTube block (see below).

> The redirect URI does not matter for this flow — the script uses the refresh token directly, so
> no real HTTP redirect is involved. You can leave the default `http://localhost`.

### Step 5 — Get a refresh token with the Python script

The uploader needs an **offline refresh token**. Run the script below once; it opens your browser,
you log in, and the token is printed to your terminal. (Python 3.10+ only; install the deps first with `pip3 install -r requirements.txt` — no virtualenv needed on a laptop.)

```python
#!/usr/bin/env python3
"""One-time OAuth2 consent flow: prints the YouTube refresh token.

Save as scripts/get_youtube_refresh_token.py and run:
    python3 scripts/get_youtube_refresh_token.py
"""

import os
import sys

# Let this script import helpers from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_CONFIG = {
    "installed": {
        "client_id": os.getenv("YOUTUBE_CLIENT_ID", ""),
        "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET", ""),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    }
}


def main() -> None:
    if not CLIENT_CONFIG["installed"]["client_id"] or not CLIENT_CONFIG["installed"]["client_secret"]:
        print("Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first.")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_config(
        CLIENT_CONFIG, scopes=SCOPES, redirect_uri="http://localhost"
    )
    # The flow will open a browser. After you sign in and grant permissions,
    # the refresh token is printed to the terminal.
    credentials = flow.run_local_server(port=0, prompt="consent")
    print("Refresh token:")
    print(credentials.refresh_token)


if __name__ == "__main__":
    main()
```

1. Open the file, then update the `client_id` and `client_secret` in the script (or set them as `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` in `.env`).
2. Run it from a terminal.
3. A browser window opens. Sign in with the Google account from Step 1 and allow the app.
4. The script prints the refresh token. Copy the entire line into the dashboard's Youtube block:

   | Dashboard field | What to paste |
   | --- | --- |
   | YouTube client ID | The Client ID from Step 4 |
   | YouTube client secret | The Client secret from Step 4 |
   | YouTube refresh token | The printed refresh token |

When all three turn green, `backend/youtube_uploader.py` can upload the first clip in a run to YouTube Shorts automatically.

### Step 6 — (Alternative) Service account JSON

If you would rather not use a browser, create a service account in the Google Cloud Console
(**IAM & Admin → Service Accounts → Create Service Account**), download the JSON key under **Keys**, and paste the whole JSON into the dashboard's `YOUTUBE_SERVICE_ACCOUNT` field. Grant it the `youtube.upload` role. Service accounts cannot use the browser consent flow, so the refresh token is not needed.

---

## 8. Dashboard login (next-auth) and credits

The dashboard signs users in with next-auth. How the pieces fit:

- **`/login`** — email + password (plus a **Continue with Google** button when
  `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` are set). The first sign-in creates the account with
  **5 free credits**; there is no separate sign-up form.
- **`/dashboard`** requires a session on public hosts and redirects anonymous visitors to `/login`.
  On **localhost the login is bypassed entirely**, so you never sign in while testing.
- **`ADMIN_EMAIL`** — the signed-in account matching this email is admin: a golden
  *Admin (Unlimited Credits)* badge and no credit check, ever. You cannot lock yourself out.
- **`/api/generate`** charges public users 1 credit per *accepted* job (validation failures and
  failed spawns are free). At 0 credits it returns `403` with a "buy more" message.
- Optional HTTP Basic (`DASHBOARD_USER`/`DASHBOARD_PASSWORD`) still works as an outer layer;
  `/api/auth` is exempt from the middleware so Google's OAuth redirect back to the app is never
  blocked by a 401.

### Local setup (email/password only)

```bash
# .env
NEXTAUTH_SECRET=$(openssl rand -base64 32)   # sign session cookies
NEXTAUTH_URL=http://localhost:3000
ADMIN_EMAIL=you@gmail.com                     # your admin address
```

Restart, open `http://localhost:3000/login`, and sign in with any email + password — the account is
created on the first attempt and starts with 5 credits.

### Google sign-in (local and Render)

1. Open the [Google Cloud Console](https://console.cloud.google.com/) (any project works — you can
   reuse the one from the YouTube uploader, section 7).
2. **APIs & Services → OAuth consent screen** → *External* → fill in the app name and emails →
   Save. While the app is in **Testing** mode, add your email under **Test users**.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID** → application type
   **Web application**.
4. Add the authorized redirect URIs:

   ```
   http://localhost:3000/api/auth/callback/google                       # local
   https://<your-service>.onrender.com/api/auth/callback/google        # Render
   ```

5. Copy the **Client ID** and **Client secret**:
   - locally → `.env` as `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`, then restart;
   - on Render → **Environment** tab → add both as secrets → redeploy.
6. The **Continue with Google** button appears on `/login` automatically. Before public launch,
   click **Publish app** on the consent screen so any Google account (not just test users) can
   sign in.

### Keeping users and credits across deploys

The store lives in `data/users.json` (gitignored), which survives restarts but not a Render
deploy. Attach a **persistent disk** to the service and set `ACF_USERS_FILE=/data/users.json` to
keep accounts and balances across deploys.

---

## 9. YouTube downloads

`yt-dlp` works for most videos, but YouTube occasionally blocks cloud IPs ("Sign in to confirm
you're not a bot"). When that happens:

1. Export cookies from a logged-in browser (`Get cookies.txt LOCALLY` extension) to `cookies.txt`.
2. Store it privately and set `YTDLP_COOKIES=/path/to/cookies.txt` (on Render you need to bake it
   into a private image or fetch it at boot; env vars cannot hold a file).

Keep sources under ~30 minutes; transcription is the slowest step on a free CPU.

1. Create a free [UptimeRobot](https://uptimerobot.com) account.
2. **Add New Monitor** → HTTP(s) → URL `https://<your-service>.onrender.com/api/health` →
   interval **5 minutes**.
3. Optional alert contact = your email.

Why: a spun-down service cannot run the 19:00/21:00 scheduler or finish a generation job.
The health endpoint is deliberately excluded from dashboard Basic auth.

---

## 9. Optional: Render Cron Jobs (paid)

Render Cron Jobs cost **at least $1/month each** and are not available on the free plan. If you
enable them, uncomment the two cron blocks in `render.yaml`. They run:

```
python3 scheduler/scheduler.py --run-once --time=evening   # 16:00 UTC = 19:00 EAT
python3 scheduler/scheduler.py --run-once --time=night     # 18:00 UTC = 21:00 EAT
```

Important: each cron job is a **separate container with its own `/tmp`**. It will not see the web
service's queue. Unless you attach persistent storage or add object storage, the in-process
scheduler (`ACF_ENABLE_SCHEDULER=1`) is the correct free architecture. The cron flags exist so the
spec is satisfied and so you can add shared storage later.

Both cron and in-process runs use an idempotency guard (`/tmp/state/slots.json`) so a slot cannot
post twice in one day.

---

## 10. Local development

```bash
bash setup.sh                       # node/python deps, ffmpeg, Chromium, assets, .env
# edit .env
npm run dev                         # landing on http://localhost:3000, app on /dashboard
python3 telegram_bot/bot.py         # bot (separate terminal)

# renderer smoke test, no network required:
npm run smoke

# a real generation:
python3 backend/main.py --url "https://youtu.be/VIDEO_ID" --num-shorts 3

# inspect / post the queue:
python3 scheduler/scheduler.py --list
python3 scheduler/scheduler.py --run-once --force --dry-run
```

On a laptop you can use project folders instead of `/tmp`:

```bash
export ACF_DATA_ROOT="$PWD"         # downloads/, exports/, queue/, posted/, state/
```

`config.json` holds defaults (slots, clip length, keyword list, hashtags) and is the only file-based
override — edit it and redeploy. There is no `state/settings.json`: credentials and settings come
from the environment, so nothing is lost when Render wipes `/tmp`.

---

## 11. How a clip is made

1. **Download** — yt-dlp, H.264 ≤1080p, audio merged.
2. **Transcribe** — faster-whisper `tiny` int8 with word timestamps and VAD.
3. **Score** — every 30–45 s window gets points for:
   story keywords (`warned`, `forbidden`, `spirit`, `curse`, `night`, `disappeared`, `village`, …),
   questions, exclamations, first-person hooks, a strong opening line, speech density, complete
   sentence endings, and RMS volume spikes versus the rolling median.
4. **Select** — top 10 non-overlapping windows; missing slots are filled with evenly spaced
   visual-only windows.
5. **Trim** — the cut starts at the first spoken word and ends 0.3 s after the last, so leading and
   trailing silence disappear without desyncing the video.
6. **Reframe** — MediaPipe samples four frames; the crop follows the median face centre. No face
   → blurred fill + centred footage + dark gradient + cached Pixabay B-roll.
7. **Audio** — 1.1× `atempo`/`setpts` (in sync), drum loop at −22 dB, ambience at −30 dB, limiter.
8. **Captions** — ASS word cards (2–3 words), yellow `#FFD700`, black stroke, scale pop, hook at
   0–2 s, outro for the final 2 s.
9. **Export** — 1080×1920 H.264/AAC, faststart, JPEG thumbnail, `metadata.json`.
10. **Queue** — copied to `/tmp/queue` with a `scheduled_for` slot assigned 2 per day.

---

## 12. API map

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/health` | GET | Render health check: `{status, queue, time, …}` |
| `/api/generate` | POST | Start a job `{url, num_shorts}` → `{job_id}` |
| `/api/generate?job_id=` | GET | Job progress/results |
| `/api/clips` | GET | Queue + posted clips and public config |
| `/api/clips` | PATCH | Edit caption/title/schedule by id |
| `/api/clips/[id]/post` | POST | Post one clip now |
| `/api/telegram` | POST | Send a clip to Telegram |
| `/api/download` | GET | ZIP of the queue (or `?id=`) |
| `/api/media/[id]` | GET | Range-capable MP4 (public, used by Instagram) |
| `/api/thumb/[id]` | GET | 540×960 JPEG |
| `/api/settings` | GET | Read-only config, environment-variable status, runtime (**PUT returns 403**) |
| `/api/analytics` | GET/POST | Daily view points behind the dashboard chart |
| `/api/analytics/refresh` | POST | Fold live YouTube view counts into today's chart point |
| `/api/logs` | GET | JSONL log tail |

---

## 13. Troubleshooting

| Symptom | Fix |
| --- | --- |
| Build fails with exit 137 | Render's 512 MB builder ran out of memory. Retry; if it persists, temporarily upgrade the build plan, or bake the image locally and push to a registry. |
| First request takes ~50 s | Normal cold start on the free plan. UptimeRobot prevents it. |
| Queue disappears after deploy | `/tmp` is ephemeral by design. Download the ZIP or post before restarting. |
| `ffmpeg failed` / no audio | Confirm the clip plays locally; some source containers have no audio track — the renderer then uses a silent bed. |
| YouTube bot check | Set `YTDLP_COOKIES` (section 9) **or** `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`/`YOUTUBE_REFRESH_TOKEN` for an OAuth2 upload (section 7). |
| `Missing Python packages` in job status | The image was built before requirements changed. Redeploy. |
| Instagram 400 "media download failed" | `PUBLIC_BASE_URL`/`RENDER_EXTERNAL_URL` wrong, service asleep, or media route blocked by Basic auth (it is excluded). |
| Instagram stuck `IN_PROGRESS` | Reels processing can take minutes; the scheduler waits 5. Check the clip is H.264/AAC (it is) and under 90 s. |
| TikTok `no TikTok session` | `TIKTOK_AUTH_B64` missing/invalid; re-run `--login`. |
| TikTok upload not confirmed | TikTok changed the DOM or served a captcha. A screenshot is written to `/tmp/state/screenshots/`; post manually via Telegram fallback. |
| Queue empty alert at 19:00 | Expected if you have no clips. Send `/clip <url>` or generate from the dashboard. |
| `Another generation job is already running` | One job at a time by design. Wait or delete `/tmp/state/generate.lock` if it is stale (>4 h). |
| Whisper crashes with memory error | Keep `WHISPER_MODEL=tiny`; do not run two jobs. |
| Dashboard is public | Set `DASHBOARD_USER` and `DASHBOARD_PASSWORD` on Render. |

---

## 14. Security notes

- Set dashboard Basic auth before sharing the URL; `/api/clips/[id]/post` can publish to your accounts.
- Tokens saved through the dashboard live in `/tmp` in plaintext (same trust level as env vars).
- Never commit `.env`, `auth.json`, or cookies. They are in `.gitignore`.
- The media route is public by design so Meta can fetch the Reel; filenames are unguessable-ish but
  not secret — do not put private footage in this pipeline.

---

## 15. Deliberate deviations from the original spec

- **OpenMontage captions.** OpenMontage is a clone-and-run agentic video studio, not an importable
  pip/npm caption library, so it cannot be called from this container. `backend/captions.py`
  reproduces its word-level, popped-caption look natively with ASS + ffmpeg. If you want the full
  OpenMontage pipeline, clone its repo separately; it needs an AI coding assistant to drive it.
- **Remotion.** The same caption/overlay result is produced by ffmpeg, so Remotion is not a runtime
  dependency. That keeps the free-tier image smaller and the render deterministic.
- **Render Cron Jobs.** They have a $1/month minimum, so the free deployment uses the in-process
  scheduler. The cron definitions are provided (commented) for parity.
- **`playwright` in requirements.txt.** The file is exactly as specified; the Python Playwright
  package is installed separately in `Dockerfile`/`setup.sh` because the browser driver is not part
  of the mandated list.
- **Assets.** The drum loop and night ambience are synthesised locally instead of downloaded, which
  guarantees licence-free assets with no network dependency. Replace `assets/drum_loop.wav` with
  your own CC0 loop if you prefer a different groove.

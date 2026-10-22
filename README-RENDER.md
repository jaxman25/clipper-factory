# African Clipper Factory — Render deployment guide

Paste one YouTube link → get 10 vertical African-tales shorts → two auto-post per day at
**19:00 and 21:00 EAT** to Instagram Reels and TikTok.

This document covers deployment on Render's **free** plan, every token you need, and the
trade-offs that come with a 512 MB / ephemeral-disk host.

---

## 1. What is in the box

| Path | Role |
| --- | --- |
| `backend/main.py` | Clip generator: yt-dlp → faster-whisper → viral detector → ffmpeg render → queue |
| `backend/viral.py` | Scores 30–45 s windows on story keywords, questions, delivery density and volume spikes |
| `backend/renderer.py` | 9:16 reframe (MediaPipe face centring), drum bed, ASS caption burn-in, thumbnails |
| `backend/captions.py` | Word-pop captions, hook (0–2 s) and outro (last 2 s) |
| `backend/broll.py` | Pexels B-roll for face-less fallbacks |
| `scheduler/scheduler.py` | APScheduler posting loop **and** `--run-once` mode for cron |
| `telegram_bot/bot.py` | `/start /clip /queue /postnow /settings /cancel`, raw-link handling, optional in-process scheduler |
| `auto-post/instagram.js` | Meta Graph API Reels upload |
| `auto-post/tiktok_auto.py` | Playwright TikTok Studio upload with a saved session |
| `app/` | Next.js 14 dashboard: generate, preview, edit captions, drag-to-reschedule, logs |
| `scripts/make_assets.py` | Synthesises the royalty-free drum loop, night ambience and gradient card |
| `scripts/smoke_render.py` | End-to-end render test that needs no network |

Generated media lives under `ACF_DATA_ROOT` (`/tmp` on Render):

```
/tmp/downloads   source video (deleted after the job)
/tmp/exports     <job>/<clip>.mp4, .jpg, metadata.json
/tmp/queue       ready-to-post clips + JSON metadata
/tmp/posted      published clips
/tmp/state       settings, schedule overrides, logs, job progress, tiktok auth
/tmp/whisper_models  faster-whisper model cache
```

---

## 2. Free-tier reality check (read this first)

| Constraint | What it means here |
| --- | --- |
| **512 MB RAM** | Keep `WHISPER_MODEL=tiny` and `WHISPER_COMPUTE_TYPE=int8`. Rendering is CPU-heavy; one job at a time is enforced by a lock. A full run (Next + bot + whisper + ffmpeg + Chromium) can still exceed 512 MB; if jobs die, the Starter plan ($7/mo) is the reliable option. |
| **Ephemeral disk** | Everything in `/tmp` disappears on deploy/restart/spin-down. Queue clips are lost. Post clips as they are made, or download the ZIP before a restart. |
| **Spin-down after 15 min** | First request takes ~50 s. Keep the service awake with UptimeRobot (section 8). The in-process scheduler needs the service awake. |
| **750 instance hours/month** | One always-awake web service consumes ~744 h, leaving almost nothing for a second free service. Run everything in the one web service. |
| **Render Cron Jobs are not free** | Minimum $1/month per cron job. The free path is `ACF_ENABLE_SCHEDULER=1` inside the bot. Optional paid cron blocks are in `render.yaml` (commented). |
| **No GPU** | Everything is CPU + `tiny` whisper. A 20-minute source takes roughly 5–15 minutes to become 10 shorts. |
| **Datacenter IPs** | YouTube sometimes demands a sign-in. Set `YTDLP_COOKIES` to a `cookies.txt` path (section 9). |

---

## 3. Deploy with a Render Blueprint (one click)

1. Push this repository to GitHub.
2. Render dashboard → **New → Blueprint** → select the repository.
3. Render reads `render.yaml` and shows one **web service** (`african-clipper-factory`, Free plan, Docker).
4. Fill the `sync: false` secrets (section 4). Only Telegram is strictly required to boot; Instagram/TikTok can be added later.
5. Click **Apply**. The first Docker build installs Node 18, Python, ffmpeg, Chromium and the AI wheels — expect **8–15 minutes**, and a **512 MB build may be tight**. If the build is OOM-killed, retry once; Render's builders occasionally get more headroom. Upgrading temporarily is the only guaranteed fix.
6. When the service is live, open `/api/health`. You should see:

```json
{ "status": "ok", "queue": 0, "time": "2026-10-22T08:00:00.000Z", "timezone": "Africa/Nairobi" }
```

7. Open the dashboard at `/`. If you set `DASHBOARD_USER`/`DASHBOARD_PASSWORD`, the browser asks for them.

### Environment variables

| Key | Required | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | yes | BotFather token |
| `TELEGRAM_CHAT_ID` | yes | Where confirmations and alerts go |
| `PEXELS_API_KEY` | optional | Free B-roll for face-less clips |
| `IG_USER_ID`, `IG_ACCESS_TOKEN` | optional | Instagram Reels publishing |
| `TIKTOK_AUTH_B64` | optional | Base64 of a Playwright `auth.json` |
| `PUBLIC_BASE_URL` | optional | Public origin for IG's video fetch; defaults to `RENDER_EXTERNAL_URL` |
| `YTDLP_COOKIES` | optional | Path to cookies.txt |
| `WHISPER_MODEL` | optional | `tiny` (default), `base`, … |
| `ACF_ENABLE_SCHEDULER` | optional | `1` posts at 19:00/21:00 inside the bot process |
| `DASHBOARD_USER`, `DASHBOARD_PASSWORD` | optional | HTTP Basic protection for the dashboard |
| `IG_GRAPH_VERSION` | optional | Defaults to `v21.0` |

`TELEGRAM_*`, `PEXELS_API_KEY`, `IG_*` and `TIKTOK_AUTH_B64` can also be entered on the dashboard's
**Settings** page. They are stored in `/tmp/state/settings.json` for immediate use, but Render env
vars always win and are the only permanent option.

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

## 7. YouTube downloads

`yt-dlp` works for most videos, but YouTube occasionally blocks cloud IPs ("Sign in to confirm
you're not a bot"). When that happens:

1. Export cookies from a logged-in browser (`Get cookies.txt LOCALLY` extension) to `cookies.txt`.
2. Store it privately and set `YTDLP_COOKIES=/path/to/cookies.txt` (on Render you need to bake it
   into a private image or fetch it at boot; env vars cannot hold a file).

Keep sources under ~30 minutes; transcription is the slowest step on a free CPU.

---

## 8. Keep it awake with UptimeRobot

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
npm run dev                         # dashboard on http://localhost:3000
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

`config.json` holds defaults (slots, clip length, keyword list, hashtags). Dashboard changes are
written to `state/settings.json` and override it.

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
   → blurred fill + centred footage + dark gradient + cached Pexels B-roll.
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
| `/api/settings` | GET/PUT | Slots, platforms, tokens (write-only), runtime |
| `/api/logs` | GET | JSONL log tail |

---

## 13. Troubleshooting

| Symptom | Fix |
| --- | --- |
| Build fails with exit 137 | Render's 512 MB builder ran out of memory. Retry; if it persists, temporarily upgrade the build plan, or bake the image locally and push to a registry. |
| First request takes ~50 s | Normal cold start on the free plan. UptimeRobot prevents it. |
| Queue disappears after deploy | `/tmp` is ephemeral by design. Download the ZIP or post before restarting. |
| `ffmpeg failed` / no audio | Confirm the clip plays locally; some source containers have no audio track — the renderer then uses a silent bed. |
| YouTube bot check | Set `YTDLP_COOKIES` (section 7). |
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

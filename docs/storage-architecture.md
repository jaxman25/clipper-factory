# Persistent storage architecture — Phase 10, Stage 4

**Status:** research and recommendation only. No application code, configuration,
`.env`, services or data were changed while producing this document.

**Date:** 2026-11-06 · Prices checked against vendor pages on this date; they
change, so re-check before ordering.

---

## 1. What the app stores today

All mutable data is file-based. Python (`backend/paths.py`) and Node
(`lib/store.js`) share `ACF_DATA_ROOT`, which is `/tmp` on Render and has **no
persistence** there. `data/users.json` is separate: it defaults to
`<cwd>/data/users.json` (inside the container image, not `ACF_DATA_ROOT`) unless
`ACF_USERS_FILE` points elsewhere.

| Path (under `ACF_DATA_ROOT`) | Contents | Writers → readers | Regenerable? | Typical size | Survives restart/deploy today? |
|---|---|---|---|---|---|
| `queue/` | `<id>.mp4`, `<id>.jpg`, `<id>.json` (schedule, caption, attempts) | Python generator, scheduler (`_move_to_posted`), Node dashboard/bot | No — renders are expensive | 5–15 MB per clip | **No** |
| `posted/` | same triple after publishing, plus partial/manual markers | scheduler, Node dashboard/downloads | No (published history) | 5–15 MB per clip | **No** |
| `exports/<job>/` | all rendered clips + `metadata.json` per job | Python renderer, Node edit/reset | Re-render from source (costly) | 50–200 MB per job | **No** |
| `downloads/` | downloaded source video/audio | Python, Node clip editor | Yes (re-download) | 50–300 MB per job | **No** |
| `state/jobs/*.json` | job status/progress/log refs | Node API, Python worker | No (operational history) | 1–5 KB each | **No** |
| `state/slots.json` | scheduler claims: `pending`/`posted`/`partial`/`failed`/`abandoned`, platform results, timestamps | Python scheduler only | No — duplicate-post protection | ~5–20 KB | **No** |
| `state/logs.jsonl`, `state/logs/*.log` | activity tail + per-job logs | both runtimes | Yes (disposable) | 1–5 MB/month | **No** |
| `state/analytics.json` | chart points | Node API | Yes | KB | **No** |
| `state/generate.lock` | running-job ownership | Node/Python | Yes | bytes | **No** |
| `data/users.json` (`ACF_USERS_FILE`) | credits + scrypt password hashes | Node only | **No — money-equivalent** | KB | **No on Render deploys** |
| `assets/broll`, `assets/*.wav` | B-roll, music, watermark | read-only | Yes (repo/Pixabay) | repo-sized | Yes (baked into image) |
| Whisper models (`/tmp/whisper_models`) | speech model cache | Python | Yes (re-download) | ~75–500 MB | No (fine) |

Important consequences visible in today's code:

- `state/slots.json` is the **only** thing preventing a duplicate Instagram or
  TikTok post after a crash (Stage 3 protocol). Because Render's `/tmp` is wiped
  on deploy/restart/spin-down, the guarantee currently holds only for the life of
  the process, not across deployments. This is the single most important storage
  requirement.
- A queue JSON and its MP4 must stay in the same directory and move together
  (`shutil.move`/rename). Any storage split must preserve that pairing rule.
- The scheduler is **in-process** (`ACF_ENABLE_SCHEDULER=1`) and posts at
  19:00/21:00 Africa/Nairobi, with `catch_up()` at startup. Free Render spins
  down after 15 idle minutes, which kills the in-process timer.
- `queue.json` files are pruned/removed by `_move_to_posted`; the dashboard
  streams MP4s through `/api/media/[id]`, so disk reads and Render bandwidth
  both matter.

### Sizing assumptions (not measured)

A 30–45 s 1080×1920 H.264 clip is roughly **5–15 MB** (assume 8 MB). One
10-clip job produces ~80 MB of MP4s + thumbnails, plus a 50–300 MB source
download and 10–20 thumbnails. Two jobs/day with no retention:

| Stream | Per day | Per 30 days |
|---|---|---|
| Source downloads | ~300 MB | ~9 GB |
| Exports | ~160 MB | ~4.8 GB |
| Queue + posted copies | ~160 MB | ~4.8 GB |
| Jobs/logs/analytics/users/slots | < 5 MB | < 150 MB |
| **Total without cleanup** | **~0.6 GB** | **~19 GB** |

With the retention rules in §6 (delete downloads after render, exports after the
queue copy is verified, posted kept 30–90 days) steady state is **8–15 GB**.
That is the number to size a disk for; 10 GB is tight, **20 GB** leaves room for
a backlog.

---

## 2. Requirements the storage design must satisfy

| # | Requirement | Why it matters here |
|---|---|---|
| R1 | Scheduler claims survive process crashes, restarts **and deployments** | Prevent duplicate IG/TikTok posts; Stage 3 protocol assumes a durable filesystem |
| R2 | Queue record ↔ video consistency | `_move_to_posted` moves `.mp4/.jpg/.json` as a unit; `listQueue()` ignores a JSON with no usable MP4 |
| R3 | No silent data loss | Users/credits and posted history must not disappear on a deploy |
| R4 | Exact 19:00/21:00 EAT posting | Needs an always-on scheduler; no spin-down, no best-effort cron |
| R5 | Free/cheap MP4 egress | Dashboard downloads and ZIP exports can exceed small bandwidth allowances |
| R6 | Single-instance correctness, clear multi-instance story | A disk can be mounted by one instance only |
| R7 | Backup and recovery | Claims/users are tiny but non-regenerable |

---

## 3. Options compared

### 3.1 Compute + storage hosts

| Option | Storage model | Durable across deploys? | Free? | Price (checked 2026-11-06) | Single / multi-instance | Verdict |
|---|---|---|---|---|---|---|
| **Local machine / NAS** | Local disk (`ACF_DATA_ROOT=$PWD`) | Yes (while machine runs) | Yes | $0 | Single | Best $0 local testing; no 24/7 guarantee |
| **Render free web service** | Ephemeral `/tmp` | **No** | Genuinely free | $0 (750 h/mo, sleeps after 15 min) | Single, no disk | Cannot meet R1/R4 — demo only |
| **Render Starter + disk** | Persistent SSD mounted at `/data` | **Yes** | No | **$7/mo** compute + **$0.25/GB/mo** disk (20 GB = $5) → **$12/mo** | **Single only**; disk blocks scaling and zero-downtime deploys | Recommended managed option |
| **Render Standard + disk** | same | Yes | No | $25 + $5 = **$30/mo** (2 GB RAM, safer for ffmpeg/Whisper) | Single only | Use if Starter OOMs |
| **Render Cron Job** | Ephemeral per run | No disk access at all | No | **$1/mo minimum** per job | — | Cannot share `slots.json`/queue; not usable alone |
| **Oracle Cloud Always Free VM** | 200 GB block/boot + 20 GB object | Yes (block volume) | **Genuinely free, no end date** | **$0** (2 Arm OCPU/12 GB or 2×1 GB AMD, 10 TB egress/mo) | Single VM; more possible | Best $0 always-on, but self-administered |
| **Fly.io Machines + volume** | Volume $0.15/GB/mo | Yes | **No free tier** | 1 GB machine $6.70 + 10 GB volume $1.50 = **$8.20/mo**; 2 GB **$16.39** with 20 GB | Single writer; multi needs DB | Viable but no cheaper than Render |
| **Railway** | Volume $0.15/GB/mo | Yes | $1/mo credit only | Hobby $5 min; RAM $10/GB/mo, CPU $20/vCPU/mo → 1 vCPU/1 GB ≈ **$30+/mo** | Single volume per service | Poor value for this workload |
| **Hetzner Cloud (CX23)** | 40 GB NVMe included | Yes | No | **€5.49/mo** (~$6.40) + 20% backups ≈ **€6.6/mo** | Single VM | Cheapest paid, self-managed |
| **Supabase / Neon (DB-only)** | Managed Postgres | Yes | Free tiers exist | Supabase free 500 MB DB/1 GB files, **pauses after 7 days idle**; Pro $25 | Multi-instance possible | Not a media store; pause risk |

### 3.2 Object storage (for MP4s, backups, future multi-instance)

| Service | Free allowance (ongoing) | Paid rate | Egress | Notes |
|---|---|---|---|---|
| **Cloudflare R2** | **10 GB-month**, 1M Class A, 10M Class B ops/month | **$0.015/GB-mo** | **$0 — always** | S3-compatible; best fit for media if the app is later taught to use object storage |
| **Backblaze B2** | **First 10 GB storage free**, free API calls | **$6.95/TB-mo = $0.00695/GB** | Free up to 3× stored/month, then $0.01/GB; free via partner CDNs | Cheapest storage; S3-compatible |
| **AWS S3 Standard** | No S3 allowance for new accounts (replaced by up to **$200 credits**, 6-month free plan, 12-month expiry) | **$0.023/GB-mo** first 50 TB | $0.09/GB after 100 GB/mo free | Mature but egress is the cost trap |
| **Render disk** | none | $0.25/GB/mo | Counts as Render bandwidth | Block device, not object storage; **one instance only** |
| **Oracle Object Storage** | 20 GB Always Free | paid tier | 10 TB/mo egress in Always Free | Part of the Oracle free account |
| **Supabase Storage** | 1 GB free, 50 MB max upload | Pro: 100 GB then $0.0213/GB | 5 GB cached egress free | Too small / pauses |

### 3.3 Genuinely free vs trial credits vs paid

| Kind | Examples |
|---|---|
| **Genuinely free, ongoing** | Render free web (750 h, sleeps, ephemeral), Cloudflare R2 free tier (10 GB), Backblaze B2 first 10 GB, Oracle Always Free (VM + 200 GB block + 10 TB egress), GitHub Actions for public repos, Supabase free (pauses), Railway $1/mo credit |
| **Trial credits / time-limited** | AWS Free Tier credits (up to $200, 6-month free plan, 12-month expiry), Fly.io $1 credit for 7 days, Railway $5 one-time trial for 30 days, Oracle $300/30-day trial (separate from Always Free), Cloudflare/AWS promotional credits |
| **Paid from day one** | Render Starter $7, Render disk $0.25/GB, Render Cron $1 minimum, Render Standard $25, Fly Machines $2.19+, Railway Hobby $5 min (usage-based), Supabase Pro $25, Hetzner €5.49, S3/R2/B2 beyond free allowances |

A "free tier" that pauses, sleeps, expires, or wipes its disk is **not** free
production capacity for this app. Only Oracle Always Free is a genuine $0
always-on host among the options reviewed.

---

## 4. Estimated monthly costs

Assumes 8–15 GB steady state, 2 posts/day, dashboard downloads of ~5–10 GB/month,
and a single instance.

| Architecture | Compute | Disk | Object/backup | Egress | **Total/month** |
|---|---|---|---|---|---|
| **Local dev machine** | $0 | existing | $0 | home connection | **$0** (not 24/7) |
| **Oracle Always Free VM** | $0 | 200 GB included | 20 GB object included | 10 TB included | **$0** + admin time |
| **Render Starter + 20 GB disk** | $7 | $5 | R2 free ≤10 GB | 5 GB included, then $0.15/GB | **$12–$14** |
| **Render Standard + 20 GB disk** | $25 | $5 | R2 free ≤10 GB | as above | **$30–$32** |
| **Render free + R2** | $0 | none (ephemeral) | $0 ≤10 GB | 5 GB | **$0 but cannot satisfy R1/R4** |
| **Fly 2 GB + 20 GB volume** | $13.39 | $3 | 10 GB snapshots free | $0.02/GB NA/EU | **~$16.50** |
| **Hetzner CX23 + backups** | €5.49 | 40 GB included | +20% | 20 TB included (EU) | **~€6.6 (~$7.7)** |
| **Railway 1 vCPU/1 GB + 20 GB** | ~$30 usage | $3 | — | $0.05/GB | **~$33+** |
| **Object storage only (R2/B2), 15 GB** | — | — | **$0.03–$0.08** (10 GB free) | free/cheap | **~$0** |
| **S3 Standard, 15 GB + 50 GB egress** | — | — | $0.35 | $0 (within 100 GB free) | **~$0.35** |

Cheapest way to meet every requirement: **Oracle Always Free ($0)**. Cheapest
managed way: **Render Starter + 20 GB disk (~$12/mo)**, accepting 512 MB RAM and
a brief stop-the-world deploy. If generation OOMs on 512 MB, Render Standard
($30) or Hetzner (~€6.6 self-managed) are better value.

---

## 5. Recommended architectures

### 5.1 $0 local-testing budget (no cloud)

Run everything on the development machine or a spare always-on box:

```bash
export ACF_DATA_ROOT="$PWD"          # queue/, posted/, exports/, state/, downloads/
export ACF_USERS_FILE="$PWD/data/users.json"
export TZ=Africa/Nairobi
npm run dev
python3 telegram_bot/bot.py          # in-process scheduler posts at 19:00/21:00 EAT
```

- Files stay on the local filesystem, so the Stage 3 claim protocol and atomic
  moves work exactly as designed.
- The machine must be awake at 19:00 and 21:00 EAT; `catch_up()` covers a missed
  slot only after the process starts.
- Backups: `rclone`/`robocopy` `state/slots.json`, `data/users.json` and the
  `queue/` + `posted/` manifests to another drive or a free R2/B2 bucket. Do not
  back up whole MP4 trees; the manifests + source URLs are enough to regenerate.
- This is the correct $0 choice for testing. It is **not** a production SLA:
  laptop sleep, Windows updates, and ISP outages will miss slots.

### 5.2 Recommended low-cost production (managed)

**Render Starter (1 instance) + 20 GB persistent disk** mounted at `/data`,
scheduler kept in-process:

```
/data/queue/            /data/state/slots.json
/data/posted/           /data/state/jobs/
/data/exports/          /data/state/logs.jsonl
/data/downloads/        /data/users.json
```

Environment (documentation only — not changed in this stage):

| Variable | Value | Reason |
|---|---|---|
| `ACF_DATA_ROOT` | `/data` | All mutable media/state on the disk |
| `ACF_USERS_FILE` | `/data/users.json` | Balances survive deploys |
| `TZ` | `Africa/Nairobi` | Keeps 19:00/21:00 local |
| `ACF_ENABLE_SCHEDULER` | `1` | In-process scheduler is the only exact-time option on one service |
| `PUBLIC_BASE_URL` etc. | unchanged | — |

Cost: **$12/mo** (plus egress beyond 5 GB at $0.15/GB). Add a free R2 bucket
(≤10 GB) for offsite copies of `slots.json`, `users.json`, job/queue manifests
and optionally posted MP4s older than 7 days.

Why not Render Cron for the two slots: cron runs in a separate container with
its own ephemeral filesystem and **cannot attach a disk** (Render docs). It would
neither see the queue nor share claims, and two cron jobs at 16:00/18:00 UTC add
$2/mo while leaving duplicate protection broken. Keep the in-process scheduler,
which remains a single writer to a single disk.

Deploy windows: avoid 18:55–19:10 and 20:55–21:10 EAT. Render stops the old
instance before starting the new one when a disk is attached (no zero-downtime
deploys), so a deploy in that window loses the exact slot; `catch_up()` will post
the overdue clip on boot, which is late but not lost.

### 5.3 $0 always-on alternative

**Oracle Cloud Always Free** Ampere VM (2 OCPU/12 GB, 200 GB block volume,
10 TB egress) running the same Docker image, with `/data` on the block volume.
This is the only genuinely free, always-on configuration that satisfies R1 and
R4. Costs are operational: account verification/credit card, capacity
availability in the home region, OS patching, TLS/reverse proxy, Docker
upgrades, monitoring, and the well-known risk that idle Always Free instances can
be reclaimed — so keep independent backups. Good for a hobby deployment; not a
managed SLA.

### 5.4 What not to do

- Do **not** run the scheduler in a Render Cron job or GitHub Actions while the
  queue/claims live on the web service's `/tmp`; they are separate filesystems.
- Do **not** mount the disk at `/app` (Docker `WORKDIR`) — it would shadow the
  application code. Use `/data`.
- Do **not** split the web service and a scheduler worker onto two services
  sharing "the same disk"; Render disks attach to exactly one service and are
  not shared.
- Do **not** grow the disk instead of cleaning up `downloads/` and old
  `exports/`; Render disks can only be increased, never decreased.

---

## 6. Retention and consistency rules

| Data | Retention | Notes |
|---|---|---|
| `downloads/` | delete after successful render (or 24 h) | largest, fully regenerable |
| `exports/<job>/` | 7 days after queue copy verified, or until downloaded | regenerable but expensive |
| `queue/` | until posted/abandoned; cap ~30 clips | JSON+MP4 move together |
| `posted/` | 30–90 days on disk, archive older to R2/B2 | keep manifests indefinitely |
| `state/slots.json` | keep all recent records (pruning already caps terminal records) | never prune unresolved claims |
| `state/jobs/` | 90 days | small |
| `state/logs.jsonl` | rotate/truncate at ~10 MB | `/api/logs` only shows a tail |
| `users.json` | forever, versioned backups | non-regenerable |
| Whisper models | cache in `/tmp` | re-downloadable |

Consistency rules that must survive any migration:

1. Write `queue/<id>.json` **after** `queue/<id>.mp4` is fully written and
   fsynced; readers already ignore zero-byte MP4s.
2. Move queue → posted as a unit (current `_move_to_posted`) or, with object
   storage later, copy the MP4 first, verify, then update metadata, then delete
   the old object.
3. A slot claim is written before the first platform call (Stage 3). On a
   persistent disk this now survives deploys; never delete `slots.json` as part
   of a deploy or cleanup.
4. Single writer: only one scheduler process may own `/data`. Two instances on
   one disk is not possible on Render; two VMs on one NFS/SMB share is also
   unsafe without a lock (NFS rename/fsync semantics differ).

---

## 7. Backup and recovery

What is actually irreplaceable: `data/users.json` (balances/auth) and
`state/slots.json` (claim history). Everything else is regenerable, expensive,
or disposable.

| Item | Backup | Frequency | RPO | Restore |
|---|---|---|---|---|
| `users.json` | R2/B2 copy + local encrypted copy | hourly (cron) or daily | 1 h–24 h | copy back to `ACF_USERS_FILE`; verify user count/credits |
| `slots.json` | R2/B2 copy **before and after each slot** (3 writes/day, KB) | per slot | ≤ 1 slot | copy back; do not reset — Stage 3 recovery retires abandoned claims |
| `posted/` + queue manifests | R2/B2 (`*.json` only) | daily | 24 h | rebuild dashboard; media may be gone |
| MP4s | Render daily disk snapshot (7-day retention per docs) and/or R2 archive | daily | 24 h | download/restore from R2 or snapshot |
| `state/jobs`, logs, analytics | not backed up (or daily) | — | — | disposable |
| Code/config | git | on change | — | redeploy |

Render automatically snapshots a persistent disk every 24 h and keeps snapshots
for 7 days; a full-disk restore rolls back everything after the snapshot, which
can resurrect already-posted clips or lose today's claims. For that reason the
tiny `slots.json` offsite copy is more valuable than the disk snapshot. Test a
restore into a scratch directory at least once per quarter: copy `users.json`
and `slots.json` back, start the scheduler with `--dry-run`/`--list`, and confirm
no queue item is claimed twice.

RTO target: under 1 hour for a degraded single-instance service (redeploy +
restore two small files); MP4 history is best-effort.

---

## 8. Single-instance vs multi-instance

**Today (single instance, local disk):** all invariants are simple — one
process tree, one filesystem, atomic rename, one `slots.json`. Stage 3's
`pending`/`abandoned` protocol is correct on a persistent filesystem. This is
the recommended mode.

**Render persistent disk:** explicitly single-service, single-instance. Attaching
a disk disables scaling and zero-downtime deploys. A second instance cannot see
the disk.

**To run multiple instances (not recommended for this app yet)** you would need
all three:

1. **Shared media store** — object storage (R2/B2/S3) for queue/posted MP4s and
   thumbnails; metadata in a DB or the object store.
2. **Atomic claims** — a transactional store: Postgres unique insert on
   `(slot_key)` or advisory lock; Redis `SET NX PX`; only then is a claim
   race-free across processes. Object-store conditional writes differ by
   provider and are not a drop-in replacement for a database.
3. **Singleton scheduler or leader election** — otherwise two instances both
   fire 19:00 and 21:00, and only the atomic claim saves you (and even then one
   instance's post may fail post-claim).

Users/credits would also move to the DB to avoid last-writer-wins on
`users.json` (two Node instances currently read-modify-write the whole file).
Multi-instance is a Stage 5+ architecture change, not a storage swap.

**Free-tier multi-instance is impossible** for this app: disks cannot be shared,
free Render instances cannot scale, and the free DB tiers pause.

---

## 9. Migration risks and rollback

| Risk | Impact | Mitigation |
|---|---|---|
| Attaching a disk requires a **paid** Render plan | Service change | Do it during a quiet window; budget $7+ |
| Disk deploy is **not zero-downtime** (old instance stops first) | Brief outage; may miss 19:00/21:00 | Deploy outside 18:55–19:10 / 20:55–21:10 EAT; startup `catch_up()` posts overdue clips late |
| Forgetting `ACF_USERS_FILE=/data/users.json` | Every user resets to 5 credits on next sign-in | Copy file first, set env, verify `/api/credits` before opening traffic |
| Forgetting `ACF_DATA_ROOT=/data` (or setting it only for one runtime) | Python and Node write to different roots; empty dashboard, split state | Both runtimes read the same env var; verify `/api/health` + `/api/clips` after cutover |
| Mounting the disk at `/app` | Shadowed application code | Mount at `/data` only |
| Existing `/tmp` data not copied | Queue/posted history and pending claims lost at cutover | Export queue ZIP or copy `queue/`, `posted/`, `state/`, `data/users.json` over the shell before switching; do it when the queue is empty if possible |
| Disk cannot be shrunk | Over-provisioning cost | Start at 20 GB; clean `downloads/`/`exports/` |
| Snapshot restore is all-or-nothing | Duplicate or missing posts after rollback | Keep per-slot `slots.json` offsite copies; restore those, not the whole disk, for claim recovery |
| Changing `TZ`/`posting_times` during migration | Posts at wrong times | Leave `TZ=Africa/Nairobi`, `posting_times` 19:00/21:00 unchanged |
| Scheduler disabled by env drift | No posts at all | Keep `ACF_ENABLE_SCHEDULER=1`; check startup log "Internal scheduler started: 19:00, 21:00" |
| Later object-storage migration | Queue JSON references local paths; `/api/media` streams from disk | Do it in a later stage with dual-read: upload first, keep local copy, then switch readers; never move metadata before the object exists |
| Vendor/region | Disk latency/egress costs | Single region close to users; bandwidth allowance 5 GB on Hobby |

**Rollback plan**

1. Keep the current image/env values and the previous deploy available.
2. If the disk service misbehaves, redeploy the previous image (disk remains
   mounted; data is intact). Do **not** delete the disk.
3. If the disk must be detached, first copy `/data` out (shell/SCP), then switch
   `ACF_DATA_ROOT` back to `/tmp` only with the queue drained; otherwise clips
   and claims written to `/data` since cutover are orphaned.
4. Restore only from a snapshot if disk corruption is proven; prefer restoring
   `users.json`/`slots.json` from offsite copies to avoid rolling back posts.
5. After any rollback, run `scheduler/scheduler.py --list` and inspect
   `slots.json` for `pending` claims before allowing the next slot.

---

## 10. What cannot work reliably on free hosting

1. **Exact 19:00/21:00 Africa/Nairobi posting.** Render free sleeps after 15
   idle minutes, killing the in-process scheduler. GitHub Actions cron is
   best-effort, minimum 5-minute granularity, and documented to run late —
   sometimes hours late under load; runners are ephemeral and cannot share the
   queue or claims.
2. **Durable scheduler claims.** Render's free filesystem is wiped on every
   redeploy, restart and spin-down. Without a persistent disk, `slots.json`
   disappears, so the app can neither prevent duplicates nor remember what it
   posted. Render free cannot attach a disk at all.
3. **Queue consistency.** A free Render container restarted mid-job loses
   `queue/*.mp4`/`.json`; the dashboard then shows an empty queue even though
   clips were generated.
4. **User balances.** `data/users.json` lives in the container image, so a
   deploy reverts to the baked-in file (or no users at all).
5. **Render Cron as a workaround.** Cron jobs are paid, run in separate
   containers, and cannot attach a disk; they cannot see the queue or share
   claims. Two cron jobs would give you a scheduler that posts the wrong (empty)
   queue and no duplicate protection.
6. **Free managed databases as a claim store.** Supabase free pauses after a
   week of inactivity; Render's free Postgres expires after 30 days; free tiers
   generally lack backups/PITR. A paused DB at 19:00 means no claim check and no
   post (or, worse, a post without a claim).
7. **Serverless platforms (Vercel/Netlify/Cloudflare Workers).** No persistent
   local filesystem, short execution limits, and no Python/ffmpeg/Playwright
   pipeline as shipped.
8. **Free VM tiers from Fly/Railway.** Fly has no free tier (only a 7-day $1
   trial). Railway's free plan is a $1/month credit with 0.5 GB volume, far
   below this workload. Oracle Always Free is the exception: genuinely free and
   always-on, but you operate it.

**Bottom line:** a reliable free deployment requires either accepting a
non-managed free VM (Oracle Always Free) or relaxing the exactness/durability
requirements. For a managed service, budget roughly **$12–$30/month** on Render
(disk included), or ~€6.6 on a self-managed Hetzner VM.

---

## 11. Decision summary

| Goal | Choice |
|---|---|
| $0 local testing | Local disk (`ACF_DATA_ROOT=$PWD`), local scheduler, offsite copies of `users.json`/`slots.json` |
| $0 always-on (accept ops) | Oracle Cloud Always Free VM + 200 GB block volume + Docker |
| Recommended production | Render Starter/Standard + **20 GB persistent disk at `/data`**, `ACF_DATA_ROOT=/data`, `ACF_USERS_FILE=/data/users.json`, in-process scheduler, R2 free tier for offsite state/backups |
| Future scale | Object storage (R2/B2) for media + Postgres/Redis for atomic claims + leader election; not part of Stage 4 |
| Never | Free Render disk claims, Render Cron sharing `/tmp`, GitHub Actions as an exact scheduler, serverless for ffmpeg |

---

## 12. Sources (checked 2026-11-06)

- Render pricing: <https://render.com/pricing> — disks $0.25/GB-mo; Starter $7;
  Standard $25; Hobby bandwidth 5 GB then $0.15/GB.
- Render persistent disks: <https://render.com/docs/disks> — paid services only;
  one service instance; daily snapshots, 7-day retention; no zero-downtime
  deploys with a disk; cron jobs cannot use disks.
- Render free tier: <https://render.com/docs/free> — 15-minute spin-down, 750
  hours, ephemeral filesystem, no persistent disks, no scaling.
- Render cron jobs: <https://render.com/docs/cronjobs> — $1/month minimum; no
  persistent disk access.
- Cloudflare R2 pricing: <https://developers.cloudflare.com/r2/pricing> — 10
  GB-month free; $0.015/GB-mo; free egress; 1M Class A / 10M Class B free.
- Backblaze B2 pricing: <https://www.backblaze.com/cloud-storage/pricing> — first
  10 GB free; $6.95/TB-mo; egress free up to 3× stored, then $0.01/GB.
- AWS S3 pricing and Free Tier: <https://aws.amazon.com/s3/pricing> — $0.023/GB-mo
  Standard; $0.09/GB egress after 100 GB; up to $200 credits for new accounts
  since July 2025.
- Oracle Always Free resources:
  <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm>
  — 200 GB block/boot, 20 GB object, 10 TB/month egress, no end date.
- Fly.io pricing: <https://fly.io/docs/about/pricing> — no free tier; 1 GB
  machine $6.70/mo; volumes $0.15/GB-mo; snapshots $0.08/GB with 10 GB free.
- Railway pricing: <https://docs.railway.com/pricing> — Free $1/mo credit,
  0.5 GB volume; Hobby $5 minimum; RAM $10/GB-mo, CPU $20/vCPU-mo.
- Supabase pricing: <https://supabase.com/pricing> — free 500 MB DB/1 GB storage,
  pauses after 1 week idle; Pro $25.
- Hetzner Cloud pricing: <https://www.hetzner.com/cloud> — CX23 €5.49/mo, 40 GB
  NVMe, backups +20%.
- GitHub Actions billing and schedule behavior:
  <https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions>
  (2,000 free minutes for private repos; public repos free) and GitHub's
  documented best-effort `schedule` event with delays under load.

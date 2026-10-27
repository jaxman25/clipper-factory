/**
 * Filesystem store shared with the Python workers.
 *
 * Everything lives under ACF_DATA_ROOT (/tmp on Render) so both runtimes agree
 * on where downloads, exports, queue, posted and state are. JSON writes are
 * atomic because Python and Node read the same files concurrently.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

export const ROOT = process.cwd();
export const DATA_ROOT = process.env.ACF_DATA_ROOT || '/tmp';
export const DIRS = {
  root: DATA_ROOT,
  downloads: path.join(DATA_ROOT, 'downloads'),
  exports: path.join(DATA_ROOT, 'exports'),
  queue: path.join(DATA_ROOT, 'queue'),
  posted: path.join(DATA_ROOT, 'posted'),
  state: path.join(DATA_ROOT, 'state'),
  jobs: path.join(DATA_ROOT, 'state', 'jobs'),
  logs: path.join(DATA_ROOT, 'state', 'logs'),
  assets: path.join(ROOT, 'assets'),
};

export const LOCK_FILE = path.join(DIRS.state, 'generate.lock');

export const DEFAULTS = {
  timezone: 'Africa/Nairobi',
  posting_times: ['19:00', '21:00'],
  shorts_per_video: 10,
  clip_min_seconds: 30,
  clip_max_seconds: 45,
  playback_speed: 1.1,
  drum_volume_db: -22,
  caption_color: '#FFD700',
  caption_words_per_card: 3,
  hook_seconds: 2,
  outro_seconds: 2,
  outro_text: 'Follow for more African tales',
  hashtags: '#AfricanTales #AfricanFolklore #Storytime #Shorts',
  platforms: { instagram: true, tiktok: true },
  youtube_auto_post: false,
};

export const TOKEN_KEYS = [
  'TELEGRAM_BOT_TOKEN',
  'TELEGRAM_CHAT_ID',
  'PIXABAY_API_KEY',
  'IG_USER_ID',
  'IG_ACCESS_TOKEN',
  'TIKTOK_AUTH_B64',
  // YouTube OAuth credentials for auto-posting to YouTube Shorts
  'YOUTUBE_CLIENT_ID',
  'YOUTUBE_CLIENT_SECRET',
  'YOUTUBE_REFRESH_TOKEN',
  'YOUTUBE_SERVICE_ACCOUNT',
];

export function ensureDirs() {
  for (const dir of [DIRS.downloads, DIRS.exports, DIRS.queue, DIRS.posted, DIRS.jobs, DIRS.logs]) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

export function readJSON(file, fallback = {}) {
  try {
    const raw = fs.readFileSync(file, 'utf8');
    const data = JSON.parse(raw);
    return data ?? fallback;
  } catch (err) {
    return fallback;
  }
}

const RETRY_CODES = new Set(['EPERM', 'EACCES', 'EBUSY', 'ENOTEMPTY']);

/** Synchronous sleep (rename retries happen inside sync writeJSON). */
function sleepSync(ms) {
  try {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
  } catch (err) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      /* busy-wait fallback where Atomics.wait is unavailable */
    }
  }
}

/** Unique, collision-resistant temp name beside the destination file. */
function uniqueTmp(file) {
  return `${file}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`;
}

function renameWithRetry(tmp, file) {
  let delay = 20;
  for (let attempt = 0; ; attempt += 1) {
    try {
      fs.renameSync(tmp, file);
      return;
    } catch (err) {
      // Windows maps a destination briefly held open by a reader (WinError 32)
      // onto EPERM/EACCES/EBUSY; our readers are millisecond-long JSON parses,
      // so a few short retries clear the window. Anything else propagates.
      if (!err || !RETRY_CODES.has(err.code) || attempt >= 4) throw err;
      sleepSync(delay);
      delay = Math.min(delay * 2, 500);
    }
  }
}

export function writeJSON(file, data) {
  const payload = JSON.stringify(data, null, 2); // throws before touching disk
  fs.mkdirSync(path.dirname(file), { recursive: true });
  // Unique temp file created with O_EXCL in the destination directory: two
  // writers (Python worker, bot, dashboard) can never open the same temp
  // file, which is what raised WinError 32 with the old shared .node.tmp.
  const tmp = uniqueTmp(file);
  let fd;
  try {
    fd = fs.openSync(tmp, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY, 0o644);
    fs.writeFileSync(fd, payload);
    fs.fsyncSync(fd);
    fs.closeSync(fd);
    fd = undefined;
    renameWithRetry(tmp, file);
  } finally {
    if (fd !== undefined) {
      try {
        fs.closeSync(fd);
      } catch (err) {
        /* already closed */
      }
    }
    // Only this call's uniquely named temp file is ever removed here.
    try {
      if (fs.existsSync(tmp)) fs.rmSync(tmp, { force: true });
    } catch (err) {
      /* best effort */
    }
  }
  return data;
}

/**
 * Create a file only when it does not exist yet (returns true when created).
 *
 * Used by the API to initialise a job *before* spawning the worker: if a
 * record is already on disk - the worker has started writing progress - the
 * existing document wins and is never clobbered by the initial 0% state.
 */
export function writeJSONIfAbsent(file, data) {
  if (fs.existsSync(file)) return false;
  writeJSON(file, data);
  return true;
}

/** Read-modify-write merge: only the given keys change, all others survive. */
export function updateJSON(file, patch) {
  const current = readJSON(file, null);
  if (!current) return null;
  const next = { ...current, ...patch };
  writeJSON(file, next);
  return next;
}

/**
 * Read generate.lock as {job_id, pid, created_at}; legacy locks hold a bare
 * job id. Returns null when missing/unreadable - an unreadable lock is owned
 * by nobody and is never treated as free to delete.
 */
export function readLock() {
  let raw;
  try {
    raw = fs.readFileSync(LOCK_FILE, 'utf8').trim();
  } catch (err) {
    return null;
  }
  if (!raw) return null;
  try {
    const info = JSON.parse(raw);
    if (info && typeof info === 'object' && !Array.isArray(info) && Object.keys(info).length) {
      return info;
    }
  } catch (err) {
    /* legacy plain-text lock: fall through */
  }
  return { job_id: raw };
}

/** Delete generate.lock only when it belongs to jobId (true when removed). */
export function removeLockIfOwned(jobId) {
  const info = readLock();
  if (!info || !jobId || String(info.job_id || '') !== String(jobId)) return false;
  try {
    fs.rmSync(LOCK_FILE, { force: true });
    return true;
  } catch (err) {
    return false;
  }
}

const ACTIVE_STATUSES = new Set(['running', 'queued']);

/**
 * Conditional transition running/queued -> cancelled. Returns the updated
 * job, or null when nothing active was cancelled (missing document or an
 * already-terminal state), which makes repeated cancels idempotent.
 */
export function markJobCancelledIfActive(jobId, message = 'Cancelled by user') {
  const file = path.join(DIRS.jobs, `${jobId}.json`);
  const job = readJSON(file, null);
  if (!job || !ACTIVE_STATUSES.has(job.status)) return null;
  const next = { ...job, status: 'cancelled', message, updated_at: new Date().toISOString() };
  writeJSON(file, next);
  return next;
}

/**
 * Conditional transition running -> error for workers that died before they
 * could report. Never overwrites a done/cancelled/error document and never
 * creates a job document, so a phantom "running" job cannot survive a failed
 * start while a finished or cancelled one keeps its real end state.
 */
export function markJobErrorIfRunning(jobId, { message, error }) {
  const file = path.join(DIRS.jobs, `${jobId}.json`);
  const job = readJSON(file, null);
  if (!job || job.status !== 'running') return null;
  const next = {
    ...job,
    status: 'error',
    stage: 'error',
    message,
    error,
    updated_at: new Date().toISOString(),
  };
  writeJSON(file, next);
  return next;
}

export function loadSettings() {
  return readJSON(path.join(DIRS.state, 'settings.json'), {});
}

export function saveSettings(patch) {
  const current = loadSettings();
  const next = { ...current, ...patch };
  writeJSON(path.join(DIRS.state, 'settings.json'), next);
  return next;
}

export function loadConfig() {
  const fileConfig = readJSON(path.join(ROOT, 'config.json'), {});
  const overrides = loadSettings();
  const cfg = { ...DEFAULTS, ...fileConfig, ...overrides };
  delete cfg.tokens; // never hand secrets to a page/API consumer
  if (!Array.isArray(cfg.posting_times) || !cfg.posting_times.length) {
    cfg.posting_times = DEFAULTS.posting_times;
  }
  return cfg;
}

/** Tokens saved in the dashboard win only when the process env has none. */
export function runtimeTokens() {
  const tokens = loadSettings().tokens;
  return tokens && typeof tokens === 'object' ? tokens : {};
}

export function getSecret(key) {
  return String(process.env[key] || runtimeTokens()[key] || '').trim();
}

export function tokenStatus() {
  const status = {};
  for (const key of TOKEN_KEYS) {
    const value = getSecret(key);
    status[key] = { configured: Boolean(value), hint: value ? `…${value.slice(-4)}` : '' };
  }
  return status;
}

export function childEnv(extra = {}) {
  const env = { ...process.env, ...extra };
  for (const [key, value] of Object.entries(runtimeTokens())) {
    if (value && !process.env[key]) env[key] = String(value);
  }
  return env;
}

function enrich(item, state) {
  const id = String(item.id || '');
  return {
    ...item,
    state,
    media_url: `/api/media/${encodeURIComponent(id)}`,
    thumb_url: `/api/thumb/${encodeURIComponent(id)}`,
    download_url: `/api/media/${encodeURIComponent(id)}?download=1`,
  };
}

export function listQueue() {
  ensureDirs();
  const items = [];
  for (const name of fs.readdirSync(DIRS.queue)) {
    if (!name.endsWith('.json')) continue;
    const item = readJSON(path.join(DIRS.queue, name), null);
    if (!item || !item.id) continue;
    const video = path.join(DIRS.queue, item.file || `${item.id}.mp4`);
    if (!fs.existsSync(video)) continue;
    items.push(enrich(item, 'queued'));
  }
  items.sort((a, b) => String(a.scheduled_for || '9').localeCompare(String(b.scheduled_for || '9')));
  return items;
}

export function listPosted() {
  ensureDirs();
  const items = [];
  for (const name of fs.readdirSync(DIRS.posted)) {
    if (!name.endsWith('.json')) continue;
    const item = readJSON(path.join(DIRS.posted, name), null);
    if (!item || !item.id) continue;
    items.push(enrich(item, 'posted'));
  }
  items.sort((a, b) => String(b.posted_at || '').localeCompare(String(a.posted_at || '')));
  return items;
}

export function findClip(id) {
  ensureDirs();
  for (const state of ['queue', 'posted']) {
    const dir = DIRS[state];
    const meta = readJSON(path.join(dir, `${id}.json`), null);
    const video = path.join(dir, `${id}.mp4`);
    if (fs.existsSync(video)) {
      return { id, state, video, meta: meta || {}, thumb: path.join(dir, `${id}.jpg`) };
    }
  }
  // Exports are the source of truth if a clip was never queued (or was cleaned).
  try {
    for (const job of fs.readdirSync(DIRS.exports)) {
      const video = path.join(DIRS.exports, job, `${id}.mp4`);
      if (fs.existsSync(video)) {
        const manifest = readJSON(path.join(DIRS.exports, job, 'metadata.json'), {});
        const meta = (manifest.clips || []).find((clip) => clip.id === id) || {};
        return { id, state: 'export', video, meta, thumb: path.join(DIRS.exports, job, `${id}.jpg`) };
      }
    }
  } catch (err) {
    /* exports dir may not exist yet */
  }
  return null;
}

export function updateClip(id, patch) {
  for (const state of ['queue', 'posted']) {
    const file = path.join(DIRS[state], `${id}.json`);
    if (!fs.existsSync(file)) continue;
    const item = readJSON(file, {});
    const next = { ...item, ...patch, updated_at: new Date().toISOString() };
    writeJSON(file, next);
    return { state, item: next };
  }
  return null;
}

export function listJobs(limit = 10) {
  ensureDirs();
  try {
    return fs
      .readdirSync(DIRS.jobs)
      .filter((name) => name.endsWith('.json'))
      .map((name) => readJSON(path.join(DIRS.jobs, name), null))
      .filter(Boolean)
      .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
      .slice(0, limit);
  } catch (err) {
    return [];
  }
}

export function readJob(id) {
  return readJSON(path.join(DIRS.jobs, `${id}.json`), null);
}

export function appendLog(level, message, extra = {}) {
  const entry = { ts: new Date().toISOString(), level, message, ...extra };
  try {
    ensureDirs();
    fs.appendFileSync(path.join(DIRS.state, 'logs.jsonl'), `${JSON.stringify(entry)}\n`);
  } catch (err) {
    /* logging must never break a request */
  }
  return entry;
}

export function readLogs(limit = 120) {
  try {
    const raw = fs.readFileSync(path.join(DIRS.state, 'logs.jsonl'), 'utf8');
    return raw
      .trim()
      .split('\n')
      .slice(-limit)
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch (err) {
          return null;
        }
      })
      .filter(Boolean)
      .reverse();
  } catch (err) {
    return [];
  }
}

export function sanitizeId(value) {
  return String(value || '').replace(/[^A-Za-z0-9_-]/g, '');
}

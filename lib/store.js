/**
 * Filesystem store shared with the Python workers.
 *
 * Everything lives under ACF_DATA_ROOT (/tmp on Render) so both runtimes agree
 * on where downloads, exports, queue, posted and state are. JSON writes are
 * atomic because Python and Node read the same files concurrently.
 */
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
};

export const TOKEN_KEYS = [
  'TELEGRAM_BOT_TOKEN',
  'TELEGRAM_CHAT_ID',
  'PIXABAY_API_KEY',
  'IG_USER_ID',
  'IG_ACCESS_TOKEN',
  'TIKTOK_AUTH_B64',
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

export function writeJSON(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.node.tmp`;
  // Use openSync with O_TRUNC|O_CREAT to overwrite any existing .tmp file
  // with explicit 0644 permissions, so cross-language readers (e.g. Python
  // workers) can overwrite it atomically. Node's default umask is usually
  // 022, but explicit permissions avoid permission-denied errors when the
  // file already exists and is owned by a different process.
  const fd = fs.openSync(tmp, fs.constants.O_CREAT | fs.constants.O_TRUNC | fs.constants.O_WRONLY, 0o644);
  fs.writeSync(fd, JSON.stringify(data, null, 2));
  fs.closeSync(fd);
  fs.renameSync(tmp, file);
  return data;
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

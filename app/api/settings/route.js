import {
  DIRS,
  TOKEN_KEYS,
  listPosted,
  listQueue,
  loadConfig,
  loadSettings,
  saveSettings,
  tokenStatus,
} from '@/lib/store';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const NUMERIC = [
  'shorts_per_video',
  'clip_min_seconds',
  'clip_max_seconds',
  'playback_speed',
  'drum_volume_db',
  'caption_words_per_card',
  'hook_seconds',
  'outro_seconds',
];

function normalizeTimes(value) {
  const list = Array.isArray(value) ? value : String(value || '').split(',');
  const out = [];
  for (const entry of list) {
    const match = /^(\d{1,2}):(\d{2})$/.exec(String(entry).trim());
    if (!match) continue;
    const hour = Number(match[1]);
    const minute = Number(match[2]);
    if (hour > 23 || minute > 59) continue;
    out.push(`${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`);
  }
  return [...new Set(out)].sort();
}

function publicSettings() {
  const saved = { ...loadSettings() };
  delete saved.tokens;
  return saved;
}

export async function GET() {
  return Response.json(
    {
      config: loadConfig(),
      saved: publicSettings(),
      tokens: tokenStatus(),
      queue: listQueue().length,
      posted: listPosted().length,
      runtime: {
        data_root: DIRS.root,
        whisper_model: process.env.WHISPER_MODEL || 'tiny',
        scheduler_in_bot: ['1', 'true', 'yes'].includes(
          String(process.env.ACF_ENABLE_SCHEDULER || '').toLowerCase()
        ),
        public_base_url: Boolean(process.env.PUBLIC_BASE_URL || process.env.RENDER_EXTERNAL_URL),
      },
    },
    { headers: { 'Cache-Control': 'no-store' } }
  );
}

export async function PUT(request) {
  let body;
  try {
    body = await request.json();
  } catch (err) {
    return Response.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  const patch = {};
  const input = body.settings || {};

  if (input.posting_times !== undefined) {
    const times = normalizeTimes(input.posting_times);
    if (!times.length) return Response.json({ error: 'Add at least one HH:MM posting time' }, { status: 400 });
    patch.posting_times = times;
  }
  if (input.timezone !== undefined) {
    try {
      new Intl.DateTimeFormat('en-US', { timeZone: input.timezone });
      patch.timezone = input.timezone;
    } catch (err) {
      return Response.json({ error: 'Unknown time zone' }, { status: 400 });
    }
  }
  for (const key of NUMERIC) {
    if (input[key] === undefined) continue;
    const value = Number(input[key]);
    if (!Number.isFinite(value)) return Response.json({ error: `${key} must be a number` }, { status: 400 });
    patch[key] = value;
  }
  if (input.caption_color !== undefined) {
    if (!/^#[0-9A-Fa-f]{6}$/.test(input.caption_color)) {
      return Response.json({ error: 'caption_color must look like #FFD700' }, { status: 400 });
    }
    patch.caption_color = input.caption_color;
  }
  if (input.outro_text !== undefined) patch.outro_text = String(input.outro_text).slice(0, 120);
  if (input.hashtags !== undefined) patch.hashtags = String(input.hashtags).slice(0, 300);
  if (input.platforms !== undefined) {
    patch.platforms = {
      instagram: Boolean(input.platforms.instagram),
      tiktok: Boolean(input.platforms.tiktok),
    };
  }

  const current = loadSettings();
  if (body.tokens || body.clearTokens) {
    const tokens = { ...(current.tokens || {}) };
    for (const key of TOKEN_KEYS) {
      const value = body.tokens?.[key];
      if (typeof value === 'string' && value.trim()) tokens[key] = value.trim();
    }
    for (const key of body.clearTokens || []) {
      if (TOKEN_KEYS.includes(key)) delete tokens[key];
    }
    patch.tokens = tokens;
  }

  saveSettings(patch);
  return Response.json({ ok: true, saved: publicSettings(), tokens: tokenStatus() });
}

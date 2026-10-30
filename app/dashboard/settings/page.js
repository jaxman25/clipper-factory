'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Loader2, X } from 'lucide-react';
import ActivityFeed, { ClearLogsButton, RestoreLogsButton } from '@/components/studio/ActivityFeed';
import { Input, PageHeader, SectionCard, Switch } from '@/components/studio/ui';
import { cn } from '@/lib/cn';

const USER_CONFIG_KEY = 'userConfig';

/**
 * Credentials are environment-only (Render / .env), so this page reports
 * whether the running process can see each variable instead of offering
 * inputs that could not be persisted anywhere durable.
 */
const ENV_FIELDS = [
  { key: 'TELEGRAM_BOT_TOKEN', label: 'Telegram bot token', hint: 'From @BotFather' },
  { key: 'TELEGRAM_CHAT_ID', label: 'Telegram chat id', hint: 'Send /start to the bot to see it' },
  { key: 'PIXABAY_API_KEY', label: 'Pixabay API key', hint: 'Free at pixabay.com/api/docs' },
  { key: 'IG_USER_ID', label: 'Instagram user id', hint: 'Business account linked to a Page' },
  { key: 'IG_ACCESS_TOKEN', label: 'Instagram access token', hint: 'Meta long-lived token' },
  { key: 'TIKTOK_AUTH_B64', label: 'TikTok auth.json (base64)', hint: 'Output of --login' },
  { key: 'YOUTUBE_CLIENT_ID', label: 'YouTube client ID', hint: 'From Google Cloud Console (OAuth2)' },
  { key: 'YOUTUBE_CLIENT_SECRET', label: 'YouTube client secret', hint: 'From Google Cloud Console' },
  { key: 'YOUTUBE_REFRESH_TOKEN', label: 'YouTube refresh token', hint: 'From OAuth2 playground or auth flow' },
  { key: 'YOUTUBE_API_KEY', label: 'YouTube Data API key', hint: 'Live view counts for the analytics chart' },
];

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="shrink-0 text-subtle">{label}</dt>
      <dd className="truncate text-right font-mono text-[11px] text-fg/80">{String(value)}</dd>
    </div>
  );
}

function platformState(config) {
  if (!config) {
    return { instagram: false, tiktok: false, youtube_auto_post: false };
  }
  return {
    instagram: Boolean(config.platforms?.instagram ?? config.instagram),
    tiktok: Boolean(config.platforms?.tiktok ?? config.tiktok),
    youtube_auto_post: Boolean(config.platforms?.youtube_auto_post ?? config.youtube_auto_post),
  };
}

export default function SettingsPage() {
  const [data, setData] = useState(null);
  const [note, setNote] = useState(null);
  const [saving, setSaving] = useState(false);
  const mountTime = useRef(Date.now());

  const [form, setForm] = useState({
    timezone: '',
    posting_times: '',
    shorts_per_video: '',
    clip_min_seconds: '',
    clip_max_seconds: '',
    playback_speed: '',
    drum_volume_db: '',
    caption_words_per_card: '',
    outro_text: '',
    hashtags: '',
    caption_color: '',
    hook_seconds: '',
    outro_seconds: '',
    instagram: true,
    tiktok: true,
    youtube_auto_post: true,
  });

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/settings', { cache: 'no-store' });
      if (!response.ok) throw new Error('Could not load settings');
      setData(await response.json());
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const config = data?.config || null;

  // Initialise form state from localStorage when the server config has landed.
  // If nothing is stored yet, fall back to the committed config.json values.
  useEffect(() => {
    if (!config) return;
    if (mountTime.current) mountTime.current = Date.now();

    let parsed = null;
    try {
      const raw = typeof window !== 'undefined' ? window.localStorage.getItem(USER_CONFIG_KEY) : null;
      if (raw) parsed = JSON.parse(raw);
    } catch (err) {
      /* stale JSON in localStorage is treated as absent */
    }

    if (parsed && typeof parsed === 'object' && parsed !== null) {
      setForm({
        timezone: typeof parsed.timezone === 'string' ? parsed.timezone : config.timezone,
        posting_times: Array.isArray(parsed.posting_times) && parsed.posting_times.length
          ? parsed.posting_times.join(', ')
          : config.posting_times?.join(', ') || '',
        shorts_per_video: typeof parsed.shorts_per_video === 'number' || /^[0-9]+$/.test(String(parsed.shorts_per_video))
          ? String(parsed.shorts_per_video)
          : String(config.shorts_per_video ?? ''),
        clip_min_seconds: typeof parsed.clip_min_seconds === 'number' || /^[0-9.]+$/.test(String(parsed.clip_min_seconds))
          ? String(parsed.clip_min_seconds)
          : String(config.clip_min_seconds ?? ''),
        clip_max_seconds: typeof parsed.clip_max_seconds === 'number' || /^[0-9.]+$/.test(String(parsed.clip_max_seconds))
          ? String(parsed.clip_max_seconds)
          : String(config.clip_max_seconds ?? ''),
        playback_speed: typeof parsed.playback_speed === 'number' || /^[0-9.]+$/.test(String(parsed.playback_speed))
          ? String(parsed.playback_speed)
          : String(config.playback_speed ?? ''),
        drum_volume_db: typeof parsed.drum_volume_db === 'number' || /^[0-9.-]+$/.test(String(parsed.drum_volume_db))
          ? String(parsed.drum_volume_db)
          : String(config.drum_volume_db ?? ''),
        caption_words_per_card: typeof parsed.caption_words_per_card === 'number' || /^[0-9]+$/.test(String(parsed.caption_words_per_card))
          ? String(parsed.caption_words_per_card)
          : String(config.caption_words_per_card ?? ''),
        outro_text: typeof parsed.outro_text === 'string' ? parsed.outro_text : (config.outro_text || ''),
        hashtags: typeof parsed.hashtags === 'string' ? parsed.hashtags : (config.hashtags || ''),
        caption_color: typeof parsed.caption_color === 'string' ? parsed.caption_color : (config.caption_color || ''),
        hook_seconds: typeof parsed.hook_seconds === 'number' || /^[0-9.]+$/.test(String(parsed.hook_seconds))
          ? String(parsed.hook_seconds)
          : String(config.hook_seconds ?? ''),
        outro_seconds: typeof parsed.outro_seconds === 'number' || /^[0-9.]+$/.test(String(parsed.outro_seconds))
          ? String(parsed.outro_seconds)
          : String(config.outro_seconds ?? ''),
        instagram: typeof parsed.instagram === 'boolean' ? parsed.instagram : platformState(config).instagram,
        tiktok: typeof parsed.tiktok === 'boolean' ? parsed.tiktok : platformState(config).tiktok,
        youtube_auto_post: typeof parsed.youtube_auto_post === 'boolean' ? parsed.youtube_auto_post : platformState(config).youtube_auto_post,
      });
    } else {
      setForm({
        timezone: config.timezone || '',
        posting_times: config.posting_times?.join(', ') || '',
        shorts_per_video: String(config.shorts_per_video ?? ''),
        clip_min_seconds: String(config.clip_min_seconds ?? ''),
        clip_max_seconds: String(config.clip_max_seconds ?? ''),
        playback_speed: String(config.playback_speed ?? ''),
        drum_volume_db: String(config.drum_volume_db ?? ''),
        caption_words_per_card: String(config.caption_words_per_card ?? ''),
        outro_text: config.outro_text || '',
        hashtags: config.hashtags || '',
        caption_color: config.caption_color || '',
        hook_seconds: String(config.hook_seconds ?? ''),
        outro_seconds: String(config.outro_seconds ?? ''),
        instagram: platformState(config).instagram,
        tiktok: platformState(config).tiktok,
        youtube_auto_post: platformState(config).youtube_auto_post,
      });
    }
  }, [config]);

  const update = useCallback((key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  }, []);

  const parseForm = useCallback(() => {
    const num = (value, fallback) => {
      if (value === '' || value == null) return fallback;
      const n = Number(value);
      return Number.isFinite(n) ? n : fallback;
    };
    return {
      timezone: form.timezone || config?.timezone || 'Africa/Nairobi',
      posting_times: form.posting_times
        ? form.posting_times.split(',').map((s) => s.trim()).filter(Boolean)
        : config?.posting_times || ['19:00', '21:00'],
      shorts_per_video: num(form.shorts_per_video, config?.shorts_per_video ?? 10),
      clip_min_seconds: num(form.clip_min_seconds, config?.clip_min_seconds ?? 30),
      clip_max_seconds: num(form.clip_max_seconds, config?.clip_max_seconds ?? 45),
      playback_speed: num(form.playback_speed, config?.playback_speed ?? 1.1),
      drum_volume_db: num(form.drum_volume_db, config?.drum_volume_db ?? -22),
      caption_words_per_card: num(form.caption_words_per_card, config?.caption_words_per_card ?? 3),
      outro_text: form.outro_text || config?.outro_text || 'Follow for more African tales',
      hashtags: form.hashtags || config?.hashtags || '#AfricanTales #AfricanFolklore #Storytime #Shorts',
      caption_color: form.caption_color || config?.caption_color || '#FFD700',
      hook_seconds: num(form.hook_seconds, config?.hook_seconds ?? 2),
      outro_seconds: num(form.outro_seconds, config?.outro_seconds ?? 2),
      platforms: {
        instagram: Boolean(form.instagram),
        tiktok: Boolean(form.tiktok),
        youtube_auto_post: Boolean(form.youtube_auto_post),
      },
    };
  }, [form, config]);

  const save = useCallback(async () => {
    setSaving(true);
    setNote(null);
    try {
      if (typeof window === 'undefined') throw new Error('Browser storage unavailable');
      window.localStorage.setItem(USER_CONFIG_KEY, JSON.stringify(parseForm()));
      setNote({
        kind: 'ok',
        text: 'Preferences saved in this browser. They are applied to new jobs from this device only — credentials and server config are unchanged.',
      });
    } catch (err) {
      setNote({ kind: 'error', text: err.message || 'Could not save preferences' });
    } finally {
      setSaving(false);
    }
  }, [parseForm]);

  const platform = platformState(config);
  const source = config || null;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Configuration"
        title="Auto-post settings"
        description="Credentials come from environment variables. Slots and render defaults can be personalised here for this browser only — nothing is written to disk."
      />

      {note && (
        <p
          className={cn(
            'rounded-lg border px-3.5 py-2.5 text-[12px]',
            note.kind === 'error'
              ? 'border-danger/30 bg-danger/10 text-danger'
              : 'border-ok/30 bg-ok/10 text-ok'
          )}
        >
          {note.text}
        </p>
      )}

      {!source ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="card h-64 animate-pulse" />
          <div className="card h-64 animate-pulse" />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <SectionCard
            title="Posting schedule"
            description="Two slots a day keeps the queue flowing. Personalised for this browser unless you clear saved preferences."
          >
            <div className="space-y-3">
              <label className="label">Posting times</label>
              <Input
                value={form.posting_times}
                onChange={(event) => update('posting_times', event.target.value)}
                placeholder="19:00, 21:00"
                hint="Comma-separated 24-hour times"
              />
              <label className="label">Time zone</label>
              <Input
                value={form.timezone}
                onChange={(event) => update('timezone', event.target.value)}
                placeholder="Africa/Nairobi"
              />
            </div>
          </SectionCard>

          <SectionCard title="Render defaults" description="Applied to every new clip run">
            <div className="space-y-3">
              <label className="label">Shorts per video</label>
              <Input
                type="number"
                min={1}
                max={20}
                value={form.shorts_per_video}
                onChange={(event) => update('shorts_per_video', event.target.value)}
              />
              <div className="grid grid-cols-2 gap-3">
                <label className="label">Min clip seconds</label>
                <Input
                  type="number"
                  min={3}
                  max={120}
                  value={form.clip_min_seconds}
                  onChange={(event) => update('clip_min_seconds', event.target.value)}
                />
                <label className="label">Max clip seconds</label>
                <Input
                  type="number"
                  min={5}
                  max={120}
                  value={form.clip_max_seconds}
                  onChange={(event) => update('clip_max_seconds', event.target.value)}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="label">Playback speed</label>
                <Input
                  type="number"
                  min={1}
                  max={2}
                  step={0.05}
                  value={form.playback_speed}
                  onChange={(event) => update('playback_speed', event.target.value)}
                />
                <label className="label">Drum volume</label>
                <Input
                  type="number"
                  min={-60}
                  max={0}
                  step={1}
                  value={form.drum_volume_db}
                  onChange={(event) => update('drum_volume_db', event.target.value)}
                  hint="dB"
                />
              </div>
              <label className="label">Words per caption</label>
              <Input
                type="number"
                min={1}
                max={12}
                value={form.caption_words_per_card}
                onChange={(event) => update('caption_words_per_card', event.target.value)}
              />
            </div>
          </SectionCard>

          <SectionCard title="Captions & copy" description="Burned into the video and used in the publish payload">
            <div className="space-y-3">
              <label className="label">Outro text</label>
              <Input
                value={form.outro_text}
                onChange={(event) => update('outro_text', event.target.value)}
                placeholder="Follow for more African tales"
              />
              <label className="label">Hashtags</label>
              <Input
                value={form.hashtags}
                onChange={(event) => update('hashtags', event.target.value)}
                placeholder="#AfricanTales #AfricanFolklore #Storytime #Shorts"
              />
              <label className="label">Caption colour</label>
              <Input
                type="color"
                value={form.caption_color || '#FFD700'}
                onChange={(event) => update('caption_color', event.target.value)}
                className="h-10"
              />
              <label className="label">Hook seconds</label>
              <Input
                type="number"
                min={0}
                max={10}
                step={0.5}
                value={form.hook_seconds}
                onChange={(event) => update('hook_seconds', event.target.value)}
              />
              <label className="label">Outro seconds</label>
              <Input
                type="number"
                min={0}
                max={10}
                step={0.5}
                value={form.outro_seconds}
                onChange={(event) => update('outro_seconds', event.target.value)}
              />
            </div>
          </SectionCard>

          <SectionCard title="Platforms" description="Where the scheduler publishes each clip">
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-4 rounded-lg border border-line bg-wash px-3.5 py-3">
                <div className="min-w-0">
                  <p className="text-[13px] font-medium">Instagram Reels</p>
                  <p className="mt-0.5 text-[11px] text-subtle">Meta Graph API business account</p>
                </div>
                <Switch
                  label={form.instagram ? 'On' : 'Off'}
                  checked={form.instagram}
                  onChange={(next) => update('instagram', next)}
                />
              </div>
              <div className="flex items-center justify-between gap-4 rounded-lg border border-line bg-wash px-3.5 py-3">
                <div className="min-w-0">
                  <p className="text-[13px] font-medium">TikTok</p>
                  <p className="mt-0.5 text-[11px] text-subtle">Playwright session upload</p>
                </div>
                <Switch
                  label={form.tiktok ? 'On' : 'Off'}
                  checked={form.tiktok}
                  onChange={(next) => update('tiktok', next)}
                />
              </div>
              <div className="flex items-center justify-between gap-4 rounded-lg border border-line bg-wash px-3.5 py-3">
                <div className="min-w-0">
                  <p className="text-[13px] font-medium">YouTube Shorts</p>
                  <p className="mt-0.5 text-[11px] text-subtle">OAuth2 upload right after a render</p>
                </div>
                <Switch
                  id="youtube-auto-post-settings"
                  label={form.youtube_auto_post ? 'On' : 'Off'}
                  checked={form.youtube_auto_post}
                  onChange={(next) => update('youtube_auto_post', next)}
                />
              </div>
            </div>
          </SectionCard>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-line bg-wash px-3.5 py-3">
        <div>
          <p className="text-[13px] font-medium">Save preferences</p>
          <p className="mt-0.5 text-[11px] text-subtle">
            Stored in this browser only (localStorage). Does not change config.json or the environment.
          </p>
        </div>
        <button
          type="button"
          disabled={saving}
          onClick={save}
          className="btn btn-primary"
        >
          {saving ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Saving…
            </>
          ) : (
            <>
              <Check className="h-3.5 w-3.5" />
              Save preferences
            </>
          )}
        </button>
      </div>

      <SectionCard
        title="Environment variables"
        description="Credentials are never written to disk — set them as environment variables (Render dashboard or .env) and restart."
      >
        <div className="grid gap-3 sm:grid-cols-2">
          {ENV_FIELDS.map((field) => {
            const configured = Boolean(data?.tokens?.[field.key]?.configured);
            return (
              <div key={field.key} className="rounded-lg border border-line bg-wash p-3.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-mono text-[12px] font-medium">{field.key}</p>
                    <p className="mt-0.5 text-[11px] text-subtle">{field.label}</p>
                    <p className="mt-0.5 text-[10px] text-subtle/80">{field.hint}</p>
                  </div>
                  <span
                    className={cn(
                      'pill shrink-0',
                      configured ? 'border-ok/30 text-ok' : 'border-danger/30 text-danger'
                    )}
                    title={configured ? 'Visible to the running process' : 'Not present in the environment'}
                  >
                    {configured ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
                    {configured ? 'set' : 'missing'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </SectionCard>

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Runtime" description="Read-only environment details">
          <dl className="space-y-2.5 text-[12px]">
            {[
              ['Data root', data?.runtime?.data_root || '—'],
              ['Whisper model', data?.runtime?.whisper_model || '—'],
              ['Scheduler in bot', data?.runtime?.scheduler_in_bot ? 'enabled' : 'disabled'],
              ['Public base URL', data?.runtime?.public_base_url ? 'configured' : 'missing'],
              ['Queue / posted', `${data?.queue ?? 0} / ${data?.posted ?? 0}`],
            ].map(([label, value]) => (
              <div key={label} className="flex items-center justify-between gap-3">
                <dt className="text-subtle">{label}</dt>
                <dd className="truncate font-mono text-[11px] text-fg/80">{value}</dd>
              </div>
            ))}
          </dl>
        </SectionCard>

        <SectionCard
          title="Recent activity"
          description="Worker log tail"
          actions={
            <>
              <ClearLogsButton />
              <RestoreLogsButton />
            </>
          }
        >
          <ActivityFeed limit={8} />
        </SectionCard>
      </div>
    </div>
  );
}

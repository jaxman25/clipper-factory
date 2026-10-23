'use client';

import { useCallback, useEffect, useState } from 'react';
import { Check, KeyRound, Loader2, Save, Trash2 } from 'lucide-react';
import ActivityFeed from '@/components/studio/ActivityFeed';
import { PageHeader, SectionCard } from '@/components/studio/ui';
import { cn } from '@/lib/cn';

const TOKEN_FIELDS = [
  { key: 'TELEGRAM_BOT_TOKEN', label: 'Telegram bot token', hint: 'From @BotFather' },
  { key: 'TELEGRAM_CHAT_ID', label: 'Telegram chat id', hint: 'Send /start to the bot to see it' },
  { key: 'PIXABAY_API_KEY', label: 'Pixabay API key', hint: 'Free at pixabay.com/api/docs' },
  { key: 'IG_USER_ID', label: 'Instagram user id', hint: 'Business account linked to a Page' },
  { key: 'IG_ACCESS_TOKEN', label: 'Instagram access token', hint: 'Meta long-lived token' },
  { key: 'TIKTOK_AUTH_B64', label: 'TikTok auth.json (base64)', hint: 'Output of --login' },
];

function Switch({ checked, onChange, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-6 w-11 shrink-0 rounded-full transition',
        checked ? 'bg-brand' : 'bg-white/15'
      )}
    >
      <span
        className={cn(
          'absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all',
          checked ? 'left-[22px]' : 'left-0.5'
        )}
      />
    </button>
  );
}

export default function SettingsPage() {
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [tokenValues, setTokenValues] = useState({});
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/settings', { cache: 'no-store' });
      if (!response.ok) throw new Error('Could not load settings');
      const payload = await response.json();
      setData(payload);
      setForm((current) =>
        current || {
          posting_times: (payload.config.posting_times || []).join(', '),
          timezone: payload.config.timezone || 'Africa/Nairobi',
          shorts_per_video: payload.config.shorts_per_video ?? 10,
          clip_min_seconds: payload.config.clip_min_seconds ?? 30,
          clip_max_seconds: payload.config.clip_max_seconds ?? 45,
          playback_speed: payload.config.playback_speed ?? 1.1,
          drum_volume_db: payload.config.drum_volume_db ?? -22,
          outro_text: payload.config.outro_text || '',
          hashtags: payload.config.hashtags || '',
          caption_color: payload.config.caption_color || '#FFD700',
          caption_words_per_card: payload.config.caption_words_per_card ?? 3,
          instagram: Boolean(payload.config.platforms?.instagram),
          tiktok: Boolean(payload.config.platforms?.tiktok),
        }
      );
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function saveSettings(event) {
    event.preventDefault();
    if (!form) return;
    setBusy('settings');
    setNote(null);
    try {
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          settings: {
            posting_times: form.posting_times,
            timezone: form.timezone,
            shorts_per_video: Number(form.shorts_per_video),
            clip_min_seconds: Number(form.clip_min_seconds),
            clip_max_seconds: Number(form.clip_max_seconds),
            playback_speed: Number(form.playback_speed),
            drum_volume_db: Number(form.drum_volume_db),
            caption_words_per_card: Number(form.caption_words_per_card),
            outro_text: form.outro_text,
            hashtags: form.hashtags,
            caption_color: form.caption_color,
            platforms: { instagram: form.instagram, tiktok: form.tiktok },
          },
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not save settings');
      setNote({ kind: 'ok', text: 'Settings saved — new runs and the scheduler pick them up immediately.' });
      setData((current) =>
        current ? { ...current, config: { ...current.config, ...payload.saved } } : current
      );
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    } finally {
      setBusy('');
    }
  }

  async function saveToken(key) {
    const value = (tokenValues[key] || '').trim();
    if (!value) {
      setNote({ kind: 'error', text: 'Paste a value before saving' });
      return;
    }
    setBusy(key);
    setNote(null);
    try {
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tokens: { [key]: value } }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not save token');
      setData((current) => (current ? { ...current, tokens: payload.tokens } : current));
      setTokenValues((current) => ({ ...current, [key]: '' }));
      setNote({ kind: 'ok', text: `${key} saved. Restart the bot to change its own polling token.` });
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    } finally {
      setBusy('');
    }
  }

  async function clearToken(key) {
    setBusy(key);
    setNote(null);
    try {
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clearTokens: [key] }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not clear token');
      setData((current) => (current ? { ...current, tokens: payload.tokens } : current));
      setNote({ kind: 'ok', text: `${key} cleared from dashboard settings.` });
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    } finally {
      setBusy('');
    }
  }

  const saving = busy === 'settings';

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Configuration"
        title="Auto-post settings"
        description="Slots, render defaults and platform tokens. Env vars from Render always win over values saved here."
        actions={
          <button type="submit" form="settings-form" disabled={!form || saving} className="btn btn-primary btn-sm">
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        }
      />

      {note && (
        <p
          className={cn(
            'rounded-lg border px-3.5 py-2.5 text-[12px]',
            note.kind === 'error'
              ? 'border-red-500/30 bg-red-500/10 text-red-300'
              : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
          )}
        >
          {note.text}
        </p>
      )}

      {!form ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="card h-64 animate-pulse" />
          <div className="card h-64 animate-pulse" />
        </div>
      ) : (
        <form id="settings-form" onSubmit={saveSettings} className="grid gap-4 lg:grid-cols-2">
          <SectionCard
            title="Posting schedule"
            description="Two slots a day keeps the queue flowing — 10 shorts ≈ 5 days."
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="posting-times" className="label">
                  Posting times
                </label>
                <input
                  id="posting-times"
                  type="text"
                  value={form.posting_times}
                  onChange={(event) => update('posting_times', event.target.value)}
                  placeholder="19:00, 21:00"
                  className="input mt-1.5"
                />
              </div>
              <div>
                <label htmlFor="timezone" className="label">
                  Time zone
                </label>
                <input
                  id="timezone"
                  type="text"
                  value={form.timezone}
                  onChange={(event) => update('timezone', event.target.value)}
                  placeholder="Africa/Nairobi"
                  className="input mt-1.5"
                />
              </div>
            </div>
          </SectionCard>

          <SectionCard title="Render defaults" description="Applied to every new clip run">
            <div className="grid gap-4 sm:grid-cols-2">
              {[
                ['shorts_per_video', 'Shorts per video', '1–20'],
                ['clip_min_seconds', 'Min clip seconds', 'seconds'],
                ['clip_max_seconds', 'Max clip seconds', 'seconds'],
                ['playback_speed', 'Playback speed', '1.0–1.5'],
                ['drum_volume_db', 'Drum volume', 'dB'],
                ['caption_words_per_card', 'Words per caption', '2–3'],
              ].map(([key, label, hint]) => (
                <div key={key}>
                  <label htmlFor={key} className="label">
                    {label}
                  </label>
                  <input
                    id={key}
                    type="number"
                    step="0.1"
                    value={form[key] ?? ''}
                    onChange={(event) => update(key, event.target.value)}
                    className="input mt-1.5 tabular-nums"
                  />
                  <p className="mt-1 text-[10px] text-zinc-600">{hint}</p>
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard title="Captions & copy" description="Burned into the video and used in the publish payload">
            <div className="space-y-4">
              <div>
                <label htmlFor="outro_text" className="label">
                  Outro text
                </label>
                <input
                  id="outro_text"
                  type="text"
                  value={form.outro_text}
                  onChange={(event) => update('outro_text', event.target.value)}
                  className="input mt-1.5"
                />
              </div>
              <div>
                <label htmlFor="hashtags" className="label">
                  Hashtags
                </label>
                <input
                  id="hashtags"
                  type="text"
                  value={form.hashtags}
                  onChange={(event) => update('hashtags', event.target.value)}
                  className="input mt-1.5"
                />
              </div>
              <div>
                <label htmlFor="caption_color" className="label">
                  Caption colour
                </label>
                <div className="mt-1.5 flex items-center gap-2">
                  <input
                    id="caption_color"
                    type="color"
                    value={form.caption_color}
                    onChange={(event) => update('caption_color', event.target.value)}
                    className="h-10 w-12 cursor-pointer rounded-lg border border-white/10 bg-transparent"
                  />
                  <input
                    type="text"
                    value={form.caption_color}
                    onChange={(event) => update('caption_color', event.target.value)}
                    className="input"
                  />
                </div>
              </div>
            </div>
          </SectionCard>

          <SectionCard title="Platforms" description="Where the scheduler publishes each clip">
            <div className="space-y-2">
              {[
                ['instagram', 'Instagram Reels', 'Meta Graph API business account'],
                ['tiktok', 'TikTok', 'Playwright session upload'],
              ].map(([key, label, hint]) => (
                <div
                  key={key}
                  className="flex items-center justify-between gap-4 rounded-lg border border-white/10 bg-white/[0.02] px-3.5 py-3"
                >
                  <div>
                    <p className="text-[13px] font-medium">{label}</p>
                    <p className="mt-0.5 text-[11px] text-zinc-500">{hint}</p>
                  </div>
                  <Switch
                    checked={Boolean(form[key])}
                    onChange={(value) => update(key, value)}
                    label={`Enable ${label}`}
                  />
                </div>
              ))}
            </div>
            <button type="submit" disabled={saving} className="btn btn-primary btn-sm mt-4 w-full">
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </SectionCard>
        </form>
      )}

      <SectionCard
        title="Integrations"
        description="Tokens are stored on this instance and are write-only in the UI."
      >
        <div className="grid gap-3 sm:grid-cols-2">
          {TOKEN_FIELDS.map((field) => {
            const status = data?.tokens?.[field.key];
            const configured = Boolean(status?.configured);
            return (
              <div key={field.key} className="rounded-lg border border-white/10 bg-white/[0.02] p-3.5">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[13px] font-medium">{field.label}</p>
                    <p className="mt-0.5 text-[11px] text-zinc-500">{field.hint}</p>
                  </div>
                  <span
                    className={cn(
                      'pill shrink-0',
                      configured ? 'border-emerald-500/30 text-emerald-300' : 'text-zinc-500'
                    )}
                  >
                    {configured ? <Check className="h-3 w-3" /> : <KeyRound className="h-3 w-3" />}
                    {configured ? status.hint || 'set' : 'not set'}
                  </span>
                </div>
                <div className="mt-3 flex gap-2">
                  <input
                    type="password"
                    autoComplete="off"
                    value={tokenValues[field.key] || ''}
                    onChange={(event) =>
                      setTokenValues((current) => ({ ...current, [field.key]: event.target.value }))
                    }
                    placeholder="paste value"
                    className="input"
                    aria-label={field.label}
                  />
                  <button
                    type="button"
                    onClick={() => saveToken(field.key)}
                    disabled={busy === field.key}
                    className="btn btn-sm shrink-0"
                  >
                    Save
                  </button>
                  {configured && (
                    <button
                      type="button"
                      onClick={() => clearToken(field.key)}
                      disabled={busy === field.key}
                      aria-label={`Clear ${field.label}`}
                      className="btn btn-sm shrink-0 text-red-400"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
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
                <dt className="text-zinc-500">{label}</dt>
                <dd className="truncate font-mono text-[11px] text-zinc-300">{value}</dd>
              </div>
            ))}
          </dl>
        </SectionCard>

        <SectionCard title="Recent activity" description="Worker log tail">
          <ActivityFeed limit={8} />
        </SectionCard>
      </div>
    </div>
  );
}

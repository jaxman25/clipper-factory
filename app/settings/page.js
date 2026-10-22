'use client';

import { useCallback, useEffect, useState } from 'react';
import TopBar from '@/components/TopBar';

const TOKEN_FIELDS = [
  { key: 'TELEGRAM_BOT_TOKEN', label: 'Telegram bot token', hint: 'From @BotFather' },
  { key: 'TELEGRAM_CHAT_ID', label: 'Telegram chat id', hint: 'Send /start to the bot to see it' },
  { key: 'PEXELS_API_KEY', label: 'Pexels API key', hint: 'Free at pexels.com/api' },
  { key: 'IG_USER_ID', label: 'Instagram user id', hint: 'Business account linked to a Facebook Page' },
  { key: 'IG_ACCESS_TOKEN', label: 'Instagram access token', hint: 'Meta Graph API long-lived token' },
  { key: 'TIKTOK_AUTH_B64', label: 'TikTok auth.json (base64)', hint: 'Output of --login, base64 encoded' },
];

function runtimeLine(entry) {
  const time = entry.ts ? new Date(entry.ts) : null;
  const stamp = time && !Number.isNaN(time.getTime())
    ? time.toLocaleTimeString('en-GB', { hour12: false })
    : '—';
  return (
    <div className="log-line" key={`${entry.ts}-${entry.message}-${Math.random()}`}>
      <span>{stamp}</span>
      <span className={`lv ${entry.level || 'info'}`}>{entry.level || 'info'}</span>
      <span>{entry.message}</span>
    </div>
  );
}

export default function SettingsPage() {
  const [data, setData] = useState(null);
  const [health, setHealth] = useState(null);
  const [form, setForm] = useState(null);
  const [tokenValues, setTokenValues] = useState({});
  const [logs, setLogs] = useState([]);
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState('');

  const loadSettings = useCallback(async () => {
    try {
      const [settingsRes, healthRes] = await Promise.all([
        fetch('/api/settings', { cache: 'no-store' }),
        fetch('/api/health', { cache: 'no-store' }),
      ]);
      if (healthRes.ok) setHealth(await healthRes.json());
      if (!settingsRes.ok) throw new Error('Could not load settings');
      const payload = await settingsRes.json();
      setData(payload);
      setForm((current) => current || {
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
        instagram: Boolean(payload.config.platforms?.instagram),
        tiktok: Boolean(payload.config.platforms?.tiktok),
      });
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    }
  }, []);

  const loadLogs = useCallback(async () => {
    try {
      const response = await fetch('/api/logs?limit=120', { cache: 'no-store' });
      if (response.ok) {
        const payload = await response.json();
        setLogs(payload.logs || []);
      }
    } catch (err) {
      /* ignore transient log errors */
    }
  }, []);

  useEffect(() => {
    loadSettings();
    loadLogs();
    const timer = setInterval(loadLogs, 15000);
    return () => clearInterval(timer);
  }, [loadSettings, loadLogs]);

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
            outro_text: form.outro_text,
            hashtags: form.hashtags,
            caption_color: form.caption_color,
            platforms: { instagram: form.instagram, tiktok: form.tiktok },
          },
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not save settings');
      setNote({ kind: 'ok', text: 'Settings saved. New generations use them immediately.' });
      setData((current) => (current ? { ...current, config: { ...current.config, ...payload.saved } } : current));
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
      setNote({
        kind: 'ok',
        text: `${key} saved for new workers. Restart the bot process to change its own polling token.`,
      });
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

  return (
    <>
      <TopBar active="settings" health={health} />
      <main className="container">
        <section className="hero">
          <div>
            <div className="eyebrow">Configuration</div>
            <h1>Settings &amp; integrations</h1>
            <p>
              Slots are stored in <code>/tmp/state/settings.json</code> and override config.json. Values
              set here apply to new render jobs and the in-process scheduler immediately; env vars from
              Render always win over dashboard tokens.
            </p>
          </div>
        </section>

        {note && <p className={`note ${note.kind}`} style={{ marginBottom: 16 }}>{note.text}</p>}

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2 className="panel-title">Posting &amp; rendering</h2>
              <p className="panel-sub">Two slots a day keeps the queue flowing (10 shorts ≈ 5 days).</p>
            </div>
          </div>
          {form ? (
            <form onSubmit={saveSettings}>
              <div className="settings-grid">
                <div className="field">
                  <label htmlFor="posting-times">Posting times (comma separated)</label>
                  <input
                    id="posting-times"
                    type="text"
                    value={form.posting_times}
                    onChange={(event) => update('posting_times', event.target.value)}
                    placeholder="19:00, 21:00"
                  />
                </div>
                <div className="field">
                  <label htmlFor="timezone">Time zone</label>
                  <input
                    id="timezone"
                    type="text"
                    value={form.timezone}
                    onChange={(event) => update('timezone', event.target.value)}
                    placeholder="Africa/Nairobi"
                  />
                </div>
                <div className="field">
                  <label htmlFor="shorts-per-video">Shorts per video</label>
                  <input
                    id="shorts-per-video"
                    type="number"
                    min={1}
                    max={20}
                    value={form.shorts_per_video}
                    onChange={(event) => update('shorts_per_video', event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="clip-min">Min clip seconds</label>
                  <input
                    id="clip-min"
                    type="number"
                    min={10}
                    max={90}
                    value={form.clip_min_seconds}
                    onChange={(event) => update('clip_min_seconds', event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="clip-max">Max clip seconds</label>
                  <input
                    id="clip-max"
                    type="number"
                    min={15}
                    max={120}
                    value={form.clip_max_seconds}
                    onChange={(event) => update('clip_max_seconds', event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="speed">Playback speed</label>
                  <input
                    id="speed"
                    type="number"
                    step="0.05"
                    min={1}
                    max={1.5}
                    value={form.playback_speed}
                    onChange={(event) => update('playback_speed', event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="drum">Drum bed (dB)</label>
                  <input
                    id="drum"
                    type="number"
                    step="1"
                    min={-40}
                    max={-6}
                    value={form.drum_volume_db}
                    onChange={(event) => update('drum_volume_db', event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="caption-color">Caption colour</label>
                  <input
                    id="caption-color"
                    type="text"
                    value={form.caption_color}
                    onChange={(event) => update('caption_color', event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="outro">Outro text</label>
                  <input
                    id="outro"
                    type="text"
                    value={form.outro_text}
                    onChange={(event) => update('outro_text', event.target.value)}
                  />
                </div>
                <div className="field" style={{ gridColumn: '1 / -1' }}>
                  <label htmlFor="hashtags">Hashtags</label>
                  <input
                    id="hashtags"
                    type="text"
                    value={form.hashtags}
                    onChange={(event) => update('hashtags', event.target.value)}
                  />
                </div>
              </div>

              <div className="checkline">
                <input
                  id="ig-enabled"
                  type="checkbox"
                  checked={form.instagram}
                  onChange={(event) => update('instagram', event.target.checked)}
                />
                <label htmlFor="ig-enabled">Post to Instagram</label>
              </div>
              <div className="checkline">
                <input
                  id="tt-enabled"
                  type="checkbox"
                  checked={form.tiktok}
                  onChange={(event) => update('tiktok', event.target.checked)}
                />
                <label htmlFor="tt-enabled">Post to TikTok</label>
              </div>

              <button type="submit" className="btn btn-primary" disabled={busy === 'settings'}>
                {busy === 'settings' ? 'Saving…' : 'Save settings'}
              </button>
            </form>
          ) : (
            <div className="skeleton" />
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2 className="panel-title">Tokens</h2>
              <p className="panel-sub">
                Stored in /tmp/state/settings.json on Render (ephemeral). For permanence set them as
                Render env vars.
              </p>
            </div>
          </div>
          <div className="settings-grid">
            {TOKEN_FIELDS.map((field) => {
              const status = data?.tokens?.[field.key];
              return (
                <div className="field" key={field.key}>
                  <label htmlFor={`token-${field.key}`}>{field.label}</label>
                  <div className="token-row">
                    <input
                      id={`token-${field.key}`}
                      type="password"
                      placeholder={status?.configured ? `Configured ${status.hint}` : field.hint}
                      value={tokenValues[field.key] || ''}
                      onChange={(event) =>
                        setTokenValues((current) => ({ ...current, [field.key]: event.target.value }))
                      }
                      autoComplete="new-password"
                    />
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => saveToken(field.key)}
                        disabled={busy === field.key}
                      >
                        Save
                      </button>
                      {status?.configured && (
                        <button
                          type="button"
                          className="btn btn-sm btn-danger"
                          onClick={() => clearToken(field.key)}
                          disabled={busy === field.key}
                        >
                          Clear
                        </button>
                      )}
                    </div>
                  </div>
                  <span className={`token-status ${status?.configured ? 'on' : ''}`}>
                    {status?.configured ? 'Configured' : field.hint}
                  </span>
                </div>
              );
            })}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2 className="panel-title">Runtime</h2>
              <p className="panel-sub">Where the free tier keeps its state.</p>
            </div>
            <button type="button" className="btn btn-sm" onClick={loadLogs}>
              Refresh logs
            </button>
          </div>
          <div className="settings-grid">
            <div className="stat">
              <b style={{ fontSize: 13 }}>{data?.runtime?.data_root || '/tmp'}</b>
              <span>Data root</span>
            </div>
            <div className="stat">
              <b style={{ fontSize: 15 }}>{data?.runtime?.whisper_model || 'tiny'}</b>
              <span>Whisper model</span>
            </div>
            <div className="stat">
              <b style={{ fontSize: 15 }}>{data?.runtime?.scheduler_in_bot ? 'On' : 'Off'}</b>
              <span>In-bot scheduler</span>
            </div>
            <div className="stat">
              <b style={{ fontSize: 15 }}>{data?.queue ?? 0}</b>
              <span>Queue</span>
            </div>
            <div className="stat">
              <b style={{ fontSize: 15 }}>{data?.posted ?? 0}</b>
              <span>Posted</span>
            </div>
          </div>

          <div className="logs" style={{ marginTop: 16 }}>
            {logs.length ? logs.map((entry) => runtimeLine(entry)) : 'No logs yet. Run a generation or a post.'}
          </div>
        </section>

        <p className="footer">
          Deploy notes and token walkthroughs live in <code>README-RENDER.md</code>.
        </p>
      </main>
    </>
  );
}

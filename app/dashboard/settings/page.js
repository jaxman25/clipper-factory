'use client';

import { useCallback, useEffect, useState } from 'react';
import { Check, X } from 'lucide-react';
import ActivityFeed, { ClearLogsButton, RestoreLogsButton } from '@/components/studio/ActivityFeed';
import { PageHeader, SectionCard } from '@/components/studio/ui';
import { cn } from '@/lib/cn';

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

export default function SettingsPage() {
  const [data, setData] = useState(null);
  const [note, setNote] = useState(null);

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

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Configuration"
        title="Auto-post settings"
        description="Read-only: slots and render defaults come from config.json, credentials from the environment variables set on this deployment."
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

      {!config ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="card h-64 animate-pulse" />
          <div className="card h-64 animate-pulse" />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <SectionCard
            title="Posting schedule"
            description="Two slots a day keeps the queue flowing — edit config.json and redeploy."
          >
            <dl className="space-y-2.5 text-[12px]">
              <Row label="Posting times" value={(config.posting_times || []).join(' · ')} />
              <Row label="Time zone" value={config.timezone || '—'} />
            </dl>
          </SectionCard>

          <SectionCard title="Render defaults" description="Applied to every new clip run">
            <dl className="space-y-2.5 text-[12px]">
              <Row label="Shorts per video" value={config.shorts_per_video ?? '—'} />
              <Row label="Min clip seconds" value={config.clip_min_seconds ?? '—'} />
              <Row label="Max clip seconds" value={config.clip_max_seconds ?? '—'} />
              <Row label="Playback speed" value={config.playback_speed ?? '—'} />
              <Row label="Drum volume" value={`${config.drum_volume_db ?? '—'} dB`} />
              <Row label="Words per caption" value={config.caption_words_per_card ?? '—'} />
            </dl>
          </SectionCard>

          <SectionCard title="Captions & copy" description="Burned into the video and used in the publish payload">
            <dl className="space-y-2.5 text-[12px]">
              <Row label="Outro text" value={config.outro_text || '—'} />
              <Row label="Hashtags" value={config.hashtags || '—'} />
              <Row label="Caption colour" value={config.caption_color || '—'} />
              <Row label="Hook seconds" value={config.hook_seconds ?? '—'} />
              <Row label="Outro seconds" value={config.outro_seconds ?? '—'} />
            </dl>
          </SectionCard>

          <SectionCard title="Platforms" description="Where the scheduler publishes each clip">
            <div className="space-y-2">
              {[
                ['instagram', 'Instagram Reels', 'Meta Graph API business account'],
                ['tiktok', 'TikTok', 'Playwright session upload'],
                ['youtube_auto_post', 'YouTube Shorts', 'OAuth2 upload right after a render'],
              ].map(([key, label, hint]) => {
                const enabled = Boolean(config.platforms?.[key] ?? config[key]);
                return (
                  <div
                    key={key}
                    className="flex items-center justify-between gap-4 rounded-lg border border-line bg-wash px-3.5 py-3"
                  >
                    <div className="min-w-0">
                      <p className="text-[13px] font-medium">{label}</p>
                      <p className="mt-0.5 text-[11px] text-subtle">{hint}</p>
                    </div>
                    <span
                      className={cn(
                        'pill shrink-0',
                        enabled ? 'border-ok/30 text-ok' : 'border-danger/30 text-danger'
                      )}
                    >
                      {enabled ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
                      {enabled ? 'on' : 'off'}
                    </span>
                  </div>
                );
              })}
            </div>
          </SectionCard>
        </div>
      )}

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

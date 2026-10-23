'use client';

import { useCallback, useEffect, useState } from 'react';
import { Bot, Check, Send } from 'lucide-react';
import ActivityFeed from '@/components/studio/ActivityFeed';
import { EmptyState, PageHeader, SectionCard, StatCard } from '@/components/studio/ui';
import { useStudio } from '@/components/studio/StudioProvider';
import { cn } from '@/lib/cn';

const COMMANDS = [
  ['/start', 'Welcome message and your chat id'],
  ['/clip <youtube url>', 'Start a generation run (raw links also work)'],
  ['/queue', 'List queued clips and pin the list'],
  ['/postnow [clip-id]', 'Publish the oldest clip immediately'],
  ['/settings', 'Slots, integrations and queue health'],
  ['/cancel', 'Stop the running generation'],
];

export default function BotPage() {
  const { clips, health, notify } = useStudio();
  const [status, setStatus] = useState(null);
  const [sending, setSending] = useState('');

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/settings', { cache: 'no-store' });
      if (response.ok) setStatus(await response.json());
    } catch (err) {
      /* the bot page tolerates a cold start */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function sendClip(clip) {
    setSending(clip.id);
    try {
      const response = await fetch('/api/telegram', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: clip.id }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Telegram upload failed');
      notify(`Sent ${clip.hook || clip.id} to Telegram`);
    } catch (err) {
      notify(err.message);
    } finally {
      setSending('');
    }
  }

  const token = status?.tokens || {};
  const botReady = Boolean(token.TELEGRAM_BOT_TOKEN?.configured);
  const chatReady = Boolean(token.TELEGRAM_CHAT_ID?.configured);
  const scheduler = Boolean(status?.runtime?.scheduler_in_bot);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Automation"
        title="Bot control"
        description="The same worker answers Telegram commands. Anything you can do here, you can do from chat."
      />

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <StatCard
          label="Bot token"
          value={botReady ? 'Connected' : 'Missing'}
          hint={botReady ? token.TELEGRAM_BOT_TOKEN?.hint : 'Set TELEGRAM_BOT_TOKEN'}
          icon={Bot}
          tone="brand"
        />
        <StatCard
          label="Chat"
          value={chatReady ? 'Linked' : 'Missing'}
          hint={chatReady ? token.TELEGRAM_CHAT_ID?.hint : 'Send /start to the bot'}
          icon={Send}
        />
        <StatCard
          label="Scheduler"
          value={scheduler ? 'In bot' : 'External'}
          hint={scheduler ? 'Posts at the configured slots' : 'Enable ACF_ENABLE_SCHEDULER'}
          icon={Check}
        />
        <StatCard label="Queue" value={health?.queue ?? clips.length} hint="Clips ready to post" />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SectionCard
          title="Send a clip to Telegram"
          description="Useful when a platform rejects an upload"
          className="min-w-0 lg:col-span-2"
        >
          {clips.length === 0 ? (
            <EmptyState
              icon={Send}
              title="Nothing to send"
              description="Generate a clip run first — queued clips appear here."
            />
          ) : (
            <ul className="divide-y divide-white/5">
              {clips.slice(0, 5).map((clip) => (
                <li key={clip.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                  <img
                    src={clip.thumb_url}
                    alt=""
                    width={36}
                    height={52}
                    className="h-[52px] w-9 shrink-0 rounded-md border border-white/10 object-cover"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium">{clip.hook || clip.title || clip.id}</p>
                    <p className="mt-0.5 text-[11px] text-zinc-500">
                      {Number(clip.duration || 0).toFixed(0)}s · 🔥 {Math.round(clip.viral_score || 0)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => sendClip(clip)}
                    disabled={sending === clip.id}
                    className="btn btn-sm shrink-0"
                  >
                    <Send className="h-3.5 w-3.5 text-brand" />
                    {sending === clip.id ? 'Sending…' : 'Send'}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>

        <SectionCard title="Commands" description="Available in the bot chat" className="min-w-0">
          <ul className="space-y-3">
            {COMMANDS.map(([command, description]) => (
              <li key={command}>
                <code className="rounded bg-white/[0.05] px-1.5 py-0.5 font-mono text-[11px] text-brand">
                  {command}
                </code>
                <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">{description}</p>
              </li>
            ))}
          </ul>
        </SectionCard>
      </div>

      <SectionCard
        title="Bot activity"
        description="Shared worker log — Telegram, scheduler and render events"
        actions={
          <span
            className={cn(
              'inline-flex items-center gap-1.5 text-[11px]',
              botReady ? 'text-emerald-400' : 'text-amber-400'
            )}
          >
            <span className={cn('h-1.5 w-1.5 rounded-full', botReady ? 'bg-emerald-400' : 'bg-amber-400')} />
            {botReady ? 'token present' : 'token missing'}
          </span>
        }
      >
        <ActivityFeed limit={12} />
      </SectionCard>
    </div>
  );
}

'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ListVideo, RefreshCw, Sparkles, Trash2, AlertTriangle } from 'lucide-react';
import ScheduleBoard from '@/components/studio/ScheduleBoard';
import ClipCard from '@/components/studio/ClipCard';
import { EmptyState, PageHeader, SectionCard, Skeleton } from '@/components/studio/ui';
import { useStudio } from '@/components/studio/StudioProvider';
import { cn } from '@/lib/cn';

export default function QueuePage() {
  const { clips, posted, loading, refresh, notify } = useStudio();
  const [tab, setTab] = useState('queue');
  const [resetOpen, setResetOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const list = tab === 'queue' ? clips : posted;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Queue"
        title="Queue & schedule"
        description="Every clip waiting for a slot, plus the last seven days of posting slots."
        actions={
          <>
            <button type="button" onClick={refresh} className="btn btn-sm">
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
            <a
              href="/api/download"
              className="btn btn-primary btn-sm"
              aria-disabled={!clips.length && !posted.length}
              onClick={(event) => {
                if (!clips.length && !posted.length) event.preventDefault();
              }}
            >
              Download all
            </a>
            <button
              type="button"
              onClick={() => setResetOpen(true)}
              className="btn btn-sm btn-danger"
              aria-label="Reset system - delete all clips and clear queue"
              disabled={resetting}
            >
              <Trash2 className="h-3.5 w-3.5" />
              {resetting ? 'Resetting…' : 'Reset System'}
            </button>
          </>
        }
      />

      <SectionCard title="Posting calendar" description="Drag a clip onto another cell to move its slot">
        <ScheduleBoard />
      </SectionCard>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-full border border-white/10 bg-surface p-1">
          {[
            ['queue', `Queued (${clips.length})`],
            ['posted', `Posted (${posted.length})`],
          ].map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={cn(
                'rounded-full px-4 py-1.5 text-xs font-semibold transition',
                tab === key ? 'bg-brand text-white' : 'text-muted hover:text-white'
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="text-[11px] text-zinc-500">Captions and slots save instantly.</p>
      </div>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[520px]" />
          ))}
        </div>
      ) : list.length ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {list.map((clip) => (
            <ClipCard key={clip.id} clip={clip} />
          ))}
        </div>
      ) : tab === 'queue' ? (
        <EmptyState
          icon={Sparkles}
          title="The queue is empty"
          description="Paste a YouTube link on the dashboard, or send /clip to the Telegram bot."
          action={
            <Link href="/dashboard" className="btn btn-primary btn-sm">
              Start a clip run
            </Link>
          }
        />
      ) : (
        <EmptyState
          icon={ListVideo}
          title="Nothing posted yet"
          description="Clips land here once Instagram or TikTok accepts them."
        />
      )}

      {resetOpen && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/60 p-6" role="dialog" aria-modal="true">
          <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-surface p-6 shadow-2xl">
            <div className="flex flex-col gap-4">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-red-500/15 text-red-300">
                  <AlertTriangle className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="text-lg font-bold text-white">Reset the entire system?</h2>
                  <p className="mt-1 text-sm text-zinc-400">
                    This will delete all queued and posted clips, remove all generated video and
                    thumbnail files, clear the job database, and wipe the logs. This action
                    <b>cannot be undone</b>.
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-3 justify-end">
                <button
                  type="button"
                  onClick={() => setResetOpen(false)}
                  className="btn btn-sm"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={confirmReset}
                  className="btn btn-sm btn-danger"
                  disabled={resetting}
                >
                  {resetting ? 'Resetting…' : 'Yes, delete everything'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  async function confirmReset() {
    setResetOpen(false);
    setResetting(true);
    try {
      const response = await fetch('/api/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'Reset failed');
      }
      notify(`${data.removed.mp4} video files deleted`);
      refresh();
    } catch (err) {
      notify(err.message);
      setResetOpen(true);
    } finally {
      setResetting(false);
    }
  }
}

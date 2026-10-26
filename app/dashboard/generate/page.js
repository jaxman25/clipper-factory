'use client';

import Link from 'next/link';
import { CheckCircle2, Clock, Loader2, XCircle } from 'lucide-react';
import GeneratePanel from '@/components/studio/GeneratePanel';
import { EmptyState, PageHeader, SectionCard } from '@/components/studio/ui';
import { useStudio } from '@/components/studio/StudioProvider';
import { formatInTZ } from '@/lib/time';

const STEPS = [
  ['Download', 'yt-dlp pulls the source at ≤1080p.'],
  ['Transcribe', 'faster-whisper tiny, word-level timestamps.'],
  ['Score', '30–45s windows ranked on hooks and volume spikes.'],
  ['Render', '9:16 reframe, drum bed, ASS caption burn-in.'],
  ['Queue', 'Two slots a day assigned automatically.'],
];

function statusIcon(status) {
  if (status === 'running') return <Loader2 className="h-3.5 w-3.5 animate-spin text-brand" />;
  if (status === 'done') return <CheckCircle2 className="h-3.5 w-3.5 text-ok" />;
  if (status === 'error') return <XCircle className="h-3.5 w-3.5 text-danger" />;
  return <Clock className="h-3.5 w-3.5 text-subtle" />;
}

export default function GeneratePage() {
  const { jobs, timeZone, job } = useStudio();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Generate"
        title="New clip run"
        description="One link in, a queue of vertical shorts out. Jobs run one at a time on this instance."
        actions={
          <Link href="/dashboard/queue" className="btn btn-sm">
            View queue
          </Link>
        }
      />

      <GeneratePanel autoFocus />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SectionCard
          title="Recent runs"
          description="The last ten jobs on this instance"
          className="min-w-0 lg:col-span-2"
        >
          {jobs.length === 0 ? (
            <EmptyState
              icon={Clock}
              title="No jobs yet"
              description="Every run you start shows up here with its stage and progress."
            />
          ) : (
            <ul className="divide-y divide-line/60">
              {jobs.map((entry) => (
                <li key={entry.id} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
                  <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-wash">
                    {statusIcon(entry.status)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium text-fg">
                      {entry.message || entry.stage || entry.status}
                    </p>
                    <p className="mt-0.5 text-[11px] text-subtle">
                      <span className="font-mono">{entry.id}</span>
                      {entry.created_at ? ` · ${formatInTZ(entry.created_at, timeZone)}` : ''}
                      {entry.clips?.length ? ` · ${entry.clips.length} clips` : ''}
                    </p>
                  </div>
                  <span className="shrink-0 text-[11px] tabular-nums text-muted">
                    {entry.status === 'running' ? `${entry.progress || 0}%` : entry.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>

        <SectionCard title="Pipeline" description="What happens after you hit generate" className="min-w-0">
          <ol className="space-y-3">
            {STEPS.map(([title, body], index) => (
              <li key={title} className="flex gap-3">
                <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-wash text-[10px] font-bold text-muted">
                  {index + 1}
                </span>
                <div>
                  <p className="text-[13px] font-medium text-fg/90">{title}</p>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-subtle">{body}</p>
                </div>
              </li>
            ))}
          </ol>
          {job?.status === 'running' && (
            <p className="mt-4 rounded-lg bg-brand/10 px-3 py-2 text-[11px] text-brand">
              Job {job.id} is running — this page updates automatically.
            </p>
          )}
        </SectionCard>
      </div>
    </div>
  );
}

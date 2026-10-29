'use client';

import Link from 'next/link';
import {
  Activity,
  ArrowUpRight,
  CalendarClock,
  ListVideo,
  RefreshCw,
  Sparkles,
  TrendingUp,
} from 'lucide-react';
import GeneratePanel from '@/components/studio/GeneratePanel';
import ScheduleBoard from '@/components/studio/ScheduleBoard';
import AnalyticsSummary from '@/components/studio/AnalyticsSummary';
import ActivityFeed, { ClearLogsButton, RestoreLogsButton } from '@/components/studio/ActivityFeed';
import { EmptyState, PageHeader, SectionCard, StatCard } from '@/components/studio/ui';
import { useStudio } from '@/components/studio/StudioProvider';
import { cn } from '@/lib/cn';
import { formatInTZ } from '@/lib/time';

// Each integration needs every key before it can run; the overview shows
// connected / incomplete / not set so a saved token is visible straight away.
const INTEGRATIONS = [
  { label: 'Telegram', keys: ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'] },
  { label: 'Instagram', keys: ['IG_USER_ID', 'IG_ACCESS_TOKEN'] },
  { label: 'TikTok', keys: ['TIKTOK_AUTH_B64'] },
  { label: 'YouTube', keys: ['YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET', 'YOUTUBE_REFRESH_TOKEN'] },
  { label: 'B-roll', keys: ['PIXABAY_API_KEY'] },
];

export default function OverviewPage() {
  const { clips, posted, avgScore, loading, timeZone, postingTimes, health, refresh, tokens, analytics } =
    useStudio();
  const next = clips[0]?.scheduled_for;
  const upNext = clips.slice(0, 3);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Overview"
        title="Dashboard"
        description={`Two posts a day at ${postingTimes.join(' and ')} (${timeZone}). Paste a link and the worker handles the rest.`}
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
          </>
        }
      />

      <GeneratePanel autoFocus />

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <StatCard label="Queued" value={loading ? '—' : clips.length} hint="Ready to publish" icon={ListVideo} tone="brand" />
        <StatCard label="Posted" value={loading ? '—' : posted.length} hint="Delivered to platforms" icon={ArrowUpRight} />
        <StatCard label="Avg score" value={loading ? '—' : avgScore || '—'} hint="Viral detector" icon={TrendingUp} />
        <StatCard
          label="Next post"
          value={next ? formatInTZ(next, timeZone).split(' ').slice(-1)[0] : '—'}
          hint={next ? formatInTZ(next, timeZone) : 'Queue is empty'}
          icon={CalendarClock}
        />
      </div>

      <AnalyticsSummary analytics={analytics} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="min-w-0 space-y-4 lg:col-span-2">
          <SectionCard
            title="Posting calendar"
            description="Next 7 days · drag a clip to move its slot"
            actions={
              <Link href="/dashboard/queue" className="btn btn-ghost btn-sm">
                Open queue
                <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            }
          >
            <ScheduleBoard />
          </SectionCard>

          <SectionCard
            title="Up next"
            description="The three clips the scheduler will publish next"
            actions={
              <Link href="/dashboard/queue" className="btn btn-ghost btn-sm">
                View all
              </Link>
            }
          >
            {upNext.length === 0 ? (
              <EmptyState
                icon={Sparkles}
                title="Nothing queued yet"
                description="Paste a YouTube link above. Ten clips land in the queue in about 5–15 minutes."
              />
            ) : (
              <ul className="divide-y divide-line/60">
                {upNext.map((clip) => (
                  <li key={clip.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                    <img
                      src={clip.thumb_url}
                      alt=""
                      width={40}
                      height={56}
                      className="h-14 w-10 shrink-0 rounded-md border border-line object-cover"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium text-fg">
                        {clip.hook || clip.title || clip.id}
                      </p>
                      <p className="mt-0.5 text-[11px] text-subtle">
                        {formatInTZ(clip.scheduled_for, timeZone)} · 🔥 {Math.round(clip.viral_score || 0)}
                      </p>
                    </div>
                    <span className="pill shrink-0">{Number(clip.duration || 0).toFixed(0)}s</span>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        </div>

        <div className="min-w-0 space-y-4">
          <SectionCard
            title="Recent activity"
            description="Worker log tail"
            actions={
              <>
                <span className="inline-flex items-center gap-1.5 text-[11px] text-subtle">
                  <Activity className="h-3 w-3" />
                  live
                </span>
                <ClearLogsButton />
                <RestoreLogsButton />
              </>
            }
          >
            <ActivityFeed limit={9} />
          </SectionCard>

          <SectionCard title="Runtime" description="Health of this instance">
            <dl className="space-y-2.5 text-[12px]">
              {[
                ['Status', health?.status === 'ok' ? 'Online' : 'Connecting…'],
                ['Queue', `${health?.queue ?? clips.length} clips`],
                ['Posting', (health?.posting_times || postingTimes).join(' · ')],
                ['Time zone', health?.timezone || timeZone],
                ['Running job', health?.running_job || 'none'],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between gap-3">
                  <dt className="text-subtle">{label}</dt>
                  <dd className="truncate font-medium text-fg/90">{value}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-4 border-t border-line/60 pt-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-subtle">
                  Integrations
                </p>
                <Link href="/dashboard/settings" className="text-[11px] text-brand hover:underline">
                  Manage
                </Link>
              </div>
              <ul className="mt-2 space-y-1.5 text-[12px]">
                {INTEGRATIONS.map(({ label, keys }) => {
                  const ready = keys.every((key) => tokens?.[key]?.configured);
                  const partial = !ready && keys.some((key) => tokens?.[key]?.configured);
                  return (
                    <li key={label} className="flex items-center justify-between gap-3">
                      <span className="flex items-center gap-2 text-muted">
                        <span
                          className={cn(
                            'h-1.5 w-1.5 rounded-full',
                            ready ? 'bg-ok' : partial ? 'bg-warn' : 'bg-line'
                          )}
                        />
                        {label}
                      </span>
                      <span className="text-[11px] text-subtle">
                        {ready ? 'connected' : partial ? 'incomplete' : 'not set'}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>

            <a
              href="/api/health"
              target="_blank"
              rel="noreferrer"
              className="btn btn-ghost btn-sm mt-4 w-full justify-between"
            >
              /api/health
              <ArrowUpRight className="h-3.5 w-3.5" />
            </a>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}

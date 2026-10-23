'use client';

import { useState } from 'react';
import { AlertCircle, Link2, Loader2, Sparkles } from 'lucide-react';
import { useStudio } from '@/components/studio/StudioProvider';

function Progress({ job, onClear }) {
  const running = job.status === 'running';
  const failed = job.status === 'error';
  const pct = Math.max(0, Math.min(100, Number(job.progress) || 0));

  return (
    <div className="mt-5 rounded-xl border border-white/10 bg-black/20 p-4">
      <div className="flex items-center justify-between gap-4 text-xs">
        <span className="flex min-w-0 items-center gap-2 text-zinc-300">
          {running && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-brand" />}
          {failed && <AlertCircle className="h-3.5 w-3.5 shrink-0 text-red-400" />}
          <span className="truncate">
            <span className="font-mono text-[11px] text-zinc-500">{job.id}</span>
            <span className="mx-2 text-zinc-700">/</span>
            {job.message || job.stage || (running ? 'Working…' : 'Finished')}
          </span>
        </span>
        <div className="flex items-center gap-3">
          <b className="tabular-nums text-white">{pct}%</b>
          {onClear && !running && (
            <button type="button" onClick={onClear} className="text-[11px] text-zinc-500 hover:text-white">
              dismiss
            </button>
          )}
        </div>
      </div>

      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            failed ? 'bg-red-500' : 'bg-gradient-to-r from-brand to-brand-dark'
          }`}
          style={{ width: `${failed ? 100 : pct}%` }}
        />
      </div>

      {job.error && <p className="mt-3 text-[11px] leading-relaxed text-red-400">{job.error}</p>}
    </div>
  );
}

export default function GeneratePanel({ autoFocus = false }) {
  const { config, job, setJob, startGeneration, notify } = useStudio();
  const [url, setUrl] = useState('');
  const [num, setNum] = useState(config?.shorts_per_video || 10);
  const [busy, setBusy] = useState(false);
  const running = job?.status === 'running';

  async function submit(event) {
    event.preventDefault();
    if (!url.trim()) {
      notify('Paste a YouTube link first');
      return;
    }
    setBusy(true);
    try {
      await startGeneration(url.trim(), num);
      setUrl('');
      notify('Generation started — clips land in 5–15 minutes');
    } catch (err) {
      notify(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card relative overflow-hidden">
      <div className="pointer-events-none absolute inset-x-0 -top-32 h-56 bg-[radial-gradient(45%_60%_at_50%_60%,rgba(47,128,237,0.18),transparent_75%)]" />

      <div className="relative p-5 sm:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="label text-brand">New clip run</p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">Paste a YouTube link</h2>
            <p className="mt-1.5 text-sm text-muted">
              yt-dlp → whisper → viral scoring → 1080×1920 render → queue
            </p>
          </div>
          <span className="hidden h-10 w-10 items-center justify-center rounded-xl bg-brand/15 text-brand sm:inline-flex">
            <Sparkles className="h-5 w-5" />
          </span>
        </div>

        <form onSubmit={submit} className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Link2 className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
            <input
              id="youtube-url"
              type="url"
              autoFocus={autoFocus}
              inputMode="url"
              placeholder="https://www.youtube.com/watch?v=…"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              disabled={busy || running}
              aria-label="YouTube URL"
              className="input h-12 pl-10 text-[15px]"
            />
          </div>

          <div className="flex items-center gap-3">
            <label className="sr-only" htmlFor="num-shorts">
              Shorts to generate
            </label>
            <input
              id="num-shorts"
              type="number"
              min={1}
              max={20}
              value={num}
              onChange={(event) => setNum(event.target.value)}
              disabled={busy || running}
              className="input h-12 w-[88px] text-center tabular-nums"
            />
            <button type="submit" disabled={busy || running} className="btn btn-primary h-12 flex-1 px-6 sm:flex-none">
              {busy ? 'Starting…' : running ? 'Working…' : 'Generate'}
            </button>
          </div>
        </form>

        {job && <Progress job={job} onClear={() => setJob(null)} />}

        <p className="mt-4 text-[11px] text-zinc-500">
          {config?.shorts_per_video || 10} shorts per run · {config?.clip_min_seconds || 30}–
          {config?.clip_max_seconds || 45}s clips · one job at a time
        </p>
      </div>
    </section>
  );
}

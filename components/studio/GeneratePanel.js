'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Link2, Loader2, Sparkles } from 'lucide-react';
import { Switch } from '@/components/studio/ui';
import { useStudio } from '@/components/studio/StudioProvider';

function Progress({ job, onClear, onCancel, onCanceling }) {
  const running = job.status === 'running';
  const failed = job.status === 'error';
  const pct = Math.max(0, Math.min(100, Number(job.progress) || 0));

  return (
    <div className="mt-5 rounded-xl border border-line bg-black/20 p-4">
      <div className="flex items-center justify-between gap-4 text-xs">
        <span className="flex min-w-0 items-center gap-2 text-fg/80">
          {running && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-brand" />}
          {failed && <AlertCircle className="h-3.5 w-3.5 shrink-0 text-danger" />}
          <span className="truncate">
            <span className="font-mono text-[11px] text-subtle">{job.id}</span>
            <span className="mx-2 text-subtle/70">/</span>
            {job.message || job.stage || (running ? 'Working…' : 'Finished')}
          </span>
        </span>
        <div className="flex items-center gap-3">
          <b className="tabular-nums text-fg">{pct}%</b>
          {onClear && !running && (
            <button type="button" onClick={onClear} className="text-[11px] text-subtle hover:text-fg">
              dismiss
            </button>
          )}
        </div>
      </div>

      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-wash-strong">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            failed ? 'bg-danger' : 'bg-gradient-to-r from-brand to-brand-hover'
          }`}
          style={{ width: `${failed ? 100 : pct}%` }}
        />
      </div>

      {running && (
        <button
          type="button"
          onClick={onCancel}
          disabled={onCanceling}
          className="btn btn-sm btn-danger"
        >
          {onCanceling ? 'Cancelling…' : 'Cancel Job'}
        </button>
      )}

      {job.error && <p className="mt-3 text-[11px] leading-relaxed text-danger">{job.error}</p>}
    </div>
  );
}

export default function GeneratePanel({ autoFocus = false }) {
  const { config, job, setJob, startGeneration, notify, mode, setMode } = useStudio();
  const [url, setUrl] = useState('');
  const [num, setNum] = useState(config?.shorts_per_video || 10);
  const [busy, setBusy] = useState(false);
  const [canceling, setCanceling] = useState(false);
  const running = job?.status === 'running';

  // YouTube auto-post is a per-user preference stored in the browser. The
  // server still owns the default (config.youtube_auto_post), but a value
  // the user explicitly toggled survives reloads via localStorage and wins
  // over the server default until the user toggles it back.
  const YOUTUBE_AUTO_POST_KEY = 'youtubeAutoPost';
  const effectiveAutoPostRef = useRef(config?.youtube_auto_post);
  const [autoPostChecked, setAutoPostChecked] = useState(() => {
    if (typeof localStorage === 'undefined') return Boolean(config?.youtube_auto_post);
    const stored = localStorage.getItem(YOUTUBE_AUTO_POST_KEY);
    if (stored !== null) {
      const parsed = stored === 'true';
      effectiveAutoPostRef.current = parsed;
      return parsed;
    }
    effectiveAutoPostRef.current = Boolean(config?.youtube_auto_post);
    return Boolean(config?.youtube_auto_post);
  });

  // When the server config arrives (or re-fetches), refresh the default unless
  // the user has already overridden it with a localStorage value.
  useEffect(() => {
    if (typeof localStorage === 'undefined') return;
    const stored = localStorage.getItem(YOUTUBE_AUTO_POST_KEY);
    if (stored !== null) return; // user choice wins; don't clobber it with a refresh
    const next = Boolean(config?.youtube_auto_post);
    effectiveAutoPostRef.current = next;
    setAutoPostChecked(next);
  }, [config?.youtube_auto_post]);

  const toggleAutoPost = useCallback(
    (next) => {
      if (typeof localStorage === 'undefined') return;
      localStorage.setItem(YOUTUBE_AUTO_POST_KEY, String(next));
      effectiveAutoPostRef.current = next;
      setAutoPostChecked(next);
    },
    [],
  );

  async function submit(event) {
    event.preventDefault();
    if (!url.trim()) {
      notify('Paste a YouTube link first');
      return;
    }
    setBusy(true);
    try {
      await startGeneration(url.trim(), num, mode, effectiveAutoPostRef.current);
      setUrl('');
      notify('Generation started — clips land in 5–15 minutes');
    } catch (err) {
      notify(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function cancelJob() {
    if (!job?.id) return;
    setCanceling(true);
    try {
      const response = await fetch('/api/jobs/abort', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: job.id }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || 'Cancel failed');
      }
      notify(`Job ${job.id} cancelled`);
      setJob(null);
    } catch (err) {
      notify(err.message);
    } finally {
      setCanceling(false);
    }
  }

  return (
    <section className="card relative overflow-hidden">
      <div className="pointer-events-none absolute inset-x-0 -top-32 h-56 bg-[radial-gradient(45%_60%_at_50%_60%,rgb(var(--brand-rgb)/0.18),transparent_75%)]" />

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
            <Link2 className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" />
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

        {job && <Progress job={job} onClear={() => setJob(null)} onCancel={cancelJob} onCanceling={canceling} />}

        <div className="mt-4 flex flex-col gap-3 rounded-lg bg-wash p-3">
          <span className="text-xs text-muted">Clip mode</span>
          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={() => setMode('viral')}
              className={`relative w-full rounded-md px-4 py-2 text-sm font-medium transition ${
                mode === 'viral' ? 'bg-brand text-fg' : 'bg-wash-strong text-muted hover:text-fg'
              } ${running ? 'pointer-events-none opacity-50' : ''}`}
            >
              Viral Moments
            </button>
            <button
              type="button"
              onClick={() => setMode('equal')}
              className={`relative w-full rounded-md px-4 py-2 text-sm font-medium transition ${
                mode === 'equal' ? 'bg-brand text-fg' : 'bg-wash-strong text-muted hover:text-fg'
              } ${running ? 'pointer-events-none opacity-50' : ''}`}
            >
              Equal Slices
            </button>
            <button
              type="button"
              onClick={() => setMode('transform')}
              title="AI rewrite + voiceover, renders 21s/30s/59s versions"
              className={`relative w-full rounded-md px-4 py-2 text-sm font-medium transition ${
                mode === 'transform' ? 'bg-brand text-fg' : 'bg-wash-strong text-muted hover:text-fg'
              } ${running ? 'pointer-events-none opacity-50' : ''}`}
            >
              Transform
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-lg bg-wash p-3">
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted">Auto-post to YouTube Shorts</span>
            <Switch
              id="youtube-auto-post"
              label={autoPostChecked ? 'On' : 'Off'}
              checked={autoPostChecked}
              onChange={toggleAutoPost}
              disabled={busy || running}
            />
          </div>
          <span className="text-[11px] text-subtle">
            {typeof window !== 'undefined' && localStorage.getItem('youtubeAutoPost') != null
              ? 'Saved in this browser'
              : 'Default from config'}
          </span>
        </div>

        <p className="mt-4 text-[11px] text-subtle">
          {config?.shorts_per_video || 10} shorts per run · one job at a time
        </p>
      </div>
    </section>
  );
}

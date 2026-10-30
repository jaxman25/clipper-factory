'use client';

import { usePathname } from 'next/navigation';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

const EMPTY = {
  clips: [],
  posted: [],
  config: {
    timezone: 'Africa/Nairobi',
    posting_times: ['19:00', '21:00'],
    platforms: { instagram: true, tiktok: true },
  },
};

const StudioContext = createContext(null);

export function StudioProvider({ children }) {
  const pathname = usePathname();
  const [data, setData] = useState(EMPTY);
  const [health, setHealth] = useState(null);
  const [settings, setSettings] = useState(null);
  const [analyticsFeed, setAnalyticsFeed] = useState(null);
  const [job, setJob] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [mode, setMode] = useState('viral');
  const [loading, setLoading] = useState(true);
  const [toastText, setToastText] = useState('');
  const toastTimer = useRef(null);

  const notify = useCallback((text) => {
    setToastText(text);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToastText(''), 6000);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [clipsRes, healthRes, settingsRes, analyticsRes] = await Promise.all([
        fetch('/api/clips', { cache: 'no-store' }),
        fetch('/api/health', { cache: 'no-store' }),
        fetch('/api/settings', { cache: 'no-store' }),
        fetch('/api/analytics', { cache: 'no-store' }),
      ]);
      if (clipsRes.ok) setData(await clipsRes.json());
      if (healthRes.ok) setHealth(await healthRes.json());
      if (settingsRes.ok) setSettings(await settingsRes.json());
      if (analyticsRes.ok) setAnalyticsFeed(await analyticsRes.json());
    } catch (err) {
      notify(`Could not load state: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [notify]);

  const refreshJobs = useCallback(async () => {
    try {
      const response = await fetch('/api/generate', { cache: 'no-store' });
      if (!response.ok) return;
      const payload = await response.json();
      const list = payload.jobs || [];
      setJobs(list);

      // If the last known job was aborted, drop it. The abort endpoint marks
      // the document 'cancelled' (it keeps it for job history) instead of
      // deleting it, so a job that is missing or no longer 'running' is
      // treated as finished. This prevents the auto-polling from
      // re-triggering a phantom "running" job.
      setJob((current) => {
        if (current?.id) {
          const currentJob = list.find((entry) => entry.id === current.id);
          if (!currentJob) {
            return null;
          }
          return currentJob;
        }
        return list.find((entry) => entry.status === 'running') || null;
      });
    } catch (err) {
      /* the service can be cold-starting; retry on the next tick */
    }
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      refresh();
      refreshJobs();
    }, 20000);
    return () => clearInterval(timer);
  }, [refresh, refreshJobs]);

  // Re-fetch on every dashboard navigation. The provider lives in the layout
  // and therefore survives route changes, so without this a page can mount
  // with whatever was captured before the last save (e.g. returning to the
  // overview right after editing posting times on the settings page).
  useEffect(() => {
    refresh();
    refreshJobs();
  }, [pathname, refresh, refreshJobs]);

  // Analytics starts empty: state/analytics.json is only written when a point
  // arrives, and before this nothing ever sent one, so the chart could never
  // render. On the first load that finds posted clips but no points, seed one
  // point per posting date (read from the clips' own posted_at/created_at) so
  // the x-axis carries real dates. Views stay 0 on purpose - stuffing the clip
  // count into `views` would fabricate the earnings estimate ($0.50/1k). One
  // seed per mount; the API also dedupes by date, so re-runs are harmless.
  const seededAnalytics = useRef(false);
  useEffect(() => {
    if (seededAnalytics.current) return;
    const points = analyticsFeed?.points;
    const postedClips = data.posted || [];
    if (!Array.isArray(points) || points.length || !postedClips.length) return;
    seededAnalytics.current = true;
    const dates = [
      ...new Set(
        postedClips
          .map((clip) => String(clip.posted_at || clip.created_at || '').slice(0, 10))
          .filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date))
      ),
    ]
      .sort()
      .slice(-30); // the chart shows the last 30 days
    if (!dates.length) return;
    Promise.all(
      dates.map((date) =>
        fetch('/api/analytics', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ date, views: 0 }),
        }).then((response) => (response.ok ? response.json() : null))
      )
    )
      .then((payloads) => {
        const latest = payloads.filter(Boolean).pop();
        if (latest) setAnalyticsFeed(latest); // chart updates without waiting for the next poll
      })
      .catch(() => {
        /* the next refresh retries the read */
      });
  }, [analyticsFeed, data.posted]);

  // Pull live YouTube view counts once per load and fold the increase into
  // today's point, so the chart shows real numbers instead of seeded zeroes.
  // Missing API key, cold API or no YouTube clips: the route answers with a
  // reason and we simply keep what we have.
  const refreshedViews = useRef(false);
  useEffect(() => {
    if (refreshedViews.current || !analyticsFeed) return;
    refreshedViews.current = true;
    fetch('/api/analytics/refresh', { method: 'POST', cache: 'no-store' })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (payload?.ok && Array.isArray(payload.points)) {
          setAnalyticsFeed({
            points: payload.points,
            total_views: payload.total_views,
            estimated_earnings: payload.total_views / 1000 * 0.5,
          });
        }
      })
      .catch(() => {
        /* the next load retries */
      });
  }, [analyticsFeed]);

  useEffect(() => {
    if (job?.status !== 'running') return undefined;
    const timer = setInterval(async () => {
      try {
        const response = await fetch(`/api/generate?job_id=${encodeURIComponent(job.id)}`, {
          cache: 'no-store',
        });
        if (!response.ok) return;
        const next = await response.json();
        setJob(next);
        if (next.status === 'done') {
          notify(`${(next.clips || []).length} shorts ready`);
          refresh();
          refreshJobs();
        } else if (next.status === 'error') {
          notify(`Job failed: ${next.message || 'unknown error'}`);
          refresh();
          refreshJobs();
        }
      } catch (err) {
        /* transient error while the service wakes up */
      }
    }, 4000);
    return () => clearInterval(timer);
  }, [job?.id, job?.status, refresh, refreshJobs, notify]);

  const startGeneration = useCallback(
    async (url, numShorts, mode = 'viral', youtubeAutoPost = null, userConfig = null) => {
      const pc = userConfig || applySavedPreferences() || null;
      const body = {
        url,
        num_shorts: Number(numShorts),
        mode,
        ...(youtubeAutoPost !== null && { youtube_auto_post: youtubeAutoPost }),

      };
      const pick = (key) => pc ? pc[key] : undefined;
      const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok) {
        if (payload.job_id) {
          setJob({ id: payload.job_id, status: 'running', progress: 0, message: payload.error });
        }
        throw new Error(payload.error || 'Could not start generation');
      }
      setJob({
        id: payload.job_id,
        status: 'running',
        progress: 0,
        stage: 'queued',
        mode: mode,
        message: 'Queued for the clip worker',
      });
      refreshJobs();
      return payload;
    },
    [refreshJobs]
  );

  const applySavedPreferences = useCallback(() => {
    if (typeof window === 'undefined') return null;
    try {
      const raw = window.localStorage.getItem('userConfig');
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return null;
      // Only expose the keys the backend knows how to override, and only when
      // they look intentional. Missing keys are left undefined so the worker
      // falls back to config.json for that run.
      const out = {};
      const num = (key) => {
        if (key in parsed) {
          const n = Number(parsed[key]);
          if (Number.isFinite(n)) return n;
        }
        return undefined;
      };
      if (parsed.timezone && typeof parsed.timezone === 'string') out.timezone = parsed.timezone;
      if (Array.isArray(parsed.posting_times) && parsed.posting_times.length) {
        out.posting_times = parsed.posting_times.map((s) => String(s).trim()).filter(Boolean);
      }
      const _n_shorts = num('shorts_per_video');
      const _n_clip_min = num('clip_min_seconds');
      const _n_clip_max = num('clip_max_seconds');
      const _n_speed = num('playback_speed');
      const _n_drum = num('drum_volume_db');
      const _n_words = num('caption_words_per_card');
      const _n_hook = num('hook_seconds');
      if (_n_shorts != null) out.shorts_per_video = _n_shorts;
      if (_n_clip_min != null) out.clip_min_seconds = _n_clip_min;
      if (_n_clip_max != null) out.clip_max_seconds = _n_clip_max;
      if (_n_speed != null) out.playback_speed = _n_speed;
      if (_n_drum != null) out.drum_volume_db = _n_drum;
      if (_n_words != null) out.caption_words_per_card = _n_words;
      if ('outro_text' in parsed && typeof parsed.outro_text === 'string') out.outro_text = parsed.outro_text;
      if ('hashtags' in parsed && typeof parsed.hashtags === 'string') out.hashtags = parsed.hashtags;
      if ('caption_color' in parsed && typeof parsed.caption_color === 'string') out.caption_color = parsed.caption_color;
      if (parsed.instagram === true || parsed.instagram === false) out.instagram = parsed.instagram;
      if (parsed.tiktok === true || parsed.tiktok === false) out.tiktok = parsed.tiktok;
      if (parsed.youtube_auto_post === true || parsed.youtube_auto_post === false) out.youtube_auto_post = parsed.youtube_auto_post;
      if ('outro_text' in parsed && typeof parsed.outro_text === 'string') out.outro_text = parsed.outro_text;
      if ('hashtags' in parsed && typeof parsed.hashtags === 'string') out.hashtags = parsed.hashtags;
      if ('caption_color' in parsed && typeof parsed.caption_color === 'string') out.caption_color = parsed.caption_color;
      if (parsed.instagram === true || parsed.instagram === false) out.instagram = parsed.instagram;
      if (parsed.tiktok === true || parsed.tiktok === false) out.tiktok = parsed.tiktok;
      if (parsed.youtube_auto_post === true || parsed.youtube_auto_post === false) out.youtube_auto_post = parsed.youtube_auto_post;
      return Object.keys(out).length ? out : null;
    } catch (err) {
      return null;
    }
  }, []);


  const reschedule = useCallback(
    async (id, iso) => {
      const response = await fetch('/api/clips', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, scheduled_for: iso }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not reschedule');
      await refresh();
    },
    [refresh]
  );

  const clips = data.clips || [];
  const posted = data.posted || [];
  const avgScore = clips.length
    ? Math.round(clips.reduce((sum, clip) => sum + Number(clip.viral_score || 0), 0) / clips.length)
    : 0;

  const value = useMemo(
    () => {
      const userConfig = applySavedPreferences();
      // Prefer the dedicated /api/analytics feed (points + totals); the
      // settings payload only carries analytics when it was stored there.
      const raw = analyticsFeed?.points ? analyticsFeed : (settings || {}).analytics;
      const points = Array.isArray(raw?.points) ? raw.points : [];
      let views = 0;
      for (const p of points) {
        const v = Number(p.views);
        if (Number.isFinite(v)) views += v;
      }
      const analytics = {
        points: points.map((p) => ({ date: p.date || '', label: p.label || '', views: Number(p.views) || 0 })),
        total_views: views,
        estimated_earnings: views / 1000 * 0.5,
      };
      return {
        data,
        clips,
        posted,
        config: data.config || EMPTY.config,
        timeZone: data.config?.timezone || 'Africa/Nairobi',
        postingTimes: data.config?.posting_times?.length ? data.config.posting_times : ['19:00', '21:00'],
        avgScore,
        health,
        // Redacted integration status ({configured, hint} per key) so the
        // overview can show what is wired up without a second fetch.
        tokens: settings?.tokens || {},
        runtime: settings?.runtime || null,
        analytics,
        loading,
        job,
        jobs,
        setJob,
        refresh,
        refreshJobs,
        startGeneration,
        reschedule,
        notify,
        mode,
        setMode,
      };
    },
    [data, clips, posted, avgScore, health, settings, analyticsFeed, loading, job, jobs, refresh, refreshJobs, startGeneration, reschedule, notify, mode]
  );

  return (
    <StudioContext.Provider value={value}>
      {children}
      {toastText && (
        <div
          role="status"
          className="fixed bottom-6 left-1/2 z-[60] w-[min(92vw,420px)] -translate-x-1/2 animate-rise rounded-xl border border-line border-l-2 border-l-brand bg-raised px-4 py-3 break-words text-sm text-fg shadow-2xl"
        >
          {toastText}
        </div>
      )}
    </StudioContext.Provider>
  );
}

export function useStudio() {
  const context = useContext(StudioContext);
  if (!context) throw new Error('useStudio must be used inside StudioProvider');
  return context;
}

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
      const [clipsRes, healthRes, settingsRes] = await Promise.all([
        fetch('/api/clips', { cache: 'no-store' }),
        fetch('/api/health', { cache: 'no-store' }),
        fetch('/api/settings', { cache: 'no-store' }),
      ]);
      if (clipsRes.ok) setData(await clipsRes.json());
      if (healthRes.ok) setHealth(await healthRes.json());
      if (settingsRes.ok) setSettings(await settingsRes.json());
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

  // Write confirmed settings straight into shared state so every consumer
  // (overview header, posting calendar, generate panel) updates instantly,
  // without waiting for the next poll or another GET round-trip.
  const applyConfig = useCallback((patch = {}) => {
    setData((current) => ({
      ...current,
      config: {
        ...current.config,
        ...patch,
        ...(patch.platforms
          ? { platforms: { ...current.config?.platforms, ...patch.platforms } }
          : null),
      },
    }));
    setHealth((current) => {
      if (!current) return current;
      const next = { ...current };
      if (patch.posting_times !== undefined) next.posting_times = patch.posting_times;
      if (patch.timezone !== undefined) next.timezone = patch.timezone;
      if (patch.youtube_auto_post !== undefined) next.youtube_auto_post = patch.youtube_auto_post;
      return next;
    });
  }, []);

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
    async (url, numShorts, mode = 'viral') => {
      const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, num_shorts: Number(numShorts), mode }),
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
    () => ({
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
      loading,
      job,
      jobs,
      setJob,
      refresh,
      refreshJobs,
      applyConfig,
      startGeneration,
      reschedule,
      notify,
      mode,
      setMode,
    }),
    [
      data,
      clips,
      posted,
      avgScore,
      health,
      settings,
      loading,
      job,
      jobs,
      refresh,
      refreshJobs,
      applyConfig,
      startGeneration,
      reschedule,
      notify,
      mode,
    ]
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

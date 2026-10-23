'use client';

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
  const [data, setData] = useState(EMPTY);
  const [health, setHealth] = useState(null);
  const [job, setJob] = useState(null);
  const [jobs, setJobs] = useState([]);
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
      const [clipsRes, healthRes] = await Promise.all([
        fetch('/api/clips', { cache: 'no-store' }),
        fetch('/api/health', { cache: 'no-store' }),
      ]);
      if (clipsRes.ok) setData(await clipsRes.json());
      if (healthRes.ok) setHealth(await healthRes.json());
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
      setJob((current) => {
        if (current?.id) {
          return list.find((entry) => entry.id === current.id) || current;
        }
        return list.find((entry) => entry.status === 'running') || null;
      });
    } catch (err) {
      /* the service can be cold-starting; retry on the next tick */
    }
  }, []);

  useEffect(() => {
    refresh();
    refreshJobs();
    const timer = setInterval(() => {
      refresh();
      refreshJobs();
    }, 20000);
    return () => clearInterval(timer);
  }, [refresh, refreshJobs]);

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
    async (url, numShorts) => {
      const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, num_shorts: Number(numShorts) }),
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
      loading,
      job,
      jobs,
      setJob,
      refresh,
      refreshJobs,
      startGeneration,
      reschedule,
      notify,
    }),
    [data, clips, posted, avgScore, health, loading, job, jobs, refresh, refreshJobs, startGeneration, reschedule, notify]
  );

  return (
    <StudioContext.Provider value={value}>
      {children}
      {toastText && (
        <div
          role="status"
          className="fixed bottom-6 left-1/2 z-[60] w-[min(92vw,420px)] -translate-x-1/2 animate-rise rounded-xl border border-white/10 border-l-2 border-l-brand bg-raised px-4 py-3 text-sm text-white shadow-2xl"
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

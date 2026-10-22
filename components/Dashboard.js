'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import TopBar from '@/components/TopBar';
import CalendarBoard from '@/components/CalendarBoard';
import ClipCard from '@/components/ClipCard';
import { formatInTZ } from '@/lib/time';

const EMPTY = {
  clips: [],
  posted: [],
  config: {
    timezone: 'Africa/Nairobi',
    posting_times: ['19:00', '21:00'],
    platforms: { instagram: true, tiktok: true },
  },
};

export default function Dashboard() {
  const [data, setData] = useState(EMPTY);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [job, setJob] = useState(null);
  const [url, setUrl] = useState('');
  const [num, setNum] = useState(10);
  const [tab, setTab] = useState('queue');
  const [generating, setGenerating] = useState(false);
  const [toastText, setToastText] = useState('');
  const [clock, setClock] = useState('');
  const toastTimer = useRef(null);

  const timeZone = data.config?.timezone || 'Africa/Nairobi';
  const clips = data.clips || [];
  const posted = data.posted || [];

  const toast = useCallback((text) => {
    setToastText(text);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToastText(''), 6000);
  }, []);

  const load = useCallback(async () => {
    try {
      const [clipsRes, healthRes] = await Promise.all([
        fetch('/api/clips', { cache: 'no-store' }),
        fetch('/api/health', { cache: 'no-store' }),
      ]);
      if (clipsRes.ok) setData(await clipsRes.json());
      if (healthRes.ok) setHealth(await healthRes.json());
    } catch (err) {
      toast(`Could not load state: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
    fetch('/api/generate', { cache: 'no-store' })
      .then((response) => response.json())
      .then((payload) => {
        const running = (payload.jobs || []).find((entry) => entry.status === 'running');
        if (running) setJob(running);
      })
      .catch(() => {});
  }, [load]);

  useEffect(() => {
    const tick = () =>
      setClock(
        new Intl.DateTimeFormat('en-GB', {
          timeZone,
          dateStyle: 'medium',
          timeStyle: 'short',
        }).format(new Date())
      );
    tick();
    const timer = setInterval(tick, 30000);
    return () => clearInterval(timer);
  }, [timeZone]);

  useEffect(() => {
    if (!job || job.status !== 'running') return undefined;
    const timer = setInterval(async () => {
      try {
        const response = await fetch(`/api/generate?job_id=${encodeURIComponent(job.id)}`, {
          cache: 'no-store',
        });
        if (!response.ok) return;
        const next = await response.json();
        setJob(next);
        if (next.status === 'done') {
          toast(`${(next.clips || []).length} shorts ready — scroll down to preview`);
          load();
        } else if (next.status === 'error') {
          toast(`Job failed: ${next.message}`);
          load();
        }
      } catch (err) {
        /* transient fetch error while the service wakes up */
      }
    }, 4000);
    return () => clearInterval(timer);
  }, [job?.id, job?.status, load, toast]);

  async function startGeneration(event) {
    event.preventDefault();
    if (!url.trim()) {
      toast('Paste a YouTube link first');
      return;
    }
    setGenerating(true);
    try {
      const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim(), num_shorts: Number(num) }),
      });
      const payload = await response.json();
      if (!response.ok) {
        if (payload.job_id) setJob({ id: payload.job_id, status: 'running', progress: 0, message: payload.error });
        throw new Error(payload.error || 'Could not start generation');
      }
      setJob({ id: payload.job_id, status: 'running', progress: 0, message: 'Queued for the clip worker' });
      setUrl('');
      toast('Generation started — this takes 5-15 minutes');
    } catch (err) {
      toast(err.message);
    } finally {
      setGenerating(false);
    }
  }

  async function reschedule(id, iso) {
    try {
      const response = await fetch('/api/clips', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, scheduled_for: iso }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not reschedule');
      toast('Clip rescheduled');
      await load();
    } catch (err) {
      toast(err.message);
    }
  }

  const avgScore = clips.length
    ? Math.round(clips.reduce((sum, clip) => sum + Number(clip.viral_score || 0), 0) / clips.length)
    : 0;
  const nextPost = clips[0]?.scheduled_for;

  return (
    <>
      <TopBar active="dashboard" health={health} />
      <main className="container">
        <section className="hero">
          <div>
            <div className="eyebrow">YouTube → 10 shorts → autopilot</div>
            <h1>African tales, cut for the scroll.</h1>
            <p>
              Paste one link. Whisper finds the story beats, the viral detector ranks them, ffmpeg
              reframes 9:16 with word-pop captions, and the scheduler posts two a day at{' '}
              {(data.config?.posting_times || ['19:00', '21:00']).join(' & ')} ({timeZone}).
            </p>
          </div>
          <div className="hero-stats">
            <div className="stat">
              <b>{clips.length}</b>
              <span>Queued</span>
            </div>
            <div className="stat">
              <b>{posted.length}</b>
              <span>Posted</span>
            </div>
            <div className="stat">
              <b>{avgScore || '—'}</b>
              <span>Avg score</span>
            </div>
            <div className="stat">
              <b style={{ fontSize: 15 }}>{clock || '—'}</b>
              <span>Local time</span>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2 className="panel-title">New clip run</h2>
              <p className="panel-sub">
                yt-dlp → faster-whisper → viral scoring → 1080×1920 render → queue
              </p>
            </div>
            {job && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setJob(null)}>
                {job.status === 'running' ? 'Hide progress' : 'Clear'}
              </button>
            )}
          </div>

          <form className="generate-form" onSubmit={startGeneration}>
            <div className="field">
              <label htmlFor="youtube-url">YouTube URL</label>
              <input
                id="youtube-url"
                type="url"
                placeholder="https://www.youtube.com/watch?v=…"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                disabled={generating || job?.status === 'running'}
              />
            </div>
            <div className="field">
              <label htmlFor="num-shorts">Shorts</label>
              <input
                id="num-shorts"
                type="number"
                min={1}
                max={20}
                value={num}
                onChange={(event) => setNum(event.target.value)}
                disabled={generating || job?.status === 'running'}
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={generating || job?.status === 'running'}
            >
              {generating ? 'Starting…' : job?.status === 'running' ? 'Working…' : 'Generate'}
            </button>
          </form>

          {job && (
            <div style={{ marginTop: 18 }}>
              <div className="job-line">
                <span>
                  <b>{job.id}</b> · {job.message || job.stage}
                </span>
                <b>{job.progress || 0}%</b>
              </div>
              <div className="progress">
                <div className="progress-bar" style={{ width: `${job.progress || 0}%` }} />
              </div>
              {job.error && <p className="note error">{job.error}</p>}
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2 className="panel-title">Posting calendar</h2>
              <p className="panel-sub">
                Next 7 days · drag a clip to move its slot ({timeZone})
                {nextPost ? ` · next ${formatInTZ(nextPost, timeZone)}` : ''}
              </p>
            </div>
          </div>
          <CalendarBoard
            clips={clips}
            timeZone={timeZone}
            postingTimes={data.config?.posting_times}
            onReschedule={reschedule}
            busy={job?.status === 'running'}
          />
        </section>

        <div className="toolbar">
          <div className="tabs">
            <button
              type="button"
              className={`tab ${tab === 'queue' ? 'active' : ''}`}
              onClick={() => setTab('queue')}
            >
              Queue ({clips.length})
            </button>
            <button
              type="button"
              className={`tab ${tab === 'posted' ? 'active' : ''}`}
              onClick={() => setTab('posted')}
            >
              Posted ({posted.length})
            </button>
          </div>
          <div className="toolbar-actions">
            <button type="button" className="btn btn-sm" onClick={load}>
              Refresh
            </button>
            <a
              className={`btn btn-sm ${clips.length || posted.length ? 'btn-primary' : ''}`}
              href="/api/download"
              aria-disabled={!clips.length && !posted.length}
              onClick={(event) => {
                if (!clips.length && !posted.length) event.preventDefault();
              }}
            >
              Download All ZIP
            </a>
          </div>
        </div>

        {loading ? (
          <div className="clip-grid">
            <div className="skeleton" />
            <div className="skeleton" />
            <div className="skeleton" />
          </div>
        ) : tab === 'queue' ? (
          clips.length ? (
            <div className="clip-grid">
              {clips.map((clip) => (
                <ClipCard
                  key={clip.id}
                  clip={clip}
                  timeZone={timeZone}
                  onRefresh={load}
                  toast={toast}
                />
              ))}
            </div>
          ) : (
            <div className="empty">
              <h3>Queue is empty</h3>
              <p>Paste a YouTube link above — or send /clip to the Telegram bot.</p>
            </div>
          )
        ) : posted.length ? (
          <div className="clip-grid">
            {posted.map((clip) => (
              <ClipCard
                key={clip.id}
                clip={clip}
                timeZone={timeZone}
                onRefresh={load}
                toast={toast}
              />
            ))}
          </div>
        ) : (
          <div className="empty">
            <h3>Nothing posted yet</h3>
            <p>Clips land here after Instagram/TikTok accept them.</p>
          </div>
        )}

        <p className="footer">
          Media lives in <code>$ACF_DATA_ROOT</code> (/tmp on Render). Render free instances sleep after 15
          minutes — keep <code>/api/health</code> warm with UptimeRobot.
        </p>
      </main>
      {toastText && <div className="toast">{toastText}</div>}
    </>
  );
}

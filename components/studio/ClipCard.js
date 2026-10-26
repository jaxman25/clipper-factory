'use client';

import { useEffect, useState } from 'react';
import { CalendarClock, Download, Loader2, Save, Send, Sparkles } from 'lucide-react';
import { useStudio } from '@/components/studio/StudioProvider';
import { dayKeyInTZ, formatInTZ, timeInTZ, zonedToIso } from '@/lib/time';
import { cn } from '@/lib/cn';

export default function ClipCard({ clip }) {
  const { timeZone, refresh, notify } = useStudio();
  const posted = clip.state === 'posted';
  const [caption, setCaption] = useState(clip.caption || '');
  const [date, setDate] = useState(dayKeyInTZ(clip.scheduled_for, timeZone));
  const [time, setTime] = useState(timeInTZ(clip.scheduled_for, timeZone));
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState('');

  useEffect(() => {
    setCaption(clip.caption || '');
    setDate(dayKeyInTZ(clip.scheduled_for, timeZone));
    setTime(timeInTZ(clip.scheduled_for, timeZone));
  }, [clip.id, clip.caption, clip.scheduled_for, timeZone]);

  async function saveCaption() {
    setBusy('caption');
    setNote(null);
    try {
      const response = await fetch('/api/clips', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: clip.id, caption }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not save caption');
      setNote({ kind: 'ok', text: 'Caption saved' });
      refresh();
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    } finally {
      setBusy('');
    }
  }

  async function reschedule() {
    if (!date || !time) {
      setNote({ kind: 'error', text: 'Pick a date and time first' });
      return;
    }
    setBusy('schedule');
    setNote(null);
    try {
      const response = await fetch('/api/clips', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: clip.id, scheduled_for: zonedToIso(date, time, timeZone) }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not reschedule');
      setNote({ kind: 'ok', text: 'Rescheduled' });
      notify('Clip rescheduled');
      refresh();
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    } finally {
      setBusy('');
    }
  }

  async function postNow() {
    if (!window.confirm('Post this clip to Instagram and TikTok now?')) return;
    setBusy('post');
    setNote(null);
    try {
      const response = await fetch(`/api/clips/${encodeURIComponent(clip.id)}/post`, { method: 'POST' });
      const data = await response.json();
      if (response.status === 202 || data.pending) {
        setNote({ kind: 'ok', text: data.message || 'Posting in the background…' });
      } else if (!response.ok || !data.ok) {
        throw new Error(data.result?.reason || data.error || 'Posting failed');
      } else {
        setNote({ kind: 'ok', text: 'Posted successfully' });
        notify('Posted to your platforms');
      }
      refresh();
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    } finally {
      setBusy('');
    }
  }

  async function sendTelegram() {
    setBusy('telegram');
    setNote(null);
    try {
      const response = await fetch('/api/telegram', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: clip.id }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Telegram upload failed');
      setNote({ kind: 'ok', text: 'Sent to Telegram' });
      notify('Clip sent to Telegram');
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    } finally {
      setBusy('');
    }
  }

  const platforms = Object.entries(clip.platforms || {})
    .filter(([, value]) => value?.ok)
    .map(([key]) => key);

  return (
    <article className="card flex flex-col overflow-hidden">
      <div className="relative bg-black">
        <video
          src={clip.media_url}
          poster={clip.thumb_url}
          controls
          playsInline
          preload="metadata"
          className="aspect-[9/16] max-h-[360px] w-full object-contain"
        />
        <span
          className={cn(
            'absolute left-3 top-3 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide backdrop-blur',
            posted ? 'bg-emerald-500/15 text-ok' : 'bg-black/60 text-fg'
          )}
        >
          {clip.manual_required ? 'Needs manual' : posted ? 'Posted' : 'Queued'}
        </span>
        <span className="absolute right-3 top-3 rounded-full bg-black/60 px-2.5 py-1 text-[10px] font-bold text-[#FFD700] backdrop-blur">
          🔥 {Math.round(clip.viral_score || 0)}
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <h3 className="line-clamp-2 text-sm font-semibold leading-snug">
            {clip.hook || clip.title || clip.id}
          </h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="pill">{Number(clip.duration || 0).toFixed(1)}s</span>
            <span className="pill">
              <Sparkles className="h-3 w-3 text-brand" />
              {clip.face_detected ? 'face crop' : 'cinematic'}
            </span>
            <span className="pill">
              <CalendarClock className="h-3 w-3" />
              {formatInTZ(clip.scheduled_for, timeZone)}
            </span>
            {posted && platforms.length > 0 && <span className="pill">{platforms.join(' + ')}</span>}
          </div>
        </div>

        <div>
          <label htmlFor={`caption-${clip.id}`} className="label">
            Caption
          </label>
          <textarea
            id={`caption-${clip.id}`}
            value={caption}
            rows={3}
            onChange={(event) => setCaption(event.target.value)}
            disabled={posted || busy === 'caption'}
            className="input mt-1.5 resize-y text-[13px] leading-relaxed"
          />
        </div>

        {!posted && (
          <div className="grid grid-cols-[1fr_88px] gap-2">
            <div>
              <label htmlFor={`date-${clip.id}`} className="label">
                Date ({timeZone.split('/').pop()})
              </label>
              <input
                id={`date-${clip.id}`}
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
                className="input mt-1.5 px-2.5 py-2 text-xs"
              />
            </div>
            <div>
              <label htmlFor={`time-${clip.id}`} className="label">
                Time
              </label>
              <input
                id={`time-${clip.id}`}
                type="time"
                value={time}
                onChange={(event) => setTime(event.target.value)}
                className="input mt-1.5 px-2.5 py-2 text-xs"
              />
            </div>
            <button
              type="button"
              onClick={reschedule}
              disabled={busy === 'schedule'}
              className="btn btn-sm col-span-2"
            >
              {busy === 'schedule' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              {busy === 'schedule' ? 'Saving…' : 'Reschedule'}
            </button>
          </div>
        )}

        <div className="mt-auto flex flex-wrap gap-2 pt-1">
          {!posted && (
            <>
              <button type="button" onClick={saveCaption} disabled={busy === 'caption'} className="btn btn-sm">
                <Save className="h-3.5 w-3.5" />
                {busy === 'caption' ? 'Saving…' : 'Save'}
              </button>
              <button type="button" onClick={postNow} disabled={busy === 'post'} className="btn btn-primary btn-sm">
                <Send className="h-3.5 w-3.5" />
                {busy === 'post' ? 'Posting…' : 'Post now'}
              </button>
            </>
          )}
          <button type="button" onClick={sendTelegram} disabled={busy === 'telegram'} className="btn btn-sm">
            <Send className="h-3.5 w-3.5 text-brand" />
            {busy === 'telegram' ? 'Sending…' : 'Telegram'}
          </button>
          <a href={clip.download_url} className="btn btn-ghost btn-sm">
            <Download className="h-3.5 w-3.5" />
            Download
          </a>
        </div>

        {note && (
          <p className={cn('text-[11px]', note.kind === 'error' ? 'text-danger' : 'text-ok')}>
            {note.text}
          </p>
        )}
        {!note && posted && clip.posted_at && (
          <p className="text-[11px] text-subtle">Posted {formatInTZ(clip.posted_at, timeZone)}</p>
        )}
      </div>
    </article>
  );
}

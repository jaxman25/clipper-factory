'use client';

import { useEffect, useState } from 'react';
import { dayKeyInTZ, formatInTZ, timeInTZ, zonedToIso } from '@/lib/time';

export default function ClipCard({ clip, timeZone, onRefresh, toast }) {
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
      onRefresh?.();
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
      toast?.('Clip rescheduled');
      onRefresh?.();
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
      const response = await fetch(`/api/clips/${encodeURIComponent(clip.id)}/post`, {
        method: 'POST',
      });
      const data = await response.json();
      if (response.status === 202 || data.pending) {
        setNote({ kind: 'ok', text: data.message || 'Posting in the background…' });
      } else if (!response.ok || !data.ok) {
        const detail = data.result?.reason || data.error || 'Posting failed';
        throw new Error(detail);
      } else {
        setNote({ kind: 'ok', text: 'Posted successfully' });
        toast?.('Posted to your platforms');
      }
      onRefresh?.();
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
      toast?.('Clip sent to Telegram');
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    } finally {
      setBusy('');
    }
  }

  const platforms = Object.entries(clip.platforms || {})
    .filter(([, value]) => value && value.ok)
    .map(([key]) => key);

  return (
    <article className="clip-card">
      <div className="thumb-wrap">
        <video
          src={clip.media_url}
          poster={clip.thumb_url}
          controls
          playsInline
          preload="metadata"
        />
        <span className={`badge ${posted ? 'posted' : ''}`}>
          {clip.manual_required ? 'Needs manual' : posted ? 'Posted' : 'Queued'}
        </span>
        <span className="badge score">🔥 {Math.round(clip.viral_score || 0)}</span>
      </div>

      <div className="clip-body">
        <h3 className="clip-title">{clip.hook || clip.title || clip.id}</h3>
        <div className="clip-meta">
          <span className="pill">{Number(clip.duration || 0).toFixed(1)}s</span>
          <span className="pill">{clip.face_detected ? 'face crop' : 'cinematic'}</span>
          <span className="pill">{formatInTZ(clip.scheduled_for, timeZone)}</span>
          {posted && platforms.length > 0 && <span className="pill">{platforms.join(' + ')}</span>}
        </div>

        <div className="field">
          <label htmlFor={`caption-${clip.id}`}>Caption</label>
          <textarea
            id={`caption-${clip.id}`}
            value={caption}
            rows={4}
            onChange={(event) => setCaption(event.target.value)}
            disabled={posted || busy === 'caption'}
          />
        </div>

        {!posted && (
          <div className="schedule-row">
            <div className="field">
              <label htmlFor={`date-${clip.id}`}>Date ({timeZone.split('/').pop()})</label>
              <input
                id={`date-${clip.id}`}
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor={`time-${clip.id}`}>Time</label>
              <input
                id={`time-${clip.id}`}
                type="time"
                value={time}
                onChange={(event) => setTime(event.target.value)}
              />
            </div>
            <button
              type="button"
              className="btn btn-sm"
              onClick={reschedule}
              disabled={busy === 'schedule'}
            >
              {busy === 'schedule' ? 'Saving…' : 'Reschedule'}
            </button>
          </div>
        )}

        <div className="actions">
          {!posted && (
            <>
              <button type="button" className="btn btn-sm" onClick={saveCaption} disabled={busy === 'caption'}>
                {busy === 'caption' ? 'Saving…' : 'Save caption'}
              </button>
              <button type="button" className="btn btn-primary btn-sm" onClick={postNow} disabled={busy === 'post'}>
                {busy === 'post' ? 'Posting…' : 'Post Now'}
              </button>
            </>
          )}
          <button type="button" className="btn btn-sm" onClick={sendTelegram} disabled={busy === 'telegram'}>
            {busy === 'telegram' ? 'Sending…' : 'Send to Telegram Now'}
          </button>
          <a className="btn btn-sm btn-ghost" href={clip.download_url}>
            Download
          </a>
        </div>

        {note && <p className={`note ${note.kind}`}>{note.text}</p>}
        {!note && posted && clip.posted_at && (
          <p className="note">Posted {formatInTZ(clip.posted_at, timeZone)}</p>
        )}
      </div>
    </article>
  );
}

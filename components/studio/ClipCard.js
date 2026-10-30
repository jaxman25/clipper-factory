'use client';

import { useEffect, useRef, useState } from 'react';
import { CalendarClock, Download, Loader2, Pencil, Save, Send, Sparkles, X, DollarSign, TrendingUp } from 'lucide-react';
import { useStudio } from '@/components/studio/StudioProvider';
import { dayKeyInTZ, formatInTZ, timeInTZ, zonedToIso } from '@/lib/time';
import { cn } from '@/lib/cn';
import MultiPlatformPlayer from '@/components/studio/MultiPlatformPlayer';
import MetadataEditor from '@/components/studio/MetadataEditor';

export default function ClipCard({ clip }) {
  const { timeZone, refresh, notify } = useStudio();
  const posted = clip.state === 'posted';
  const [caption, setCaption] = useState(clip.caption || '');
  const [date, setDate] = useState(dayKeyInTZ(clip.scheduled_for, timeZone));
  const [time, setTime] = useState(timeInTZ(clip.scheduled_for, timeZone));
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState('');

  // Which AI metadata set the user picked (title/description/hashtags).
  const [selectedMeta, setSelectedMeta] = useState(() => {
    if (clip.metadata_selected_set_index != null && Number.isFinite(Number(clip.metadata_selected_set_index))) {
      return { setIndex: Number(clip.metadata_selected_set_index) };
    }
    if (Array.isArray(clip.metadata_variants?.titles) && clip.metadata_variants.titles.length) {
      return { setIndex: 0 };
    }
    return null;
  });

  // Edit modal: opened from the "Edit clip" button below; the modal owns its
  // form state and re-renders the clip through /api/clips/edit.
  const [isEditing, setIsEditing] = useState(false);

  useEffect(() => {
    setCaption(clip.caption || '');
    setDate(dayKeyInTZ(clip.scheduled_for, timeZone));
    setTime(timeInTZ(clip.scheduled_for, timeZone));
    if (Array.isArray(clip.metadata_variants?.titles) && clip.metadata_variants.titles.length) {
      if (selectedMeta == null || selectedMeta.setIndex >= clip.metadata_variants.titles.length) {
        setSelectedMeta({ setIndex: 0 });
      }
    } else {
      setSelectedMeta(null);
    }
  }, [clip.id, clip.caption, clip.scheduled_for, clip.metadata_variants, timeZone]);

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

  async function saveMetadataSelection() {
    if (!selectedMeta) return;
    setBusy('metadata');
    setNote(null);
    try {
      const response = await fetch('/api/clips', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: clip.id,
          metadata_selected_set_index: selectedMeta.setIndex,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not save metadata selection');
      setNote({ kind: 'ok', text: 'Metadata set saved' });
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

  function applySelectedMetadata(selected) {
    setSelectedMeta(selected);
    if (selected) {
      const title = selected.title || '';
      const description = selected.description || '';
      const hashtags = selected.hashtags || '';
      const caption = [title, description, hashtags].filter(Boolean).join(' ').trim();
      setCaption(caption);
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

  const isTransform = clip.mode === 'transform';

  function transformedBadge() {
    const speed = Number(clip.speed);
    const transformed =
      Number.isFinite(speed) &&
      speed >= 1.1 &&
      speed <= 1.2 &&
      Boolean(clip.voiceover) &&
      clip.metadata_variants != null;
    if (transformed) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-ok/15 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-ok backdrop-blur">
          <TrendingUp className="h-3 w-3" />
          Transformed: Safe to Post
        </span>
      );
    }
    return (
      <span className="inline-flex items-center justify-center rounded-full bg-wash-strong px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-subtle backdrop-blur">
        Standard
      </span>
    );
  }

  const earningsPerThousand = 0.5;
  const totalViews = Number(clip._analytics?.total_views ?? 0);
  const estimatedEarnings = totalViews > 0 ? (totalViews / 1000) * earningsPerThousand : 0;

  return (
    <>
    <article className="card flex flex-col overflow-hidden">
      <div className="relative bg-black">
        <MultiPlatformPlayer clip={clip} />
        <span
          className={cn(
            'absolute left-3 top-3 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide backdrop-blur',
            posted ? 'bg-ok/15 text-ok' : 'bg-black/60 text-fg'
          )}
        >
          {clip.manual_required ? 'Needs manual' : posted ? 'Posted' : 'Queued'}
        </span>
        <div className="absolute right-3 top-3 flex gap-2">
          {transformedBadge()}
          {!isTransform && (
            <span className="rounded-full bg-black/60 px-2.5 py-1 text-[10px] font-bold text-[#FFD700] backdrop-blur">
              🔥 {Math.round(clip.viral_score || 0)}
            </span>
          )}
        </div>
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
            {isTransform && (
              <span className="pill">
                <TrendingUp className="h-3 w-3 text-brand" />
                Transformed
              </span>
            )}
          </div>
        </div>

        {isTransform && clip.metadata_variants && (
          <div>
            <MetadataEditor clip={clip} selected={selectedMeta} onSelect={applySelectedMetadata} />
          </div>
        )}

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
        )}          <div className="mt-auto flex flex-wrap gap-2 pt-1">
            {!posted && (
              <>
                <button type="button" onClick={() => setIsEditing(true)} className="btn btn-sm">
                  <Pencil className="h-3.5 w-3.5" />
                  Edit clip
                </button>
                <button type="button" onClick={saveCaption} disabled={busy === 'caption'} className="btn btn-sm">
                  <Save className="h-3.5 w-3.5" />
                  {busy === 'caption' ? 'Saving…' : 'Save'}
                </button>
                {isTransform && selectedMeta && (
                  <button type="button" onClick={saveMetadataSelection} disabled={busy === 'metadata'} className="btn btn-sm">
                    <Save className="h-3.5 w-3.5" />
                    {busy === 'metadata' ? 'Saving…' : 'Save metadata set'}
                  </button>
                )}
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
        {isTransform && (
          <div className="mt-3 flex items-center gap-3 rounded-lg border border-line/60 bg-wash/40 p-3">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
              <DollarSign className="h-3.5 w-3.5" />
              Est. earnings
            </div>
            <div className="tabular-nums text-sm font-semibold">
              ${estimatedEarnings.toFixed(2)}
            </div>              <p className="text-[11px] text-subtle">
              {(totalViews / 1000).toFixed(1)}k views · ${estimatedEarnings.toFixed(2)}/thousand
            </p>
          </div>
        )}
      </div>
    </article>
      <ClipEditModal
        clip={clip}
        open={isEditing}
        onClose={() => setIsEditing(false)}
      />
    </>
  );
}

/**
 * Modal for editing a clip's start and end times.
 */
export function ClipEditModal({ clip, open, onClose }) {
  const { refresh, notify } = useStudio();
  const videoRef = useRef(null);
  const [start, setStart] = useState(String(clip.start ?? 0));
  const [end, setEnd] = useState(String(clip.end ?? clip.duration ?? 0));
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);

  // The preview plays the clip file itself, so the editable window is the
  // clip's current [start, end] range (seconds on the original source
  // timeline, which is also what gets sent to the re-render API).
  const windowStart = Number(clip.start ?? 0);
  const windowEnd =
    Number.isFinite(Number(clip.end)) && Number(clip.end) > windowStart
      ? Number(clip.end)
      : windowStart + Number(clip.duration ?? 0);

  useEffect(() => {
    if (open) {
      setStart(String(clip.start ?? 0));
      setEnd(String(clip.end ?? clip.duration ?? 0));
      setNote(null);
      setBusy(false);
      const video = videoRef.current;
      if (video) video.currentTime = 0;
    }
  }, [open, clip.id]);

  if (!open) return null;

  // Map a source-timestamp onto the previewed clip file and seek there, so
  // dragging a slider shows exactly the frame at that timestamp.
  function seekTo(absolute) {
    const video = videoRef.current;
    if (!video) return;
    const relative = Number(absolute) - windowStart;
    const limit =
      Number.isFinite(video.duration) && video.duration > 0
        ? video.duration
        : Number(clip.duration || windowEnd - windowStart);
    video.pause();
    video.currentTime = Math.min(Math.max(relative, 0), Math.max(limit - 0.05, 0));
  }

  // Sliders stay inside the window and never cross each other.
  function changeStart(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return;
    const clamped = Math.min(Math.max(numeric, windowStart), Number(end) - 0.1);
    setStart(String(Number(clamped.toFixed(1))));
    seekTo(clamped);
  }

  function changeEnd(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return;
    const clamped = Math.max(Math.min(numeric, windowEnd), Number(start) + 0.1);
    setEnd(String(Number(clamped.toFixed(1))));
    seekTo(clamped);
  }

  async function handleSave() {
    // Raw typing in the number boxes is allowed; clamp once at save time.
    const rawStart = Number.isFinite(Number(start)) ? Number(start) : windowStart;
    const rawEnd = Number.isFinite(Number(end)) ? Number(end) : windowEnd;
    const payloadStart = Math.min(Math.max(rawStart, windowStart), rawEnd - 0.1);
    const payloadEnd = Math.max(Math.min(rawEnd, windowEnd), payloadStart + 0.1);

    setBusy(true);
    setNote(null);
    try {
      const response = await fetch('/api/clips/edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clip_id: clip.id,
          new_start: Number(payloadStart.toFixed(1)),
          new_end: Number(payloadEnd.toFixed(1)),
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || 'Could not save edits');
      }
      onClose();
      notify('Clip re-rendered with new start/end times');
      refresh();
    } catch (err) {
      setNote({ kind: 'error', text: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="w-[92vw] max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl bg-surface border border-line p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-fg">Edit clip</h2>
            <p className="mt-0.5 text-[12px] text-subtle">{clip.hook || clip.title || clip.id}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-muted hover:bg-wash hover:text-fg transition"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4">
          <video
            ref={videoRef}
            src={clip.media_url}
            poster={clip.thumb_url}
            controls
            playsInline
            className="w-full rounded-lg border border-line bg-black/40 aspect-[9/16] max-h-[320px]"
          />
          <p className="mt-1 text-[11px] text-subtle">
            {clip.duration ? `Current duration: ${clip.duration}s` : 'Clip duration will be recalculated from your edits.'}
          </p>
        </div>

        <div className="mt-4 space-y-4">
          <div>
            <label htmlFor="edit-start" className="label">
              Start time ({windowStart}s – {windowEnd}s)
            </label>
            <input
              id="edit-start"
              type="range"
              min={windowStart}
              max={windowEnd}
              step={0.1}
              value={start}
              onChange={(event) => changeStart(event.target.value)}
              className="mt-1.5 w-full accent-brand"
              disabled={busy}
            />
            <input
              id="edit-start-seconds"
              type="number"
              step="0.1"
              value={start}
              onChange={(event) => {
                setStart(event.target.value);
                if (Number.isFinite(Number(event.target.value))) seekTo(event.target.value);
              }}
              className="input mt-1.5"
              disabled={busy}
            />
          </div>
          <div>
            <label htmlFor="edit-end" className="label">
              End time ({windowStart}s – {windowEnd}s)
            </label>
            <input
              id="edit-end"
              type="range"
              min={windowStart}
              max={windowEnd}
              step={0.1}
              value={end}
              onChange={(event) => changeEnd(event.target.value)}
              className="mt-1.5 w-full accent-brand"
              disabled={busy}
            />
            <input
              id="edit-end-seconds"
              type="number"
              step="0.1"
              value={end}
              onChange={(event) => {
                setEnd(event.target.value);
                if (Number.isFinite(Number(event.target.value))) seekTo(event.target.value);
              }}
              className="input mt-1.5"
              disabled={busy}
            />
          </div>
          <p className="text-[11px] text-subtle">
            New duration:{' '}
            {Math.max((Number.isFinite(Number(end)) ? Number(end) : windowEnd) - (Number.isFinite(Number(start)) ? Number(start) : windowStart), 0).toFixed(1)}s
            {' — '}drag a slider to preview that exact frame.
          </p>
        </div>

        {note && (
          <p className={cn('text-[11px]', note.kind === 'error' ? 'text-danger' : 'text-ok')}>
            {note.text}
          </p>
        )}

        <div className="mt-5 flex gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn btn-ghost"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={busy}
            className="btn btn-primary"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            {busy ? 'Rendering…' : 'Save & re-render'}
          </button>
        </div>
      </div>
    </div>
  );
}


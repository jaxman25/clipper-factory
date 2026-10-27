import fs from 'node:fs';
import path from 'node:path';
import { DIRS, findClip, sanitizeId, writeJSON } from '@/lib/store';
import { runPython } from '@/lib/spawn';

// Re-render a queued clip with new user-chosen start and end times.
//
// The cut itself is done by the Python backend (backend/rerender.py), which
// reuses the project's FFmpeg setup and atomically replaces the queued .mp4.
// Source resolution: prefer the original source video still sitting in
// downloads/ (kept when a job ran with --keep-source) and cut the requested
// absolute window from it; otherwise fall back to the clip already on disk
// and cut the equivalent window relative to that file. The latter keeps the
// manual editor working after downloads have been cleaned up, which is the
// normal case - sources are deleted as soon as a job finishes.
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 120;

const SOURCE_EXTS = ['.mp4', '.mkv', '.webm'];

function findOriginalSource(jobId, clipId) {
  for (const stem of [jobId, clipId]) {
    if (!stem) continue;
    for (const ext of SOURCE_EXTS) {
      const candidate = path.join(DIRS.downloads, `${stem}${ext}`);
      if (fs.existsSync(candidate)) return candidate;
    }
  }
  return null;
}

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch (err) {
    return Response.json({ ok: false, error: 'clip_id, new_start, and new_end are required' }, { status: 400 });
  }

  const { clip_id, new_start, new_end } = body || {};

  if (!clip_id || new_start == null || new_end == null) {
    return Response.json({ ok: false, error: 'clip_id, new_start, and new_end are required' }, { status: 400 });
  }

  const start = Number(new_start);
  const end = Number(new_end);
  if (!Number.isFinite(start) || !Number.isFinite(end)) {
    return Response.json({ ok: false, error: 'new_start and new_end must be numbers' }, { status: 400 });
  }
  if (end <= start) {
    return Response.json({ ok: false, error: 'new_end must be greater than new_start' }, { status: 400 });
  }

  const clip = findClip(sanitizeId(String(clip_id)));
  if (!clip) {
    return Response.json({ ok: false, error: 'clip not found' }, { status: 404 });
  }

  // The editor works inside the clip's current window: the modal previews the
  // clip file itself, so bounds outside [windowStart, windowEnd] could never
  // be previewed and would silently disagree with the rendered result.
  const clipMeta = clip.meta || {};
  const windowStart = Number(clipMeta.start ?? 0);
  const windowEndRaw = Number(clipMeta.end);
  const windowEnd =
    Number.isFinite(windowEndRaw) && windowEndRaw > windowStart
      ? windowEndRaw
      : windowStart + Number(clipMeta.duration || 0);
  if (start < windowStart - 0.05 || (windowEnd > windowStart && end > windowEnd + 0.05)) {
    return Response.json(
      {
        ok: false,
        error: `Keep start/end within the current clip (${windowStart}s - ${windowEnd}s)`,
      },
      { status: 400 }
    );
  }

  const original = findOriginalSource(clipMeta.job_id, clip.id);
  const source = original || clip.video;
  // Absolute source timestamps map onto the fallback file's own timeline.
  const cutStart = original ? start : start - windowStart;
  const cutEnd = original ? end : end - windowStart;
  const outPath = path.join(path.dirname(clip.video), `${clip.id}.mp4`);
  const thumbPath = path.join(path.dirname(clip.video), `${clip.id}.jpg`);

  const result = await runPython(
    'backend/rerender.py',
    [
      '--source', source,
      '--start', cutStart.toFixed(3),
      '--end', cutEnd.toFixed(3),
      '--out', outPath,
      '--thumb', thumbPath,
    ],
    { timeoutMs: 115000 }
  );

  if (result.timedOut) {
    return Response.json({ ok: false, error: 'Re-render timed out' }, { status: 500 });
  }
  if (result.code !== 0) {
    const tail = (result.stderr || '').trim().slice(-600);
    return Response.json(
      { ok: false, error: tail || `Re-render failed (exit ${result.code})` },
      { status: 500 }
    );
  }

  // Update the clip metadata with the new segment bounds. The thumbnail is
  // regenerated from the new cut by backend/rerender.py (--thumb), so the
  // queue preview always matches the edited clip.
  const duration = Number((end - start).toFixed(2));
  const meta = {
    id: clip.id,
    file: `${clip.id}.mp4`,
    thumb: `${clip.id}.jpg`,
    ...clipMeta,
    start: Number(start.toFixed(3)),
    end: Number(end.toFixed(3)),
    duration,
    manual_edited: true,
  };

  // Best effort: keep the clip's entry inside its job document in sync. The
  // job document may already be cleaned up, which must not fail the edit.
  if (clipMeta.job_id) {
    try {
      const jobPath = path.join(DIRS.jobs, `${sanitizeId(String(clipMeta.job_id))}.json`);
      const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
      const clipIndex = job.clips?.findIndex((entry) => entry.id === clip.id) ?? -1;
      if (clipIndex >= 0) {
        job.clips[clipIndex] = { ...job.clips[clipIndex], ...meta };
        writeJSON(jobPath, job);
      }
    } catch (err) {
      /* job document gone - the clip's own metadata below still updates */
    }
  }

  writeJSON(path.join(path.dirname(clip.video), `${clip.id}.json`), meta);

  return Response.json({
    ok: true,
    message: 'Clip re-rendered with new start/end times',
    clip_id: clip.id,
    start: meta.start,
    end: meta.end,
    duration: meta.duration,
  });
}

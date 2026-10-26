import fs from 'node:fs';
import path from 'node:path';
import { DIRS, findClip, sanitizeId, loadSettings } from '@/lib/store';

// Re-render a queued clip with new user-chosen start and end times.
// Reads the original source from downloads/, cuts it with FFmpeg, and
// overwrites the .mp4 in the queue folder.
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 120;

function ffmpegBin() {
  return process.env.FFMPEG_BIN || 'ffmpeg';
}

/**
 * Re-render one clip from the original source video using the new
 * start/end times. The old .mp4 in the queue folder is replaced.
 */
async function rerenderClip(clip) {
  const sourceDir = path.join(DIRS.root, 'downloads');
  const source = path.join(sourceDir, `${clip.id}.mp4`);
  const outPath = path.join(DIRS.queue, `${clip.id}.mp4`);
  const thumbPath = path.join(DIRS.queue, `${clip.id}.jpg`);

  if (!fs.existsSync(source)) {
    throw new Error(`Source video not found: ${source}`);
  }

  const args = [
    ffmpegBin(),
    '-y',
    '-ss', String(clip.new_start),
    '-t', String(clip.new_end - clip.new_start),
    '-i', source,
    '-c:v', 'libx264',
    '-preset', 'veryfast',
    '-crf', '21',
    '-pix_fmt', 'yuv420p',
    '-r', '30',
    '-g', '60',
    '-c:a', 'aac',
    '-b:a', '128k',
    '-ar', '44100',
    '-ac', '2',
    '-movflags', '+faststart',
    '-t', String(clip.new_end - clip.new_start),
    outPath,
  ];

  const { spawnSync } = await import('node:child_process');
  const result = spawnSync(args[0], args.slice(1), { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] });

  if (result.error) {
    throw new Error(`FFmpeg spawn failed: ${result.error.message}`);
  }
  if (result.status !== 0) {
    const stderr = (result.stderr || '').toString().trim();
    const stdout = (result.stdout || '').toString().trim();
    throw new Error(`FFmpeg failed (exit ${result.status}): ${stderr || stdout}`);
  }

  // Copy thumbnail if it exists and remove any stale one
  if (fs.existsSync(clip.thumb)) {
    fs.copyFileSync(clip.thumb, thumbPath);
  } else {
    fs.rmSync(thumbPath, { force: true });
  }

  // Update the clip metadata with the new segment bounds
  const meta = { ...clip, ...clip.meta };
  const job = JSON.parse(fs.readFileSync(path.join(DIRS.jobs, `${clip.id}.json`), 'utf8'));
  meta.start = clip.new_start;
  meta.end = clip.new_end;
  meta.duration = Number(clip.new_end - clip.new_start).toFixed(2);
  meta.manual_edited = true;

  // Rewrite the job doc and the queue metadata
  const jobPath = path.join(DIRS.jobs, `${job.id}.json`);
  if (fs.existsSync(jobPath)) {
    const jobData = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
    const clipIndex = jobData.clips?.findIndex((c) => c.id === clip.id);
    if (clipIndex >= 0) {
      jobData.clips[clipIndex] = meta;
      fs.writeFileSync(jobPath, JSON.stringify(jobData, null, 2), 'utf8');
    }
  }

  fs.writeFileSync(
    path.join(DIRS.queue, `${clip.id}.json`),
    JSON.stringify(meta, null, 2),
    'utf8'
  );
}

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch (err) {
    return Response.json({ ok: false, error: 'invalid JSON body' }, { status: 400 });
  }

  const { clip_id, new_start, new_end } = body || {};

  if (!clip_id || new_start == null || new_end == null) {
    return Response.json({ ok: false, error: 'clip_id, new_start, and new_end are required' }, { status: 400 });
  }

  if (new_end <= new_start) {
    return Response.json({ ok: false, error: 'new_end must be greater than new_start' }, { status: 400 });
  }

  const clip = findClip(clip_id);
  if (!clip) {
    return Response.json({ ok: false, error: 'clip not found' }, { status: 404 });
  }

  try {
    await rerenderClip({ ...clip, new_start, new_end });
    return Response.json({ ok: true, message: 'Clip re-rendered with new start/end times' });
  } catch (err) {
    return Response.json({ ok: false, error: err.message }, { status: 500 });
  }
}

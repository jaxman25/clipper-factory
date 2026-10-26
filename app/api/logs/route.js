import fs from 'node:fs';
import path from 'node:path';
import { DIRS, appendLog, readLogs } from '@/lib/store';
import { hasDashboardAccess, unauthorizedHeaders } from '@/lib/auth';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/** Writes are dashboard-only even though /api/logs is skipped by the middleware. */
function unauthorized() {
  return new Response('Authentication required', {
    status: 401,
    headers: unauthorizedHeaders(),
  });
}

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const limit = Math.max(10, Math.min(500, Number(searchParams.get('limit')) || 120));
  return Response.json(
    { logs: readLogs(limit) },
    { headers: { 'Cache-Control': 'no-store' } }
  );
}

/**
 * Remove the per-job .log files the Python side writes (STATE/<job_id>.log,
 * plus anything in state/jobs and state/logs). Returns how many went away.
 */
function clearJobLogs() {
  let removed = 0;
  for (const dir of [DIRS.state, DIRS.jobs, DIRS.logs]) {
    let names = [];
    try {
      names = fs.readdirSync(dir);
    } catch (err) {
      continue; // directory may not exist yet
    }
    for (const name of names) {
      if (!name.endsWith('.log')) continue;
      try {
        fs.unlinkSync(path.join(dir, name));
        removed += 1;
      } catch (err) {
        // A running job may still hold the file open (Windows cannot unlink
        // it). Skip instead of failing the whole request.
      }
    }
  }
  return removed;
}

/**
 * Debug helper: re-seed the activity panel after a clear so the dashboard has
 * something to show again. Entries are spread over the last few minutes so
 * they sort like a real log tail.
 */
const SAMPLE_LOGS = [
  ['info', 'Telegram bot polling started'],
  ['info', 'Internal scheduler started: 19:00, 21:00'],
  ['info', 'Downloading source video (7%)', { job: 'demo-job' }],
  ['warn', 'Whisper transcription queued behind a running job', { job: 'demo-job' }],
  ['error', 'yt-dlp failed to download this URL: video unavailable in your country', { job: 'demo-job' }],
  ['info', 'Rendered 10 shorts, next post scheduled for 19:00'],
];

export async function POST(request) {
  if (!hasDashboardAccess(request)) return unauthorized();
  try {
    const newest = Date.now();
    const added = SAMPLE_LOGS.map(([level, message, extra], index) =>
      appendLog(level, message, {
        ...(extra || {}),
        ts: new Date(newest - (SAMPLE_LOGS.length - 1 - index) * 90_000).toISOString(),
      })
    );
    return Response.json(
      { ok: true, added: added.length, message: 'Sample logs restored' },
      { headers: { 'Cache-Control': 'no-store' } }
    );
  } catch (err) {
    return Response.json(
      { ok: false, error: 'Failed to restore sample logs' },
      { status: 500, headers: { 'Cache-Control': 'no-store' } }
    );
  }
}

/** Truncate the worker log tail so the dashboard's activity panel starts blank. */
export async function DELETE(request) {
  if (!hasDashboardAccess(request)) return unauthorized();
  const file = path.join(DIRS.state, 'logs.jsonl');
  try {
    fs.mkdirSync(DIRS.state, { recursive: true });
    // Truncate rather than unlink: Python workers may hold the file open and
    // append with O_APPEND, which works against a truncated file but can fail
    // against a deleted inode.
    fs.writeFileSync(file, '');
    const jobLogs = clearJobLogs();
    return Response.json(
      { ok: true, message: 'Logs cleared', job_logs: jobLogs },
      { headers: { 'Cache-Control': 'no-store' } }
    );
  } catch (err) {
    return Response.json(
      { ok: false, error: 'Failed to clear logs' },
      { status: 500, headers: { 'Cache-Control': 'no-store' } }
    );
  }
}

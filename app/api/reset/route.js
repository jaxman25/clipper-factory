import fs from 'node:fs';
import path from 'node:path';
import { DIRS, ensureDirs } from '@/lib/store';

// Destructive. Requires explicit "yes" body so an accidental click can't
// nuke the queue on a mis-typed request.
const ALLOWED = new Set(['yes', 'y', 'confirm', 'confirm-clear', 'reset']);

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

function cleanDir(dir) {
  if (!fs.existsSync(dir)) return 0;
  let removed = 0;
  for (const entry of fs.readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (fs.statSync(full).isDirectory()) {
      removed += cleanDir(full);
      fs.rmSync(full, { recursive: true, force: true });
    } else {
      fs.unlinkSync(full);
      removed += 1;
    }
  }
  return removed;
}

function clearDirectory(name) {
  const dir = DIRS[name];
  if (!fs.existsSync(dir)) return 0;
  let removed = 0;
  for (const entry of fs.readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (fs.statSync(full).isDirectory()) {
      removed += cleanDir(full);
      fs.rmSync(full, { recursive: true, force: true });
    } else {
      fs.unlinkSync(full);
      removed += 1;
    }
  }
  return removed;
}

export const maxDuration = 60;

export async function POST(request) {
  const raw = await request.text();
  const body = raw.trim().toLowerCase();

  if (!ALLOWED.has(body)) {
    return Response.json(
      { ok: false, error: 'Reset requires explicit confirmation: pass {"confirm": true}' },
      { status: 400 }
    );
  }

  const counts = {};

  // 1. Queue + jobs database (JSON files)
  counts.queue = clearDirectory('queue');
  counts.jobs = clearDirectory('state/jobs');

  // 2. Delete all physical clip / thumbnail / export files
  counts.mp4 = clearDirectory('queue') + clearDirectory('posted') + clearDirectory('exports');
  counts.jpg = counts.mp4; // thumbnail files share the same directories as the video files

  // 3. Clear logs
  const logFile = path.join(DIRS.state, 'logs.jsonl');
  if (fs.existsSync(logFile)) {
    fs.unlinkSync(logFile);
  }
  const slotFile = path.join(DIRS.state, 'slots.json');
  if (fs.existsSync(slotFile)) {
    fs.writeFileSync(slotFile, '{}', 'utf8');
  }

  // Also drop any per-job lock so a stale lock from a crashed job never blocks a new run.
  const lockFile = path.join(DIRS.state, 'generate.lock');
  fs.rmSync(lockFile, { force: true });

  return Response.json({
    ok: true,
    message: 'System reset complete.',
    removed: counts,
  });
}

import fs from 'node:fs';
import path from 'node:path';
import { DIRS, ensureDirs } from '@/lib/store';

// Destructive. Requires explicit confirmation so an accidental click can't
// nuke the queue on a mis-typed request.

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export const maxDuration = 60;

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

export async function POST(request) {
  let raw;
  try {
    raw = await request.text();
  } catch (err) {
    console.error('[RESET] request.text() threw:', err.message);
    return Response.json({ ok: false, error: 'Failed to read request body' }, { status: 400 });
  }

  let parsed;
  try {
    parsed = JSON.parse(raw.trim());
  } catch (err) {
    console.error('[RESET] JSON.parse failed:', err.message);
    return Response.json(
      { ok: false, error: 'Invalid JSON body. Expected {"confirm": true}' },
      { status: 400 }
    );
  }

  // Only the literal boolean true confirms: "true", 1 or yes-ish strings all
  // fail, which is what the hint below tells the caller to send.
  if (parsed.confirm !== true) {
    return Response.json(
      {
        ok: false,
        error: 'Reset requires explicit confirmation.',
        hint: 'Pass {"confirm": true} in the JSON body.',
      },
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

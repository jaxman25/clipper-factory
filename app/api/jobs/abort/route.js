import fs from 'node:fs';
import path from 'node:path';
import {
  DIRS,
  markJobCancelledIfActive,
  readLock,
  removeLockIfOwned,
} from '@/lib/store';

// Abort a generation job.
//
// Ownership rules enforced here:
//  * the job document is marked 'cancelled' with a conditional transition
//    first, so a live worker can never overwrite the terminal state with a
//    misleading 'running' or 'done' state while it winds down;
//  * generate.lock is removed only when it belongs to the requested job, so
//    cancelling one job can never unlock a different, still-running job;
//  * only a PID recorded under this job is signalled - a PID found via a lock
//    owned by another job is never touched;
//  * the job document is kept (job history): it now reads status 'cancelled'
//    instead of being deleted;
//  * repeated requests are idempotent - an already-cancelled or unknown job
//    still reports ok.
//
// The Python worker catches SIGTERM where the OS delivers it, and the job
// document's terminal state stops any worker that survives the signal.
//
// Expected body: { "job_id": "the-id-of-the-running-job" }
export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch (err) {
    return Response.json({ ok: false, error: 'Invalid JSON body' }, { status: 400 });
  }

  const { job_id } = body || {};
  if (!job_id || typeof job_id !== 'string' || job_id.trim() === '') {
    return Response.json(
      { ok: false, error: 'Missing job_id in body' },
      { status: 400 }
    );
  }

  const job_id_trimmed = job_id.trim();
  const jobFile = path.join(DIRS.jobs, `${job_id_trimmed}.json`);

  const lock = readLock(); // {job_id, pid, created_at} | {job_id} | null
  const lockOwned = Boolean(lock && String(lock.job_id || '') === job_id_trimmed);

  let job = null;
  try {
    job = JSON.parse(fs.readFileSync(jobFile, 'utf8'));
  } catch (err) {
    /* no job document for this id */
  }

  if (!job && !lock) {
    return Response.json({
      ok: true,
      cancelled: false,
      reason: 'no active generation is running',
    });
  }

  // 1. Conditional running/queued -> cancelled (null when nothing active, so
  //    repeating this request never flips a terminal state back).
  const transitioned = markJobCancelledIfActive(job_id_trimmed, 'Cancelled by user');
  const nowCancelled = Boolean(transitioned) || job?.status === 'cancelled';

  // 2. Signal this job's own worker only.
  const pid = job && job.pid ? job.pid : lockOwned ? lock.pid : null;
  let signalOk = false;
  if (pid) {
    try {
      process.kill(pid, 'SIGTERM');
      signalOk = true;
    } catch (err) {
      signalOk = false;
    }
  }

  // 3. Drop the lock only when it belongs to this job.
  const lockRemoved = lockOwned ? removeLockIfOwned(job_id_trimmed) : false;

  let reason;
  if (lock && !lockOwned) {
    reason = `Requested job is not the lock holder; generate.lock owned by ${
      lock.job_id || 'another job'
    } was left untouched`;
  } else if (signalOk) {
    reason = lockRemoved || !lock
      ? 'Worker signalled; lock cleared'
      : 'Worker signalled';
  } else if (nowCancelled) {
    reason = lockRemoved
      ? 'Job cancelled; lock cleared (no worker PID to signal)'
      : 'Job already cancelled';
  } else {
    reason = 'no active generation is running';
  }

  return Response.json({
    ok: true,
    cancelled: nowCancelled,
    job_id: job_id_trimmed,
    reason,
  });
}

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 30;

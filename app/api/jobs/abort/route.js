import fs from 'node:fs';
import path from 'node:path';
import { DIRS } from '@/lib/store';

// Abort the currently running generation job. We signal the raw worker
// process by its PID (read from the persistent job document), which is the
// most reliable way to reach the detached spawn child across module boundaries.
// The Python worker itself catches SIGTERM and exits cleanly, clearing the
// generate.lock so the queue is immediately reusable.
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
  const lockFile = path.join(DIRS.state, 'generate.lock');

  // Read the job document to find the PID of the running worker.
  let jobFile = path.join(DIRS.jobs, `${job_id_trimmed}.json`);
  let job = null;
  let pid = null;
  try {
    const raw = fs.readFileSync(jobFile, 'utf8');
    job = JSON.parse(raw);
    pid = job?.pid;
  } catch (err) {
    /* not a real job file */
  }

  // No lock on disk means no worker is currently running.
  if (!fs.existsSync(lockFile)) {
    if (job?.status === 'running') {
      return Response.json({
        ok: true,
        cancelled: false,
        reason: 'job is running but no worker lock exists; it has already exited',
      });
    }
    return Response.json({
      ok: true,
      cancelled: false,
      reason: 'no active generation is running',
    });
  }

  // Resolve the correct job: if the caller passes a job_id, prefer that;
  // otherwise use the one whose PID is on disk.
  let targetJobId = job_id_trimmed;
  if (pid) {
    targetJobId = job?.id || targetJobId;
  }

  // Signal the worker process directly.
  let signalOk = false;
  if (pid) {
    try {
      process.kill(pid, 'SIGTERM');
      signalOk = true;
    } catch (err) {
      signalOk = false;
    }
  }

  // Regardless of whether the worker process responds, clear the lock so the
  // queue stays usable immediately.
  fs.rmSync(lockFile, { force: true });

  // Remove the stale job doc so the dashboard stops polling a running job.
  fs.rmSync(jobFile, { force: true });

  return Response.json({
    ok: true,
    cancelled: true,
    job_id: targetJobId,
    reason: signalOk
      ? 'Worker signalled; lock cleared'
      : 'No running worker PID found to signal',
  });
}

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 30;

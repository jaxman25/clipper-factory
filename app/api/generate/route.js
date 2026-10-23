import fs from 'node:fs';
import path from 'node:path';
import { DIRS, ensureDirs, listJobs, readJob, sanitizeId, writeJSON } from '@/lib/store';
import { startPython } from '@/lib/spawn';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 60;

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const jobId = sanitizeId(searchParams.get('job_id'));
  if (jobId) {
    const job = readJob(jobId);
    if (!job) return Response.json({ error: 'job not found' }, { status: 404 });
    return Response.json(job, { headers: { 'Cache-Control': 'no-store' } });
  }
  return Response.json(
    { jobs: listJobs(8) },
    { headers: { 'Cache-Control': 'no-store' } }
  );
}

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch (err) {
    return Response.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  const url = String(body.url || '').trim();
  let parsed;
  try {
    parsed = new URL(url);
  } catch (err) {
    return Response.json({ error: 'Paste a valid YouTube URL' }, { status: 400 });
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    return Response.json({ error: 'Only http(s) URLs are supported' }, { status: 400 });
  }

  const numShorts = Math.max(1, Math.min(20, Number(body.num_shorts) || 10));
  ensureDirs();

  // Refuse to stampede the free CPU with a second whisper/ffmpeg job.
  const active = listJobs(20).find(
    (job) =>
      job.status === 'running' &&
      Date.now() - new Date(job.updated_at || job.created_at || 0).getTime() < 2 * 3600 * 1000
  );
  if (active) {
    return Response.json(
      { error: `Job ${active.id} is still running (${active.progress || 0}%)`, job_id: active.id },
      { status: 409 }
    );
  }
  if (fs.existsSync(path.join(DIRS.state, 'generate.lock'))) {
    try {
      const ageMs = Date.now() - fs.statSync(path.join(DIRS.state, 'generate.lock')).mtimeMs;
      if (ageMs < 4 * 3600 * 1000) {
        return Response.json(
          { error: 'Another generation job holds the lock. Try again or delete /tmp/state/generate.lock.' },
          { status: 409 }
        );
      }
      fs.unlinkSync(path.join(DIRS.state, 'generate.lock'));
    } catch (err) {
      /* race with the worker removing the lock is fine */
    }
  }

  const jobId = sanitizeId(`job-${Date.now().toString(36)}`);
  const worker = startPython(
    'backend/main.py',
    ['--url', url, '--job-id', jobId, '--num-shorts', String(numShorts)],
    jobId
  );

  // Persist the worker PID in the job doc so the abort endpoint can
  // signal the running worker by PID across module boundaries.
  writeJSON(path.join(DIRS.jobs, `${jobId}.json`), {
    id: jobId,
    status: 'running',
    pid: worker.pid,
    stage: 'queued',
    progress: 0,
    message: 'Queued for the clip worker',
    source_url: url,
    num_shorts: numShorts,
    clips: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });

  // A worker that dies before writing status (bad interpreter, OOM) must not
  // leave the dashboard polling a phantom "running" job forever.
  worker.child?.on('exit', (code) => {
    if (code === 0) return;
    try {
      const job = readJob(jobId);
      if (!job || job.status !== 'running') return;
      let tail = '';
      try {
        tail = fs.readFileSync(worker.log, 'utf8').slice(-800).trim();
      } catch (err) {
        /* log may not exist */
      }
      writeJSON(path.join(DIRS.jobs, `${jobId}.json`), {
        ...job,
        status: 'error',
        stage: 'error',
        message: tail || `Clip worker exited with code ${code}`,
        error: tail || `exit code ${code}`,
        updated_at: new Date().toISOString(),
      });
    } catch (err) {
      /* never throw from an exit handler */
    }
  });

  return Response.json({
    ok: true,
    job_id: jobId,
    pid: worker.pid,
    log: worker.log,
  }, { status: 202 });
}

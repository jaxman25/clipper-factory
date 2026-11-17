import fs from 'node:fs';
import path from 'node:path';
import { getServerSession } from 'next-auth';
import { deductCredit, ensureUser, getCredits, isAdminEmail, normalizeEmail } from '@/lib/credits';
import { isLocalRequest } from '@/lib/auth';
import { authOptions } from '@/lib/next-auth';
import { DIRS, ensureDirs, listJobs, markJobErrorIfRunning, readJob, reconcileStaleJobs, sanitizeId, updateJSON, writeJSONIfAbsent } from '@/lib/store';
import { buildWorkerArgs } from '@/lib/generate-args';
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

  // ---- Credit gate (spec 04) ------------------------------------------
  // Localhost bypasses everything (owner testing). Admins (ADMIN_EMAIL)
  // generate unlimited, forever. Public users need a session and pay 1
  // credit per accepted job; 0 credits = 403 with a nudge to buy more.
  // The gate runs before any work so an empty balance never touches the
  // lock, the queue or the worker.
  // Only a genuine local-development request skips sign-in and credits.
  // isLocalRequest() ignores x-forwarded-host and is always false in
  // production, so a forged header can no longer claim to be the owner.
  let payerEmail = null;
  if (!isLocalRequest(request)) {
    const session = await getServerSession(authOptions);
    const email = normalizeEmail(session?.user?.email);
    if (!email) {
      return Response.json({ error: 'Sign in to generate videos' }, { status: 401 });
    }
    if (!isAdminEmail(email)) {
      ensureUser(email);
      if (getCredits(email) <= 0) {
        return Response.json(
          { error: 'You are out of credits - buy more to generate another video.' },
          { status: 403 }
        );
      }
      payerEmail = email;
    }
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

  const mode = String(body.mode || 'viral');
  const numShorts = Math.max(1, Math.min(20, Number(body.num_shorts) || 10));
  if (mode !== 'viral' && mode !== 'equal' && mode !== 'transform') {
    return Response.json(
      { error: 'mode must be "viral", "equal" or "transform"' },
      { status: 400 }
    );
  }
  const language = String(body.language || '').trim();
  if (language && !/^(auto|[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?)$/.test(language)) {
    return Response.json(
      { error: 'language must be "auto" or an ISO language code such as "en"' },
      { status: 400 }
    );
  }
  const youtubeAutoPost =
    body.youtube_auto_post === true ? true : body.youtube_auto_post === false ? false : null;
  // Transform mode fields (anti-flag pipeline)
  const sourceUrl = url;
  const originalChannel = String(body.original_channel || '').trim();
  const transformSpeed = Number(body.transform_speed);
  const userConfig =
    body.user_config && typeof body.user_config === 'object'
      ? body.user_config
      : null;
  // The clip-length override is opt-in. The old unconditional default of 25 s
  // silently overrode config.json's 45 s, which made clip_min (30) > clip_max
  // (25) and zeroed viral candidate generation. An explicit per-job value wins
  // over a saved preference; with neither, the worker uses config.json.
  const requestedMax = body.clip_max_seconds ?? userConfig?.clip_max_seconds;
  const maxClipSeconds =
    requestedMax != null && Number.isFinite(Number(requestedMax))
      ? Math.max(1, Math.min(120, Number(requestedMax)))
      : null;
  const overrides = {
    timezone: userConfig?.timezone,
    posting_times: userConfig?.posting_times,
    shorts_per_video: userConfig?.shorts_per_video,
    clip_min_seconds: userConfig?.clip_min_seconds,
    clip_max_seconds: userConfig?.clip_max_seconds,
    playback_speed: userConfig?.playback_speed,
    drum_volume_db: userConfig?.drum_volume_db,
    caption_words_per_card: userConfig?.caption_words_per_card,
    outro_text: userConfig?.outro_text,
    hashtags: userConfig?.hashtags,
    caption_color: userConfig?.caption_color,
    hook_seconds: userConfig?.hook_seconds,
    outro_seconds: userConfig?.outro_seconds,
    instagram: userConfig?.instagram,
    tiktok: userConfig?.tiktok,
    youtube_auto_post: userConfig?.youtube_auto_post,
  };
  ensureDirs();

  // A job left 'running' by a worker that died with the previous app process
  // must not block this request forever.
  reconcileStaleJobs();

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
  const jobFile = path.join(DIRS.jobs, `${jobId}.json`);

  // Initialise the job document BEFORE spawning the worker. Writing it after
  // the spawn raced with the worker's first write: the API's initial 0%
  // "queued" record could land on top of progress the worker had already
  // recorded, and writeJSONIfAbsent keeps the existing document authoritative.
  writeJSONIfAbsent(jobFile, {
    id: jobId,
    status: 'running',
    pid: null,
    stage: 'queued',
    progress: 0,
    message: 'Queued for the clip worker',
    source_url: url,
    num_shorts: numShorts,
    requested_count: numShorts,
    selected_count: 0,
    rendered_count: 0,
    mode: mode,
    language: language || 'auto',
    clips: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });

  let worker;
  try {
    worker = startPython(
      'backend/main.py',
      buildWorkerArgs({
        url,
        jobId,
        numShorts,
        mode,
        language,
        maxClipSeconds,
        originalChannel,
        youtubeAutoPost,
        transformSpeed,
        overrides: { ...overrides, user_config: userConfig },
      }),
      jobId
    );
  } catch (err) {
    // A spawn failure must produce a useful error state, not a phantom job
    // the dashboard would poll forever.
    markJobErrorIfRunning(jobId, {
      message: `Clip worker failed to start: ${err.message}`,
      error: String(err.message || err),
    });
    return Response.json({ error: `Clip worker failed to start: ${err.message}` }, { status: 500 });
  }

  // Persist the worker PID in the job doc so the abort endpoint can signal
  // the running worker by PID across module boundaries. This is a
  // read-modify-write merge (never a full overwrite) and it is skipped when
  // the worker already recorded its own pid or a cancellation landed first.
  try {
    const doc = readJob(jobId);
    if (doc && doc.status === 'running' && !doc.pid) {
      updateJSON(jobFile, { pid: worker.pid });
    }
  } catch (err) {
    /* pid is best effort - the worker writes its own pid too */
  }

  // A worker that dies before writing status (bad interpreter, OOM) must not
  // leave the dashboard polling a phantom "running" job forever.
  const reportWorkerFailure = (message, error) => {
    try {
      let tail = '';
      try {
        tail = fs.readFileSync(worker.log, 'utf8').slice(-800).trim();
      } catch (err) {
        /* log may not exist */
      }
      // Conditional transition: markJobErrorIfRunning only rewrites a document
      // that is still 'running', so it can never overwrite a done/cancelled
      // end state with stale error data.
      markJobErrorIfRunning(jobId, { message: tail || message, error: tail || error });
    } catch (err) {
      /* never throw from a process event handler */
    }
  };

  worker.child?.on('exit', (code) => {
    if (code === 0) return;
    reportWorkerFailure(`Clip worker exited with code ${code}`, `exit code ${code}`);
  });
  // Spawn failures (missing interpreter, EPERM, ...) emit 'error' instead of
  // 'exit'; without this the initial record would stay "running" forever.
  worker.child?.on('error', (err) => {
    reportWorkerFailure(
      `Clip worker failed to start: ${err.message}`,
      `spawn error: ${err.message}`
    );
  });

  // Charge only once the worker is actually accepted: a failed spawn never
  // consumes a credit (the error returns above happen before this point).
  let creditsLeft = null;
  if (payerEmail) {
    const result = deductCredit(payerEmail);
    creditsLeft = result.credits;
  }

  return Response.json({
    ok: true,
    job_id: jobId,
    pid: worker.pid,
    log: worker.log,
    mode: mode,
    ...(payerEmail ? { credits: creditsLeft } : {}),
  }, { status: 202 });
}

#!/usr/bin/env node
/**
 * Instagram Reels publisher (Meta Graph API).
 *
 *   node auto-post/instagram.js --file /tmp/queue/clip.mp4 --id clip-1 --caption "text"
 *
 * The Graph API ingests a video from a public HTTPS URL, so the clip is served
 * by Next.js at `${PUBLIC_BASE_URL}/api/media/<id>` (PUBLIC_BASE_URL defaults to
 * Render's RENDER_EXTERNAL_URL). Without IG_USER_ID / IG_ACCESS_TOKEN the script
 * skips cleanly and logs why.
 */
'use strict';

const fs = require('fs');
const path = require('path');

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      out[key] = next;
      i += 1;
    } else {
      out[key] = true;
    }
  }
  return out;
}

function dataRoot() {
  return process.env.ACF_DATA_ROOT || '/tmp';
}

function log(level, message, extra = {}) {
  const entry = {
    ts: new Date().toISOString(),
    level,
    message: `[instagram] ${message}`,
    ...extra,
  };
  process.stderr.write(`${entry.ts} ${level.toUpperCase()} ${entry.message}\n`);
  try {
    const dir = path.join(dataRoot(), 'state');
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, 'logs.jsonl'), `${JSON.stringify(entry)}\n`);
  } catch (err) {
    /* logging must never break posting */
  }
}

function emit(result) {
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function graph(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(120000),
  });
  const text = await response.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch (err) {
    body = { raw: text.slice(0, 500) };
  }
  if (!response.ok || (body && body.error)) {
    const detail = body && body.error
      ? `${body.error.message} (code ${body.error.code})`
      : text.slice(0, 300);
    throw new Error(`Graph API ${response.status}: ${detail}`);
  }
  return body;
}

async function main() {
  const args = parseArgs(process.argv);
  const file = args.file;
  const caption = String(args.caption || '');
  const userId = (process.env.IG_USER_ID || '').trim();
  const token = (process.env.IG_ACCESS_TOKEN || '').trim();
  const version = (process.env.IG_GRAPH_VERSION || 'v21.0').trim();
  const base = (process.env.PUBLIC_BASE_URL || process.env.RENDER_EXTERNAL_URL || '').replace(/\/+$/, '');

  let id = String(args.id || '').trim();
  if (!id && file) id = path.basename(file, path.extname(file));

  if (!file || !fs.existsSync(file)) {
    return { ok: false, platform: 'instagram', error: `video not found: ${file || '(none)'}` };
  }
  if (!userId || !token) {
    log('warn', 'IG_USER_ID / IG_ACCESS_TOKEN not set - skipping Instagram');
    return {
      ok: false,
      skipped: true,
      platform: 'instagram',
      reason: 'missing IG_USER_ID or IG_ACCESS_TOKEN',
    };
  }
  if (!base) {
    log('warn', 'PUBLIC_BASE_URL / RENDER_EXTERNAL_URL not set - cannot expose a public video URL');
    return {
      ok: false,
      skipped: true,
      platform: 'instagram',
      reason: 'no public base URL (set PUBLIC_BASE_URL or deploy on Render)',
    };
  }

  const videoUrl = `${base}/api/media/${encodeURIComponent(id)}`;
  log('info', `creating Reels container from ${videoUrl}`);

  const createUrl = new URL(`https://graph.facebook.com/${version}/${userId}/media`);
  createUrl.searchParams.set('media_type', 'REELS');
  createUrl.searchParams.set('video_url', videoUrl);
  createUrl.searchParams.set('caption', caption.slice(0, 2200));
  createUrl.searchParams.set('share_to_feed', 'true');
  createUrl.searchParams.set('access_token', token);

  const created = await graph(createUrl.toString(), { method: 'POST' });
  const creationId = created.id;
  if (!creationId) throw new Error('Graph API did not return a container id');

  const statusUrl = new URL(`https://graph.facebook.com/${version}/${creationId}`);
  statusUrl.searchParams.set('fields', 'status_code,status');
  statusUrl.searchParams.set('access_token', token);

  let state = 'IN_PROGRESS';
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await sleep(5000);
    const status = await graph(statusUrl.toString());
    state = status.status_code || 'IN_PROGRESS';
    log('info', `container ${creationId} status=${state}`);
    if (state === 'FINISHED') break;
    if (state === 'ERROR' || state === 'EXPIRED') {
      throw new Error(`Instagram rejected the upload: ${status.status || state}`);
    }
  }
  if (state !== 'FINISHED') {
    throw new Error('Instagram container did not finish processing in 5 minutes');
  }

  const publishUrl = new URL(`https://graph.facebook.com/${version}/${userId}/media_publish`);
  publishUrl.searchParams.set('creation_id', creationId);
  publishUrl.searchParams.set('access_token', token);
  const published = await graph(publishUrl.toString(), { method: 'POST' });

  log('info', `published media ${published.id}`);
  return {
    ok: true,
    platform: 'instagram',
    media_id: published.id,
    container_id: creationId,
    url: `${base}/api/media/${encodeURIComponent(id)}`,
  };
}

main()
  .then((result) => {
    emit(result);
    process.exit(result.ok || result.skipped ? 0 : 1);
  })
  .catch((error) => {
    log('error', error.message);
    emit({ ok: false, platform: 'instagram', error: error.message });
    process.exit(1);
  });

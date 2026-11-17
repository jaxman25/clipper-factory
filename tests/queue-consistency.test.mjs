import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, before, describe, it } from 'node:test';

// ACF_DATA_ROOT must be set before lib/store.js is imported.
let tmpRoot;
let store;

before(() => {
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'acf-queue-'));
  process.env.ACF_DATA_ROOT = tmpRoot;
});

after(() => {
  fs.rmSync(tmpRoot, { recursive: true, force: true });
});

async function loadStore() {
  if (!store) store = await import('../lib/store.js');
  return store;
}

function queueFile(id) {
  return path.join(tmpRoot, 'queue', `${id}.json`);
}
function queueVideo(id) {
  return path.join(tmpRoot, 'queue', `${id}.mp4`);
}
function jobFile(id) {
  return path.join(tmpRoot, 'state', 'jobs', `${id}.json`);
}

describe('usable video check', () => {
  it('rejects missing and zero-byte files, accepts real bytes', async () => {
    const { isUsableVideo } = await loadStore();
    const dir = path.join(tmpRoot, 'probe');
    fs.mkdirSync(dir, { recursive: true });
    const empty = path.join(dir, 'empty.mp4');
    const real = path.join(dir, 'real.mp4');
    fs.writeFileSync(empty, '');
    fs.writeFileSync(real, 'not-really-mp4-but-not-empty');

    assert.equal(isUsableVideo(path.join(dir, 'missing.mp4')), false);
    assert.equal(isUsableVideo(empty), false);
    assert.equal(isUsableVideo(real), true);
  });
});

describe('queue consistency', () => {
  it('listQueue skips a zero-byte clip and keeps the valid one', async () => {
    const { listQueue, writeJSON } = await loadStore();
    fs.mkdirSync(path.dirname(queueFile('q-empty')), { recursive: true });

    writeJSON(queueFile('q-empty'), { id: 'q-empty', title: 'broken' });
    fs.writeFileSync(queueVideo('q-empty'), '');
    writeJSON(queueFile('q-ok'), { id: 'q-ok', title: 'ready' });
    fs.writeFileSync(queueVideo('q-ok'), 'video-bytes');

    const ids = listQueue().map((clip) => clip.id);
    assert.ok(ids.includes('q-ok'));
    assert.ok(!ids.includes('q-empty'), 'zero-byte clip must not be listed');

    fs.rmSync(queueFile('q-empty'), { force: true });
    fs.rmSync(queueVideo('q-empty'), { force: true });
    fs.rmSync(queueFile('q-ok'), { force: true });
    fs.rmSync(queueVideo('q-ok'), { force: true });
  });

  it('findClip refuses a zero-byte file but serves a valid one', async () => {
    const { findClip, writeJSON } = await loadStore();
    fs.mkdirSync(path.dirname(queueFile('c-empty')), { recursive: true });

    writeJSON(queueFile('c-empty'), { id: 'c-empty' });
    fs.writeFileSync(queueVideo('c-empty'), '');
    assert.equal(findClip('c-empty'), null);

    writeJSON(queueFile('c-ok'), { id: 'c-ok' });
    fs.writeFileSync(queueVideo('c-ok'), 'video-bytes');
    const found = findClip('c-ok');
    assert.equal(found.state, 'queue');
    assert.equal(found.video, queueVideo('c-ok'));

    for (const id of ['c-empty', 'c-ok']) {
      fs.rmSync(queueFile(id), { force: true });
      fs.rmSync(queueVideo(id), { force: true });
    }
  });

  it('downloadClips excludes broken videos but keeps their history', async () => {
    const { downloadClips, listPosted, writeJSON } = await loadStore();
    const postedDir = path.join(tmpRoot, 'posted');
    fs.mkdirSync(postedDir, { recursive: true });
    fs.mkdirSync(path.dirname(queueFile('d-queued')), { recursive: true });

    writeJSON(queueFile('d-queued'), { id: 'd-queued' });
    fs.writeFileSync(queueVideo('d-queued'), 'video-bytes');

    writeJSON(path.join(postedDir, 'd-broken.json'), { id: 'd-broken', posted_at: '2026-01-01' });
    fs.writeFileSync(path.join(postedDir, 'd-broken.mp4'), '');

    writeJSON(path.join(postedDir, 'd-good.json'), { id: 'd-good', posted_at: '2026-01-02' });
    fs.writeFileSync(path.join(postedDir, 'd-good.mp4'), 'video-bytes');

    const ids = downloadClips().map((clip) => clip.id);
    assert.deepEqual(ids.sort(), ['d-good', 'd-queued']);
    // Posted history itself is untouched: only the download is filtered.
    assert.ok(listPosted().some((clip) => clip.id === 'd-broken'));

    fs.rmSync(path.join(postedDir, 'd-broken.json'), { force: true });
    fs.rmSync(path.join(postedDir, 'd-broken.mp4'), { force: true });
    fs.rmSync(path.join(postedDir, 'd-good.json'), { force: true });
    fs.rmSync(path.join(postedDir, 'd-good.mp4'), { force: true });
    fs.rmSync(queueFile('d-queued'), { force: true });
    fs.rmSync(queueVideo('d-queued'), { force: true });
  });
});

describe('stale job recovery', () => {
  function writeJob(writeJSON, id, patch) {
    writeJSON(jobFile(id), {
      id,
      status: 'running',
      stage: 'render',
      progress: 60,
      updated_at: '2026-01-01T00:00:00.000Z',
      ...patch,
    });
  }

  function readJob(id) {
    return JSON.parse(fs.readFileSync(jobFile(id), 'utf8'));
  }

  it('marks a running job with a dead worker PID as error', async () => {
    const { reconcileStaleJobs, writeJSON } = await loadStore();
    writeJob(writeJSON, 'job-dead', { pid: 2147483646 });

    const reconciled = reconcileStaleJobs();
    assert.ok(reconciled.includes('job-dead'));

    const job = readJob('job-dead');
    assert.equal(job.status, 'error');
    assert.equal(job.stage, 'error');
    assert.match(job.message, /no longer running/);
    assert.equal(job.progress, 60, 'progress history must survive');
    fs.rmSync(jobFile('job-dead'), { force: true });
  });

  it('leaves a live worker, a starting job and terminal states alone', async () => {
    const { reconcileStaleJobs, writeJSON } = await loadStore();
    writeJob(writeJSON, 'job-live', { pid: process.pid });
    writeJob(writeJSON, 'job-starting', { pid: null, stage: 'queued', progress: 0 });
    writeJob(writeJSON, 'job-done', { status: 'done', progress: 100, pid: 2147483646 });

    const reconciled = reconcileStaleJobs();
    assert.equal(reconciled.length, 0);
    assert.equal(readJob('job-live').status, 'running');
    assert.equal(readJob('job-starting').status, 'running');
    assert.equal(readJob('job-done').status, 'done');

    for (const id of ['job-live', 'job-starting', 'job-done']) {
      fs.rmSync(jobFile(id), { force: true });
    }
  });
});

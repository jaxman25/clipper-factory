import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, before, describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';

// ACF_DATA_ROOT must be set before lib/store.js is imported, so the store is
// loaded dynamically inside the hooks below.
let tmpRoot;
let store;

before(() => {
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'acf-joblock-'));
  process.env.ACF_DATA_ROOT = tmpRoot;
});

after(() => {
  fs.rmSync(tmpRoot, { recursive: true, force: true });
});

async function loadStore() {
  if (!store) store = await import('../lib/store.js');
  return store;
}

describe('lock ownership', () => {
  it('readLock parses JSON locks, legacy plain locks and missing files', async () => {
    const { LOCK_FILE, readLock } = await loadStore();
    fs.mkdirSync(path.dirname(LOCK_FILE), { recursive: true });

    fs.writeFileSync(
      LOCK_FILE,
      JSON.stringify({ job_id: 'job-a', pid: 4321, created_at: 'now' }),
      'utf8'
    );
    assert.deepEqual(readLock(), { job_id: 'job-a', pid: 4321, created_at: 'now' });

    // Locks written by older builds are a bare job id.
    fs.writeFileSync(LOCK_FILE, 'job-a', 'utf8');
    assert.deepEqual(readLock(), { job_id: 'job-a' });

    fs.writeFileSync(LOCK_FILE, '', 'utf8');
    assert.equal(readLock(), null);

    fs.rmSync(LOCK_FILE, { force: true });
    assert.equal(readLock(), null);
  });

  it('removeLockIfOwned refuses a lock owned by another job', async () => {
    const { LOCK_FILE, removeLockIfOwned } = await loadStore();
    fs.mkdirSync(path.dirname(LOCK_FILE), { recursive: true });
    fs.writeFileSync(
      LOCK_FILE,
      JSON.stringify({ job_id: 'job-a', pid: 4321 }),
      'utf8'
    );

    assert.equal(removeLockIfOwned('job-b'), false);
    assert.equal(fs.existsSync(LOCK_FILE), true, 'foreign lock must survive');

    assert.equal(removeLockIfOwned('job-a'), true);
    assert.equal(fs.existsSync(LOCK_FILE), false);

    // Idempotent: removing again is a harmless no-op.
    assert.equal(removeLockIfOwned('job-a'), false);
    fs.rmSync(LOCK_FILE, { force: true });
  });
});

describe('job state transitions', () => {
  const jobFile = (id) => path.join(tmpRoot, 'state', 'jobs', `${id}.json`);

  it('markJobCancelledIfActive cancels a running job and is idempotent', async () => {
    const { markJobCancelledIfActive, writeJSON } = await loadStore();
    writeJSON(jobFile('job-run'), {
      id: 'job-run',
      status: 'running',
      stage: 'download',
      progress: 42,
    });

    const updated = markJobCancelledIfActive('job-run');
    assert.equal(updated.status, 'cancelled');
    assert.equal(updated.message, 'Cancelled by user');
    assert.equal(updated.progress, 42, 'cancellation must not reset progress');

    // Repeating the request never flips a terminal state back.
    assert.equal(markJobCancelledIfActive('job-run'), null);
    const data = JSON.parse(fs.readFileSync(jobFile('job-run'), 'utf8'));
    assert.equal(data.status, 'cancelled');
    fs.rmSync(jobFile('job-run'), { force: true });
  });

  it('cancelling one job never removes another job\'s lock', async () => {
    const { LOCK_FILE, markJobCancelledIfActive, removeLockIfOwned, writeJSON } =
      await loadStore();
    fs.mkdirSync(path.dirname(LOCK_FILE), { recursive: true });
    // job-b is generating; a stale cancel for job-a arrives.
    fs.writeFileSync(
      LOCK_FILE,
      JSON.stringify({ job_id: 'job-b', pid: 5555 }),
      'utf8'
    );
    writeJSON(jobFile('job-a'), { id: 'job-a', status: 'running', progress: 5 });

    assert.ok(markJobCancelledIfActive('job-a'));
    assert.equal(removeLockIfOwned('job-a'), false, 'must not steal job-b lock');
    assert.equal(fs.existsSync(LOCK_FILE), true);
    assert.equal(
      JSON.parse(fs.readFileSync(LOCK_FILE, 'utf8')).job_id,
      'job-b'
    );

    fs.rmSync(LOCK_FILE, { force: true });
    fs.rmSync(jobFile('job-a'), { force: true });
  });

  it('markJobErrorIfRunning never overwrites cancelled or done states', async () => {
    const { markJobErrorIfRunning, writeJSON } = await loadStore();

    // Stale worker-exit after a cancellation: the terminal state survives.
    writeJSON(jobFile('job-cancelled'), {
      id: 'job-cancelled',
      status: 'cancelled',
      progress: 42,
    });
    assert.equal(
      markJobErrorIfRunning('job-cancelled', { message: 'tail', error: 'exit 1' }),
      null
    );
    assert.equal(
      JSON.parse(fs.readFileSync(jobFile('job-cancelled'), 'utf8')).status,
      'cancelled'
    );

    // A finished job keeps its end state.
    writeJSON(jobFile('job-done'), { id: 'job-done', status: 'done', progress: 100 });
    assert.equal(
      markJobErrorIfRunning('job-done', { message: 'tail', error: 'exit 1' }),
      null
    );
    assert.equal(
      JSON.parse(fs.readFileSync(jobFile('job-done'), 'utf8')).status,
      'done'
    );

    // A genuinely dead worker is reported.
    writeJSON(jobFile('job-dead'), { id: 'job-dead', status: 'running', progress: 3 });
    const failed = markJobErrorIfRunning('job-dead', {
      message: 'python: not found',
      error: 'spawn error',
    });
    assert.equal(failed.status, 'error');
    assert.equal(failed.stage, 'error');
    assert.equal(failed.message, 'python: not found');

    fs.rmSync(jobFile('job-cancelled'), { force: true });
    fs.rmSync(jobFile('job-done'), { force: true });
    fs.rmSync(jobFile('job-dead'), { force: true });
  });

  it('worker startup failure without a document creates no phantom job', async () => {
    const { markJobErrorIfRunning } = await loadStore();
    assert.equal(
      markJobErrorIfRunning('job-ghost', { message: 'spawn failed', error: 'EPERM' }),
      null
    );
    assert.equal(fs.existsSync(jobFile('job-ghost')), false);
  });
});
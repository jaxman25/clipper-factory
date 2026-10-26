/**
 * Integration tests for /api/logs against a running server.
 *
 *   npm run dev          # in one terminal
 *   npm test             # in another
 *
 * With DASHBOARD_USER/DASHBOARD_PASSWORD set in this process the suite also
 * checks that writes need credentials while the read stays open.
 *
 * The data root is taken from the *server* (/api/settings → runtime.data_root)
 * rather than from this process, so the seeded job log always lands in the same
 * directory the route cleans up.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, describe, it } from 'node:test';

const BASE = process.env.TEST_BASE_URL || 'http://localhost:3000';

const authHeader =
  process.env.DASHBOARD_USER && process.env.DASHBOARD_PASSWORD
    ? `Basic ${Buffer.from(`${process.env.DASHBOARD_USER}:${process.env.DASHBOARD_PASSWORD}`).toString('base64')}`
    : null;

const headers = (extra = {}) => ({
  ...(authHeader ? { authorization: authHeader } : {}),
  ...extra,
});

const get = (init = {}) => fetch(`${BASE}/api/logs?limit=40`, { cache: 'no-store', ...init });
const post = (init = {}) => fetch(`${BASE}/api/logs`, { method: 'POST', headers: headers(), ...init });
const del = (init = {}) => fetch(`${BASE}/api/logs`, { method: 'DELETE', headers: headers(), ...init });

async function reachable() {
  try {
    const res = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}

/** The directory the running server actually writes to. */
async function serverDataRoot() {
  try {
    const res = await fetch(`${BASE}/api/settings`, {
      headers: headers(),
      cache: 'no-store',
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return null;
    const payload = await res.json();
    return payload?.runtime?.data_root || null;
  } catch {
    return null;
  }
}

const available = await reachable();
if (!available) {
  console.error(
    `[logs-api] no server answering at ${BASE} - integration tests skipped. Start one with "npm run dev".`
  );
}

const dataRoot = (available && (await serverDataRoot())) || process.env.ACF_DATA_ROOT || '/tmp';
const STATE = path.resolve(path.join(dataRoot, 'state'));
const LOG_FILE = path.join(STATE, 'logs.jsonl');
const FAKE_JOB_LOG = path.join(STATE, 'af-test-job.log');

const logSize = () => (fs.existsSync(LOG_FILE) ? fs.statSync(LOG_FILE).size : -1);
const tail = async () => (await (await get()).json()).logs || [];

describe('logs API', { skip: available ? false : 'server not running' }, () => {
  // Runs first so the following tests start from an empty tail.
  it('DELETE empties the tail and removes job logs but keeps settings', async () => {
    fs.mkdirSync(STATE, { recursive: true });
    fs.writeFileSync(FAKE_JOB_LOG, 'worker output\n', 'utf8');
    const settingsFile = path.join(STATE, 'settings.json');
    const settingsExisted = fs.existsSync(settingsFile);

    const res = await del();
    assert.equal(res.status, 200);
    const payload = await res.json();
    assert.equal(payload.ok, true);
    assert.equal(
      typeof payload.job_logs,
      'number',
      'DELETE did not report job_logs - the server is running an older build; restart it with "npm run dev"'
    );
    assert.ok(
      payload.job_logs >= 1,
      `the seeded job log (${FAKE_JOB_LOG}) was not counted; the server is probably using a different data root`
    );

    assert.equal(fs.existsSync(FAKE_JOB_LOG), false);
    assert.equal(logSize(), 0);
    if (settingsExisted) assert.equal(fs.existsSync(settingsFile), true);

    assert.deepEqual(await tail(), []);
  });

  it('POST seeds a sample tail with mixed levels, newest first', async () => {
    const res = await post();
    assert.equal(res.status, 200);
    const payload = await res.json();
    assert.equal(payload.ok, true);
    assert.equal(payload.added, 6);

    const logs = await tail();
    assert.equal(logs.length, 6, 'a clear tail plus one restore is exactly six entries');
    assert.ok(logs.some((entry) => entry.message.includes('Telegram bot polling started')));
    assert.ok(logs.some((entry) => entry.level === 'warn'));
    assert.ok(logs.some((entry) => entry.level === 'error'));

    // Compare parsed timestamps: Node writes ISO "Z" stamps, the Python workers
    // write offset stamps, so raw string ordering is not meaningful.
    const times = logs.map((entry) => Date.parse(entry.ts));
    assert.ok(times.every((value) => !Number.isNaN(value)), 'every entry needs a parsable ts');
    for (let i = 1; i < times.length; i += 1) {
      assert.ok(times[i - 1] >= times[i], 'seeded entries must be newest first');
    }
  });

  it('GET returns the tail with parsable timestamps', async () => {
    const res = await get();
    assert.equal(res.status, 200);
    const { logs } = await res.json();
    assert.ok(Array.isArray(logs));
    assert.ok(logs.length > 0, 'the previous test seeds entries');
    for (const entry of logs) {
      assert.equal(typeof entry.message, 'string');
      assert.equal(typeof entry.level, 'string');
      assert.ok(!Number.isNaN(Date.parse(entry.ts)), `unparsable timestamp: ${entry.ts}`);
    }
  });

  it('matches the configured auth posture for writes', async () => {
    // Without configured credentials the dashboard is open by design, so the
    // write must succeed rather than 401.
    if (!authHeader) {
      const open = await post();
      assert.equal(open.status, 200);
      const read = await get();
      assert.equal(read.status, 200);
      return;
    }

    const anonymous = await fetch(`${BASE}/api/logs`, { method: 'POST' });
    assert.equal(anonymous.status, 401);
    assert.equal(anonymous.headers.get('www-authenticate'), 'Basic realm="Clipper Factory"');

    const denied = await del({
      headers: { authorization: 'Basic ' + Buffer.from('jane:wrong').toString('base64') },
    });
    assert.equal(denied.status, 401);

    // The read stays open even when writes are gated.
    const read = await fetch(`${BASE}/api/logs?limit=1`);
    assert.equal(read.status, 200);
  });
});

after(async () => {
  if (!available) return;
  // Leave the dashboard with something to show instead of an empty panel.
  try {
    await del();
    await post();
  } catch {
    /* best effort */
  }
});

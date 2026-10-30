/**
 * Integration tests for the read-only settings contract against a running
 * server.
 *
 *   npm run dev          # in one terminal
 *   npm test             # in another
 *
 * Credentials and settings are environment-only (Render's disk is wiped on
 * every deploy), so /api/settings has no working write path: PUT is rejected
 * with 403 and GET reports the effective config.json values plus which
 * credential environment variables the process can see. None of the reads may
 * be cached, or the dashboard would render an old copy.
 *
 * The suite never writes successfully, so config is expected to be unchanged
 * before and after it runs - which the teardown asserts.
 */
import assert from 'node:assert/strict';
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

const getJson = async (path) => {
  const res = await fetch(`${BASE}${path}`, {
    headers: headers(),
    cache: 'no-store',
    signal: AbortSignal.timeout(10000),
  });
  return { res, body: res.ok ? await res.json() : null };
};

async function reachable() {
  try {
    const res = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}

const available = await reachable();
if (!available) {
  console.error(
    `[settings-sync] no server answering at ${BASE} - integration tests skipped. Start one with "npm run dev".`
  );
}

// Snapshot the config once, before any test runs (the describe body itself
// must stay synchronous, so this happens at module scope).
const initial = available ? (await getJson('/api/settings')).body : null;

const original = {
  posting_times: initial?.config?.posting_times,
  timezone: initial?.config?.timezone,
  youtube_auto_post: initial?.config?.youtube_auto_post,
};

describe('settings sync', { skip: available ? false : 'server not running' }, () => {
  after(async () => {
    if (!original.posting_times?.length) return;
    // Nothing in this suite may change configuration: there is no write path
    // left, so the config must still match the snapshot it took at startup.
    const { body } = await getJson('/api/settings');
    assert.deepEqual(body?.config?.posting_times, original.posting_times, 'config must stay unchanged');
    assert.equal(body?.config?.timezone, original.timezone);
    assert.equal(body?.config?.youtube_auto_post, original.youtube_auto_post);
  });

  it('PUT /api/settings is rejected with 403 (env-only deployment)', async () => {
    const put = await fetch(`${BASE}/api/settings`, {
      method: 'PUT',
      headers: headers({ 'Content-Type': 'application/json' }),
      cache: 'no-store',
      body: JSON.stringify({
        settings: { posting_times: ['06:30', '17:45'], timezone: 'Africa/Lagos' },
        tokens: { TELEGRAM_BOT_TOKEN: 'should-never-be-stored' },
      }),
    });

    assert.equal(put.status, 403);
    const payload = await put.json();
    assert.equal(
      payload.error,
      'Settings are managed via environment variables on this deployment.'
    );

    // The rejection must leave the stored configuration untouched.
    const { body } = await getJson('/api/settings');
    assert.deepEqual(body.config.posting_times, original.posting_times, 'a rejected PUT must not change anything');
    assert.equal(body.config.timezone, original.timezone);
  });

  it('state endpoints forbid caching so a page cannot reuse an old copy', async () => {
    for (const path of ['/api/clips', '/api/health']) {
      const { res } = await getJson(path);
      assert.match(
        res.headers.get('cache-control') || '',
        /no-store/,
        `${path} must answer with Cache-Control: no-store`
      );
    }
  });

  it('GET /api/settings returns config, tokens, runtime and queue counts', async () => {
    const { body } = await getJson('/api/settings');

    assert.ok(body.config && typeof body.config === 'object', 'config must be present');
    assert.ok(Array.isArray(body.config.posting_times) && body.config.posting_times.length, 'posting_times come from config.json');
    assert.equal(typeof body.config.timezone, 'string');

    assert.ok(body.tokens && typeof body.tokens === 'object', 'a redacted token status map is expected');
    for (const [key, status] of Object.entries(body.tokens)) {
      assert.equal(typeof status.configured, 'boolean', `${key} must report a boolean`);
      assert.equal(typeof status.hint, 'string', `${key} must carry only a redacted hint`);
      assert.equal('value' in status, false, `${key} must never echo the secret itself`);
    }

    assert.ok(body.runtime && typeof body.runtime === 'object', 'runtime details must be present');
    assert.equal(typeof body.runtime.data_root, 'string');
    assert.equal(typeof body.runtime.whisper_model, 'string');

    assert.equal(typeof body.queue, 'number', 'queue count must be present');
    assert.equal(typeof body.posted, 'number', 'posted count must be present');

    assert.equal('saved' in body, false, 'settings.json overrides are gone by design');
  });
});

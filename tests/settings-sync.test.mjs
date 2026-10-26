/**
 * Integration tests for setting -> state synchronisation against a running
 * server.
 *
 *   npm run dev          # in one terminal
 *   npm test             # in another
 *
 * Guards the contract the dashboard relies on: once a settings write is
 * accepted, every other read endpoint reports the new values on the very next
 * request, and none of them may be cached. A regression here is what makes the
 * overview look stale after editing Auto-Post Settings.
 *
 * The originals are always restored, so the test leaves config unchanged.
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

// Read the originals once, before any test mutates them (the describe body
// itself must stay synchronous, so this runs at module scope).
const initial = available ? (await getJson('/api/settings')).body : null;

const original = {
  posting_times: initial?.config?.posting_times,
  timezone: initial?.config?.timezone,
  youtube_auto_post: initial?.config?.youtube_auto_post,
};

describe('settings sync', { skip: available ? false : 'server not running' }, () => {
  after(async () => {
    if (!original.posting_times?.length) return;
    await fetch(`${BASE}/api/settings`, {
      method: 'PUT',
      headers: headers({ 'Content-Type': 'application/json' }),
      cache: 'no-store',
      body: JSON.stringify({ settings: original }),
    });
    const { body } = await getJson('/api/settings');
    assert.deepEqual(body?.config?.posting_times, original.posting_times, 'originals must be restored');
    assert.equal(body?.config?.timezone, original.timezone);
    assert.equal(body?.config?.youtube_auto_post, original.youtube_auto_post);
  });

  it('a saved setting is visible to every consumer on the next request', async () => {
    const times = ['06:30', '17:45'];
    const zone = original.timezone === 'Africa/Lagos' ? 'Africa/Nairobi' : 'Africa/Lagos';
    const autoPost = !original.youtube_auto_post;

    const put = await fetch(`${BASE}/api/settings`, {
      method: 'PUT',
      headers: headers({ 'Content-Type': 'application/json' }),
      cache: 'no-store',
      body: JSON.stringify({
        settings: { posting_times: times, timezone: zone, youtube_auto_post: autoPost },
      }),
    });
    assert.equal(put.status, 200);
    const saved = await put.json();
    assert.deepEqual(saved.saved.posting_times, times, 'PUT must echo the normalised values it stored');

    // No delay: the very next reads must already carry the new values.
    const clips = await getJson('/api/clips');
    assert.deepEqual(clips.body.config.posting_times, times, '/api/clips served a stale posting_times');
    assert.equal(clips.body.config.timezone, zone, '/api/clips served a stale time zone');
    assert.equal(clips.body.config.youtube_auto_post, autoPost, '/api/clips served a stale auto-post flag');

    const health = await getJson('/api/health');
    assert.deepEqual(health.body.posting_times, times, '/api/health served stale posting times');
    assert.equal(health.body.timezone, zone, '/api/health served a stale time zone');

    const reread = await getJson('/api/settings');
    assert.deepEqual(reread.body.config.posting_times, times, 'the write was not persisted');
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

  it('settings reads never expose stored tokens', async () => {
    const { body } = await getJson('/api/settings');
    assert.equal('tokens' in (body.saved || {}), false);
    assert.ok(body.tokens && typeof body.tokens === 'object', 'a redacted token status map is expected instead');
  });
});

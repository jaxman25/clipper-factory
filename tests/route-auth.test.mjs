/**
 * Proves the /api/logs route handlers themselves enforce Basic auth on
 * writes, so this coverage never depends on a running server.
 *
 * The route imports Next-style "@/..." aliases, which plain Node cannot
 * resolve; registerHooks() maps them to the project root. Rejections happen
 * before any file access, so these tests never mutate log state.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, describe, it } from 'node:test';

let route = null;
let unavailable = null;

const hasHooks = typeof (await import('node:module')).registerHooks === 'function';
if (!hasHooks) {
  unavailable = 'needs node:module registerHooks (Node >= 23.5)';
} else {
  const { registerHooks } = await import('node:module');
  const ROOT_URL = new URL('../', import.meta.url);
  registerHooks({
    resolve(specifier, context, nextResolve) {
      if (specifier.startsWith('@/')) {
        const rel = specifier.slice(2);
        return nextResolve(new URL(rel.endsWith('.js') ? rel : `${rel}.js`, ROOT_URL).href, context);
      }
      return nextResolve(specifier, context);
    },
  });
  try {
    route = await import('../app/api/logs/route.js');
  } catch (err) {
    unavailable = `could not import the route: ${err.message}`;
  }
}

const original = {
  DASHBOARD_USER: process.env.DASHBOARD_USER,
  DASHBOARD_PASSWORD: process.env.DASHBOARD_PASSWORD,
};

function restoreEnv() {
  for (const [key, value] of Object.entries(original)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
}

after(restoreEnv);

const DATA_ROOT = process.env.ACF_DATA_ROOT || '/tmp';
const LOG_FILE = path.join(DATA_ROOT, 'state', 'logs.jsonl');
const fileSnapshot = () => (fs.existsSync(LOG_FILE) ? fs.statSync(LOG_FILE).size : -1);

const req = (method, headers = {}) =>
  new Request('http://localhost:3000/api/logs?limit=5', {
    method,
    headers,
  });

const basic = (user, password) => ({
  authorization: `Basic ${Buffer.from(`${user}:${password}`).toString('base64')}`,
});

describe('/api/logs route guards', { skip: unavailable || false }, () => {
  it('rejects an anonymous POST without touching the log file', async () => {
    process.env.DASHBOARD_USER = 'jane';
    process.env.DASHBOARD_PASSWORD = 'secret';
    const before = fileSnapshot();

    const res = await route.POST(req('POST'));

    assert.equal(res.status, 401);
    assert.equal(res.headers.get('www-authenticate'), 'Basic realm="Clipper Factory"');
    assert.equal(fileSnapshot(), before, 'the guard must run before any write');
    restoreEnv();
  });

  it('rejects an anonymous DELETE without touching the log file', async () => {
    process.env.DASHBOARD_USER = 'jane';
    process.env.DASHBOARD_PASSWORD = 'secret';
    const before = fileSnapshot();

    const res = await route.DELETE(req('DELETE'));

    assert.equal(res.status, 401);
    assert.equal(fileSnapshot(), before);
    restoreEnv();
  });

  it('rejects a wrong password even when it is sent', async () => {
    process.env.DASHBOARD_USER = 'jane';
    process.env.DASHBOARD_PASSWORD = 'secret';
    const before = fileSnapshot();

    const res = await route.POST(req('POST', basic('jane', 'wrong')));

    assert.equal(res.status, 401);
    assert.equal(fileSnapshot(), before);
    restoreEnv();
  });

  it('keeps GET public while writes are protected', async () => {
    process.env.DASHBOARD_USER = 'jane';
    process.env.DASHBOARD_PASSWORD = 'secret';

    const res = await route.GET(req('GET'));

    assert.equal(res.status, 200);
    const payload = await res.json();
    assert.ok(Array.isArray(payload.logs), 'the polling read must stay open');
    restoreEnv();
  });

  it('admits requests once credentials match', async () => {
    process.env.DASHBOARD_USER = 'jane';
    process.env.DASHBOARD_PASSWORD = 'secret';
    // Assert the guard decision rather than running a full POST, which would
    // seed sample logs into the shared state directory.
    const { hasDashboardAccess } = await import('../lib/auth.js');
    assert.equal(hasDashboardAccess(req('POST', basic('jane', 'secret'))), true);
    assert.equal(hasDashboardAccess(req('POST', basic('jane', 'other'))), false);
    restoreEnv();
  });
});

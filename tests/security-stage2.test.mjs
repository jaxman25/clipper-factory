/**
 * Phase 10 Stage 2: production authentication posture.
 *
 * Exercises the real middleware and route handlers with a throwaway data root.
 * `next-auth` is replaced by tests/helpers/next-auth-stub.mjs (anonymous
 * session) because the real getServerSession() needs the Next request context;
 * the stub is exactly what an unauthenticated production caller looks like.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, describe, it } from 'node:test';

const TEST_DATA_ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'acf-sec-stage2-'));
process.env.ACF_DATA_ROOT = TEST_DATA_ROOT;
process.env.ACF_USERS_FILE = path.join(TEST_DATA_ROOT, 'users.json');
process.env.NODE_ENV = 'development';
delete process.env.DASHBOARD_USER;
delete process.env.DASHBOARD_PASSWORD;

const originalNodeEnv = process.env.NODE_ENV;
let unavailable = null;
let mods = null;

const hasHooks = typeof (await import('node:module')).registerHooks === 'function';
if (!hasHooks) {
  unavailable = 'needs node:module registerHooks (Node >= 23.5)';
} else {
  const { registerHooks } = await import('node:module');
  const ROOT_URL = new URL('../', import.meta.url);
  const SESSION_STUB = new URL('./helpers/next-auth-stub.mjs', import.meta.url).href;
  const OPTIONS_STUB = new URL('./helpers/next-auth-options-stub.mjs', import.meta.url).href;
  registerHooks({
    resolve(specifier, context, nextResolve) {
      if (specifier === 'next-auth') return nextResolve(SESSION_STUB, context);
      if (specifier === '@/lib/next-auth') return nextResolve(OPTIONS_STUB, context);
      // Next's package exports do not resolve in plain Node; the ESM entry does.
      if (specifier === 'next/server') return nextResolve('next/server.js', context);
      if (specifier.startsWith('@/')) {
        const rel = specifier.slice(2);
        return nextResolve(new URL(rel.endsWith('.js') ? rel : `${rel}.js`, ROOT_URL).href, context);
      }
      // Several project modules import siblings without an extension, which
      // Node's ESM resolver rejects but Next's bundler accepts.
      if (specifier.startsWith('.') && !path.extname(specifier)) {
        return nextResolve(`${specifier}.js`, context);
      }
      return nextResolve(specifier, context);
    },
  });
  try {
    mods = {
      auth: await import('../lib/auth.js'),
      server: await import('next/server.js'),
      middlewareModule: await import('../middleware.js'),
      logs: await import('../app/api/logs/route.js'),
      reset: await import('../app/api/reset/route.js'),
      generate: await import('../app/api/generate/route.js'),
      credits: await import('../app/api/credits/route.js'),
    };
  } catch (err) {
    unavailable = `could not import the modules under test: ${err.message}`;
  }
}

after(() => {
  delete process.env.DASHBOARD_USER;
  delete process.env.DASHBOARD_PASSWORD;
  process.env.NODE_ENV = originalNodeEnv;
  fs.rmSync(TEST_DATA_ROOT, { recursive: true, force: true });
});

const basic = (user = 'jane', password = 'secret') =>
  `Basic ${Buffer.from(`${user}:${password}`).toString('base64')}`;

function configure(user = 'jane', password = 'secret') {
  process.env.DASHBOARD_USER = user;
  process.env.DASHBOARD_PASSWORD = password;
}

function jwtFreeEnv() {
  process.env.NODE_ENV = 'production';
  delete process.env.DASHBOARD_USER;
  delete process.env.DASHBOARD_PASSWORD;
}

describe('middleware gate', { skip: unavailable || false }, () => {
  const { NextRequest } = mods?.server || {};
  const middleware = mods?.middlewareModule?.middleware;
  const matcher = (mods?.middlewareModule?.config?.matcher || []).join(' ');

  const call = (url, headers) =>
    middleware(new NextRequest(url, { headers }));

  it('fails closed in production when credentials are missing', async () => {
    jwtFreeEnv();
    const res = await call('https://app.example.com/dashboard', {
      host: 'app.example.com',
    });
    assert.equal(res.status, 503);
    assert.match(await res.text(), /DASHBOARD_USER/);
  });

  it('challenges anonymous API requests when credentials are configured', async () => {
    process.env.NODE_ENV = 'production';
    configure();
    const res = await call('https://app.example.com/api/generate', {
      host: 'app.example.com',
    });
    assert.equal(res.status, 401);
    assert.equal(res.headers.get('www-authenticate'), 'Basic realm="Clipper Factory"');
  });

  it('lets an authenticated API request through', async () => {
    process.env.NODE_ENV = 'production';
    configure();
    const res = await call('https://app.example.com/api/generate', {
      host: 'app.example.com',
      authorization: basic(),
    });
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('x-middleware-next'), '1');
  });

  it('still redirects an authenticated non-local dashboard to login', async () => {
    process.env.NODE_ENV = 'production';
    configure();
    const res = await call('https://app.example.com/dashboard', {
      host: 'app.example.com',
      authorization: basic(),
    });
    assert.equal(res.status, 307);
  });

  it('stays credential-free for local development', async () => {
    process.env.NODE_ENV = 'development';
    delete process.env.DASHBOARD_USER;
    delete process.env.DASHBOARD_PASSWORD;
    const res = await call('http://localhost:3000/dashboard', {
      host: 'localhost:3000',
    });
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('x-middleware-next'), '1');
  });

  it('keeps health, auth, media and thumb outside the matcher', () => {
    for (const prefix of ['api/health', 'api/auth', 'api/media', 'api/thumb']) {
      assert.ok(matcher.includes(prefix), `${prefix} must be excluded from the gate`);
    }
    assert.ok(
      !/api\/generate|api\/reset/.test(matcher),
      'generation and reset must stay gated by the middleware'
    );
    // /api/logs stays outside the matcher for cheap polling; the route itself
    // now enforces the same dashboard credentials on GET, POST and DELETE.
    assert.ok(matcher.includes('api/logs'));
  });
});

describe('generate authorization', { skip: unavailable || false }, () => {
  const post = (headers) =>
    mods.generate.POST(
      new Request('https://app.example.com/api/generate', {
        method: 'POST',
        headers: {
          host: 'app.example.com',
          'content-type': 'application/json',
          ...headers,
        },
        body: JSON.stringify({ url: 'https://example.com/v', mode: 'viral', num_shorts: 1 }),
      })
    );

  it('refuses a forged local header in production', async () => {
    process.env.NODE_ENV = 'production';
    delete process.env.DASHBOARD_USER;
    delete process.env.DASHBOARD_PASSWORD;
    const before = globalThis.__nextAuthSessionCalls || 0;

    const res = await post({ 'x-forwarded-host': 'localhost' });

    assert.equal(res.status, 401);
    assert.match((await res.json()).error, /Sign in/);
    assert.ok(
      (globalThis.__nextAuthSessionCalls || 0) > before,
      'production must consult the session, not the forwarded header'
    );
    const jobsDir = path.join(TEST_DATA_ROOT, 'state', 'jobs');
    assert.equal(
      fs.existsSync(jobsDir) ? fs.readdirSync(jobsDir).length : 0,
      0,
      'a refused request must not spawn a job'
    );
  });

  it('credits never treats a spoofed header as localhost', async () => {
    process.env.NODE_ENV = 'production';
    const res = await mods.credits.GET(
      new Request('https://app.example.com/api/credits', {
        headers: { host: 'app.example.com', 'x-forwarded-host': 'localhost' },
      })
    );
    assert.equal(res.status, 401);
    assert.equal((await res.json()).authenticated, false);
  });
});

describe('logs read guard', { skip: unavailable || false }, () => {
  it('denies anonymous reads and admits the dashboard', async () => {
    process.env.NODE_ENV = 'production';
    configure();

    const anonymous = await mods.logs.GET(
      new Request('https://app.example.com/api/logs?limit=5', {
        headers: { host: 'app.example.com' },
      })
    );
    assert.equal(anonymous.status, 401);
    assert.equal(
      anonymous.headers.get('www-authenticate'),
      'Basic realm="Clipper Factory"'
    );

    const authorized = await mods.logs.GET(
      new Request('https://app.example.com/api/logs?limit=5', {
        headers: { host: 'app.example.com', authorization: basic() },
      })
    );
    assert.equal(authorized.status, 200);
    assert.ok(Array.isArray((await authorized.json()).logs));
  });
});

describe('destructive reset guard', { skip: unavailable || false }, () => {
  const queueDir = path.join(TEST_DATA_ROOT, 'queue');
  const sentinel = (name) => {
    fs.mkdirSync(queueDir, { recursive: true });
    const file = path.join(queueDir, name);
    fs.writeFileSync(file, JSON.stringify({ id: name.replace('.json', '') }), 'utf8');
    return file;
  };
  const reset = (headers) =>
    mods.reset.POST(
      new Request('https://app.example.com/api/reset', {
        method: 'POST',
        headers: { host: 'app.example.com', 'content-type': 'application/json', ...headers },
        body: JSON.stringify({ confirm: true }),
      })
    );

  it('rejects anonymous callers before touching any data', async () => {
    process.env.NODE_ENV = 'production';
    configure();
    const file = sentinel('keep-anonymous.json');

    const res = await reset({});

    assert.equal(res.status, 401);
    assert.equal(fs.existsSync(file), true, 'rejected reset must delete nothing');
  });

  it('still works for the authenticated owner', async () => {
    process.env.NODE_ENV = 'production';
    configure();
    const file = sentinel('remove-authenticated.json');

    const res = await reset({ authorization: basic() });

    assert.equal(res.status, 200);
    assert.equal((await res.json()).ok, true);
    assert.equal(fs.existsSync(file), false);
  });
});

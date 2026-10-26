import assert from 'node:assert/strict';
import { after, describe, it } from 'node:test';

import { hasDashboardAccess, unauthorizedHeaders } from '../lib/auth.js';

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

function configure(user = 'jane', password = 'secret') {
  process.env.DASHBOARD_USER = user;
  process.env.DASHBOARD_PASSWORD = password;
}

const request = (header) => ({ headers: new Headers(header ? { authorization: header } : {}) });
const basic = (user, password) => `Basic ${Buffer.from(`${user}:${password}`).toString('base64')}`;

describe('hasDashboardAccess', () => {
  it('is open when no credentials are configured', () => {
    delete process.env.DASHBOARD_USER;
    delete process.env.DASHBOARD_PASSWORD;
    assert.equal(hasDashboardAccess(request()), true);
    assert.equal(hasDashboardAccess(request(basic('anyone', 'anything'))), true);
    restoreEnv();
  });

  it('is open when only one of the two variables is set', () => {
    process.env.DASHBOARD_USER = 'jane';
    delete process.env.DASHBOARD_PASSWORD;
    assert.equal(hasDashboardAccess(request()), true);
    restoreEnv();
  });

  it('rejects anonymous requests when credentials are set', () => {
    configure();
    assert.equal(hasDashboardAccess(request()), false);
    restoreEnv();
  });

  it('rejects a wrong user or password', () => {
    configure('jane', 'secret');
    assert.equal(hasDashboardAccess(request(basic('jane', 'wrong'))), false);
    assert.equal(hasDashboardAccess(request(basic('intruder', 'secret'))), false);
    restoreEnv();
  });

  it('accepts matching credentials', () => {
    configure('jane', 'secret');
    assert.equal(hasDashboardAccess(request(basic('jane', 'secret'))), true);
    restoreEnv();
  });

  it('rejects other auth schemes', () => {
    configure();
    assert.equal(hasDashboardAccess(request('Bearer abc.def')), false);
    assert.equal(hasDashboardAccess(request('Digest username="jane"')), false);
    restoreEnv();
  });

  it('rejects malformed Basic credentials instead of throwing', () => {
    configure();
    // Not base64 at all: atob throws and must fall through to a rejection.
    assert.equal(hasDashboardAccess(request('Basic %%%not-base64%%%')), false);
    // Valid base64 but no user:password shape.
    assert.equal(
      hasDashboardAccess(request(`Basic ${Buffer.from('nocolon').toString('base64')}`)),
      false
    );
    // Empty password segment must not match a non-empty configured password.
    assert.equal(hasDashboardAccess(request(basic('jane', ''))), false);
    restoreEnv();
  });
});

describe('unauthorizedHeaders', () => {
  it('carries the Basic challenge for the Clipper Factory realm', () => {
    assert.equal(unauthorizedHeaders()['WWW-Authenticate'], 'Basic realm="Clipper Factory"');
  });
});

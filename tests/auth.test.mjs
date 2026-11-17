import assert from 'node:assert/strict';
import { after, describe, it } from 'node:test';

import {
  dashboardCredentialsConfigured,
  hasDashboardAccess,
  isLocalRequest,
  isProduction,
  unauthorizedHeaders,
} from '../lib/auth.js';

const original = {
  NODE_ENV: process.env.NODE_ENV,
  DASHBOARD_USER: process.env.DASHBOARD_USER,
  DASHBOARD_PASSWORD: process.env.DASHBOARD_PASSWORD,
};

// Every legacy case below describes local development.
process.env.NODE_ENV = 'development';

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

describe('production posture', () => {
  it('fails closed when dashboard credentials are missing', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.DASHBOARD_USER;
    delete process.env.DASHBOARD_PASSWORD;

    assert.equal(isProduction(), true);
    assert.equal(dashboardCredentialsConfigured(), false);
    assert.equal(hasDashboardAccess(request()), false);
    assert.equal(hasDashboardAccess(request(basic('anyone', 'anything'))), false);

    process.env.NODE_ENV = 'development';
  });

  it('fails closed when only one credential is set', () => {
    process.env.NODE_ENV = 'production';
    process.env.DASHBOARD_USER = 'jane';
    delete process.env.DASHBOARD_PASSWORD;
    assert.equal(hasDashboardAccess(request()), false);

    process.env.NODE_ENV = 'development';
    restoreEnv();
  });

  it('keeps admitting matching credentials in production', () => {
    process.env.NODE_ENV = 'production';
    configure();
    assert.equal(hasDashboardAccess(request()), false);
    assert.equal(hasDashboardAccess(request(basic('jane', 'secret'))), true);

    process.env.NODE_ENV = 'development';
    restoreEnv();
  });

  it('leaves credential-free local development working', () => {
    process.env.NODE_ENV = 'development';
    delete process.env.DASHBOARD_USER;
    delete process.env.DASHBOARD_PASSWORD;
    assert.equal(hasDashboardAccess(request()), true);
  });
});

describe('isLocalRequest', () => {
  const reqWith = (headers) => ({ headers: new Headers(headers) });

  it('accepts local hosts outside production', () => {
    process.env.NODE_ENV = 'development';
    assert.equal(isLocalRequest(reqWith({ host: 'localhost:3000' })), true);
    assert.equal(isLocalRequest(reqWith({ host: '127.0.0.1:3000' })), true);
    assert.equal(isLocalRequest(reqWith({ host: 'clips.example.com' })), false);
  });

  it('ignores a forged x-forwarded-host header', () => {
    process.env.NODE_ENV = 'development';
    const spoofed = reqWith({
      host: 'clips.example.com',
      'x-forwarded-host': 'localhost',
    });
    assert.equal(isLocalRequest(spoofed), false);
  });

  it('is never local in production, whatever the headers say', () => {
    process.env.NODE_ENV = 'production';
    assert.equal(isLocalRequest(reqWith({ host: 'localhost:3000' })), false);
    assert.equal(
      isLocalRequest(reqWith({ host: 'localhost:3000', 'x-forwarded-host': 'localhost' })),
      false
    );
    process.env.NODE_ENV = 'development';
  });
});

describe('unauthorizedHeaders', () => {
  it('carries the Basic challenge for the Clipper Factory realm', () => {
    assert.equal(unauthorizedHeaders()['WWW-Authenticate'], 'Basic realm="Clipper Factory"');
  });
});

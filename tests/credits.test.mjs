/**
 * Covers the credit-store rules the /api/generate gate depends on:
 * 5 free credits on signup, no balance reset on re-sight, no negative
 * balances, ADMIN_EMAIL matching (and its empty-safe default), and the
 * scrypt password round-trip used by the credentials login.
 *
 * ACF_DATA_ROOT must be set before lib/credits.js (or lib/store.js) is
 * imported, so the module is loaded dynamically inside the hooks below.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, before, beforeEach, describe, it } from 'node:test';

const USERS_FILE = () => path.join(tmpRoot, 'state', 'users.json');

let tmpRoot;
let credits;

before(() => {
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'acf-credits-'));
  process.env.ACF_DATA_ROOT = tmpRoot;
});

after(() => {
  delete process.env.ADMIN_EMAIL;
  fs.rmSync(tmpRoot, { recursive: true, force: true });
});

beforeEach(() => {
  delete process.env.ADMIN_EMAIL;
  if (fs.existsSync(USERS_FILE())) fs.rmSync(USERS_FILE(), { force: true });
});

async function load() {
  if (!credits) credits = await import('../lib/credits.js');
  return credits;
}

const tempsIn = (dir) =>
  fs.existsSync(dir)
    ? fs.readdirSync(dir).filter((name) => name.endsWith('.tmp'))
    : [];

describe('signup credits', () => {
  it('grants every new user 5 free credits', async () => {
    const { ensureUser, DEFAULT_CREDITS, getCredits } = await load();
    assert.equal(DEFAULT_CREDITS, 5);
    const user = ensureUser('New.User@Example.com ');
    assert.equal(user.credits, 5);
    assert.equal(getCredits('new.user@example.com'), 5);
    // The stored key is normalised so login casing can't create duplicates.
    assert.equal(Object.keys(JSON.parse(fs.readFileSync(USERS_FILE(), 'utf8'))).length, 1);
  });

  it('never resets the balance of an existing user', async () => {
    const { ensureUser, deductCredit, getCredits } = await load();
    ensureUser('jane@example.com');
    deductCredit('jane@example.com');
    deductCredit('jane@example.com');
    assert.equal(getCredits('jane@example.com'), 3);

    const again = ensureUser('JANE@example.com');
    assert.equal(again.credits, 3, 're-sighting must not restore credits');
    assert.equal(getCredits('jane@example.com'), 3);
  });
});

describe('deductCredit', () => {
  it('walks the balance down to zero and then refuses', async () => {
    const { ensureUser, deductCredit, getCredits } = await load();
    ensureUser('spend@example.com');
    for (let i = 5; i >= 1; i -= 1) {
      const result = deductCredit('spend@example.com');
      assert.deepEqual(result, { ok: true, credits: i - 1, error: null });
      assert.equal(getCredits('spend@example.com'), i - 1);
    }
    const refused = deductCredit('spend@example.com');
    assert.equal(refused.ok, false);
    assert.equal(refused.credits, 0, 'a zero balance never goes negative');
    assert.equal(getCredits('spend@example.com'), 0);
  });

  it('treats an unknown user as broke and creates nothing', async () => {
    const { deductCredit, getCredits } = await load();
    const result = deductCredit('ghost@example.com');
    assert.equal(result.ok, false);
    assert.equal(getCredits('ghost@example.com'), 0);
    assert.equal(fs.existsSync(USERS_FILE()), false, 'no user file is created by a failed debit');
  });

  it('leaves no temp files behind', async () => {
    const { ensureUser, deductCredit } = await load();
    ensureUser('tidy@example.com');
    deductCredit('tidy@example.com');
    assert.deepEqual(tempsIn(path.dirname(USERS_FILE())), []);
  });
});

describe('isAdminEmail (ADMIN_EMAIL)', () => {
  it('matches case-insensitively when set', async () => {
    const { isAdminEmail } = await load();
    process.env.ADMIN_EMAIL = ' Owner@Example.COM ';
    assert.equal(isAdminEmail('owner@example.com'), true);
    assert.equal(isAdminEmail('OWNER@EXAMPLE.COM'), true);
    assert.equal(isAdminEmail('someone-else@example.com'), false);
  });

  it('grants nobody admin when ADMIN_EMAIL is missing or empty', async () => {
    const { isAdminEmail } = await load();
    delete process.env.ADMIN_EMAIL;
    assert.equal(isAdminEmail('owner@example.com'), false);
    assert.equal(isAdminEmail(''), false);
    process.env.ADMIN_EMAIL = '';
    assert.equal(isAdminEmail('owner@example.com'), false, 'an empty value must not match everything');
    process.env.ADMIN_EMAIL = '@';
    assert.equal(isAdminEmail('@'), false, 'junk values never match');
  });
});

describe('password hashing', () => {
  it('round-trips a password and rejects wrong/tampered values', async () => {
    const { ensureUser, hashPassword, setPassword, verifyPassword } = await load();
    ensureUser('pw@example.com');
    const hash = hashPassword('correct horse battery staple');
    assert.equal(verifyPassword('correct horse battery staple', hash), true);
    assert.equal(verifyPassword('wrong', hash), false);
    assert.equal(verifyPassword('', hash), false);

    // Tampered hex digest / malformed storage is a clean false, not a throw.
    const [scheme, salt] = hash.split(':');
    assert.equal(verifyPassword('correct horse battery staple', `${scheme}:${salt}:deadbeef`), false);
    assert.equal(verifyPassword('x', 'not-a-hash'), false);
    assert.equal(verifyPassword('x', ''), false);
    assert.equal(verifyPassword('x', null), false);
  });

  it('setPassword persists a verifiable hash for the right user only', async () => {
    const { ensureUser, findUser, setPassword, verifyPassword } = await load();
    ensureUser('real@example.com');
    assert.equal(setPassword('nobody@example.com', 'pw'), false, 'cannot attach a password to a missing user');

    assert.equal(setPassword('REAL@example.com', 'hunter2'), true);
    const stored = findUser('real@example.com');
    assert.equal(verifyPassword('hunter2', stored.password_hash), true);
    assert.equal(verifyPassword('other', stored.password_hash), false);
    assert.match(stored.password_hash, /^scrypt:[0-9a-f]+:[0-9a-f]+$/, 'never store plaintext');
  });
});

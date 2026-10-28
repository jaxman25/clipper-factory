/**
 * Users and credits for the public-facing app.
 *
 * One JSON document (state/users.json) keyed by normalised email, written with
 * the same atomic writeJSON the rest of the app uses, so a crash mid-write can
 * never corrupt a balance. Passwords are hashed with scrypt from node:crypto -
 * no extra dependency; only the hash and the balance are persisted.
 *
 * ADMIN_EMAIL (the owner's email, set in .env) grants admin: unlimited
 * credits, no credit check at all. A missing/empty ADMIN_EMAIL means nobody is
 * admin - the comparison never matches an empty string against a real email.
 */
import crypto from 'node:crypto';
import path from 'node:path';
import { DIRS, readJSON, writeJSON } from './store.js';

/** Free credits granted on first sign-up (spec: every new public user). */
export const DEFAULT_CREDITS = 5;

const USERS_FILE = path.join(DIRS.state, 'users.json');

export function normalizeEmail(email) {
  return String(email || '').trim().toLowerCase();
}

/** True only when ADMIN_EMAIL is set and matches the given email (case-insensitive). */
export function isAdminEmail(email) {
  const admin = String(process.env.ADMIN_EMAIL || '').trim().toLowerCase();
  const candidate = normalizeEmail(email);
  if (!admin || !candidate) return false;
  // Require something on both sides of the @ so a junk/empty config value
  // ("@", " ") can never be string-matched by a crafted sign-in.
  const [local, domain] = admin.split('@');
  if (!local || !domain || admin.includes('@', admin.indexOf('@') + 1)) return false;
  return candidate === admin;
}

function readUsers() {
  const data = readJSON(USERS_FILE, {});
  return data && typeof data === 'object' && !Array.isArray(data) ? data : {};
}

function writeUsers(users) {
  writeJSON(USERS_FILE, users);
}

export function findUser(email) {
  const key = normalizeEmail(email);
  if (!key) return null;
  return readUsers()[key] || null;
}

/**
 * Create-on-first-sight with the free signup credits.
 * An existing user is returned untouched - never resets a spent balance.
 */
export function ensureUser(email) {
  const key = normalizeEmail(email);
  if (!key) return null;
  const users = readUsers();
  if (users[key]) return users[key];
  users[key] = {
    email: key,
    credits: DEFAULT_CREDITS,
    password_hash: null, // set by password sign-in; Google sign-ins have none
    created_at: new Date().toISOString(),
  };
  writeUsers(users);
  return users[key];
}

export function getCredits(email) {
  const user = findUser(email);
  return user ? user.credits : 0;
}

/**
 * Spend one credit. Returns { ok, credits, error } and never drives a
 * balance negative; an unknown user counts as out of credits.
 */
export function deductCredit(email) {
  const key = normalizeEmail(email);
  const users = readUsers();
  const user = users[key];
  if (!user) return { ok: false, credits: 0, error: 'unknown user' };
  if (user.credits <= 0) return { ok: false, credits: 0, error: 'out of credits' };
  user.credits -= 1;
  user.updated_at = new Date().toISOString();
  writeUsers(users);
  return { ok: true, credits: user.credits, error: null };
}

export function hashPassword(password) {
  const salt = crypto.randomBytes(16).toString('hex');
  const hash = crypto.scryptSync(String(password), salt, 64).toString('hex');
  return `scrypt:${salt}:${hash}`;
}

/** Constant-time verification; any malformed/absent hash is simply "wrong". */
export function verifyPassword(password, stored) {
  try {
    const [scheme, salt, hash] = String(stored || '').split(':');
    if (scheme !== 'scrypt' || !salt || !hash) return false;
    const candidate = crypto.scryptSync(String(password), salt, 64);
    const expected = Buffer.from(hash, 'hex');
    if (candidate.length !== expected.length) return false;
    return crypto.timingSafeEqual(candidate, expected);
  } catch (err) {
    return false;
  }
}

/** Attach a password to an existing user (returns false if absent/invalid). */
export function setPassword(email, password) {
  const key = normalizeEmail(email);
  if (!key || !password) return false;
  const users = readUsers();
  if (!users[key]) return false;
  users[key].password_hash = hashPassword(password);
  users[key].password_set_at = new Date().toISOString();
  writeUsers(users);
  return true;
}

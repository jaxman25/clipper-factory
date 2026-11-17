/**
 * Test double for `next-auth` used by tests/security-stage2.test.mjs.
 *
 * Next's real getServerSession() needs the Next request context, which does not
 * exist when a route handler is imported into plain Node. Returning an
 * anonymous session is exactly what an unauthenticated production request
 * looks like, so the route guards can be exercised without weakening anything.
 */
export async function getServerSession() {
  globalThis.__nextAuthSessionCalls = (globalThis.__nextAuthSessionCalls || 0) + 1;
  return null;
}

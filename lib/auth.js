/**
 * HTTP Basic auth for the dashboard, shared by the middleware and by route
 * handlers the middleware matcher skips (e.g. /api/logs, which is excluded so
 * the dashboard's polling stays cheap). Writes on those routes must still
 * reject anonymous callers, so they check this directly.
 *
 * With no DASHBOARD_USER/DASHBOARD_PASSWORD configured the dashboard is open,
 * which is the local-development default.
 */
export function hasDashboardAccess(request) {
  const user = process.env.DASHBOARD_USER;
  const password = process.env.DASHBOARD_PASSWORD;
  if (!user || !password) return true;

  const header = request.headers.get('authorization') || '';
  if (header.startsWith('Basic ')) {
    try {
      const decoded = atob(header.slice(6));
      const index = decoded.indexOf(':');
      const suppliedUser = decoded.slice(0, index);
      const suppliedPassword = decoded.slice(index + 1);
      if (suppliedUser === user && suppliedPassword === password) return true;
    } catch (err) {
      /* fall through to the rejection below */
    }
  }
  return false;
}

export function unauthorizedHeaders() {
  return { 'WWW-Authenticate': 'Basic realm="Clipper Factory"' };
}

/**
 * Hostname the client actually addressed, read straight from the headers.
 *
 * x-forwarded-host (set by the Render proxy) wins over Host, so a request
 * arriving on the public domain is never mistaken for localhost - which would
 * skip the login and credit gates. Edge-safe: plain string handling only.
 */
export function requestHostname(request) {
  const raw =
    (request.headers.get('x-forwarded-host') || request.headers.get('host') || '')
      .split(',')[0]
      .trim()
      .toLowerCase();
  if (!raw) return '';
  // Strip the port without breaking IPv6 literals like [::1]:3000.
  if (raw.startsWith('[')) {
    const end = raw.indexOf(']');
    return end === -1 ? raw : raw.slice(0, end + 1);
  }
  const colon = raw.indexOf(':');
  return colon === -1 ? raw : raw.slice(0, colon);
}

export const LOCAL_HOSTNAMES = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

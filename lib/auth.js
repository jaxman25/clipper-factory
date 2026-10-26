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

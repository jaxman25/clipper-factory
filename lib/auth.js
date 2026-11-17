/**
 * HTTP Basic auth for the dashboard, shared by the middleware and by route
 * handlers the middleware matcher skips (e.g. /api/logs, which is excluded so
 * the dashboard's polling stays cheap). Reads and writes on those routes must
 * still apply this check directly.
 *
 * Local development stays credential-free. Production fails closed: without
 * DASHBOARD_USER/DASHBOARD_PASSWORD every gated request is refused instead of
 * exposing the dashboard because a deployment forgot to set them.
 */
export function isProduction() {
  return String(process.env.NODE_ENV || '').toLowerCase() === 'production';
}

/** True only when both Basic-auth credentials are configured. */
export function dashboardCredentialsConfigured() {
  const user = process.env.DASHBOARD_USER;
  const password = process.env.DASHBOARD_PASSWORD;
  return Boolean(user && password);
}

export function hasDashboardAccess(request) {
  const user = process.env.DASHBOARD_USER;
  const password = process.env.DASHBOARD_PASSWORD;
  if (!user || !password) return !isProduction();

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

/** Lower-cased hostname of one header value, port stripped, IPv6 safe. */
function hostnameOf(value) {
  const raw = String(value || '')
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

/**
 * Hostname the client addressed, for display. Proxy-aware: x-forwarded-host
 * wins because Render's proxy rewrites it for public requests.
 *
 * Never use this to decide whether a request is local - see isLocalRequest().
 */
export function requestHostname(request) {
  return hostnameOf(
    request.headers.get('x-forwarded-host') || request.headers.get('host')
  );
}

/**
 * True only when this really is a local-development request.
 *
 * Production is never local, whatever the headers say. Outside production only
 * the Host header is consulted: x-forwarded-host is supplied by the caller, so
 * trusting it let a remote request claim "localhost" and skip sign-in and the
 * credit gate.
 */
export function isLocalRequest(request) {
  if (isProduction()) return false;
  return LOCAL_HOSTNAMES.has(hostnameOf(request.headers.get('host')));
}

export const LOCAL_HOSTNAMES = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

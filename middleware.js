import { NextResponse } from 'next/server';

/**
 * Optional dashboard protection. Set DASHBOARD_USER + DASHBOARD_PASSWORD on
 * Render and every page/API except /api/health, /api/media and /api/thumb asks
 * for HTTP Basic credentials. Media stays public so Instagram can fetch a Reel
 * and health stays public for UptimeRobot.
 */
const PUBLIC_PATHS = [/^\/$/, /^\/favicon\.ico$/, /^\/assets\//];

// Dashboard's short-polling endpoints. The frontend polls these every
// 20s (clips/health) and 4s (job progress) while rendering. They flood
// the terminal with request logs and should be served immediately
// without reaching the route handlers or the request logging pipeline.
const POLLING_PATHS = ['/api/generate', '/api/logs'];

function isPollingPath(pathname) {
  return POLLING_PATHS.some((p) => pathname === p || pathname.startsWith(p));
}

export function middleware(request) {
  // Short-polling endpoints are intercepted here, before they reach
  // the route handlers or the request logging pipeline.
  if (isPollingPath(request.nextUrl.pathname)) {
    return new NextResponse('{}', { status: 200 });
  }

  const user = process.env.DASHBOARD_USER;
  const password = process.env.DASHBOARD_PASSWORD;
  if (!user || !password) return NextResponse.next();

  // Marketing page + brand assets stay public; everything else is gated.
  if (PUBLIC_PATHS.some((pattern) => pattern.test(request.nextUrl.pathname))) {
    return NextResponse.next();
  }

  const header = request.headers.get('authorization') || '';
  if (header.startsWith('Basic ')) {
    try {
      const decoded = atob(header.slice(6));
      const index = decoded.indexOf(':');
      const suppliedUser = decoded.slice(0, index);
      const suppliedPassword = decoded.slice(index + 1);
      if (suppliedUser === user && suppliedPassword === password) {
        return NextResponse.next();
      }
    } catch (err) {
      /* fall through to 401 */
    }
  }

  return new NextResponse('Authentication required', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="Clipper Factory"' },
  });
}

export const config = {
  matcher: ['/((?!api/health|api/media|api/thumb|_next/static|_next/image|favicon.ico|api/generate|api/logs).*)'],
};

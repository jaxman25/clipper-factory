import { NextResponse } from 'next/server';

/**
 * Optional dashboard protection. Set DASHBOARD_USER + DASHBOARD_PASSWORD on
 * Render and every page/API except /api/health, /api/media and /api/thumb asks
 * for HTTP Basic credentials. Media stays public so Instagram can fetch a Reel
 * and health stays public for UptimeRobot.
 */
const PUBLIC_PATHS = [/^\/$/, /^\/favicon\.ico$/, /^\/assets\//];

export function middleware(request) {
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
  matcher: ['/((?!api/health|api/media|api/thumb|_next/static|_next/image|favicon.ico).*)'],
};

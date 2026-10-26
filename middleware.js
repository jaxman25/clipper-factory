import { NextResponse } from 'next/server';

import { hasDashboardAccess, unauthorizedHeaders } from '@/lib/auth';

/**
 * Optional dashboard protection. Set DASHBOARD_USER + DASHBOARD_PASSWORD on
 * Render and every page/API except /api/health, /api/media and /api/thumb asks
 * for HTTP Basic credentials. Media stays public so Instagram can fetch a Reel
 * and health stays public for UptimeRobot.
 */
const PUBLIC_PATHS = [/^\/$/, /^\/favicon\.ico$/, /^\/assets\//];

// /api/logs is skipped by the matcher because the route enforces its own
// posture (public reads, authenticated writes). Everything else, including the
// 4s /api/generate job polling, goes through the gate below.
export function middleware(request) {
  // Marketing page + brand assets stay public; everything else is gated.
  if (PUBLIC_PATHS.some((pattern) => pattern.test(request.nextUrl.pathname))) {
    return NextResponse.next();
  }

  if (hasDashboardAccess(request)) {
    return NextResponse.next();
  }

  return new NextResponse('Authentication required', {
    status: 401,
    headers: unauthorizedHeaders(),
  });
}

export const config = {
  matcher: ['/((?!api/health|api/media|api/thumb|_next/static|_next/image|favicon.ico|api/logs).*)'],
};

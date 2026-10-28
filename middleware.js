import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';

import { hasDashboardAccess, LOCAL_HOSTNAMES, requestHostname, unauthorizedHeaders } from '@/lib/auth';

/**
 * Optional dashboard protection. Set DASHBOARD_USER + DASHBOARD_PASSWORD on
 * Render and every page/API except /api/health, /api/media and /api/thumb asks
 * for HTTP Basic credentials. Media stays public so Instagram can fetch a Reel
 * and health stays public for UptimeRobot.
 *
 * On top of that (spec 04), /dashboard additionally requires a next-auth
 * session and redirects anonymous visitors to /login - except on localhost,
 * where login is bypassed entirely so the owner never signs in while testing.
 * /api/auth is excluded from this middleware entirely: the browser returns
 * from Google's OAuth redirect without any Basic header, so gating it would
 * break Google sign-in whenever Basic auth is enabled.
 */
const PUBLIC_PATHS = [/^\/$/, /^\/favicon\.ico$/, /^\/assets\//];

// /api/logs is skipped by the matcher because the route enforces its own
// posture (public reads, authenticated writes). Everything else, including
// the 4s /api/generate job polling, goes through the gate below.
export async function middleware(request) {
  // Marketing page + brand assets stay public; everything else is gated.
  if (PUBLIC_PATHS.some((pattern) => pattern.test(request.nextUrl.pathname))) {
    return NextResponse.next();
  }

  if (!hasDashboardAccess(request)) {
    return new NextResponse('Authentication required', {
      status: 401,
      headers: unauthorizedHeaders(),
    });
  }

  const { pathname } = request.nextUrl;
  const isDashboard = pathname === '/dashboard' || pathname.startsWith('/dashboard/');
  if (isDashboard && !LOCAL_HOSTNAMES.has(requestHostname(request))) {
    let token = null;
    try {
      token = await getToken({ req: request, secret: process.env.NEXTAUTH_SECRET });
    } catch (err) {
      // Missing/undecodable session = anonymous = redirect to login.
      token = null;
    }
    if (!token) {
      const login = new URL('/login', request.url);
      const callbackUrl = pathname + (request.nextUrl.search || '');
      login.searchParams.set('callbackUrl', callbackUrl);
      return NextResponse.redirect(login);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    '/((?!api/health|api/auth|api/media|api/thumb|_next/static|_next/image|favicon.ico|api/logs).*)',
  ],
};

import { getServerSession } from 'next-auth';
import { findUser, isAdminEmail, normalizeEmail } from '@/lib/credits';
import { LOCAL_HOSTNAMES, requestHostname } from '@/lib/auth';
import { authOptions } from '@/lib/next-auth';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const NO_STORE = { 'Cache-Control': 'no-store' };

/**
 * Identity + balance for the dashboard header.
 *
 * On localhost the whole login system is bypassed (spec), so the caller is
 * presented as an unlimited admin instead of being asked to sign in.
 */
export async function GET(request) {
  const host = requestHostname(request);
  if (LOCAL_HOSTNAMES.has(host)) {
    return Response.json(
      {
        authenticated: true,
        email: String(process.env.ADMIN_EMAIL || '').trim() || 'localhost',
        isAdmin: true,
        credits: null,
        localhost: true,
      },
      { headers: NO_STORE }
    );
  }

  const session = await getServerSession(authOptions);
  const email = normalizeEmail(session?.user?.email);
  if (!email) {
    return Response.json({ authenticated: false }, { status: 401, headers: NO_STORE });
  }

  const user = findUser(email);
  return Response.json(
    {
      authenticated: true,
      email,
      isAdmin: isAdminEmail(email),
      // Admins are unlimited; report null so the UI never shows a bogus number.
      credits: isAdminEmail(email) ? null : (user ? user.credits : 0),
    },
    { headers: NO_STORE }
  );
}

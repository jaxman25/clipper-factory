/**
 * next-auth configuration (server-only; never imported by middleware).
 *
 * - Google sign-in appears only when GOOGLE_CLIENT_ID/SECRET are configured.
 * - Credentials = email + password against state/users.json. The first
 *   password sign-in registers the account with the free signup credits.
 * - JWT sessions; session.isAdmin is true when the email matches ADMIN_EMAIL,
 *   which is what lets the owner bypass the credit system entirely.
 */
import CredentialsProvider from 'next-auth/providers/credentials';
import GoogleProvider from 'next-auth/providers/google';
import {
  ensureUser,
  findUser,
  isAdminEmail,
  normalizeEmail,
  setPassword,
  verifyPassword,
} from './credits.js';

function buildProviders() {
  const providers = [];
  const googleId = String(process.env.GOOGLE_CLIENT_ID || '').trim();
  const googleSecret = String(process.env.GOOGLE_CLIENT_SECRET || '').trim();
  if (googleId && googleSecret) {
    providers.push(
      GoogleProvider({ clientId: googleId, clientSecret: googleSecret })
    );
  }
  providers.push(
    CredentialsProvider({
      id: 'credentials',
      name: 'Email and password',
      credentials: {
        email: { label: 'Email', type: 'email' },
        password: { label: 'Password', type: 'password' },
      },
      async authorize(credentials) {
        const email = normalizeEmail(credentials?.email);
        const password = String(credentials?.password || '');
        if (!email || !password) return null;

        const existing = findUser(email);
        if (existing) {
          // An account created via Google sign-in has no password; never
          // let a password login take it over.
          if (!existing.password_hash) return null;
          if (!verifyPassword(password, existing.password_hash)) return null;
          return { id: email, email, name: existing.name || email.split('@')[0] };
        }
        // First password sign-in registers the account (5 free credits come
        // from ensureUser inside the signIn callback below).
        ensureUser(email);
        setPassword(email, password);
        return { id: email, email, name: email.split('@')[0] };
      },
    })
  );
  return providers;
}

export const authOptions = {
  session: { strategy: 'jwt' },
  providers: buildProviders(),
  pages: {
    signIn: '/login',
    error: '/login',
  },
  callbacks: {
    // Runs for every provider: first sign-in anywhere creates the user with
    // the free credits (and never resets an existing balance).
    async signIn({ user }) {
      const email = normalizeEmail(user?.email);
      if (email) ensureUser(email);
      return true;
    },
    async jwt({ token, user }) {
      if (user?.email) token.email = normalizeEmail(user.email);
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.email = token.email || session.user.email;
        session.isAdmin = isAdminEmail(session.user.email);
      }
      return session;
    },
  },
};

/** Provider list for the login page (ids + display names only). */
export function publicProviders() {
  return authOptions.providers.map((provider) => ({
    id: provider.id,
    name: provider.name,
  }));
}

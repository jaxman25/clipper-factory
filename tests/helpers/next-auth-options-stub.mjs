/**
 * Test double for lib/next-auth.js.
 *
 * The route handlers only need `authOptions` and `publicProviders`; importing
 * the real module drags in the NextAuth provider packages, whose CJS/ESM
 * interop does not resolve outside Next's bundler. The stub keeps the route
 * under test honest: getServerSession is stubbed anonymously in the same test.
 */
export const authOptions = {};

export function publicProviders() {
  return [];
}

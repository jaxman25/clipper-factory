/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async redirects() {
    return [
      {
        source: '/settings',
        destination: '/dashboard/settings',
        permanent: false,
      },
    ];
  },
  experimental: {
    serverComponentsExternalPackages: ['archiver'],
  },
  async headers() {
    return [
      {
        // Suppress request logging for the dashboard's polling endpoints.
        // The frontend polls these every 20s (clips/health) and 4s (job
        // progress), which floods the terminal with request logs during
        // rendering. These are short-polling endpoints, so aggressive
        // client-side caching is safe and appropriate.
        source: '/api/generate/:path*',
        headers: [
          { key: 'Cache-Control', value: 'no-store, no-cache, must-revalidate, max-age=0' },
        ],
      },
      {
        source: '/api/logs/:path*',
        headers: [
          { key: 'Cache-Control', value: 'no-store, no-cache, must-revalidate, max-age=0' },
        ],
      },
    ];
  },
};

export default nextConfig;

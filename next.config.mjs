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
};

export default nextConfig;

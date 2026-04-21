import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  compress: true,
  eslint: {
    ignoreDuringBuilds: true
  },
  typescript: {
    ignoreBuildErrors: true
  },
  images: {
    // Skip Next.js image optimization entirely. Render's free plan lacks
    // the RAM to run the sharp-based optimizer at scale, and we mostly
    // serve pre-optimized Unsplash URLs. Images are loaded as-is.
    unoptimized: true,
    formats: ["image/avif", "image/webp"],
    remotePatterns: [
      { protocol: "https", hostname: "images.unsplash.com" },
      { protocol: "https", hostname: "cdn.immohorizon.com" }
    ]
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" }
        ]
      }
    ];
  },
  // Proxy all API calls through the same origin (immohorizon.com) so
  // the browser never needs to make a cross-origin request to the
  // Render backend. This eliminates CORS, ITP and onrender.com
  // network-level blocks that some ISPs / iOS builds apply.
  async rewrites() {
    const backend =
      process.env.BACKEND_URL ||
      process.env.NEXT_PUBLIC_API_BASE_URL ||
      "https://h2-0.onrender.com";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`
      }
    ];
  }
};

export default withNextIntl(nextConfig);

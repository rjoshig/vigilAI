/**
 * The /api/* rewrite proxy means the browser only ever talks to this origin, so there
 * is no CORS to configure against FastAPI (standards/frontend.md).
 */
const apiUrl = process.env.GREENLIGHT_AI_API_URL ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default nextConfig;

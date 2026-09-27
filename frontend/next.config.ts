import type { NextConfig } from "next";

// The browser only ever talks to this Next.js origin. /api/* is proxied to FastAPI so auth
// cookies stay first-party and no backend URL or secret reaches client code.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;

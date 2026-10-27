import type { NextConfig } from "next";

// Local development: proxy the relative /api/v1 calls made by src/lib/api.ts
// to the FastAPI backend. Override with BACKEND_URL if it runs elsewhere.
const backendUrl = process.env.BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${backendUrl}/api/v1/:path*` },
      { source: "/health", destination: `${backendUrl}/health` },
      { source: "/health/:path*", destination: `${backendUrl}/health/:path*` },
    ];
  },
};

export default nextConfig;

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://backend:8000"}/api/:path*`,
      },
    ];
  },
  webpack(config) {
    // Use $ for exact-match alias so "maplibre-gl/dist/maplibre-gl.css"
    // (and other subpath imports) are NOT affected by this alias.
    config.resolve.alias = {
      ...config.resolve.alias,
      "maplibre-gl$": "maplibre-gl/dist/maplibre-gl-dev.js",
    };
    return config;
  },
};

export default nextConfig;

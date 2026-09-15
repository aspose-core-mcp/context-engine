/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // Keep dev and production build artifacts isolated.
  // This prevents broken chunk references when `next build` is run while `next dev` is active.
  distDir: process.env.NODE_ENV === "development" ? ".next-dev" : ".next",
};

export default nextConfig;

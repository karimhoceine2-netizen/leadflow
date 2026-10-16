import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  distDir: process.env.LEADFLOW_E2E === "1" ? ".next-e2e" : ".next",
  outputFileTracingRoot: path.resolve(process.cwd()),
  poweredByHeader: false,
  devIndicators: false,
};
export default nextConfig;

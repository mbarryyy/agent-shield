import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  // Linting is a dedicated CI step (`npm run lint` in the ci.yml `console`
  // job); keep `next build` focused on build correctness so the two gates
  // fail independently and legibly.
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;

import type { NextConfig } from 'next';
import path from 'node:path';

const nextConfig: NextConfig = {
  // The backend lockfile belongs to another runtime, not a parent JS workspace.
  outputFileTracingRoot: path.resolve(__dirname),
};

export default nextConfig;

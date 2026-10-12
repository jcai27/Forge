import type { NextConfig } from 'next';
// The development badge sits over the bottom of the sidebar; errors are still shown without it.
const config: NextConfig = {distDir: process.env.NEXT_DIST_DIR ?? '.next', devIndicators: false};
export default config;

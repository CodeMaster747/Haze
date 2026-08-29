/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// One SPA build, two destinations:
//
//   `npm run build`       -> web/dist, copied into the Python wheel by
//                            `make build-web`, served by the agent from
//                            http://127.0.0.1:7433.  Talks to the real agent.
//   `npm run build:demo`  -> web/dist with VITE_HAZE_MODE=demo baked in,
//                            deployed to Firebase Hosting.  Runs an in-browser
//                            simulated cluster and makes zero network calls.
//
// Same components, same scheduler behaviour, different DataSource. See
// src/data/DataSource.ts.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  define: {
    // Baked at build time rather than read at runtime: the demo build must not
    // be able to fall back to hitting a local agent, and the agent build must
    // not ship simulation code paths that could be mistaken for real data.
    __HAZE_DEMO__: JSON.stringify(mode === 'demo'),
  },
  build: {
    // Firebase Hosting Spark allows 360 MB/day of transfer and disables the
    // site (rather than billing) when that is exceeded. At ~300 KB gzipped
    // that is roughly 1,200 cold visits/day, so bundle size is a real budget
    // here, not a vanity metric. This warns before it becomes a problem.
    chunkSizeWarningLimit: 400,
    sourcemap: mode !== 'demo',
  },
  server: { port: 5173, strictPort: false },
  test: {
    // The conformance suite reads a JSON corpus off disk, so it needs the
    // node environment rather than jsdom.
    environment: 'node',
    include: ['tests/**/*.test.ts', 'src/**/*.test.ts'],
  },
}));

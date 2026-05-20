/// <reference types="vitest" />
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Vitest test stack — closes the W3 G3-NOTE accept-as-tracked-debt
// (no-console-test-suite). Initial bootstrap: smoke tests under tests/;
// extended coverage and Playwright e2e land in the post-merge demo-capture
// pass (ADR-0013 C6).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});

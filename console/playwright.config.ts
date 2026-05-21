import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: {
    timeout: 7_500,
  },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:3210',
    locale: 'en-US',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev -- --hostname 127.0.0.1 --port 3210',
    url: 'http://127.0.0.1:3210',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:8787',
      NEXT_PUBLIC_GOV_RUN_ID: 'banking',
      NEXT_PUBLIC_GOV_WORKFLOW_ID: 'banking',
      NEXT_PUBLIC_SHIELD_AUTH_MODE: 'open',
    },
  },
});

// Explicit BODY09-only route: no Worker, D1, build, network install or retries.
// Execution still requires independent fixture review and a fresh authority/qualification receipt.
import {defineConfig, devices} from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: 'p04-catch-contrast.spec.ts',
  outputDir: '../test-results/p04-body09',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  maxFailures: 1,
  forbidOnly: true,
  timeout: 90_000,
  expect: {timeout: 10_000},
  reporter: [['list'], ['json', {outputFile: 'test-results/p04-body09-results.json'}]],
  use: {
    baseURL: 'http://p04-body09.test',
    locale: 'en-US', timezoneId: 'America/Los_Angeles',
    serviceWorkers: 'block',
    trace: 'retain-on-failure', screenshot: 'only-on-failure',
    // A qualified existing executable may be supplied; no search/download fallback.
    launchOptions: process.env.PW_CHROMIUM ? {executablePath: process.env.PW_CHROMIUM} : {},
  },
  projects: [
    {name: 'phone', use: {...devices['Desktop Chrome'], viewport: {width: 390, height: 844}, deviceScaleFactor: 1, isMobile: true, hasTouch: true}},
    {name: 'laptop', use: {...devices['Desktop Chrome'], viewport: {width: 1280, height: 800}, deviceScaleFactor: 1}},
  ],
});

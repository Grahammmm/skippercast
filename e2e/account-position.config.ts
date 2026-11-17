// Synthetic account dialog only: no Worker, seeded database, app feeds or product network.
import {defineConfig} from '@playwright/test';
export default defineConfig({
  testDir: '.', testMatch: 'v2-account-position.spec.ts', timeout: 30000, workers: 2, retries: 0,
  use: {baseURL: 'http://account.invalid', browserName: 'chromium', headless: true, serviceWorkers: 'block'},
  projects: [
    {name: 'phone', use: {viewport: {width: 390, height: 844}}},
    {name: 'laptop', use: {viewport: {width: 1280, height: 800}}},
  ],
});

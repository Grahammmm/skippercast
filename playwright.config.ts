// Browser tests (P4-09a): Playwright + axe against the built site served by
// `wrangler dev` (e2e/serve.mjs). Two viewports: a phone (390×844) and a
// laptop (1280×800). Run `pnpm build && pnpm e2e`.
//
// Browser: CI installs Playwright's Chromium (`npx playwright install
// chromium`). Where that download is not possible, set PW_CHROMIUM to a
// Chromium binary; if unset, an existing /opt/pw-browsers/chromium-*/ build
// is used when Playwright's own is missing (local sandboxes only).
import {existsSync, readdirSync} from 'node:fs';
import {defineConfig, devices} from '@playwright/test';

const port = process.env.E2E_PORT || '8787';
function localChromium(): string | undefined {
  if (process.env.PW_CHROMIUM) return process.env.PW_CHROMIUM;
  if (process.env.CI) return undefined;
  const dir = '/opt/pw-browsers';
  if (!existsSync(dir)) return undefined;
  const found = readdirSync(dir).filter(n => /^chromium-\d+$/.test(n)).sort().reverse()
    .map(n => `${dir}/${n}/chrome-linux/chrome`).find(p => existsSync(p));
  return found;
}
const executablePath = localChromium();

export default defineConfig({
  testDir: 'e2e',
  outputDir: 'test-results/e2e',
  fullyParallel: true,
  workers: process.env.CI ? 2 : 3,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: {timeout: 15_000},
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [['list'], ['github']] : [['list']],
  globalTeardown: './e2e/axe-summary.ts',
  use: {
    baseURL: `http://localhost:${port}`,
    timezoneId: 'America/Los_Angeles',
    locale: 'en-US',
    trace: 'retain-on-failure',
    // Service workers would answer requests the tests' routing cannot see;
    // only the offline test turns them on.
    serviceWorkers: 'block',
    screenshot: 'only-on-failure',
    launchOptions: executablePath ? {executablePath} : {},
  },
  projects: [
    {name: 'phone', use: {...devices['Desktop Chrome'], viewport: {width: 390, height: 844}, hasTouch: true, isMobile: true}},
    {name: 'laptop', use: {...devices['Desktop Chrome'], viewport: {width: 1280, height: 800}}},
  ],
  webServer: {
    command: 'node e2e/serve.mjs',
    url: `http://localhost:${port}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});

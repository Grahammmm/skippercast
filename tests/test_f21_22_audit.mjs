import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

// Stand in for Playwright only: the real driver still samples frames, applies
// its settle timeout and retry policy, and writes the gallery metadata.
function fakePlaywright() {
  let now = 0;
  Date.now = () => now;
  const loads = new Map();
  return {launch: async () => ({
    newPage: async () => ({evaluate: async (_diff, [a, b]) => ({changed: Number(a !== b)})}),
    newContext: async () => ({
      route() {}, addInitScript() {}, close() {},
      newPage() {
        let frames;
        return {
          clock: {setFixedTime() {}}, on() {}, async waitForLoadState() {}, evaluate: () => true, title: () => 'Synthetic',
          async goto(path) {
            const load = (loads.get(path) ?? 0) + 1;
            loads.set(path, load);
            const changes = path === '/never' || (path === '/late' && load === 1) || (path === '/lost' && load > 1);
            const last = path === '/disagree' ? String(load) : 'B';
            frames = [changes ? 'A' : last, last];
            return {status: () => 200};
          },
          waitForTimeout(ms) { now += ms; },
          screenshot: () => Buffer.from(frames.shift()),
        };
      },
    }),
    close() {},
  })};
}

test('capture metadata requires two consecutive settled loads that agree', () => {
  const dir = mkdtempSync(join(tmpdir(), 'showcase-settle-'));
  try {
    const hook = join(dir, 'playwright-stub.mjs');
    const stub = `export const chromium = (${fakePlaywright})();`;
    writeFileSync(hook, `import {registerHooks} from 'node:module';
registerHooks({resolve(id, context, next) {
  if (id === '@playwright/test') return {shortCircuit: true, url: ${JSON.stringify(`data:text/javascript,${encodeURIComponent(stub)}`)}};
  return next(id, context);
}});`);
    const job = join(dir, 'job.json');
    writeFileSync(job, JSON.stringify({
      base_url: 'http://example.invalid', now: '2026-01-01T00:00:00Z', out_dir: dir,
      pages: ['never', 'late', 'lost', 'disagree', 'steady'].map(id => ({id, path: `/${id}`, settle_ms: 0, max_settle_ms: 400})),
    }));
    const driver = fileURLToPath(new URL('../scripts/showcase_capture.mjs', import.meta.url));
    execFileSync(process.execPath, ['--import', hook, driver, job], {timeout: 10_000});
    const rows = JSON.parse(readFileSync(join(dir, 'results.json'), 'utf8'));
    assert.deepEqual(rows.map(({id, status, settled, steady, loads}) => [id, status, settled, steady, loads]), [
      ['never', 'ok', false, false, 4],     // All final frames match; every load times out changing A to B.
      ['late', 'ok', true, true, 3],        // An unsettled first load cannot vote, but later settled ones can.
      ['lost', 'ok', false, false, 4],      // A settled first load cannot agree with an unsettled second one.
      ['disagree', 'ok', true, false, 4],   // Settling alone does not prove agreement between loads.
      ['steady', 'ok', true, true, 2],
    ]);
    assert.equal(readFileSync(join(dir, 'never.png'), 'utf8'), 'B'); // Keep the unsteady image for review.
  } finally {
    rmSync(dir, {recursive: true, force: true});
  }
});

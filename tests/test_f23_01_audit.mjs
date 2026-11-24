import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {posix} from 'node:path';
import {test} from 'node:test';

const workflow = readFileSync(new URL('../.github/workflows/research-substrate.yml', import.meta.url), 'utf8');
const cache = 'var/noaa-native-cache';
const archives = new Set([
  'coast-seafloor-inventory', 'csumb-scc-source-leads', 'csumb-bss-source-leads', 'sources', 'surveys',
].flatMap(name => {
  // Take the original archive basenames from committed metadata, never the cache.
  const metadata = readFileSync(new URL(`../catalog/${name}.json`, import.meta.url), 'utf8');
  return metadata.match(/[\w.-]+_additional_products\.tar\.gz\b/g) ?? [];
}));

function transportPaths(text, action) {
  // This workflow uses literal single paths or indented multiline path lists.
  const lines = [];
  for (const step of text.split(/^      - /m)) {
    const used = step.match(/^(?: {8})?uses: ([^@\s]+)@/m)?.[1];
    if (used !== action && !used?.startsWith(`${action}/`)) continue;
    const path = step.match(/^          path: ([^\n]+)((?:\n {12}[^\n]+)*)/m);
    assert.ok(path, `${action} must declare its path`);
    const patterns = (path[1] === '|' ? path[2] : path[1]).trim().split(/\n\s*/);
    for (const pattern of patterns) {
      assert.match(pattern, /^[\w./*-]+$/, `unmodeled ${action} path: ${pattern}`);
      lines.push(pattern);
    }
  }
  return lines;
}

function assertNoHeldTransport(text, action) {
  assert.ok(archives.size, 'the reviewed archive-name inventory must not be empty');
  const selected = transportPaths(text, action);
  for (const selection of selected) {
    const pattern = posix.normalize(selection).replace(/\/$/, '');
    for (const archive of archives) {
      const file = `${cache}/${archive}`;
      // Both actions transport descendants when a directory itself matches.
      for (let path = file; ; path = posix.dirname(path)) {
        assert.ok(!posix.matchesGlob(path, pattern), `${action} selects held archive via ${selection}: ${file}`);
        if (path === '.') break;
      }
    }
  }
}

for (const action of ['actions/cache', 'actions/upload-artifact']) {
  test(`${action} selects no licence-held original`, () => assertNoHeldTransport(workflow, action));
  test(`${action} rejects recursive and real-name archive selections while permitting receipts`, () => {
    const step = path => `      - uses: ${action}@synthetic\n        with:\n          path: ${path}\n`;
    // A leaf-only check misses directories; a placeholder inventory misses scoped selections.
    for (const unsafe of ['.', `${cache}/`, 'var/noaa-*', `${cache}/SCC_Block04_*.tar.gz`]) {
      assert.throws(() => assertNoHeldTransport(step(unsafe), action), /selects held archive via/);
    }
    assertNoHeldTransport(step('var/review/csumb-scc-source-leads.json'), action);
  });
}

test('public CI only checks committed receipts and records the hold, without a private runner', () => {
  const job = workflow.match(/^  csumb-native:\n((?:^(?: {4}[^\n]*|)\n)+)/m);
  assert.ok(job, 'the hold must remain visible in the workflow');
  const [header, ...steps] = job[1].split(/^      - /m);
  // SC-CI-OC1 chains the research jobs with `needs:`/`if: ${{ !cancelled() }}` to cap
  // parallelism; ordering lines are allowed, but the runner, timeout and steps stay pinned
  // (a `runs-on:` change to a private runner still fails this check).
  assert.deepEqual(header.split('\n').map(line => line.trim())
    .filter(line => line && !line.startsWith('#') && !/^(needs|if): /.test(line)),
  ['runs-on: ubuntu-latest', 'timeout-minutes: 45', 'steps:']);
  // Allowlist, not a denylist: any fetch, cache, artifact or audit-script step
  // added here would turn this back into an off-box processing job.
  const allowed = [
    /^uses: actions\/checkout@[0-9a-f]{40} # \S+\n$/,
    /^uses: actions\/setup-python@[0-9a-f]{40} # \S+\n {8}with:\n {10}python-version: "3\.12"\n$/,
    /^name: Install pinned native-grid reader\n {8}run: python -m pip install -r requirements-survey\.txt\n$/,
    /^name: Verify native-grid receipts stay out of fishing targets\n {8}env:\n {10}PYTHONPATH: src:\.\n {8}run: python -m unittest(?: research\.tests\.[\w.]+)+ -v\n$/,
    /^name: Report licence hold \(SCA-137\)\n {8}run: \|\n {10}printf '%s\\n' 'SCA-137: CSUMB native survey processing skipped; no approved private runner or storage route\.' >> "\$GITHUB_STEP_SUMMARY"\n$/,
  ];
  assert.equal(steps.length, allowed.length);
  steps.forEach((step, index) => assert.match(step, allowed[index]));
});

test('the permit for coordinate-free source-use receipts is unaffected', () => {
  assert.match(workflow, /python research\/scripts\/audit_csumb_source_policy\.py\s+--output var\/review\/csumb-original-source-policy-review\.json\s+--verify research\/receipts\/csumb-original-source-policy-review\.json/);
  // A legitimate source-lead report still has an upload path, so the exclusion
  // above is not a consequence of an empty or broken path scanner.
  assert.ok(transportPaths(workflow, 'actions/upload-artifact').some(pattern =>
    posix.matchesGlob('var/review/csumb-scc-source-leads.json', pattern)));
});

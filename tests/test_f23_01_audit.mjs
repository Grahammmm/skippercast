import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {matchesGlob} from 'node:path';
import {test} from 'node:test';

const workflow = readFileSync(new URL('../.github/workflows/research-substrate.yml', import.meta.url), 'utf8');

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

for (const action of ['actions/cache', 'actions/upload-artifact']) {
  test(`${action} selects no synthetic licence-held original`, () => {
    const selected = transportPaths(workflow, action);
    for (const archive of ['SCC_Block99', 'BSS_Block99', 'BigCreek']) {
      const file = `var/noaa-native-cache/${archive}_additional_products.tar.gz`;
      assert.deepEqual(selected.filter(pattern => matchesGlob(file, pattern)), [], file);
    }
  });
}

test('public CI can only record the hold, even without private runner configuration', () => {
  const job = workflow.match(/^  csumb-native:\n((?:^(?: {4}[^\n]*|)\n)+)/m);
  assert.ok(job, 'the hold must remain visible in the workflow');
  // A checkout, fetch, or artifact step here would turn this back into a processing job.
  assert.deepEqual(job[1].split('\n').map(line => line.trim()).filter(line => line && !line.startsWith('#')), [
    'runs-on: ubuntu-latest',
    'steps:',
    '- name: Report licence hold (SCA-137)',
    'run: |',
    'printf \'%s\\n\' \'SCA-137: CSUMB native survey processing skipped; no approved private runner or storage route.\' >> "$GITHUB_STEP_SUMMARY"',
  ]);
});

test('the permit for coordinate-free source-use receipts is unaffected', () => {
  assert.match(workflow, /python research\/scripts\/audit_csumb_source_policy\.py\s+--output var\/review\/csumb-original-source-policy-review\.json\s+--verify research\/receipts\/csumb-original-source-policy-review\.json/);
  // A legitimate source-lead report still has an upload path, so the exclusion
  // above is not a consequence of an empty or broken path scanner.
  assert.ok(transportPaths(workflow, 'actions/upload-artifact').some(pattern =>
    matchesGlob('var/review/csumb-scc-source-leads.json', pattern)));
});

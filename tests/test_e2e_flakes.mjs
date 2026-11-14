import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, writeFileSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve, join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {registry, policy, quarantine, measure, nightly, markdown} from '../scripts/e2e-flakes.mjs';

const header = 'spec\tfirst_seen\towner\texpiry\ttest\n';
const rows = registry(header + 'e2e/example.spec.ts\t2030-01-01\t@owner\t2030-01-16\tknown flake\n');
const row = rows[0];
const empty = () => ({days: {}, expired: {}});
const result = (status = 'passed', retry = 0) => ({status, retry});
function reports(day = '2030-01-01', change = t => t) {
  return ['phone', 'laptop'].map((projectName, i) => ({
    config: {argv: ['node', 'cli', 'test', `--shard=${i + 1}/2`], shard: {current: i + 1, total: 2}}, errors: [], stats: {startTime: `${day}T09:00:00Z`},
    suites: [{suites: [{specs: [{file: 'example.spec.ts', title: 'known flake', tests: [change({
      projectName, expectedStatus: 'passed', status: 'expected', results: [result()],
    }, i)]}]}]}],
  }));
}
test('quarantine rows require ownership, real dates, one row/spec and a bounded expiry', () => {
  for (const cells of [
    ['e2e/example.spec.ts', '2030-02-30', '@owner', '2030-03-02', 'test'],
    ['e2e/example.spec.ts', '2030-01-01', '', '2030-01-16', 'test'],
    ['../example.spec.ts', '2030-01-01', '@owner', '2030-01-16', 'test'],
    ['e2e/example.spec.ts', '2030-01-01', '@owner', '2030-01-17', 'test'],
    ['e2e/example.spec.ts', '2030-01-01', '@owner', '2030-01-01', 'test'],
  ]) assert.throws(() => registry(header + cells.join('\t')));
  assert.throws(() => registry(header + row.key + '\n' + row.key));
  assert.throws(() => registry('spec\towner\n'));
  assert.throws(() => quarantine('e2e/unregistered.spec.ts'), /requires a flaky.tsv row/);
  assert.deepEqual(policy(row, empty(), '2030-01-15'), {tag: ['@flaky'], retries: 2});
  assert.deepEqual(policy(row, empty(), '2030-01-16'), {tag: [], retries: 0});
  assert.deepEqual(policy(row, empty(), '2029-12-31'), {tag: [], retries: 0});
});
test('JSON accounting separates first-pass, retry recovery, failure, skip and unknown denominator', () => {
  const input = reports();
  input[0].suites[0].suites[0].specs.push({file: 'example.spec.ts', title: 'recovery', tests: [
    {expectedStatus: 'passed', status: 'flaky', results: [result('failed'), result('passed', 1)]},
    {expectedStatus: 'passed', status: 'unexpected', results: [result('timedOut')]},
    {expectedStatus: 'skipped', status: 'skipped', results: [result('skipped')]},
  ]});
  input[0].suites[0].suites[0].specs.push({file: 'skipped.spec.ts', title: 'disabled', tests: [
    {expectedStatus: 'skipped', status: 'skipped', results: [result('skipped')]},
  ]});
  const m = measure(input, rows);
  assert.equal(m.complete, true);
  assert.deepEqual({...m.specs[row.spec], target_projects: []}, {
    executed: 4, flaky: 1, failed: 1, skipped: 1, first_attempt_failed: 2,
    target_projects: [], target_green: true, flake_rate: 0.25,
  });
  assert.equal(m.specs['e2e/skipped.spec.ts'].flake_rate, null);
  assert.match(markdown({day: '2030-01-01', active: [row.spec], ...m}), /25\.00%/);
});
test('14 distinct consecutive fully green UTC nights remove effective tag and retries, not assertions', () => {
  let state = empty(), report;
  for (let d = 1; d <= 14; d++) {
    const day = `2030-01-${String(d).padStart(2, '0')}`;
    ({state, report} = nightly(reports(day), rows, state, day));
    assert.equal(report.specs[row.spec].green_days, d);
    assert.equal(report.active.length, d === 14 ? 0 : 1);
  }
  assert.equal(state.expired[row.key], '2030-01-14');
  assert.deepEqual(policy(row, state, '2030-01-15'), {tag: [], retries: 0});
  // Duplicate same-day processing never earns a second day.
  const repeat = nightly(reports('2030-01-14'), rows, state, '2030-01-14');
  assert.equal(repeat.report.specs[row.spec].green_days, 14);
});
test('a failing rerun on the 14th green date voids the streak expiry; the hard deadline stays', () => {
  let state = empty();
  for (let d = 1; d <= 14; d++) {
    const day = `2030-01-${String(d).padStart(2, '0')}`;
    ({state} = nightly(reports(day), rows, state, day));
  }
  assert.equal(state.expired[row.key], '2030-01-14');
  const bad = reports('2030-01-14'); bad[1].suites = [];
  let report;
  ({state, report} = nightly(bad, rows, state, '2030-01-14'));
  assert.equal(state.days['2030-01-14'][row.key], false);
  assert.equal(report.specs[row.spec].green_days, 0);
  assert.equal(state.expired[row.key], undefined);
  assert.deepEqual(policy(row, state, '2030-01-14'), {tag: ['@flaky'], retries: 2});
  // A later green rerun cannot restore the broken date either.
  ({state} = nightly(reports('2030-01-14'), rows, state, '2030-01-14'));
  assert.equal(state.expired[row.key], undefined);
  // An expiry latched on an earlier date survives a later failure.
  const earlier = {days: structuredClone(state.days), expired: {[row.key]: '2030-01-14'}};
  const later = reports('2030-01-15'); later[1].suites = [];
  assert.equal(nightly(later, rows, earlier, '2030-01-15').state.expired[row.key], '2030-01-14');
  // The hard deadline still expires it on a failing night.
  const hardBad = reports('2030-01-16'); hardBad[1].suites = [];
  assert.equal(nightly(hardBad, rows, empty(), '2030-01-16').state.expired[row.key], '2030-01-16');
  assert.equal(nightly(hardBad, rows, {days: {}, expired: {[row.key]: '2030-01-16'}}, '2030-01-16').state.expired[row.key], '2030-01-16');
});
test('failure, recovery, skip, missing target/project/shard and global errors break green credit', () => {
  const mutations = [
    r => { r.pop(); },
    r => { r[1] = structuredClone(r[0]); },
    r => { r[1].config.shard.current = 3; },
    r => { r[1].config.argv.push('--grep', 'known flake'); },
    r => { r[1].stats.startTime = '2030-01-01T09:00:00Z'; },
    r => { r[1].suites = []; },
    r => { r[1].errors = [{message: 'worker interrupted'}]; },
    r => { r[1].suites[0].suites[0].specs[0].title = 'different case'; },
    r => { Object.assign(r[1].suites[0].suites[0].specs[0].tests[0], {status: 'flaky', results: [result('failed'), result('passed', 1)]}); },
    r => { Object.assign(r[1].suites[0].suites[0].specs[0].tests[0], {status: 'skipped', results: [result('skipped')]}); },
    r => { Object.assign(r[1].suites[0].suites[0].specs[0].tests[0], {status: 'unexpected', results: [result('failed')]}); },
  ];
  for (const mutate of mutations) {
    let {state} = nightly(reports(), rows, empty(), '2030-01-01');
    const r = reports('2030-01-02'); mutate(r);
    ({state} = nightly(r, rows, state, '2030-01-02'));
    assert.equal(state.days['2030-01-02'][row.key], false);
    // A same-day successful rerun must not erase the failure.
    ({state} = nightly(reports('2030-01-02'), rows, state, '2030-01-02'));
    assert.equal(state.days['2030-01-02'][row.key], false);
    assert.equal(nightly(reports('2030-01-03'), rows, state, '2030-01-03').report.specs[row.spec].green_days, 1);
  }
  const first = nightly(reports(), rows, empty(), '2030-01-01');
  assert.equal(nightly(reports('2030-01-03'), rows, first.state, '2030-01-03').report.specs[row.spec].green_days, 1);
});
test('the shard total comes from the reports: all four shards are complete, a partial set is not', () => {
  const shards = (total = 4) => Array.from({length: total}, (_, i) => {
    const r = structuredClone(reports()[Math.min(i, 1)]);
    if (i > 1) r.suites = [];
    r.config = {argv: ['node', 'cli', 'test', `--shard=${i + 1}/${total}`], shard: {current: i + 1, total}};
    return r;
  });
  assert.equal(measure(shards(), rows).complete, true);
  assert.equal(nightly(shards(), rows, empty(), '2030-01-01').report.specs[row.spec].green_days, 1);
  for (const mutate of [
    r => { r.pop(); },
    r => { r.splice(2); },
    r => { r[3] = structuredClone(r[2]); },
    r => { r[3].config.shard.total = 5; },
    r => { r[3].config.argv[3] = '--shard=4/2'; },
  ]) {
    const r = shards(); mutate(r);
    assert.equal(measure(r, rows).complete, false);
  }
  assert.equal(measure([], rows).complete, false);
});
test('real Playwright execution: only tagged tests retry twice; persistent failures still fail', () => {
  const dir = mkdtempSync(join(tmpdir(), 'sc-ci-3-'));
  try {
    const output = join(dir, 'run.json');
    const pw = resolve('node_modules/@playwright/test/index.mjs');
    const active = policy(row, empty(), '2030-01-01');
    const expired = policy(row, empty(), '2030-01-16');
    writeFileSync(join(dir, 'playwright.config.mjs'), `export default {testDir: ${JSON.stringify(dir)}, outputDir: ${JSON.stringify(join(dir, 'results'))}, retries: 0, workers: 1, reporter: [['json', {outputFile: ${JSON.stringify(output)}}]]};`);
    writeFileSync(join(dir, 'policy.spec.mjs'), `import {test, expect} from ${JSON.stringify(pw)};
      test.describe('quarantine', {tag: ${JSON.stringify(active.tag)}}, () => {
        test.describe.configure({retries: ${active.retries}});
        test('recovers', async ({}, info) => { expect(info.retry).toBe(2); });
        test('still broken', async () => { expect(false).toBe(true); });
      });
      test.describe('expired', {tag: ${JSON.stringify(expired.tag)}}, () => {
        test.describe.configure({retries: ${expired.retries}});
        test('expired failure', async () => { expect(false).toBe(true); });
      });
      test('ordinary failure', async ({}, info) => { expect(info.retry).toBe(0); expect(false).toBe(true); });`);
    const run = spawnSync('pnpm', ['exec', 'playwright', 'test', '--config', join(dir, 'playwright.config.mjs')], {encoding: 'utf8', timeout: 60_000});
    assert.equal(run.status, 1, run.stderr);
    const json = JSON.parse(readFileSync(output, 'utf8'));
    const specs = json.suites[0].suites.flatMap(s => s.specs).concat(json.suites[0].specs);
    const get = title => specs.find(s => s.title === title).tests[0];
    assert.equal(get('recovers').status, 'flaky');
    assert.equal(get('recovers').results.length, 3);
    assert.equal(get('still broken').status, 'unexpected');
    assert.equal(get('still broken').results.length, 3);
    assert.equal(get('ordinary failure').results.length, 1);
    assert.equal(get('expired failure').results.length, 1);
    assert.deepEqual(specs.find(s => s.title === 'expired failure').tags, []);
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

test('production discovery tags only the registered case, in both original projects', () => {
  const run = spawnSync('pnpm', ['exec', 'playwright', 'test', '--list', '--reporter=json'], {encoding: 'utf8', timeout: 60_000, maxBuffer: 5_000_000});
  assert.equal(run.status, 0, run.stderr);
  const json = JSON.parse(run.stdout), tagged = [];
  function walk(suites) {
    for (const suite of suites) {
      for (const spec of suite.specs ?? []) if (spec.tags.some(t => t.replace(/^@/, '') === 'flaky')) tagged.push(spec);
      walk(suite.suites ?? []);
    }
  }
  walk(json.suites);
  const admitted = registry()[0];
  assert.equal(tagged.length, quarantine(admitted.spec).retries ? 1 : 0);
  for (const spec of tagged) {
    assert.equal(spec.title, admitted.test);
    assert.equal(spec.file, admitted.spec.replace(/^e2e\//, ''));
    assert.deepEqual(spec.tests.map(t => t.projectName).sort(), ['laptop', 'phone']);
  }
  assert.ok(json.config.projects.every(p => p.retries === 0));
});

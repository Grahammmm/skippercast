// SC-CI-3: registry, effective tag policy and nightly JSON accounting. No network or source writes.
import {existsSync, readFileSync, mkdirSync, writeFileSync, appendFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

export const STATE = 'test-results/quarantine-state.json';
const DAY = 86_400_000;
const today = () => new Date().toISOString().slice(0, 10);
function date(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || new Date(value).toISOString().slice(0, 10) !== value) throw Error(`Invalid date: ${value}`);
  return value;
}
export function registry(text = readFileSync('e2e/flaky.tsv', 'utf8')) {
  const [header, ...lines] = text.trimEnd().split('\n');
  if (header !== 'spec\tfirst_seen\towner\texpiry\ttest') throw Error('flaky.tsv header must be spec, first_seen, owner, expiry, test');
  const seen = new Set();
  return lines.map(line => {
    const cells = line.split('\t');
    if (cells.length !== 5) throw Error('flaky.tsv requires five nonempty columns');
    const [spec, first_seen, owner, expiry, test] = cells;
    if (!/^e2e\/[\w-]+\.spec\.ts$/.test(spec) || !owner.trim() || !test.trim() || seen.has(spec)) throw Error(`Invalid/duplicate quarantine: ${spec}`);
    seen.add(spec);
    date(first_seen); date(expiry);
    if (expiry <= first_seen || Date.parse(expiry) - Date.parse(first_seen) > 15 * DAY) throw Error(`Quarantine deadline exceeds 15 days: ${spec}`);
    return {spec, first_seen, owner, expiry, test, key: line};
  });
}
export function readState(path = STATE) {
  if (!existsSync(path)) return {days: {}, expired: {}};
  const state = JSON.parse(readFileSync(path, 'utf8'));
  if (state.version !== 1 || !state.days || !state.expired) throw Error('Invalid quarantine history');
  return state;
}
export function policy(row, state, day = today()) {
  date(day);
  const active = day >= row.first_seen && day < row.expiry && !state.expired[row.key];
  return {tag: active ? ['@flaky'] : [], retries: active ? 2 : 0};
}
export function quarantine(spec) {
  const row = registry().find(row => row.spec === spec);
  if (!row) throw Error(`@flaky requires a flaky.tsv row: ${spec}`);
  return policy(row, readState());
}

// Playwright JSON suites nest file -> describe -> specs -> project-specific tests.
export function measure(reports, rows) {
  const specs = {};
  const targets = new Map(rows.map(row => [row.spec, row]));
  let complete = reports.length === 2 && reports.every(r => Array.isArray(r.suites) && r.stats && !r.errors?.length);
  function walk(suites) {
    for (const suite of suites) {
      for (const spec of suite.specs ?? []) {
        const file = 'e2e/' + spec.file.replace(/^.*?(?:e2e\/)/, '').replace(/^e2e\//, '');
        const m = specs[file] ??= {executed: 0, flaky: 0, failed: 0, skipped: 0, first_attempt_failed: 0, target_projects: [], target_green: true};
        for (const t of spec.tests) {
          const results = t.results ?? [];
          const skipped = results.length && results.every(r => r.status === 'skipped');
          const green = t.expectedStatus === 'passed' && t.status === 'expected' && results.length === 1 && results[0].status === 'passed';
          if (skipped) m.skipped++;
          else {
            m.executed++;
            if (t.status === 'flaky') m.flaky++;
            if (t.status !== 'expected' && t.status !== 'flaky') m.failed++;
            if (!green) m.first_attempt_failed++;
          }
          if (targets.get(file)?.test === spec.title) {
            m.target_projects.push(t.projectName);
            m.target_green &&= green;
          }
        }
      }
      walk(suite.suites ?? []);
    }
  }
  for (const report of reports) walk(report.suites ?? []);
  for (const m of Object.values(specs)) m.flake_rate = m.executed ? m.flaky / m.executed : null;
  // Each shard reports its identity; duplicate/partial files cannot earn a green day.
  complete &&= reports.map(r => r.config?.shard?.current).sort().join(',') === '1,2' && reports.every(r => r.config?.shard?.total === 2);
  // Match the workflow's full-suite invocation; --grep/file/project smoke runs
  // must not be mistaken for a complete nightly, even with both shard numbers.
  complete &&= reports.every(r => r.config.argv?.slice(2).join(' ') === `test --shard=${r.config.shard.current}/2`);
  return {complete, specs};
}
export function nightly(reports, rows, previous, day = today()) {
  date(day);
  const measured = measure(reports, rows), specs = measured.specs;
  // Old artifacts and a run straddling UTC dates are not a new green night.
  const complete = measured.complete && reports.every(r => r.stats.startTime?.slice(0, 10) === day);
  const days = structuredClone(previous.days), expired = {...previous.expired};
  days[day] ??= {};
  for (const row of rows) {
    const m = specs[row.spec];
    const projects = m?.target_projects ?? [];
    const green = complete && !!m && m.target_green && projects.length === 2 && projects.includes('phone') && projects.includes('laptop') && m.first_attempt_failed === 0;
    // A failed earlier attempt/night on this UTC date cannot be overwritten by a rerun.
    days[day][row.key] = (days[day][row.key] ?? true) && green;
    let streak = 0;
    for (let t = Date.parse(day); t >= Date.parse(row.first_seen) && days[new Date(t).toISOString().slice(0, 10)]?.[row.key] === true; t -= DAY) streak++;
    const hard = day >= row.expiry;
    // A streak expiry latched earlier on this UTC date is void if a failing rerun breaks the
    // streak; the hard deadline and expiries latched on earlier dates stay.
    if (!hard && streak < 14 && expired[row.key] === day) delete expired[row.key];
    if (streak >= 14 || hard) expired[row.key] ??= day;
    if (m) m.green_days = streak;
  }
  for (const d of Object.keys(days)) if (Date.parse(day) - Date.parse(d) > 30 * DAY) delete days[d];
  const state = {version: 1, days, expired};
  return {state, report: {day, complete, active: rows.filter(r => policy(r, state, day).retries === 2).map(r => r.spec), specs}};
}
export function markdown(report) {
  return `## Nightly e2e flake rates (${report.day}, ${report.complete ? 'complete' : 'INCOMPLETE — no green credit'})\n\nActive quarantines: ${report.active.length}\n\n` +
    '| Spec | Executed | Recovered flakes | Final failures | Skipped | Flake rate | Green days |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: |\n' +
    Object.entries(report.specs).sort().map(([file, m]) => `| ${file} | ${m.executed} | ${m.flaky} | ${m.failed} | ${m.skipped} | ${m.flake_rate === null ? 'unknown' : (100 * m.flake_rate).toFixed(2) + '%'} | ${m.green_days ?? '—'} |`).join('\n') + '\n';
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const reports = process.argv.slice(2).filter(existsSync).map(p => JSON.parse(readFileSync(p, 'utf8')));
  const {state, report} = nightly(reports, registry(), readState());
  mkdirSync(dirname(STATE), {recursive: true});
  writeFileSync(STATE, JSON.stringify(state, null, 2) + '\n');
  writeFileSync('test-results/flake-rates.json', JSON.stringify(report, null, 2) + '\n');
  const md = markdown(report);
  writeFileSync('test-results/flake-rates.md', md);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, md);
  console.log(md);
  if (!report.complete) process.exitCode = 1;
}

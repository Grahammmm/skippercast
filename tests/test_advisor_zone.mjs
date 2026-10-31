// The text advisor's one default time zone (RF1140-6): answers/time.ts PACIFIC is the
// only 'America/Los_Angeles' code literal in server/advisor/, cron.ts DEFAULT_TZ is the
// same value, a region's zone is still preferred, and the DST fall-back hour is pinned.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {PACIFIC, localDate, localParts} = await import('../server/advisor/answers/time.ts');
const {DEFAULT_TZ} = await import('../server/advisor/cron.ts');
const {boatToday} = await import('../server/advisor/intake/reports.ts');
const {reportEvidence} = await import('../server/advisor/answers/confidence.ts');

const ZONE = 'America/' + 'Los_Angeles';
const isComment = line => /^\s*(\/\/|\*|\/\*)/.test(line);
const codeLines = text => text.split('\n').map((line, i) => [i + 1, line]).filter(([, line]) => line.includes(ZONE) && !isComment(line)).map(([n]) => n);
const root = new URL('../server/advisor/', import.meta.url);
const tsFiles = readdirSync(root, {recursive: true}).filter(f => f.endsWith('.ts')).map(f => f.split('\\').join('/'));

test('the matcher flags a code literal and skips comment lines', () => {
  const sample = [`const tz = x ?? '${ZONE}';`, `// today (${ZONE})`, ` * in ${ZONE}`, `/* ${ZONE} */`, 'const y = 1;'].join('\n');
  assert.deepEqual(codeLines(sample), [1]);
});

test('answers/time.ts holds the only America/Los_Angeles code literal in server/advisor', () => {
  assert.ok(tsFiles.includes('answers/time.ts') && tsFiles.includes('cron.ts'));
  const hits = tsFiles.filter(f => f !== 'answers/time.ts').flatMap(f => codeLines(readFileSync(new URL(f, root), 'utf8')).map(n => `${f}:${n}`));
  assert.deepEqual(hits, []);
  assert.deepEqual(codeLines(readFileSync(new URL('answers/time.ts', root), 'utf8')).length, 1);
});

test('cron DEFAULT_TZ is the PACIFIC constant', () => {
  assert.equal(PACIFIC, ZONE);
  assert.equal(DEFAULT_TZ, PACIFIC);
});

test('a known region zone is used; unknown or missing regions keep PACIFIC', () => {
  const t = Date.UTC(2026, 6, 15, 6, 30);   // 23:30 PDT on 2026-07-14, already the 15th in UTC
  const pacific = localDate(t, PACIFIC);
  assert.equal(pacific, '2026-07-14');
  assert.equal(boatToday({region: 'morro-bay'}, t), pacific);
  assert.equal(boatToday({region: 'no-such-region'}, t), pacific);
  assert.equal(boatToday(null, t), pacific);
  assert.notEqual(localDate(t, 'UTC'), pacific);
  assert.deepEqual(reportEvidence(null, 'x', t), reportEvidence(null, 'x', t, null, PACIFIC));
});

test('the fall-back hour: 01:30 PDT and 01:30 PST are both 1 a.m. on 2026-11-01', () => {
  for (const t of [Date.UTC(2026, 10, 1, 8, 30), Date.UTC(2026, 10, 1, 9, 30)]) {
    const p = localParts(t);
    assert.equal(p.date, '2026-11-01');
    assert.equal(p.hour, 1);
  }
});

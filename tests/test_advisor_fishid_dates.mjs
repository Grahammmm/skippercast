// Rules replies never state a calendar date that does not exist (RF1300-17,
// server/advisor/answers/fishid.ts monthDay): MM-DD allows the month's longest
// length (Feb 29 for a recurring season), YYYY-MM-DD the real calendar with
// leap years; any other day is shown exactly as written. Offline, synthetic
// rule rows only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const F = await import('../server/advisor/answers/fishid.ts');

const row = (open, close) => ({size_min_in: null, size_max_in: null, bag_limit: 5, season_open: open, season_close: close, depth_limit_ft: null});

test('real days still read as a month name and day, in both languages', () => {
  assert.equal(F.monthDay('04-01', 'en'), 'Apr 1');
  assert.equal(F.monthDay('04-01', 'es'), '1 abr');
  assert.equal(F.monthDay('2026-12-31', 'en'), 'Dec 31');
  assert.equal(F.monthDay('2026-12-31', 'es'), '31 dic');
  assert.equal(F.monthDay('04-30', 'en'), 'Apr 30');
  assert.equal(F.monthDay('01-31', 'es'), '31 ene');
  assert.equal(F.monthDay('2026-11-30', 'en'), 'Nov 30');
});

test('a day past the end of its month is returned as written (en and es)', () => {
  for (const d of ['02-31', '04-31', '06-45', '11-31', '02-30', '09-31', '2026-04-31', '2026-06-31', '2026-01-32']) {
    assert.equal(F.monthDay(d, 'en'), d, `en ${d}`);
    assert.equal(F.monthDay(d, 'es'), d, `es ${d}`);
  }
});

test('Feb 29: allowed for a recurring MM-DD and in a leap year, written as-is otherwise', () => {
  assert.equal(F.monthDay('02-29', 'en'), 'Feb 29');
  assert.equal(F.monthDay('02-29', 'es'), '29 feb');
  assert.equal(F.monthDay('2024-02-29', 'en'), 'Feb 29');
  assert.equal(F.monthDay('2000-02-29', 'es'), '29 feb');
  assert.equal(F.monthDay('2026-02-29', 'en'), '2026-02-29');
  assert.equal(F.monthDay('2026-02-29', 'es'), '2026-02-29');
  assert.equal(F.monthDay('2100-02-29', 'en'), '2100-02-29');
  assert.equal(F.monthDay('2026-02-28', 'en'), 'Feb 28');
});

test('month 00/13, day 00, empty and non-dates keep today\'s fallback', () => {
  for (const d of ['00-10', '13-01', '05-00', '2026-00-10', '2026-13-01', '2026-05-00']) {
    assert.equal(F.monthDay(d, 'en'), d, `en ${d}`);
    assert.equal(F.monthDay(d, 'es'), d, `es ${d}`);
  }
  assert.equal(F.monthDay(null, 'en'), null);
  assert.equal(F.monthDay('', 'es'), null);
  assert.equal(F.monthDay('spring', 'en'), 'spring');
  assert.equal(F.monthDay('2026-2-28', 'en'), '2026-2-28');
});

test('ruleParts shows an impossible season day as written, never "Feb 30"', () => {
  const en = F.ruleParts(row('02-30', '10-31'), 'en');
  assert.ok(en.includes('open 02-30 to Oct 31'), en.join(' | '));
  assert.ok(!en.join(' ').includes('Feb 30'));
  const es = F.ruleParts(row('02-30', '10-31'), 'es');
  assert.ok(es.includes('abierta del 02-30 al 31 oct'), es.join(' | '));
  assert.ok(!es.join(' ').includes('30 feb'));
  assert.ok(F.ruleParts(row('04-01', '04-31'), 'en').includes('open Apr 1 to 04-31'));
  assert.ok(F.ruleParts(row('02-29', '06-30'), 'en').includes('open Feb 29 to Jun 30'));
});

test('the "checked" date in a rules reply is never an impossible day', () => {
  const rule = {species_key: 'lingcod', label: 'Lingcod', applies_as: 'species', stale: false, ...row('04-01', '12-31'),
    source_name: 'CDFW', source_url: 'https://example.invalid/rules', checked: '2026-02-29'};
  const text = F.rulesText(rule, 'lingcod', null, 'en');
  assert.ok(text.includes('2026-02-29'), text);
  assert.ok(!text.includes('Feb 29'), text);
  assert.ok(F.rulesText({...rule, checked: '2026-02-28'}, 'lingcod', null, 'en').includes('Feb 28'));
});

// Rules replies name a half-listed season (RF1300-18, server/advisor/answers/
// fishid.ts ruleParts): a row with only an opening or only a closing date
// gets one part naming the known date and saying the other is not listed;
// two-date, no-date and no-take rows keep today's parts. Offline, synthetic
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

const row = (open, close, bag = 3) => ({species_key: 'lingcod', label: 'Lingcod', applies_as: 'species', stale: false,
  size_min_in: 22, size_max_in: null, bag_limit: bag, season_open: open, season_close: close, depth_limit_ft: null,
  source_name: 'CDFW', source_url: 'https://wildlife.ca.gov/', checked: '2026-10-01'});
const season = parts => parts.filter(p => /open|close|abre|abierta|cierra/.test(p));

test('only an opening date: one part naming it and that the closing date is not listed', () => {
  const en = F.ruleParts(row('04-01', null), 'en');
  assert.deepEqual(en, ['22 in. minimum', 'bag 3', 'opens Apr 1; closing date not listed']);
  assert.ok(!en.includes('open all year'));
  const es = F.ruleParts(row('04-01', null), 'es');
  assert.deepEqual(es, ['mínimo 22 pulg.', 'límite 3 por persona', 'abre el 1 abr; fecha de cierre no indicada']);
  assert.ok(!es.includes('abierta todo el año'));
});

test('only a closing date: one part naming it and that the opening date is not listed', () => {
  assert.deepEqual(season(F.ruleParts(row(null, '10-31'), 'en')), ['closes Oct 31; opening date not listed']);
  assert.deepEqual(season(F.ruleParts(row(null, '10-31'), 'es')), ['cierra el 31 oct; fecha de apertura no indicada']);
  assert.deepEqual(season(F.ruleParts(row(null, '2026-12-31'), 'en')), ['closes Dec 31; opening date not listed']);
});

test('two dates and no dates keep today\'s parts', () => {
  assert.deepEqual(season(F.ruleParts(row('04-01', '10-31'), 'en')), ['open Apr 1 to Oct 31']);
  assert.deepEqual(season(F.ruleParts(row('04-01', '10-31'), 'es')), ['abierta del 1 abr al 31 oct']);
  assert.deepEqual(F.ruleParts(row(null, null), 'en'), ['22 in. minimum', 'bag 3', 'open all year']);
  assert.deepEqual(season(F.ruleParts(row(null, null), 'es')), ['abierta todo el año']);
  assert.deepEqual(season(F.ruleParts(row(null, null, null), 'en')), ['open all year']);
});

test('no-take rows: one date still gets the half-season part, no dates get no season part', () => {
  assert.deepEqual(F.ruleParts(row('04-01', null, 0), 'en'), ['22 in. minimum', 'no take', 'opens Apr 1; closing date not listed']);
  assert.deepEqual(F.ruleParts(row(null, '10-31', 0), 'en'), ['22 in. minimum', 'no take', 'closes Oct 31; opening date not listed']);
  assert.deepEqual(F.ruleParts(row(null, null, 0), 'en'), ['22 in. minimum', 'no take']);
  assert.deepEqual(F.ruleParts(row(null, null, 0), 'es'), ['mínimo 22 pulg.', 'no se puede quedar']);
});

test('a date monthDay cannot format is shown as written', () => {
  assert.deepEqual(season(F.ruleParts(row('02-30', null), 'en')), ['opens 02-30; closing date not listed']);
  assert.deepEqual(season(F.ruleParts(row('02-30', null), 'es')), ['abre el 02-30; fecha de cierre no indicada']);
  assert.deepEqual(season(F.ruleParts(row(null, '04-31'), 'en')), ['closes 04-31; opening date not listed']);
  assert.deepEqual(season(F.ruleParts(row(null, 'Labor Day'), 'en')), ['closes Labor Day; opening date not listed']);
});

test('empty-string dates count as not listed (no half-season part, open all year)', () => {
  assert.deepEqual(season(F.ruleParts(row('', null), 'en')), ['open all year']);
  assert.deepEqual(season(F.ruleParts(row(null, ''), 'en')), ['open all year']);
});

test('the rules sentence carries the half-season part', () => {
  const text = F.rulesText(row('04-01', null), 'lingcod', null, 'en');
  assert.match(text, /Rules \(CDFW, checked Oct 1\): 22 in\. minimum, bag 3, opens Apr 1; closing date not listed\./);
});

// RF1240-16: the admin click report reads only the days and region it names. clickQuery
// takes ?days= only as the exact text '7', '30' or '90' (absent or empty: 30) and ?region=
// only as a regions/<id> name, upper case included, by the registry.ts REGION pattern (absent
// or empty: null); anything else gets the existing errors.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// clicks.ts reaches server/config.ts through go.ts, which reads the build-time globals.
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {clickQuery} = await import('../server/fleet/admin/clicks.ts');

const DAYS_ERROR = {error: 'days must be 7, 30 or 90'};
const REGION_ERROR = {error: 'invalid region'};

test('days: exact 7, 30 and 90 are kept; absent or empty is 30', () => {
  assert.deepEqual(clickQuery('7', undefined), {days: 7, region: null});
  assert.deepEqual(clickQuery('30', undefined), {days: 30, region: null});
  assert.deepEqual(clickQuery('90', undefined), {days: 90, region: null});
  assert.deepEqual(clickQuery(undefined, undefined), {days: 30, region: null});
  assert.deepEqual(clickQuery('', undefined), {days: 30, region: null});
});

test('days: any other spelling of a number, a prototype key or an unlisted value is refused', () => {
  for (const days of ['0x7', '7e0', '7.0', ' 7', '7 ', '+7', '007', '-7', 'Infinity', 'constructor', '__proto__',
    'toString', 'hasOwnProperty', '14', '0', '3e1', '9e1']) {
    assert.deepEqual(clickQuery(days, undefined), DAYS_ERROR, JSON.stringify(days));
  }
});

test('region: a regions/<id> name is kept, upper case included; absent or empty is null; a bad edge is refused', () => {
  // Owner ruling (G, 2026-11-03): upper-case region ids are correct. regions/CA and regions/OR
  // exist on disk and fleet_vessels.region holds 'CA', so ?region=CA must not be a 400.
  assert.deepEqual(clickQuery('30', 'CA'), {days: 30, region: 'CA'});
  assert.deepEqual(clickQuery('7', 'OR'), {days: 7, region: 'OR'});
  assert.deepEqual(clickQuery('7', 'Morro-Bay'), {days: 7, region: 'Morro-Bay'});
  assert.deepEqual(clickQuery('7', 'morro-bay'), {days: 7, region: 'morro-bay'});
  assert.deepEqual(clickQuery('7', 'a'), {days: 7, region: 'a'});
  assert.deepEqual(clickQuery('7', undefined), {days: 7, region: null});
  assert.deepEqual(clickQuery('7', ''), {days: 7, region: null});
  for (const region of ['-x', 'x-', '-CA', 'CA-', 'a_b', '../x', '../CA', 'morro bay', ' morro', 'morro\n', 'CA\n']) {
    assert.deepEqual(clickQuery('7', region), REGION_ERROR, JSON.stringify(region));
  }
});

test('region: the pattern is the registry one, so the two cannot drift', async () => {
  const {REGION} = await import('../server/fleet/registry.ts');
  for (const region of ['CA', 'OR', 'morro-bay', 'Morro-Bay', 'x-', '../x', 'a'.repeat(65)]) {
    assert.equal('error' in clickQuery('7', region), !REGION.test(region), JSON.stringify(region));
  }
});

test('region: 64 characters are kept, 65 are refused (length rule unchanged)', () => {
  const r64 = 'a'.repeat(64), r65 = 'a'.repeat(65);
  assert.deepEqual(clickQuery('30', r64), {days: 30, region: r64});
  assert.deepEqual(clickQuery('30', 'a' + '-'.repeat(62) + 'b'), {days: 30, region: 'a' + '-'.repeat(62) + 'b'});
  assert.deepEqual(clickQuery('30', 'A'.repeat(64)), {days: 30, region: 'A'.repeat(64)});
  assert.deepEqual(clickQuery('30', r65), REGION_ERROR);
  assert.deepEqual(clickQuery('30', 'A'.repeat(65)), REGION_ERROR);
});

test('the days error wins when both values are bad', () => {
  assert.deepEqual(clickQuery('0x7', 'x-'), DAYS_ERROR);
  assert.deepEqual(clickQuery('__proto__', 'x-'), DAYS_ERROR);
  assert.deepEqual(clickQuery('7', 'x-'), REGION_ERROR);
});

test('?region=CA yields a normal report filtered on the CA region column', async () => {
  const {clickReport} = await import('../server/fleet/admin/clicks.ts');
  const binds = [];
  const db = {prepare: sql => ({bind: (...args) => { binds.push(args); return {all: async () => ({results: sql.includes('GROUP BY c.day')
    ? [{day: '2026-11-03', count: 2}]
    : [{vessel_id: 'v1', slug: 'boat', name: 'Boat', region: 'CA', target: 'website', placement: 'other', n: 2}]})}; }})};
  const query = clickQuery(undefined, 'CA');
  assert.deepEqual(query, {days: 30, region: 'CA'});
  const report = await clickReport(db, query.days, query.region, new Date('2026-11-03T12:00:00Z'));
  assert.equal(report.region, 'CA');
  assert.equal(report.days, 30);
  assert.equal(report.totals.total, 2);
  assert.deepEqual(report.daily, [{day: '2026-11-03', count: 2}]);
  assert.deepEqual(report.vessels.map(v => [v.vessel_id, v.region, v.total]), [['v1', 'CA', 2]]);
  for (const args of binds) assert.equal(args.at(-1), 'CA');
});

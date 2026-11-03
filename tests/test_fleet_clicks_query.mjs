// RF1240-16: the admin click report reads only the days and region it names. clickQuery
// takes ?days= only as the exact text '7', '30' or '90' (absent or empty: 30) and ?region=
// only as a lowercase slug (absent or empty: null); anything else gets the existing errors.
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

test('region: a lowercase slug is kept; absent or empty is null; upper case or a bad edge is refused', () => {
  assert.deepEqual(clickQuery('7', 'morro-bay'), {days: 7, region: 'morro-bay'});
  assert.deepEqual(clickQuery('7', 'a'), {days: 7, region: 'a'});
  assert.deepEqual(clickQuery('7', undefined), {days: 7, region: null});
  assert.deepEqual(clickQuery('7', ''), {days: 7, region: null});
  for (const region of ['Morro-Bay', 'MORRO', 'morro-Bay', '-x', 'x-', 'a_b', '../x', 'morro bay', ' morro', 'morro\n']) {
    assert.deepEqual(clickQuery('7', region), REGION_ERROR, JSON.stringify(region));
  }
});

test('region: 64 lowercase characters are kept, 65 are refused (length rule unchanged)', () => {
  const r64 = 'a'.repeat(64), r65 = 'a'.repeat(65);
  assert.deepEqual(clickQuery('30', r64), {days: 30, region: r64});
  assert.deepEqual(clickQuery('30', 'a' + '-'.repeat(62) + 'b'), {days: 30, region: 'a' + '-'.repeat(62) + 'b'});
  assert.deepEqual(clickQuery('30', r65), REGION_ERROR);
  assert.deepEqual(clickQuery('30', 'A'.repeat(64)), REGION_ERROR);
});

test('the days error wins when both values are bad', () => {
  assert.deepEqual(clickQuery('0x7', 'Morro-Bay'), DAYS_ERROR);
  assert.deepEqual(clickQuery('__proto__', 'x-'), DAYS_ERROR);
  assert.deepEqual(clickQuery('7', 'Morro-Bay'), REGION_ERROR);
});

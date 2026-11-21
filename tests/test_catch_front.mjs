import test from 'node:test';
import assert from 'node:assert/strict';
import { catchFrontItem } from '../server/catch-front.ts';
import { parseConditionsV1 } from '../server/conditions-v1.ts';

const point = Object.freeze({ lat: 0, lon: 0 });
const tz = 'America/Los_Angeles';
const startedAt = '2026-01-11T00:00:00-08:00';
const midnight = '2026-01-11T08:00:00.000Z';
const geometry = Object.freeze({
  type: 'LineString', coordinates: Object.freeze([Object.freeze([-1, 1]), Object.freeze([1, 1])]),
});
const doc = Object.freeze({
  product: 'Fixture SST', observed_at: midnight, fronts: Object.freeze([Object.freeze({ geometry })]),
});

function expectItem(actual, expected) {
  assert.deepEqual(actual, expected);
  assert.deepEqual(parseConditionsV1({ v: 1, at: midnight, layers: { front_nm: actual } }), {
    ok: true, value: { v: 1, at: midnight, layers: { front_nm: expected } },
  });
}

const archivedItem = (sample_at, product = doc.product) => ({ value: 60.04, product, sample_at });

test('C1: no position takes precedence over unreadable time and archive inputs', () => {
  expectItem(catchFrontItem(null, null, 'not a time', 'Not/A_Zone'), { missing: 'no position' });
});

test('C1: do not fall back to host time or consult the archive for a bad catch time', () => {
  for (const time of ['2026-01-11T00:00:00', '01-11-2026', '2026-13-11T00:00:00Z']) {
    expectItem(catchFrontItem(point, null, time, tz), { missing: 'bad time' });
  }
});

test('C1: an invalid region zone is a time error, not a missing archive', () => {
  expectItem(catchFrontItem(point, null, startedAt, 'Not/A_Zone'), { missing: 'bad time' });
});

test('C2: reject non-plain documents even when they carry valid archive fields', () => {
  for (const input of [null, Object.assign([], doc), Object.create(doc)]) {
    expectItem(catchFrontItem(point, input, startedAt, tz), { missing: 'not archived' });
  }
});

test('C2: reject missing, blank, non-string and oversized products instead of storing them', () => {
  const { observed_at, fronts } = doc;
  for (const input of [{ observed_at, fronts }, ...['', ' \t', 42, 'x'.repeat(201)]
    .map(product => ({ ...doc, product }))]) {
    expectItem(catchFrontItem(point, input, startedAt, tz), { missing: 'not archived' });
  }
});

test('C2: count product characters as the snapshot parser does and allow null-prototype records', () => {
  const product = '🌊'.repeat(200);
  const input = Object.assign(Object.create(null), doc, { product });
  expectItem(catchFrontItem(point, input, startedAt, tz), archivedItem(midnight, product));
});

test('C2: an unzoned or unparseable observation cannot identify an archived day', () => {
  for (const observed_at of [undefined, '2026-01-11T08:00:00', '2026-13-11T08:00:00Z']) {
    expectItem(catchFrontItem(point, { ...doc, observed_at }, startedAt, tz), { missing: 'not archived' });
  }
});

test('C2: Pacific midnight splits observations even within one UTC day, in winter and summer', () => {
  for (const [before, after] of [
    ['2026-01-11T07:59:59.999Z', midnight],
    ['2026-07-11T06:59:59.999Z', '2026-07-11T07:00:00.000Z'],
  ]) {
    expectItem(catchFrontItem(point, { ...doc, observed_at: before }, after, tz), { missing: 'not archived' });
    expectItem(catchFrontItem(point, { ...doc, observed_at: after }, before, tz), { missing: 'not archived' });
    expectItem(catchFrontItem(point, { ...doc, observed_at: after }, after, tz), archivedItem(after));
  }
});

test('C3: accept a same-Pacific-day front across UTC midnight and preserve its observation instant', () => {
  // Frozen coordinates and archive data also catch attempts to modify the inputs.
  const input = Object.freeze({ ...doc, observed_at: '2026-01-10T15:59:59-08:00' });
  expectItem(catchFrontItem(point, input, '2026-01-10T23:59:59.999-0800', tz),
    archivedItem('2026-01-10T23:59:59.000Z'));
});

test('C3: distinguish an archived day with no usable fronts from a missing archive', () => {
  for (const fronts of [[], [{ geometry: { type: 'LineString', coordinates: [[0, 0]] } }]]) {
    expectItem(catchFrontItem(point, { ...doc, fronts }, startedAt, tz), { missing: 'no fronts' });
  }
});

test('C3: throwing archive metadata fails closed rather than escaping', () => {
  const input = { ...doc, get observed_at() { throw new Error('unreadable'); } };
  expectItem(catchFrontItem(point, input, startedAt, tz), { missing: 'not archived' });
});

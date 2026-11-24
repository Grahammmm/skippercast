import test from 'node:test';
import assert from 'node:assert/strict';
import {nearshoreAt} from '../packages/coast/src/nearshore.ts';
import {nearshoreRings} from '../web/map/nearshore.ts';

const rows = [{at: '2026-01-01T12:00:00Z', waveFt: 1}, {at: '2026-01-01T14:00:00Z', waveFt: 2}];
const site = (validThrough) => ({hours: rows, ...(validThrough === undefined ? {} : {validThrough})});
const Q = '2026-01-01T13:00:00Z';

test('nearshore_declared_unreadable_end_is_not_unbounded', () => {
  for (const bad of ['not-a-date', '', '   ', '2026-13-45T99:00:00Z', 5, {}, true]) {
    assert.equal(nearshoreAt(site(bad), Q), undefined, String(JSON.stringify(bad)));
  }
});

test('nearshore_null_or_omitted_end_keeps_sample_span', () => {
  for (const s of [site(null), site(undefined)]) {
    assert.equal(nearshoreAt(s, Q), rows[0]);
    assert.equal(nearshoreAt(s, '2026-01-01T11:59:59Z'), undefined);
    assert.equal(nearshoreAt(s, '2026-01-01T14:00:01Z'), undefined);
  }
});

test('nearshore_declared_end_boundary_is_inclusive', () => {
  assert.equal(nearshoreAt(site('2026-01-01T13:00:00Z'), Q), rows[0]);
  assert.equal(nearshoreAt(site('2026-01-01T12:59:59.999Z'), Q), undefined);
  assert.equal(nearshoreAt(site('2026-01-01T05:00:00-08:00'), Q), rows[0]);
  assert.equal(nearshoreAt(site('2026-01-01T12:30:00Z'), Q), undefined);
});

test('nearshore_nearest_controls_and_purity', () => {
  const s = site('2026-01-02T00:00:00Z');
  Object.freeze(s); Object.freeze(rows); rows.forEach(Object.freeze);
  assert.equal(nearshoreAt(s, '2026-01-01T14:00:00Z'), rows[1]);
  assert.equal(nearshoreAt(s, '2026-01-01T12:00:00Z'), rows[0]);
  assert.equal(nearshoreAt({hours: [], validThrough: null}, Q), undefined);
  assert.equal(nearshoreAt(s, 'nope'), undefined);
});

test('same-time corrections invalidate the rings draw only when rendered geometry changes', () => {
  const now = new Date(Q);
  const original = {...site(Q), id: 'site-a', areaId: 'central', lon: -121, lat: 35,
    sourceId: 'test-model', availability: 'available', freshness: 'current', issuedAt: rows[0].at, fetchedAt: Q};
  const draw = (patch = {}, waveFt = rows[0].waveFt) => nearshoreRings({nearshore: [{...original, ...patch,
    hours: [{...rows[0], waveFt}, {...rows[1]}]}]}, 'central', now, now);
  const initial = draw();
  const refresh = draw();
  assert.deepEqual(refresh.collection, initial.collection);
  assert.equal(refresh.key, initial.key);

  const resized = draw({}, 5);
  const moved = draw({lon: -120.75, lat: 35.25});
  const geometry = r => r.collection.features.map(f => [f.properties.id, f.properties.radius, f.geometry.coordinates]);
  assert.deepEqual(geometry(initial), [['site-a', 7, [-121, 35]]]);
  assert.deepEqual(geometry(resized), [['site-a', 19, [-121, 35]]]);
  assert.deepEqual(geometry(moved), [['site-a', 7, [-120.75, 35.25]]]);
  // Swell skips setData on equal keys. IDs and clocks alone left both corrections off the mounted source.
  assert.deepEqual({height: resized.key !== initial.key, location: moved.key !== initial.key}, {height: true, location: true});

  const capped = draw({}, 15);
  const aboveCap = draw({}, 30);
  assert.deepEqual(geometry(capped), [['site-a', 49, [-121, 35]]]);
  assert.deepEqual(aboveCap.collection, capped.collection);
  assert.equal(aboveCap.key, capped.key, 'raw heights above the cap do not change the drawn radius');
});

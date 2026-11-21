import assert from 'node:assert/strict';
import test from 'node:test';
import {chlEdgesDocTap} from '../web/map/chl-edges-doc-tap.ts';

const region = 'test-coast';
const observedAt = '2026-11-20T12:00:00Z';
const now = new Date('2026-11-20T13:00:00Z');
const tap = {lon: 4, lat: 5};
const edge = {
  id: 'edge-1', observed_at: '2026-11-20T11:00:00Z', cells: 5,
  strength_log10_per_cell: 0.32, band_half_width_km: 2,
  geometry: {type: 'LineString', coordinates: [[3, 5], [5, 5]]},
};
const raw = {
  schema_version: 1, region_id: region, layer_id: 'chl-edges', product: 'Synthetic chlorophyll',
  credit: 'Fixture credit', max_age_hours: 48, observed_at: observedAt,
  observed_fraction: 0.8, withheld: null, edges: [edge],
};

// A wrapper that collapses hidden results would discard distinctions made by the reader.
test('C1: forward the other hidden reasons unchanged', () => {
  for (const [data, clock, reason] of [
    [{...raw, edges: [], observed_at: null}, now, 'no-observation'],
    [{...raw, edges: [], observed_at: null, withheld: 'no-usable-frame'}, now, 'no-usable-frame'],
    [raw, new Date('2026-11-20T10:59:59Z'), 'future'],
  ]) assert.deepEqual(chlEdgesDocTap(data, region, tap, clock), {kind: 'hidden', reason});
});

// The clock exposes any attempt to read after refusal, even if the wrapper swallows its error.
test('C2: refuse bad schema, tampered geometry and unreadable data before reading', () => {
  let clockReads = 0;
  const clock = new Date(now);
  clock.getTime = () => { clockReads++; throw new Error('unexpected clock access'); };
  const tampered = {...edge, geometry: {type: 'LineString', coordinates: [[3, 5], [5, 91]]}};
  for (const data of [
    {...raw, schema_version: 2},
    {...raw, edges: [edge, tampered]},
    {...raw, get edges() { throw new TypeError('unreadable document'); }},
  ]) assert.deepEqual(chlEdgesDocTap(data, region, tap, clock), {kind: 'invalid'});
  assert.equal(clockReads, 0);
});

// A valid document can still reach a caller-supplied point whose getter fails.
test('C2: do not let an unreadable tap escape after validation', () => {
  const unreadableTap = {get lon() { throw new TypeError('unreadable tap'); }, lat: tap.lat};
  assert.deepEqual(chlEdgesDocTap(raw, region, unreadableTap, now), {kind: 'invalid'});
});

// Reading the raw shape directly or ignoring the supplied tap loses this hit.
test('C3: return the full reading for a tap on an edge', () => {
  assert.deepEqual(chlEdgesDocTap(raw, region, tap, now), {
    kind: 'edge', id: 'edge-1', distanceKm: 0, strengthLog10PerCell: 0.32, factorPerCell: 2.1,
    bandHalfWidthKm: 2, observedAt: edge.observed_at, product: raw.product, basis: 'observed',
  });
});

// A miss, a stale hit and a withheld feed are not interchangeable empty results.
test('C3: distinguish a miss, a stale feed and a withheld feed', () => {
  assert.deepEqual(chlEdgesDocTap(raw, region, {lon: 4, lat: 6}, now), {kind: 'none'});
  assert.deepEqual(chlEdgesDocTap(raw, region, tap, new Date('2026-11-22T12:00:00.001Z')),
    {kind: 'hidden', reason: 'stale'});
  assert.deepEqual(chlEdgesDocTap({...raw, withheld: 'too-little-clear-water', edges: []}, region, tap, now),
    {kind: 'hidden', reason: 'withheld-clear-water'});
});

// Deriving the expected region from the document instead of the caller would admit this hit.
test('C3: refuse an otherwise usable feed for another region', () => {
  assert.deepEqual(chlEdgesDocTap({...raw, region_id: 'other-coast'}, region, tap, now), {kind: 'invalid'});
});

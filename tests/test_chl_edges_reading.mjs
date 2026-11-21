import assert from 'node:assert/strict';
import test from 'node:test';
import {readChlEdges} from '../web/map/chl-edges-feed.ts';
import {chlEdgeAt, chlEdgeReading} from '../web/map/chl-edges-reading.ts';

const observedAt = '2026-11-20T12:00:00Z';
const now = new Date('2026-11-20T13:00:00Z');
const tap = {lon: 0, lat: 0};
const lineAt = lat => [[-1, lat], [1, lat]];
const edge = (line, overrides = {}) => ({id: 'e1', line, observedAt, cells: 5, strength: 0.32, bandHalfWidthKm: 2, ...overrides});
const doc = (...edges) => ({product: 'Synthetic chlorophyll', credit: '', maxAgeMs: 48 * 3_600_000,
  observedAt, observedFraction: 0.8, withheld: null, edges});

// Endpoint-only distance would miss the on-line and beside-line taps. Strict band comparison would miss the rim.
test('C1: project onto a two-point line and include the band rim, but not just beyond it', () => {
  for (const [distanceKm, inside] of [[0, true], [1.5, true], [2, true], [2.001, false]]) {
    const e = edge(lineAt(distanceKm / 111.195));
    assert.deepEqual(chlEdgeAt(doc(e), tap), inside ? {edge: e, distanceKm} : null, `${distanceKm} km`);
  }
});

// A fixed minimum must not replace the band's own width or erase its exact boundary.
test('C1: floor narrower bands at one kilometre, inclusive', () => {
  for (const [distanceKm, inside] of [[0.75, true], [1, true], [1.001, false]]) {
    const e = edge(lineAt(distanceKm / 111.195), {bandHalfWidthKm: 0.25});
    assert.deepEqual(chlEdgeAt(doc(e), tap), inside ? {edge: e, distanceKm} : null, `${distanceKm} km`);
  }
});

// Omitting longitude scaling misses this tap; projecting on the infinite line hits past the endpoint.
test('C1: scale longitude at the tap latitude and clamp to the segment ends', () => {
  const e = edge([[0.03, 61], [0.03, 59]]);
  assert.deepEqual(chlEdgeAt(doc(e), {lon: 0, lat: 60}), {edge: e, distanceKm: 0.03 * (111.195 * Math.cos(Math.PI / 3))});
  const short = edge([[0.001, 0], [0.01, 0]]);
  assert.deepEqual(chlEdgeAt(doc(short), tap), {edge: short, distanceKm: 0.111195});
  assert.deepEqual(chlEdgeAt(doc(short), {lon: 0.03, lat: 0}), null);
});

// A zero-length segment still has a distance, and equality at coordinate bounds is legal.
test('C1: handle coincident endpoints and inclusive coordinate limits', () => {
  for (const [lon, lat] of [[180, 90], [-180, -90]]) {
    const e = edge([[lon, lat], [lon, lat]]);
    assert.deepEqual(chlEdgeAt(doc(e), {lon, lat}), {edge: e, distanceKm: 0});
  }
});

// Reject invalid taps even when clamping them to the valid extent would produce a hit.
test('C1: reject non-finite coordinates and coordinates beyond either signed limit', () => {
  const d = doc(edge([[-180, -90], [-180, 90], [180, 90], [180, -90]]));
  for (const [lon, lat] of [[NaN, 90], [180, NaN], [Infinity, 90], [-180, -Infinity],
    [-180.001, 0], [180.001, 0], [180, -90.001], [180, 90.001]]) {
    assert.deepEqual(chlEdgeAt(d, {lon, lat}), null, `${lon}, ${lat}`);
  }
});

// First-hit, nearest-before-filtering, and last-on-tie selection all give the wrong edge here.
test('C1: select the nearest qualifying edge, preserving feed order on a tie', () => {
  const outside = edge(lineAt(1.125 / 111.195), {id: 'outside', bandHalfWidthKm: 0.5});
  const farther = edge(lineAt(2 / 111.195), {id: 'farther'});
  const near = edge(lineAt(1.5 / 111.195), {id: 'near'});
  const tied = edge(lineAt(-1.5 / 111.195), {id: 'tied'});
  assert.deepEqual(chlEdgeAt(doc(outside, farther, near, tied), tap), {edge: near, distanceKm: 1.5});
  assert.deepEqual(chlEdgeAt(doc(tied, near), tap), {edge: tied, distanceKm: 1.5});
});

// An endpoint chord is far from the tap; the final segment hits. Spreading all distances can throw.
test('C1: traverse a long line to its final segment without a stack-sized spread', () => {
  const e = edge([...Array.from({length: 150_000}, (_, i) => [-1, 1 + i / 150_000]), [-1, 2], [1, -2]]);
  assert.deepEqual(chlEdgeAt(doc(e), tap), {edge: e, distanceKm: 0});
  assert.deepEqual(chlEdgeAt(doc(), tap), null);
});

// The projection must stop at the feed gate, even when a tap would otherwise consult geometry.
test('C2: forward each hidden reason before touching edges', () => {
  for (const [fields, clock, reason] of [
    [{}, new Date('2026-11-22T12:00:00.001Z'), 'stale'],
    [{withheld: 'too-little-clear-water'}, now, 'withheld-clear-water'],
    [{withheld: 'no-usable-frame'}, now, 'no-usable-frame'],
    [{observedAt: null}, now, 'no-observation'],
    [{}, new Date('2026-11-20T10:59:59.999Z'), 'future'],
  ]) {
    const d = {...doc(), ...fields, get edges() { assert.fail('hidden reading touched geometry'); }};
    assert.deepEqual(chlEdgeReading(d, tap, clock), {kind: 'hidden', reason});
  }
});

// No hit in a shown feed must not be mistaken for withheld data or an edge card.
test('C2: report none for a shown feed with no pick or an invalid tap', () => {
  const d = doc(edge(lineAt(0.1)));
  assert.deepEqual(chlEdgeReading(d, tap, now), {kind: 'none'});
  assert.deepEqual(chlEdgeReading(doc(edge(lineAt(0))), {lon: 0, lat: NaN}, now), {kind: 'none'});
});

// Distinct product, credit and times catch metadata mix-ups; freezing detects writes to parsed geometry.
test('C3: round the displayed distance and factor, preserving edge time and feed product without mutation', () => {
  const edgeTime = '2026-11-20T11:00:00Z';
  const d = readChlEdges({schema_version: 1, region_id: 'test-coast', layer_id: 'chl-edges',
    product: 'Synthetic chlorophyll', credit: 'Fixture credit', max_age_hours: 48, observed_at: observedAt,
    observed_fraction: 0.8, withheld: null, edges: [{id: 'colour-break', observed_at: edgeTime,
      cells: 5, strength_log10_per_cell: 0.32, band_half_width_km: 1.5,
      geometry: {type: 'LineString', coordinates: lineAt(1.26 / 111.195)}}],
  }, 'test-coast');
  const before = structuredClone(d);
  for (const e of d.edges) {
    for (const p of e.line) Object.freeze(p);
    Object.freeze(e.line);
    Object.freeze(e);
  }
  Object.freeze(d.edges);
  Object.freeze(d);
  assert.deepEqual(chlEdgeReading(d, tap, now), {kind: 'edge', id: 'colour-break', distanceKm: 1.3,
    strengthLog10PerCell: 0.32, factorPerCell: 2.1, bandHalfWidthKm: 1.5, observedAt: edgeTime,
    product: 'Synthetic chlorophyll', basis: 'observed'});
  assert.deepEqual(d, before);
});

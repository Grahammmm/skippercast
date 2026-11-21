import assert from 'node:assert/strict';
import test from 'node:test';
import {chlEdgesShown, readChlEdges, regionalChlEdges} from '../web/map/chl-edges-feed.ts';

const region = 'test-coast-2';
const observedAt = '2026-11-20T12:00:00Z';
const rawEdge = {
  id: 'edge-1', observed_at: observedAt, cells: 5, strength_log10_per_cell: 0.32, band_half_width_km: 1.5,
  geometry: {type: 'LineString', coordinates: [[-131, 36], [-130, 37]]},
};
const rawDoc = {
  schema_version: 1, region_id: region, layer_id: 'chl-edges', product: 'Synthetic chlorophyll', credit: 'Fixture credit',
  generated_at: '2026-11-20T12:10:00Z', max_age_hours: 48, observed_at: observedAt, observed_fraction: 0.64,
  withheld: null, refused_frames: [], edges: [rawEdge],
};
const doc = {
  product: 'Synthetic chlorophyll', credit: 'Fixture credit', maxAgeMs: 172_800_000,
  observedAt, observedFraction: 0.64, withheld: null,
  edges: [{id: 'edge-1', observedAt, cells: 5, strength: 0.32, bandHalfWidthKm: 1.5, line: [[-131, 36], [-130, 37]]}],
};

// A reader for the SST shape, or one that leaks unprojected metadata, fails this control.
test('C1: project the full chlorophyll document and edge', () => {
  assert.deepEqual(readChlEdges(rawDoc, region), doc);
});

test('C1: preserve inclusive wire bounds, non-UTC time and string-only edge timestamps', () => {
  const observed_at = '2024-02-29T05:30:00.250-07:00';
  const coordinates = [[-180, -90], [180, 90]];
  const edge = {...rawEdge, observed_at: 'not interpreted by this reader', band_half_width_km: 0, geometry: {type: 'LineString', coordinates}};
  assert.deepEqual(readChlEdges({...rawDoc, observed_at, max_age_hours: 0.5, observed_fraction: 1, edges: [edge]}, region), {
    ...doc, observedAt: observed_at, maxAgeMs: 1_800_000, observedFraction: 1,
    edges: [{...doc.edges[0], observedAt: 'not interpreted by this reader', bandHalfWidthKm: 0, line: coordinates}],
  });
});

// An empty array can mean clear-water withholding, no usable frame, or simply no edge found.
test('C1: distinguish empty results and preserve observation coverage, with absent credit defaulting to empty', () => {
  const {credit, ...withoutCredit} = rawDoc;
  assert.deepEqual(readChlEdges({...withoutCredit, observed_fraction: 0, withheld: 'too-little-clear-water', edges: []}, region), {
    ...doc, credit: '', observedFraction: 0, withheld: 'too-little-clear-water', edges: [],
  });
  assert.deepEqual(readChlEdges({...rawDoc, observed_at: null, observed_fraction: null, withheld: 'no-usable-frame', edges: []}, region), {
    ...doc, observedAt: null, observedFraction: null, withheld: 'no-usable-frame', edges: [],
  });
  assert.deepEqual(readChlEdges({...rawDoc, edges: []}, region), {...doc, edges: []});
});

// Each mutation would pass if its wire check were dropped or replaced by a coercion.
test('C1: reject wrong identities, missing or coerced fields, invalid ranges and withheld documents with edges', () => {
  for (const data of [null, undefined, [], 'not a document']) assert.deepEqual(readChlEdges(data, region), null);
  for (const [field, values] of Object.entries({
    schema_version: [undefined, '1', 2], region_id: [undefined, 'other-region'], layer_id: [undefined, 'sst-fronts'],
    product: [undefined, '', '  ', 3], max_age_hours: [undefined, '48', 0, -1, NaN, Infinity],
    observed_at: [undefined, 0, '2026-11-20', '2026-11-20T12:00:00', 'November 20, 2026 12:00 GMT',
      '2026-11-20T12:00:00+25:00', '2026-02-29T12:00:00Z', '2026-04-31T12:00:00Z'],
    observed_fraction: [undefined, '0.64', -0.01, 1.01, NaN, Infinity], withheld: [undefined, false, 'cloudy'],
    edges: [undefined, null, {}],
  })) {
    for (const value of values) assert.deepEqual(readChlEdges({...rawDoc, [field]: value}, region), null, `${field}: ${value}`);
  }
  for (const withheld of ['too-little-clear-water', 'no-usable-frame']) {
    assert.deepEqual(readChlEdges({...rawDoc, withheld}, region), null, withheld);
  }
});

// Keep a valid first edge to catch readers that silently drop a malformed sibling.
test('C1: reject the whole document for one bad edge or invalid LineString', () => {
  const reject = (edge, why) => assert.deepEqual(readChlEdges({...rawDoc, edges: [rawEdge, edge]}, region), null, why);
  reject(null, 'null edge');
  reject(undefined, 'absent edge');
  for (const [field, values] of Object.entries({
    id: [undefined, '', '  ', 1], observed_at: [undefined, null, 1], cells: [undefined, 4, 5.5, '5', Infinity],
    strength_log10_per_cell: [undefined, -0.32, 0, '0.32', NaN, Infinity],
    band_half_width_km: [undefined, -1, '1.5', NaN, Infinity],
  })) {
    for (const value of values) reject({...rawEdge, [field]: value}, `${field}: ${value}`);
  }
  for (const [why, geometry] of [
    ['missing geometry', null],
    ['wrong geometry type', {...rawEdge.geometry, type: 'MultiLineString'}],
    ['non-array coordinates', {type: 'LineString', coordinates: {}}],
    ['one point', {type: 'LineString', coordinates: [[0, 0]]}],
  ]) reject({...rawEdge, geometry}, why);
  for (const [why, point] of [
    ['not an array', {0: 0, 1: 0}], ['short point', [0]], ['extra dimension', [0, 0, 0]],
    ['longitude below range', [-180.001, 0]], ['longitude above range', [180.001, 0]],
    ['latitude below range', [0, -90.001]], ['latitude above range', [0, 90.001]],
    ['non-finite longitude', [NaN, 0]], ['non-finite latitude', [0, Infinity]],
    ['string longitude', ['0', 0]], ['string latitude', [0, '0']],
  ]) reject({...rawEdge, geometry: {type: 'LineString', coordinates: [[0, 0], point]}}, why);
});

test('C1: a throwing property on unknown input is refused rather than escaping', () => {
  const data = {...rawDoc, get edges() { throw new TypeError('unreadable'); }};
  assert.deepEqual(readChlEdges(data, region), null);
});

const page = 'https://fixture.invalid/nested/map?region=ignored';

test('C2: load the same-origin root-relative regional path and project a ready result', async () => {
  const calls = [];
  const signal = new AbortController().signal;
  const fetchFn = async (...args) => {
    calls.push(args);
    return Response.json(rawDoc);
  };
  assert.deepEqual(await regionalChlEdges(region, {fetchFn, page, signal}), {state: 'ready', doc});
  assert.deepEqual(calls, [['https://fixture.invalid/feeds/conditions/regions/test-coast-2/chl-edges.json', {signal}]]);
});

test('C2: reject unsafe region ids before fetch', async () => {
  const calls = [];
  const fetchFn = async (...args) => { calls.push(args); return Response.json(rawDoc); };
  for (const id of ['', '../other', 'coast%2fother', 'Upper', 'with_space', 'coast?other', 'coast\n']) {
    assert.deepEqual(await regionalChlEdges(id, {fetchFn, page}), {state: 'error'}, JSON.stringify(id));
  }
  assert.deepEqual(calls, []);
});

// Valid bodies on failed status codes catch incorrectly treating transport errors as ready.
test('C2: distinguish 404, HTTP failure, invalid JSON and a valid JSON document for another region', async () => {
  for (const [label, response, expected] of [
    ['404', Response.json(rawDoc, {status: 404}), {state: 'none'}],
    ['500', Response.json(rawDoc, {status: 500}), {state: 'error'}],
    ['invalid JSON', new Response('{'), {state: 'error'}],
    ['wrong region', Response.json({...rawDoc, region_id: 'other-region'}), {state: 'error'}],
  ]) assert.deepEqual(await regionalChlEdges(region, {fetchFn: async () => response, page}), expected, label);
});

test('C2: ordinary URL and fetch errors resolve to error even when a fetch error is named AbortError', async () => {
  const calls = [];
  const fetchFn = async (...args) => { calls.push(args); throw new DOMException('transport failure', 'AbortError'); };
  assert.deepEqual(await regionalChlEdges(region, {page: 'not a URL', fetchFn}), {state: 'error'});
  assert.deepEqual(calls, []);
  assert.deepEqual(await regionalChlEdges(region, {page, fetchFn, signal: new AbortController().signal}), {state: 'error'});
});

test('C2: rethrow the original rejection for an aborted signal', async () => {
  const controller = new AbortController();
  controller.abort();
  const fetchFn = async (_url, {signal}) => signal.throwIfAborted();
  await assert.rejects(regionalChlEdges(region, {fetchFn, page, signal: controller.signal}), error => {
    assert.equal(error.constructor, DOMException);
    assert.equal(error, controller.signal.reason);
    return true;
  });
});

// Withholding must win both over a stale timestamp and over no observation.
test('C3: classify withholding before testing the observation time', () => {
  const now = new Date(observedAt);
  assert.deepEqual(chlEdgesShown({...doc, observedAt: '2026-11-17T12:00:00Z', withheld: 'too-little-clear-water', edges: []}, now),
    {show: false, reason: 'withheld-clear-water'});
  assert.deepEqual(chlEdgesShown({...doc, observedAt: null, withheld: 'no-usable-frame', edges: []}, now), {show: false, reason: 'no-usable-frame'});
  assert.deepEqual(chlEdgesShown({...doc, observedAt: null, edges: []}, now), {show: false, reason: 'no-observation'});
});

test('C3: show through both exact time limits and refuse one millisecond beyond each', () => {
  for (const [clock, expected] of [
    ['2026-11-20T10:59:59.999Z', {show: false, reason: 'future'}],
    ['2026-11-20T11:00:00.000Z', {show: true}],
    ['2026-11-20T12:00:00.000Z', {show: true}],
    ['2026-11-22T12:00:00.000Z', {show: true}],
    ['2026-11-22T12:00:00.001Z', {show: false, reason: 'stale'}],
  ]) assert.deepEqual(chlEdgesShown(doc, new Date(clock)), expected, clock);
});

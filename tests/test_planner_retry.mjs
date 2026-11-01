// SC1737-05: the trip planner asks again after a failed read. A failed port list
// (web/ports.ts `loadPorts` by default) is asked again on Best available and,
// while there is no list, the planner says Best available has no distance limit;
// a dropped depth-contour read (thrown, 429, 5xx) is asked again on the next
// toggle, while a 404 or a failed check stays the visit's answer.
import test from 'node:test';
import assert from 'node:assert/strict';

const {createPlanner, loadContourFile, PORTS_FAILED_NOTE} = await import('../web/planner.ts');
const {distanceNm} = await import('../dist/spot-ranking.js');
const {HOME_PORT_KEY} = await import('../dist/home-port.js');

const NOW = new Date('2026-10-12T18:00:00Z');
const REGION = {id: 'test-coast', name: 'Test Coast', timezone: 'America/Los_Angeles', mpa: {bounds: [-10, -10, 10, 10]}};
const ring = (x, y, w = 0.002) => [[x, y], [x + w, y], [x + w, y + w], [x, y + w], [x, y]];
const SCREEN = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, exportExclusions: () => ({features: [], checked_at: NOW.toISOString()})};
const MAP = {getSize: () => ({x: 512, y: 512}), getBounds: () => ({getWest: () => -1, getEast: () => 1, getNorth: () => 1, getSouth: () => -1, contains: () => true})};
function reefs(n = 3) {
  const targets = Array.from({length: n}, (_, i) => ({
    id: `reef-${i}`, label: `Reef ${i}`, canonical_habitat: true, latitude: 0.01 * i, longitude: 0.01 * i, habitat_grade: 'A', habitat_score: 90 - i,
    neighborhood_depth_ft: [90, 120], resolution_m: 2, evidence_confidence: {percent: 90 - i}, species_fit: {lingcod: 3, 'rockfish-reef': 3},
    area_ids: [`area-${i}`], terrain_interpretation: 'Raised structure', source_url: 'https://example.org/s', evidence_status: 'Fish presence unverified.',
  }));
  const areas = targets.map((t, i) => ({id: `area-${i}`, target_ids: [t.id], geometry: {type: 'Polygon', coordinates: [ring(t.longitude, t.latitude)]}}));
  return {targets, areas, publication: {export_sha256: 'a'.repeat(64), status: 'ready', expires_at: '2099-12-31T00:00:00Z', region: 'test-coast'}, source_validation_date: '2026-10-01'};
}
const ATLAS = {targets: [{id: 'old-1', label: 'Old 1', latitude: 0.5, longitude: 0.5, habitat_grade: 'B', center_depth_ft: 80, neighborhood_depth_ft: [70, 90]}], areas: [], drifts: []};
const P1 = {id: 'p1', name: 'Port 1', region: 'test-coast', match: [0.05, 0.03]};
const P2 = {id: 'p2', name: 'Port 2', region: 'test-coast', match: [-0.04, 0.02]};
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

function make(extra = {}) {
  return createPlanner({atlas: ATLAS, screen: SCREEN, region: REGION, map: MAP, getVisible: () => [], storage: null, now: () => NOW,
    landWater: async () => () => ({state: 'water'}), loadReefs: async () => reefs(), emit: () => {}, nav: {open() {}, showMap() {}, conditions() {}}, ...extra});
}
/** A source giving `answers` in order (an Error rejects); `calls()` counts the asks. */
function source(...answers) {
  let n = 0;
  const fn = async () => { const a = answers[Math.min(n++, answers.length - 1)]; if (a instanceof Error) throw a; return a; };
  return Object.assign(fn, {calls: () => n});
}
const fromPort = (p, port) => p.spots.value.every(t => t.distance_nm === distanceNm({latitude: port.match[0], longitude: port.match[1]}, t));

test('the note is the exact text', () => {
  assert.equal(PORTS_FAILED_NOTE, 'Port list unavailable, so Best available has no distance limit. It is asked again when you select Best available.');
});

test('a port list that rejected at creation is asked again on Best available; the answer fills the ports and the ranking uses the port', async () => {
  const loadPorts = source(new Error('offline'), {ports: [P1, P2]}), p = make({loadPorts});
  await settle();
  assert.equal(p.portsReady.value, true);
  assert.equal(p.portsFailed.value, true);
  assert.deepEqual(p.ports.value, []);
  assert.equal(p.filters.value.port, '');
  await p.selectBest();
  assert.equal(loadPorts.calls(), 2);
  assert.equal(p.portsFailed.value, false);
  assert.deepEqual(p.ports.value.map(x => x.id), ['p1', 'p2']);
  assert.equal(p.filters.value.port, 'p1', 'the first port without a saved one');
  assert.equal(p.ranked.value, true, p.scopeStatus.value);
  assert.ok(p.spots.value.length > 0 && fromPort(p, P1), 'distances from the port the retry found');
  await p.selectBest();
  assert.equal(loadPorts.calls(), 2, 'a loaded list is not asked again');
  p.dispose();
});

test('a retry keeps a user-chosen listed port, else the saved home port', async () => {
  const chosen = make({loadPorts: source(new Error('offline'), {ports: [P1, P2]})});
  await settle();
  chosen.setFilter('port', 'p2');
  await chosen.selectBest();
  assert.equal(chosen.filters.value.port, 'p2');
  assert.ok(chosen.spots.value.length > 0 && fromPort(chosen, P2));
  chosen.dispose();
  const storage = {getItem: k => k === HOME_PORT_KEY ? 'p2' : null, setItem() {}};
  const saved = make({storage, loadPorts: source(null, {ports: [P1, P2]})});
  await settle();
  saved.setFilter('port', 'gone');
  await saved.selectBest();
  assert.equal(saved.filters.value.port, 'p2', 'an unlisted choice falls back to the saved port');
  saved.dispose();
});

test('null or no array is a failure; an empty list or only other regions is not', async () => {
  for (const answer of [null, {}, {ports: 'x'}]) {
    const p = make({loadPorts: source(answer)});
    await settle();
    assert.equal(p.portsFailed.value, true, JSON.stringify(answer));
    assert.equal(p.portsReady.value, true);
    p.dispose();
  }
  for (const answer of [{ports: []}, {ports: [{...P1, region: 'other-coast'}]}]) {
    const loadPorts = source(answer), p = make({loadPorts});
    await settle();
    assert.equal(p.portsFailed.value, false, JSON.stringify(answer));
    assert.deepEqual(p.ports.value, []);
    await p.selectBest();
    assert.equal(loadPorts.calls(), 1, 'an answered list is not asked again');
    assert.ok(p.spots.value.length > 0 && p.spots.value.every(t => t.distance_nm === null));
    p.dispose();
  }
});

test('a retry that fails again still ranks with no distance limit, keeps the note, and asks once per click', async () => {
  const loadPorts = source(new Error('a'), new Error('b'), null), p = make({loadPorts});
  await settle();
  await p.selectBest();
  assert.equal(loadPorts.calls(), 2);
  assert.equal(p.portsFailed.value, true);
  assert.equal(p.ranked.value, true, p.scopeStatus.value);
  assert.ok(p.spots.value.length > 0 && p.spots.value.every(t => t.distance_nm === null), 'no port, no distance');
  await p.selectBest();
  assert.equal(loadPorts.calls(), 3, 'one more ask for the second click');
  assert.equal(p.portsFailed.value, true);
  assert.equal(p.ranked.value, true, p.scopeStatus.value);
  p.dispose();
});

test('without deps.loadPorts the planner reads web/ports.ts loadPorts: a 503, then the directory on Best available', async () => {
  const original = globalThis.fetch, urls = [];
  const directory = {schema_version: 1, ports: [{...P1, status: 'active', forecast_point: 'x', forecast_name: 'X'}]};
  let n = 0;
  globalThis.fetch = async url => { urls.push(String(url)); const ok = n++ > 0; return {ok, status: ok ? 200 : 503, json: async () => directory}; };
  try {
    const p = make();
    await settle(); await settle();
    assert.equal(p.portsFailed.value, true);
    await p.selectBest();
    assert.deepEqual(urls, ['data/home-ports.json', 'data/home-ports.json']);
    assert.equal(p.portsFailed.value, false);
    assert.equal(p.filters.value.port, 'p1');
    assert.ok(p.spots.value.length > 0 && fromPort(p, P1));
    p.dispose();
  } finally { globalThis.fetch = original; }
});

/** A planner with one research spot selected, so the summary shows what blocks an export. */
function contourPlanner(loadContours) {
  const p = make({loadPorts: source({ports: [P1]}), loadContours});
  p.setResearch(true); p.toggleSpot('old-1', true);
  return p;
}

test('a contour file refused with retry blocks the export, and the next toggle asks again', async () => {
  const loadContours = source({refused: 'Dropped. Turn off depth contour tracks to export.', retry: true}, {collection: null}), p = contourPlanner(loadContours);
  p.setContourTracks(true);
  await settle();
  assert.equal(p.summary.value.message, 'Dropped. Turn off depth contour tracks to export.');
  await assert.rejects(p.exportFile('gpx'), {message: 'Dropped. Turn off depth contour tracks to export.'});
  p.setContourTracks(false);
  await settle();
  assert.equal(loadContours.calls(), 1, 'turning off does not ask');
  p.setContourTracks(true);
  assert.equal(p.summary.value.message, 'Loading depth contours…');
  await settle();
  assert.equal(loadContours.calls(), 2);
  assert.equal(p.summary.value.ok, true, p.summary.value.message);
  assert.equal(p.summary.value.counts.contours, 0, 'the file is in the request');
  p.setContourTracks(false); p.setContourTracks(true);
  await settle();
  assert.equal(loadContours.calls(), 2, 'a loaded file is kept for the visit');
  p.dispose();
});

test('a refusal without retry stays the visit\'s answer', async () => {
  const loadContours = source({refused: 'Withheld. Turn off depth contour tracks to export.'}, {collection: null}), p = contourPlanner(loadContours);
  p.setContourTracks(true);
  await settle();
  p.setContourTracks(false); p.setContourTracks(true);
  await settle();
  assert.equal(loadContours.calls(), 1);
  assert.equal(p.summary.value.message, 'Withheld. Turn off depth contour tracks to export.');
  p.dispose();
});

test('a rejected contour load is refused with retry and asked again on the next toggle', async () => {
  const loadContours = source(new Error('boom'), {collection: null}), p = contourPlanner(loadContours);
  p.setContourTracks(true);
  await settle();
  assert.match(p.summary.value.message, /^Depth contours did not load, so none are drawn\. Turn off depth contour tracks to export\.$/);
  p.setContourTracks(false); p.setContourTracks(true);
  await settle();
  assert.equal(loadContours.calls(), 2);
  assert.equal(p.summary.value.ok, true, p.summary.value.message);
  p.dispose();
});

test('loadContourFile marks a thrown fetch, 429 and 5xx for retry; 404, other statuses and a failed check are not', async () => {
  const page = () => 'https://skippercast.test/app/';
  const reply = (status, body = {}) => async () => ({status, ok: status >= 200 && status < 300, json: async () => body});
  for (const fetchFn of [async () => { throw new TypeError('network'); }, reply(429), reply(500), reply(503), reply(599)]) {
    const file = await loadContourFile('morro-bay', '2026-09-22', fetchFn, page);
    assert.equal(file.retry, true);
    assert.match(file.refused, /did not load/);
  }
  assert.deepEqual(await loadContourFile('morro-bay', '2026-09-22', reply(404), page), {collection: null});
  for (const fetchFn of [reply(403), reply(200, {type: 'FeatureCollection'})]) {
    const file = await loadContourFile('morro-bay', '2026-09-22', fetchFn, page);
    assert.ok(file.refused && !('retry' in file), JSON.stringify(file));
  }
});

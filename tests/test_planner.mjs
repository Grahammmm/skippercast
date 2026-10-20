// #602: the day planner's state (web/planner.ts), ported from v1's
// dist/export-ui.js onto v2 signals. A plan saved before the port must open
// and export unchanged, and a change made while a slow call loads must win, so
// these pin the draft's key and shape, ranking, restore, the races and the
// export guards. The full flow in a browser is e2e/v2-trip.spec.ts.
import test from 'node:test';
import assert from 'node:assert/strict';

const {createPlanner, nextFriday, planFit} = await import('../web/planner.ts');
const {draftKey} = await import('../dist/trip-export.js');
const {coordinates} = await import('../web/state.ts');

const NOW = new Date('2026-10-12T18:00:00Z');  // Monday, Pacific
const REGION = {id: 'test-coast', name: 'Test Coast', timezone: 'America/Los_Angeles', mpa: {bounds: [-10, -10, 10, 10]}};
const ring = (x, y, w = 0.002) => [[x, y], [x + w, y], [x + w, y + w], [x, y + w], [x, y]];
const SCREEN = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, exportExclusions: () => ({features: [], checked_at: NOW.toISOString()})};
const MAP = {getSize: () => ({x: 512, y: 512}), getBounds: () => ({getWest: () => -1, getEast: () => 1, getNorth: () => 1, getSouth: () => -1, contains: () => true})};

/** A screened publication of `n` canonical reefs, best first. */
function reefs(n = 5, sha = 'a'.repeat(64)) {
  const targets = Array.from({length: n}, (_, i) => ({
    id: `reef-${i}`, label: `Reef ${i}`, canonical_habitat: true, latitude: 0.01 * i, longitude: 0.01 * i, habitat_grade: 'A', habitat_score: 90 - i,
    neighborhood_depth_ft: [90, 120], resolution_m: 2, evidence_confidence: {percent: 90 - i}, species_fit: {lingcod: 3, 'rockfish-reef': 3},
    area_ids: [`area-${i}`], terrain_interpretation: 'Raised structure', source_url: 'https://example.org/s', evidence_status: 'Fish presence unverified.',
  }));
  const areas = targets.map((t, i) => ({id: `area-${i}`, target_ids: [t.id], geometry: {type: 'Polygon', coordinates: [ring(t.longitude, t.latitude)]}}));
  // `expires_at` is a far-future constant, not a date near the test's frozen NOW:
  // buildExport compares against the real clock (its `now` default), so a near date
  // would "expire" once wall-clock time passes it and fail the export guards below.
  return {targets, areas, publication: {export_sha256: sha, status: 'ready', expires_at: '2099-12-31T00:00:00Z', region: 'test-coast'}, source_validation_date: '2026-10-01'};
}
const ATLAS = {targets: [{id: 'old-1', label: 'Old 1', latitude: 0.5, longitude: 0.5, habitat_grade: 'B', center_depth_ft: 80, neighborhood_depth_ft: [70, 90]}], areas: [], drifts: []};

function harness({stored = null, loadReefs, ports = [{id: 'p1', name: 'Port 1', region: 'test-coast', match: [0, 0]}]} = {}) {
  const store = new Map(stored ? [[draftKey(REGION.id), stored]] : []);
  const storage = {getItem: k => store.get(k) ?? null, setItem: (k, v) => { store.set(k, v); }};
  const emitted = [], nav = [];
  const planner = createPlanner({atlas: ATLAS, screen: SCREEN, region: REGION, map: MAP, getVisible: () => [], storage, now: () => NOW,
    loadReefs: loadReefs ?? (async () => reefs()), loadPorts: async () => ({ports}), emit: d => emitted.push(d),
    nav: {open: () => nav.push('open'), showMap: () => nav.push('map'), conditions: date => nav.push(`conditions ${date}`)}});
  return {planner, store, emitted, nav, saved: () => JSON.parse(store.get(draftKey(REGION.id)))};
}
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

test('downloaded notes follow the coordinate choice while GPX positions remain decimal degrees', async () => {
  const {planner: p} = harness();
  p.add('old-1'); p.setResearch(true);
  try {
    for (const [mode, expected] of [['dd', '0.5000° N, 0.5000° E'], ['ddm', '0° 30.000′ N, 0° 30.000′ E'], ['dms', '0° 30′ 00.00″ N, 0° 30′ 00.00″ E']]) {
      coordinates.value = mode;
      assert.ok((await (await p.exportFile('notes')).text()).includes(expected));
      const gpx = await (await p.exportFile('gpx')).text();
      assert.match(gpx, /lat="0\.5" lon="0\.5"/);
      assert.doesNotMatch(gpx, /[°′″]/);
    }
  } finally { coordinates.value = 'dd'; p.dispose(); }
});

test('a draft saved before the port opens with its ids, name, date, layers and coverage, under the same key', () => {
  const v1 = JSON.stringify({ids: ['old-1', 'gone'], rankedPlan: null, name: 'Sunday reef', date: '2026-10-18', avoidScope: 'region',
    layers: {waypoints: true, outlines: false, alignments: true, exclusions: false}});
  const {planner: p, saved} = harness({stored: v1});
  assert.deepEqual(p.draft.value, {ids: ['old-1'], rankedPlan: null, name: 'Sunday reef', date: '2026-10-18', avoidScope: 'region',
    layers: {waypoints: true, outlines: false, alignments: true, exclusions: false}});
  p.edit({name: 'Monday reef'});
  assert.deepEqual(Object.keys(saved()).sort(), ['avoidScope', 'date', 'ids', 'layers', 'name', 'rankedPlan'], 'the stored shape is v1\'s');
  assert.equal(saved().name, 'Monday reef');
  p.dispose();
});

test('blocked storage keeps the plan in the page and says so', () => {
  const p = createPlanner({atlas: ATLAS, screen: SCREEN, region: REGION, map: MAP, getVisible: () => [], now: () => NOW, loadPorts: async () => null, emit: () => {},
    storage: {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }}, nav: {open() {}, showMap() {}, conditions() {}}});
  assert.equal(p.draft.value.name, 'My fishing day');
  assert.equal(p.draft.value.date, '2026-10-12', 'today in the region\'s zone');
  p.toggleSpot('old-1', true);
  assert.deepEqual(p.draft.value.ids, ['old-1']);
  assert.match(p.storageNote.value, /Browser storage is unavailable/);
  p.dispose();
});

test('the distance filter starts from the saved Boat range (#644), else 20 nm', () => {
  const make = reachNm => createPlanner({atlas: ATLAS, screen: SCREEN, region: REGION, map: MAP, getVisible: () => [], now: () => NOW, loadPorts: async () => null, emit: () => {},
    storage: null, nav: {open() {}, showMap() {}, conditions() {}}, ...(reachNm === undefined ? {} : {reachNm})});
  for (const [reachNm, distance] of [[undefined, 20], [null, 20], [12.5, 12.5]]) {
    const p = make(reachNm);
    assert.equal(p.filters.value.distance, distance, String(reachNm));
    p.dispose();
  }
});

test('Best available ranks distinct reefs, sets the ranked layers, names the plan, moves today to Friday, and draws the set', async () => {
  const {planner: p, emitted, saved} = harness();
  await settle();
  assert.equal(p.portsReady.value, true);
  assert.equal(p.filters.value.port, 'p1');
  await p.selectBest();
  assert.equal(p.ranked.value, true);
  assert.match(p.scopeStatus.value, /^5 distinct reef spots ranked\. Waypoints \+ reef outlines only\. Fewer than your requested limit qualified\. Check conditions for 2026-10-16/);
  const d = saved();
  assert.deepEqual(d.ids, ['reef-0', 'reef-1', 'reef-2', 'reef-3', 'reef-4']);
  assert.equal(d.name, 'Lingcod + rockfish');
  assert.equal(d.date, nextFriday('2026-10-12'));
  assert.deepEqual(d.layers, {waypoints: true, outlines: true, alignments: false, exclusions: false});
  assert.deepEqual(d.rankedPlan, {sha256: 'a'.repeat(64), species: 'reef', priorities: d.ids.map((id, i) => ({id, rank: i + 1}))});
  assert.equal(p.summary.value.ok, true, p.summary.value.message);
  assert.equal(p.summary.value.counts.waypoints, 5);
  assert.deepEqual(emitted.at(-1).targets.map(t => t.id), d.ids);
  assert.deepEqual(p.spots.value.map(t => t.trip_rank), [1, 2, 3, 4, 5], 'the list shows only ranked reefs, in rank order');
  p.dispose();
});

// CI6-01A: the planner's distances run from the chosen listed port, never the device position.
test('Best available measures distance from the chosen port; without one there is no distance and no device fallback', async () => {
  const {distanceNm} = await import('../dist/spot-ranking.js');
  const saved = Object.getOwnPropertyDescriptor(globalThis, 'navigator'), calls = [];
  Object.defineProperty(globalThis, 'navigator', {configurable: true, writable: true, value: {geolocation: {
    getCurrentPosition(ok) { calls.push('get'); ok({coords: {latitude: 0.5, longitude: 0.5}}); }, watchPosition() { calls.push('watch'); return 1; }, clearWatch() {}}}});
  try {
    const ports = [{id: 'p1', name: 'Port 1', region: 'test-coast', match: [0, 0]}, {id: 'p2', name: 'Launch 2', region: 'test-coast', match: [0.05, 0.03]}];
    for (const id of ['p1', 'p2']) {
      const {planner: p} = harness({ports});
      await settle();
      p.setFilter('port', id);
      await p.selectBest();
      const [lat, lon] = ports.find(x => x.id === id).match;
      assert.equal(p.ranked.value, true, p.scopeStatus.value);
      for (const t of p.spots.value) assert.equal(t.distance_nm, distanceNm({latitude: lat, longitude: lon}, t), `${t.id} from ${id}`);
      p.dispose();
    }
    const {planner: none} = harness({ports: []});
    await settle();
    assert.equal(none.filters.value.port, '');
    await none.selectBest();
    assert.equal(none.ranked.value, true, none.scopeStatus.value);
    assert.ok(none.spots.value.length > 0 && none.spots.value.every(t => t.distance_nm === null), 'no port, no distance');
    none.dispose();
    assert.deepEqual(calls, [], 'the planner never asks for the device position');
  } finally { if (saved) Object.defineProperty(globalThis, 'navigator', saved); else delete globalThis.navigator; }
});

test('a selection made while Best available loads wins over its answer', async () => {
  let release;
  const {planner: p} = harness({loadReefs: () => new Promise(resolve => { release = () => resolve(reefs()); })});
  await settle();
  const pending = p.selectBest();
  assert.equal(p.loading.value, true);
  await settle();
  p.preset('none');
  release();
  await pending;
  assert.equal(p.ranked.value, false);
  assert.deepEqual(p.draft.value.ids, []);
  assert.equal(p.scopeStatus.value, '0 spots selected. Your previous selection has been replaced.');
  assert.equal(p.loading.value, false);
  p.dispose();
});

test('a changed trip filter blocks the export until Best available runs again', async () => {
  const {planner: p} = harness();
  await settle();
  await p.selectBest();
  p.setFilter('limit', 10);
  assert.equal(p.filtersDirty.value, true);
  assert.equal(p.summary.value.ok, false);
  assert.match(p.summary.value.message, /Trip filters changed/);
  await p.selectBest();
  assert.equal(p.filtersDirty.value, false);
  assert.equal(p.summary.value.ok, true);
  p.dispose();
});

test('a saved ranked plan restores from the same publication, and is held when the publication changed', async () => {
  const first = harness();
  await settle();
  await first.planner.selectBest();
  const stored = first.store.get(draftKey(REGION.id));
  first.planner.dispose();

  const same = harness({stored});
  assert.equal(same.planner.restorePending.value, true);
  assert.match(same.planner.summary.value.message, /Saved ranked plan needs current reef data/);
  await same.planner.restore();
  assert.equal(same.planner.ranked.value, true);
  assert.equal(same.planner.scopeStatus.value, 'Saved ranked reefs restored from the current publication. Check your trip conditions before departure.');
  assert.equal(same.planner.tripAtlas.value.targets.find(t => t.id === 'reef-0').name, '01 LR H3 C90% 90-120ft');
  assert.equal(same.planner.summary.value.ok, true);
  same.planner.dispose();

  const changed = harness({stored, loadReefs: async () => reefs(5, 'b'.repeat(64))});
  await changed.planner.restore();
  assert.equal(changed.planner.ranked.value, false);
  assert.equal(changed.planner.restorePending.value, true);
  assert.match(changed.planner.scopeStatus.value, /Saved reef data changed/);
  assert.deepEqual(changed.planner.draft.value.ids, JSON.parse(stored).ids, 'the saved selection is retained for review');
  changed.planner.dispose();
});

test('the export re-checks the publication: changed reef data blocks the file', async () => {
  let sha = 'a'.repeat(64);
  const {planner: p} = harness({loadReefs: async () => reefs(5, sha)});
  await settle();
  await p.selectBest();
  const file = await p.exportFile('gpx');
  assert.equal(file.name, 'SkipperCast-test-coast-2026-10-16-5wp.gpx');
  assert.match(await file.text(), /<wpt /);
  const notes = await p.exportFile('notes');
  assert.equal(notes.name, 'SkipperCast-test-coast-2026-10-16-5wp.html');
  assert.equal(notes.type, 'text/html');
  assert.match(await notes.text(), /^<!doctype html>/);
  sha = 'c'.repeat(64);
  await assert.rejects(p.exportFile('gpx'), /Reef data changed\. Select Best available again before exporting\./);
  p.dispose();
});

test('adding an unranked spot clears the ranked set; research references need the opt-in', async () => {
  const {planner: p, emitted} = harness();
  await settle();
  await p.selectBest();
  p.add('old-1');
  assert.equal(p.ranked.value, false);
  assert.deepEqual(emitted.at(-1), {targets: [], areas: []});
  assert.match(p.scopeStatus.value, /^Saved research reference/);
  assert.ok(p.draft.value.ids.includes('old-1'));
  p.setLayer('outlines', false);  // the fixture's research reference has no linked outline
  assert.match(p.summary.value.message, /Research coordinates need explicit opt-in/, 'a research reference blocks the download until opted in');
  p.setResearch(true);
  assert.equal(p.summary.value.ok, true, JSON.stringify(p.summary.value));
  p.add('missing');
  assert.equal(p.draft.value.ids.includes('missing'), false);
  p.dispose();
});

test('a plan name keystroke neither re-runs the counts nor redraws the Chart; filtered research needs the opt-in', async () => {
  const {planner: p, emitted, saved} = harness();
  await settle();
  await p.selectBest();
  const before = emitted.length, counts = p.summary.value;
  p.edit({name: 'Sunday'});
  assert.equal(saved().name, 'Sunday', 'the name is still saved as typed');
  assert.equal(p.summary.value, counts);
  assert.equal(emitted.length, before);
  p.preset('filtered');
  assert.equal(p.scopeStatus.value, 'Enable Research-coordinate export to use filtered research references.');
  assert.equal(p.ranked.value, true, 'a refused preset changes nothing');
  p.dispose();
});

test('the map and conditions hand-offs', async () => {
  const {planner: p, nav, emitted} = harness();
  await settle();
  p.showOnMap();
  assert.deepEqual(nav, [], 'nothing ranked: nothing to show');
  await p.selectBest();
  p.showOnMap();
  assert.equal(nav.at(-1), 'map');
  assert.equal(emitted.at(-1).fit, true);
  p.checkConditions();
  assert.equal(nav.at(-1), 'conditions 2026-10-16');
  p.review('reef-0');
  assert.equal(nav.at(-1), 'open');
  p.dispose();
});

test('the combined target ranks on the weaker fit', () => {
  const t = {species_fit: {lingcod: 3, 'rockfish-reef': 2}};
  assert.equal(planFit(t, 'reef'), 2);
  assert.equal(planFit(t, 'lingcod'), 3);
  assert.equal(planFit(t, 'rockfish'), 2);
  assert.equal(nextFriday('2026-10-16'), '2026-10-16');
  assert.equal(nextFriday('2026-10-17'), '2026-10-23');
});

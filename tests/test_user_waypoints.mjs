// CI6-14: synthetic user points stay distinct from screened habitat and research references.
import test from 'node:test';
import assert from 'node:assert/strict';
import {buildExport, draftKey, offlineNotes, readDraft, USER_WAYPOINT_CATEGORIES, userWaypoints} from '../dist/trip-export.js';
import {createPlanner} from '../web/planner.ts';
import {beginWaypointPlacement, cancelWaypointPlacement, placeWaypoint, waypointPlacement} from '../web/waypoint-placement.ts';

const region = {id: 'test-coast', name: 'Test Coast', timezone: 'UTC', mpa: {bounds: [-2, -2, 2, 2]}};
const atlas = {targets: [], areas: [], drifts: []};
const point = {id: 'user:fixture', name: 'Synthetic <reef> & mark', category: 'reef', latitude: 0.2, longitude: 0.3};
const screen = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true};
const request = (patch = {}) => ({atlas, screen, ids: [point.id], userWaypoints: [point], region, ...patch});
function harness({stored = null, boundary = screen} = {}) {
  const store = new Map(stored ? [[draftKey(region.id), stored]] : []);
  let pick;
  const p = createPlanner({atlas, screen: boundary, region, storage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v)},
    getVisible: () => [], loadPorts: async () => null, emit() {},
    map: {getSize: () => ({x: 100, y: 100}), getBounds: () => ({getWest: () => -2, getEast: () => 2, getNorth: () => 2, getSouth: () => -2})},
    nav: {open() {}, showMap() {}, conditions() {}, chooseWaypoint: fn => { pick = fn; }}});
  return {p, store, drop(at = point) { p.chooseWaypoint(); pick({latitude: at.latitude, longitude: at.longitude}); }};
}

test('all original categories serialize as GPX 1.1 type, without invented depth or evidence', () => {
  assert.deepEqual(USER_WAYPOINT_CATEGORIES, ['reef', 'wreck', 'bait', 'hazard', 'other']);
  for (const category of USER_WAYPOINT_CATEGORIES) {
    const result = buildExport(request({userWaypoints: [{...point, category}], layers: {waypoints: true, outlines: true, alignments: true}}));
    assert.match(result.gpx, new RegExp(`<type>${category}</type></wpt>`));
    assert.match(result.gpx, /<name>Synthetic &lt;reef&gt; &amp; mark<\/name>/);
    assert.match(result.gpx, /lat="0.2" lon="0.3"/);
    assert.equal(result.counts.waypoints, 1);
    assert.equal(result.counts.tracks, 0);
    assert.doesNotMatch(result.gpx, /undefined|NaN|Terrain|Fishing Area|Survey/);
    const notes = offlineNotes(result, region, {name: 'Test', date: '2026-10-21'});
    assert.match(notes, /User waypoint/);
    assert.doesNotMatch(notes, /undefined|terrain score|ft center/);
  }
});

test('stored points are bounded, sanitized, deduplicated and cannot claim measured habitat', () => {
  const contaminated = {...point, canonical_habitat: true, area_ids: ['fake'], trip_rank: 1, user_waypoint: true};
  assert.deepEqual(userWaypoints([contaminated]), [point]);
  const draft = readDraft(JSON.stringify({ids: [point.id, 'missing'], userWaypoints: [contaminated]}), atlas, '2026-10-21');
  assert.deepEqual(draft.userWaypoints, [point]);
  assert.deepEqual(draft.ids, [point.id]);
  assert.equal(draft.allowResearch, undefined);
  for (const bad of [{category: 'foreign-icon'}, {latitude: 91}, {longitude: '0.3'}, {latitude: null}, {name: ' '}, {name: 'a'.repeat(81)}, {id: 'reef:canonical'}]) {
    assert.deepEqual(userWaypoints([{...point, ...bad}]), []);
    assert.throws(() => buildExport(request({userWaypoints: [{...point, ...bad}]})), /Invalid user waypoints/);
  }
  assert.equal(userWaypoints([point, point]).length, 1);
  assert.throws(() => buildExport(request({userWaypoints: [point, point]})), /Invalid user waypoints/);
  assert.deepEqual(userWaypoints(Array.from({length: 101}, (_, i) => ({...point, id: `user:${i}`}))), []);
  assert.throws(() => buildExport(request({atlas: {...atlas, targets: [{...point}]}})), /Invalid user waypoints/);
});

test('adding a user point never exempts other research references, including forged flags', () => {
  const research = {...point, id: 'research', user_waypoint: true, neighborhood_depth_ft: [20, 30], area_ids: []};
  const mixed = request({atlas: {...atlas, targets: [research]}, ids: [point.id, research.id]});
  assert.throws(() => buildExport(mixed), /explicit opt-in/);
  const result = buildExport({...mixed, allowResearch: true});
  assert.equal(result.features.selected.find(t => t.id === research.id).user_waypoint, false);
  assert.equal(result.counts.waypoints, 2);
});

test('map click, save, reload, deselect and remove use only the existing region draft', async () => {
  const {p, store, drop} = harness();
  try {
    drop();
    p.saveWaypoint(point.name, 'wreck');
    assert.equal(p.allowResearch.value, false);
    assert.equal(p.summary.value.ok, true);
    assert.equal(p.summary.value.counts.waypoints, 1);
    assert.equal(p.waypointPosition.value, null);
    assert.deepEqual([...store.keys()], [draftKey(region.id)]);
    const stored = store.get(draftKey(region.id));
    const restored = harness({stored});
    try {
      const [saved] = restored.p.draft.value.userWaypoints;
      assert.equal(saved.name, point.name);
      assert.equal(saved.category, 'wreck');
      assert.equal(restored.p.summary.value.ok, true);
      assert.match(await (await restored.p.exportFile('gpx')).text(), /<type>wreck<\/type>/);
      restored.p.toggleSpot(saved.id, false);
      assert.equal(restored.p.summary.value.ok, false);
      assert.equal(restored.p.draft.value.userWaypoints.length, 1);
      restored.p.toggleSpot(saved.id, true);
      restored.p.removeWaypoint(saved.id);
      assert.deepEqual(restored.p.draft.value.ids, []);
      assert.deepEqual(restored.p.draft.value.userWaypoints, []);
    } finally { restored.p.dispose(); }
  } finally { p.dispose(); }
});

test('invalid names cannot save a point; 100-point cap retains the existing draft', () => {
  const {p, drop} = harness();
  try {
    drop(); p.saveWaypoint(' ', 'other');
    assert.equal(p.draft.value.userWaypoints, undefined);
    assert.ok(p.waypointPosition.value);
    for (let i = 0; i < 100; i++) { drop(); p.saveWaypoint(`Synthetic ${i}`, 'other'); }
    const previous = p.draft.value;
    drop(); p.saveWaypoint('Over limit', 'other');
    assert.equal(p.draft.value, previous);
    assert.match(p.actionStatus.value, /100 waypoints/);
  } finally { p.dispose(); }
});

test('freshness and last-moment protected-area checks apply to GPX and offline notes', async () => {
  let fresh = true, allowed = true;
  const boundary = {ready: () => fresh, pointAllowed: () => allowed,
    inspect: () => ({fresh, status: allowed ? 'allowed' : 'excluded', matches: [{name: 'Synthetic Reserve', agency: 'Test agency', url: 'https://example.org/rules'}]})};
  const {p, drop} = harness({boundary});
  try {
    drop(); p.saveWaypoint('Synthetic boundary point', 'hazard');
    assert.equal(p.summary.value.ok, true);
    allowed = false; p.tick.value++;
    assert.equal(p.protectedHits.value[0].matches[0].name, 'Synthetic Reserve');
    assert.equal(p.summary.value.ok, false);
    assert.equal(p.notesReady.value, true);
    await assert.rejects(p.exportFile('gpx'), /selected spot fails/);
    const html = await (await p.exportFile('notes')).text();
    assert.match(html, /Synthetic Reserve/);
    assert.match(html, /GPX withheld/);
    assert.ok(!html.includes(String(point.longitude)));
    fresh = false; p.tick.value++;
    assert.equal(p.notesReady.value, false);
    await assert.rejects(p.exportFile('gpx'), /unavailable or older/);
    await assert.rejects(p.exportFile('notes'), /unavailable or older/);
  } finally { p.dispose(); }
});

test('placement is explicit, one-shot, cancellable and bound to the region', () => {
  const picked = [];
  cancelWaypointPlacement();
  assert.equal(placeWaypoint(region.id, {lat: 1, lon: 2}), false);
  beginWaypointPlacement(region.id, at => picked.push(at));
  assert.equal(waypointPlacement.value, region.id);
  assert.equal(placeWaypoint(region.id, {lat: NaN, lon: 2}), false);
  assert.equal(placeWaypoint(region.id, {lat: 1, lon: 2}), true);
  assert.deepEqual(picked, [{latitude: 1, longitude: 2}]);
  assert.equal(placeWaypoint(region.id, {lat: 1, lon: 2}), false);
  beginWaypointPlacement(region.id, at => picked.push(at));
  assert.equal(placeWaypoint('another-region', {lat: 1, lon: 2}), false);
  assert.equal(waypointPlacement.value, null);
  beginWaypointPlacement(region.id, at => picked.push(at)); cancelWaypointPlacement();
  assert.equal(placeWaypoint(region.id, {lat: 1, lon: 2}), false);
  assert.equal(picked.length, 1);
});

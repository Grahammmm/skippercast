// SCA-295 / F16-10: the map preset with no map width must change nothing but the message.
// Synthetic reef data and in-memory storage only; no browser, network or live data.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createPlanner} from '../web/planner.ts';
import {draftKey} from '../dist/trip-export.js';
import {getRegion} from '../dist/region.js';

const region = getRegion(), now = new Date('2026-11-09T18:00:00Z');
const screen = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, coversGeometry: () => true, exportExclusions: () => ({features: [], checked_at: now.toISOString()})};
const point = (id, n) => ({id, label: id, name: id, latitude: 35 + n / 100, longitude: -121, habitat_grade: 'A', canonical_habitat: true, neighborhood_depth_ft: [90, 120], species_fit: {lingcod: 3, 'rockfish-reef': 3}, habitat_score: 90 - n, resolution_m: 2, evidence_confidence: {percent: 90}, area_ids: [`area-${id}`]});
const publication = {export_sha256: 'a'.repeat(64), status: 'ready', expires_at: '2099-12-31T00:00:00Z', region: region.id};
const reefs = {targets: [point('A', 1), point('B', 3), point('C', 4)], areas: ['A', 'B', 'C'].map((id, i) => ({id: `area-${id}`, target_ids: [id], geometry: {type: 'Polygon', coordinates: [[[-121, 35 + i / 100], [-120.999, 35 + i / 100], [-120.999, 35.001 + i / 100], [-121, 35 + i / 100]]]}})), publication};

function make({raw, width = 0} = {}) {
  const store = new Map(raw ? [[draftKey(region.id), raw]] : []), emitted = [], size = {x: width};
  const map = {getSize: () => ({x: size.x, y: size.x}), getBounds: () => ({getWest: () => -125, getEast: () => -115, getSouth: () => 30, getNorth: () => 40, contains: () => true})};
  const p = createPlanner({atlas: {targets: [], areas: []}, region, screen, map, getVisible: () => [], now: () => now, landWater: async () => () => ({state: 'water'}),
    loadReefs: async () => reefs, loadPorts: async () => ({ports: []}), emit: d => emitted.push(d),
    storage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v)}, nav: {open() {}, showMap() {}, conditions() {}}});
  return {p, store, emitted, size, raw: () => store.get(draftKey(region.id))};
}
const snap = h => JSON.stringify({draft: h.p.draft.value, ranked: h.p.ranked.value, dirty: h.p.filtersDirty.value, pending: h.p.restorePending.value, emitted: h.emitted.length, raw: h.raw()});
const MSG = 'Open the map to choose an area first. Your selection is retained.';

test('F16-10: map preset with no map keeps a dirty ranked plan and its export decision', async () => {
  const h = make();
  try {
    await h.p.selectBest();
    assert.equal(h.p.ranked.value, true, h.p.scopeStatus.value);
    h.p.filtersDirty.value = true;
    const before = snap(h), ids = [...h.p.draft.value.ids];
    assert.ok(h.p.draft.value.rankedPlan && ids.length);
    await assert.rejects(h.p.exportFile('gpx'), /Trip filters changed/);
    h.p.preset('map');
    assert.equal(snap(h), before, 'only the message may change');
    assert.equal(h.p.scopeStatus.value, MSG);
    assert.equal(h.p.filtersDirty.value, true);
    assert.deepEqual(h.p.draft.value.ids, ids);
    await assert.rejects(h.p.exportFile('gpx'), /Trip filters changed/);
  } finally { h.p.dispose(); }
});

test('F16-10: map preset with no map keeps a pending restoration and its export decision', async () => {
  const src = make(); await src.p.selectBest(); const raw = src.raw(); src.p.dispose();
  const h = make({raw});
  try {
    assert.equal(h.p.restorePending.value, true);
    const before = snap(h), meta = JSON.stringify(h.p.draft.value.rankedPlan);
    assert.notEqual(meta, 'null');
    await assert.rejects(h.p.exportFile('gpx'), /needs current reef data/);
    h.p.preset('map');
    assert.equal(snap(h), before, 'only the message may change');
    assert.equal(h.p.scopeStatus.value, MSG);
    assert.equal(JSON.stringify(h.p.draft.value.rankedPlan), meta);
    assert.equal(h.raw(), raw, 'storage still restores the same plan');
    await assert.rejects(h.p.exportFile('gpx'), /needs current reef data/);
  } finally { h.p.dispose(); }
});

test('F16-10 positive control: with a map the preset still replaces the selection and clears the blockers', async () => {
  const h = make({width: 512});
  try {
    await h.p.selectBest();
    h.p.filtersDirty.value = true;
    h.p.preset('map');
    assert.equal(h.p.filtersDirty.value, false);
    assert.equal(h.p.ranked.value, false);
    assert.equal(h.p.draft.value.rankedPlan, null);
    assert.match(h.p.scopeStatus.value, /spots selected/);
  } finally { h.p.dispose(); }
});

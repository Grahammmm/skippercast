import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {initProtectedAreas} from '../dist/protected-areas.js';
import {pointInGeometry} from '../dist/geo-screen.js';
import {getRegion} from '../dist/region.js';
import {buildExport, protectedPlanNotes} from '../dist/trip-export.js';
import {createPlanner} from '../web/planner.ts';
import {build} from 'esbuild';

const mpas = JSON.parse(readFileSync(new URL('../dist/data/protected-areas.geojson', import.meta.url)));
const morro = mpas.features.find(f => f.properties.NAME === 'Morro Bay SMR');
// Find an interior point in the committed ds582 polygon, not a synthetic square.
const vertices = morro.geometry.coordinates.flat(Infinity);
const xs = vertices.filter((_, i) => i % 2 === 0), ys = vertices.filter((_, i) => i % 2 === 1);
let inside;
for (let x = Math.min(...xs); !inside && x < Math.max(...xs); x += 0.0005) {
  for (let y = Math.min(...ys); y < Math.max(...ys); y += 0.0005) {
    if (pointInGeometry([x, y], morro.geometry)) { inside = {longitude: x, latitude: y}; break; }
  }
}
assert.ok(inside, 'real Morro Bay polygon contains the test point');
const target = {id: 'manual-morro', label: 'Synthetic saved reference', ...inside, neighborhood_depth_ft: [0, 0]};
const atlas = {targets: [target], areas: [], drifts: []};
const region = getRegion();
const draft = {name: 'Boundary review', date: '2026-10-20'};
const map = {getSize: () => ({x: 512}), getBounds: () => ({getWest: () => -122, getEast: () => -120, getSouth: () => 34, getNorth: () => 37})};
async function screenFixture() {
  const saved = {fetch: globalThis.fetch, document: globalThis.document};
  globalThis.fetch = async () => ({ok: true, json: async () => ({...mpas, checked_at: new Date().toISOString()})});
  globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}};
  try { return await initProtectedAreas(null, () => {}); }
  finally { Object.assign(globalThis, saved); }
}
const requestFor = screen => ({atlas, screen, ids: [target.id], region, allowResearch: true});

test('rendered plan names the selected boundary and keeps only context notes enabled', async () => {
  const bundle = await build({stdin: {contents: `export {Planner} from './web/app/Planner.tsx'; export {createPlanner} from './web/planner.ts'; export {h} from 'preact'; export {default as render} from 'preact-render-to-string';`, resolveDir: new URL('..', import.meta.url).pathname}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', jsxImportSource: 'preact'});
  const ui = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
  const screen = await screenFixture();
  const p = ui.createPlanner({atlas, screen, region, map, getVisible: () => [], storage: null,
    loadPorts: async () => null, emit() {}, nav: {open() {}, showMap() {}, conditions() {}}});
  try {
    p.add(target.id);
    p.setResearch(true);
    const html = ui.render(ui.h(ui.Planner, {model: p, open: false}));
    assert.match(html, /Morro Bay State Marine Reserve/);
    assert.match(html, /href="https:\/\/wildlife.ca.gov\/Conservation\/Marine\/MPAs\/Morro-Bay"/);
    assert.match(html, /id="export-download" disabled/);
    assert.match(html, /id="export-share" disabled/);
    assert.match(html, /id="export-notes">/);
  } finally { p.dispose(); }
});

test('manually added Morro Bay MPA point is named in plan and context notes; GPX stays blocked', async () => {
  const screen = await screenFixture();
  const p = createPlanner({atlas, screen, region, map, getVisible: () => [], storage: null,
    loadPorts: async () => null, emit() {}, nav: {open() {}, showMap() {}, conditions() {}}});
  try {
    p.add(target.id);
    assert.equal(p.summary.value.ok, false);
    assert.equal(p.notesReady.value, false, 'research opt-in still applies');
    p.setResearch(true);
    assert.equal(p.protectedHits.value[0].matches[0].name, 'Morro Bay State Marine Reserve');
    assert.equal(p.protectedHits.value[0].matches[0].url, 'https://wildlife.ca.gov/Conservation/Marine/MPAs/Morro-Bay');
    assert.equal(p.notesReady.value, true);
    await assert.rejects(p.exportFile('gpx'), /selected spot fails/);
    const file = await p.exportFile('notes'), html = await file.text();
    assert.match(file.name, /boundary-context.html$/);
    assert.match(html, /Morro Bay State Marine Reserve/);
    assert.match(html, /https:\/\/wildlife.ca.gov\/Conservation\/Marine\/MPAs\/Morro-Bay/);
    assert.match(html, /Boundaries are context; current rules are on the agency page/);
    assert.match(html, /GPX withheld/);
    assert.doesNotMatch(html, /<wpt|Approach notes|terrain score/);
    assert.ok(!html.includes(String(target.longitude)), 'no fishing coordinates in context report');
    p.restorePending.value = true;
    assert.equal(p.notesReady.value, false);
    p.restorePending.value = false;
    p.filtersDirty.value = true;
    assert.equal(p.notesReady.value, false);
    p.filtersDirty.value = false;
    const ready = screen.ready;
    screen.ready = () => false;
    p.tick.value++;
    assert.deepEqual(p.protectedHits.value, []);
    assert.equal(p.notesReady.value, false);
    await assert.rejects(p.exportFile('notes'), /unavailable or older/);
    screen.ready = ready;
  } finally { p.dispose(); }
});

test('context notes preserve freshness, validity, publication and consent gates', async () => {
  const screen = await screenFixture(), req = requestFor(screen);
  assert.throws(() => buildExport(req), /selected spot fails/);
  assert.throws(() => protectedPlanNotes({...req, allowResearch: false}, draft), /explicit opt-in/);
  assert.throws(() => protectedPlanNotes({...req, screen: {...screen, ready: () => false}}, draft), /unavailable or older/);
  assert.throws(() => protectedPlanNotes({...req, atlas: {...atlas, targets: [{...target, latitude: NaN}]}}, draft), /selected spot fails/);
  assert.throws(() => protectedPlanNotes({...req, atlas: {...atlas, targets: [{...target, canonical_habitat: true}], publication: {status: 'ready', expires_at: '2000-01-01'}}}, draft), /screening expired/);
  assert.throws(() => protectedPlanNotes({...req, screen: {...screen, inspect: undefined}}, draft), /selected spot fails/);
});

test('mixed selections and HTML text stay identification-only in a blocked report', async () => {
  const screen = await screenFixture();
  const mixed = {...atlas, targets: [{...target, label: '<script>bad</script>'}, {id: 'outside', label: 'Outside reference', longitude: -125, latitude: 35}]};
  const html = protectedPlanNotes({...requestFor(screen), atlas: mixed, ids: mixed.targets.map(t => t.id)}, draft);
  assert.match(html, /&lt;script&gt;bad&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>|Outside reference/);
  assert.match(html, /Other selected items are omitted/);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {checkGpx} from '../web/gpx-check.ts';
import {featuresGPX} from '../dist/gpx.js';
import {createPlanner} from '../web/planner.ts';
import {launchPoints} from '../web/launches.ts';
import {launchChoice} from '../web/reach.ts';
import {region as activeRegion} from '../web/state.ts';
const root = new URL('..', import.meta.url).pathname;
const region = {id: 'test-coast', name: 'Test Coast', timezone: 'UTC', mpa: {bounds: [-1, -1, 1, 1]}};
const screen = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, exportExclusions: () => ({features: [], checked_at: new Date().toISOString()})};
const map = {getSize: () => ({x: 10, y: 10}), getBounds: () => ({getWest: () => -1, getEast: () => 1, getNorth: () => 1, getSouth: () => -1})};
const place = {id: 'survey:rock', name: 'Survey <script> & "place"', latitude: .2, longitude: .3};
const settle = () => new Promise(r => setTimeout(r, 0));
function harness(extra = {}) {
  let time = Date.now(); const store = new Map();
  const p = createPlanner({atlas: {targets: [], areas: [], drifts: []}, screen, region, map, getVisible: () => [],
    storage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v)}, now: () => new Date(time),
    loadPorts: async () => ({ports: []}), emit() {}, nav: {open() {}, showMap() {}, conditions() {}}, ...extra});
  return {p, store, age: n => {time += n;}};
}
let ui;
async function components() {
  if (ui) return ui;
  const out = join(mkdtempSync(join(tmpdir(), 'handoff-')), 'ui.mjs');
  await build({stdin: {resolveDir: root, loader: 'ts', contents: `export {MarkCard} from './web/app/MarkCard.tsx'; export {Planner} from './web/app/Planner.tsx'; export {chartPick, markData, SURVEY_PICK} from './web/map/marks.ts'; export * as state from './web/state.ts'; export {h} from 'preact'; export {render} from 'preact-render-to-string';`}, bundle: true, platform: 'node', format: 'esm', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  return ui = await import(pathToFileURL(out).href);
}
const sample = readFileSync(new URL('./fixtures/gpx/handoff-sample.gpx', import.meta.url), 'utf8');
test('golden GPX passes and each delivery corruption fails specifically', () => {
  assert.deepEqual(checkGpx(sample, {waypoints: 3}), {ok: true});
  for (const [xml, count, problem] of [
    [sample, 4, 'Waypoint count mismatch'], [sample.replace('lat="0.1"', 'lat="91"'), 3, 'Invalid wpt lat'],
    [sample.replace('lon="0.1"', 'lon="NaN"'), 3, 'Invalid wpt lon'], [sample.replace('Atlas reef', ''), 3, 'Empty or malformed name'],
    [sample.replace('Survey place', 'ATLAS REEF'), 3, 'Duplicate waypoint name'], [sample.replace('Atlas reef', '\u0001Atlas reef'), 3, 'XML-forbidden control character'],
    [sample.replace('</gpx>', ''), 3, 'Missing or invalid GPX root close'],
    [sample.replace('</gpx>', '<trk><name>Track</name><trkseg></trk></gpx>'), 3, 'Unbalanced trk tag'],
    [sample.replace(/^<\?xml[^>]+>\n/, ''), 3, 'Missing XML declaration'],
  ]) { const c = checkGpx(xml, {waypoints: count}); assert.equal(c.ok, false); assert.ok(c.problems.includes(problem), JSON.stringify(c)); }
});
test('only colliding waypoint names change; cmt ids remain original, including suffix-shaped originals', () => {
  const user = (name, id) => ({name, id, latitude: 0, longitude: 0, user_waypoint: true, category: 'other'});
  const points = [user('A', 'u1'), user('a', 'u2'), user('A (2)', 'u3')];
  const f = {selected: points, waypoints: points, areas: [], drifts: []};
  const xml = featuresGPX({}, f, 'Day');
  assert.deepEqual([...xml.matchAll(/<wpt[^>]*><name>(.*?)<\/name>/g)].map(m => m[1]), ['A', 'a (2)', 'A (2) (2)']);
  assert.match(xml, /<cmt>u2<\/cmt>/); assert.equal(checkGpx(xml, {waypoints: 3}).ok, true);
  const dir = mkdtempSync(join(tmpdir(), 'gpx-before-')), old = join(dir, 'gpx.mjs');
  // Checked-in copy of dist/gpx.js before this change (main at 20e58f5b), so CI needs no remote ref.
  const source = readFileSync(new URL('./fixtures/gpx/gpx-baseline-20e58f5b.js.txt', import.meta.url), 'utf8').replace("'./spot-ranking.js'", JSON.stringify(pathToFileURL(join(root, 'dist/spot-ranking.js')).href));
  writeFileSync(old, source);
  return import(pathToFileURL(old).href).then(before => {
    for (const atlas of [JSON.parse(readFileSync(join(root, 'dist/data/atlas.json')))]) {
      const selected = atlas.targets.slice(0, 3), features = {selected, waypoints: selected, areas: [], drifts: []};
      assert.equal(featuresGPX(atlas, features, 'Day'), before.featuresGPX(atlas, features, 'Day'));
    }
  });
});
test('actual survey picks round to 5 decimals, categories and kelp label survive card-to-planner data flow', async () => {
  const u = await components(); u.state.configureStore({v2: true, storage: null}); u.state.syncFromURL('https://s.test/map?region=test-coast&presentation=chart');
  const {p} = harness();
  for (const [kind, category] of [['rock', 'reef'], ['mixed', 'reef'], ['sediment', 'other'], ['kelp', 'other']]) {
    u.markData.value = {region, atlas: null, geology: null, survey: {type: 'FeatureCollection', features: [{type: 'Feature', geometry: null, properties: {id: kind, habitat_kind: kind, name: 'Place'}}]}};
    const mark = u.chartPick(u.SURVEY_PICK, {id: kind}, null, {lat: .234567, lon: .345678});
    assert.deepEqual(mark.position, {latitude: .23457, longitude: .34568});
    assert.match(u.render(u.h(u.MarkCard, {mark})), />Add to trip<\/button>/);
    const name = kind === 'kelp' ? `${mark.kind} · ${mark.name}` : mark.name;
    const id = p.addPlace({id: mark.id, name, ...mark.position, shore: category === 'other'});
    assert.equal(id, `user:survey-${kind}`); assert.equal(p.addPlace({id: mark.id, name, ...mark.position}), id);
    assert.equal(p.draft.value.userWaypoints.at(-1).category, category);
    if (kind === 'kelp') assert.match(p.draft.value.userWaypoints.at(-1).name, /^Historical kelp detections · /);
  }
  assert.equal(p.draft.value.ids.length, 4);
  for (let i = 4; i < 100; i++) p.addPlace({...place, id: `survey:p${i}`});
  assert.equal(p.addPlace({...place, id: 'survey:overflow'}), null); assert.match(p.actionStatus.value, /Limit: 100 waypoints/);
  p.dispose(); u.markData.value = null;
});
test('nonexportable cards render their precise reason and disabled actions', async () => {
  const u = await components();
  for (const [id, reason] of [['survey:s', 'Pick this place on the map to export its position'], ['geology:g', 'Geology unit: context for reading the map, not a place to fish'], ['charter:c', 'Charter-reported grounds and AIS activity are not exported: they show apparent activity, not a verified place.'], ['fleet:f', 'Charter-reported grounds and AIS activity are not exported: they show apparent activity, not a verified place.']]) {
    const html = u.render(u.h(u.MarkCard, {mark: {id, name: 'Place', kind: 'Context', reading: '', source: 'Synthetic', basis: ''}}));
    assert.ok(html.includes(reason)); assert.match(html, /<button disabled[^>]*>.*?Add to trip<\/button>/s); assert.match(html, /<button disabled[^>]*>.*?GPX<\/button>/s);
  }
});
test('launch defaults off, follows chosen ramp, persists, counts in GPX/notes; absent/malformed published list hides control', async () => {
  const ramps = ['one', 'two'].map((id, i) => ({id, name: `Ramp ${id}`, latitude: .1 + i / 10, longitude: .1}));
  launchPoints.value = {region: region.id, points: ramps}; launchChoice.value = {[region.id]: 'one'};
  const {p, store} = harness(); p.addPlace(place); assert.equal(p.draft.value.launchId, undefined);
  assert.equal(p.summary.value.counts.waypoints, 1); p.setLaunch(true); assert.equal(p.summary.value.counts.waypoints, 2);
  assert.match(await (await p.exportFile('gpx')).text(), /<name>Launch · Ramp one<\/name>/);
  launchChoice.value = {[region.id]: 'two'};
  assert.match(await (await p.exportFile('gpx')).text(), /lat="0.2" lon="0.1"><name>Launch · Ramp two/);
  const notes = await (await p.exportFile('notes')).text(); assert.match(notes, /Launch · Ramp two/); assert.match(notes, /Survey &lt;script&gt; &amp; &quot;place&quot;/); assert.match(notes, /User waypoint · other/);
  assert.equal(JSON.parse([...store.values()][0]).launchId, 'one');
  const restore = harness({storage: {getItem: () => [...store.values()][0], setItem() {}}}).p;
  assert.equal(restore.draft.value.launchId, 'one'); restore.dispose();
  const u = await components(); launchPoints.value = {region: region.id, points: []};
  assert.equal(p.launch.value, undefined); assert.doesNotMatch(u.render(u.h(u.Planner, {model: p, open: false})), /Include launch ramp/);
  p.dispose(); launchPoints.value = null; launchChoice.value = {};
});
test('protected survey export names its hit, removal clears it; unavailable/stale screens produce no file', async () => {
  const s = {...screen, pointAllowed: t => t.latitude !== .2, inspect: t => ({fresh: true, status: t.latitude === .2 ? 'excluded' : 'allowed', matches: [{name: 'Synthetic closure', inside: true, agency: 'Test', url: 'https://example.org'}]})};
  const {p} = harness({screen: s}); const id = p.addPlace(place); p.addPlace({...place, id: 'survey:clear', latitude: .4});
  await assert.rejects(p.exportFile('gpx'), /protected-area check/);
  const u = await components(), html = u.render(u.h(u.Planner, {model: p, open: false}));
  assert.ok(html.includes('Not exported: Survey &lt;script> &amp; &quot;place&quot; is inside Synthetic closure'), html);
  assert.match(html, /Remove Survey/); p.removeWaypoint(id); assert.equal(checkGpx(await (await p.exportFile('gpx')).text(), {waypoints: 1}).ok, true); p.dispose();
  for (const reason of ['missing', 'older than 36h']) { const {p} = harness({screen: {...screen, ready: () => false}}); p.addPlace(place); await assert.rejects(p.exportFile('gpx'), /unavailable or older than 36 hours/, reason); p.dispose(); }
});
test('prepared share is synchronous, failures download, cancel does not, absent canShare downloads', async () => {
  const oldDoc = globalThis.document, oldNav = Object.getOwnPropertyDescriptor(globalThis, 'navigator'), oldTimeout = globalThis.setTimeout;
  let downloads = 0, shares = 0, crossed = false, reject = '', supported = true;
  globalThis.document = {createElement: () => ({click() {downloads++;}, remove() {}}), body: {append() {}}};
  globalThis.setTimeout = (fn, ms, ...args) => ms === 60000 ? {unref() {}} : oldTimeout(fn, ms, ...args);
  Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {canShare: () => supported, share() {shares++; assert.equal(crossed, false, 'share stays in the tap call stack'); return reject ? Promise.reject(Object.assign(new Error(reject), {name: reject})) : Promise.resolve();}}});
  const {p, age} = harness();
  try {
    p.addPlace(place); await settle(); await settle();
    for (const name of ['', 'NotAllowedError', 'TypeError', 'DataError', 'AbortError']) {
      reject = name; crossed = false; const before = downloads;
      queueMicrotask(() => {crossed = true;}); const done = p.deliver('share'); await done;
      assert.equal(downloads - before, name && name !== 'AbortError' ? 1 : 0);
      assert.match(p.actionStatus.value, name === 'AbortError' ? /Share cancelled/ : name ? /could not open the share sheet, so the file was downloaded/ : /Confirm the import/);
    }
    supported = false; await p.deliver('share'); assert.match(p.actionStatus.value, /This browser cannot share/);
    const before = shares; age(60000); await p.deliver('share'); assert.equal(shares, before); assert.equal(p.actionStatus.value, 'File ready — tap Share again');
    p.edit({name: 'Changed'}); await p.deliver('share'); assert.equal(shares, before);
    p.tick.value++; await p.deliver('share'); assert.equal(shares, before);
    activeRegion.value = 'another-region'; await p.deliver('share'); assert.equal(shares, before); assert.match(p.actionStatus.value, /Region changed/); activeRegion.value = null;
    p.dispose(); await p.deliver('gpx');
  } finally { p.dispose(); globalThis.document = oldDoc; globalThis.setTimeout = oldTimeout; if (oldNav) Object.defineProperty(globalThis, 'navigator', oldNav); else delete globalThis.navigator; activeRegion.value = null; }
});

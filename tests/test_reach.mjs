// #644 (walkthrough slice 5, owner decision C): the range to consider for Boat
// and Kayak, kept on the device with no default (web/reach.ts); the "Where to
// look" filter it drives (web/ranking.ts); the Chart's reach ring
// (web/map/reach.ts); the Your limits field and the brief's range control
// (web/app/LimitsPanel.tsx, web/brief/WhereToLook.tsx) rendered to a string;
// and the trip planner's starting distance (web/planner.ts). Offline: the
// atlas and boundaries are the committed snapshots.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {distanceNm} from '../dist/spot-ranking.js';
import {assessScreen} from '../web/map/habitat.ts';
import {LAYERS, layerEntry} from '../web/map/layers.ts';
import {REACH_LABEL, REACH_LINE, REACH_SOURCE, reachFeatures, reachLabel, reachOverlay} from '../web/map/reach.ts';
import {readPalette} from '../web/map/palette.ts';
import {harborOrigin, ranking} from '../web/ranking.ts';
import * as reach from '../web/reach.ts';
import {configureStore, STORAGE_KEYS} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const MORRO = read('regions/morro-bay/region.json'), ATLAS = read('data/atlas.json');
const DATA = {region: {...MORRO, id: 'morro-bay'}, atlas: ATLAS, survey: null, geology: null};
const NOW = Date.now();
const CHECKED = assessScreen({areas: read('data/protected-areas.geojson').features, checkedAt: new Date(NOW).toISOString(), live: true}, NOW);
const inputs = (patch = {}) => ({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: CHECKED, terrain: {state: 'unavailable'}, now: NOW, ...patch});
const HARBOR = harborOrigin(DATA);
const CLAIMS = /safe|passage|reachable|guarantee|hotspot|catch/i;

test('the range is per profile, on the device, with no default; blank, out-of-range or unreadable values save nothing', () => {
  const data = new Map();
  configureStore({storage: {getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v)}});
  assert.deepEqual(reach.loadReach(), {}, 'nothing saved: no range');
  assert.equal(reach.reachFor('boat'), null);
  assert.equal(reach.saveReach('boat', '12.3'), 12.5, 'rounds to the half mile');
  assert.equal(reach.saveReach('kayak', 3), 3);
  assert.deepEqual(JSON.parse(data.get(STORAGE_KEYS.reach)), {boat: 12.5, kayak: 3});
  assert.equal(reach.reachFor('boat'), 12.5);
  for (const p of ['shore', 'spear']) assert.equal(reach.reachFor(p), null, `${p} has no range`);
  for (const bad of ['', ' ', 'far', 0, 0.5, 61, NaN, null]) assert.equal(reach.parseReach('boat', bad), null, `${JSON.stringify(bad)} is no boat range`);
  assert.equal(reach.parseReach('kayak', 11), null, 'a kayak range stops at 10 nm');
  assert.equal(reach.parseReach('kayak', 0.5), 0.5);
  assert.equal(reach.saveReach('boat', ''), null, 'blank clears it');
  assert.deepEqual(reach.loadReach(), {kayak: 3}, 'and only that profile');
  data.set(STORAGE_KEYS.reach, '{oops');
  assert.deepEqual(reach.loadReach(), {}, 'unreadable storage: no range');
  data.set(STORAGE_KEYS.reach, JSON.stringify({boat: 400, kayak: '2', shore: 5}));
  assert.deepEqual(reach.loadReach(), {kayak: 2}, 'stored values are re-checked; other profiles dropped');
  configureStore({storage: {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('quota'); }}});
  assert.equal(reach.saveReach('boat', 8), 8);
  assert.equal(reach.reachFor('boat'), 8, 'blocked storage still holds the range for the page');
  configureStore({storage: null});
  reach.reachRange.value = {};
});

test('the ring is the range on the sphere the distances use, closed, around the harbor', () => {
  assert.ok(HARBOR, 'Morro Bay names a harbor');
  for (const nm of [1, 12.5, 60]) {
    const ring = reach.reachRing(HARBOR, nm);
    assert.deepEqual(ring.at(-1), ring[0], 'closed');
    assert.equal(ring.length, 129);
    for (const [longitude, latitude] of ring) assert.ok(Math.abs(distanceNm(HARBOR, {latitude, longitude}) - nm) < 0.001, `${nm} nm ring point`);
  }
  assert.ok(reach.reachRing(HARBOR, 5)[0][1] > HARBOR.latitude, 'starts due north, where the label sits');
});

test('a range keeps "Where to look" to places inside it and says so; none, or no harbor, ranks as before', () => {
  const all = ranking(inputs());
  assert.equal(all.reach, undefined);
  assert.ok(all.picks.length > 0);
  const far = Math.max(...all.picks.map(p => p.nm));
  const cut = Math.max(1, Math.floor(far) - 1);
  const near = ranking(inputs({reachNm: cut}));
  assert.equal(near.reach, cut);
  assert.ok(near.picks.every(p => p.nm !== null && p.nm <= cut), 'every pick inside the range');
  assert.match(near.basis, new RegExp(`Only places within your ${cut} nm range are listed\\.`));
  assert.doesNotMatch(near.basis + near.empty, CLAIMS);
  // Places outside the range never appear, even when the in-range list is short.
  const outside = ATLAS.targets.filter(t => distanceNm(HARBOR, t) > cut).map(t => t.id);
  assert.ok(near.picks.every(p => !outside.includes(p.id)));
  const tiny = ranking(inputs({reachNm: 0.5}));
  assert.deepEqual(tiny.picks, []);
  assert.equal(tiny.empty, `No surveyed reef marks within 300 ft and 0.5 nm of ${HARBOR.name} for this target.`);
  // Kayak keeps its own depth limit with the range.
  assert.match(ranking(inputs({profile: 'kayak', reachNm: 0.5})).empty, /within 120 ft and 0\.5 nm of/);
  // Without a harbor position the range cannot be measured, so it is not applied.
  const noHarbor = {...DATA, region: {...DATA.region, harbor: undefined}};
  const unmeasured = ranking(inputs({data: noHarbor, reachNm: 1}));
  assert.equal(unmeasured.reach, undefined);
  assert.equal(unmeasured.picks.length, ranking(inputs({data: noHarbor})).picks.length);
  assert.doesNotMatch(unmeasured.basis, /Only places within/);
});

test('the Chart ring: a dashed line and one label, drawn only with a harbor and a range, under the marks in the registry', () => {
  assert.deepEqual(reachFeatures(null, 10).features, []);
  assert.deepEqual(reachFeatures(HARBOR, null).features, []);
  const fc = reachFeatures(HARBOR, 12);
  assert.deepEqual(fc.features.map(f => [f.geometry.type, f.properties.kind]), [['LineString', 'ring'], ['Point', 'label']]);
  assert.equal(fc.features[1].properties.label, `12 nm from ${HARBOR.name} · straight line, not a route`);
  assert.equal(reachLabel(2.5, 'Morro Bay'), '2.5 nm from Morro Bay · straight line, not a route');
  const sentinel = readPalette(name => `token(${name})`);
  const o = reachOverlay(sentinel, fc);
  assert.deepEqual(Object.keys(o.sources), [REACH_SOURCE]);
  assert.deepEqual(o.layers.map(l => l.id), [REACH_LINE, REACH_LABEL]);
  assert.ok(o.layers[0].paint['line-dasharray'], 'dashed');
  assert.equal(o.layers[0].paint['line-color'], 'token(blue)');
  const ids = LAYERS.map(e => e.id);
  assert.ok(ids.indexOf('reach') < ids.indexOf('marks'), 'under the marks');
  assert.deepEqual(layerEntry('reach').sources, [REACH_SOURCE]);
  assert.doesNotMatch(layerEntry('reach').basis + layerEntry('reach').legend[0].label, /safe|reachable|guarantee/i);
});

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'reach-')), 'reach.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {LimitsForm} from './web/app/LimitsPanel.tsx';
      export {WhereToLook, pickRun} from './web/brief/WhereToLook.tsx';
      export {cruiseSpeed} from './web/limits.ts';
      export {reachRange} from './web/reach.ts';
      export {profile} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

test('Your limits carries the range for Boat and Kayak, blank with no default; Shore and Spear do not', async () => {
  const {LimitsForm, render, h, reachRange} = await load();
  reachRange.value = {};
  const boat = render(h(LimitsForm, {profile: 'boat'}));
  assert.match(boat, /Range to consider <span class="ui-mono">\(nm, one way\)<\/span>/);
  assert.match(boat, /<input[^>]*name="reach"[^>]*value(?:="")? aria-describedby/, 'blank until the user types one');
  assert.match(boat, /No default · 1–60 · straight line from the harbor, not a route · blank clears it/);
  assert.match(render(h(LimitsForm, {profile: 'kayak'})), /name="reach"[^>]*max="10"/);
  reachRange.value = {kayak: 2.5};
  assert.match(render(h(LimitsForm, {profile: 'kayak'})), /name="reach"[^>]*value="2.5"/);
  for (const p of ['shore', 'spear']) assert.doesNotMatch(render(h(LimitsForm, {profile: p})), /name="reach"/);
  reachRange.value = {};
});

test('"Where to look" asks for a range or shows it for Boat and Kayak, and a Boat pick shows its run time at the saved speed', async () => {
  const {WhereToLook, pickRun, render, h, profile, cruiseSpeed, reachRange} = await load();
  const pick = {id: 'a', kind: 'spot', name: 'Reef a', distance: '7.4 nm', nm: 7.4, depth: '~60–90 ft', fit: 'Fits', reason: 'Hard bottom.'};
  const r = {source: 'atlas', label: 'Survey reef atlas', basis: 'b', picks: [pick], empty: '', harbor: 'Morro Bay'};
  profile.value = 'boat'; reachRange.value = {}; cruiseSpeed.value = null;
  let html = render(h(WhereToLook, {ranking: r}));
  assert.match(html, />Set range</);
  assert.doesNotMatch(html, /run ≥/, 'no speed: no run time');
  reachRange.value = {boat: 12}; cruiseSpeed.value = 20;
  html = render(h(WhereToLook, {ranking: r}));
  assert.match(html, /data-reach="12"[^>]*>Range 12 nm</);
  assert.match(html, /7\.4 nm · ~60–90 ft · run ≥ 25 min</);
  assert.equal(pickRun(7.4, 20), ' · run ≥ 25 min', '22.2 min rounds up to 25');
  assert.equal(pickRun(null, 20), '');
  assert.equal(pickRun(3, null), '');
  profile.value = 'kayak';
  html = render(h(WhereToLook, {ranking: r}));
  assert.match(html, />Set range</, 'kayak has its own range');
  assert.doesNotMatch(html, /run ≥/, 'run times are the Boat brief\'s');
  profile.value = 'shore'; assert.doesNotMatch(render(h(WhereToLook, {ranking: r})), /app-where-range/);
  profile.value = 'spear'; assert.doesNotMatch(render(h(WhereToLook, {ranking: r})), /data-reach|Set range/, 'Spear shows its dive limits instead (tests/test_spear_kayak.mjs)');
  profile.value = 'boat';
  const {harbor: _, ...unmeasured} = r;
  assert.doesNotMatch(render(h(WhereToLook, {ranking: unmeasured})), /app-where-range/, 'no harbor to measure from: no range shown, none applied');
  profile.value = 'boat'; reachRange.value = {}; cruiseSpeed.value = null;
});

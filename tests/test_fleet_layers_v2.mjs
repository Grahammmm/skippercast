// Charter fleet activity in v2 (FE-24, docs/plans/front-end/dev-plan.md): the admin part of the
// Charter fleet entry, ported from dist/fleet-activity.js. Access is v1's own check (/api/session,
// then the map API's filters probe, a 404 while either fleet flag is off); the features are
// synthetic and every request is answered by a fake fetch (offline).
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {signal} from '@preact/signals';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import * as v1 from '../dist/fleet-activity.js';
import {ACTIVITY_LAYERS} from '../web/map/charter-grounds.ts';
import {
  ACTIVITY, FLEET_EVENTS, FLEET_HEAT, FLEET_SOURCE, FLEET_TRACKS, FLEET_TRACKS_DASHED, activityAccess, activityCollections, activityMark,
  activityOn, activityOverlay, activityStatus, createFleetActivity, toggleActivity, viewBBox,
} from '../web/map/fleet.ts';
import {layerEntry} from '../web/map/layers.ts';
import {MARK_PICK, markData} from '../web/map/marks.ts';
import {readPalette} from '../web/map/palette.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url);
const sentinel = readPalette(name => `token(${name})`);
const until = async (ok, what) => { for (let i = 0; i < 200 && !ok(); i++) await new Promise(r => setTimeout(r, 5)); assert.ok(ok(), what); };

const EVENT = {type: 'Feature', id: 'ev-1', geometry: {type: 'Point', coordinates: [-120.9, 35.3]}, properties: {layer: 'event', id: 'ev-1', vessel_name: 'Test Boat',
  kind: 'drift-anchor', dwell_min: 49, local_date: '2026-09-01', started_at: '2026-09-01T16:00:00Z', ended_at: '2026-09-01T16:49:00Z', port_id: 'morro-bay',
  trip_type: 'half-day', basis: 'inferred-from-movement', source: 'aisstream', rights: 'internal', planning_only: false}};
const TROLL = {...EVENT, id: 'ev-2', properties: {...EVENT.properties, id: 'ev-2', kind: 'troll', dwell_min: 4, planning_only: true}};
const SEGMENT = (id, kind, extra = {}) => ({type: 'Feature', id, geometry: {type: 'LineString', coordinates: [[-120.9, 35.3], [-120.95, 35.32]]},
  properties: {layer: 'track', id, trip_id: 't-1', segment_kind: kind, vessel_name: 'Test Boat', local_date: '2026-09-01', departed_at: '2026-09-01T14:00:00Z',
    returned_at: null, depart_port_id: 'morro-bay', distance_nm: 12.25, max_offshore_nm: 4, fishing_min: 95, rights: 'internal', planning_only: false, ...extra}});
const CELL = (id, dwell) => ({type: 'Feature', id, geometry: {type: 'Polygon', coordinates: [[[-121, 35], [-120.99, 35], [-120.99, 35.01], [-121, 35.01], [-121, 35]]]},
  properties: {layer: 'heat', id, kind: 'drift-anchor', dwell_min: dwell, vessels_n: 3, events_n: 7, first_date: '2026-08-01', last_date: '2026-09-30', rights: 'internal'}});
const result = features => ({features, more: false, ignored: [], trips: 1});

test('features become the three sources with v1\'s sizes; the overlay is heat, tracks, dashed tracks, events in tokens only', () => {
  const data = activityCollections(v1, {events: result([EVENT, TROLL]), tracks: result([SEGMENT('s1', 'fishing-drift'), SEGMENT('s2', 'gap'), SEGMENT('s3', 'transit', {planning_only: true})]),
    heat: result([CELL('c1', 100), CELL('c2', 25)])});
  assert.deepEqual(data.events.features.map(f => f.properties), [
    {key: 'ev-1', radius: v1.eventRadius(49), drift: true, planning: false}, {key: 'ev-2', radius: 4, drift: false, planning: true}]);
  assert.equal(v1.eventRadius(49), 14, 'radius ∝ √dwell');
  assert.deepEqual(data.tracks.features.map(f => [f.properties.key, f.properties.width, f.properties.dashed]), [['s1', 4, false], ['s2', 2, true], ['s3', 2, true]],
    'gaps and NOAA planning-only rows dashed');
  assert.deepEqual(data.heat.features.map(f => f.properties.opacity), [0.7, v1.heatOpacity(25, 100)], 'opacity ∝ dwell against the heaviest drawn cell');
  assert.deepEqual(activityCollections(v1, {}).events.features, []);

  const o = activityOverlay(sentinel, data);
  assert.deepEqual(o.layers.map(l => l.id), [...ACTIVITY_LAYERS]);
  assert.deepEqual([FLEET_HEAT, FLEET_TRACKS, FLEET_TRACKS_DASHED, FLEET_EVENTS], [...ACTIVITY_LAYERS]);
  assert.deepEqual(Object.keys(o.sources).sort(), Object.values(FLEET_SOURCE).sort());
  const colours = o.layers.flatMap(l => Object.entries(l.paint).filter(([k]) => /color$/.test(k)).map(([, v]) => v));
  assert.ok(colours.length >= 5);
  for (const c of colours) assert.equal(c, 'token(amber)', 'the --fleet (--amber) family only');
});

test('Accept 2: every card says the activity is inferred from movement', () => {
  const cards = [activityMark(v1, 'events', EVENT.properties, 'America/Los_Angeles'), activityMark(v1, 'events', TROLL.properties, 'America/Los_Angeles'),
    activityMark(v1, 'tracks', SEGMENT('s1', 'fishing-troll').properties, 'America/Los_Angeles'), activityMark(v1, 'heat', CELL('c1', 130).properties, 'America/Los_Angeles')];
  for (const card of cards) {
    assert.ok(card.reading.endsWith(v1.INFERRED), card.id);
    assert.match(card.basis, /^Inferred from movement; filters in the Fleet view\./);
  }
  assert.equal(cards[0].reading, `Drift or anchor · 49 min on 2026-09-01, 9:00 AM–9:49 AM · Morro bay · Half day. ${v1.INFERRED}`);
  assert.equal(cards[0].kind, 'Fleet activity · admin');
  assert.equal(cards[1].kind, 'Fleet activity · admin · NOAA planning-only');
  assert.match(cards[1].basis, /keep it off paid surfaces\./);
  assert.match(cards[2].reading, /^Troll segment · trip of 2026-09-01, 7:00 AM–open · Morro bay · 12\.3 nm, furthest 4\.0 nm offshore · fishing time 1 hr 35 min\./);
  assert.match(cards[3].reading, /^2 hr 10 min total dwell · 3 boats · 7 stops · 2026-08-01 to 2026-09-30\./);
  for (const id of ['fleet-heat', 'fleet-tracks', 'fleet-events']) assert.equal(layerEntry(id).basis, 'Inferred from movement; filters in the Fleet view.');
  assert.match(v1.statusText({events: result([EVENT])}), /inferred from movement/, 'the legend\'s status line');
});

test('the map\'s bounds, clamped as v1\'s mapBBox', () => {
  const view = (w, h) => ({size: () => ({width: w, height: h}), unproject: (x, y) => ({lon: -121 + x / 1000, lat: 35.5 - y / 1000})});
  assert.deepEqual(viewBBox(view(200, 100)), [-121, 35.4, -120.8, 35.5]);
  assert.equal(viewBBox(view(0, 0)), null);
});

/** A fake engine and fetch; `admin` and `flags` answer v1's access check as server/fleet/map.ts does. */
function harness({admin, flags}) {
  const asked = [], calls = [];
  const fetchFn = async url => {
    asked.push(url);
    const ok = body => ({ok: true, status: 200, json: async () => body}), missing = {ok: false, status: 404, json: async () => ({})};
    if (url === '/api/session') return ok({is_admin: admin});
    const u = new URL(url, 'https://s.test');
    if (!admin || !flags) return missing;
    if (u.pathname === '/api/fleet/map/filters') return ok({region: u.searchParams.get('region')});
    const layer = u.pathname.split('/').pop();
    const features = {events: [EVENT, TROLL], tracks: [SEGMENT('s1', 'fishing-drift'), SEGMENT('s2', 'gap')], heat: [CELL('c1', 60)]}[layer];
    return ok({type: 'FeatureCollection', features, meta: {next: null, trips: 1, ignored: []}});
  };
  const view = {size: () => ({width: 400, height: 300}), unproject: (x, y) => ({lon: -121 + x / 1000, lat: 35.5 - y / 1000}), on: () => () => {}};
  const engine = signal({view, setOverlay: (layer, o, before) => calls.push(['overlay', layer, o && o.layers.map(l => l.id), before ?? null]),
    setData: (id, data) => calls.push(['data', id, data.features.length])});
  return {asked, calls, engine, fetchFn};
}

function open(t, h, layers = 'fleet') {
  globalThis.location = {href: `https://s.test/map?region=morro-bay&layers=${layers}`};
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  markData.value = {region: {id: 'morro-bay', jurisdiction_id: 'california-central', assets: {}}, atlas: null, survey: null, geology: null};
  const fleet = createFleetActivity({engine: h.engine, fetchFn: h.fetchFn, palette: () => sentinel});
  t.after(() => { fleet.destroy(); markData.value = null; activityOn.value = []; });
  return fleet;
}

test('nothing is asked while the Charter fleet entry is off', async t => {
  const off = harness({admin: true, flags: true});
  open(t, off, 'seafloor');
  await new Promise(r => setTimeout(r, 50));
  assert.deepEqual(off.asked, [], 'the access check waits for the entry');
  assert.equal(activityAccess.value, false);
});

test('Accept 1: a visitor gets no activity options and never calls the map API', async t => {
  const visitor = harness({admin: false, flags: true});
  open(t, visitor);
  await until(() => visitor.asked.length === 1, 'v1 asks the session');
  await new Promise(r => setTimeout(r, 30));
  assert.deepEqual(visitor.asked, ['/api/session'], 'a visitor never calls the map API');
  assert.equal(activityAccess.value, false);
});

test('Accept 1: an admin with a fleet flag off gets the 404 and no options', async t => {
  const h = harness({admin: true, flags: false});
  open(t, h);
  await until(() => h.asked.length === 2, 'v1 probes the filters');
  assert.deepEqual(h.asked, ['/api/session', '/api/fleet/map/filters?region=CA']);
  await new Promise(r => setTimeout(r, 30));
  assert.equal(activityAccess.value, false);
});

test('an admin with both flags gets the options; each loads for the map\'s bounds only while on and draws under the clouds and marks', async t => {
  const h = harness({admin: true, flags: true});
  const fleet = open(t, h);
  await until(() => activityAccess.value, 'the filters probe answers');
  assert.deepEqual(h.asked, ['/api/session', '/api/fleet/map/filters?region=CA']);
  assert.equal(activityStatus.value, '', 'off by default, as v1');
  toggleActivity('events', true);
  await until(() => h.calls.some(c => c[1] === FLEET_SOURCE.events), 'events draw');
  assert.equal(h.asked[2], '/api/fleet/map/events?region=CA&bbox=-121%2C35.2%2C-120.6%2C35.5');
  assert.deepEqual(h.calls[0], ['overlay', 'fleet-activity', null, null], 'nothing drawn before an option is on');
  assert.deepEqual(h.calls[1], ['overlay', 'fleet-activity', [...ACTIVITY_LAYERS], [MARK_PICK]]);
  assert.deepEqual(h.calls.slice(2).map(c => c.slice(1)), [[FLEET_SOURCE.events, 2], [FLEET_SOURCE.tracks, 0], [FLEET_SOURCE.heat, 0]]);
  assert.equal(activityStatus.value, '2 stops · inferred from movement.');
  const card = fleet.pick.mark(FLEET_EVENTS, {key: 'ev-1'});
  assert.equal(card.name, 'Test Boat');
  assert.ok(card.reading.endsWith(v1.INFERRED));
  assert.equal(fleet.pick.mark(FLEET_HEAT, {key: 'c1'}), null, 'heat is not loaded');
  assert.deepEqual(fleet.pick.layers, [FLEET_EVENTS, FLEET_TRACKS, FLEET_TRACKS_DASHED, FLEET_HEAT]);
  assert.equal(fleet.pick.ordered, true, 'among the Chart\'s own picks, under the marks');

  toggleActivity('heat', true);
  await until(() => activityStatus.value.includes('heat'), 'heat loads');
  assert.deepEqual(activityOn.value, ['events', 'heat']);
  assert.equal(activityStatus.value, '2 stops · 1 heat cells · inferred from movement.');
  assert.ok(fleet.pick.mark(FLEET_HEAT, {key: 'c1'}).reading.endsWith(v1.INFERRED));

  for (const name of ACTIVITY) toggleActivity(name, false);
  await until(() => h.calls.at(-1)[2] === null, 'the overlay leaves');
  assert.equal(activityStatus.value, '');
});

test('Accept 1: the rail offers the activity layers only with access; the legend keys them with v1\'s status line', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'fleet-rail-')), 'rail.mjs');
  await build({stdin: {resolveDir: ROOT.pathname, loader: 'ts', contents: `
      export {LayerRail} from './web/app/LayerRail.tsx';
      export {Legend} from './web/app/Legend.tsx';
      export {activityAccess, activityOn, activityStatus} from './web/map/fleet.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  const m = await import(pathToFileURL(out).href);
  globalThis.location = {href: 'https://s.test/map?region=morro-bay&presentation=chart&layers=fleet'};
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(location.href);
  const options = html => [...html.matchAll(/<label class="app-rail-option">.*?<\/label>/g)].map(x => x[0].replace(/<[^>]+>/g, ''));
  assert.deepEqual(options(m.render(m.h(m.LayerRail))), [], 'absent, not disabled');
  m.activityAccess.value = true;
  assert.deepEqual(options(m.render(m.h(m.LayerRail))), ['Fleet events · admin', 'Fleet tracks · admin', 'Fleet heat · admin']);
  m.activityOn.value = ['events'];
  m.activityStatus.value = '2 stops · inferred from movement.';
  const legend = m.render(m.h(m.Legend));
  assert.match(legend, /data-layer="fleet-events"/);
  assert.doesNotMatch(legend, /data-layer="fleet-heat"/);
  assert.match(legend, /data-reason="fleet-activity">2 stops · inferred from movement\.</);
  m.activityAccess.value = false;
  assert.doesNotMatch(m.render(m.h(m.Legend)), /fleet-activity|fleet-events/, 'nothing for a viewer without access');
});

test('Accept 3: v1\'s fleet-activity.js is byte for byte as before FE-24', async () => {
  const sha = createHash('sha256').update(await readFile(new URL('dist/fleet-activity.js', ROOT))).digest('hex');
  assert.equal(sha, 'ae87a65ef41e5329ef9bb35a85fddb83bfb0a01ccc749e2487fe2b4d618bc1f8');
});

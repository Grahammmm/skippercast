// Fleet view (FE-53, docs/plans/front-end/dev-plan.md): the public charter grounds, the AIS 2024
// option and the boat directory link, and for an admin the server admitted v1's filter form driving
// FE-24's layers. Every request is answered by a fake fetch (offline); the boat and filter values are
// synthetic, shaped as tests/test_fleet_layers.mjs's.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {signal} from '@preact/signals';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import * as v1 from '../dist/fleet-activity.js';
import {FILTERS, boatDirectory, directoryHref, filterChoices, readFilters, regionPorts} from '../web/fleet.ts';
import {FLEET_SOURCE, activityAccess, activityChoices, activityFilters, activityOn, createFleetActivity, hidePlanning, toggleActivity} from '../web/map/fleet.ts';
import {markData} from '../web/map/marks.ts';
import {readPalette} from '../web/map/palette.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url);
const until = async (ok, what) => { for (let i = 0; i < 200 && !ok(); i++) await new Promise(r => setTimeout(r, 5)); assert.ok(ok(), what); };
const CHOICES = {region: 'CA', vessels: [{id: 'v1', name: 'Sea <b>Example</b>'}], truncated: true, ports: ['morro-bay'], classes: ['six-pack'],
  trip_types: ['half-day'], kinds: ['drift-anchor', 'troll-slow'], seasons: ['2026'], season_parts: ['summer'], dates: {min: '2026-06-01', max: '2026-07-30'}};
const EVENT = (id, planning) => ({type: 'Feature', geometry: {type: 'Point', coordinates: [-120.9, 35.3]},
  properties: {id, vessel_name: 'Test Boat', kind: 'drift-anchor', dwell_min: 30, planning_only: planning}});

test('the form\'s names, options and values are v1\'s', () => {
  assert.deepEqual([...FILTERS], v1.FILTERS);
  const html = v1.filterOptions(CHOICES), mine = filterChoices(CHOICES);
  for (const name of Object.keys(html)) {
    const theirs = [...html[name].matchAll(/<option value="([^"]*)">([^<]*)<\/option>/g)].map(m => [m[1], m[2].replace(/&lt;/g, '<').replace(/&gt;/g, '>')]);
    assert.deepEqual(mine[name].map(c => [c.value, c.label]), theirs, name);
  }
  const values = {vessel: 'v1', port: ' ', class: '', from: '2026-06-01', season_part: 'summer', other: 'x'};
  assert.deepEqual(readFilters(values), v1.readFilters({elements: Object.fromEntries(Object.entries(values).map(([k, value]) => [k, {value}]))}));
  assert.deepEqual(filterChoices(null).vessel, [{value: '', label: 'Any'}]);
});

/** A fake engine and fetch; `admin` and `flags` answer v1's access check as server/fleet/map.ts and routes/admin.ts do. */
function harness({admin, flags}) {
  const asked = [], calls = [];
  const fetchFn = async url => {
    asked.push(url);
    const ok = body => ({ok: true, status: 200, json: async () => body}), missing = {ok: false, status: 404, json: async () => ({})};
    if (url === '/api/session') return ok({is_admin: admin});
    const u = new URL(url, 'https://s.test');
    if (!admin || !flags) return missing;
    if (u.pathname === '/api/fleet/map/filters') return ok({...CHOICES, region: u.searchParams.get('region')});
    return ok({type: 'FeatureCollection', features: [EVENT('e1', false), EVENT('e2', true)], meta: {next: null, trips: 0, ignored: []}});
  };
  const view = {size: () => ({width: 400, height: 300}), unproject: (x, y) => ({lon: -121 + x / 1000, lat: 35.5 - y / 1000}), on: () => () => {}};
  const engine = signal({view, setOverlay: () => {}, setData: (id, data) => calls.push([id, data.features.length])});
  return {asked, calls, engine, fetchFn};
}

function open(t, h, query) {
  globalThis.location = {href: `https://s.test/map?region=morro-bay&${query}`};
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  markData.value = {region: {id: 'morro-bay', jurisdiction_id: 'california-central', assets: {}}, atlas: null, survey: null, geology: null};
  const fleet = createFleetActivity({engine: h.engine, fetchFn: h.fetchFn, palette: () => readPalette(name => `token(${name})`)});
  t.after(() => { fleet.destroy(); markData.value = null; activityOn.value = []; activityFilters.value = {}; hidePlanning.value = false; });
  return fleet;
}

test('privacy: in the Fleet view a visitor gets no filter values and never calls the map API', async t => {
  const visitor = harness({admin: false, flags: true});
  open(t, visitor, 'view=fleet&layers=seafloor');
  await until(() => visitor.asked.length === 1, 'the view asks the session even with the entry off');
  await new Promise(r => setTimeout(r, 30));
  assert.deepEqual(visitor.asked, ['/api/session']);
  assert.equal(activityAccess.value, false);
  assert.equal(activityChoices.value, null, 'no boat list for a visitor');
});

test('Accept 1: an admin with a fleet flag off gets the 404 and no form', async t => {
  const h = harness({admin: true, flags: false});
  open(t, h, 'view=fleet&layers=seafloor');
  await until(() => h.asked.length === 2, 'the probe is asked');
  await new Promise(r => setTimeout(r, 30));
  assert.equal(activityAccess.value, false);
  assert.equal(activityChoices.value, null);
});

test('Accept 2: the admin\'s filters reach the map API exactly as v1 sends them; planning-only rows can be left out', async t => {
  const h = harness({admin: true, flags: true});
  open(t, h, 'view=fleet&layers=fleet');
  await until(() => activityAccess.value, 'the probe answers');
  assert.equal(activityChoices.value.vessels[0].name, 'Sea <b>Example</b>');
  const filters = readFilters({port: 'morro-bay', vessel: ' ', kind: 'troll-slow', from: '2026-06-01', season_part: 'summer'});
  activityFilters.value = filters;
  toggleActivity('events', true);
  await until(() => h.calls.some(c => c[0] === FLEET_SOURCE.events), 'events draw');
  const sent = h.asked.at(-1);
  assert.equal(sent, v1.layerQuery('events', filters, {region: 'CA', bbox: [-121, 35.2, -120.6, 35.5]}));
  const u = new URL(sent, 'https://s.test');
  assert.equal(u.searchParams.get('port'), 'morro-bay');
  assert.equal(u.searchParams.get('kind'), 'troll-slow');
  assert.equal(u.searchParams.has('vessel'), false, 'empty filters are left out, as v1');
  assert.equal(h.calls.findLast(c => c[0] === FLEET_SOURCE.events)[1], 2);
  hidePlanning.value = true;
  await until(() => h.calls.findLast(c => c[0] === FLEET_SOURCE.events)[1] === 1, 'the planning-only row leaves without a new request');
  const before = h.asked.length;
  activityFilters.value = {...filters, season: '2026'};
  await until(() => h.asked.length > before, 'a new filter reloads');
  assert.equal(new URL(h.asked.at(-1), 'https://s.test').searchParams.get('season'), '2026');
});

test('the directory link shows only while the public port page answers, and sends no cookie', async () => {
  const PORTS = [{id: 'port-san-luis', name: 'Port San Luis', region: 'morro-bay', status: 'active'}, {id: 'morro-bay', name: 'Morro Bay', region: 'morro-bay', status: 'active'},
    {id: 'monterey', name: 'Monterey', region: 'monterey-point-sur', status: 'active'}, {id: 'cayucos', name: 'Cayucos', region: 'morro-bay', status: 'preview'}];
  assert.deepEqual(regionPorts(PORTS, 'morro-bay', 'morro-bay').map(p => p.id), ['morro-bay', 'port-san-luis']);
  assert.equal(directoryHref(PORTS[1]), '/ports/morro-bay#boats-title');
  const seen = [];
  const answer = status => async (url, init) => { seen.push([url, init]); return {ok: status === 200, status}; };
  assert.deepEqual(await boatDirectory('morro-bay', null, answer(404), async () => PORTS), [], 'off: no link');
  assert.deepEqual((await boatDirectory('morro-bay', 'morro-bay', answer(200), async () => PORTS)).map(p => p.id), ['morro-bay', 'port-san-luis']);
  assert.deepEqual(seen.at(-1), ['/ports/morro-bay', {method: 'HEAD', credentials: 'omit', cache: 'no-store'}]);
  assert.deepEqual(await boatDirectory(null, null, answer(200), async () => PORTS), []);
  assert.deepEqual(await boatDirectory('morro-bay', null, answer(200), async () => { throw Error('offline'); }), []);
});

test('the view: grounds and the AIS 2024 option for everyone; the form, "inferred from movement" and boat names only for the admitted admin', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'fleet-view-')), 'view.mjs');
  await build({stdin: {resolveDir: ROOT.pathname, loader: 'ts', contents: `
      export {Fleet} from './web/app/views/Fleet.tsx';
      export {Desktop} from './web/app/Desktop.tsx';
      export {activityAccess, activityChoices, activityOn} from './web/map/fleet.ts';
      export {aisState} from './web/map/commercial-ais.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  const m = await import(pathToFileURL(out).href);
  globalThis.location = {href: 'https://s.test/map?region=morro-bay&view=fleet&layers=fleet'};
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(location.href);
  m.aisState.value = {offered: true, drawn: 0, note: ''};
  const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');

  const visitor = m.render(m.h(m.Fleet));
  assert.match(visitor, /<div class="app-fleet"><h1 id="app-fleet-title">Fleet<\/h1>/);
  assert.match(text(visitor), /Show charter grounds/);
  assert.match(text(visitor), /Commercial AIS 2024/);
  assert.match(visitor, /These are named areas from published trip records, not AIS-confirmed fishing positions\./);
  assert.deepEqual([...visitor.matchAll(/type="checkbox"/g)].length, 2, 'the grounds and the AIS option only');
  assert.doesNotMatch(visitor, /<form|<select|Boats out of|admin|vessel|Sea /i, 'no form, no directory link while it is off, no boat');

  m.activityAccess.value = true;
  m.activityChoices.value = CHOICES;
  const admin = m.render(m.h(m.Fleet));
  assert.match(admin, /Fleet activity · admin/);
  assert.match(admin, /Inferred from movement; filters in the Fleet view\./, 'Accept 3');
  assert.match(text(admin), /How fleet activity is inferred/);
  assert.match(admin, /<option value="v1">Sea &lt;b>Example&lt;\/b><\/option>/, 'registry text is escaped');
  assert.match(admin, /The boat list shows the first 500 boats by name\./);
  assert.match(admin, /name="from" type="date" value min="2026-06-01" max="2026-07-30"/);
  assert.match(admin, /Fleet activity is off\. Turn on a layer to load it\./);
  for (const name of FILTERS) assert.match(admin, new RegExp(`name="${name}"`), name);
  assert.match(text(admin), /Apply filters Show on map/);

  // The desktop shows the view in the brief column, with the map's chrome kept.
  const desktop = m.render(m.h(m.Desktop, {now: new Date('2026-10-05T20:00:00Z')}));
  assert.match(desktop, /<aside class="app-brief" aria-label="Fleet"><div class="app-fleet"/);
  assert.match(desktop, /class="ui-rail-item"/);
  m.activityAccess.value = false;
  m.activityChoices.value = null;
});

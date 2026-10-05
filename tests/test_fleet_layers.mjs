// CF-51: the admin-only fleet activity layers in the client (dist/fleet-activity.js;
// docs/plans/charter-fleet/design.md § 14, D10, D11). Fixtures are synthetic.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {
  INFERRED, EVENT_STYLE, SEGMENT_STYLE, LAYERS, MAX_PAGES, eventRadius, heatOpacity, layerQuery, fleetRegion, eventCardHTML,
  trackCardHTML, heatCardHTML, filterOptions, readFilters, fleetAccess, fetchLayer, statusText, visibleFeatures, featureArea,
} from '../dist/fleet-activity.js';

const html = readFileSync(new URL('../dist/index.html', import.meta.url), 'utf8');
const app = readFileSync(new URL('../dist/app.js', import.meta.url), 'utf8');
const source = readFileSync(new URL('../dist/fleet-activity.js', import.meta.url), 'utf8');

const event = (over = {}) => ({type: 'Feature', id: 'e1', geometry: {type: 'Point', coordinates: [-120.95, 35.3]}, properties: {
  layer: 'event', id: 'e1', trip_id: 't1', vessel_id: 'v1', vessel_name: 'Sea Example', vessel_slug: 'sea-example', port_id: 'morro-bay',
  vessel_class: 'inspected-party', trip_type: 'half-day', kind: 'drift-anchor', local_date: '2026-07-04', started_at: '2026-07-04T15:10:00Z',
  ended_at: '2026-07-04T15:55:00Z', dwell_min: 45, season: '2026', season_part: 'summer', source: 'aisstream', classifier_version: 'c1',
  basis: 'inferred-from-movement', rights: 'aisstream-terms', planning_only: false, ...over}});
const segment = (over = {}) => ({type: 'Feature', id: 's1', geometry: {type: 'LineString', coordinates: [[-120.9, 35.3], [-120.95, 35.32]]}, properties: {
  layer: 'track', id: 's1', trip_id: 't1', seq: 2, segment_kind: 'fishing-troll', vessel_name: 'Sea Example', depart_port_id: 'morro-bay',
  return_port_id: 'morro-bay', trip_type: 'half-day', trip_status: 'closed', local_date: '2026-07-04', departed_at: '2026-07-04T14:00:00Z',
  returned_at: '2026-07-04T20:00:00Z', distance_nm: 18.2, max_offshore_nm: 6.1, fishing_min: 150, source: 'aisstream',
  basis: 'inferred-from-movement', rights: 'aisstream-terms', planning_only: false, ...over}});
const cell = (over = {}) => ({type: 'Feature', id: 'a1', geometry: {type: 'Polygon', coordinates: [[[-121, 35], [-120.99, 35], [-120.99, 35.01], [-121, 35.01], [-121, 35]]]},
  properties: {layer: 'heat', id: 'a1', cell_id: 'g1', module: 'grid', kind: 'troll', season: '2026', season_part: null, vessels_n: 4, events_n: 9,
    dwell_min: 320, first_date: '2026-06-01', last_date: '2026-07-30', computed_at: '2026-08-01T00:00:00Z', basis: 'inferred-from-movement',
    rights: 'aisstream-terms', planning_only: false, ...over}});
const page = (features, meta = {}) => ({type: 'FeatureCollection', features, meta: {count: features.length, next: null, ignored: [], ...meta}});
const reply = (status, body) => ({ok: status >= 200 && status < 300, status, json: async () => body});
const FILTERS = {region: 'CA', vessels: [{id: 'v1', name: 'Sea <b>Example</b>'}], truncated: false, ports: ['morro-bay'], classes: ['six-pack'],
  trip_types: ['half-day'], kinds: ['drift-anchor', 'troll'], seasons: ['2026'], season_parts: ['summer'], dates: {min: '2026-06-01', max: '2026-07-30'}};

// ---- Toggles: shipped hidden, inside one admin section ----

test('index.html ships the three toggles hidden inside the admin-only fleet section', () => {
  const section = html.match(/<details id="fleet-layers"[^>]*>[\s\S]*?<\/form>/)?.[0];
  assert.ok(section, 'fleet section present');
  assert.match(section, /^<details id="fleet-layers" class="fleet-layers" hidden>/);
  for (const name of LAYERS) {
    assert.equal(html.split(`id="layer-fleet-${name}"`).length, 2, `one ${name} toggle`);
    assert.ok(section.includes(`id="layer-fleet-${name}"`), `${name} toggle inside the hidden section`);
  }
  for (const name of ['vessel', 'port', 'class', 'trip_type', 'kind', 'from', 'to', 'season', 'season_part'])
    assert.match(section, new RegExp(`name="${name}"`), `${name} filter`);
});

test('app.js wires the layer with the optional guard; plain module names only', () => {
  assert.match(app, /import \{ initFleetActivity \} from "\.\/fleet-activity\.js";/);
  assert.match(app, /optional\("Fleet activity",\(\)=>initFleetActivity\(map,\{onSelect:\(html,area\)=>showAreaDetails\(html,area,"fleet-weather"\)/);
  for (const text of [app, html, source]) assert.doesNotMatch(text, /fleet-activity[^"'\s]*-v\d+|fleet-activity\.js\?v=|modulepreload[^>]*fleet-activity/);
});

// ---- Access: admin and both flags, decided by the server ----

test('a visitor who is not an admin never reaches the map API', async () => {
  const calls = [];
  const fetcher = async url => { calls.push(url); return reply(200, {signedIn: true, is_admin: false}); };
  assert.equal(await fleetAccess('CA', fetcher), null);
  assert.deepEqual(calls, ['/api/session']);
  calls.length = 0;
  assert.equal(await fleetAccess('CA', async url => { calls.push(url); return reply(404, {error: 'Not found'}); }), null);
  assert.deepEqual(calls, ['/api/session'], 'no session route (static preview) means no layers');
  assert.equal(await fleetAccess(null, async () => assert.fail('no region, no request')), null);
  assert.equal(await fleetAccess('CA', async () => { throw new TypeError('offline'); }), null);
});

test('an admin with either flag off gets the 404 probe and no layers', async () => {
  const calls = [];
  const fetcher = async url => { calls.push(url); return url === '/api/session' ? reply(200, {is_admin: true}) : reply(404, {error: 'Not found'}); };
  assert.equal(await fleetAccess('CA', fetcher), null);
  assert.deepEqual(calls, ['/api/session', '/api/fleet/map/filters?region=CA']);
  const wrong = async url => url === '/api/session' ? reply(200, {is_admin: true}) : reply(200, {...FILTERS, region: 'OR'});
  assert.equal(await fleetAccess('CA', wrong), null, 'a filters answer for another region is refused');
  const ok = async url => url === '/api/session' ? reply(200, {is_admin: true}) : reply(200, FILTERS);
  assert.deepEqual(await fleetAccess('CA', ok), FILTERS);
});

test('the fleet region is the state of the coastal region', () => {
  assert.equal(fleetRegion({jurisdiction_id: 'california-central'}), 'CA');
  assert.equal(fleetRegion({jurisdiction_id: 'oregon-south'}), 'OR');
  assert.equal(fleetRegion({jurisdiction_id: 'baja-norte'}), null);
  assert.equal(fleetRegion({}), null);
});

// ---- The DOM: toggles absent for non-admins and with the flag off ----

function dom() {
  const elements = new Map();
  const make = (id, extra = {}) => {
    const handlers = {};
    const e = {id, value: '', checked: false, hidden: false, textContent: '', innerHTML: '', removed: false, min: '', max: '',
      addEventListener(name, fn) { handlers[name] = fn; }, fire(name, ev = {preventDefault() {}}) { return handlers[name]?.(ev); },
      remove() { this.removed = true; elements.delete(id); }, close() {}, ...extra};
    elements.set(id, e); return e;
  };
  const section = make('fleet-layers', {hidden: true});
  const toggles = Object.fromEntries(LAYERS.map(n => [n, make(`layer-fleet-${n}`)]));
  const controls = Object.fromEntries(['vessel', 'port', 'class', 'trip_type', 'kind', 'from', 'to', 'season', 'season_part'].map(n => [n, {value: '', innerHTML: '', min: '', max: ''}]));
  const form = make('fleet-filters', {elements: controls});
  for (const id of ['fleet-activity-status', 'fleet-hide-planning', 'fleet-show', 'fleet-vessels-note', 'map-options']) make(id);
  // Removing the section removes everything inside it (index.html nests them all).
  const inside = [...elements.keys()].filter(id => id !== 'map-options');
  section.remove = function () { this.removed = true; for (const id of inside) elements.delete(id); };
  return {elements, section, toggles, controls, form, get: id => elements.get(id)};
}

function leaflet() {
  const drawn = {circles: [], shapes: []};
  const group = () => ({items: [], on: false, addTo() { this.on = true; return this; }, clearLayers() { this.items = []; }});
  const item = (kind, args) => ({kind, args, handlers: {}, on(name, fn) { this.handlers[name] = fn; return this; }, bindTooltip(t) { this.tooltip = t; return this; },
    addTo(g) { g.items.push(this); (kind === 'circle' ? drawn.circles : drawn.shapes).push(this); return this; }});
  return {drawn, L: {layerGroup: group, circleMarker: (...args) => item('circle', args), geoJSON: (...args) => item('shape', args)}};
}

const map = () => ({removeLayer(g) { g.on = false; }, on(name, fn) { this.moved = fn; },
  getBounds: () => ({getWest: () => -121.5, getSouth: () => 34.9, getEast: () => -120.4, getNorth: () => 35.8})});
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

async function start(t, fetcher) {
  const {initFleetActivity} = await import('../dist/fleet-activity.js');
  const d = dom(), {drawn, L} = leaflet();
  const saved = {document: globalThis.document, L: globalThis.L};
  t.after(() => { for (const [k, v] of Object.entries(saved)) { if (v === undefined) delete globalThis[k]; else globalThis[k] = v; } });
  globalThis.document = {getElementById: id => d.get(id)};
  globalThis.L = L;
  const selected = [];
  const m = map();
  const ui = await initFleetActivity(m, {onSelect: (h, area) => selected.push({h, area}), showMap() {}, fetcher, region: 'CA'});
  return {d, drawn, ui, selected, m};
}

test('toggles are removed for a non-admin and while FLEET_MAP_ENABLED is off', async t => {
  for (const fetcher of [
    async () => reply(200, {signedIn: false, is_admin: false}),
    async url => url === '/api/session' ? reply(200, {is_admin: true}) : reply(404, {error: 'Not found'}),
  ]) {
    const {d, ui} = await start(t, fetcher);
    assert.equal(d.section.removed, true);
    for (const name of LAYERS) assert.equal(d.get(`layer-fleet-${name}`), undefined);
    assert.equal(d.toggles.events.checked, false);
    assert.equal(ui.enabled, false);
  }
});

test('an admin with the flags on sees the toggles, fills the filter card and draws a layer', async t => {
  const requests = [];
  const fetcher = async url => {
    requests.push(url);
    if (url === '/api/session') return reply(200, {is_admin: true});
    if (url.startsWith('/api/fleet/map/filters')) return reply(200, FILTERS);
    if (url.startsWith('/api/fleet/map/events')) return reply(200, page([event(), event({id: 'e2', kind: 'troll', planning_only: true, rights: 'noaa-planning-only'})]));
    return reply(500, {});
  };
  const {d, drawn, ui, selected} = await start(t, fetcher);
  assert.equal(ui.enabled, true);
  assert.equal(d.section.hidden, false);
  assert.match(d.controls.vessel.innerHTML, /Sea &lt;b&gt;Example&lt;\/b&gt;/);
  assert.equal(d.controls.from.min, '2026-06-01');
  assert.match(d.controls.season_part.innerHTML, /<option value="">Whole season<\/option>/);
  d.controls.port.value = 'morro-bay';
  d.toggles.events.checked = true;
  await d.toggles.events.fire('change');
  const url = new URL(requests.at(-1), 'https://x.test');
  assert.equal(url.pathname, '/api/fleet/map/events');
  assert.equal(url.searchParams.get('region'), 'CA');
  assert.equal(url.searchParams.get('port'), 'morro-bay');
  assert.equal(url.searchParams.get('bbox'), '-121.5,34.9,-120.4,35.8');
  assert.equal(drawn.circles.length, 2);
  const [drift, troll] = drawn.circles;
  assert.equal(drift.args[1].fillOpacity > troll.args[1].fillOpacity, true, 'drift filled, troll ringed');
  assert.equal(troll.args[1].dashArray !== null, true, 'planning-only rows are drawn dotted');
  assert.match(d.get('fleet-activity-status').textContent, /2 stops · inferred from movement/);
  drift.handlers.click();
  assert.match(selected[0].h, new RegExp(INFERRED.replace(/[().]/g, '\\$&')));
  assert.equal(selected[0].area.latitude, 35.3);
  d.get('fleet-hide-planning').checked = true;
  d.get('fleet-hide-planning').fire('change');
  assert.equal(drawn.circles.length, 3, 'redraw keeps only the one row that is not planning-only');
});

// ---- Cards ----

test('the event card states the inference and never calls it confirmed fishing', () => {
  const card = eventCardHTML(event().properties, {timezone: 'America/Los_Angeles'});
  assert.ok(card.includes(INFERRED));
  assert.equal(INFERRED, 'Inferred from movement (speed and track shape). Not a confirmed fishing stop or catch.');
  assert.doesNotMatch(card.replace(INFERRED, ''), /confirmed fishing|catch spot|hotspot/i);
  for (const text of ['Sea Example', 'Morro bay', 'Inspected party', 'Half day', '2026-07-04', '45 min', 'Drift or anchor', 'aisstream', 'aisstream-terms', 'Summer'])
    assert.ok(card.includes(text), text);
  assert.match(card, /8:10\s?AM–8:55\s?AM/);
  assert.match(card, /id="fleet-weather"/);
  assert.match(card, /<details class="detail-section"><summary>Source &amp; rights<\/summary>/);
});

test('every card escapes registry text and flags planning-only rights', () => {
  const p = event({vessel_name: '<img src=x onerror=alert(1)>', planning_only: true, rights: 'noaa-planning-only'}).properties;
  for (const card of [eventCardHTML(p), trackCardHTML({...segment().properties, ...p}), heatCardHTML({...cell().properties, planning_only: true, module: '<b>m</b>'})]) {
    assert.doesNotMatch(card, /<img|<b>m<\/b>/);
    assert.match(card, /PLANNING-ONLY/);
    assert.match(card, /NOAA planning-only/);
    assert.ok(card.includes(INFERRED));
  }
});

test('track and heat cards carry their facts', () => {
  const track = trackCardHTML(segment().properties);
  for (const text of ['Troll', 'Morro bay → Morro bay', '18.2 nm', '6.1 nm', '2 hr 30 min', 'Closed']) assert.ok(track.includes(text), text);
  const heat = heatCardHTML(cell().properties);
  for (const text of ['Troll cell', '5 hr 20 min', '2026-06-01 to 2026-07-30', '>4<', '>9<']) assert.ok(heat.includes(text), text);
});

// ---- Drawing rules and queries ----

test('event radius grows with the square root of dwell inside 4–18 px', () => {
  assert.equal(eventRadius(0), 4);
  assert.equal(eventRadius(null), 4);
  assert.equal(eventRadius(16), 8);
  assert.equal(eventRadius(36), 12);
  assert.equal(eventRadius(10_000), 18);
  assert.ok(heatOpacity(320, 320) > heatOpacity(80, 320));
  assert.equal(heatOpacity(5, 0), 0.1);
  assert.ok(heatOpacity(1e9, 10) <= 0.7);
});

test('styles distinguish drift, troll and gaps', () => {
  assert.ok(EVENT_STYLE['drift-anchor'].fill && !EVENT_STYLE.troll.fill);
  assert.notEqual(SEGMENT_STYLE['fishing-drift'].color, SEGMENT_STYLE['fishing-troll'].color);
  assert.notEqual(SEGMENT_STYLE.transit.color, SEGMENT_STYLE['fishing-troll'].color);
  assert.ok(SEGMENT_STYLE.gap.dashArray);
  for (const kind of ['in-port', 'transit', 'fishing-drift', 'fishing-troll', 'gap']) assert.ok(SEGMENT_STYLE[kind], kind);
});

test('queries leave out empty filters and pass the rest to the server', () => {
  const url = new URL(layerQuery('heat', {kind: 'troll', season: '2026', vessel: ''}, {region: 'CA', bbox: [-121.123456, 35, -120, 36]}), 'https://x.test');
  assert.equal(url.pathname, '/api/fleet/map/heat');
  assert.deepEqual([...url.searchParams.keys()].sort(), ['bbox', 'kind', 'region', 'season']);
  assert.equal(url.searchParams.get('bbox'), '-121.12346,35,-120,36');
  assert.equal(url.searchParams.has('season_part'), false, 'heat defaults to whole-season cells');
  const form = {elements: {vessel: {value: 'v1'}, port: {value: ' '}, from: {value: '2026-06-01'}, season_part: {value: 'summer'}}};
  assert.deepEqual(readFilters(form), {vessel: 'v1', from: '2026-06-01', season_part: 'summer'});
  const options = filterOptions(FILTERS);
  assert.match(options.kind, /<option value="drift-anchor">Drift or anchor<\/option>/);
  assert.match(options.class, /<option value="six-pack">Six pack<\/option>/);
});

test('tracks page on meta.next, never on feature counts, up to the page limit', async () => {
  const seen = [];
  let n = 0;
  const fetcher = async url => {
    seen.push(new URL(url, 'https://x.test').searchParams.get('cursor'));
    n++;
    // The bbox can empty a page while more trips remain.
    return reply(200, page(n === 1 ? [] : [segment({id: `s${n}`})], {trips: 300, next: `c${n}`}));
  };
  const result = await fetchLayer('tracks', {}, {region: 'CA', fetcher});
  assert.deepEqual(seen, [null, 'c1', 'c2']);
  assert.equal(seen.length, MAX_PAGES);
  assert.equal(result.features.length, 2);
  assert.equal(result.more, true);
  await assert.rejects(fetchLayer('events', {}, {region: 'CA', fetcher: async () => reply(404, {})}), /failed \(404\)/);
});

test('the status line counts trips, flags more pages and names filters heat ignores', () => {
  const text = statusText({tracks: {features: [], trips: 12, more: true}, heat: {features: [cell()], more: false, ignored: ['vessel', 'trip_type', 'from']}});
  assert.match(text, /^12\+ trips · 1 heat cells · inferred from movement\. More remain/);
  assert.match(text, /Heat cells ignore boat, trip type, from date\.$/);
  assert.match(statusText({}), /Turn on a layer/);
  assert.equal(visibleFeatures([event(), event({planning_only: true})], true).length, 1);
  assert.equal(visibleFeatures([event(), event({planning_only: true})], false).length, 2);
  assert.ok(Math.abs(featureArea(cell(), 'x').latitude - 35.005) < 1e-9, 'a cell centres on its ring, closing point excluded');
  assert.ok(Math.abs(featureArea(segment(), 'x').longitude + 120.925) < 1e-9);
  assert.equal(featureArea({geometry: {type: 'Point', coordinates: [NaN, 1]}, properties: {}}, 'x'), null);
});

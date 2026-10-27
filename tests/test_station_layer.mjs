import assert from 'node:assert/strict';
import {readFile, readdir} from 'node:fs/promises';
import test from 'node:test';
import {signal} from '@preact/signals';
import catalog from '../catalog/station-locations.json' with {type: 'json'};
import {counties} from '../packages/coast/src/counties.ts';
import {configuredStations, selectedStations, readingState, stationPins, stationGeoJSON, located} from '../web/map/station-model.ts';
import {createStations, stationState, STATION_DOTS, STATION_HIT} from '../web/map/stations.ts';
import {tideSelection} from '../web/tide-selection.ts';
import {configureStore, syncFromURL} from '../web/state.ts';
import {chartMark} from '../web/map/chart.ts';
import {readPalette} from '../web/map/palette.ts';

const NOW = new Date('2026-10-20T18:00:00Z'), HOUR = 3_600_000;
const ago = h => new Date(+NOW - h * HOUR).toISOString();
const region = {id: 'fixture', stations: {tide: '9412553', nearshore_buoy: '46053', offshore_buoy: '46054', roles: {nearshore_buoy: {stations: ['46053', '46054']}}}};
const buoy = (patch = {}) => ({id: 'buoy-primary', kind: 'observation', name: 'Primary role', url: 'https://example.test', checked_at: ago(0), status: 'ok', station: '46054', fallback_for: '46053',
  data: {station: '46054', units: {WTMP: 'degC', WVHT: 'm', DPD: 'sec', WSPD: 'm/s', GST: 'm/s'}, observations: [
    {time: ago(1), WTMP: 10, WVHT: null, WSPD: 2}, {time: ago(2), WTMP: 9, WVHT: 1, DPD: 12}, {time: ago(0.5), WTMP: null, WVHT: 2}]}, ...patch});
const tide = (patch = {}) => ({id: 'tides', kind: 'prediction', name: 'Tide', url: 'https://example.test', checked_at: ago(1), status: 'ok', station: '9412553',
  data: {station: '9412553', units: 'ft', datum: 'MLLW', note: 'Not entrance current.', coverage_start: ago(5), coverage_end: ago(-5), predictions: [{time: ago(5), height_ft: 1, type: 'L'}, {time: ago(-1), height_ft: 4, type: 'H'}, {time: ago(-5), height_ft: 2, type: 'L'}]}, ...patch});
const pins = (sources = {buoy: buoy(), tides: tide()}, patch = {}) => stationPins({region, catalog, feed: {region_id: 'fixture', sources}, now: NOW, at: NOW, ...patch});
const at = (all, key) => all.find(p => p.key === key);

test('offline catalog is exactly the configured region/context/role-chain and bound county union, with provenance', async () => {
  const expected = new Set();
  for (const dir of await readdir(new URL('../regions/', import.meta.url))) {
    let r;
    try {r = JSON.parse(await readFile(new URL(`../regions/${dir}/region.json`, import.meta.url), 'utf8'));} catch (e) {if (e.code === 'ENOENT' || e.code === 'ENOTDIR') continue; throw e;}
    for (const c of [r, ...Object.values(r.contexts ?? {})]) for (const s of configuredStations(c.stations)) expected.add(`${s.provider}:${s.id}`);
  }
  for (const county of Object.values(counties)) for (const s of selectedStations({id: 'bound'}, null, county)) expected.add(`${s.provider}:${s.id}`);
  assert.deepEqual(Object.keys(catalog.stations).sort(), [...expected].sort());
  assert.equal(catalog.schema_version, 1);
  const admitted = JSON.parse(await readFile(new URL('../catalog/station-failover.json', import.meta.url), 'utf8')).sources;
  for (const s of Object.values(catalog.sources)) {
    assert.ok(admitted.includes(s.url)); assert.match(s.sha256, /^[a-f0-9]{64}$/); assert.ok(Number.isFinite(Date.parse(s.retrieved_at)));
  }
  for (const [key, loc] of Object.entries(catalog.stations)) {assert.equal(key, `${loc.provider}:${loc.id}`); assert.ok(located(loc)); assert.ok(loc.name); assert.ok(catalog.sources[loc.provider]);}
  assert.deepEqual([catalog.stations['coops:9412553'].latitude, catalog.stations['coops:9412553'].longitude], [35.6417, -121.188]);
  assert.equal(catalog.stations['coops:9412553'].reference_id, '9412110');
  assert.equal(catalog.stations['coops:9412553'].type, 'S');
  assert.deepEqual([catalog.stations['ndbc:46015'].latitude, catalog.stations['ndbc:46015'].longitude], [42.754, -124.839]);
});

test('configured set deduplicates shared buoys; backup has its own position/name/link and primary no values', () => {
  const all = pins();
  assert.deepEqual(all.map(p => p.key), ['coops:9412553', 'ndbc:46053', 'ndbc:46054']);
  const active = at(all, 'ndbc:46054'), inactive = at(all, 'ndbc:46053');
  assert.equal(active.location, catalog.stations['ndbc:46054']);
  assert.match(active.mark.name, /46054 \(backup for 46053\)/);
  assert.match(active.mark.provider.href, /station=46054$/);
  assert.match(inactive.mark.reading, /Water: unavailable/);
  assert.ok(!inactive.mark.reading.includes('50.0'));
  assert.deepEqual(stationGeoJSON(all).features.find(f => f.properties.id === active.key).geometry.coordinates, [active.location.longitude, active.location.latitude]);
});

test('latest VALID sample per variable, independent of row ordering; missing sensors remain missing', () => {
  const mark = at(pins(), 'ndbc:46054').mark;
  assert.match(mark.reading, /Water 50.0 °F · 2026-10-20T17:00:00.000Z · fresh/);
  assert.match(mark.reading, /Seas 6.6 ft · 2026-10-20T17:30:00.000Z/);
  assert.match(mark.reading, /Period 12.0 s · 2026-10-20T16:00:00.000Z/);
  assert.match(mark.reading, /Gust: unavailable/);
  const s = buoy(); s.data.observations.reverse();
  assert.equal(at(pins({buoy: s}), 'ndbc:46054').mark.reading, mark.reading);
});

test('stale and retained readings keep values and original clocks; invalid/future clocks are unavailable', () => {
  assert.equal(readingState(ago(3), +NOW, 3 * HOUR), 'fresh');
  assert.equal(readingState(ago(3.001), +NOW, 3 * HOUR), 'stale');
  for (const time of ['no clock', '2026-10-20T18:00:00', ago(-1)]) assert.equal(readingState(time, +NOW, 3 * HOUR), 'unavailable');
  const s = buoy({status: 'retained'});
  let active = at(pins({buoy: s}), 'ndbc:46054');
  assert.match(active.mark.reading, /Water 50.0 °F.*stale \/ last good/); assert.ok(active.stale);
  s.status = 'ok'; s.data.observations = [{time: ago(8), WTMP: 10}, {time: 'bad', WTMP: 99}, {time: ago(-1), WTMP: 99}];
  active = at(pins({buoy: s}), 'ndbc:46054');
  assert.match(active.mark.reading, /50.0 °F.*10:00:00.000Z · stale/);
  s.data.observations = [{time: 'bad', WTMP: 10}];
  assert.match(at(pins({buoy: s}), 'ndbc:46054').mark.reading, /Water: unavailable/);
});

test('mismatched payloads, other regions, unknown feed stations and wrong units never supply values', () => {
  const s = buoy(); s.data.station = '46053';
  assert.match(at(pins({buoy: s}), 'ndbc:46054').mark.reading, /Water: unavailable/);
  const wrong = pins({}, {feed: {region_id: 'elsewhere', sources: {buoy: buoy()}}});
  assert.match(at(wrong, 'ndbc:46054').mark.reading, /Water: unavailable/);
  s.station = '99999'; s.data.station = '99999'; assert.equal(pins({unknown: s}).length, 3);
  const unit = buoy(); unit.data.units.WTMP = 'K';
  assert.match(at(pins({buoy: unit}), 'ndbc:46054').mark.reading, /Water: unavailable/);
});

test('context and forecast-point switching select only their configured set', () => {
  const r = {...region, forecast_points: [{id: 'point', context: 'other'}], contexts: {other: {stations: {tide: '9412110', nearshore_buoy: '46215'}}}};
  assert.deepEqual(selectedStations(r, 'point'), [{provider: 'coops', id: '9412110'}, {provider: 'ndbc', id: '46215'}]);
  assert.deepEqual(selectedStations(r, 'other'), selectedStations(r, 'point'));
  assert.deepEqual(selectedStations(r, null), selectedStations(region, null));
});

test('missing and invalid metadata keeps a named accessible gap, never invented geometry', () => {
  const c = structuredClone(catalog); delete c.stations['coops:9412553']; c.stations['ndbc:46054'].longitude = 200;
  const all = pins(undefined, {catalog: c});
  assert.equal(all.length, 3); assert.equal(stationGeoJSON(all).features.length, 1);
  assert.match(at(all, 'coops:9412553').mark.source, /location unavailable/);
  assert.match(at(all, 'coops:9412553').mark.reading, /4.0 ft MLLW/);
});

test('tide events are predictions with datum, valid/retrieval/coverage clocks; gaps and retained state explicit', () => {
  const mark = at(pins(), 'coops:9412553').mark;
  assert.equal(mark.kind, 'Tide prediction station');
  assert.match(mark.reading, /Tide high event: 4.0 ft MLLW · valid 2026-10-20T19:00:00.000Z/);
  assert.match(mark.reading, /retrieved 2026-10-20T17:00:00.000Z · fresh · coverage/);
  assert.match(mark.provider.href, /id=9412553$/);
  const s = tide({status: 'retained', data_retrieved_at: ago(40), last_success_at: ago(40)});
  assert.match(at(pins({tide: s}), 'coops:9412553').mark.reading, /stale \/ last good/);
  assert.match(at(pins(undefined, {at: new Date(+NOW + 8 * HOUR)}), 'coops:9412553').mark.reading, /unavailable for selected time/);
  assert.match(at(pins({tide: tide({checked_at: 'invalid'})}), 'coops:9412553').mark.reading, /no valid retrieval clock/);
});

test('bound report samples keep physical identity and per-variable latest selection', () => {
  const county = counties.slo;
  const report = {countyId: 'slo', observations: [{stationId: '46215', observedAt: ago(1), waterTempF: 55, waveFt: null}, {stationId: '46215', observedAt: ago(2), waterTempF: null, waveFt: 4}], tides: [], tideEvents: [], sources: []};
  const all = pins({}, {report, county});
  assert.match(at(all, 'ndbc:46215').mark.source, /SCRIPPS|CDIP/i);
  assert.match(at(all, 'ndbc:46215').mark.reading, /Water 55.0 °F/);
  assert.match(at(all, 'ndbc:46215').mark.reading, /Seas 4.0 ft/);
  assert.match(at(all, 'ndbc:46054').mark.reading, /Water: unavailable/);
});

const flush = () => new Promise(resolve => setImmediate(resolve));
function browser(regionId = 'fixture') {configureStore({v2: true, storage: null}); syncFromURL(`https://example.test/map?region=${regionId}&layers=stations`);}
test('runtime draws configured dots, opens cards, ages readings, and clears on region/off changes', async t => {
  t.mock.timers.enable({apis: ['setInterval']}); browser();
  const overlays = new Map(), data = new Map(), palette = readPalette(n => `token(${n})`);
  const e = {setOverlay: (k, v) => overlays.set(k, v), setData: (k, v) => data.set(k, v)};
  let now = NOW;
  const s = createStations({engine: signal(e), zone: () => 'UTC', feed: () => ({region_id: 'fixture', sources: {buoy: buoy()}}), fetchFn: async () => ({ok: true, json: async () => region}), palette: () => palette, now: () => now});
  t.after(() => s.destroy()); await flush();
  assert.equal(data.get('stations').features.length, 3);
  assert.equal(overlays.get('stations').layers[0].paint['circle-radius'], 22);
  const card = s.pick.mark(STATION_DOTS, {id: 'ndbc:46054'}); assert.match(card.reading, /fresh/);
  chartMark.value = card; now = new Date(+NOW + 4 * HOUR); t.mock.timers.tick(60_000);
  assert.match(chartMark.value.reading, /stale/);
  assert.equal(s.pick.mark(STATION_HIT, {id: 'unknown'}), null);
  browser('other'); assert.equal(stationState.value.pins.length, 0); assert.equal(chartMark.value, null);
  await flush(); assert.match(stationState.value.note, /unavailable/);
  syncFromURL('https://example.test/map?region=other&layers=none'); assert.equal(overlays.get('stations'), null);
});

test('tide choice: no chosen station adds no labels', () => {
  for (const tideChoice of [null, {regionId: 'fixture', defaultStation: '9412553', chosen: null}]) {
    const all = pins(undefined, {tideChoice});
    assert.equal(at(all, 'coops:9412553').mark.kind, 'Tide prediction station');
    assert.ok(!at(all, 'coops:9412553').mark.reading.includes('Region default tide station'));
    assert.ok(!at(all, 'coops:9412553').mark.reading.includes('Chosen tide station'));
  }
});

test('tide choice: choosing the default station is identical to no choice', () => {
  const all = pins(undefined, {tideChoice: {regionId: 'fixture', defaultStation: '9412553', chosen: '9412553'}});
  assert.equal(at(all, 'coops:9412553').mark.kind, 'Tide prediction station');
  assert.ok(!at(all, 'coops:9412553').mark.reading.includes('Region default tide station'));
  assert.ok(!at(all, 'coops:9412553').mark.reading.includes('Chosen tide station'));
});

test('tide choice: an unconfigured chosen station labels the region default and never adds a chosen pin', () => {
  const all = pins(undefined, {tideChoice: {regionId: 'fixture', defaultStation: '9412553', chosen: '9412110'}});
  const def = at(all, 'coops:9412553');
  assert.equal(def.mark.kind, 'Region default tide station');
  assert.match(def.mark.reading, /Region default tide station · the Brief uses your chosen station 9412110/);
  assert.match(def.mark.reading, /4\.0 ft MLLW/);
  assert.equal(at(all, 'coops:9412110'), undefined);
  assert.equal(at(all, 'ndbc:46054').mark.kind, 'Observing buoy');
});

test('tide choice: a chosen configured context station is labelled chosen and keeps only its own product', () => {
  const r = {...region, contexts: {other: {stations: {tide: '9412110', nearshore_buoy: '46215'}}}};
  const t2110 = tide(); t2110.station = '9412110'; t2110.data.station = '9412110';
  const all = stationPins({region: r, context: 'other', catalog, feed: {region_id: 'fixture', sources: {tides: t2110}}, now: NOW, at: NOW, tideChoice: {regionId: 'fixture', defaultStation: '9412553', chosen: '9412110'}});
  const chosen = at(all, 'coops:9412110');
  assert.equal(chosen.mark.kind, 'Chosen tide station');
  assert.match(chosen.mark.reading, /4\.0 ft MLLW/);
  assert.ok(!chosen.mark.reading.includes('Region default tide station'));
});

test('tide choice: a different region is ignored', () => {
  const all = pins(undefined, {tideChoice: {regionId: 'elsewhere', defaultStation: '9412553', chosen: '9412110'}});
  assert.equal(at(all, 'coops:9412553').mark.kind, 'Tide prediction station');
  assert.ok(!at(all, 'coops:9412553').mark.reading.includes('Region default tide station'));
});

test('stations.ts labels the default pin and notes an unconfigured chosen station without leaking the chosen reading', async t => {
  t.mock.timers.enable({apis: ['setInterval']}); browser();
  const overlays = new Map(), data = new Map(), palette = readPalette(n => `token(${n})`);
  const e = {setOverlay: (k, v) => overlays.set(k, v), setData: (k, v) => data.set(k, v)};
  const now = NOW;
  const s = createStations({engine: signal(e), zone: () => 'UTC', feed: () => ({region_id: 'fixture', sources: {buoy: buoy(), tides: tide()}}), fetchFn: async () => ({ok: true, json: async () => region}), palette: () => palette, now: () => now});
  t.after(() => { s.destroy(); tideSelection.region.value = null; tideSelection.choice.value = null; tideSelection.reading.value = null; });
  tideSelection.region.value = {id: 'fixture', bounds: [-125, 34, -119, 36], station: '9412553', name: 'Fixture'};
  tideSelection.choice.value = '9412110';
  tideSelection.reading.value = {station: {id: '9412110', name: 'Port San Luis', lat: 35.1, lng: -120.6, type: 'R'}, points: [{at: ago(0), heightFt: 99.9}], events: [], fetchedAt: ago(0), failed: false};
  await flush();
  const pins = stationState.value.pins;
  const def = pins.find(p => p.key === 'coops:9412553');
  assert.equal(def.mark.kind, 'Region default tide station');
  assert.match(def.mark.reading, /Region default tide station · the Brief uses your chosen station 9412110/);
  assert.equal(pins.some(p => p.key === 'coops:9412110'), false);
  assert.match(stationState.value.note, /Chosen tide station 9412110 is shown in the Brief, not on this layer/);
  assert.equal(pins.some(p => p.mark.reading.includes('99.9')), false);
});

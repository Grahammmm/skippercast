// #491 and #482: Water temp and Currents outside a report binding. web/map/habitat-feed.ts reads the region's published
// habitat-dynamics manifest and its SHA-256-checked surface-temperature tiles; web/map/sst.ts judges the
// result with the report's gate (age, the dock's hour, the grid). The manifest and tiles here are
// synthetic, in the pipeline's shape (src/skippercast/pipeline/habitat_dynamics.py).
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {signal} from '@preact/signals';
import {validCurrentField} from '../packages/coast/src/state/current-layer.ts';
import {createCurrents, currentsState, currentsStatus, regionalCurrentsStatus} from '../web/map/currents.ts';
import {habitatManifestURL, habitatTileURL, regionalCurrents, regionalSST} from '../web/map/habitat-feed.ts';
import {railNotes} from '../web/map/layers.ts';
import {readPalette} from '../web/map/palette.ts';
import {analysisStatus, createWaterTemp, regionalStatus, waterTempState} from '../web/map/sst.ts';
import {watchOffline} from '../web/map/offline.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';
import {feedServer, wcofsFeed} from './helpers/wcofs-feed.mjs';

const PAGE = 'https://s.test/map', TZ = 'America/Los_Angeles', REGION = 'test-coast', HOUR = 3_600_000;
const SAMPLE_AT = '2026-10-15T12:00:00Z', TIME = Date.parse(SAMPLE_AT) / 1000;
const NOW = new Date('2026-10-16T12:00:00Z'), AT = NOW;
const FIELDS = ['latitude', 'longitude', 'temperature_c', 'analysis_error_c', 'temperature_gradient_c_per_km', 'thermal_contrast_supported'];
const BASE = `${PAGE.replace('/map', '')}/feeds/conditions/regions/${REGION}/`;
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

/** A 6×4 grid of 0.05° cells split into two tiles; (0, 0) is land (no temperature) and (1, 0) has no error. */
function feed({region = REGION, status = 'ok', sampleAt = SAMPLE_AT, maxAge = 72, tile = t => t, record = r => r} = {}) {
  const tiles = [[-121.0, 35.0, -120.85, 35.2], [-120.85, 35.0, -120.7, 35.2]].map((bounds, k) => {
    const cells = [];
    for (let j = 0; j < 4; j++) for (let i = 0; i < 3; i++) {
      const lat = +(35.025 + j * 0.05).toFixed(3), lon = +(bounds[0] + 0.025 + i * 0.05).toFixed(3);
      const temp = k === 0 && i === 0 && j === 0 ? null : 14 + i * 0.2 + k * 0.6 + j * 0.1;
      cells.push([lat, lon, temp, k === 0 && i === 1 && j === 0 ? null : 0.3, null, null]);
    }
    const body = tile({schema_version: 1, region_id: region, layer_id: 'sst-analysis', bounds, resolution_degrees: [0.05, 0.05], fields: FIELDS,
      frames: [{time: TIME, cells}]}, k);
    const bytes = Buffer.from(JSON.stringify(body));
    const path = `habitat-tiles/sst-analysis-${k}-0-${sha(bytes).slice(0, 16)}.json`;
    return {bytes, record: record({path, bounds, sha256: sha(bytes), bytes: bytes.length}, k)};
  });
  const manifest = {schema_version: 1, region_id: region,
    layers: {'sst-analysis': {id: 'sst-analysis', kind: 'analysis', sample_at: sampleAt, resolution_degrees: [0.05, 0.05], fields: FIELDS, status, max_age_hours: maxAge,
      native_stride: 1, source_id: 'noaa-blended-sst', frames: [{time: TIME, valid_cells: 22, total_cells: 24}], tiles: tiles.map(t => t.record)}},
    sources: {'sst-analysis': {id: 'sst-analysis', name: 'NOAA Geo-Polar Blended night SST, 5 km', kind: 'analysis',
      url: 'https://coastwatch.noaa.gov/cwn/products/noaa-geo-polar-blended-global-sea-surface-temperature-analysis-level-4.html',
      max_age_hours: maxAge, status, data_retrieved_at: '2026-10-16T06:00:00Z'}}};
  return {manifest, tiles};
}
/** A fetch that serves one feed and records every URL it was asked for. */
function server({manifest, tiles}, {manifestStatus = 200, tileStatus = 200} = {}) {
  const asked = [];
  const fetchFn = async url => {
    asked.push(url);
    if (url === `${BASE}habitat-dynamics.json`) return manifestStatus === 200 ? Response.json(manifest) : new Response('Not found', {status: manifestStatus});
    const t = tiles.find(t => url === BASE + t.record.path);
    return t && tileStatus === 200 ? new Response(t.bytes) : new Response('Not found', {status: t ? tileStatus : 404});
  };
  return {fetchFn, asked};
}
const read = (f, opts) => regionalSST(REGION, {fetchFn: server(f, opts).fetchFn, page: PAGE, now: NOW});

test('offline ocean misses say not saved, while online, invalid and expired data retain their reasons', async () => {
  for (const reader of [regionalSST, regionalCurrents]) {
    const missed = await reader(REGION, {fetchFn: async () => { throw new TypeError('offline'); }, page: PAGE, now: NOW});
    assert.deepEqual(missed, {state: 'error', network: true});
    const status = reader === regionalSST
      ? offline => regionalStatus(true, missed, AT, NOW, TZ, offline)
      : offline => regionalCurrentsStatus('wcofs', missed, AT, NOW, TZ, offline);
    assert.equal(status(true).note, 'not saved for offline');
    assert.equal(status(true).drawn, null);
    assert.equal(status(false).note, 'unavailable');
  }
  assert.equal(regionalStatus(true, {state: 'error'}, AT, NOW, TZ, true).note, 'unavailable');
  assert.equal(regionalCurrentsStatus('wcofs', {state: 'error'}, AT, NOW, TZ, true).note, 'unavailable');
  for (const status of [
    (state, offline) => analysisStatus(true, state, null, AT, NOW, TZ, offline),
    (state, offline) => currentsStatus('wcofs', state, null, AT, NOW, TZ, offline),
  ]) {
    assert.equal(status('error', true).note, 'not saved for offline');
    assert.equal(status('error', false).note, 'unavailable');
    assert.equal(status('invalid', true).note, 'unavailable');
    assert.equal(status('expired', true).note, 'expired');
  }
  assert.equal(analysisStatus(false, 'error', null, AT, NOW, TZ, true).note, '');
  assert.equal(currentsStatus('off', 'error', null, AT, NOW, TZ, true).note, '');
});

test('connectivity status follows offline and online events and removes its listeners', () => {
  const navigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  const old = {addEventListener: globalThis.addEventListener, removeEventListener: globalThis.removeEventListener};
  const events = new EventTarget(), connection = {onLine: true};
  Object.defineProperty(globalThis, 'navigator', {value: connection, configurable: true});
  globalThis.addEventListener = events.addEventListener.bind(events);
  globalThis.removeEventListener = events.removeEventListener.bind(events);
  try {
    const watched = watchOffline();
    assert.equal(watched.offline.value, false);
    connection.onLine = false; events.dispatchEvent(new Event('offline'));
    assert.equal(watched.offline.value, true);
    connection.onLine = true; events.dispatchEvent(new Event('online'));
    assert.equal(watched.offline.value, false);
    watched.destroy();
    connection.onLine = false; events.dispatchEvent(new Event('offline'));
    assert.equal(watched.offline.value, false);
  } finally {
    Object.assign(globalThis, old);
    if (navigator) Object.defineProperty(globalThis, 'navigator', navigator); else delete globalThis.navigator;
  }
});

test('tile references stay inside the manifest\'s own region folder', () => {
  const manifestURL = habitatManifestURL(REGION, PAGE), record = feed().tiles[0].record;
  assert.equal(manifestURL, `${BASE}habitat-dynamics.json`);
  assert.equal(habitatTileURL(manifestURL, record, REGION), BASE + record.path);
  assert.throws(() => habitatManifestURL('../other', PAGE));
  for (const path of ['../other/habitat-tiles/sst-analysis-0-0-0123456789abcdef.json', 'habitat-tiles/../x-0123456789abcdef.json', 'https://evil.test/habitat-tiles/sst-analysis-0123456789abcdef.json', 'habitat-tiles/SST.json'])
    assert.throws(() => habitatTileURL(manifestURL, {...record, path}, REGION), /Invalid ocean tile reference|outside region/, path);
  assert.throws(() => habitatTileURL(manifestURL, record, 'other-region'), /outside region/);
  assert.throws(() => habitatTileURL(manifestURL, {...record, sha256: 'abc'}, REGION));
  assert.throws(() => habitatTileURL(manifestURL, {...record, bytes: 6_000_000}, REGION));
});

test('a checked feed becomes the report\'s analysis shape, in °F, without land or error-less cells', async () => {
  const f = feed(), got = await read(f);
  assert.equal(got.state, 'ready');
  assert.equal(got.product, 'NOAA Geo-Polar Blended night SST');
  assert.deepEqual(regionalStatus(true, got, AT, NOW, TZ, true), regionalStatus(true, got, AT, NOW, TZ), 'usable saved SST is not mislabelled missing');
  assert.equal(got.maxAgeMs, 72 * HOUR);
  const {points, ...rest} = got.sst;
  assert.deepEqual(rest, {sourceId: 'noaa-blended-sst', analysedAt: '2026-10-15T12:00:00.000Z', fetchedAt: '2026-10-16T06:00:00Z', nativeResolutionDeg: 0.05,
    sampleSpacingDeg: 0.05, url: f.manifest.sources['sst-analysis'].url, kind: 'analysis'});
  assert.equal(points.length, 22, 'the land cell and the cell with no analysis error are left out');
  assert.ok(!points.some(p => p.lon === -120.975 && p.lat === 35.025), 'land stays blank');
  const corner = points.find(p => p.lon === -120.875 && p.lat === 35.025);
  assert.ok(Math.abs(corner.tempF - (14.4 * 1.8 + 32)) < 1e-9 && Math.abs(corner.errorF - 0.54) < 1e-9);
});

test('a missing feed or layer is "none"; a failed read or any failed tile check refuses the whole analysis', async () => {
  assert.deepEqual(await read(feed(), {manifestStatus: 404}), {state: 'none'});
  const noLayer = feed();
  delete noLayer.manifest.layers['sst-analysis'];
  assert.deepEqual(await read(noLayer), {state: 'none'});
  assert.deepEqual(await read(feed(), {manifestStatus: 503}), {state: 'error'});
  assert.deepEqual(await read(feed({region: 'other-region'})), {state: 'error'}, 'a manifest for another region');
  assert.deepEqual(await read(feed(), {tileStatus: 500}), {state: 'error'});
  const cases = {
    'hash': feed({record: (r, k) => (k === 1 ? {...r, sha256: 'f'.repeat(64)} : r)}),
    'length': feed({record: (r, k) => (k === 1 ? {...r, bytes: r.bytes + 1} : r)}),
    'tile region': feed({tile: (t, k) => (k === 1 ? {...t, region_id: 'other-region'} : t)}),
    'tile layer': feed({tile: (t, k) => (k === 1 ? {...t, layer_id: 'chlorophyll-observation'} : t)}),
    'tile grid': feed({tile: (t, k) => (k === 1 ? {...t, resolution_degrees: [0.01, 0.01]} : t)}),
    'tile bounds': feed({tile: (t, k) => (k === 1 ? {...t, bounds: [-120.8, 35.0, -120.7, 35.2]} : t)}),
    'tile frame time': feed({tile: (t, k) => (k === 1 ? {...t, frames: [{...t.frames[0], time: TIME + 86400}]} : t)}),
    'tile cell': feed({tile: (t, k) => (k === 1 ? {...t, frames: [{...t.frames[0], cells: [[35, -120.8, '14']]}]} : t)}),
  };
  for (const [name, f] of Object.entries(cases)) assert.deepEqual(await read(f), {state: 'error'}, name);
});

test('tiles are read only for an ok or retained layer inside its own age limit', async () => {
  for (const status of ['stale', 'error', 'unavailable']) {
    const s = server(feed({status}));
    const got = await regionalSST(REGION, {fetchFn: s.fetchFn, page: PAGE, now: NOW});
    assert.deepEqual(got, {state: 'listed', product: 'NOAA Geo-Polar Blended night SST', analysedAt: '2026-10-15T12:00:00.000Z', maxAgeMs: 72 * HOUR, layerStatus: status});
    assert.deepEqual(s.asked, [`${BASE}habitat-dynamics.json`], `${status}: no tile is fetched`);
  }
  assert.equal((await read(feed({status: 'retained'}))).state, 'ready');
  const old = server(feed({maxAge: 12}));
  assert.equal((await regionalSST(REGION, {fetchFn: old.fetchFn, page: PAGE, now: NOW})).state, 'listed', 'past the layer\'s own 12-hour limit');
  assert.equal(old.asked.length, 1);
});

test('the rail and legend name the feed\'s product, date and age limit, or why nothing draws', async () => {
  const reason = s => [s.note, s.reason];
  assert.deepEqual(regionalStatus(false, null, AT, NOW, TZ).note, '');
  assert.deepEqual(reason(regionalStatus(true, null, AT, NOW, TZ)), ['loading', 'Loading the region\'s surface-temperature analysis.']);
  assert.deepEqual(reason(regionalStatus(true, {state: 'none'}, AT, NOW, TZ)),
    ['no analysis for this region', 'Water temp unavailable: no local surface-temperature analysis covers this region yet.']);
  assert.equal(regionalStatus(true, {state: 'error'}, AT, NOW, TZ).note, 'unavailable');
  const listed = {state: 'listed', product: 'NOAA Geo-Polar Blended night SST', analysedAt: '2026-10-15T12:00:00.000Z', maxAgeMs: 72 * HOUR};
  assert.deepEqual(reason(regionalStatus(true, {...listed, layerStatus: 'stale'}, AT, NOW, TZ)), ['no fresh analysis · last Oct 15',
    'Water temp unavailable: the latest NOAA Geo-Polar Blended night SST analysis, for Oct 15, is past its 72-hour age limit.']);
  assert.equal(regionalStatus(true, {...listed, layerStatus: 'error'}, AT, NOW, TZ).note, 'no analysis in the feed');

  const ready = await read(feed());
  const drawn = regionalStatus(true, ready, AT, NOW, TZ);
  assert.equal(drawn.note, 'analysis Oct 15 · 24 h old');
  assert.equal(drawn.drawn.limitMs, 72 * HOUR);
  assert.match(drawn.basis, /^NOAA Geo-Polar Blended night SST daily analysis on a 0\.05° grid, for Oct 15 \(24 h old\), with an analysis error of 0\.5 °F\./);
  assert.equal(regionalStatus(true, ready, new Date('2026-10-15T11:00:00Z'), NOW, TZ).note, 'analysis after this hour · Oct 15');
  assert.equal(regionalStatus(true, ready, AT, new Date('2026-10-18T13:00:00Z'), TZ).note, 'no fresh analysis · last Oct 15', 'judged again as the clock moves on');
  const short = await regionalSST(REGION, {fetchFn: server(feed({maxAge: 48})).fetchFn, page: PAGE, now: NOW});
  assert.equal(regionalStatus(true, short, AT, new Date('2026-10-17T13:00:00Z'), TZ).reason,
    'Water temp unavailable: the latest NOAA Geo-Polar Blended night SST analysis, for Oct 15, is past its 48-hour age limit.', 'the layer\'s own limit');
});

/** As tests/test_field_texture.mjs: a browser just big enough for the store, and an engine that records what was drawn. */
function browser(href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
}
function engine() {
  const e = {overlay: null, images: []};
  return Object.assign(e, {
    setOverlay(_layer, overlay) { e.overlay = overlay; }, setImage(id, texture) { e.images.push([id, texture]); }, setData() {},
    setRasterOpacity() {}, setCamera() {}, setVisible() {}, destroy() {},
  });
}
const settle = () => new Promise(resolve => setImmediate(resolve));
/** Waits until `done()` (the tiles' SHA-256 checks are asynchronous and slow under a loaded suite), at most 5 s. */
async function until(done) { for (const end = Date.now() + 5000; !done() && Date.now() < end;) await new Promise(resolve => setTimeout(resolve, 5)); }

test('Morro Bay layers display the offline reason on startup and update it on reconnect', () => {
  browser(`${PAGE}?region=morro-bay&layers=water-temp&current=wcofs`);
  const navigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  const old = {addEventListener: globalThis.addEventListener, removeEventListener: globalThis.removeEventListener};
  const events = new EventTarget(), connection = {onLine: false};
  Object.defineProperty(globalThis, 'navigator', {value: connection, configurable: true});
  globalThis.addEventListener = events.addEventListener.bind(events);
  globalThis.removeEventListener = events.removeEventListener.bind(events);
  const data = {coastReport: signal(null), coastOcean: signal(null), coastStatus: signal({report: 'error', ocean: 'error'}), setPlace() {}, load: async () => {}};
  const options = {zone: () => TZ, place: () => ({regionId: 'morro-bay'}), data, now: () => NOW, palette: () => readPalette(name => `token(${name})`)};
  let water, currents;
  try {
    water = createWaterTemp({...options, engine: signal(engine())});
    currents = createCurrents({...options, view: {}, doc: null, source: () => 'wcofs'});
    assert.equal(railNotes.value['water-temp'], 'not saved for offline');
    assert.equal(currentsState.value.note, 'not saved for offline');
    assert.match(waterTempState.value.reason, /Save Coastal readings/);
    assert.match(currentsState.value.reason, /Save Coastal readings/);
    connection.onLine = true; events.dispatchEvent(new Event('online'));
    assert.equal(railNotes.value['water-temp'], 'unavailable');
    assert.equal(currentsState.value.note, 'unavailable');
  } finally {
    water?.destroy(); currents?.destroy();
    Object.assign(globalThis, old);
    if (navigator) Object.defineProperty(globalThis, 'navigator', navigator); else delete globalThis.navigator;
  }
});

test('a place with no local report draws its region\'s feed; a bound place never asks for it', async t => {
  browser(`${PAGE}?region=${REGION}&layers=none`);
  const e = engine(), s = server(feed());
  const coastStatus = signal({report: 'unbound', ocean: 'unbound', history: 'unbound'});
  const data = {coastReport: signal(null), coastStatus, setPlace() {}, load: async () => {}};
  const w = createWaterTemp({engine: signal(e), zone: () => TZ, place: () => ({regionId: REGION}), data, palette: () => readPalette(name => `token(${name})`),
    now: () => NOW, fetchFn: s.fetchFn, page: () => PAGE});
  t.after(() => w.destroy());
  await settle();
  assert.deepEqual(s.asked, [], 'nothing is read while Water temp is off');

  setParams({layers: 'water-temp'});
  assert.equal(railNotes.value['water-temp'], 'loading');
  await until(() => waterTempState.value.note !== 'loading');
  assert.equal(s.asked.length, 3, 'the manifest and its two tiles');
  assert.equal(waterTempState.value.note, 'analysis Oct 15 · 24 h old');
  assert.equal(railNotes.value['water-temp'], 'analysis Oct 15 · 24 h old');
  assert.equal(e.images.length, 1, 'the texture is painted');
  assert.ok(e.overlay);

  setParams({layers: 'none'});
  setParams({layers: 'water-temp'});
  await settle();
  assert.equal(s.asked.length, 3, 'read once within the hour');

  coastStatus.value = {report: 'loading', ocean: 'idle', history: 'idle'};
  assert.equal(waterTempState.value.note, 'loading', 'a bound place follows its report, not the feed');
  assert.equal(e.overlay, null);
  await settle();
  assert.equal(s.asked.length, 3);
});

// #482: the region's WCOFS surface forecast for Currents, through packages/coast `selectedCurrent`.
const C_NOW = new Date('2026-10-07T12:20:00Z'), C_AT = new Date('2026-10-07T12:00:00Z');
const C_TIMES = ['2026-10-07T09:00:00Z', '2026-10-07T12:00:00Z', '2026-10-07T15:00:00Z'].map(t => Date.parse(t) / 1000);
/** 8 × 8 cells 0.04° apart, split into two tiles by column; (0, 0) is dry. */
const C_GRIDS = [0, 1].map(k => {
  const cells = [];
  for (let j = 0; j < 8; j++) for (let i = k * 4; i < k * 4 + 4; i++) cells.push([+(35.5 - j * 0.04).toFixed(6), +(-121 + i * 0.04).toFixed(6)]);
  return {bounds: [-121.02 + k * 0.16, 35.2, -120.86 + k * 0.16, 35.52], cells};
});
const cFeed = (extra = {}) => wcofsFeed({region: REGION, times: C_TIMES, grids: C_GRIDS, issuedAt: '2026-10-07T03:00:00Z', retrievedAt: '2026-10-07T11:50:00Z',
  flow: (lat, lon) => (lat === 35.5 && lon === -121 ? null : [0.3, -0.4]), ...extra});
const cRead = (f, opts) => regionalCurrents(REGION, {fetchFn: feedServer(f, {page: PAGE, region: REGION, ...opts}).fetchFn, page: PAGE, now: C_NOW});

test('a checked WCOFS layer becomes the packet\'s CurrentField, wet cells only, speed and toward-bearing from u and v', async () => {
  const got = await cRead(cFeed());
  assert.equal(got.state, 'ready');
  const {frames, ...field} = got.field;
  assert.deepEqual(field, {id: 'wcofs', kind: 'forecast', label: 'NOAA WCOFS surface-current forecast', url: 'https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html',
    fetchedAt: '2026-10-07T11:50:00Z', issuedAt: '2026-10-07T03:00:00Z', sampleAt: null, nativeResolutionKm: 4, sampleStride: 1, horizontalDatum: 'NAD83', surfaceOnly: true,
    attribution: 'NOAA National Ocean Service · WCOFS', license: 'public-domain-us-gov', limitations: 'Synthetic test forecast.'});
  assert.deepEqual(frames.map(f => f.validAt), ['2026-10-07T09:00:00.000Z', '2026-10-07T12:00:00.000Z', '2026-10-07T15:00:00.000Z']);
  assert.equal(frames[1].cells.length, 63, 'the dry cell is left out');
  const c = frames[1].cells[0];
  assert.ok(Math.abs(c.speedKnots - 0.5 * 1.94384449) < 1e-9);
  assert.ok(Math.abs(c.towardDeg - (Math.atan2(0.3, -0.4) * 180 / Math.PI + 360) % 360) < 1e-9, 'toward the south-south-east');
  assert.ok(validCurrentField(got.field), 'packages/coast accepts it as a current field');
});

test('WCOFS tiles are read only for an ok or retained layer issued inside its own limit; a failed tile refuses it', async () => {
  for (const status of ['stale', 'error']) {
    const s = feedServer(cFeed({status}), {page: PAGE, region: REGION});
    const got = await regionalCurrents(REGION, {fetchFn: s.fetchFn, page: PAGE, now: C_NOW});
    assert.deepEqual(got, {state: 'listed', validAt: ['2026-10-07T09:00:00.000Z', '2026-10-07T12:00:00.000Z', '2026-10-07T15:00:00.000Z'], layerStatus: status});
    assert.equal(s.asked.length, 1, `${status}: no tile is fetched`);
  }
  assert.equal((await cRead(cFeed({issuedAt: '2026-10-05T03:00:00Z'}))).state, 'listed', 'issued past its own 36 hours');
  assert.deepEqual(await cRead(cFeed(), {manifestStatus: 404}), {state: 'none'});
  assert.deepEqual(await cRead(cFeed({record: (r, k) => (k ? {...r, sha256: '0'.repeat(64)} : r)})), {state: 'error'});
  assert.deepEqual(await cRead(cFeed({tile: (t, k) => (k ? {...t, layer_id: 'sst-analysis'} : t)})), {state: 'error'});
  assert.deepEqual(await cRead(cFeed({tile: (t, k) => (k ? {...t, frames: [...t.frames, t.frames[0]]} : t)})), {state: 'error'}, 'a repeated frame');
});

test('Currents from the feed: the forecast frame and its grid, its last frame when stale, and radar only from a packet', async () => {
  const ready = await cRead(cFeed());
  assert.equal(regionalCurrentsStatus('off', ready, C_AT, C_NOW, TZ).note, '');
  assert.equal(regionalCurrentsStatus('wcofs', null, C_AT, C_NOW, TZ).note, 'loading');
  const drawn = regionalCurrentsStatus('wcofs', ready, C_AT, C_NOW, TZ);
  const saved = regionalCurrentsStatus('wcofs', ready, C_AT, C_NOW, TZ, true);
  assert.equal(saved.note, drawn.note, 'usable saved currents are not mislabelled missing');
  assert.equal(saved.drawn.frame, drawn.drawn.frame);
  assert.equal(saved.drawn.expiresAt, drawn.drawn.expiresAt, 'the existing age gate is unchanged');
  assert.equal(drawn.note, 'forecast Wed 5 am');
  assert.equal(drawn.drawn.frame.validAt, '2026-10-07T12:00:00.000Z');
  assert.match(drawn.basis, /^NOAA WCOFS surface forecast, about 4 km, issued 9 h ago;/);
  assert.equal(regionalCurrentsStatus('wcofs', ready, C_AT, new Date('2026-10-07T18:00:00Z'), TZ).note, 'no fresh frame · last Wed 5 am',
    'packages/coast\'s six-hour retrieval limit applies to the feed as to the packet');
  assert.equal(regionalCurrentsStatus('wcofs', {state: 'listed', validAt: ['2026-10-07T09:00:00.000Z'], layerStatus: 'stale'}, C_AT, C_NOW, TZ).note, 'no fresh frame · last Wed 2 am');
  assert.deepEqual([regionalCurrentsStatus('wcofs', {state: 'none'}, C_AT, C_NOW, TZ).note, regionalCurrentsStatus('wcofs', {state: 'error'}, C_AT, C_NOW, TZ).note],
    ['no forecast for this region', 'unavailable']);
  const radar = regionalCurrentsStatus('hfr-1', ready, C_AT, C_NOW, TZ);
  assert.deepEqual([radar.note, radar.drawn], ['no radar for this region', null]);
  assert.equal(radar.reason, 'Currents unavailable: Observed HF radar · 1 km is published only where a local surface-current packet covers the region; the NOAA WCOFS forecast may be.');
});

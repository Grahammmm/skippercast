// #491: Water temp outside a report binding. web/map/habitat-feed.ts reads the region's published
// habitat-dynamics manifest and its SHA-256-checked surface-temperature tiles; web/map/sst.ts judges the
// result with the report's gate (age, the dock's hour, the grid). The manifest and tiles here are
// synthetic, in the pipeline's shape (src/skippercast/pipeline/habitat_dynamics.py).
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {signal} from '@preact/signals';
import {habitatManifestURL, habitatTileURL, regionalSST} from '../web/map/habitat-feed.ts';
import {railNotes} from '../web/map/layers.ts';
import {readPalette} from '../web/map/palette.ts';
import {createWaterTemp, regionalStatus, waterTempState} from '../web/map/sst.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

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
  for (let i = 0; i < 100 && waterTempState.value.note === 'loading'; i++) await settle();   // the tiles' SHA-256 checks are asynchronous
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

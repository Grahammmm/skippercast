import assert from 'node:assert/strict';
import test from 'node:test';
import {answer, cellWeights, hermite, meta, weatherCode} from '../server/model-api.js';

// A 3x3 tile, 0.25 degree cells, SW corner at (35, -121). Bottom-left cell is land.
const times = [0, 3600, 7200, 18000];  // 0h, 1h, 2h, 5h: an hourly run then a 3-hour gap
const plane = 9;
const q16 = (values, scale) => Buffer.from(new Int16Array(values.map(v => (v == null ? -32768 : Math.round(v / scale)))).buffer).toString('base64');
function field(fn, scale) {
  const values = [];
  for (let t = 0; t < times.length; t++) for (let j = 0; j < 3; j++) for (let i = 0; i < 3; i++) values.push(fn(t, j, i));
  return {scale, data: q16(values, scale)};
}
const seaBits = [0, 1, 1, 1, 1, 1, 1, 1, 1];  // row-major from the south-west corner
const sea = Buffer.from([seaBits.slice(0, 8).reduce((a, b, k) => a | (b << (7 - k)), 0), seaBits[8] << 7]).toString('base64');
const windTile = {
  schema_version: 1, model: 'gfs_global', key: '35_-121', times, lat0: 35, lon0: -121, dlat: 0.25, dlon: 0.25, nlat: 3, nlon: 3, sea,
  fields: {
    u10: field(() => 0, 0.01), v10: field(t => -[5, 6, 7, 10][t], 0.01),   // wind FROM the north, m/s
    gust: field(t => [7, 8, 9, 12][t], 0.01), visibility: field(() => 20000, 10), t2m: field(() => 15, 0.01),
    precipitation: field(() => 0, 0.01), cloud_cover: field(() => 90, 0.1),
  },
};
const waveTile = {
  ...windTile, model: 'ncep_gfswave016', fields: {
    wave_height: field((t, j, i) => (j === 0 && i === 0 ? null : 2), 0.01),
    wave_period: field(() => 10, 0.01), wave_direction: field(() => 350, 0.1),
  },
};
const manifest = model => ({model, tiles: ['35_-121'], meta: {last_run_initialisation_time: 0, data_end_time: 18000},
  provider: 'test', documentation: 'x', cycle_iso: '1970-01-01T00:00:00Z'});
const store = {manifest: async m => manifest(m), tile: async m => (m === 'gfs_global' ? windTile : waveTile)};

test('monotone cubic interpolation hits native values and never overshoots', () => {
  const out = hermite([0, 3, 6], [0, 10, 10], [0, 1, 2, 3, 4, 5, 6]);
  assert.equal(out[0], 0); assert.equal(out[3], 10); assert.equal(out[6], 10);
  for (let k = 1; k < out.length; k++) assert.ok(out[k] >= out[k - 1] - 1e-9 && out[k] <= 10 + 1e-9);
  assert.deepEqual(hermite([0, 3], [1, null], [0, 1, 3, 4]), [1, null, null, null]);
});

test('sea selection drops land cells and renormalizes', () => {
  const w = cellWeights(windTile, 35.1, -120.9, true);
  assert.ok(w.cells.every(([j, i]) => !(j === 0 && i === 0)));
  assert.ok(Math.abs(w.cells.reduce((s, c) => s + c[2], 0) - 1) < 1e-9);
  assert.equal(cellWeights(windTile, 35.1, -120.9, false).cells.length, 4);
});

test('weather codes follow fog, precipitation and cloud thresholds', () => {
  assert.equal(weatherCode(0, 10, 500, 15), 45);
  assert.equal(weatherCode(3, 100, 20000, 15), 63);
  assert.equal(weatherCode(0, 90, 20000, 15), 3);
  assert.equal(weatherCode(0, 10, 20000, 15), 0);
});

test('forecast answers look like Open-Meteo: units, suffixes, local times, hourly fill', async () => {
  const params = new URLSearchParams({latitude: '35.25', longitude: '-120.75', models: 'gfs_global', forecast_days: '1',
    hourly: 'wind_speed_10m,wind_direction_10m,wind_gusts_10m,weather_code', wind_speed_unit: 'kn', timezone: 'UTC', timeformat: 'unixtime'});
  const r = await answer('forecast', params, store, 3600);
  assert.equal(r.hourly_units.wind_speed_10m, 'kn');
  assert.equal(r.hourly.time[0], 0);
  assert.equal(r.hourly.wind_speed_10m[0], 9.7);           // 5 m/s
  assert.equal(r.hourly.wind_direction_10m[0], 0);          // from the north
  assert.ok(r.hourly.wind_speed_10m[3] > 13.6 && r.hourly.wind_speed_10m[3] < 19.4);  // between 7 and 10 m/s
  assert.equal(r.hourly.wind_speed_10m[6], null);           // beyond the model's last step
  assert.equal(r.hourly.weather_code[0], 3);
  const both = await answer('forecast', new URLSearchParams({latitude: '35.25,35.3', longitude: '-120.75,-120.8',
    models: 'gfs_global,gfs_global', hourly: 'wind_speed_10m', timezone: 'America/Los_Angeles', forecast_days: '1'}), store, 3600);
  assert.ok(Array.isArray(both) && both.length === 2);
  assert.ok('wind_speed_10m_gfs_global' in both[0].hourly);
  assert.match(both[0].hourly.time[0], /^\d{4}-\d{2}-\d{2}T00:00$/);
  assert.equal(both[0].timezone, 'America/Los_Angeles');
});

test('marine answers use sea cells, imperial heights and circular directions', async () => {
  const r = await answer('marine', new URLSearchParams({latitude: '35.05', longitude: '-120.95', models: 'ncep_gfswave016',
    hourly: 'wave_height,wave_direction,swell_wave_height', length_unit: 'imperial', timezone: 'UTC', forecast_days: '1', timeformat: 'unixtime'}), store, 0);
  assert.equal(r.hourly.wave_height[0], 6.56);
  assert.equal(r.hourly.wave_direction[0], 350);
  assert.equal(r.hourly.swell_wave_height[0], null);        // not in this tile
  assert.ok(!(r.latitude === 35 && r.longitude === -121));  // never reports the land cell
});

test('bad queries are rejected and meta mirrors Open-Meteo', async () => {
  await assert.rejects(answer('forecast', new URLSearchParams({latitude: '1', longitude: '2', models: 'ecmwf_wam'}), store), /not available/);
  await assert.rejects(answer('forecast', new URLSearchParams({latitude: '1', longitude: '2', hourly: 'bogus'}), store), /not available/);
  await assert.rejects(answer('forecast', new URLSearchParams({latitude: '1,2', longitude: '2'}), store), /matching/);
  assert.equal((await meta('gfs_global', store)).last_run_initialisation_time, 0);
});

test('scripts/model_api.mjs (the Python pipeline sampler) runs under plain node and matches answer()', async () => {
  // src/skippercast/forecast/local.py runs exactly this command; model-api stays
  // plain JavaScript so it needs no TypeScript support from the node it finds.
  const {mkdtempSync, mkdirSync, writeFileSync, rmSync} = await import('node:fs');
  const {tmpdir} = await import('node:os');
  const {join} = await import('node:path');
  const {spawnSync} = await import('node:child_process');
  const root = mkdtempSync(join(tmpdir(), 'sc-tiles-'));
  try {
    for (const [model, tile] of [['gfs_global', windTile], ['ncep_gfswave016', waveTile]]) {
      mkdirSync(join(root, model, 'tiles'), {recursive: true});
      writeFileSync(join(root, model, 'manifest.json'), JSON.stringify(manifest(model)));
      writeFileSync(join(root, model, 'tiles', '35_-121.json'), JSON.stringify(tile));
    }
    const query = 'latitude=35.25&longitude=-120.75&models=gfs_global&hourly=wind_speed_10m,wind_gusts_10m&wind_speed_unit=kn&timezone=UTC&timeformat=unixtime&forecast_days=1';
    const script = new URL('../scripts/model_api.mjs', import.meta.url).pathname;
    const run = (...args) => spawnSync(process.execPath, ['--no-experimental-strip-types', script, root, ...args], {encoding: 'utf8', env: {...process.env, SKIPPERCAST_NOW: '3600'}});
    const out = run('forecast', query);
    assert.equal(out.status, 0, out.stderr);
    const cli = JSON.parse(out.stdout), direct = await answer('forecast', new URLSearchParams(query), store, 3600);
    delete cli.generationtime_ms; delete direct.generationtime_ms;
    assert.deepEqual(cli, direct);
    const described = run('meta', 'gfs_global');
    assert.equal(described.status, 0, described.stderr);
    assert.deepEqual(JSON.parse(described.stdout), await meta('gfs_global', store));
    const rejected = run('meta', 'nope');
    assert.equal(rejected.status, 3);assert.equal(JSON.parse(rejected.stdout).reason, 'Unknown model');
  } finally { rmSync(root, {recursive: true, force: true}); }
});

test('repeated models and same-tile points have bounded reads while retaining suffixes and values', async () => {
  const counts = {manifests: 0, tiles: 0, decodedU: 0};
  const counted = {
    manifest: async m => { counts.manifests++; return manifest(m); },
    tile: async () => {
      counts.tiles++;
      const tile = structuredClone(windTile), data = tile.fields.u10.data;
      Object.defineProperty(tile.fields.u10, 'data', {get() { counts.decodedU++; return data; }});
      return tile;
    },
  };
  const params = new URLSearchParams({latitude: Array(50).fill('35.25').join(','), longitude: Array(50).fill('-120.75').join(','),
    models: Array(100).fill('gfs_global').join(','), hourly: Array(100).fill('wind_speed_10m').join(','),
    forecast_days: '8', timezone: 'UTC', timeformat: 'unixtime', wind_speed_unit: 'kn'});
  const results = await answer('forecast', params, counted, 3600);
  assert.equal(results.length, 50);
  assert.deepEqual(counts, {manifests: 1, tiles: 1, decodedU: 1});
  for (const r of results) {
    assert.equal(r.hourly.wind_speed_10m_gfs_global[0], 9.7);
    assert.equal(r.hourly.wind_speed_10m_gfs_global[6], null);
    assert.deepEqual(Object.keys(r.hourly), ['time', 'wind_speed_10m_gfs_global']);
    assert.equal(r.hourly_units.wind_speed_10m_gfs_global, 'kn');
  }
  // Request-local memoization must not reuse the preceding request's storage.
  await answer('forecast', params, counted, 3600);
  assert.deepEqual(counts, {manifests: 2, tiles: 2, decodedU: 2});
});

test('both models read each distinct tile once, including a null tile, and retain output order', async () => {
  const manifests = [], tiles = [];
  const counted = {
    manifest: async m => { manifests.push(m); return {tiles: ['35_-121', '36_-121']}; },
    tile: async (m, key) => { tiles.push(`${m}/${key}`); return key === '35_-121' ? windTile : null; },
  };
  const results = await answer('forecast', new URLSearchParams({latitude: '35.25,35.3,36.1,36.2',
    longitude: '-120.75,-120.8,-120.9,-120.9', models: 'ecmwf_ifs025,gfs_global,ecmwf_ifs025',
    hourly: 'temperature_2m,wind_speed_10m,temperature_2m', forecast_days: '1', timezone: 'UTC'}), counted, 3600);
  assert.deepEqual(manifests, ['ecmwf_ifs025', 'gfs_global']);
  assert.deepEqual(tiles, ['ecmwf_ifs025/35_-121', 'gfs_global/35_-121', 'ecmwf_ifs025/36_-121', 'gfs_global/36_-121']);
  assert.deepEqual(Object.keys(results[0].hourly), ['time', 'temperature_2m_ecmwf_ifs025', 'wind_speed_10m_ecmwf_ifs025',
    'temperature_2m_gfs_global', 'wind_speed_10m_gfs_global']);
  assert.equal(results[0].hourly.temperature_2m_ecmwf_ifs025[0], 15);
  assert.ok(results[2].hourly.wind_speed_10m_gfs_global.every(v => v === null));
});

test('duplicate marine variables are computed once without changing units or missing values', async () => {
  const tile = structuredClone(waveTile), value = tile.fields.wave_height;
  let accesses = 0;
  Object.defineProperty(tile.fields, 'wave_height', {get() { accesses++; return value; }});
  const r = await answer('marine', new URLSearchParams({latitude: '35.05', longitude: '-120.95',
    hourly: Array(100).fill('wave_height').concat('swell_wave_height').join(','), forecast_days: '1',
    length_unit: 'imperial', timezone: 'UTC'}), {manifest: async () => manifest('ncep_gfswave016'), tile: async () => tile}, 0);
  assert.ok(accesses <= 3, `repeated variable caused ${accesses} field reads`);
  assert.equal(r.hourly.wave_height[0], 6.56);
  assert.equal(r.hourly_units.wave_height, 'ft');
  assert.equal(r.hourly.swell_wave_height[0], null);
});

test('timezone formatter cost stays constant across fifty points and DST time axes remain correct', async () => {
  const Original = Intl.DateTimeFormat;
  let constructions = 0;
  Intl.DateTimeFormat = new Proxy(Original, {construct(target, args) { constructions++; return Reflect.construct(target, args); }});
  try {
    const query = {hourly: 'wind_speed_10m', forecast_days: '8', timezone: 'America/Los_Angeles'};
    const spring = Date.UTC(2026, 2, 8, 12) / 1000;
    const one = await answer('forecast', new URLSearchParams({...query, latitude: '35.25', longitude: '-120.75'}), store, spring);
    const oneCost = constructions;
    constructions = 0;
    const many = await answer('forecast', new URLSearchParams({...query, latitude: Array(50).fill('35.25').join(','),
      longitude: Array(50).fill('-120.75').join(',')}), store, spring);
    assert.equal(constructions, oneCost);
    assert.ok(constructions <= 4, `formatter budget exceeded: ${constructions}`);
    assert.deepEqual(one.hourly.time.slice(0, 4), ['2026-03-08T00:00', '2026-03-08T01:00', '2026-03-08T03:00', '2026-03-08T04:00']);
    assert.equal(one.utc_offset_seconds, -25200);
    assert.equal(one.timezone_abbreviation, 'PDT');
    assert.deepEqual(many[49].hourly.time, one.hourly.time);
    assert.notEqual(many[0].hourly.time, many[1].hourly.time, 'point time arrays remain independently mutable');
    const fall = await answer('forecast', new URLSearchParams({...query, latitude: '35.25', longitude: '-120.75'}), store,
      Date.UTC(2026, 10, 1, 12) / 1000);
    assert.deepEqual(fall.hourly.time.slice(0, 4), ['2026-11-01T00:00', '2026-11-01T01:00', '2026-11-01T01:00', '2026-11-01T02:00']);
    assert.equal(fall.utc_offset_seconds, -28800);
    assert.equal(fall.timezone_abbreviation, 'PST');
  } finally { Intl.DateTimeFormat = Original; }
});

test('all input validation precedes storage and a tile failure never becomes a cached null response', async () => {
  let reads = 0;
  const rejectStore = {manifest: async () => { reads++; return manifest('gfs_global'); },
    tile: async () => { reads++; throw Error('tile unavailable'); }};
  for (const bad of [{models: 'gfs_global,unknown'}, {hourly: 'wind_speed_10m,unknown'}, {forecast_days: '9'},
    {timezone: 'No/Such_Zone'}, {wind_speed_unit: 'unknown'}, {latitude: '35.1,35.2'}]) {
    await assert.rejects(answer('forecast', new URLSearchParams({latitude: '35.25', longitude: '-120.75', ...bad}), rejectStore, 0));
    assert.equal(reads, 0);
  }
  const valid = new URLSearchParams({latitude: '35.25', longitude: '-120.75', hourly: 'wind_speed_10m'});
  await assert.rejects(answer('forecast', valid, rejectStore, 0), /tile unavailable/);
  await assert.rejects(answer('forecast', valid, rejectStore, 0), /tile unavailable/);
  assert.equal(reads, 4);
});

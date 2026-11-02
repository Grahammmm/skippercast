// /api/om model answers refuse out-of-range coordinates and unknown
// cell_selection values before any manifest or tile read (RF2310-10).
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {answer, QueryError} from '../server/model-api.js';

// A 3x3 tile, 0.25 degree cells, SW corner at (35, -121). Bottom-left cell is land.
const times = [0, 3600, 7200, 18000];
const q16 = (values, scale) => Buffer.from(new Int16Array(values.map(v => (v == null ? -32768 : Math.round(v / scale)))).buffer).toString('base64');
function field(fn, scale) {
  const values = [];
  for (let t = 0; t < times.length; t++) for (let j = 0; j < 3; j++) for (let i = 0; i < 3; i++) values.push(fn(t, j, i));
  return {scale, data: q16(values, scale)};
}
const seaBits = [0, 1, 1, 1, 1, 1, 1, 1, 1];
const sea = Buffer.from([seaBits.slice(0, 8).reduce((a, b, k) => a | (b << (7 - k)), 0), seaBits[8] << 7]).toString('base64');
const tile = {
  schema_version: 1, model: 'gfs_global', key: '35_-121', times, lat0: 35, lon0: -121, dlat: 0.25, dlon: 0.25, nlat: 3, nlon: 3, sea,
  fields: {u10: field(() => 0, 0.01), v10: field(t => -[5, 6, 7, 10][t], 0.01), t2m: field((t, j, i) => 10 + 3 * j + i, 0.01)},
};
const manifest = model => ({model, tiles: ['35_-121'], meta: {last_run_initialisation_time: 0, data_end_time: 18000}});
function counting() {
  const store = {reads: 0, manifest: async m => { store.reads++; return manifest(m); }, tile: async () => { store.reads++; return tile; }};
  return store;
}
const query = extra => new URLSearchParams({latitude: '35.1', longitude: '-120.9', models: 'gfs_global',
  hourly: 'temperature_2m,wind_speed_10m', forecast_days: '1', timezone: 'UTC', timeformat: 'unixtime', ...extra});

test('out-of-range latitude or longitude is a QueryError before any read', async () => {
  const LAT = /Latitude must be in range of -90 to 90°$/, LON = /Longitude must be in range of -180 to 180°$/;
  for (const [bad, message] of [[{latitude: '90.0001'}, LAT], [{latitude: '-90.0001'}, LAT],
    [{longitude: '180.0001'}, LON], [{longitude: '-180.0001'}, LON],
    [{latitude: '35.1,95', longitude: '-120.9,-120.9'}, LAT], [{latitude: '35.1,35.2', longitude: '-120.9,400'}, LON]]) {
    const store = counting();
    await assert.rejects(answer('forecast', query(bad), store, 0), e => e instanceof QueryError && message.test(e.message), JSON.stringify(bad));
    await assert.rejects(answer('marine', query({...bad, models: 'ncep_gfswave016', hourly: 'wave_height'}), store, 0), message);
    assert.equal(store.reads, 0, JSON.stringify(bad));
  }
});

test('boundary coordinates are accepted and answer with null hours', async () => {
  for (const edge of [{latitude: '90'}, {latitude: '-90'}, {longitude: '180'}, {longitude: '-180'}, {latitude: '90', longitude: '-180'}]) {
    const r = await answer('forecast', query(edge), counting(), 0);
    assert.equal(r.hourly.time.length, 24);
    assert.ok(r.hourly.temperature_2m.every(v => v === null), JSON.stringify(edge));
    assert.ok(r.hourly.wind_speed_10m.every(v => v === null), JSON.stringify(edge));
  }
});

test('unknown cell_selection is a QueryError before any read; empty falls back to the default', async () => {
  for (const bad of ['see', 'SEA', 'Land', 'nearest ', 'sea,land']) {
    const store = counting();
    await assert.rejects(answer('forecast', query({cell_selection: bad}), store, 0), e => e instanceof QueryError && e.message === 'Invalid cell_selection', bad);
    await assert.rejects(answer('marine', query({cell_selection: bad, models: 'ncep_gfswave016', hourly: 'wave_height'}), store, 0), /Invalid cell_selection/);
    assert.equal(store.reads, 0, bad);
  }
  const strip = r => { delete r.generationtime_ms; return r; };
  const empty = strip(await answer('forecast', query({cell_selection: ''}), counting(), 0));
  assert.deepEqual(empty, strip(await answer('forecast', query({cell_selection: 'land'}), counting(), 0)));
  assert.notEqual(empty.hourly.temperature_2m[0], null);
});

test('cell_selection=nearest keeps today\'s land behaviour on forecast', async () => {
  const run = async cell => answer('forecast', query({cell_selection: cell}), counting(), 0);
  const land = await run('land'), nearest = await run('nearest'), seaOnly = await run('sea');
  assert.deepEqual(nearest.hourly, land.hourly);
  assert.deepEqual([nearest.latitude, nearest.longitude], [land.latitude, land.longitude]);
  assert.notDeepEqual(seaOnly.hourly.temperature_2m, land.hourly.temperature_2m, 'fixture separates land from sea cells');
});

test('the /api/om route answers 400 with the reason for an out-of-range latitude', async () => {
  const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
  globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
  globalThis.DEPLOYMENT = read('../deployments/production.json');
  globalThis.SHELLS = {'/landing.html': '/landing.0123456789.html', '/app.html': '/app.0123456789.html', '/sources.html': '/sources.0123456789.html'};
  globalThis.BUILD_ID = 'build-test';
  const {default: worker} = await import('../server/index.ts');
  const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
  for (const [path, reason] of [['/api/om/v1/forecast?latitude=95&longitude=0', 'Latitude must be in range of -90 to 90°'],
    ['/api/om/v1/marine?latitude=0&longitude=-181', 'Longitude must be in range of -180 to 180°'],
    ['/api/om/v1/forecast?latitude=35&longitude=-121&cell_selection=see', 'Invalid cell_selection']]) {
    const response = await worker.fetch(new Request('https://skippercast.com' + path), {ASSETS});
    assert.equal(response.status, 400, path);
    const body = await response.json();
    assert.deepEqual([body.error, body.reason], [true, reason], path);
  }
});

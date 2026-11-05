// Only kmh, ms, mph and kn are valid wind_speed_unit values: inherited Object
// names are refused with the QueryError before any manifest or tile read (RF1410-4).
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {isDeepStrictEqual} from 'node:util';
import {answer, QueryError} from '../server/model-api.js';

// A 3x3 tile, 0.25 degree cells, SW corner at (35, -121). Wind blows at 5, 6, 7, 10 m/s.
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
  fields: {u10: field(() => 0, 0.01), v10: field(t => -[5, 6, 7, 10][t], 0.01), t2m: field(() => 10, 0.01)},
};
const manifest = model => ({model, tiles: ['35_-121'], meta: {last_run_initialisation_time: 0, data_end_time: 18000}});
function counting() {
  const store = {reads: 0, manifest: async m => { store.reads++; return manifest(m); }, tile: async () => { store.reads++; return tile; }};
  return store;
}
const query = extra => new URLSearchParams({latitude: '35.1', longitude: '-120.9', models: 'gfs_global',
  hourly: 'wind_speed_10m', forecast_days: '1', timezone: 'UTC', timeformat: 'unixtime', ...extra});
const marine = extra => query({models: 'ncep_gfswave016', hourly: 'wave_height', ...extra});
const isRefusal = e => e instanceof QueryError && e.message === 'Invalid wind_speed_unit';

test('inherited object names are refused before any read, in forecast and marine', async () => {
  for (const bad of ['constructor', 'toString', '__proto__', 'valueOf', 'hasOwnProperty']) {
    const store = counting();
    await assert.rejects(answer('forecast', query({wind_speed_unit: bad}), store, 0), isRefusal, bad);
    await assert.rejects(answer('forecast', query({wind_speed_unit: bad, hourly: 'wind_gusts_10m,temperature_2m'}), store, 0), isRefusal, bad);
    await assert.rejects(answer('forecast', query({wind_speed_unit: bad, hourly: ''}), store, 0), isRefusal, bad);
    await assert.rejects(answer('marine', marine({wind_speed_unit: bad}), store, 0), isRefusal, bad);
    await assert.rejects(answer('marine', marine({wind_speed_unit: bad, hourly: ''}), store, 0), isRefusal, bad);
    assert.equal(store.reads, 0, bad);
  }
});

test('unknown, wrong-case, padded and comma-separated units are still refused; omitted and empty default to kmh', async () => {
  for (const bad of ['furlongs', 'KN', 'Kmh', 'kn ', ' kn', 'kn,ms', 'kmh,mph']) {
    const store = counting();
    await assert.rejects(answer('forecast', query({wind_speed_unit: bad}), store, 0), isRefusal, JSON.stringify(bad));
    await assert.rejects(answer('marine', marine({wind_speed_unit: bad}), store, 0), isRefusal, JSON.stringify(bad));
    assert.equal(store.reads, 0, JSON.stringify(bad));
  }
  const strip = r => { delete r.generationtime_ms; return r; };
  const omitted = strip(await answer('forecast', query(), counting(), 0));
  assert.equal(omitted.hourly_units.wind_speed_10m, 'km/h');
  assert.ok(isDeepStrictEqual(omitted, strip(await answer('forecast', query({wind_speed_unit: ''}), counting(), 0))), 'empty equals omitted');
  assert.ok(isDeepStrictEqual(omitted, strip(await answer('forecast', query({wind_speed_unit: 'kmh'}), counting(), 0))), 'kmh equals omitted');
});

test('supported units keep their conversion and label; nulls stay null', async () => {
  const expected = {kmh: [18, 'km/h'], ms: [5, 'm/s'], mph: [11.2, 'mp/h'], kn: [9.7, 'kn']};
  for (const [unit, [first, label]] of Object.entries(expected)) {
    const r = await answer('forecast', query({wind_speed_unit: unit, hourly: 'wind_speed_10m,wind_gusts_10m'}), counting(), 0);
    assert.equal(r.hourly_units.wind_speed_10m, label, unit);
    assert.equal(r.hourly_units.wind_gusts_10m, label, unit);
    assert.equal(r.hourly.wind_speed_10m[0], first, unit);
    assert.ok(r.hourly.wind_speed_10m.every(v => v === null || Number.isFinite(v)), unit);
  }
  // Off-tile coordinates have no data: every hour stays null whatever the unit.
  const r = await answer('forecast', query({wind_speed_unit: 'kn', latitude: '90'}), counting(), 0);
  assert.ok(r.hourly.wind_speed_10m.every(v => v === null));
});

test('the /api/om route answers 400 with the reason for an inherited unit and makes no upstream request', async () => {
  const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
  const saved = {};
  const names = ['REGIONS', 'DEPLOYMENT', 'SHELLS', 'BUILD_ID', 'fetch'];
  for (const n of names) saved[n] = Object.getOwnPropertyDescriptor(globalThis, n);
  let fetched = 0;
  try {
    globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
    globalThis.DEPLOYMENT = read('../deployments/production.json');
    globalThis.SHELLS = {'/landing.html': '/landing.0123456789.html', '/app.html': '/app.0123456789.html', '/sources.html': '/sources.0123456789.html'};
    globalThis.BUILD_ID = 'build-test';
    const {default: worker} = await import('../server/index.ts');
    globalThis.fetch = async () => { fetched++; throw new Error('no upstream request expected'); };
    const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
    for (const kind of ['forecast', 'marine']) for (const bad of ['constructor', 'toString', '__proto__', 'valueOf', 'hasOwnProperty']) {
      const path = `/api/om/v1/${kind}?latitude=35&longitude=-121&wind_speed_unit=${bad}`;
      const response = await worker.fetch(new Request('https://skippercast.com' + path), {ASSETS});
      assert.equal(response.status, 400, path);
      const body = await response.json();
      assert.deepEqual([body.error, body.reason], [true, 'Invalid wind_speed_unit'], path);
    }
    assert.equal(fetched, 0);
  } finally {
    for (const n of names) { if (saved[n]) Object.defineProperty(globalThis, n, saved[n]); else delete globalThis[n]; }
  }
});

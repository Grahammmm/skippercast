import assert from 'node:assert/strict';
import {readdirSync, readFileSync} from 'node:fs';
import test from 'node:test';
import {answer} from '../server/model-api.js';

// A 2x2 all-sea tile with uniform fields, native steps at 0h, 1h and 2h.
const times = [0, 3600, 7200];
const q16 = (values, scale) => Buffer.from(new Int16Array(values.map(v => (v == null ? -32768 : Math.round(v / scale)))).buffer).toString('base64');
const field = (perTime, scale) => ({scale, data: q16(perTime.flatMap(v => [v, v, v, v]), scale)});
const base = {schema_version: 1, key: '35_-121', times, lat0: 35, lon0: -121, dlat: 0.25, dlon: 0.25, nlat: 2, nlon: 2, sea: '8A=='};
const tiles = {
  gfs_global: {...base, model: 'gfs_global', fields: {u10: field([0, 0, 0], 0.01), v10: field([-7.37, 0, -12.3], 0.01),
    visibility: field([20000, 1500, 0], 10)}},
  ncep_gfswave016: {...base, model: 'ncep_gfswave016', fields: {wave_height: field([1.23, null, -0.5], 0.01)}},
};
const store = {manifest: async model => ({model, tiles: ['35_-121']}), tile: async m => tiles[m]};
const nulls = Array(21).fill(null);
const ask = async (kind, extra) => {
  const r = await answer(kind, new URLSearchParams({latitude: '35.1', longitude: '-120.9', forecast_days: '1', timezone: 'UTC',
    timeformat: 'unixtime', ...extra}), store, 0);
  delete r.generationtime_ms;
  return r;
};
const expected = (name, unit, values) => ({latitude: 35, longitude: -121, utc_offset_seconds: 0, timezone: 'UTC',
  timezone_abbreviation: 'UTC', elevation: 0, hourly_units: {time: 'unixtime', [name]: unit},
  hourly: {time: Array.from({length: 24}, (_, i) => i * 3600), [name]: [...values, ...nulls]}});

test('units.js exports exactly the factors the Worker sampler has always used', async () => {
  const units = await import('../server/units.js');  // plain node, no loader flags
  assert.deepEqual({...units}, {KN_PER_MS: 1.9438444924, MPH_PER_MS: 2.2369362921, KMH_PER_MS: 3.6, FT_PER_M: 3.28084});
});

test('no unit literal lives anywhere in server/ except units.js', () => {
  const stray = /1\.94384|2\.23693|3\.28084/;
  const walk = dir => readdirSync(dir, {withFileTypes: true}).flatMap(e => (e.name === 'node_modules' ? []
    : e.isDirectory() ? walk(`${dir}/${e.name}`) : /\.(js|ts)$/.test(e.name) ? [`${dir}/${e.name}`] : []));
  const root = new URL('../server', import.meta.url).pathname;
  const hits = walk(root).filter(path => stray.test(readFileSync(path, 'utf8'))).map(path => path.slice(root.length + 1));
  assert.deepEqual(hits, ['units.js']);
  assert.ok(!stray.test(readFileSync(`${root}/model-api.js`, 'utf8')));
});

test('wind answers are unchanged in every speed unit, including zero and beyond-range null', async () => {
  const cases = {kn: ['kn', [14.3, 0, 23.9]], mph: ['mp/h', [16.5, 0, 27.5]], kmh: ['km/h', [26.5, 0, 44.3]], ms: ['m/s', [7.4, 0, 12.3]]};
  for (const [speed, [unit, values]] of Object.entries(cases)) {
    const r = await ask('forecast', {models: 'gfs_global', hourly: 'wind_speed_10m', wind_speed_unit: speed});
    assert.deepEqual(r, expected('wind_speed_10m', unit, values), speed);
  }
});

test('imperial heights and visibility are unchanged; negatives keep their sign and nulls stay null', async () => {
  const waves = await ask('marine', {models: 'ncep_gfswave016', hourly: 'wave_height', length_unit: 'imperial'});
  assert.deepEqual(waves, expected('wave_height', 'ft', [4.04, null, -1.64]));
  const seen = await ask('forecast', {models: 'gfs_global', hourly: 'visibility', length_unit: 'imperial'});
  assert.deepEqual(seen, expected('visibility', 'ft', [65617, 4921, 0]));
});

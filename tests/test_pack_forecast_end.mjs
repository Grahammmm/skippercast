// SC2037-06: a saved pack records the last hour both its saved wind and wave models cover (dist/offline-pack.js forecastEnd),
// and the Trip list says how far the saved forecast reaches (web/trip-forecast-end.ts).
import assert from 'node:assert/strict';
import test from 'node:test';
import {forecastEnd, listPacks} from '../dist/offline-pack.js';
import {MODELS} from '../dist/marine-data.js';
import {PACK_META} from '../dist/offline-core.js';
import {forecastEndLine} from '../web/trip-forecast-end.ts';

const sec = iso => Date.parse(iso) / 1000;
const wind = MODELS.filter(m => m.kind === 'wind'), wave = MODELS.filter(m => m.kind === 'wave');
/** A cache holding the given meta bodies by model id (a string body is stored as is). */
const cacheOf = bodies => ({
  puts: 0,
  async put() { this.puts++; },
  async match(url) {
    const m = MODELS.find(x => x.meta === url);
    return m && m.id in bodies ? new Response(typeof bodies[m.id] === 'string' ? bodies[m.id] : JSON.stringify(bodies[m.id])) : undefined;
  },
});
const ends = (windIso, waveIso) => ({[wind[0].id]: {data_end_time: sec(windIso)}, [wave[0].id]: {data_end_time: sec(waveIso)}});

test('both models saved: the earlier end, as ISO; the newest model of a kind counts', async () => {
  assert.equal(await forecastEnd(cacheOf(ends('2026-11-10T00:00:00Z', '2026-11-09T18:00:00Z')), MODELS), '2026-11-09T18:00:00.000Z');
  assert.equal(await forecastEnd(cacheOf(ends('2026-11-09T06:00:00Z', '2026-11-12T00:00:00Z')), MODELS), '2026-11-09T06:00:00.000Z');
  const two = {...ends('2026-11-08T00:00:00Z', '2026-11-12T00:00:00Z'), [wind[1].id]: {data_end_time: sec('2026-11-11T00:00:00Z')}};
  assert.equal(await forecastEnd(cacheOf(two), MODELS), '2026-11-11T00:00:00.000Z');
});

test('one kind missing, unreadable or non-finite: no field, never a guess', async () => {
  assert.equal(await forecastEnd(cacheOf({[wind[0].id]: {data_end_time: sec('2026-11-10T00:00:00Z')}}), MODELS), null);
  assert.equal(await forecastEnd(cacheOf({[wave[0].id]: {data_end_time: sec('2026-11-10T00:00:00Z')}}), MODELS), null);
  assert.equal(await forecastEnd(cacheOf({}), MODELS), null);
  for (const bad of [{}, {data_end_time: null}, {data_end_time: 'soon'}, {data_end_time: 0}, 'not json']) {
    const b = ends('2026-11-10T00:00:00Z', '2026-11-09T18:00:00Z');
    b[wave[0].id] = bad;
    assert.equal(await forecastEnd(cacheOf(b), MODELS), null, JSON.stringify(bad));
  }
});

test('the line: through, ended (exactly at the end too), not recorded', () => {
  const meta = {forecast_end: '2026-11-09T18:00:00.000Z'};
  assert.equal(forecastEndLine(meta, new Date('2026-11-05T12:00:00Z'), 'America/Los_Angeles'), 'Forecast saved through Mon 10 am');
  assert.equal(forecastEndLine(meta, new Date('2026-11-09T17:59:59Z'), 'America/Los_Angeles'), 'Forecast saved through Mon 10 am');
  const ended = 'The saved forecast has ended; save again with a connection';
  assert.equal(forecastEndLine(meta, new Date('2026-11-09T18:00:00Z'), 'America/Los_Angeles'), ended);
  assert.equal(forecastEndLine(meta, new Date('2026-11-10T00:00:00Z')), ended);
  for (const m of [{}, {forecast_end: 'garbage'}, {forecast_end: 5}]) assert.equal(forecastEndLine(m, new Date('2026-11-05T12:00:00Z')), 'Forecast end not recorded');
});

test('the DST-change day formats the local hour: 2026-11-01 is PDT before 09:00Z and PST after', () => {
  const now = new Date('2026-10-30T00:00:00Z');
  assert.equal(forecastEndLine({forecast_end: '2026-11-01T08:00:00Z'}, now, 'America/Los_Angeles'), 'Forecast saved through Sun 1 am');
  assert.equal(forecastEndLine({forecast_end: '2026-11-01T10:00:00Z'}, now, 'America/Los_Angeles'), 'Forecast saved through Sun 2 am');
});

test('an old pack without the field is listed as not recorded and is not rewritten', async () => {
  const old = {schema_version: 1, region_id: 'r', region_name: 'R', saved_at: '2026-10-01T00:00:00.000Z', bytes: 1, missing: [], tiles: {saved: 0, planned: 0}};
  const cache = {puts: 0, async put() { this.puts++; }, async match(k) { return k === PACK_META ? new Response(JSON.stringify(old)) : undefined; }};
  const saved = {caches: globalThis.caches, self: globalThis.self};
  Object.assign(globalThis, {self: globalThis, caches: {keys: async () => ['sc-pack-r-1'], open: async () => cache}});
  try {
    const [pack] = await listPacks();
    assert.equal(forecastEndLine(pack.meta, new Date('2026-11-05T00:00:00Z')), 'Forecast end not recorded');
    assert.equal('forecast_end' in pack.meta, false);
    assert.equal(cache.puts, 0, 'listing never writes');
  } finally { if (saved.self === undefined) Reflect.deleteProperty(globalThis, 'self'); else globalThis.self = saved.self; if (saved.caches === undefined) Reflect.deleteProperty(globalThis, 'caches'); else globalThis.caches = saved.caches; }
});

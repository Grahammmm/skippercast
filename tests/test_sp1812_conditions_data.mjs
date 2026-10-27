// SP-18-v1 / SP1812: synthetic producer-shaped feed, full real module imports.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
// Also protects ordinary repository test discovery, without a launcher preload.
await import('./fixtures/sp1812_conditions_data/offline.mjs');
const c = await import('../server/advisor/answers/conditions.ts');
const {COMFORT_WORD, verdictFor} = await import('../server/advisor/answers/comfort.ts');
const {rateComfort} = await import('../web/score.ts');
const healthy = () => JSON.parse(readFileSync(new URL('./fixtures/sp1812_conditions_data/healthy.json', import.meta.url)));
const region = {id: 'synthetic-coast', timezone: 'America/Los_Angeles', forecast_points: [{id: 'central'}], marine_zones: {coastal: 'PZZ645'}};
const DATE = '2026-09-28';
const run = (feed, point = 'central', date = DATE, window) => c.windowConditions(feed, region, point, date, window);
const failed = () => { const f = healthy(); for (const m of Object.values(f.forecast.models)) m.error = 'synthetic model failure'; return f; };
const summaries = ['wind_kt', 'wind_from', 'gusts_kt', 'seas_ft', 'sea_period_s', 'swell_ft', 'swell_period_s', 'swell_from', 'models_agree'];
function empty(day, reason) {
  assert.equal(day.available, false);
  assert.match(day.reason, reason);
  assert.equal(day.comfort, COMFORT_WORD.unknown);
  for (const key of summaries) assert.equal(day[key], null, key);
  assert.equal(day.date, DATE);
  assert.equal(day.window, '06:00-14:00');
}
function noMeasurements() {
  const f = healthy();
  for (const m of Object.values(f.forecast.models)) for (const d of m.data) d.hourly = {time: d.hourly.time};
  return f;
}
function put(f, model, key, unit, values) {
  const m = f.forecast.models[model];
  m.data[0] ??= {hourly_units: {time: 'unixtime'}, hourly: {time: [...f.forecast.models.gfs_global.data[0].hourly.time]}};
  m.data[0].hourly_units[key] = unit;
  m.data[0].hourly[key] = values;
}

test('A1 primary regression: model errors with cached timestamps have no usable forecast', () => {
  const f = failed(), times = f.forecast.models.gfs_global.data[0].hourly.time;
  assert.equal(globalThis.SP1812_OFFLINE, true);
  assert.deepEqual(times.map(t => new Date(t * 1000).toISOString()), ['2026-09-28T13:00:00.000Z', '2026-09-28T14:00:00.000Z']);
  // Independent prerequisites: the payload contains healthy numeric samples,
  // readHour suppresses only because of the recognized model error markers.
  assert.deepEqual(healthy().forecast.models.gfs_global.data[0].hourly.wind_speed_10m, [5, 5]);
  for (const t of times) for (const [key, value] of Object.entries(c.readHour(f, 0, t))) if (key !== 'time') assert.equal(value, null, key);
  assert.equal(run({...f, region_id: 'wrong-region'}).reason, 'regional forecast unavailable');
  assert.equal(run(f).available, false, 'SP1812_A1_NO_USABLE_FORECAST');
  empty(run(f), /no usable forecast/i);
});

test('A2 null, invalid units and missing arrays cannot make timestamps usable', async t => {
  for (const kind of ['null', 'invalid units', 'invalid time unit', 'missing arrays', 'empty arrays', 'nonfinite', 'outside window']) {
    await t.test(kind, () => {
      const f = healthy();
      for (const m of Object.values(f.forecast.models)) for (const d of m.data) {
        for (const key of Object.keys(d.hourly).filter(k => k !== 'time')) {
          if (kind === 'null') d.hourly[key] = [null, null];
          if (kind === 'invalid units') d.hourly_units[key] = 'invalid';
          if (kind === 'missing arrays') delete d.hourly[key];
          if (kind === 'empty arrays') d.hourly[key] = [];
          if (kind === 'nonfinite') d.hourly[key] = [NaN, Infinity];
          if (kind === 'outside window') d.hourly[key] = [null, null, 5];
        }
        if (kind === 'invalid time unit') d.hourly_units.time = 'iso8601';
        if (kind === 'outside window') d.hourly.time.push(Date.parse('2026-09-28T22:00:00Z') / 1000);
      }
      empty(run(f), /no usable forecast/i);
    });
  }
});

test('A3 healthy control: same window without errors keeps wind 5 kt and seas 2 ft', () => {
  const f = healthy(), day = run(f);
  assert.equal(day.available, true);
  assert.equal(day.reason, undefined);
  assert.deepEqual(day.wind_kt, [5, 5]);
  assert.deepEqual(day.seas_ft, [2, 2]);
  assert.equal(day.gusts_kt, null);
  assert.equal(day.sea_period_s, null);
  const rating = rateComfort(c.readHour(f, 0, f.forecast.models.gfs_global.data[0].hourly.time[0]));
  assert.ok(rating, 'real limited scoring remains enabled');
  assert.equal(day.comfort, COMFORT_WORD[verdictFor({conditions: rating.score})]);
});

test('A4 a single wind sample preserves partial availability and missing sea', () => {
  const f = noMeasurements(); put(f, 'gfs_global', 'wind_speed_10m', 'kn', [null, 5]);
  const day = run(f);
  assert.equal(day.available, true);
  assert.deepEqual(day.wind_kt, [5, 5]);
  assert.equal(day.seas_ft, null);
  assert.equal(day.comfort, COMFORT_WORD.unknown);
  assert.equal(day.models_agree, null);
});

test('A5 secondary-model-only samples preserve availability without inventing primary wind', async t => {
  for (const [model, key, unit, value] of [['ecmwf_ifs025', 'wind_speed_10m', 'kn', 5], ['ecmwf_ifs025', 'wind_gusts_10m', 'kn', 8], ['ecmwf_wam', 'wave_height', 'ft', 2]]) {
    await t.test(key, () => {
      const f = noMeasurements(); f.forecast.models.gfs_global.error = 'synthetic stale primary'; put(f, model, key, unit, [value, null]);
      const day = run(f);
      assert.equal(day.available, true);
      assert.equal(day.wind_kt, null);
      assert.deepEqual(day.seas_ft, model === 'ecmwf_wam' ? [2, 2] : null);
      assert.equal(day.comfort, COMFORT_WORD.unknown);
      f.forecast.models[model].error = 'synthetic secondary failure';
      empty(run(f), /no usable forecast/i);
    });
  }
});

test('A6 no timestamps, wrong region, missing point and date/window selection are unchanged', () => {
  const f = healthy(); f.forecast.models.gfs_global.data[0].hourly.time = [];
  empty(run(f), /does not cover this window yet/);
  empty(run({...healthy(), region_id: 'wrong-region'}), /^regional forecast unavailable$/);
  empty(run(healthy(), 'missing'), /^regional forecast unavailable$/);
  assert.equal(run(healthy(), 'central', '2026-09-29').reason, 'the forecast does not cover this window yet');
  assert.equal(run(healthy(), 'central', DATE, {start: 8, end: 9}).reason, 'the forecast does not cover this window yet');
});

test('A7 valid dates, window epochs and advisory event inclusion survive availability changes', () => {
  const now = Date.parse('2026-09-27T19:00:00Z');
  for (const text of ['tomorrow', 'mañana', DATE]) assert.deepEqual(c.parseTripDate(text, now).dates, [DATE]);
  const epochs = c.windowEpochs(DATE, region.timezone);
  assert.deepEqual(epochs, [Date.parse('2026-09-28T13:00:00Z'), Date.parse('2026-09-28T21:59:59.999Z')]);
  const daily = {sources: {'alerts-PZZ645': {data: {alerts: [
    {event: 'Small Craft Advisory', onset: '2026-09-28T14:00:00Z', ends: '2026-09-28T20:00:00Z'},
    {event: 'Gale Warning', onset: '2026-09-29T14:00:00Z'},
    {event: 'Rip Current Statement', onset: '2026-09-28T14:00:00Z'}
  ]}}}};
  for (const f of [healthy(), failed()]) {
    run(f);
    assert.deepEqual(c.advisoriesFrom(daily, c.regionZones(region), ...epochs).map(a => [a.event, a.zone]), [['Small Craft Advisory', 'PZZ645']]);
  }
});

test('all fifteen readHour measurement fields count, including zero, but time alone does not', async t => {
  const rows = [
    ['gfs_global', 'wind_speed_10m', 'kn'], ['gfs_global', 'wind_gusts_10m', 'kn'], ['gfs_global', 'wind_direction_10m', '°'],
    ['ncep_gfswave016', 'wave_height', 'ft'], ['ncep_gfswave016', 'wave_period', 's'],
    ['ncep_gfswave016', 'wind_wave_height', 'ft'], ['ncep_gfswave016', 'wind_wave_period', 's'],
    ['ncep_gfswave016', 'swell_wave_height', 'ft'], ['ncep_gfswave016', 'swell_wave_period', 's'], ['ncep_gfswave016', 'swell_wave_direction', '°'],
    ['ncep_gfswave016', 'secondary_swell_wave_height', 'ft'], ['ncep_gfswave016', 'secondary_swell_wave_direction', '°'],
    ['ecmwf_ifs025', 'wind_speed_10m', 'kn'], ['ecmwf_ifs025', 'wind_gusts_10m', 'kn'], ['ecmwf_wam', 'wave_height', 'ft']
  ];
  for (const [model, key, unit] of rows) await t.test(`${model}.${key}`, () => {
    const f = noMeasurements(); put(f, model, key, unit, [key === 'wave_period' ? 8 : 0, null]);
    assert.equal(run(f).available, true, key);
    f.forecast.models[model].data[0].hourly_units[key] = 'invalid';
    empty(run(f), /no usable forecast/i);
  });
  const invalidPeriod = noMeasurements(); put(invalidPeriod, 'ncep_gfswave016', 'wave_period', 's', [0, -1]);
  put(invalidPeriod, 'ncep_gfswave016', 'wave_height', 'ft', [2, 2]);
  empty(run(invalidPeriod), /no usable forecast/i);
});

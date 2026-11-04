// SC2007-06: the advisor reads an hour after a model's meta.data_end_time as unknown, as the web
// forecast-grid sample() does (web/map/forecast-grid.ts: `epoch > meta.data_end_time` is null, the
// end itself is still read), so the advisor never says "comfortable" for an hour the app shows as
// unknown. Offline: the committed intelligence fixture, morro-bay 'central', 2026-09-28 17-19 local.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {readHour, rateHour, windowConditions} = await import('../server/advisor/answers/conditions.ts');
const {rateComfort} = await import('../web/score.ts');

const region = REGIONS['morro-bay'], POINT = region.forecast_points.findIndex(p => p.id === 'central');
const WINDOW = {start: 17, end: 19};
const feed = () => structuredClone(read('./fixtures/feeds/intelligence.json'));
const [T0, T1, T2] = feed().forecast.models.gfs_global.data[POINT].hourly.time;
const WIND = ['gfs_global', 'ecmwf_ifs025'], WAVE = ['ncep_gfswave016', 'ecmwf_wam'];
const endAt = (f, ids, end) => { for (const id of ids) f.forecast.models[id].meta = {...f.forecast.models[id].meta, data_end_time: end}; return f; };
const WIND_FIELDS = ['wind', 'gust', 'wind_from', 'other_wind', 'other_gust'];
const WAVE_FIELDS = ['sea', 'sea_period', 'chop', 'chop_period', 'swell', 'swell_period', 'swell_from', 'secondary', 'secondary_from', 'other_sea'];
const nulls = (h, fields) => fields.every(k => h[k] === null);
const some = (h, fields) => fields.every(k => Number.isFinite(h[k]));

test('the hour exactly at data_end_time is still read, the web rule (equal to the end is read)', () => {
  const f = endAt(feed(), [...WIND, ...WAVE], T1);
  assert.deepEqual(readHour(f, POINT, T1), readHour(feed(), POINT, T1));
  assert.ok(some(readHour(f, POINT, T1), ['wind', 'gust', 'sea', 'swell', 'other_wind', 'other_sea']));
});

test('one step after the end every field of that model reads null', () => {
  const f = endAt(feed(), [...WIND, ...WAVE], T1), h = readHour(f, POINT, T2);
  assert.ok(nulls(h, [...WIND_FIELDS, ...WAVE_FIELDS]), JSON.stringify(h));
  assert.equal(h.time, T2);
  assert.equal(rateHour(h), null);
  // and each model is cut on its own end: only ECMWF wind ended, the rest still read at T2.
  const one = readHour(endAt(feed(), ['ecmwf_ifs025'], T1), POINT, T2);
  assert.ok(nulls(one, ['other_wind', 'other_gust']));
  assert.ok(some(one, ['wind', 'gust', 'sea', 'swell', 'other_sea']));
});

test('wave model ended, wind model not: seas null, wind kept, never the full-rubric score', () => {
  const h = readHour(endAt(feed(), WAVE, T1), POINT, T2);
  assert.ok(nulls(h, ['sea', 'chop', 'swell', 'other_sea', 'sea_period']));
  assert.ok(some(h, ['wind', 'gust', 'other_wind']));
  assert.equal(rateHour(h), null, 'no seas at all: no score');
  // Only the GFS-Wave ended: ECMWF WAM seas remain, so the hour is rated, but by the limited rubric (capped).
  const lim = readHour(endAt(feed(), ['ncep_gfswave016'], T1), POINT, T2);
  assert.ok(nulls(lim, ['sea', 'chop', 'swell']));
  assert.ok(Number.isFinite(lim.wind) && Number.isFinite(lim.other_sea));
  const rating = rateComfort(lim);
  assert.equal(rating.limited, true);
  assert.equal(rateHour(lim), rating.score);
  assert.equal(rateHour(readHour(feed(), POINT, T2)) !== null, true);
  assert.equal(rateComfort(readHour(feed(), POINT, T2)).limited, false, 'the unchanged fixture hour is the full rubric');
});

test('every model ended before the window: the day is unavailable with no usable measurements', () => {
  const day = windowConditions(endAt(feed(), [...WIND, ...WAVE], T0 - 1), region, 'central', '2026-09-28', WINDOW);
  assert.equal(day.available, false);
  assert.match(day.reason, /^no usable forecast measurements/);
  assert.equal(day.comfort, 'unknown');
});

test('a missing meta, a null, string or NaN end cuts nothing (today output)', () => {
  const base = feed();
  for (const id of Object.keys(base.forecast.models)) delete base.forecast.models[id].meta;
  const expected = [T0, T1, T2].map(t => readHour(base, POINT, t)), day = windowConditions(base, region, 'central', '2026-09-28', WINDOW);
  assert.equal(day.available, true);
  for (const bad of [null, '1790640000', NaN, undefined, Infinity]) {
    const f = endAt(feed(), [...WIND, ...WAVE], bad);
    assert.deepEqual([T0, T1, T2].map(t => readHour(f, POINT, t)), expected, `end ${String(bad)}`);
    assert.deepEqual(windowConditions(f, region, 'central', '2026-09-28', WINDOW), day, `end ${String(bad)}`);
  }
  const noMeta = feed();
  for (const id of Object.keys(noMeta.forecast.models)) noMeta.forecast.models[id].meta = null;
  assert.deepEqual([T0, T1, T2].map(t => readHour(noMeta, POINT, t)), expected);
});

test('a window straddling the end is computed from the pre-end hours only', () => {
  const cut = endAt(feed(), [...WIND, ...WAVE], T1);
  // The post-end hour is made violent; if it counted, wind, seas and comfort would change.
  for (const id of Object.keys(cut.forecast.models)) {
    const hourly = cut.forecast.models[id].data[POINT].hourly;
    for (const [k, v] of Object.entries(hourly)) if (Array.isArray(v) && k !== 'time') v[2] = k.includes('direction') ? 90 : 60;
  }
  const trimmed = feed();   // the same feed without the post-end hour at all
  for (const id of Object.keys(trimmed.forecast.models)) {
    const hourly = trimmed.forecast.models[id].data[POINT].hourly;
    for (const [k, v] of Object.entries(hourly)) if (Array.isArray(v)) hourly[k] = v.slice(0, 2);
  }
  const day = windowConditions(cut, region, 'central', '2026-09-28', WINDOW);
  assert.equal(day.available, true);
  assert.deepEqual(day, windowConditions(trimmed, region, 'central', '2026-09-28', WINDOW));
  assert.ok(day.wind_kt[1] < 60 && day.gusts_kt < 60);
  // Control: with no end the violent hour is read, so the cut is what made the difference.
  const open = structuredClone(cut);
  for (const id of Object.keys(open.forecast.models)) delete open.forecast.models[id].meta;
  assert.equal(windowConditions(open, region, 'central', '2026-09-28', WINDOW).gusts_kt, 60);
});

test('a model with error set is still null, whatever its end', () => {
  for (const end of [T0 - 1, T2, 9e9]) {
    const f = endAt(feed(), WAVE, end);
    f.forecast.models.ncep_gfswave016.error = 'upstream failed';
    const h = readHour(f, POINT, T1);
    assert.ok(nulls(h, ['sea', 'chop', 'swell', 'secondary']), `end ${end}`);
    assert.ok(Number.isFinite(h.other_sea) === (end >= T1));
  }
});

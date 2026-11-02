// BF-hourly-table: web/hourly-table.ts. The forecast below is synthetic
// (values invented, the /api/forecast series shape as ConditionsForecast);
// the zone is America/Los_Angeles, so 2026-03-08 springs forward and
// 2026-11-01 falls back.
import test from 'node:test';
import assert from 'node:assert/strict';

const {hourlyTable, hourlyCells, NO_FORECAST} = await import('../web/hourly-table.ts');
const {feedReader} = await import('../web/brief/verdict.ts');
const {rateComfort} = await import('../web/score.ts');

const HOUR = 3600, TZ = 'America/Los_Angeles';
const WIND = {wind_speed_10m: [8, 'kn'], wind_gusts_10m: [12, 'kn'], wind_direction_10m: [300, '°'], visibility: [16093, 'm']};
const WAVE = {wave_height: [4.2, 'ft'], wave_period: [11, 's'], wind_wave_height: [1.5, 'ft'], wind_wave_period: [5, 's'],
  swell_wave_height: [3.1, 'ft'], swell_wave_period: [14, 's'], swell_wave_direction: [290, '°']};

/** Hourly series over three days from `t0` (epoch s); `edit(variable, i)` may replace a value. */
function series(t0, values, edit = () => undefined) {
  const time = Array.from({length: 72}, (_, i) => t0 + i * HOUR);
  return {utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map((_, i) => edit(k, i) ?? v)]))}};
}
/** A forecast whose series start at local midnight before `day`; `ecmwfAge` hours old ECMWF runs (null drops them). */
function forecast(t0, {ecmwfAge = 6, otherWind = 10, edit} = {}) {
  const run = (id, values, age = 6) => ({id, issued: t0 - age * HOUR, end: t0 + 72 * HOUR, data: series(t0, values, edit)});
  const models = {gfs_global: run('gfs_global', WIND), ncep_gfswave016: run('ncep_gfswave016', WAVE)};
  if (ecmwfAge !== null) Object.assign(models, {ecmwf_ifs025: run('ecmwf_ifs025', {...WIND, wind_speed_10m: [otherWind, 'kn']}, ecmwfAge), ecmwf_wam: run('ecmwf_wam', WAVE, ecmwfAge)});
  return {region: 'morro-bay', retrieved: t0 * 1000, point: {id: 'central', lat: 35.36, lon: -120.94}, models};
}
// Local midnight a day before each test day (UTC 08:00 in PST, 07:00 in PDT).
const NORMAL = Date.parse('2026-06-14T07:00:00Z') / 1000, SPRING = Date.parse('2026-03-07T08:00:00Z') / 1000, FALL = Date.parse('2026-10-31T07:00:00Z') / 1000;
const nowAt = t0 => new Date((t0 + 2 * HOUR) * 1000);

test('edge 1: one row per local hour of the day (24; 23 on spring-forward; 25 on fall-back), in order', () => {
  const day = (t0, d) => hourlyTable(forecast(t0), null, d, TZ, nowAt(t0)).rows;
  assert.equal(day(NORMAL, '2026-06-15').length, 24);
  assert.equal(day(SPRING, '2026-03-08').length, 23);
  const fall = day(FALL, '2026-11-01');
  assert.equal(fall.length, 25);
  assert.ok(fall.every((r, i) => i === 0 || r.ms - fall[i - 1].ms === HOUR * 1000), 'rows ascend an hour apart');
  assert.equal(fall[0].at, '2026-11-01T07:00:00.000Z');
  // A day outside the feed has no rows and the note.
  assert.deepEqual(hourlyTable(forecast(NORMAL), null, '2026-07-01', TZ, nowAt(NORMAL)), {rows: [], note: NO_FORECAST});
});

test('edge 2: every score is rateComfort over the verdict feed reader; full hours are not limited', () => {
  const f = forecast(NORMAL), now = nowAt(NORMAL), {rows, note} = hourlyTable(f, null, '2026-06-15', TZ, now);
  const read = feedReader(f, now).read;
  assert.equal(note, null);
  for (const r of rows) {
    const rating = rateComfort(read(r.ms));
    assert.equal(r.score, rating.score);
    assert.equal(r.limited, rating.limited);
  }
  assert.equal(rows[0].limited, false);
  assert.deepEqual(hourlyCells(rows[0]), ['8 kt', '12 kt', '4.2 ft', '3.1 ft · 14 s · 290°', '1.5 ft · 5 s', '—', '10.0 mi', rows[0].score.toFixed(1)]);
});

test('edge 3: a stale or missing ECMWF run makes scores limited (marked *), never higher than with both models', () => {
  // Same wind in both models and a slight chop, so dropping ECMWF removes evidence, not a rougher reading or a charged partition.
  const calm = k => k === 'wind_wave_height' ? 0.3 : undefined;
  const now = nowAt(NORMAL), both = hourlyTable(forecast(NORMAL, {otherWind: 8, edit: calm}), null, '2026-06-15', TZ, now).rows;
  for (const ecmwfAge of [40, null]) {
    const f = forecast(NORMAL, {ecmwfAge, otherWind: 8, edit: calm}), {rows} = hourlyTable(f, null, '2026-06-15', TZ, now), read = feedReader(f, now).read;
    assert.equal(rows.length, 24);
    rows.forEach((r, i) => {
      assert.equal(r.limited, true);
      assert.equal(r.score, rateComfort(read(r.ms)).score);
      assert.ok(r.score <= both[i].score, `hour ${i}: ${r.score} > ${both[i].score}`);
      assert.match(hourlyCells(r).at(-1), /^\d+\.\d\*$/);
    });
  }
  // No seas at all from either model: rateComfort is null, the score reads —, not limited.
  const f = forecast(NORMAL, {ecmwfAge: null, edit: k => k === 'wave_height' ? 'x' : undefined});
  const r = hourlyTable(f, null, '2026-06-15', TZ, now).rows[0];
  assert.equal(r.score, null);
  assert.equal(r.limited, false);
  assert.equal(hourlyCells(r).at(-1), '—');
});

test('edge 4: a wave period of 0 blanks the seas; a gust below the wind blanks the gust', () => {
  // Hour 30 is 2026-06-15T13:00Z, 6 am local on the test day.
  const f = forecast(NORMAL, {edit: (k, i) => i === 30 && k === 'wave_period' ? 0 : i === 31 && k === 'wind_gusts_10m' ? 6 : undefined});
  const rows = hourlyTable(f, null, '2026-06-15', TZ, nowAt(NORMAL)).rows;
  assert.equal(rows[6].seas, null);
  assert.equal(hourlyCells(rows[6])[2], '—');
  assert.equal(rows[7].gust, null);
  assert.equal(hourlyCells(rows[7])[1], '—');
  assert.equal(rows[8].seas, 4.2);
  assert.equal(rows[8].gust, 12);
});

test('edge 5: tide comes from the coast series at the row hour; with no coast report every tide cell is —', () => {
  const f = forecast(NORMAL), now = nowAt(NORMAL);
  assert.ok(hourlyTable(f, null, '2026-06-15', TZ, now).rows.every(r => r.tide === null && hourlyCells(r)[5] === '—'));
  const tide = {label: 'Tide', unit: 'ft', color: '', points: [{at: '2026-06-15T09:00:00Z', value: 3.27}, {at: '2026-06-15T10:00:00Z', value: NaN}]};
  const rows = hourlyTable(f, tide, '2026-06-15', TZ, now).rows;
  assert.equal(rows[2].tide, 3.27);
  assert.equal(hourlyCells(rows[2])[5], '3.3 ft');
  assert.equal(rows[3].tide, null, 'a NaN tide reading is blank');
  assert.equal(rows[10].tide, null, 'no reading near the hour is blank');
});

test('edge 6: no forecast gives no rows and the note', () => {
  assert.deepEqual(hourlyTable(null, null, '2026-06-15', TZ, new Date()), {rows: [], note: 'No forecast for this day.'});
});

test('edge 8: visibility 16093 m reads 10.0 mi; NaN, strings and negative values in the feed read —', () => {
  const f = forecast(NORMAL, {edit: (k, i) => i === 30 ? {visibility: NaN, wind_speed_10m: 'calm', swell_wave_height: -1}[k] : undefined});
  const rows = hourlyTable(f, null, '2026-06-15', TZ, nowAt(NORMAL)).rows;
  assert.equal(rows[0].visibilityMi, 10);
  assert.equal(hourlyCells(rows[0])[6], '10.0 mi');
  const cells = hourlyCells(rows[6]);
  assert.equal(cells[0], '—', 'wind string');
  assert.equal(cells[1], '—', 'gust with no wind to check it against');
  assert.equal(cells[3], '—', 'negative swell');
  assert.equal(cells[6], '—', 'NaN visibility');
  // A GFS run over 36 h old is dropped by the feed reader, and its visibility with it.
  const stale = forecast(NORMAL);
  stale.models.gfs_global = {...stale.models.gfs_global, issued: NORMAL - 40 * HOUR};
  assert.ok(hourlyTable(stale, null, '2026-06-15', TZ, nowAt(NORMAL)).rows.every(r => r.visibilityMi === null && r.wind === null));
});

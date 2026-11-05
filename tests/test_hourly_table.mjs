// BF-hourly-table: web/hourly-table.ts. The forecast below is synthetic
// (values invented, the /api/forecast series shape as ConditionsForecast);
// the zone is America/Los_Angeles, so 2026-03-08 springs forward and
// 2026-11-01 falls back.
import test from 'node:test';
import assert from 'node:assert/strict';

const {hourlyTable, hourlyCells, NO_FORECAST, overLimits, limitLabel, LIMITS_NOTE} = await import('../web/hourly-table.ts');
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
  assert.deepEqual(hourlyCells(rows[0]), ['8 kt from WNW', '12 kt', '4.2 ft', '3.1 ft · 14 s · 290°', '—', '1.5 ft · 5 s', '—', '10.0 mi', rows[0].score.toFixed(1)]);
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
  assert.ok(hourlyTable(f, null, '2026-06-15', TZ, now).rows.every(r => r.tide === null && hourlyCells(r)[6] === '—'));
  const tide = {label: 'Tide', unit: 'ft', color: '', points: [{at: '2026-06-15T09:00:00Z', value: 3.27}, {at: '2026-06-15T10:00:00Z', value: NaN}]};
  const rows = hourlyTable(f, tide, '2026-06-15', TZ, now).rows;
  assert.equal(rows[2].tide, 3.27);
  assert.equal(hourlyCells(rows[2])[6], '3.3 ft');
  assert.equal(rows[3].tide, null, 'a NaN tide reading is blank');
  assert.equal(rows[10].tide, null, 'no reading near the hour is blank');
});

test('hourly_tide_cell_uses_nearest_reading', () => {
  const f = forecast(NORMAL), now = nowAt(NORMAL);
  // Row 2 is 09:00Z. Off-hour points only: 08:36 = 1, 08:54 = 4, 09:06 = 5, so 08:54 and 09:06 tie and the earlier wins.
  const pts = [{at: '2026-06-15T08:36:00Z', value: 1}, {at: '2026-06-15T08:54:00Z', value: 4}, {at: '2026-06-15T09:06:00Z', value: 5}];
  const noTide = hourlyTable(f, null, '2026-06-15', TZ, now).rows;
  for (const points of [pts, [...pts].reverse(), [pts[2], pts[0], pts[1]]]) {
    const rows = hourlyTable(f, {label: 'Tide', unit: 'ft', color: '', points}, '2026-06-15', TZ, now).rows;
    assert.equal(rows[2].tide, 4);
    assert.equal(hourlyCells(rows[2])[6], '4.0 ft');
    assert.equal(rows[8].tide, null, 'no reading within 30 minutes of the hour is blank');
    rows.forEach((r, i) => assert.deepEqual({...r, tide: null}, {...noTide[i], tide: null}, 'only the tide cell changes; scores and other cells stay'));
  }
});

test('edge 6: no forecast gives no rows and the note', () => {
  assert.deepEqual(hourlyTable(null, null, '2026-06-15', TZ, new Date()), {rows: [], note: 'No forecast for this day.'});
});

test('edge 8: visibility 16093 m reads 10.0 mi; NaN, strings and negative values in the feed read —', () => {
  const f = forecast(NORMAL, {edit: (k, i) => i === 30 ? {visibility: NaN, wind_speed_10m: 'calm', swell_wave_height: -1}[k] : undefined});
  const rows = hourlyTable(f, null, '2026-06-15', TZ, nowAt(NORMAL)).rows;
  assert.equal(rows[0].visibilityMi, 10);
  assert.equal(hourlyCells(rows[0])[7], '10.0 mi');
  const cells = hourlyCells(rows[6]);
  assert.equal(cells[0], '—', 'wind string');
  assert.equal(cells[1], '—', 'gust with no wind to check it against');
  assert.equal(cells[3], '—', 'negative swell');
  assert.equal(cells[7], '—', 'NaN visibility');
  // A GFS run over 36 h old is dropped by the feed reader, and its visibility with it.
  const stale = forecast(NORMAL);
  stale.models.gfs_global = {...stale.models.gfs_global, issued: NORMAL - 40 * HOUR};
  assert.ok(hourlyTable(stale, null, '2026-06-15', TZ, nowAt(NORMAL)).rows.every(r => r.visibilityMi === null && r.wind === null));
});

test('RF1600-3: a GFS run issued over an hour in the future is refused for visibility as for wind; exact boundaries hold', () => {
  const now = nowAt(NORMAL), nowS = now.getTime() / 1000, maxS = 36 * HOUR;
  const at = issued => {
    const f = forecast(NORMAL);
    f.models.gfs_global = {...f.models.gfs_global, issued};
    return hourlyTable(f, null, '2026-06-15', TZ, now).rows;
  };
  for (const ahead of [3601, 24 * HOUR]) {
    const rows = at(nowS + ahead);
    assert.ok(rows.length > 0, 'ECMWF clock keeps the rows');
    assert.ok(rows.every(r => r.wind === null && r.visibilityMi === null && hourlyCells(r)[7] === '—'), `+${ahead}s`);
  }
  for (const issued of [nowS, nowS + HOUR, nowS - maxS]) assert.equal(at(issued)[0].visibilityMi, 10, `admitted ${issued - nowS}`);
  assert.equal(at(nowS - maxS - 1)[0].visibilityMi, null, 'max age + 1 s');
  assert.equal(at(nowS + HOUR + 0.001)[0].visibilityMi, null, '+1 h + 1 ms');
  for (const bad of [null, 'x', NaN, Infinity]) assert.equal(at(bad)[0].visibilityMi, null);
});

// MYB-2b: rows are rated for the boat passed (the view passes the saved boat's
// activeBoatFactors(), as the brief verdict does); omitted, the reference boat.
const {REFERENCE_BOAT} = await import('../web/score.ts');
const {boatFactors} = await import('../dist/boat-handling.js');
const {createHash} = await import('node:crypto');
const PINNED = 'df00e2a835648398384ca1d54715546b47cd2dd8e6311659d9dcbd2119cbd30f';
const SMALL = Object.freeze({sea: 0.6, wind: 0.6, chopPeriod: 8});
const dump = ({rows, note}) => JSON.stringify({note, rows, cells: rows.map(hourlyCells)});

test('MYB-2b: a non-reference boat rates every row with rateComfort(hour, boat), and differently from the reference', () => {
  const f = forecast(NORMAL), now = nowAt(NORMAL), read = feedReader(f, now).read;
  const ref = hourlyTable(f, null, '2026-06-15', TZ, now).rows, small = hourlyTable(f, null, '2026-06-15', TZ, now, SMALL).rows;
  assert.equal(small.length, 24);
  small.forEach((r, i) => {
    const rating = rateComfort(read(r.ms), SMALL);
    assert.equal(r.score, rating.score);
    assert.equal(r.limited, rating.limited);
    assert.equal(hourlyCells(r).at(-1), rating.score.toFixed(1));
    assert.deepEqual({...r, score: null}, {...ref[i], score: null}, 'only the score depends on the boat');
  });
  assert.ok(small.some((r, i) => r.score !== ref[i].score), 'the small boat rates differently');
  assert.ok(small.every((r, i) => r.score <= ref[i].score), 'a less tolerant boat never rates higher');
});

test('MYB-2b: with no boat saved the table is byte-identical to the reference-boat table it always produced', () => {
  for (const [t0, day] of [[NORMAL, '2026-06-15'], [SPRING, '2026-03-08'], [FALL, '2026-11-01']]) {
    const f = forecast(t0, {ecmwfAge: t0 === FALL ? 40 : 6}), now = nowAt(t0), before = dump(hourlyTable(f, null, day, TZ, now));
    assert.equal(dump(hourlyTable(f, null, day, TZ, now, REFERENCE_BOAT)), before, day);
    assert.equal(dump(hourlyTable(f, null, day, TZ, now, boatFactors(null))), before, `${day}: nothing saved`);
  }
  // Pinned from main ea41c719 (before the boat parameter existed): the default output has not moved by a byte.
  const out = dump(hourlyTable(forecast(NORMAL), null, '2026-06-15', TZ, nowAt(NORMAL)));
  assert.equal(createHash('sha256').update(out).digest('hex'), PINNED);
});

// SC2037-01: wind direction in the Wind cell, a second-swell cell; nothing filled.
const cellsAt = (edit, wave = WAVE) => {
  const f = forecast(NORMAL, {edit});
  f.models.ncep_gfswave016 = {...f.models.ncep_gfswave016, data: series(NORMAL, wave, edit)};
  return hourlyCells(hourlyTable(f, null, '2026-06-15', TZ, nowAt(NORMAL)).rows[0]);
};
const SECOND = {...WAVE, secondary_swell_wave_height: [1.2, 'ft'], secondary_swell_wave_direction: [200, '°']};

test('SC2037-01: a row with wind direction and a second swell names both compass words', () => {
  const cells = cellsAt(undefined, SECOND);
  assert.equal(cells[0], '8 kt from WNW');
  assert.equal(cells[4], '1.2 ft · from SSW');
  assert.equal(cells.length, 9);
});

test('SC2037-01: missing wind direction leaves the plain wind; no wind is a dash even with a direction', () => {
  for (const bad of [NaN, Infinity, 'x']) assert.equal(cellsAt(k => k === 'wind_direction_10m' ? bad : undefined)[0], '8 kt');
  assert.equal(cellsAt(k => k === 'wind_speed_10m' ? NaN : undefined)[0], '—');
});

test('SC2037-01: no second swell (absent series, zero height, missing or non-finite direction) is a dash', () => {
  assert.equal(cellsAt()[4], '—', 'absent series');
  for (const [h, d] of [[0, 200], [-1, 200], [1.2, NaN], [1.2, null], [NaN, 200]]) {
    const wave = {...WAVE, secondary_swell_wave_height: [h, 'ft'], secondary_swell_wave_direction: [d, '°']};
    assert.equal(cellsAt(undefined, wave)[4], '—', `${h} ft from ${d}`);
  }
  assert.equal(cellsAt(undefined, {...WAVE, secondary_swell_wave_height: [1.2, 'ft']})[4], '—', 'direction series absent');
});

test('SC2037-01: compass words use the shared 16-point helper (0 and 359.9 are N; 11.25 rounds to NNE)', () => {
  const wind = d => cellsAt(k => k === 'wind_direction_10m' ? d : undefined)[0];
  assert.equal(wind(0), '8 kt from N');
  assert.equal(wind(359.9), '8 kt from N');
  assert.equal(wind(11.25), '8 kt from NNE');
});

// SC2037-02: marks over the person's own limits (strictly greater, as daily.ts buildDaily overLimit).
const mine = {wind: 12, gust: 18, seas: 5};
const rowWith = (wind, gust, seas) => ({wind, gust, seas});

test('SC2037-02: own limits mark only values strictly over, for wind, gust and seas', () => {
  for (const [k, lim] of [['wind', 12], ['gust', 18], ['seas', 5]]) {
    const at = v => overLimits({wind: null, gust: null, seas: null, [k]: v}, mine)[k];
    assert.equal(at(lim - 0.1), false, `${k} under`);
    assert.equal(at(lim), false, `${k} equal is not marked`);
    assert.equal(at(lim + 0.1), true, `${k} over`);
  }
  assert.deepEqual(overLimits(rowWith(13, 10, 6), mine), {wind: true, gust: false, seas: true});
});

test('SC2037-02: default limits (null) mark nothing; a missing value is never marked', () => {
  assert.deepEqual(overLimits(rowWith(40, 50, 20), null), {wind: false, gust: false, seas: false});
  assert.deepEqual(overLimits(rowWith(null, null, null), mine), {wind: false, gust: false, seas: false});
  assert.deepEqual(overLimits(rowWith(NaN, Infinity, undefined), mine), {wind: false, gust: false, seas: false});
  assert.equal(hourlyCells({...hourlyTable(forecast(NORMAL), null, '2026-06-15', TZ, nowAt(NORMAL)).rows[0], wind: null, windFrom: null})[0], '—');
});

test('SC2037-02: the accessible labels name the limit; the note says marks compare NOAA values and the window can differ', () => {
  assert.equal(limitLabel('wind', mine), 'over your 12 kt wind limit');
  assert.equal(limitLabel('gust', mine), 'over your 18 kt gust limit');
  assert.equal(limitLabel('seas', mine), 'over your 5 ft seas limit');
  assert.match(LIMITS_NOTE, /NOAA values/);
  assert.match(LIMITS_NOTE, /window can differ/);
});

test('SC2037-02: marking leaves the cell text and score unchanged', () => {
  const r = hourlyTable(forecast(NORMAL), null, '2026-06-15', TZ, nowAt(NORMAL)).rows[0], before = JSON.stringify([hourlyCells(r), r.score]);
  overLimits(r, {wind: 1, gust: 1, seas: 1});
  assert.equal(JSON.stringify([hourlyCells(r), r.score]), before);
});

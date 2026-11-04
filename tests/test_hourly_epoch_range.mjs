// RF1350-1: web/hourly-table.ts skips listed hours the Date cannot represent
// before any local formatting, instead of throwing a RangeError. Synthetic
// forecast; production helper; global fetch blocked.
import test from 'node:test';
import assert from 'node:assert/strict';

const {hourlyTable, hourlyCells, NO_FORECAST} = await import('../web/hourly-table.ts');

globalThis.fetch = () => { throw new Error('no network in this test'); };

const HOUR = 3600, TZ = 'America/Los_Angeles', DAY = '2026-06-15';
const MAX_S = 8_640_000_000_000;           // Date's last representable second
const BAD = [MAX_S + HOUR, -MAX_S - HOUR]; // one hour beyond each end, still hour-aligned
const WIND = {wind_speed_10m: [8, 'kn'], wind_gusts_10m: [12, 'kn'], wind_direction_10m: [300, '°'], visibility: [16093, 'm']};
const WAVE = {wave_height: [4.2, 'ft'], wave_period: [11, 's'], wind_wave_height: [1.5, 'ft'], wind_wave_period: [5, 's'],
  swell_wave_height: [3.1, 'ft'], swell_wave_period: [14, 's'], swell_wave_direction: [290, '°']};
const T0 = Date.parse('2026-06-14T07:00:00Z') / 1000, NOW = new Date((T0 + 2 * HOUR) * 1000);

const deepFreeze = o => { if (o && typeof o === 'object' && !Object.isFrozen(o)) { Object.freeze(o); Object.values(o).forEach(deepFreeze); } return o; };

/** Three-day hourly series from T0; `extra` epochs (s) are spliced in at `where` with values extended in lockstep. */
function series(values, extra = [], where = 'end', t0 = T0) {
  const base = Array.from({length: 72}, (_, i) => t0 + i * HOUR);
  const time = where === 'start' ? [...extra, ...base] : where === 'middle' ? [...base.slice(0, 30), ...extra, ...base.slice(30)] : [...base, ...extra];
  return {utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))}};
}
function forecast(extra = [], where = 'end', t0 = T0) {
  const run = (id, values) => ({id, issued: t0 - 6 * HOUR, end: t0 + 72 * HOUR, data: series(values, extra, where, t0)});
  return deepFreeze({region: 'morro-bay', retrieved: t0 * 1000, point: {id: 'central', lat: 35.36, lon: -120.94},
    models: {gfs_global: run('gfs_global', WIND), ncep_gfswave016: run('ncep_gfswave016', WAVE), ecmwf_ifs025: run('ecmwf_ifs025', WIND), ecmwf_wam: run('ecmwf_wam', WAVE)}});
}
const table = f => hourlyTable(f, null, DAY, TZ, NOW);

test('precondition: the bad epochs pass the old whole-hour check but are not Dates', () => {
  for (const s of BAD) {
    assert.ok((s * 1000) % 3_600_000 === 0);
    assert.ok(Number.isNaN(new Date(s * 1000).getTime()));
  }
});

test('hourly_epoch_both_signs_and_all_invalid: out-of-range hours alone give the no-forecast note', () => {
  const control = table(forecast());
  assert.equal(control.rows.length, 24);
  for (const bad of [[BAD[0]], [BAD[1]], BAD]) {
    assert.deepEqual(table(forecast(bad)), table(forecast()));
  }
  // Only bad hours listed: the same clock with no usable hour that day.
  const only = forecast();
  const bare = {...only, models: {gfs_global: {...only.models.gfs_global, data: {...only.models.gfs_global.data, hourly: {...only.models.gfs_global.data.hourly, time: BAD}}}}};
  assert.deepEqual(table(bare), {rows: [], note: NO_FORECAST});
});

test('hourly_epoch_mixed_keeps_real_rows: bad epochs at start, middle and end leave rows, cells and scores as the control', () => {
  const control = table(forecast());
  for (const where of ['start', 'middle', 'end']) {
    const got = table(forecast(BAD, where));
    assert.equal(got.note, null);
    assert.equal(got.rows.length, 24);
    assert.ok(got.rows.every(r => typeof r.score === 'number' && r.wind === 8), 'real readings and scores kept');
    assert.ok(got.rows.every((r, i) => r.ms === control.rows[i].ms && r.score === control.rows[i].score && r.limited === control.rows[i].limited
      && hourlyCells(r).join('|') === hourlyCells(control.rows[i]).join('|')), `${where}: rows equal control`);
  }
});

test('hourly_epoch_bounds_and_nonhours: Date endpoints do not throw; beyond them, NaN, Infinity, strings and half hours make no rows', () => {
  const edge = [MAX_S, -MAX_S, MAX_S - HOUR];
  for (const s of edge) assert.ok(Number.isFinite(new Date(s * 1000).getTime()));
  assert.deepEqual(table(forecast(edge)), table(forecast()));
  const junk = [NaN, Infinity, -Infinity, 'x', null, 1e308, T0 + 1800 + 5 * HOUR];
  assert.deepEqual(table(forecast(junk)), table(forecast()));
});

test('DST days keep 23 and 25 hours with an out-of-range epoch present', () => {
  const day = (iso, d) => { const t0 = Date.parse(iso) / 1000; return hourlyTable(forecast(BAD, 'end', t0), null, d, TZ, new Date((t0 + 2 * HOUR) * 1000)).rows.length; };
  assert.equal(day('2026-03-07T08:00:00Z', '2026-03-08'), 23);
  assert.equal(day('2026-10-31T07:00:00Z', '2026-11-01'), 25);
});

test('a missing forecast still gives the no-forecast note', () => {
  assert.deepEqual(hourlyTable(null, null, DAY, TZ, NOW), {rows: [], note: NO_FORECAST});
});

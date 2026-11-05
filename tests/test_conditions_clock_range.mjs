// RF1920-16: retrieval and run clocks a Date cannot hold are unavailable (web/conditions.ts).
// Synthetic /api/forecast feed; no network, no clock mocking.
import test from 'node:test';
import assert from 'node:assert/strict';

const {briefForecast, parseConditionsForecast, sourceClocks} = await import('../web/conditions.ts');

const T0 = Date.parse('2026-11-01T08:00:00Z') / 1000;
const MAX_MS = 8_640_000_000_000_000;
const WIND = {wind_speed_10m: [8, 'kn'], wind_gusts_10m: [12, 'kn']};
const WAVE = {wave_height: [4, 'ft'], wave_period: [11, 's']};
function series(values) {
  const hourly = {time: [T0, T0 + 3600]};
  for (const [k, [v]] of Object.entries(values)) hourly[k] = [v, v];
  return {utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))}, hourly};
}
const points = [['central', 35.36, -120.94]];
function feed({retrieved = T0 * 1000 + 3600_000, windIssued = T0 - 3600, waveIssued = T0 - 7200} = {}) {
  const model = (values, issued) => ({meta: {last_run_initialisation_time: issued, data_end_time: T0 + 86400}, data: [series(values)]});
  return {region_id: 'morro-bay', retrieved, requested_points: points, models: {gfs_global: model(WIND, windIssued), ncep_gfswave016: model(WAVE, waveIssued)}};
}
const parse = json => parseConditionsForecast(json, 'morro-bay', null);
const clocks = f => sourceClocks(f, 'gfs', null, null);

test('conditions_retrieval_requires_representable_milliseconds', () => {
  for (const bad of [1e308, -1e308, MAX_MS + 1, -MAX_MS - 1, Infinity, NaN, null, '1', true]) assert.equal(parse(feed({retrieved: bad})), null, String(bad));
  for (const ok of [T0 * 1000, 0, -86_400_000, MAX_MS, -MAX_MS]) assert.equal(parse(feed({retrieved: ok}))?.retrieved, ok, String(ok));
});

test('conditions_run_clock_requires_representable_seconds', () => {
  const bad = MAX_MS / 1000 + 1;
  const wind = parse(feed({windIssued: bad}));
  assert.equal(wind.models.gfs_global.issued, null);
  assert.equal(wind.models.ncep_gfswave016.issued, T0 - 7200);
  assert.ok(wind.models.gfs_global.data, 'model data kept');
  assert.equal(briefForecast(wind), null);
  assert.deepEqual(clocks(wind).map(c => c.at), [null, new Date((T0 - 7200) * 1000).toISOString(), new Date(T0 * 1000 + 3600_000).toISOString()]);
  const wave = parse(feed({waveIssued: -1e308}));
  assert.equal(wave.models.ncep_gfswave016.issued, null);
  assert.equal(briefForecast(wave), null);
  assert.equal(clocks(wave)[0].at, new Date((T0 - 3600) * 1000).toISOString());
  assert.equal(clocks(wave)[1].at, null);
  const both = parse(feed({windIssued: 1e308, waveIssued: Infinity}));
  assert.equal(briefForecast(both), null);
  assert.deepEqual(clocks(both).map(c => c.at).slice(0, 2), [null, null]);
});

test('conditions_clock_serializers_defend_direct_inputs', () => {
  const good = parse(feed());
  const run = (id, issued) => ({...good.models[id], issued});
  const direct = (retrieved, windIssued, waveIssued) => ({...good, retrieved, models: {gfs_global: run('gfs_global', windIssued), ncep_gfswave016: run('ncep_gfswave016', waveIssued)}});
  for (const bad of [1e308, NaN, MAX_MS / 1000 + 1]) {
    const f = direct(good.retrieved, bad, T0 - 7200);
    assert.doesNotThrow(() => clocks(f));
    assert.equal(briefForecast(f), null);
    assert.equal(clocks(f)[0].at, null);
    assert.equal(clocks(f)[1].at, new Date((T0 - 7200) * 1000).toISOString());
  }
  const f = direct(1e308, T0 - 3600, T0 - 7200);
  assert.equal(briefForecast(f), null);
  const rows = clocks(f);
  assert.deepEqual(rows.map(c => [c.label, c.kind]), [['NOAA GFS', 'run'], ['NOAA GFS-Wave', 'run'], ['Regional forecast feed', 'retrieved']]);
  assert.equal(rows[2].at, null);
  assert.equal(rows[0].at, new Date((T0 - 3600) * 1000).toISOString());
  assert.equal(rows[1].at, new Date((T0 - 7200) * 1000).toISOString());
});

test('conditions_clocks_keep_older_run_and_dst_iso_instants', () => {
  const iso = s => new Date(s * 1000).toISOString();
  const cases = [
    ['2026-03-08T09:59:59Z', '2026-03-08T10:00:00Z'], // spring forward 02:00 PST
    ['2026-11-01T08:30:00Z', '2026-11-01T09:30:00Z'], // repeated 01:30 PDT then PST
    ['2026-11-04T08:00:00Z', '2026-11-04T07:00:00Z'], // Pacific midnight
    ['1970-01-01T00:00:00Z', '1969-12-31T23:00:00Z'], // zero and negative
  ];
  for (const [wind, wave] of cases) {
    const ws = Date.parse(wind) / 1000, vs = Date.parse(wave) / 1000;
    const f = parse(feed({windIssued: ws, waveIssued: vs}));
    assert.deepEqual(clocks(f).slice(0, 2).map(c => c.at), [iso(ws), iso(vs)]);
    assert.equal(briefForecast(f).issuedAt, iso(Math.min(ws, vs)));
  }
});

test('conditions_clock_validation_preserves_input_and_samples', () => {
  const json = feed();
  const before = JSON.stringify(json);
  const f = parse(json);
  assert.equal(JSON.stringify(json), before);
  assert.equal(f.feed, json);
  assert.equal(f.models.gfs_global.end, T0 + 86400);
  const brief = briefForecast(f);
  assert.equal(brief.hours.length, 2);
  assert.equal(brief.hours[0].windKnots, 8);
  assert.equal(brief.hours[0].gustKnots, 12);
  assert.equal(brief.hours[0].waveFt, 4);
  assert.equal(brief.fetchedAt, new Date(f.retrieved).toISOString());
  assert.equal(brief.label, 'NOAA GFS model · central');
});

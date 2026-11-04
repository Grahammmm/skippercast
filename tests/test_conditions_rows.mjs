// FE-32: Conditions rows (web/conditions.ts) through packages/coast chart() (design § 10).
// The forecast feed below is synthetic (values invented, /api/forecast shape);
// the coast report is the committed tests/fixtures/coast fixture, with one
// synthetic nearshore site added.
import test from 'node:test';
import assert from 'node:assert/strict';
import report from './fixtures/coast/skippercast-report.json' with {type: 'json'};

const {chart} = await import('../packages/coast/src/charts/series.ts');
const {briefForecast, coastRows, conditionsRows, conditionsSpan, forecastRows, parseConditionsForecast, readingsAt, sourceClocks, SPAN_HOURS} = await import('../web/conditions.ts');

const HOUR = 3_600_000;
const now = new Date(Date.parse(report.generatedAt) + 10 * 60_000);
const span = conditionsSpan(now);
const t0 = Date.parse(span.start) / 1000;

/** A synthetic Open-Meteo-style series: hourly from t0 for eight days, `hole` hours left out of `variable`. */
function series(values, {hole = [], holeVariable = null} = {}) {
  const time = Array.from({length: 8 * 24}, (_, i) => t0 + i * 3600);
  const units = Object.fromEntries(Object.entries(values).map(([k, [, unit]]) => [k, unit]));
  const hourly = Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map((_, i) => k === holeVariable && hole.includes(i) ? null : v)]));
  return {utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...units}, hourly: {time, ...hourly}};
}
const WIND = {wind_speed_10m: [8, 'kn'], wind_gusts_10m: [12, 'kn'], temperature_2m: [61, '°F'], cloud_cover: [40, '%']};
const WAVE = {wave_height: [4.2, 'ft'], wave_period: [11, 's']};
function feed({hole = [], holeVariable = 'wind_speed_10m'} = {}) {
  const meta = {last_run_initialisation_time: t0 - 6 * 3600, data_end_time: t0 + 8 * 24 * 3600};
  const points = [['north', 35.45, -121.02], ['central', 35.36, -120.94], ['offshore-1-0', 35.3, -121.25]];
  const model = values => ({meta, data: points.map((_, i) => series(values, i === 1 ? {hole, holeVariable} : {}))});
  return {region_id: 'morro-bay', retrieved: now.getTime() - 20 * 60_000, requested_points: points,
    models: {gfs_global: model(WIND), ncep_gfswave016: model(WAVE), ecmwf_ifs025: model({...WIND, wind_speed_10m: [10, 'kn']}), ecmwf_wam: model(WAVE)}};
}
const pathOf = (svg, label) => {
  const paths = [...svg.matchAll(/<path d="([^"]*)" style="stroke:([^"]+)"/g)];
  const labels = [...svg.matchAll(/class="axis-label" style="fill:[^"]+">([^<]+)</g)].map(m => m[1]);
  return paths[labels.indexOf(label)]?.[1] ?? '';
};

test('the forecast point is the inshore one nearest the region centre, and a feed for another region is refused', () => {
  assert.equal(parseConditionsForecast(feed(), 'morro-bay', [35.34, -120.965]).point.id, 'central');
  assert.equal(parseConditionsForecast(feed(), 'morro-bay', [35.5, -121.0]).point.id, 'north');
  assert.equal(parseConditionsForecast(feed(), 'monterey-point-sur', [35.34, -120.965]), null);
});

test('acceptance 1: a 2 h hole produces two path segments through chart()', () => {
  const f = parseConditionsForecast(feed({hole: [10, 11]}), 'morro-bay', [35.34, -120.965]);
  const rows = conditionsRows(forecastRows(f, 'gfs', span.start), []);
  const svg = chart(rows, span.start, span.end, span.start, 'America/Los_Angeles');
  const wind = pathOf(svg, 'Wind');
  assert.equal((wind.match(/M/g) ?? []).length, 2, 'the wind path breaks once at the hole');
  assert.equal((pathOf(svg, 'Air').match(/M/g) ?? []).length, 1, 'rows without a hole stay one segment');
  // A hole in the times themselves (two hours missing from the series) breaks the line the same way.
  const gapRow = {...rows[3], points: rows[3].points.filter((_, i) => i !== 20 && i !== 21)};
  assert.equal((pathOf(chart([gapRow], span.start, span.end, span.start, 'UTC'), 'Air').match(/M/g) ?? []).length, 2);
});

test('gusts below the sustained wind and seas without a positive period stay blank (v1 rules); nothing is filled', () => {
  const f = parseConditionsForecast(feed({hole: [3], holeVariable: 'wave_period'}), 'morro-bay', [35.34, -120.965]);
  const rows = forecastRows(f, 'gfs', span.start);
  assert.deepEqual(rows.map(r => r.label), ['Wind', 'Gusts', 'Offshore seas', 'Air', 'Cloud']);
  assert.equal(rows[2].points[3].value, null);
  assert.equal(rows[2].points[4].value, 4.2);
  const ecmwf = forecastRows(f, 'ecmwf', span.start);
  assert.equal(ecmwf[0].points[0].value, 10, 'the ECMWF family reads its own wind');
  assert.ok(forecastRows(null, 'gfs', span.start).every(r => r.points.every(p => p.value === null)), 'no feed: every row is empty, not guessed');
});

test('acceptance 2: the seven-day horizon stays when the coast report covers fewer hours', () => {
  const lastTide = Date.parse(report.tides.at(-1).at);
  assert.ok(lastTide < Date.parse(span.end) - 3 * 24 * HOUR, 'the fixture report ends days before the horizon');
  const f = parseConditionsForecast(feed(), 'morro-bay', null);
  const local = coastRows(report, 'estero-bay', now);
  const rows = conditionsRows(forecastRows(f, 'gfs', span.start), local.rows);
  assert.equal(Date.parse(span.end) - Date.parse(span.start), SPAN_HOURS * HOUR);
  assert.deepEqual(rows.map(r => r.label), ['Wind', 'Gusts', 'Offshore seas', 'Tide', 'Air', 'Cloud']);
  assert.equal(rows[0].points.length, SPAN_HOURS + 1, 'forecast rows span all 169 hours');
  assert.equal(rows[0].points.at(-1).at, span.end);
  const svg = chart(rows, span.start, span.end, span.start, 'America/Los_Angeles');
  assert.match(svg, /viewBox="0 0 840 \d+"/);
  // The axis keeps the seven-day end whatever the report covers.
  assert.equal(conditionsSpan(now).end, new Date(Date.parse(span.start) + 168 * HOUR).toISOString());
});

test('nearshore joins only from a fresh site for the bound area, with its own clock', () => {
  const site = {id: 'syn', name: 'Synthetic site', areaId: 'estero-bay', lat: 35.37, lon: -120.9, sourceId: 'x', issuedAt: report.generatedAt, fetchedAt: report.generatedAt,
    hours: [0, 1, 2].map(i => ({at: new Date(Date.parse(span.start) + i * HOUR).toISOString(), waveFt: 3 + i, periodS: 12, directionDeg: 290})), url: 'https://example.invalid/',
    kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 60, waterDepthM: 20, depthDatum: 'MSL', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: null};
  const bound = {...report, nearshore: [site]};
  const local = coastRows(bound, 'estero-bay', now);
  assert.deepEqual(local.rows.map(r => r.label), ['Nearshore', 'Tide']);
  assert.equal(coastRows(bound, 'cambria-san-simeon', now).rows[0]?.label, 'Tide', 'another area takes no nearshore row');
  assert.equal(coastRows(bound, 'estero-bay', new Date(now.getTime() + 4 * HOUR)).site, null, 'a fetch past 3 h is withdrawn');
  const f = parseConditionsForecast(feed(), 'morro-bay', null);
  const clocks = sourceClocks(f, 'gfs', bound, local.site);
  assert.deepEqual(clocks.map(c => [c.label, c.kind]), [['NOAA GFS', 'run'], ['NOAA GFS-Wave', 'run'], ['Regional forecast feed', 'retrieved'], ['Nearshore model · Synthetic site', 'fetched'], [report.sources.find(s => s.kind === 'prediction').label, 'fetched']]);
  assert.equal(clocks[0].at, new Date((t0 - 6 * 3600) * 1000).toISOString());
  const rows = conditionsRows(forecastRows(f, 'gfs', span.start), local.rows);
  assert.deepEqual(readingsAt(rows, span.start).map(r => [r.label, r.value]).slice(0, 4), [['Wind', 8], ['Gusts', 12], ['Offshore seas', 4.2], ['Nearshore', 3]]);
});

test('#542: briefForecast gives the brief the NOAA hours at the chosen point, clocked by the older run', () => {
  const f = parseConditionsForecast(feed({hole: [3], holeVariable: 'wave_period'}), 'morro-bay', [35.34, -120.965]);
  const brief = briefForecast(f);
  assert.equal(brief.label, 'NOAA GFS model · central');
  assert.equal(brief.issuedAt, new Date((t0 - 6 * 3600) * 1000).toISOString());
  assert.equal(brief.fetchedAt, new Date(f.retrieved).toISOString());
  assert.equal(brief.hours.length, 8 * 24, 'every hour the wind model lists');
  assert.deepEqual(brief.hours[0], {at: span.start, windKnots: 8, gustKnots: 12, windDirectionDeg: null, waveFt: 4.2, wavePeriodS: 11, swellFt: null, swellPeriodS: null, airTempF: 61, cloudCoverPct: 40});
  assert.equal(brief.hours[3].waveFt, null, 'seas without a positive period stay null, not filled');
  assert.equal(briefForecast(f, 'ecmwf').hours[0].windKnots, 10, 'the ECMWF family reads its own wind');
  // The clock is the older run: a fresh wind run never makes an old wave run read fresh.
  const raw = feed();
  raw.models.ncep_gfswave016 = {...raw.models.ncep_gfswave016, meta: {...raw.models.ncep_gfswave016.meta, last_run_initialisation_time: t0 - 30 * 3600}};
  assert.equal(briefForecast(parseConditionsForecast(raw, 'morro-bay', null)).issuedAt, new Date((t0 - 30 * 3600) * 1000).toISOString());
  // No feed, or a run without its clock: no forecast, so the tiles read unavailable.
  assert.equal(briefForecast(null), null);
  const unclocked = feed();
  unclocked.models.gfs_global = {...unclocked.models.gfs_global, meta: {}};
  assert.equal(briefForecast(parseConditionsForecast(unclocked, 'morro-bay', null)), null);
});

// RF0210-7: readingsAt with no exact sample reads the nearest eligible one. Synthetic points only.
const SEL = '2026-11-04T10:00:00Z', MIN = 60_000;
const at = ms => new Date(Date.parse(SEL) + ms).toISOString();
const rowOf = (...pts) => ({label: 'Tide', unit: 'ft', color: '', points: pts.map(([ms, value]) => ({at: at(ms * MIN), value}))});
const perms = list => list.length < 2 ? [list] : list.flatMap((x, i) => perms([...list.slice(0, i), ...list.slice(i + 1)]).map(p => [x, ...p]));
const valueOf = row => readingsAt([row], SEL)[0].value;

test('nearest_reading_is_order_independent', () => {
  const pts = [[-24, 1], [-6, 4], [6, 5]];
  const results = perms(pts).map(p => valueOf(rowOf(...p)));
  assert.equal(results.length, 6);
  // 09:36=1, 09:54=4, 10:06=5: 09:54 and 10:06 tie, the earlier wins; the farther 1 never wins in any order.
  assert.ok(results.every(v => v === 4), 'every permutation reads 4');
  // A unique nearest wins wherever it sits in the list.
  const unique = [[-25, 1], [-10, 7], [28, 3]];
  assert.ok(perms(unique).every(p => valueOf(rowOf(...p)) === 7));
});

test('nearest_reading_tie_uses_earlier_timestamp', () => {
  assert.equal(valueOf(rowOf([-10, 2], [10, 9])), 2);
  assert.equal(valueOf(rowOf([10, 9], [-10, 2])), 2);
  assert.equal(valueOf(rowOf([10, 9], [-10, 2], [20, 5])), 2);
  // A unique nearest future point still beats an earlier, farther one.
  assert.equal(valueOf(rowOf([-12, 2], [10, 9])), 9);
  assert.equal(valueOf(rowOf([10, 9], [-12, 2])), 9);
  // An equidistant earlier point that is not finite cannot win the tie.
  assert.equal(valueOf(rowOf([-10, null], [10, 9])), 9);
});

test('exact_missing_reading_is_not_backfilled', () => {
  assert.equal(valueOf(rowOf([0, 6], [-5, 1], [5, 2])), 6, 'a finite exact reading wins over closer-looking neighbours');
  for (const missing of [null, NaN, Infinity, -Infinity, undefined, 'x']) {
    assert.equal(valueOf(rowOf([-5, 1], [0, missing], [5, 2])), null, `exact ${String(missing)} stays null`);
    assert.equal(valueOf(rowOf([5, 2], [0, missing], [-5, 1])), null, `exact ${String(missing)} stays null in reverse order`);
  }
  // Duplicate exact timestamps keep the first.
  assert.equal(valueOf(rowOf([0, 3], [0, 8])), 3);
  assert.equal(valueOf(rowOf([0, null], [0, 8])), null);
});

test('reading_tolerance_is_strict_and_inputs_are_unchanged', () => {
  const ms29 = 29 * MIN + 59_999;
  const edge = {label: 'Tide', unit: 'ft', color: '', points: [{at: at(-ms29), value: 3}]};
  assert.equal(valueOf(edge), 3, '29m59.999s before is eligible');
  assert.equal(valueOf({...edge, points: [{at: at(ms29), value: 3}]}), 3, '29m59.999s after is eligible');
  assert.equal(valueOf(rowOf([-30, 3])), null, 'exactly 30 minutes before is excluded');
  assert.equal(valueOf(rowOf([30, 3])), null, 'exactly 30 minutes after is excluded');
  assert.equal(valueOf(rowOf([-30, 3], [29, 4])), 4, 'the excluded point never wins over an eligible one');
  assert.equal(valueOf(rowOf([-31, 3], [-45, 4])), null);
  // Unreadable timestamps and values, and an empty row, yield null.
  const bad = {label: 'Tide', unit: 'ft', color: '', points: [{at: 'not a time', value: 1}, {at: at(-5 * MIN), value: NaN}, {at: at(5 * MIN), value: null}, {at: at(6 * MIN), value: '2'}]};
  assert.equal(valueOf(bad), null);
  assert.equal(valueOf(rowOf()), null);
  // An invalid selected time reads null and keeps the labels and units.
  const out = readingsAt([rowOf([0, 3])], 'garbage');
  assert.equal(out.length, 1);
  assert.equal(out[0].value, null);
  assert.equal(out[0].label, 'Tide');
  assert.equal(out[0].unit, 'ft');
  // The input is read, never reordered or rewritten.
  const frozen = rowOf([10, 9], [-24, 1], [-10, 2]);
  frozen.points.forEach(Object.freeze);
  Object.freeze(frozen.points);
  Object.freeze(frozen);
  const before = JSON.stringify(frozen);
  assert.equal(valueOf(frozen), 2);
  assert.equal(JSON.stringify(frozen), before);
});

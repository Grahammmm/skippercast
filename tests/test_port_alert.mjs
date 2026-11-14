// SCFEAT-ALERT-1: wind and swell alerts for the saved home port without a saved trip or an account.
// web/port-alert.ts keeps two thresholds on this device and reads the existing regional forecast
// (briefForecast hours); it sends nothing. Planning information only, not for navigation.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {isDeepStrictEqual} from 'node:util';

const {PORT_ALERT_KEY, parseThresholds, loadThresholds, saveThresholds, clearThresholds, evaluatePortAlert, WINDOW_HOURS} = await import('../web/port-alert.ts');

const NOW = Date.parse('2026-11-07T18:20:00Z');
const hourAt = (h, over = {}) => ({at: new Date(Date.parse('2026-11-07T18:00:00Z') + h * 3600000).toISOString(), windKnots: 8, gustKnots: 12, windDirectionDeg: 300, waveFt: 3, wavePeriodS: 8, swellFt: 3, swellPeriodS: 12, airTempF: 60, cloudCoverPct: 10, ...over});
const forecast = (hours, over = {}) => ({label: 'NOAA GFS model · morro-bay', url: '/sources', issuedAt: '2026-11-07T12:00:00Z', fetchedAt: '2026-11-07T17:30:00Z', hours, ...over});
const store = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k)}; };
const LIMITS = {windKt: 15, swellFt: 6};
// A forecast with a reading for every hour of the 48 h window (the only kind that can read "clear"); `over(i)` adjusts hour i.
const full = (over = () => ({})) => Array.from({length: WINDOW_HOURS}, (_, i) => hourAt(i, over(i)));

test('thresholds parse only when both are finite and inside the allowed ranges', () => {
  assert.deepEqual(parseThresholds(JSON.stringify(LIMITS)), LIMITS);
  for (const bad of [null, '', 'x', '[]', '{}', JSON.stringify({windKt: 0, swellFt: 3}), JSON.stringify({windKt: 15, swellFt: 99}), JSON.stringify({windKt: '15', swellFt: 3}), JSON.stringify({windKt: 15})])
    assert.equal(parseThresholds(bad), null, String(bad));
});

test('save, load and clear use one device-only key and survive a blocked store', () => {
  const s = store();
  assert.equal(loadThresholds(s), null);
  assert.deepEqual(saveThresholds(LIMITS, s), LIMITS);
  assert.deepEqual(JSON.parse(s.getItem(PORT_ALERT_KEY)), LIMITS);
  assert.deepEqual(loadThresholds(s), LIMITS);
  clearThresholds(s);
  assert.equal(loadThresholds(s), null);
  assert.equal(saveThresholds({windKt: 0, swellFt: 3}, s), null, 'out of range saves nothing');
  assert.equal(s.getItem(PORT_ALERT_KEY), null);
  const blocked = {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); }};
  assert.equal(loadThresholds(blocked), null);
  assert.doesNotThrow(() => saveThresholds(LIMITS, blocked));
  assert.doesNotThrow(() => clearThresholds(blocked));
});

test('no forecast, or no hour with a reading in the window, is "no-data": never "clear"', () => {
  assert.equal(evaluatePortAlert(LIMITS, null, NOW).state, 'no-data');
  const blank = forecast([hourAt(0, {windKnots: null, swellFt: null})]);
  assert.equal(evaluatePortAlert(LIMITS, blank, NOW).state, 'no-data');
  assert.equal(evaluatePortAlert(LIMITS, forecast([hourAt(-30), hourAt(WINDOW_HOURS + 5)]), NOW).state, 'no-data', 'only hours inside the window count');
});

test('calm hours across the whole window are "clear" and carry the source and both clocks', () => {
  const r = evaluatePortAlert(LIMITS, forecast(full()), NOW);
  assert.equal(r.state, 'clear');
  assert.deepEqual(r.exceedances, []);
  assert.equal(r.source, 'NOAA GFS model · morro-bay');
  assert.equal(r.issuedAt, '2026-11-07T12:00:00Z');
  assert.equal(r.fetchedAt, '2026-11-07T17:30:00Z');
  assert.equal(r.hoursChecked, WINDOW_HOURS);
  assert.equal(r.notification, null);
});

test('a wind or swell reading at or above its threshold is an "alert" with the first hour and the peak', () => {
  const hours = [hourAt(0), hourAt(1, {windKnots: 15}), hourAt(2, {windKnots: 21, swellFt: 7.5}), hourAt(3, {swellFt: 6})];
  const r = evaluatePortAlert(LIMITS, forecast(hours), NOW);
  assert.equal(r.state, 'alert');
  assert.deepEqual(r.exceedances.map(e => [e.kind, e.at, e.value]), [['wind', hours[1].at, 15], ['swell', hours[2].at, 7.5]]);
  assert.deepEqual(r.peak, {windKt: 21, swellFt: 7.5});
  assert.equal(r.notification.tag, 'port-alert');
  assert.match(r.notification.title, /Wind|Swell/);
  assert.doesNotMatch(r.notification.body, /safe|unsafe|go\b|no-go/i, 'no navigation safety claim');
});

test('hours before the current hour or past the window are ignored', () => {
  const r = evaluatePortAlert(LIMITS, forecast([hourAt(-3, {windKnots: 40}), hourAt(WINDOW_HOURS + 2, {windKnots: 40}), ...full()]), NOW);
  assert.equal(r.state, 'clear');
  assert.equal(r.hoursChecked, WINDOW_HOURS);
});

test('a model run older than 36 h or a feed fetched more than 6 h ago is "stale": old data never reads clear or alerts', () => {
  const calm = [hourAt(0)];
  assert.equal(evaluatePortAlert(LIMITS, forecast(calm, {issuedAt: '2026-11-06T04:00:00Z'}), NOW).state, 'stale');
  assert.equal(evaluatePortAlert(LIMITS, forecast(calm, {fetchedAt: '2026-11-07T11:00:00Z'}), NOW).state, 'stale');
  const loud = [hourAt(0, {windKnots: 40})];
  assert.equal(evaluatePortAlert(LIMITS, forecast(loud, {fetchedAt: '2026-11-07T11:00:00Z'}), NOW).state, 'stale');
  assert.equal(evaluatePortAlert(LIMITS, forecast(calm, {fetchedAt: 'nonsense'}), NOW).state, 'stale', 'an unreadable clock is not fresh');
});

test('the panel is catalogue copy, mounted in Conditions, and says what it is not', () => {
  const panel = readFileSync(new URL('../web/app/PortAlert.tsx', import.meta.url), 'utf8');
  assert.match(panel, /portAlert\.notnav/);
  assert.match(readFileSync(new URL('../web/app/views/Conditions.tsx', import.meta.url), 'utf8'), /<PortAlert\b/);
  const catalogue = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url), 'utf8'));
  const ids = Object.keys(catalogue.strings ?? catalogue).filter(k => k.startsWith('portAlert.'));
  assert.ok(ids.length >= 10, 'catalogue ids exist');
  const table = catalogue.strings ?? catalogue;
  for (const id of ids) assert.ok(table[id].en && table[id].es, id);
  assert.match(table['portAlert.notnav'].en, /not for navigation/i);
});

test('readings for only one variable never read \"clear\": partial, while a known exceedance still alerts', () => {
  const noSwell = forecast([hourAt(0, {swellFt: null}), hourAt(1, {swellFt: null})]);
  const a = evaluatePortAlert(LIMITS, noSwell, NOW);
  assert.equal(a.state, 'partial');
  assert.equal(a.notification, null);
  const noWind = forecast([hourAt(0, {windKnots: null}), hourAt(1, {windKnots: null})]);
  assert.equal(evaluatePortAlert(LIMITS, noWind, NOW).state, 'partial');
  const windHit = evaluatePortAlert(LIMITS, forecast([hourAt(0, {swellFt: null, windKnots: 20})]), NOW);
  assert.equal(windHit.state, 'alert');
  const swellHit = evaluatePortAlert(LIMITS, forecast([hourAt(0, {windKnots: null, swellFt: 9})]), NOW);
  assert.equal(swellHit.state, 'alert');
});

test('intermittent missing readings inside the window never read "clear"; known exceedances still alert', () => {
  const hours48 = over => Array.from({length: WINDOW_HOURS}, (_, i) => hourAt(i, over(i)));
  // 48 calm wind hours, swell missing for the first 47 and calm only in the last hour.
  const gapSwell = forecast(hours48(i => (i < WINDOW_HOURS - 1 ? {swellFt: null} : {})));
  const a = evaluatePortAlert(LIMITS, gapSwell, NOW);
  assert.equal(a.state, 'partial');
  assert.equal(a.notification, null);
  assert.equal(a.hoursChecked, WINDOW_HOURS);
  // The same for wind, and for gaps spread over different hours of the two variables.
  assert.equal(evaluatePortAlert(LIMITS, forecast(hours48(i => (i === 5 ? {windKnots: null} : {}))), NOW).state, 'partial');
  assert.equal(evaluatePortAlert(LIMITS, forecast(hours48(i => (i === 3 ? {windKnots: null} : i === 9 ? {swellFt: null} : {}))), NOW).state, 'partial');
  // An hour with no reading at all in the window is a gap too.
  assert.equal(evaluatePortAlert(LIMITS, forecast(hours48(i => (i === 7 ? {windKnots: null, swellFt: null} : {}))), NOW).state, 'partial');
  // Gaps outside the window do not matter.
  const outside = forecast([hourAt(-2, {swellFt: null}), ...full(), hourAt(WINDOW_HOURS + 1, {windKnots: null})]);
  assert.equal(evaluatePortAlert(LIMITS, outside, NOW).state, 'clear');
  // Hours the forecast does not list at all are gaps too: a truncated forecast (only a calm first hour, or only the first 12 h) is partial, never "clear".
  const one = evaluatePortAlert(LIMITS, forecast([hourAt(0)]), NOW);
  assert.equal(one.state, 'partial');
  assert.equal(one.hoursChecked, 1);
  assert.equal(one.notification, null);
  assert.equal(evaluatePortAlert(LIMITS, forecast(full().slice(0, 12)), NOW).state, 'partial');
  assert.equal(evaluatePortAlert(LIMITS, forecast(full().slice(-1)), NOW).state, 'partial', 'only the last hour of the window');
  // A removed interior timestamp (the hour is absent, not null) is partial, as is a window that ends one hour early.
  assert.equal(evaluatePortAlert(LIMITS, forecast(full().filter((_, i) => i !== 20)), NOW).state, 'partial');
  assert.equal(evaluatePortAlert(LIMITS, forecast(full().slice(0, WINDOW_HOURS - 1)), NOW).state, 'partial');
  // An hour listed twice does not stand in for an absent one.
  assert.equal(evaluatePortAlert(LIMITS, forecast([...full().filter((_, i) => i !== 20), hourAt(19)]), NOW).state, 'partial');
  // Truncated or gappy forecasts still alert on a known exceedance.
  assert.equal(evaluatePortAlert(LIMITS, forecast([hourAt(0), hourAt(1, {windKnots: 20})]), NOW).state, 'alert');
  assert.equal(evaluatePortAlert(LIMITS, forecast(full().filter((_, i) => i !== 20).map((h, i) => (i === 30 ? {...h, swellFt: 9} : h))), NOW).state, 'alert');
  // A known exceedance alerts despite gaps elsewhere.
  const hit = evaluatePortAlert(LIMITS, forecast(hours48(i => (i === 10 ? {windKnots: 20} : i < 40 ? {swellFt: null} : {}))), NOW);
  assert.equal(hit.state, 'alert');
  assert.equal(hit.exceedances[0].kind, 'wind');
  // Complete data stays clear.
  assert.equal(evaluatePortAlert(LIMITS, forecast(hours48(() => ({}))), NOW).state, 'clear');
});

test('negative wind or swell is a missing coverage slot', () => {
  for (const key of ['windKnots', 'swellFt']) for (const i of [0, 20, WINDOW_HOURS - 1]) {
    const r = evaluatePortAlert(LIMITS, forecast(full(n => n === i ? {[key]: -1} : {})), NOW);
    assert.equal(r.state, 'partial', `${key} at ${i}`);
    assert.equal(r.notification, null);
    assert.ok(r.peak.windKt >= 0 && r.peak.swellFt >= 0, 'peaks are never negative');
  }
});

test('all negative readings are no-data', () => {
  const r = evaluatePortAlert(LIMITS, forecast(full(() => ({windKnots: -1, swellFt: -2}))), NOW);
  assert.equal(r.state, 'no-data');
  assert.equal(r.hoursChecked, 0);
  assert.deepEqual(r.exceedances, []);
  assert.deepEqual(r.peak, {windKt: null, swellFt: null});
  assert.equal(r.notification, null);
  const one = evaluatePortAlert(LIMITS, forecast(full(() => ({windKnots: -3}))), NOW);
  assert.equal(one.state, 'partial', 'one wholly negative variable leaves the other valid');
  assert.equal(one.peak.windKt, null);
});

test('zero remains calm and a valid hit survives negative data', () => {
  assert.equal(evaluatePortAlert(LIMITS, forecast(full(i => ({windKnots: i % 2 ? 0 : -0, swellFt: 0}))), NOW).state, 'clear');
  const hit = evaluatePortAlert(LIMITS, forecast(full(i => i === 5 ? {windKnots: 15, swellFt: -1} : i === 9 ? {windKnots: -4} : {})), NOW);
  assert.equal(hit.state, 'alert');
  assert.equal(hit.exceedances[0].kind, 'wind');
  for (const bad of [NaN, Infinity, '9', undefined])
    assert.equal(evaluatePortAlert(LIMITS, forecast(full(i => i === 3 ? {windKnots: bad} : {})), NOW).state, 'partial', String(bad));
});

// RF1651-10: an unreadable (nonfinite) evaluation clock is stale, never a window of arbitrary dates.
const BAD_CLOCKS = [['NaN', NaN], ['invalid Date', new Date('invalid').getTime()], ['+Infinity', Infinity], ['-Infinity', -Infinity]];
const EMPTY_PEAK = {windKt: null, swellFt: null};
const loudFar = () => forecast([hourAt(-30, {windKnots: 40, swellFt: 9}), hourAt(24 * 13, {windKnots: 40, swellFt: 9})]);

test('a nonfinite clock cannot alert on rows outside any window: stale, nothing checked, metadata kept', () => {
  for (const [name, bad] of BAD_CLOCKS) {
    const f = loudFar();
    const r = evaluatePortAlert(LIMITS, f, bad);
    assert.equal(r.state, 'stale', name);
    assert.equal(r.hoursChecked, 0, name);
    assert.deepEqual(r.exceedances, [], name);
    assert.deepEqual(r.peak, EMPTY_PEAK, name);
    assert.equal(r.notification, null, name);
    assert.equal(r.source, f.label);
    assert.equal(r.issuedAt, f.issuedAt);
    assert.equal(r.fetchedAt, f.fetchedAt);
  }
});

test('a nonfinite clock over calm complete data or an empty forecast is stale, not clear, partial or no-data', () => {
  for (const [name, bad] of BAD_CLOCKS) for (const f of [forecast(full()), forecast([]), forecast(full(() => ({windKnots: 40})))]) {
    const r = evaluatePortAlert(LIMITS, f, bad);
    assert.equal(r.state, 'stale', name);
    assert.equal(r.hoursChecked, 0, name);
    assert.deepEqual(r.exceedances, [], name);
    assert.deepEqual(r.peak, EMPTY_PEAK, name);
    assert.equal(r.notification, null, name);
  }
});

test('an absent forecast keeps no-data precedence over any clock', () => {
  for (const now of [NaN, Infinity, -Infinity, NOW]) {
    const r = evaluatePortAlert(LIMITS, null, now);
    assert.equal(r.state, 'no-data');
    assert.equal(r.hoursChecked, 0);
    assert.deepEqual(r.exceedances, []);
    assert.deepEqual(r.peak, EMPTY_PEAK);
    assert.equal(r.source, null);
    assert.equal(r.issuedAt, null);
    assert.equal(r.fetchedAt, null);
    assert.equal(r.notification, null);
  }
});

test('finite-clock results are unchanged by the nonfinite refusal', () => {
  const calm = evaluatePortAlert(LIMITS, forecast(full()), NOW);
  assert.equal(calm.state, 'clear');
  assert.equal(calm.hoursChecked, WINDOW_HOURS);
  assert.deepEqual(calm.peak, {windKt: 8, swellFt: 3});
  const edge = evaluatePortAlert(LIMITS, forecast(full(i => (i === 4 ? {windKnots: 15} : {}))), NOW);
  assert.equal(edge.state, 'alert');
  assert.deepEqual(edge.exceedances.map(e => [e.kind, e.value]), [['wind', 15]]);
  assert.equal(evaluatePortAlert(LIMITS, forecast(full().slice(0, 12)), NOW).state, 'partial');
  assert.equal(evaluatePortAlert(LIMITS, forecast([]), NOW).state, 'no-data');
  assert.equal(evaluatePortAlert(LIMITS, forecast(full(), {fetchedAt: 'nonsense'}), NOW).state, 'stale');
  assert.equal(evaluatePortAlert(LIMITS, forecast(full(), {issuedAt: '2026-11-06T04:00:00Z'}), NOW).state, 'stale');
  const end = evaluatePortAlert(LIMITS, forecast([hourAt(WINDOW_HOURS, {windKnots: 40})]), NOW);
  assert.equal(end.state, 'no-data', 'the window end is exclusive');
});

test('refusing a nonfinite clock does not mutate the limits, forecast or hours', () => {
  const freeze = o => Object.freeze(o);
  const limits = freeze({...LIMITS});
  const hours = full(i => (i === 2 ? {windKnots: 40} : {})).map(freeze);
  const f = freeze({...forecast(Object.freeze(hours))});
  const before = JSON.stringify([limits, f]);
  for (const [name, bad] of BAD_CLOCKS) {
    const r = evaluatePortAlert(limits, f, bad);
    assert.equal(r.state, 'stale', name);
    assert.equal(JSON.stringify([limits, f]), before, name);
  }
});

// RF1900-8: each variable's exceedance is its earliest qualifying instant, whatever the order the rows arrive in.
const permute = (rows, order) => order.map(i => rows[i]);
const ORDERS = [[0, 1, 2, 3, 4, 5], [5, 4, 3, 2, 1, 0], [3, 0, 5, 1, 4, 2], [2, 5, 0, 4, 1, 3]];
const earliestRows = () => [hourAt(0), hourAt(1, {windKnots: 15, swellFt: 6}), hourAt(2), hourAt(3, {windKnots: 30, swellFt: 10}), hourAt(4, {windKnots: 22}), hourAt(5)];

test('earliest_hits_survive_reversal_and_shuffle: first qualifying value, not the later peak', () => {
  const rows = earliestRows();
  const base = evaluatePortAlert(LIMITS, forecast(rows), NOW);
  assert.deepEqual(base.exceedances.map(e => [e.kind, e.at, e.value]), [['wind', rows[1].at, 15], ['swell', rows[1].at, 6]], 'wind before swell on the same row');
  assert.deepEqual(base.peak, {windKt: 30, swellFt: 10});
  for (const order of ORDERS) assert.ok(isDeepStrictEqual(evaluatePortAlert(LIMITS, forecast(permute(rows, order)), NOW), base), `order ${order}`);
});

test('independent_variable_onsets_keep_chronological_order', () => {
  const rows = [hourAt(0), hourAt(1, {swellFt: 6}), hourAt(2, {windKnots: 16}), hourAt(3, {windKnots: 30, swellFt: 10}), hourAt(4), hourAt(5)];
  const base = evaluatePortAlert(LIMITS, forecast(rows), NOW);
  assert.deepEqual(base.exceedances.map(e => [e.kind, e.at, e.value]), [['swell', rows[1].at, 6], ['wind', rows[2].at, 16]]);
  assert.match(base.notification.title, /^Swell and Wind/);
  for (const order of ORDERS) assert.ok(isDeepStrictEqual(evaluatePortAlert(LIMITS, forecast(permute(rows, order)), NOW), base), `order ${order}`);
});

test('chronology_uses_epoch_not_timestamp_text: offset times keep their original bytes; equal instants keep source order', () => {
  const early = hourAt(0, {at: '2026-11-07T23:00:00+05:00', windKnots: 15}); // 18:00Z, lexically later than 19:00Z
  const later = hourAt(1, {at: '2026-11-07T19:00:00Z', windKnots: 20});
  assert.ok(early.at > later.at, 'text order disagrees with time order');
  const r = evaluatePortAlert(LIMITS, forecast([later, early]), NOW);
  assert.deepEqual(r.exceedances, [{kind: 'wind', at: '2026-11-07T23:00:00+05:00', value: 15}]);
  const twin = hourAt(0, {at: '2026-11-07T20:00:00+02:00', windKnots: 18}); // same instant as early
  assert.equal(evaluatePortAlert(LIMITS, forecast([twin, early, later]), NOW).exceedances[0].at, twin.at);
  assert.equal(evaluatePortAlert(LIMITS, forecast([early, twin, later]), NOW).exceedances[0].at, early.at);
});

test('invalid_and_outside_rows_cannot_displace_first_hit', () => {
  const rows = [hourAt(5, {windKnots: 25}), hourAt(-1, {windKnots: 40, swellFt: 9}), hourAt(WINDOW_HOURS, {windKnots: 40, swellFt: 9}), hourAt(0, {at: 'nonsense', windKnots: 40}),
    hourAt(2, {windKnots: null, swellFt: -4}), hourAt(3, {windKnots: -9, swellFt: null}), hourAt(4, {windKnots: 15}), hourAt(0, {at: hourAt(0).at})];
  const r = evaluatePortAlert(LIMITS, forecast(rows), NOW);
  assert.deepEqual(r.exceedances.map(e => [e.kind, e.at, e.value]), [['wind', hourAt(4).at, 15]]);
  assert.deepEqual(r.peak, {windKt: 25, swellFt: 3});
  const start = evaluatePortAlert(LIMITS, forecast([hourAt(1, {windKnots: 30}), hourAt(0, {at: '2026-11-07T18:00:00Z', windKnots: 15})]), NOW);
  assert.deepEqual(start.exceedances.map(e => e.value), [15], 'the start of the window is inclusive');
});

test('frozen_input_and_sorted_output_compatibility: input is never reordered or mutated', () => {
  const rows = earliestRows().reverse().map(h => Object.freeze(h));
  const hours = Object.freeze([...rows]);
  const f = Object.freeze(forecast(hours));
  const before = JSON.stringify(f);
  const r = evaluatePortAlert(LIMITS, f, NOW);
  assert.equal(JSON.stringify(f), before);
  assert.equal(r.exceedances[0].at, hourAt(1).at);
  assert.equal(r.hoursChecked, 6);
  assert.ok(isDeepStrictEqual(r, evaluatePortAlert(LIMITS, forecast(earliestRows()), NOW)), 'same result as ascending input');
  assert.equal(r.notification.body, 'Forecast wind 15 kt (your limit 15 kt); swell 6 ft (your limit 6 ft) within 48 h. Model forecast for planning, not for navigation.');
});

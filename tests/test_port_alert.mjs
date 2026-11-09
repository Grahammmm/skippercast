// SCFEAT-ALERT-1: wind and swell alerts for the saved home port without a saved trip or an account.
// web/port-alert.ts keeps two thresholds on this device and reads the existing regional forecast
// (briefForecast hours); it sends nothing. Planning information only, not for navigation.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

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

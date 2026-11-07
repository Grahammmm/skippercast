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

test('calm hours inside the window are "clear" and carry the source and both clocks', () => {
  const r = evaluatePortAlert(LIMITS, forecast([hourAt(0), hourAt(1), hourAt(2)]), NOW);
  assert.equal(r.state, 'clear');
  assert.deepEqual(r.exceedances, []);
  assert.equal(r.source, 'NOAA GFS model · morro-bay');
  assert.equal(r.issuedAt, '2026-11-07T12:00:00Z');
  assert.equal(r.fetchedAt, '2026-11-07T17:30:00Z');
  assert.equal(r.hoursChecked, 3);
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
  const r = evaluatePortAlert(LIMITS, forecast([hourAt(-3, {windKnots: 40}), hourAt(WINDOW_HOURS + 2, {windKnots: 40}), hourAt(1)]), NOW);
  assert.equal(r.state, 'clear');
  assert.equal(r.hoursChecked, 1);
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

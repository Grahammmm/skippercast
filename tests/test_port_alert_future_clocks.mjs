// RF1751-8: a forecast whose issue or retrieval clock is more than five minutes ahead of evaluation is stale.
import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';

const {evaluatePortAlert, WINDOW_HOURS} = await import('../web/port-alert.ts');

const NOW = Date.parse('2026-11-07T18:20:00Z');
const MIN = 60000, HOUR = 3600000, SKEW = 5 * MIN;
const LIMITS = {windKt: 15, swellFt: 6};
const hourAt = (h, over = {}) => ({at: new Date(Date.parse('2026-11-07T18:00:00Z') + h * HOUR).toISOString(), windKnots: 8, swellFt: 3, ...over});
const full = (over = () => ({})) => Array.from({length: WINDOW_HOURS}, (_, i) => hourAt(i, over(i)));
const loud = i => (i === 3 ? {windKnots: 30} : {});
const iso = ms => new Date(ms).toISOString();
// Same instant written with a +02:00 offset, so tests compare epochs rather than text.
const offset = ms => new Date(ms + 2 * HOUR).toISOString().replace('Z', '+02:00');
const fc = (hours, over = {}) => ({label: 'NOAA GFS model · morro-bay', url: '/sources', issuedAt: '2026-11-07T12:00:00Z', fetchedAt: '2026-11-07T17:30:00Z', hours, ...over});
const REFUSED = {exceedances: [], peak: {windKt: null, swellFt: null}, hoursChecked: 0, notification: null};

test('future_source_clocks_are_stale_before_readings', () => {
  const day = iso(NOW + 24 * HOUR);
  for (const over of [{issuedAt: day}, {fetchedAt: day}, {issuedAt: day, fetchedAt: day}]) {
    for (const hours of [full(), full(loud), []]) {
      const f = fc(hours, over);
      const r = evaluatePortAlert(LIMITS, f, NOW);
      assert.equal(r.state, 'stale');
      assert.ok(isDeepStrictEqual({exceedances: r.exceedances, peak: r.peak, hoursChecked: r.hoursChecked, notification: r.notification}, REFUSED), 'empty evidence');
      assert.equal(r.source, f.label);
      assert.equal(r.issuedAt, f.issuedAt);
      assert.equal(r.fetchedAt, f.fetchedAt);
    }
  }
  const trap = fc([], {issuedAt: iso(NOW + 24 * HOUR)});
  Object.defineProperty(trap, 'hours', {get() { throw new Error('hours scanned after refusal'); }});
  assert.equal(evaluatePortAlert(LIMITS, trap, NOW).state, 'stale');
});

test('five_minute_source_skew_is_inclusive', () => {
  for (const key of ['issuedAt', 'fetchedAt']) {
    for (const [delta, calm, loudState] of [[0, 'clear', 'alert'], [SKEW - 1, 'clear', 'alert'], [SKEW, 'clear', 'alert'], [SKEW + 1, 'stale', 'stale']]) {
      const over = {[key]: offset(NOW + delta)};
      assert.equal(evaluatePortAlert(LIMITS, fc(full(), over), NOW).state, calm, `${key} +${delta} calm`);
      const r = evaluatePortAlert(LIMITS, fc(full(loud), over), NOW);
      assert.equal(r.state, loudState, `${key} +${delta} loud`);
      assert.equal(r.notification === null, loudState === 'stale');
      assert.equal(r[key], over[key], 'clock text preserved');
    }
  }
});

test('old_age_edges_and_invalid_clock_controls_stay_intact', () => {
  assert.equal(evaluatePortAlert(LIMITS, fc(full(), {issuedAt: iso(NOW - 36 * HOUR)}), NOW).state, 'clear');
  assert.equal(evaluatePortAlert(LIMITS, fc(full(), {issuedAt: iso(NOW - 36 * HOUR - 1)}), NOW).state, 'stale');
  assert.equal(evaluatePortAlert(LIMITS, fc(full(), {fetchedAt: iso(NOW - 6 * HOUR)}), NOW).state, 'clear');
  assert.equal(evaluatePortAlert(LIMITS, fc(full(), {fetchedAt: iso(NOW - 6 * HOUR - 1)}), NOW).state, 'stale');
  assert.equal(evaluatePortAlert(LIMITS, fc(full(), {issuedAt: 'garbage'}), NOW).state, 'stale');
  assert.equal(evaluatePortAlert(LIMITS, fc(full()), NaN).state, 'stale');
  assert.equal(evaluatePortAlert(LIMITS, null, NaN).state, 'no-data');
});

test('forecast_valid_times_can_be_future', () => {
  const hours = full(i => (i >= 30 ? {windKnots: 25} : {}));
  const r = evaluatePortAlert(LIMITS, fc(hours), NOW);
  assert.equal(r.state, 'alert');
  assert.equal(r.exceedances[0].at, hours[30].at);
});

test('future_source_refusal_does_not_mutate_inputs', () => {
  const deepFreeze = o => { if (o && typeof o === 'object') { Object.values(o).forEach(deepFreeze); Object.freeze(o); } return o; };
  for (const over of [{issuedAt: iso(NOW + 24 * HOUR)}, {}]) {
    const f = deepFreeze(fc(full(loud), over)), limits = deepFreeze({...LIMITS});
    const before = JSON.stringify([limits, f]);
    evaluatePortAlert(limits, f, NOW);
    assert.equal(JSON.stringify([limits, f]), before);
  }
});

// forecastTime (web/map/frames.ts) refuses finite epochs outside Date's representable range with
// null instead of throwing RangeError during ISO conversion (RF1110-3); valid frames keep their
// existing gate. Fixtures are synthetic; no fetch, no real clock.
import assert from 'node:assert/strict';
import test from 'node:test';
import {forecastTime} from '../web/map/frames.ts';

const H = 3_600_000, MIN = 60_000;
const MAX = 8.64e15;
const NOW = new Date('2026-11-04T18:00:00Z');
const T0 = Date.parse('2026-11-04T18:00:00Z');
const ISSUED = T0 - 3 * H;
const FETCHED = T0 - H;
const TIMES = [T0, T0 + 3 * H];
const AT = new Date(T0);
const call = (times, issued = ISSUED, fetched = FETCHED, at = AT, now = NOW) => forecastTime(times, issued, fetched, at, now);

test('forecast_time_rejects_out_of_range_epoch_arguments', () => {
  assert.equal(call(TIMES), T0, 'control');
  for (const bad of [1e20, -1e20, MAX + 1, -MAX - 1, 8.64e15 * 2]) {
    assert.doesNotThrow(() => call(TIMES, bad));
    assert.equal(call(TIMES, bad), null, `issue ${bad}`);
    assert.equal(call(TIMES, ISSUED, bad), null, `retrieval ${bad}`);
    assert.equal(call([bad], ISSUED, FETCHED), null, `sole listed ${bad}`);
    assert.equal(call([T0, bad, T0 + 3 * H]), null, `mixed listed ${bad}`);
    assert.equal(call([bad, T0]), null, `mixed listed first ${bad}`);
  }
});

test('forecast_time_keeps_existing_nonfinite_refusals', () => {
  for (const bad of [NaN, Infinity, -Infinity]) {
    assert.equal(call(TIMES, bad), null);
    assert.equal(call(TIMES, ISSUED, bad), null);
    assert.equal(call([bad]), null);
    assert.equal(call([T0, bad]), null);
  }
  assert.equal(call([]), null);
  const times = [T0 + 3 * H, T0];
  const copy = [...times];
  assert.equal(call(times), T0);
  assert.deepEqual(times, copy);
});

test('forecast_time_date_range_boundaries_do_not_throw', () => {
  for (const edge of [MAX, -MAX]) {
    assert.doesNotThrow(() => call(TIMES, edge));
    assert.doesNotThrow(() => call(TIMES, ISSUED, edge));
    assert.doesNotThrow(() => call([edge]));
    assert.doesNotThrow(() => call([T0, edge]));
  }
  // Representable but ancient/future metadata is withheld by the unchanged freshness gate.
  assert.equal(call(TIMES, -MAX), null);
  assert.equal(call(TIMES, MAX), null);
  assert.equal(call(TIMES, ISSUED, -MAX), null);
  assert.equal(call(TIMES, ISSUED, MAX), null);
  // One millisecond outside is refused before conversion.
  for (const out of [MAX + 1, -MAX - 1]) {
    assert.doesNotThrow(() => call(TIMES, out));
    assert.equal(call(TIMES, out), null);
    assert.equal(call(TIMES, ISSUED, out), null);
    assert.equal(call([out]), null);
  }
});

test('forecast_time_valid_gate_parity', () => {
  // Exact and nearest match.
  assert.equal(call(TIMES, ISSUED, FETCHED, new Date(T0 + 3 * H)), T0 + 3 * H);
  const hourly = [T0, T0 + H, T0 + 2 * H];
  assert.equal(call(hourly, ISSUED, FETCHED, new Date(T0 + 70 * MIN)), T0 + H);
  // 90-minute tolerance inside a wide span: exact accepted, one ms beyond refused.
  const wide = [T0, T0 + 6 * H];
  assert.equal(call(wide, ISSUED, FETCHED, new Date(T0 + 90 * MIN)), T0);
  assert.equal(call(wide, ISSUED, FETCHED, new Date(T0 + 90 * MIN + 1)), null);
  assert.equal(call(wide, ISSUED, FETCHED, new Date(T0 + 6 * H - 90 * MIN)), T0 + 6 * H);
  assert.equal(call(wide, ISSUED, FETCHED, new Date(T0 + 6 * H - 90 * MIN - 1)), null);
  // Outside the listed span.
  assert.equal(call(TIMES, ISSUED, FETCHED, new Date(T0 + 3 * H + 2 * H)), null);
  assert.equal(call(TIMES, ISSUED, FETCHED, new Date(T0 - 2 * H)), null);
  // 36-hour issue and six-hour retrieval boundaries.
  assert.equal(call(TIMES, NOW.getTime() - 36 * H), T0);
  assert.equal(call(TIMES, NOW.getTime() - 36 * H - 1), null);
  assert.equal(call(TIMES, ISSUED, NOW.getTime() - 6 * H), T0);
  assert.equal(call(TIMES, ISSUED, NOW.getTime() - 6 * H - 1), null);
  // Five minutes ahead tolerated, beyond refused.
  assert.equal(call(TIMES, NOW.getTime() + 5 * MIN), T0);
  assert.equal(call(TIMES, NOW.getTime() + 5 * MIN + 1), null);
  assert.equal(call(TIMES, ISSUED, NOW.getTime() + 5 * MIN), T0);
  assert.equal(call(TIMES, ISSUED, NOW.getTime() + 5 * MIN + 1), null);
});

// RF1950-3: planRun refuses unusable distance/speed before any arithmetic.
import test from 'node:test';
import assert from 'node:assert/strict';

const {planRun} = await import('../web/brief/run.ts');

const WINDOW = {start: '2026-10-12T14:00:00.000Z', end: '2026-10-12T19:00:00.000Z', label: 'Lower wind & offshore seas', confidence: 'Low', reasons: [], wind: 8, gust: 12, wave: 3, period: 10};
const brief = (over = {}) => ({profile: 'boat', windows: [WINDOW], alerts: [], missing: [], tiles: [], limits: {custom: false}, ...over});
const at = s => new Date(s);
const NOW = at('2026-10-12T12:00:00Z');
const place = nm => ({name: 'Spot', nm});

test('plan_run_nonfinite_speed_is_no_speed', () => {
  for (const speed of [Infinity, -Infinity, NaN, 0, -5, null]) {
    const run = planRun(brief(), place(7.4), speed, NOW);
    assert.deepEqual(run, {kind: 'no-speed'}, String(speed));
  }
});

test('plan_run_bad_distance_is_no_place', () => {
  for (const nm of [-1, NaN, Infinity, -Infinity]) {
    assert.deepEqual(planRun(brief(), place(nm), 20, NOW), {kind: 'no-place'}, String(nm));
  }
  assert.deepEqual(planRun(brief(), null, 20, NOW), {kind: 'no-place'});
});

test('plan_run_helper_refusal_never_enters_arithmetic', () => {
  // Finite positive speed so small that nm / speed * 60 overflows to Infinity.
  const run = planRun(brief(), place(1e300), 1e-300, NOW);
  assert.deepEqual(run, {kind: 'no-place'});
});

test('plan_run_refusal_precedence_is_unchanged', () => {
  const none = planRun(brief({windows: []}), place(-1), Infinity, NOW);
  assert.equal(none.kind, 'no-window');
  assert.deepEqual(planRun(brief(), place(-1), Infinity, NOW), {kind: 'no-speed'});
});

test('plan_run_zero_and_fractional_distance_keep_rounding', () => {
  const zero = planRun(brief(), place(0), 20, NOW);
  assert.equal(zero.kind, 'ok');
  assert.equal(zero.runMin, 5);
  const run = planRun(brief(), place(7.4), 20, NOW);
  assert.equal(run.kind, 'ok');
  assert.equal(run.runMin, 25);
  assert.equal(run.arrive, '2026-10-12T14:25:00.000Z');
  assert.equal(run.turnBack, '2026-10-12T18:35:00.000Z');
  assert.equal(run.fishMin, 250);
});

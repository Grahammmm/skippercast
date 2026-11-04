// An explicit hazard stays no-go when its numeric conditions score is missing;
// ordinary missing evidence stays unknown. Synthetic ratings only, no network.
import test from 'node:test';
import assert from 'node:assert/strict';

// Deny the network before any product module loads.
globalThis.fetch = async () => { throw new Error('network is denied in this test'); };

const {verdictFor} = await import('../web/score.ts');
const {verdictFor: tomorrowVerdict, planDay} = await import('../dist/tomorrow.js');
const {verdictFor: advisorVerdict, COMFORT_WORD} = await import('../server/advisor/answers/comfort.ts');

const MISSING = [['absent', undefined], ['undefined', undefined], ['null', null], ['NaN', NaN], ['Infinity', Infinity], ['-Infinity', -Infinity]];
const withScore = (v, extra) => ({...extra, conditions: v});
const absentConditions = (extra) => ({...extra});

test('hazard_survives_missing_numeric_rating', () => {
  assert.equal(verdictFor(absentConditions({hazard: true})), 'no-go');
  for (const [name, v] of MISSING) assert.equal(verdictFor(withScore(v, {hazard: true})), 'no-go', name);
  for (const v of [0, 3.9, 4, 6.9, 7, 10]) assert.equal(verdictFor(withScore(v, {hazard: true})), 'no-go', String(v));
});

test('missing_without_hazard_stays_unknown', () => {
  for (const hazard of [undefined, false]) {
    assert.equal(verdictFor(absentConditions({hazard})), 'unknown');
    for (const [name, v] of MISSING) assert.equal(verdictFor(withScore(v, {hazard})), 'unknown', `${name} hazard=${hazard}`);
  }
  assert.equal(verdictFor(null), 'unknown');
  assert.equal(verdictFor(undefined), 'unknown');
  // numeric boundaries without a hazard are unchanged, including score zero
  const expected = [[0, 'no-go'], [3.9, 'no-go'], [4, 'marginal'], [6.9, 'marginal'], [7, 'go'], [10, 'go']];
  for (const [v, word] of expected) assert.equal(verdictFor({conditions: v}), word, String(v));
});

test('hazard_verdict_reexports_agree', () => {
  const ratings = [null, undefined, {}, {hazard: false}, {hazard: true}, ...MISSING.flatMap(([, v]) => [withScore(v, {}), withScore(v, {hazard: false}), withScore(v, {hazard: true})]),
    ...[0, 3.9, 4, 6.9, 7, 10].flatMap((v) => [{conditions: v}, {conditions: v, hazard: true}])];
  for (const r of ratings) {
    const want = verdictFor(r);
    assert.equal(tomorrowVerdict(r), want, JSON.stringify(r));
    assert.equal(advisorVerdict(r), want, JSON.stringify(r));
  }
  assert.equal(COMFORT_WORD[advisorVerdict({hazard: true, conditions: null})], 'rough');
  assert.equal(COMFORT_WORD[advisorVerdict({hazard: true})], 'rough');
  assert.equal(COMFORT_WORD[advisorVerdict({conditions: null})], 'unknown');
  assert.equal(COMFORT_WORD[advisorVerdict(null)], 'unknown');
});

// planDay with an injected rating per hour (14 hours, two per window) and an empty model bundle.
const DATE = '2026-09-22';
const NOW = Date.parse('2026-09-21T20:00:00-07:00');
const BOAT = {sea: 1, wind: 1, chopPeriod: 6};
function plan(ratings) {
  const frozen = ratings.map((r) => (r && typeof r === 'object' ? Object.freeze({...r}) : r));
  let i = 0;
  const rate = () => frozen[i++];
  const day = planDay({models: {}}, 0, 'lingcod', DATE, NOW, BOAT, rate);
  return {day, frozen};
}
const go = {conditions: 8};
const marginal = {conditions: 5};
const unknown = {conditions: null};
const hazardMissing = {conditions: null, hazard: true};

test('tomorrow_window_keeps_hazard_and_null_score', () => {
  // all unknown: every window unknown, every score null
  const allMissing = plan(Array(14).fill(unknown)).day;
  assert.deepEqual(allMissing.windows.map((w) => w.verdict), Array(7).fill('unknown'));
  assert.deepEqual(allMissing.windows.map((w) => w.conditions), Array(7).fill(null));

  // one hazardous hour with no score among unknowns: only its window turns no-go
  for (const hour of [0, 1, 6, 7, 13]) {
    const ratings = Array(14).fill(unknown).map((r, i) => (i === hour ? hazardMissing : r));
    const {day} = plan(ratings);
    const win = Math.floor(hour / 2);
    day.windows.forEach((w, k) => {
      assert.equal(w.verdict, k === win ? 'no-go' : 'unknown', `hour ${hour} window ${k}`);
      assert.equal(w.conditions, null, `hour ${hour} window ${k} score stays null`);
    });
  }

  // hazard beside comfortable and unknown neighbours; unrelated windows keep their verdicts
  const mixed = [go, go, hazardMissing, go, unknown, go, hazardMissing, unknown, marginal, go, go, go, unknown, unknown];
  const {day, frozen} = plan(mixed);
  assert.deepEqual(day.windows.map((w) => w.verdict), ['go', 'no-go', 'unknown', 'no-go', 'marginal', 'go', 'unknown']);
  assert.deepEqual(day.windows.map((w) => w.conditions), [8, null, null, null, 5, 8, null]);
  assert.equal(day.worst, 'no-go');
  // the inputs are not mutated and gain no invented score
  assert.deepEqual(frozen, mixed);
  assert.equal(frozen[2].conditions, null);
});

test('tomorrow_window_hazard_with_finite_score_unchanged', () => {
  const {day} = plan([go, {conditions: 9, hazard: true}, ...Array(12).fill(go)]);
  assert.equal(day.windows[0].verdict, 'no-go');
  assert.equal(day.windows[0].conditions, 8);
  assert.ok(day.windows.slice(1).every((w) => w.verdict === 'go'));
});

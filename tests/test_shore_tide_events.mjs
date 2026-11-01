// RF1740-2: the shore tide phase (packages/coast/src/shore-conditions.ts tidePhase)
// ignores malformed tide events and curve points, and reads a time listed as both
// a high and a low as an unknown boundary, the rule barTide already uses.
import test from 'node:test';
import assert from 'node:assert/strict';

const {tidePhase, shoreHours, shoreDay, seaward} = await import('../packages/coast/src/shore-conditions.ts');

const HOUR = 3_600_000, MIN = 60_000;
const t0 = Date.parse('2026-10-09T12:00:00Z');
const iso = ms => new Date(ms).toISOString();
const L0 = {at: iso(t0), heightFt: 0.5, type: 'L'}, H6 = {at: iso(t0 + 6 * HOUR), heightFt: 5, type: 'H'}, L12 = {at: iso(t0 + 12 * HOUR), heightFt: 1, type: 'L'};
const events = [L0, H6, L12];
const phases = list => [3 * HOUR, 6 * HOUR, 9 * HOUR, 20 * MIN].map(d => tidePhase(t0 + d, list).phase);

test('well-formed high and low events read as before', () => {
  assert.deepEqual(phases(events), ['rising', 'high', 'falling', 'low']);
  assert.equal(tidePhase(t0 + 20 * MIN, events).heightFt, 0.5, 'low falls back to the event height');
  assert.equal(tidePhase(t0 + 3 * HOUR, [L12, H6, L0]).phase, 'rising', 'input order does not matter');
});

test('null, array, string and wrongly-typed events are ignored without throwing', () => {
  const junk = [null, [], 'x', {at: 5}, 7, undefined, {at: 'not a time', type: 'H'}, {at: iso(t0 + 3 * HOUR), heightFt: 9}];
  assert.deepEqual(phases([junk[0], L0, ...junk.slice(1, 4), H6, ...junk.slice(4), L12]), ['rising', 'high', 'falling', 'low']);
  assert.equal(tidePhase(t0 + 3 * HOUR, junk).phase, null, 'nothing usable either side');
  // An array element in the 'at' slot or a type-like non-string stays out too.
  assert.equal(tidePhase(t0 + 3 * HOUR, [L0, {at: [iso(t0 + 4 * HOUR)], type: 'H'}, {at: iso(t0 + 4 * HOUR), type: ['H']}]).phase, null);
});

test("an event of type 'X' is ignored: the phase comes from the real events either side", () => {
  const x = {at: iso(t0 + 4 * HOUR), heightFt: 3, type: 'X'};
  assert.equal(tidePhase(t0 + 3 * HOUR, [L0, x, H6, L12]).phase, 'rising', 'not falling toward an X');
  assert.equal(tidePhase(t0 + 4 * HOUR, [L0, x, H6, L12]).phase, 'rising', 'an X within the span is no high or low');
  assert.equal(tidePhase(t0 + 3 * HOUR, [L0, {...x, type: 'h'}, H6]).phase, 'rising', 'type is case-sensitive');
  assert.equal(tidePhase(t0 + 3 * HOUR, [L0, x]).phase, null, 'only an X ahead: no next event');
});

test('a time listed as both high and low is an unknown boundary', () => {
  const at = iso(t0 + 12 * HOUR), H18 = {at: iso(t0 + 18 * HOUR), heightFt: 5, type: 'H'};
  for (const both of [[{at, heightFt: 1, type: 'L'}, {at, heightFt: 4, type: 'H'}], [{at, heightFt: 4, type: 'H'}, {at, heightFt: 1, type: 'L'}]]) {
    const list = [L0, H6, ...both, H18];
    assert.equal(tidePhase(t0 + 14 * HOUR, list).phase, null, 'between the conflict and the next event');
    assert.equal(tidePhase(t0 + 12 * HOUR + 30 * MIN, list).phase, null, 'within the span of the conflict, not high');
    assert.equal(tidePhase(t0 + 12 * HOUR, list).phase, null, 'at the conflict itself');
    assert.equal(tidePhase(t0 + 10 * HOUR, list).phase, null, 'the next event is the conflict');
    assert.equal(tidePhase(t0 + 3 * HOUR, list).phase, 'rising', 'hours away from the conflict are unchanged');
  }
  const list = [L0, H6, {at, type: 'L'}, {at, type: 'H'}, H18];
  const read = tidePhase(t0 + 14 * HOUR, list, [{at: iso(t0 + 14 * HOUR), heightFt: 2.2}]);
  assert.equal(read.phase, null);
  assert.equal(read.heightFt, 2.2, 'height from the curve is still read');
  assert.equal(read.bonus, false);
  assert.equal(tidePhase(t0 + 12 * HOUR, [{at, heightFt: -1, type: 'L'}, {at, type: 'H'}]).veryLow, false, 'no low-event height for an unknown phase');
});

test('an exact duplicate event collapses and leaves the phase unchanged', () => {
  assert.deepEqual(phases([L0, H6, {...H6}, L12]), ['rising', 'high', 'falling', 'low']);
  assert.deepEqual(phases([L0, L0, H6, H6, L12, L12]), ['rising', 'high', 'falling', 'low']);
});

test('null and non-numeric curve points are ignored; the height comes from the nearest valid point', () => {
  const at = t0 + 3 * HOUR;
  const curve = [null, {at: iso(at), heightFt: '1.2'}, [], 'x', {at: iso(at), heightFt: NaN}, {at: 5, heightFt: 9}, {at: iso(at + 30 * MIN), heightFt: 2}];
  assert.equal(tidePhase(at, events, curve).heightFt, 2);
  assert.equal(tidePhase(at, events, curve.slice(0, -1)).heightFt, null, 'no valid point at all');
  assert.equal(tidePhase(at, events, [...curve.slice(0, -1), {at: iso(at + 2 * HOUR), heightFt: 2}]).heightFt, null, 'nearest valid point more than an hour away');
  assert.equal(tidePhase(t0 + 20 * MIN, events, [null, {at: iso(t0), heightFt: '0.1'}]).heightFt, 0.5, 'low still falls back to its event height');
});

test('shoreDay reads the tide as unknown when a conflict leaves every hour without a phase', () => {
  const area = {id: 'central'}, sunrise = iso(t0), sunset = iso(t0 + 10 * HOUR);
  const hours = [2, 3, 4].map(i => ({at: iso(t0 + i * HOUR), windKnots: 5, gustKnots: 8, waveFt: 1.5, wavePeriodS: 10}));
  const day = tideEvents => shoreDay(shoreHours({hours, site: undefined, countyId: 'slo', area, tideEvents, tides: [], sunrise, sunset}), sunrise, sunset, seaward('slo', 'central'));
  const conflicted = day([{at: iso(t0), heightFt: 1, type: 'L'}, {at: iso(t0), heightFt: 4, type: 'H'}, null, H6]);
  assert.deepEqual(conflicted.hours.map(h => h.tide.phase), [null, null, null]);
  assert.equal(conflicted.tideUnknown, true);
  assert.equal(day([L0, null, H6]).tideUnknown, false, 'the same hours with a clean low read rising');
});

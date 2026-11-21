import assert from 'node:assert/strict';
import test from 'node:test';
import {MAX_ANALYSIS_ALERTS_PER_RUN, planAnalysisAlertRun} from '../server/analysis-alert-run.ts';

const sst = 'sst-analysis';
const chl = 'chlorophyll-observation';
const alert = (owner, region = 'bay', layer = sst, sampleAt = '2026-11-19T08:00:00Z') =>
  ({owner, region, layer, sampleAt});
const bay = alert('A');

// Checking for empty input before degraded would report the wrong reason.
test('C1: degraded takes precedence with no candidates', () => {
  assert.deepEqual(planAnalysisAlertRun({degraded: true, candidates: [], devices: new Set()}),
    {run: false, reason: 'degraded'});
});

// Even an eligible row must not be inspected in degraded mode.
test('C1: degraded takes precedence without evaluating candidates or devices', () => {
  const candidates = new Proxy([bay], {
    get() { assert.fail('read candidates in degraded mode'); },
  });
  assert.deepEqual(planAnalysisAlertRun({degraded: true, candidates,
    get devices() { assert.fail('read devices in degraded mode'); },
  }), {run: false, reason: 'degraded'});
});

// A healthy run with no work must not produce an empty runnable plan.
test('C1: no candidates when the input is empty', () => {
  assert.deepEqual(planAnalysisAlertRun({degraded: false, candidates: [], devices: new Set(['A'])}),
    {run: false, reason: 'no-candidates'});
});

const malformed = [null, undefined, {...bay, owner: 4}, {...bay, region: []},
  {...bay, layer: null}, {...bay, layer: 'wave-forecast'}, {...bay, sampleAt: 123}];

// A nonempty input is still idle if every row fails validation.
test('C1: no candidates when none are usable', () => {
  assert.deepEqual(planAnalysisAlertRun({degraded: false, candidates: malformed, devices: new Set(['A'])}),
    {run: false, reason: 'no-candidates'});
});

// Locale sorting, delimiter keys and last-wins dedup would change this plan.
// A malformed row before its valid twin must not claim that twin's identity.
test('C2: validates, keeps the first valid triple, and orders by owner, region, layer', () => {
  const first = alert('A', 'Z', sst, 'sample-marker');
  const later = alert('A', 'Z', sst, '2026-11-19T20:00:00Z');
  const otherLayer = alert('A', 'Z', chl);
  const otherRegion = alert('A', 'a');
  const otherOwner = alert('a', 'Z');
  const delimiterInOwner = alert('A|B', 'C');
  const delimiterInRegion = alert('A', 'B|C');
  const candidates = [otherOwner, ...malformed, otherRegion, delimiterInOwner,
    {...first, sampleAt: false}, first, otherLayer, later, delimiterInRegion];
  const devices = new Set(['a', 'A|B', 'A']);
  assert.deepEqual(planAnalysisAlertRun({degraded: false, candidates, devices}), {
    run: true,
    send: [delimiterInRegion, otherLayer, first, otherRegion, delimiterInOwner, otherOwner],
    noDevice: [], deferred: [],
  });
});

// A missing device is a classification, not a reason to drop a usable row.
test('C2: runs even when no candidate owner has a device', () => {
  const other = alert('B');
  assert.deepEqual(planAnalysisAlertRun({degraded: false, candidates: [other, bay], devices: new Set(['C'])}), {
    run: true, send: [], noDevice: [bay, other], deferred: [],
  });
});

// Hard-code the contract in the fixture so an accidental constant change cannot move the oracle.
const atCap = Array.from({length: 200}, (_, i) => alert(`owner-${String(i).padStart(3, '0')}`));
const overflow = [alert('owner-200'), alert('owner-201')];
const noDevice = [alert('A'), alert('z')];

// Reverse the input and put device-less rows on both sides of the sorted send window.
// Neither those rows nor duplicates can consume a send slot; overflow must remain in order.
for (const count of [0, 1, 2]) {
  test(`C2: plans 200 sends with ${count} eligible overflow`, () => {
    assert.equal(MAX_ANALYSIS_ALERTS_PER_RUN, 200);
    const deferred = overflow.slice(0, count);
    const eligible = [...atCap, ...deferred];
    const candidates = [noDevice[1], ...eligible.toReversed(), noDevice[0],
      {...atCap[0], sampleAt: 'later duplicate'}].map(Object.freeze);
    const devices = new Set(eligible.map(row => row.owner));
    const input = Object.freeze({degraded: false, candidates: Object.freeze(candidates), devices});
    const expected = {run: true, send: atCap, noDevice, deferred};
    const plan = planAnalysisAlertRun(input);
    assert.deepEqual(plan, expected);
    assert.deepEqual([...devices], eligible.map(row => row.owner));

    // Sorting or annotating the frozen input would fail; returning aliased rows or arrays would leak edits.
    const next = planAnalysisAlertRun(input);
    assert.deepEqual(next, expected);
    for (const bucket of ['send', 'noDevice', 'deferred']) {
      assert.notStrictEqual(plan[bucket], next[bucket]);
      for (const [i, row] of plan[bucket].entries()) {
        assert.equal(candidates.includes(row), false);
        assert.notStrictEqual(row, next[bucket][i]);
      }
    }
  });
}

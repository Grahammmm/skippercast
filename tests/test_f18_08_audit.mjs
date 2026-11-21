// SCA-588 / F18-08: a low and a high 72 hours apart do not support a flood/ebb phase at the midpoint the way a six-hour
// pair does. Offline synthetic fixture; no network, no real tide data. Valid controls must satisfy the contract. The
// affected control is only *observed* (diagnostic): the test neither asserts the gap is desirable nor fails when it is
// fixed. A synthetic negative control proves the detector.
import test from 'node:test';
import assert from 'node:assert/strict';
import {barTide} from '../packages/coast/src/bar-conditions.ts';
import {entranceTiming} from '../packages/coast/src/entrance-current.ts';

const H = 3600000, base = Date.parse('2026-06-15T17:00:00Z');
const ev = (i, type) => ({at: new Date(base + i * H).toISOString(), type, heightFt: type === 'H' ? 5 : 1});
const pair = hours => [ev(-hours / 2, 'L'), ev(hours / 2, 'H')];
// Interior gap: a supported six-hour cycle on each side, but only a low and a high 72 h apart around `base`.
const gapped = [ev(-39, 'H'), ev(-36, 'L'), ev(36, 'H'), ev(42, 'L')];
const supported = [ev(-9, 'H'), ev(-3, 'L'), ev(3, 'H'), ev(9, 'L')];

const observe = events => {
  const bar = barTide(base, events), timing = entranceTiming(base, events);
  return {barStage: bar.stage, timingState: timing.state, timingPhase: timing.state === 'ok' ? timing.phase : null};
};
// Contract: an unsupported interior gap yields unknown for both; a supported pair stays judged.
const judged = r => r.barStage !== null && r.timingState === 'ok';
const unknown = r => r.barStage === null && r.timingState === 'unknown';

test('valid controls satisfy the contract', () => {
  for (const events of [pair(6), supported]) {
    const r = observe(events);
    assert.ok(judged(r), JSON.stringify(r));
    assert.equal(r.barStage, 'flood');
    assert.equal(r.timingPhase, 'flood');
  }
  // no events at all is already unknown (not a gap case)
  assert.ok(unknown(observe([])));
});

test('checker detects the stated gap on synthetic results', () => {
  // independent negative control: fabricated results, no dependence on the tide model
  const gap = {barStage: 'flood', timingState: 'ok', timingPhase: 'flood'};
  assert.equal(unknown(gap), false, 'judged phase across an unsupported gap must be detected');
  assert.equal(unknown({barStage: 'flood', timingState: 'unknown', timingPhase: null}), false, 'barTide and entranceTiming must agree');
  assert.equal(unknown({barStage: null, timingState: 'unknown', timingPhase: null}), true);
  assert.equal(judged({barStage: null, timingState: 'unknown', timingPhase: null}), false, 'a supported pair must not become unknown');
});

test('affected control: baseline observation only (passes before and after a fix)', t => {
  // Low and high 72 h apart, probed at the midpoint. Expected after a fix: barStage null and timing unknown. Not
  // asserted, so a correct fix needs no edit here. The 6 h pair is shown for comparison.
  for (const [name, events] of [['72h gap', pair(72)], ['6h pair', pair(6)], ['interior gap between supported cycles', gapped]]) {
    const r = observe(events);
    t.diagnostic(`${name}: ${JSON.stringify(r)} unknownContractHolds=${unknown(r)}`);
  }
});

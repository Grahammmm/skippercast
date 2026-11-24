import assert from 'node:assert/strict';
import test from 'node:test';
import {selectCurrentFrame} from '../packages/coast/src/map-sources.ts';

const now = new Date('2026-11-23T13:00:00Z');
const cell = {lat: 35.35, lon: -120.95, uMs: 0, vMs: 0.51, speedKnots: 1, towardDeg: 0};
const frame = (validAt, cells = [cell]) => ({validAt, cells});
const select = frames => selectCurrentFrame({kind: 'observation', fetchedAt: now.toISOString(), frames}, now, now);
const older = frame('2026-11-23T11:00:00Z');
const newer = frame('2026-11-23T12:00:00Z');

// Picking the last eligible arrival (reverse + find) shows 11:00 in the first case.
for (const [label, frames] of [['newest first', [newer, older]], ['newest last', [older, newer]]]) {
  test(`observation uses the newest eligible native frame: ${label}`, () => {
    const selected = select(Object.freeze(frames));
    assert.equal(selected?.validAt, newer.validAt);
    assert.strictEqual(selected, newer);
  });
}

test('newer future and empty observations do not displace a usable frame', () => {
  const future = frame('2026-11-23T13:01:00Z');
  const empty = frame('2026-11-23T12:30:00Z', []);
  assert.strictEqual(select([newer, future, empty]), newer);
  assert.strictEqual(select([future, empty]), null);
});

test('observation order uses parsed time; equal epochs still favor the last supplied frame', () => {
  const earlierWithOffset = frame('2026-11-23T12:30:00+01:00');
  const tiedWithOffset = frame('2026-11-23T07:00:00-05:00');
  assert.strictEqual(select([earlierWithOffset, newer]), newer, 'lexically later timestamp is actually older');
  assert.strictEqual(select([newer, tiedWithOffset]), tiedWithOffset);
  assert.strictEqual(select([tiedWithOffset, newer]), newer);
});

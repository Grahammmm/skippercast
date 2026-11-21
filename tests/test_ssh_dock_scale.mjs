import assert from 'node:assert/strict';
import test from 'node:test';
import {sshDockScale} from '../web/map/ssh-dock-scale.ts';
import {sshPosition} from '../web/map/ssh-scale.ts';

const hour = '2026-11-21T06:00:00Z';
const sameHour = '2026-11-20T22:00:00-08:00';
const nextHour = '2026-11-21T07:00:00Z';

function frame(validAt, ...values) {
  return {validAt, cells: values.map((sshCm, i) => ({lat: 35, lon: -121 + i / 20, sshCm}))};
}

function forecast(...frames) {
  return {product: 'WCOFS', issuedAt: '2026-11-21T03:00:00Z', resolution: [0.05, 0.05], frames};
}

// String matching misses the offset timestamp, and pooling frames admits the 80 cm cell.
test('C1: fit only the matching instant and retain its frame timestamp', () => {
  const f = forecast(frame(nextHour, 80), frame(sameHour, 5, -9, NaN));
  assert.deepEqual(sshDockScale(f, hour), {validAt: sameHour, limitCm: 10, ticks: [-10, -5, 0, 5, 10]});
});

// A last-write-wins index or a preference for identical spelling selects the second frame.
test('C1: keep the first of two frames at the same instant', () => {
  const f = forecast(frame(sameHour, 3), frame(hour, 40));
  assert.deepEqual(sshDockScale(f, hour), {validAt: sameHour, limitCm: 5, ticks: [-5, -2.5, 0, 2.5, 5]});
});

// A nearest-hour fallback would select this frame just one millisecond away.
test('C2: a missing instant gives no-frame', () => {
  const f = forecast(frame(hour, 5));
  assert.deepEqual(sshDockScale(f, '2026-11-21T06:00:00.001Z'), {none: 'no-frame'});
});

// Matching raw strings or indexing NaN as a key would select the invalid frame.
test('C2: an unparsable instant gives no-frame', () => {
  assert.deepEqual(sshDockScale(forecast(frame('invalid', 5)), 'invalid'), {none: 'no-frame'});
});

// Assuming the collection has array methods would throw on a non-array payload.
test('C2: non-array frames give no-frame', () => {
  assert.deepEqual(sshDockScale({...forecast(), frames: {}}, hour), {none: 'no-frame'});
});

// Failed access to frame metadata must not escape into the dock.
test('C2: unreadable frame metadata gives no-frame', () => {
  const f = forecast({get validAt() { throw new Error('unreadable frame instant'); }});
  assert.deepEqual(sshDockScale(f, hour), {none: 'no-frame'});
});

// An empty scale must not be replaced with a default or borrowed from a later duplicate.
test('C2: an all-NaN first match gives no-values', () => {
  const f = forecast(frame(sameHour, NaN, NaN), frame(hour, 5));
  assert.deepEqual(sshDockScale(f, hour), {none: 'no-values'});
});

// Calling .map on a malformed cell list must not throw once the instant has matched.
test('C2: unreadable cells in the chosen frame give no-values', () => {
  const f = forecast({...frame(hour), cells: null});
  assert.deepEqual(sshDockScale(f, hour), {none: 'no-values'});
});

// A limit taken from the other hour would move this cell away from the quarter point.
test('C3: the chosen limit puts a chosen-frame cell at the quarter point', () => {
  const chosen = frame(hour, -5, 9);
  const f = forecast(frame(nextHour, 40), chosen);
  const result = sshDockScale(f, hour);
  assert.deepEqual(result, {validAt: hour, limitCm: 10, ticks: [-10, -5, 0, 5, 10]});
  assert.equal(sshPosition(chosen.cells[0].sshCm, result.limitCm), 0.25);
});

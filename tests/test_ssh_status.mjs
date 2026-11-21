import assert from 'node:assert/strict';
import test from 'node:test';
import {sshStatus} from '../web/map/ssh-status.ts';

const ISSUED = '2026-11-19T00:00:00Z';
const EARLY = '2026-11-19T03:00:00.000Z';
const LATE = '2026-11-19T09:00:00.000Z';
const BAD = 'not a time';
const CELL = {lat: 35.04, lon: -121.05, sshCm: 12.5};
const frame = (validAt, cells = [CELL]) => ({validAt, cells});
const ready = (...frames) => ({state: 'ready', product: 'NOAA WCOFS', issuedAt: ISSUED,
  resolution: [0.04, 0.05], maxAgeMs: 21_600_000, frames});

// C1: parsing the dock time before checking the feed would mask these states.
for (const [name, feed, result] of [
  ['pending feed is loading, not absent', null, {state: 'loading'}],
  ['absent layer is none, not loading', {state: 'none'}, {state: 'none'}],
  ['network error keeps its flag', {state: 'error', network: true}, {state: 'error', network: true}],
  ['plain error has an explicit false flag', {state: 'error'}, {state: 'error', network: false}],
]) {
  test(`C1: ${name}`, () => assert.deepEqual(sshStatus(feed, BAD), result));
}

// C1: neither an exact listed time nor a nominally OK layer label can bypass the loader gate.
for (const layerStatus of ['stale', 'ok']) {
  test(`C1: listed ${layerStatus} feed is withheld even when it lists the dock hour`, () => {
    assert.deepEqual(sshStatus({state: 'listed', validAt: [EARLY], layerStatus}, EARLY),
      {state: 'withheld', reason: 'not-current', layerStatus});
  });
}

test('C2: an invalid dock time is bad-time even with no frames', () => {
  assert.deepEqual(sshStatus(ready(), BAD), {state: 'withheld', reason: 'bad-time'});
});

for (const [name, feed] of [['empty', ready()], ['all-invalid', ready(frame(BAD))]]) {
  test(`C2: an ${name} forecast has no frame rather than temporal bounds`, () => {
    assert.deepEqual(sshStatus(feed, EARLY), {state: 'withheld', reason: 'no-frame'});
  });
}

// C2: bounds are chronological, not array endpoints; a gap must not pick a nearby frame.
for (const [validAt, reason] of [
  ['2026-11-19T02:59:59.999Z', 'before-forecast'],
  ['2026-11-19T09:00:00.001Z', 'after-forecast'],
  ['2026-11-19T06:00:00Z', 'no-frame'],
]) {
  test(`C2: ${reason} with unsorted frames and an invalid timestamp`, () => {
    assert.deepEqual(sshStatus(ready(frame(BAD), frame(LATE), frame(EARLY)), validAt),
      {state: 'withheld', reason});
  });
}

test('C2: the first exact frame with no cells is withheld even if a duplicate has cells', () => {
  assert.deepEqual(sshStatus(ready(frame(EARLY, []), frame('2026-11-19T03:00:00Z')), EARLY),
    {state: 'withheld', reason: 'no-cells'});
});

test('C2: matches by instant and reports the first duplicate’s original spelling and count', () => {
  const feed = ready(frame(BAD), frame(LATE, [CELL, {...CELL, sshCm: 0}]), frame('2026-11-19T09:00:00Z'));
  assert.deepEqual(sshStatus(feed, '2026-11-19T01:00:00-08:00'),
    {state: 'shown', cells: 2, issuedAt: ISSUED, validAt: LATE});
});

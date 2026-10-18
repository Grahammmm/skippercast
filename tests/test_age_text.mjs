// ROLL-04 / #422: preserve each surface's existing age contract. Both floor
// elapsed time; Brief explicitly reports a clock ahead, while landing follows
// confidence.ts's zero clamp and judges observation freshness separately.
// Missing timestamps are handled by callers, not passed to ageText.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {ageText as landingAge, buoyReadings, feedState} from '../web/landing/readings.ts';

const dir = await mkdtemp(join(tmpdir(), 'age-text-'));
let briefAge, sourceLine;
try {
  const out = join(dir, 'tiles.mjs');
  await build({
    entryPoints: [new URL('../web/brief/Tiles.tsx', import.meta.url).pathname],
    bundle: true, format: 'esm', platform: 'node', outfile: out,
    jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent',
  });
  ({ageText: briefAge, sourceLine} = await import(pathToFileURL(out).href));
} finally {
  await rm(dir, {recursive: true, force: true});
}

const MIN = 60_000, HOUR = 60 * MIN, DAY = 24 * HOUR;
const NOW = Date.parse('2026-10-16T12:00:00Z');

test('elapsed age floors partial units at minute, hour and day boundaries on both surfaces', () => {
  const cases = [
    [0, '0 min'], [MIN - 1, '0 min'], [MIN, '1 min'],
    [59 * MIN, '59 min'], [HOUR - 1, '59 min'], [HOUR, '1 h'],
    [DAY - 1, '23 h'], [DAY, '24 h'],
    [47 * HOUR, '47 h'], [2 * DAY - 1, '47 h'], [2 * DAY, '2 d'],
    [3 * DAY - 1, '2 d'], [3 * DAY, '3 d'],
  ];
  for (const [ms, expected] of cases) {
    assert.equal(briefAge(ms), expected, `Brief at ${ms} ms`);
    assert.equal(landingAge(ms), expected, `landing at ${ms} ms`);
  }
});

test('future ages retain the explicit per-surface difference, including source lines', () => {
  for (const ms of [-1, -MIN, -DAY]) {
    assert.equal(briefAge(ms), 'clock ahead');
    assert.equal(landingAge(ms), '0 min');
  }
  const tile = {source: 'Synthetic buoy', state: 'fresh', ageMs: -1};
  assert.equal(sourceLine(tile), 'Synthetic buoy · clock ahead old');
  assert.equal(sourceLine(tile, true), 'Synthetic buoy · clock ahead');
});

function windAt(time) {
  return buoyReadings({schema_version: 1, sources: {offshore: {
    status: 'ok', max_age_hours: 2,
    data: {station: '46028', units: {WSPD: 'm/s'}, observations: [{time, WSPD: 3}]},
  }}}, {}, NOW)[0];
}

test('landing clamps future observation text but retains its five-minute freshness tolerance', () => {
  for (const [ahead, stale] of [[1, false], [5 * MIN, false], [5 * MIN + 1, true]]) {
    const reading = windAt(new Date(NOW + ahead).toISOString());
    assert.equal(reading.source, 'NDBC 46028 · 0 min');
    assert.equal(reading.stale, stale, `${ahead} ms ahead`);
  }
  // Feed generation uses the separate existing late-only rule.
  assert.deepEqual(feedState({generated_at: new Date(NOW + DAY).toISOString()}, NOW), {age: '0 min', stale: false});
});

test('missing or invalid clocks stay unavailable rather than becoming zero-age readings', () => {
  for (const time of [undefined, null, '', 'invalid', '2026-10-16T12:00:00']) {
    const reading = windAt(time);
    assert.equal(reading.reading, 'No reading');
    assert.equal(reading.source, 'NDBC 46028 · unavailable');
    assert.equal(reading.stale, true);
    assert.deepEqual(feedState({generated_at: time}, NOW), {age: null, stale: true});
  }
  assert.equal(sourceLine({source: 'Synthetic buoy', state: 'fresh', ageMs: null}), 'Synthetic buoy · unavailable');
  assert.equal(sourceLine({source: 'Synthetic buoy', state: 'unavailable', ageMs: 0}), 'Synthetic buoy · unavailable');
});

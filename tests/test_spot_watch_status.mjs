import assert from 'node:assert/strict';
import test from 'node:test';
import {watchStatus} from '../web/spot-watch-status.ts';

const WATCH = Object.freeze({
  layer: 'water-temp', op: '>=', a: 58, b: null,
  enabled: true, lastValue: null, lastSampleAt: null,
});
const STATUS = {op: '>=', values: [58], unit: '°F', last: null, paused: false, needsNotifications: false};
const TZ = 'America/Los_Angeles';

// Catch using an absolute temperature conversion for a contrast or converting chlorophyll at all.
for (const [layer, temp, op, a, b, values, unit] of [
  ['water-temp', 'F', '>=', 58, null, [58], '°F'],
  ['water-temp', 'C', 'between', 58, 62, [14.4, 16.7], '°C'],
  ['chlorophyll', 'F', '<=', 1.2345, null, [1.2345], 'mg/m³'],
  ['chlorophyll', 'C', 'between', 1.2345, 2.3456, [1.2345, 2.3456], 'mg/m³'],
  ['sst-contrast', 'F', 'between', 1.2345, 2.3456, [1.2345, 2.3456], '°F/nm'],
  ['sst-contrast', 'C', '<=', 1.2345, NaN, [0.69], '°C/nm'],
]) {
  test(`C1: ${layer} ${temp} ${op} uses only the applicable displayed bounds`, () => {
    assert.deepEqual(watchStatus({...WATCH, layer, op, a, b}, temp, TZ, true), {...STATUS, op, values, unit});
  });
}

// Validate before showing a condition; invalid ranges must not appear as valid single bounds.
for (const [label, patch] of [
  ['unknown layer', {layer: 'currents'}],
  ['inherited layer key', {layer: 'constructor'}],
  ['unknown op', {op: '>'}],
  ['NaN a', {a: NaN}],
  ['positive infinite a', {a: Infinity}],
  ['negative infinite a', {a: -Infinity}],
  ['missing b', {op: 'between', b: null}],
  ['NaN b', {op: 'between', b: NaN}],
  ['positive infinite b', {op: 'between', b: Infinity}],
  ['negative infinite b', {op: 'between', b: -Infinity}],
  ['equal b', {op: 'between', b: 58}],
  ['descending b', {op: 'between', b: 57}],
]) {
  test(`C1: ${label} returns no status`, () => {
    assert.deepEqual(watchStatus({...WATCH, ...patch}, 'F', TZ, true), null);
  });
}

// A UTC date slice, the timestamp's source day, or a fixed region offset fails these pairs.
for (const [lastSampleAt, day] of [
  ['2026-11-20T07:59:59.999Z', '2026-11-19'],
  ['2026-11-20T08:00:00Z', '2026-11-20'],
  ['2026-11-20T02:59:59-05:00', '2026-11-19'],
  ['2026-11-20T13:30+05:30', '2026-11-20'],
  ['2026-03-08T07:59:59Z', '2026-03-07'],
  ['2026-03-08T08:00:00Z', '2026-03-08'],
  ['2026-03-08T01:59:59-08:00', '2026-03-08'],
  ['2026-03-08T03:00:00-07:00', '2026-03-08'],
  ['2026-03-09T06:59:59Z', '2026-03-08'],
  ['2026-03-09T07:00:00Z', '2026-03-09'],
]) {
  test(`C2: ${lastSampleAt} uses the region's calendar day and the chosen units`, () => {
    assert.deepEqual(watchStatus({...WATCH, lastValue: 57.6, lastSampleAt}, 'C', TZ, true), {
      ...STATUS, values: [14.4], unit: '°C', last: {value: 14.2, day},
    });
  });
}

test('C2: a zero reading is not missing', () => {
  const watch = {...WATCH, layer: 'sst-contrast', a: 2.25, lastValue: 0, lastSampleAt: '2024-02-29T12:00Z'};
  assert.deepEqual(watchStatus(watch, 'C', TZ, true), {
    ...STATUS, values: [1.25], unit: '°C/nm', last: {value: 0, day: '2024-02-29'},
  });
});

// Do not coerce missing readings to zero or let Date accept zone-less or normalized dates.
for (const [label, patch] of [
  ['missing reading', {lastValue: null}],
  ['NaN reading', {lastValue: NaN}],
  ['positive infinite reading', {lastValue: Infinity}],
  ['negative infinite reading', {lastValue: -Infinity}],
  ['missing time', {lastSampleAt: null}],
  ['zone-less time', {lastSampleAt: '2026-11-20T08:00:00'}],
  ['colon-less offset', {lastSampleAt: '2026-11-20T08:00:00-0800'}],
  ['bad time', {lastSampleAt: 'not a time'}],
  ['invalid hour', {lastSampleAt: '2026-11-20T24:00:00Z'}],
  ['invalid offset', {lastSampleAt: '2026-11-20T08:00:00+24:00'}],
  ['invalid month', {lastSampleAt: '2026-13-20T08:00:00Z'}],
  ['nonexistent leap day', {lastSampleAt: '2026-02-29T08:00:00Z'}],
]) {
  test(`C2: ${label} omits only the last reading`, () => {
    const watch = {...WATCH, lastValue: 57.6, lastSampleAt: '2026-11-20T08:00:00Z', ...patch};
    assert.deepEqual(watchStatus(watch, 'F', TZ, true), STATUS);
  });
}

test('C2: an invalid region zone does not silently substitute another zone', () => {
  const watch = {...WATCH, lastValue: 57.6, lastSampleAt: '2026-11-20T08:00:00Z'};
  assert.throws(() => watchStatus(watch, 'F', 'Not/AZone', true), RangeError);
});

// Paused watches keep their reading; missing push only prompts on an enabled watch.
for (const [enabled, pushReady, paused, needsNotifications] of [
  [true, true, false, false],
  [true, false, false, true],
  [false, true, true, false],
  [false, false, true, false],
]) {
  test(`C3: enabled=${enabled}, pushReady=${pushReady} preserves the frozen watch`, () => {
    const watch = Object.freeze({...WATCH, enabled, lastValue: 57.6, lastSampleAt: '2026-11-20T07:59:59Z'});
    assert.deepEqual(watchStatus(watch, 'F', TZ, pushReady), {
      ...STATUS, last: {value: 57.6, day: '2026-11-19'}, paused, needsNotifications,
    });
  });
}

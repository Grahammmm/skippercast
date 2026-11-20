// nearestHour's documented tie rule: the earlier instant wins whatever the input order.
// Fixtures are synthetic.
import assert from 'node:assert/strict';
import test from 'node:test';
import {nearestHour} from '../web/hour.ts';

const LA = 'America/Los_Angeles';
const iso = ms => (ms === null ? null : new Date(ms).toISOString());
const at = s => Date.parse(s);

test('dst_tie_returns_earliest_instant_in_both_orders', () => {
  // 2026-11-01: both 08:00Z and 09:00Z read 1 am in Los Angeles.
  const a = at('2026-11-01T08:00:00Z'), b = at('2026-11-01T09:00:00Z');
  assert.equal(iso(nearestHour([a, b], 1, LA)), '2026-11-01T08:00:00.000Z');
  assert.equal(iso(nearestHour([b, a], 1, LA)), '2026-11-01T08:00:00.000Z');
});

test('ordinary_tie_and_frozen_input', () => {
  // 10 am and noon are equally far from 11 (UTC-8 in January: 18:00Z and 20:00Z).
  const ten = at('2026-01-15T18:00:00Z'), noon = at('2026-01-15T20:00:00Z');
  const reversed = Object.freeze([noon, ten]);
  assert.equal(iso(nearestHour(reversed, 11, LA)), '2026-01-15T18:00:00.000Z');
  assert.deepEqual([...reversed], [noon, ten]);
  assert.equal(iso(nearestHour([ten, noon], 11, LA)), '2026-01-15T18:00:00.000Z');
});

test('empty_singleton_and_unique_nearest', () => {
  const ten = at('2026-01-15T18:00:00Z'), noon = at('2026-01-15T20:00:00Z'), one = at('2026-01-15T21:00:00Z');
  assert.equal(nearestHour([], 1, LA), null);
  assert.equal(nearestHour([one], 3, LA), one);
  assert.equal(nearestHour([one, noon, ten], 12, LA), noon);
  assert.equal(nearestHour([ten, noon, one], 12, LA), noon);
});

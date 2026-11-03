// RF1300-14: feed rows whose hour time is not a finite number are skipped. Synthetic feed hours only.
import assert from 'node:assert/strict';
import test from 'node:test';
import {modelAgreement} from '../web/brief/agreement.ts';

const H = 3_600_000, T0 = Date.parse('2026-10-13T15:00:00Z');
const hour = (ms, {wind = 6, other_wind = wind, sea = 2, other_sea = sea} = {}) => ({ms, hour: {wind, other_wind, sea, other_sea}});
const agreeing = n => Array.from({length: n}, (_, i) => hour(T0 + i * H));

test('a NaN hour time beside agreeing finite hours is not counted: agree, not partial', () => {
  const result = modelAgreement([...agreeing(3), hour(NaN)]);
  assert.equal(result.state, 'agree');
  assert.equal(result.hours, 3);
  assert.equal(result.compared, 3);
  assert.equal(result.differing, 0);
  // NaN row first, in the middle, or differing: still skipped.
  assert.deepEqual(modelAgreement([hour(NaN, {wind: 30}), ...agreeing(3)]), result);
  assert.deepEqual(modelAgreement([hour(T0), hour(NaN, {sea: 9}), hour(T0 + H), hour(T0 + 2 * H)]), result);
});

test('NaN rows never become the worst hour, and are not collapsed into one counted hour', () => {
  const rows = [hour(NaN, {wind: 30, other_wind: 2}), hour(T0, {wind: 12, other_wind: 6}), hour(NaN, {sea: 9, other_sea: 1}), hour(T0 + H)];
  const result = modelAgreement(rows);
  assert.equal(result.worst.ms, T0);
  assert.ok(Number.isFinite(result.worst.ms));
  assert.deepEqual(result.worst, {ms: T0, wind: 6, sea: 0});
  assert.equal(result.differing, 1);
  assert.equal(result.hours, 2);
  assert.equal(result.compared, 2);
  assert.equal(result.state, 'differ');
  assert.deepEqual(result.gap, {wind: 6, sea: 0});
});

test('Infinity and -Infinity hour times are dropped; only non-finite rows read none', () => {
  const withInf = modelAgreement([...agreeing(2), hour(Infinity, {wind: 40}), hour(-Infinity, {sea: 20})]);
  assert.equal(withInf.state, 'agree');
  assert.equal(withInf.hours, 2);
  assert.equal(withInf.compared, 2);
  assert.equal(withInf.differing, 0);
  const none = {state: 'none', hours: 0, compared: 0, differing: 0, gap: null, worst: null};
  assert.deepEqual(modelAgreement([hour(NaN), hour(Infinity), hour(-Infinity), hour(NaN, {wind: 30})]), none);
  assert.deepEqual(modelAgreement([hour(NaN)]), none);
  // Non-number hour times are not real hours either.
  assert.deepEqual(modelAgreement([hour(undefined), hour(null), hour('1')]), none);
});

// The reverse-then-Map rule keeps the row that comes first in input order for a repeated time (behaviour of main, unchanged).
test('duplicate finite hour times collapse to one hour by the unchanged reverse-then-Map rule; empty input reads none', () => {
  const firstDiffers = modelAgreement([hour(T0, {wind: 15, other_wind: 6}), hour(NaN), hour(T0)]);
  assert.equal(firstDiffers.hours, 1);
  assert.equal(firstDiffers.state, 'differ');
  assert.deepEqual(firstDiffers.worst, {ms: T0, wind: 9, sea: 0});
  const firstAgrees = modelAgreement([hour(T0), hour(NaN, {wind: 30}), hour(T0, {wind: 15, other_wind: 6})]);
  assert.equal(firstAgrees.hours, 1);
  assert.equal(firstAgrees.state, 'agree');
  assert.deepEqual(modelAgreement([]), {state: 'none', hours: 0, compared: 0, differing: 0, gap: null, worst: null});
});

test('a finite hour missing the other model reads one-model / partial exactly as before', () => {
  const single = hour(T0);
  delete single.hour.other_wind;
  const oneModel = modelAgreement([single, hour(NaN)]);
  assert.equal(oneModel.state, 'one-model');
  assert.equal(oneModel.hours, 1);
  assert.equal(oneModel.compared, 0);
  assert.equal(oneModel.gap, null);
  assert.equal(oneModel.worst, null);
  const partial = modelAgreement([single, hour(T0 + H), hour(Infinity)]);
  assert.equal(partial.state, 'partial');
  assert.equal(partial.hours, 2);
  assert.equal(partial.compared, 1);
});

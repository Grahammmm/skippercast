// RF1410-1: finite hour times that a Date cannot represent are not observed hours. Synthetic feed hours only.
import assert from 'node:assert/strict';
import test from 'node:test';
import util from 'node:util';
import {modelAgreement} from '../web/brief/agreement.ts';

const H = 3_600_000, T0 = Date.parse('2026-10-13T15:00:00Z'), MAX = 8_640_000_000_000_000;
const hour = (ms, {wind = 6, other_wind = wind, sea = 2, other_sea = sea} = {}) => ({ms, hour: {wind, other_wind, sea, other_sea}});
const NONE = {state: 'none', hours: 0, compared: 0, differing: 0, gap: null, worst: null};
const same = (a, b, msg) => assert.ok(util.isDeepStrictEqual(a, b), msg);

test('out-of-range finite epochs of either sign, alone or together, give the empty result', () => {
  for (const rows of [[hour(1e20)], [hour(-1e20)], [hour(1e20), hour(-1e20, {wind: 40})], [hour(MAX + 1)], [hour(-MAX - 1)], []]) {
    same(modelAgreement(rows), NONE, 'expected the empty-input object');
  }
});

test('non-finite and non-number times stay rejected', () => {
  same(modelAgreement([hour(NaN), hour(Infinity), hour(-Infinity), hour('1793793600000'), hour(null), hour(undefined)]), NONE, 'rejected');
});

test('mixed rows equal the same rows with the impossible epochs removed, in any order', () => {
  const real = [hour(T0, {wind: 12, other_wind: 6}), hour(T0 + H), hour(T0 + 2 * H, {wind: 7, other_wind: 6})];
  const expected = modelAgreement(real);
  assert.equal(expected.state, 'differ');
  const bad = [hour(1e20, {wind: 90, other_wind: 0, sea: 30}), hour(-1e20, {sea: 50, other_sea: 0}), hour(MAX + 1, {wind: 99, other_wind: 0})];
  for (const rows of [[...bad, ...real], [...real, ...bad], [bad[0], real[0], bad[1], real[1], bad[2], real[2]]]) {
    same(modelAgreement(rows), expected, 'must match the valid-only control');
  }
  assert.equal(expected.worst.ms, T0);
});

test('Date endpoints and zero stay eligible; one ms outside each does not', () => {
  const rows = [hour(-MAX), hour(-MAX - 1, {wind: 40}), hour(0), hour(MAX), hour(MAX + 1, {wind: 40})];
  const result = modelAgreement(rows);
  assert.equal(result.hours, 3);
  assert.equal(result.compared, 3);
  assert.equal(result.state, 'agree');
  assert.equal(result.worst.ms, -MAX);
});

test('duplicate precedence, ascending order and tie ordering are unchanged around impossible epochs', () => {
  const rows = [hour(1e20), hour(T0 + H, {wind: 9, other_wind: 6}), hour(T0 + H, {wind: 30, other_wind: 6}), hour(T0, {wind: 9, other_wind: 6})];
  const control = rows.slice(1);
  same(modelAgreement(rows), modelAgreement(control), 'same as without the impossible row');
  const result = modelAgreement(rows);
  assert.equal(result.hours, 2);
  assert.equal(result.worst.ms, T0, 'tie keeps the earlier hour; first duplicate wins');
});

test('incomplete real rows plus bad epochs keep the one-model and partial rules, with no placeholder hours', () => {
  const incomplete = {ms: T0, hour: {wind: 6, other_wind: NaN, sea: 2, other_sea: 2}};
  const oneModel = modelAgreement([hour(1e20), incomplete]);
  assert.equal(oneModel.state, 'one-model');
  assert.equal(oneModel.hours, 1);
  assert.equal(oneModel.compared, 0);
  assert.equal(oneModel.worst, null);
  const partial = modelAgreement([hour(-1e20), incomplete, hour(T0 + H)]);
  assert.equal(partial.state, 'partial');
  assert.equal(partial.hours, 2);
  assert.equal(partial.compared, 1);
});

test('input rows are not mutated', () => {
  const rows = [hour(1e20), hour(T0), hour(-1e20)];
  const copy = structuredClone(rows);
  modelAgreement(rows);
  same(rows, copy, 'rows unchanged');
});

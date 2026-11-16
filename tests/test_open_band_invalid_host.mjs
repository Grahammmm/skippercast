// RF2345-17: openBandPadding refuses a non-finite or degenerate host before any padding maths.
import assert from 'node:assert/strict';
import test from 'node:test';
import {openBandPadding} from '../web/map/open-band.ts';

const HOST = {top: 0, bottom: 844, left: 0, right: 390};
const TOP = {top: 0, bottom: 130, left: 0, right: 390}, SHEET = {top: 611, bottom: 844, left: 0, right: 390};
const ZERO = {top: 0, bottom: 0, left: 0, right: 0};
const COVERS = [TOP, SHEET];

test('nonfinite_host_endpoints_are_zero', () => {
  for (const key of ['top', 'bottom', 'left', 'right']) {
    for (const bad of [NaN, Infinity, -Infinity]) {
      assert.deepEqual(openBandPadding({...HOST, [key]: bad}, COVERS), ZERO, `${key}=${bad}`);
    }
  }
  assert.deepEqual(openBandPadding({...HOST, left: 100, right: 100}, COVERS), ZERO);
});

test('zero_and_reversed_dimensions_are_zero', () => {
  const hosts = [{...HOST, right: 0}, {...HOST, right: -10}, {...HOST, bottom: 0}, {...HOST, bottom: -10}];
  for (const h of hosts) for (const covers of [COVERS, [TOP], [SHEET]]) assert.deepEqual(openBandPadding(h, covers), ZERO, JSON.stringify(h));
});

test('finite_endpoints_with_overflow_are_zero', () => {
  const M = Number.MAX_VALUE;
  assert.deepEqual(openBandPadding({top: -M, bottom: M, left: 0, right: 390}, COVERS), ZERO);
  assert.deepEqual(openBandPadding({top: 0, bottom: 844, left: -M, right: M}, COVERS), ZERO);
});

test('valid_host_parity', () => {
  assert.deepEqual(openBandPadding(HOST, COVERS), {top: 130, bottom: 233, left: 0, right: 0});
  assert.deepEqual(openBandPadding({top: 50, bottom: 894, left: 0, right: 390}, [{...TOP, top: 50, bottom: 180}, {...SHEET, top: 661, bottom: 894}]), {top: 130, bottom: 233, left: 0, right: 0});
  assert.deepEqual(openBandPadding(HOST, [{...TOP, right: 195}]), {...ZERO, top: 130}, 'exact half width');
  assert.deepEqual(openBandPadding(HOST, [{...TOP, top: 8}]), {...ZERO, top: 130}, 'edge distance 8');
  assert.deepEqual(openBandPadding(HOST, [{...TOP, top: 9}]), ZERO, 'edge distance 9');
  assert.deepEqual(openBandPadding(HOST, [{...SHEET, top: 0}]), ZERO, 'full height');
  assert.deepEqual(openBandPadding(HOST, [TOP, TOP, TOP]), {...ZERO, top: 130}, 'repeated');
  assert.deepEqual(openBandPadding(HOST, [{...TOP, bottom: 400}, {...SHEET, top: 444}]), {...ZERO, top: 342, bottom: 342}, 'shrink');
  assert.deepEqual(openBandPadding({...HOST, bottom: 160}, [{...TOP, bottom: 10}]), {...ZERO, top: 0 + 0}, 'height equals minBand');
  assert.deepEqual(openBandPadding({...HOST, bottom: 159}, [TOP]), ZERO, 'below minBand');
});

test('pure_and_recoverable', () => {
  const host = Object.freeze({...HOST}), covers = Object.freeze([Object.freeze({...TOP}), Object.freeze({...SHEET})]);
  assert.deepEqual(openBandPadding(Object.freeze({...HOST, left: NaN}), covers), ZERO);
  const out = openBandPadding(host, covers);
  assert.deepEqual(out, {top: 130, bottom: 233, left: 0, right: 0});
  for (const v of Object.values(out)) assert.ok(Number.isInteger(v) && v >= 0);
});

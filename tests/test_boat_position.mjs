import test from 'node:test';
import assert from 'node:assert/strict';
import {targetVector} from '../dist/boat-position.js';

test('phone-to-target distance uses nautical miles and true bearing', () => {
  const east = targetVector({latitude:35, longitude:-121}, {latitude:35, longitude:-120.9});
  assert.ok(east.distanceNm > 4.9 && east.distanceNm < 5.0);
  assert.ok(east.bearingTrue > 89 && east.bearingTrue < 91);
  const north = targetVector({latitude:35, longitude:-121}, {latitude:35.1, longitude:-121});
  assert.ok(north.distanceNm > 5.9 && north.distanceNm < 6.1);
  assert.equal(north.bearingTrue, 0);
});

test('invalid coordinates cannot produce a displayed bearing', () => {
  assert.equal(targetVector({latitude:91, longitude:0}, {latitude:35, longitude:-121}), null);
  assert.equal(targetVector({latitude:35, longitude:0}, {latitude:NaN, longitude:-121}), null);
});

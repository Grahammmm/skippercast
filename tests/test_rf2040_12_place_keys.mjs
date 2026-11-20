import test from 'node:test';
import assert from 'node:assert/strict';
import {habitatPlace, reportAreaPlace} from '../packages/coast/src/coast3d/places.ts';

const inherited = ['constructor', 'toString', 'hasOwnProperty', 'valueOf', '__proto__'];

test('place_maps_reject_inherited_keys', () => {
  for (const key of inherited) {
    assert.equal(habitatPlace(key, -121, 35.45), 'coast', key);
    assert.equal(reportAreaPlace(key), 'coast', key);
  }
});

test('place_maps_empty_and_unknown_boundary', () => {
  assert.equal(habitatPlace('', -121, 35.45), 'coast');
  assert.equal(habitatPlace('invented', -121, 35.45), 'coast');
  assert.equal(reportAreaPlace(''), 'coast');
  assert.equal(reportAreaPlace('invented'), 'coast');
  for (const [lon, lat] of [[NaN, 35.45], [Infinity, 35.45], [-Infinity, 35.45], [-121, NaN], [-121, Infinity], [-121, -Infinity]]) {
    assert.equal(habitatPlace('morro-bay', lon, lat), 'coast');
  }
});

test('place_maps_healthy_controls_preserved', () => {
  assert.equal(reportAreaPlace('north'), 'cambria');
  assert.equal(reportAreaPlace('central'), 'morro');
  assert.equal(reportAreaPlace('south'), 'avila');
  assert.equal(habitatPlace('morro-bay', -121, 35.45), 'morro');
  assert.equal(habitatPlace('monterey-point-sur', -121.94, 36.32), 'point-sur');
  assert.equal(habitatPlace('monterey-point-sur', -121.96, 36.52), 'carmel');
  assert.equal(habitatPlace('point-arguello-conception', -120.47, 34.455), 'conception');
});

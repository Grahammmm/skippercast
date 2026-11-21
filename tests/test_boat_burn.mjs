import assert from 'node:assert/strict';
import test from 'node:test';
import {boatFactors, normalizeBoat} from '../dist/boat-handling.js';
import {parseResponse} from '../server/boat-lookup.ts';

// Strict bounds or lost string coercion would drop valid manual entries.
test('normalization keeps finite burn rates at and between both limits', () => {
  for (const [input, expected] of [[0.5, 0.5], [8.75, 8.75], [200, 200], ['0.5', 0.5], [' 8.75 ', 8.75], ['200', 200]]) {
    assert.equal(normalizeBoat({burn_gph: input}).burn_gph, expected, String(input));
  }
});

// Clamping, accepting non-finite values, or serializing a null key defeats opt-in.
test('normalization omits invalid burn rates', () => {
  for (const input of [undefined, null, '', ' ', 'unknown', 'NaN', 'Infinity', NaN, Infinity, -Infinity,
    -1, 0, 0.499, 200.001, '-1', '0.499', '200.001']) {
    assert.equal(Object.hasOwn(normalizeBoat({burn_gph: input}), 'burn_gph'), false, String(input));
  }
});

// A new default key would change persisted JSON even when the owner never opted in.
test('a legacy profile without a burn rate normalizes to the same JSON bytes', () => {
  const boat = {name: ' Ruby ', loa_ft: '23', dry_weight_lb: 3000, deadrise_deg: 20, fuel_gal: '70'};
  assert.equal(JSON.stringify(normalizeBoat(boat)),
    '{"name":"Ruby","loa_ft":23,"beam_ft":null,"displacement_lb":3900,"dry_weight_lb":3000,' +
    '"deadrise_deg":20,"cruise_kn":null,"max_hp":null,"fuel_gal":70,"hull":"deep-v","layout":null}');
});

// A fuel estimate input must not change the boat's comfort or control thresholds.
test('burn rate is not a boat handling factor', () => {
  const boat = {loa_ft: 19, displacement_lb: 2400, hull: 'modified-v', layout: 'center-console'};
  assert.deepEqual(boatFactors({...boat, burn_gph: 200}), boatFactors(boat));
});

// Passing the model's raw object to the shared normalizer would accept a manual-only value.
test('boat lookup ignores a model-supplied burn rate and its estimated flag', () => {
  const raw = {name: 'Synthetic boat', loa_ft: 23, fuel_gal: 70, burn_gph: 9, estimated: ['burn_gph', 'fuel_gal']};
  const {boat, estimated} = parseResponse({content: [{type: 'text', text: JSON.stringify(raw)}]});
  assert.equal(boat.fuel_gal, 70);
  assert.equal(Object.hasOwn(boat, 'burn_gph'), false);
  assert.deepEqual(estimated, ['fuel_gal']);
});

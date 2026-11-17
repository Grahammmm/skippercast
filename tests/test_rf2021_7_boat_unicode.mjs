// RF2021-7: float-plan boat label truncation stays on a Unicode boundary. Synthetic values only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {boatLine, seedFloatPlan, validateFloatPlan, BOAT_MAX} from '../web/float-plan.ts';

const EMOJI = '\u{1F600}';

test('truncation_does_not_split_supplementary_character', () => {
  const out = boatLine({name: 'a'.repeat(159) + EMOJI});
  assert.equal(out, 'a'.repeat(159));
  assert.ok(out.length <= BOAT_MAX);
  assert.ok(out.isWellFormed());
});

test('exact_fit_pair_is_kept', () => {
  const name = 'a'.repeat(158) + EMOJI;
  const out = boatLine({name});
  assert.equal(out.length, BOAT_MAX);
  assert.ok(out === name && out.isWellFormed());
});

test('ordinary_seed_and_length_contracts_stay_unchanged', () => {
  assert.equal(boatLine({name: 'Sea Finch', loa_ft: 24}), 'Sea Finch · 24 ft');
  assert.equal(boatLine(null), '');
  assert.equal(boatLine({name: 'Sea Finch', loa_ft: NaN}), 'Sea Finch');
  const long = boatLine({name: 'a'.repeat(158) + EMOJI + EMOJI, loa_ft: 30});
  assert.ok(long.length <= BOAT_MAX && long.isWellFormed());
  const seed = seedFloatPlan({boat: {name: 'a'.repeat(159) + EMOJI}, brief: null, shown: null, region: {id: 'r', timezone: 'America/Los_Angeles'}, date: '2026-07-01'});
  assert.ok(seed.fields.boat.isWellFormed());
  const v = validateFloatPlan(seed.fields, '2026-07-01', 'America/Los_Angeles');
  assert.equal(v.ok, true);
});

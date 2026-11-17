import test from 'node:test';
import assert from 'node:assert/strict';

const {targetFor, strategyFor, PUBLIC_GROUNDS, publicAreas} = await import('../server/advisor/answers/advice.ts');

test('strategy_rejects_inherited_target_names', () => {
  for (const key of ['constructor', 'toString', '__proto__', 'hasOwnProperty', 'valueOf']) {
    assert.equal(targetFor(key), null, key);
    assert.doesNotThrow(() => strategyFor(key, 'socal'), key);
    assert.equal(strategyFor(key, 'socal'), null, key);
  }
});

test('strategy_unknown_and_empty_boundary', () => {
  for (const key of ['', 'invented-rf2040']) {
    assert.equal(targetFor(key), null);
    assert.equal(strategyFor(key, 'socal'), null);
  }
});

test('strategy_catalog_parent_and_group_control', () => {
  const region = Object.keys(PUBLIC_GROUNDS).find(r => publicAreas(r, 'lingcod').length > 0);
  assert.ok(region, 'a region with public lingcod grounds');
  for (const key of ['lingcod', 'rockfish', 'vermilion']) {
    const target = targetFor(key);
    assert.ok(target, `${key} keeps a target`);
    const s = strategyFor(key, region);
    assert.ok(s, `${key} keeps a strategy`);
    assert.equal(s.species_key, key);
    assert.equal(s.target, target);
    assert.equal(s.region, region);
    assert.deepEqual(s.areas, publicAreas(region, key));
  }
  assert.equal(targetFor('lingcod'), 'reef');
  assert.equal(targetFor('vermilion'), 'reef');
  assert.equal(targetFor('reef'), 'reef');
  assert.ok(strategyFor('lingcod', region).areas.length > 0);
});

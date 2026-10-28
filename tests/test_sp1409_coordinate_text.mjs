import test, {beforeEach, afterEach, after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {install, restore, attempts} from './fixtures/sp1409_coordinate_text/offline-bootstrap.mjs';

// Guards are active before this dynamic import of the complete real module.
const advice = await import('../server/advisor/answers/advice.ts');
const fixture = JSON.parse(readFileSync(new URL('./fixtures/sp1409_coordinate_text/cases.json', import.meta.url)));
assert.deepEqual(attempts, [], 'product import is offline');
beforeEach(() => install());
afterEach(() => {
  try { assert.deepEqual(attempts, [], 'no network/model/persistent-storage calls'); }
  finally { restore(); }
});
after(() => restore());

test('primary regression', () => {
  assert.equal(advice.publicOnly(fixture.primary.input), fixture.primary.expected, 'SP1409_PRIMARY_SEMANTIC_MISMATCH');
});
test('healthy control', () => {
  assert.equal(advice.publicOnly(fixture.healthy.input), fixture.healthy.expected);
});

// Baseline registers EXACTLY the same pair above, not skipped/deselected tests.
if (process.env.SP1409_SUITE !== 'baseline') {
  test('A1 coordinate grammar variants drop the sentence without replacement', () => {
    for (const coordinate of fixture.coordinates) {
      assert.equal(advice.publicOnly(`${coordinate} Use a slow drift.`), 'Use a slow drift.', coordinate);
      assert.equal(advice.publicOnly(coordinate), null, coordinate);
    }
  });
  test('A2 ordinary fishing units clock dimensions and bounded tokens survive', () => {
    for (const text of fixture.ordinary) assert.equal(advice.publicOnly(text), text, text);
  });
  test('A3 publicOnly preserves order and null-on-empty behavior', () => {
    assert.equal(advice.publicOnly(fixture.ordering.input), fixture.ordering.expected);
    for (const text of [null, undefined, '', '   ']) assert.equal(advice.publicOnly(text), null);
    assert.equal(advice.publicOnly('Fish at 35 10 N. Fish at 120 49 W.'), null);
    assert.equal(advice.publicOnly(' Keep the first sentence.  Keep the last sentence! '), fixture.ordering.expected);
  });
  test('A3 publicAreas keeps committed public catalog and excludes invented grounds', () => {
    const areas = advice.publicAreas('morro-bay', 'lingcod', fixture.excluded_names);
    assert.deepEqual(areas.map(a => a.name), fixture.public_areas);
    assert.deepEqual(areas.map(a => a.general_depth_ft), [[25, 125], [25, 195], [25, 195]]);
    assert.deepEqual(advice.publicAreas('southern-california', 'lingcod', ['Pecho Rock']), []);
    assert.deepEqual(advice.publicAreas('morro-bay', 'halibut'), []);
    assert.equal(advice.publicAreas('morro-bay', 'lingcod', ['Diablo coast'])[0].name, 'Diablo coast');
    for (const area of areas) assert.equal(advice.publicOnly(area.description), area.description);
  });
  test('A3 strategyFor retains unchanged catalog strategy and null controls', () => {
    const strategy = advice.strategyFor('lingcod', 'morro-bay', fixture.excluded_names);
    assert.equal(strategy.species_key, 'lingcod');
    assert.equal(strategy.target, 'reef');
    assert.match(strategy.rig, /dropper-loop/);
    assert.match(strategy.bait_or_lure, /swimbait/);
    assert.equal(strategy.line, null);
    assert.deepEqual(strategy.depth_band_ft, [25, 195]);
    assert.deepEqual(strategy.areas.map(a => a.name), fixture.public_areas);
    assert.ok(strategy.source_notes.length);
    for (const name of fixture.excluded_names) assert.ok(!JSON.stringify(strategy).includes(name));
    assert.equal(advice.strategyFor('invented-sp1409-species', 'morro-bay'), null);
    assert.deepEqual(advice.strategyFor('halibut', 'morro-bay').areas, []);
  });
}

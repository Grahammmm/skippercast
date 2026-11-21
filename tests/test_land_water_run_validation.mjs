import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {landWaterModel, placeOf} from '../web/land-water.ts';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/sp1503_land_water_retry/products.json', import.meta.url), 'utf8'));
const modelFromRuns = runs => landWaterModel({
  ...fixture.index,
  constants: {...fixture.index.constants, grid: 2},
  tiles: {'0/0/0': runs},
}, fixture.region);

// A repeat-first decoder can throw before it checks the four-cell budget.
// In a later run, even a count that fits the whole grid can exceed the remaining cells.
for (const [label, runs] of [
  ['later run exceeds the remaining cells', 'w2l4'],
  ['oversized finite count', `w${Number.MAX_SAFE_INTEGER}`],
  ['unsafe integer count', 'w9007199254740993'],
  ['non-finite count', `w${'9'.repeat(310)}`],
  ['zero count', 'w2m0l2'],
]) {
  test(`rejects ${label} with no model or exception`, () => {
    assert.equal(modelFromRuns(runs), null);
  });
}

// A matcher that skips unmatched characters can recover four cells from corrupt input.
for (const [label, runs] of [
  ['leading junk', '?w2l2'],
  ['junk between runs', 'w2?l2'],
  ['trailing junk', 'w2l2?'],
  ['newline before the next run', 'w2\nl2'],
  ['trailing newline', 'w2l2\n'],
  ['line separator before the first run', '\u2028w2l2'],
  ['missing count', 'w4m'],
]) {
  test(`rejects ${label} even if the decoded length would be correct`, () => {
    assert.equal(modelFromRuns(runs), null);
  });
}

test('mixed runs exactly fill the grid and the first cell still classifies as water', () => {
  const model = modelFromRuns('w2m1l1');
  assert.ok(model);
  assert.equal(model.tiles.get('0/0/0'), 'wwml');
  assert.deepEqual(placeOf(model, null, fixture.points.water), {state: 'water'});
});

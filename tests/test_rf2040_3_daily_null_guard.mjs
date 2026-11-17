// RF2040-3: validDailyFeed is a total boolean guard over unvalidated upstream JSON.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
Object.assign(globalThis, {DEPLOYMENT: read('../deployments/production.json'), SHELLS: {}, BUILD_ID: 'b1'});
const {validDailyFeed} = await import('../server/routes/public.ts');

const feed = extra => ({schema_version: 1, generated_at: '2026-10-08T12:00:00Z', sources: {}, reports: [], health: {ok: 1},
  catch_probability: null, bite_score: null, ...extra});
const OTHER = 'synthetic-other';

test('daily_guard_nullish_is_false', () => {
  for (const bad of [null, undefined]) {
    for (const id of ['morro-bay', OTHER]) assert.strictEqual(validDailyFeed(bad, id), false);
  }
});

test('daily_guard_top_level_shape_boundary', () => {
  for (const bad of [{}, [], '', 'x', true, false, 0, 7]) {
    for (const id of ['morro-bay', OTHER]) assert.strictEqual(validDailyFeed(bad, id), false);
  }
  const legacy = feed({});
  assert.strictEqual(validDailyFeed(legacy, 'morro-bay'), true);
  assert.strictEqual(validDailyFeed(legacy, OTHER), false);
});

test('daily_guard_healthy_control', () => {
  const good = feed({region_id: 'monterey-point-sur'});
  const before = structuredClone(good);
  assert.strictEqual(validDailyFeed(good, 'monterey-point-sur'), true);
  assert.strictEqual(validDailyFeed(good, 'morro-bay'), false);
  assert.deepStrictEqual(good, before);
  assert.strictEqual(validDailyFeed({...good, schema_version: 2}, 'monterey-point-sur'), false);
  assert.strictEqual(validDailyFeed({...good, sources: []}, 'monterey-point-sur'), false);
  assert.strictEqual(validDailyFeed({...good, catch_probability: 0.5}, 'monterey-point-sur'), false);
});

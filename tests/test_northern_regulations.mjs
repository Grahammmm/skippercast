// Northern PC-5b: real committed rules; synthetic freshness only for future cases.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {regulationState} from '../web/regs.ts';

const read = path => JSON.parse(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
const original = read('dist/data/regulations-northern.json');
const regions = ['crescent-city', 'humboldt-bay-cape-mendocino', 'trinidad-klamath']
  .map(id => read(`dist/regions/${id}/region.json`));
const at = Date.parse(original.checked_at);
function freshAt(time) {
  const data = structuredClone(original);
  for (const check of Object.values(data.checks)) check.data_retrieved_at = new Date(time).toISOString();
  return data;
}

test('all three Northern packages keep closed KMZ salmon and conditional crab', () => {
  for (const region of regions) {
    assert.equal(regulationState(original, 'salmon', region, at).status, 'closed');
    assert.equal(regulationState(original, 'dungeness', region, at).status, 'closed');
    assert.equal(regulationState(original, 'halibut', region, at).status, 'open');
    assert.equal(regulationState(original, 'reef', region, at).status, 'open');
    const november = Date.parse('2026-11-07T20:00:00Z');
    assert.equal(regulationState(freshAt(november), 'dungeness', region, november).status, 'scheduled');
  }
  assert.equal(original.species.dungeness.methods.trap.requires_clearance, true);
});

test('Pacific halibut ends November 15 and a quota-source change withholds open sooner', () => {
  for (const region of regions) {
    for (const [date, expected] of [['2026-11-15T20:00:00Z', 'open'], ['2026-11-16T08:00:00Z', 'closed']]) {
      const time = Date.parse(date);
      assert.equal(regulationState(freshAt(time), 'pacific-halibut', region, time).status, expected);
    }
    const changed = structuredClone(original);
    changed.checks['rules-pacific-halibut'].status = 'changed';
    assert.equal(regulationState(changed, 'pacific-halibut', region, at).status, 'unknown');
    assert.equal(regulationState(changed, 'halibut', region, at).status, 'open');
  }
});

test('shared holds, failures and stale checks withhold species in both neighbors too', () => {
  for (const region of regions) {
    for (const mutate of [
      d => d.sources['rules-proposals'].approved_content_sha256 = null,
      d => d.checks['rules-proposals'].status = 'changed',
      d => d.checks['rules-proposals'].source_status = 'failed',
      d => d.checks['rules-proposals'].data_retrieved_at = new Date(at - 37 * 3600000).toISOString(),
    ]) {
      const data = structuredClone(original);
      mutate(data);
      for (const species of Object.keys(data.species)) {
        const state = regulationState(data, species, region, at);
        assert.equal(state.status, 'unknown');
        assert.ok(state.issues.includes('rules-proposals'));
      }
    }
  }
});

test('expired registry cannot authorize 2027 despite fresh source checks', () => {
  const time = Date.parse('2027-01-01T08:00:00Z');
  for (const region of regions) {
    for (const species of Object.keys(original.species)) {
      assert.equal(regulationState(freshAt(time), species, region, time).status, 'unknown');
    }
  }
});

test('new package has no search or fishing geometries, even after legal review', () => {
  const region = regions.find(r => r.id === 'trinidad-klamath');
  assert.equal(region.status, 'preview');
  const atlas = read(`dist/${region.assets.atlas}`);
  for (const key of ['targets', 'areas', 'drifts']) assert.deepEqual(atlas[key], []);
  assert.deepEqual(read(`dist/${region.assets.search_plans}`).features, []);
});

// SC2184-03 policy-A (G, 2026-11-12), on the committed California Central registry with synthetic freshness:
// in-season notices and the booklet block every species; the health page blocks only Dungeness crab;
// the proposals page is an "also check" link and blocks nothing.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {regulationState} from '../web/regs.ts';

const read = path => JSON.parse(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
const registry = read('dist/data/regulations.json');
const region = read('dist/regions/morro-bay/region.json');
const SPECIES = ['lingcod', 'rockfish', 'halibut', 'salmon', 'albacore', 'bluefin', 'dungeness'];
const NOW = Date.parse('2026-11-20T20:00:00Z');

/** The registry as it would read right after a human-approved apply: every source unchanged and fresh. */
function approved() {
  const data = structuredClone(registry);
  data.rules_review_status = 'reviewed';
  data.reviewed_at = '2026-11-20T08:00:00Z';
  data.checks = {};
  for (const [id, source] of Object.entries(data.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    data.checks[id] = {status: 'unchanged', source_status: 'ok', url: source.url, normalization: source.normalization,
      content_sha256: 'a'.repeat(64), data_retrieved_at: '2026-11-20T18:00:00Z', checked_at: '2026-11-20T18:00:00Z'};
  }
  return data;
}
const edited = id => { const data = approved(); data.checks[id].status = 'changed'; data.checks[id].content_sha256 = 'b'.repeat(64); return data; };
const statuses = data => Object.fromEntries(SPECIES.map(s => [s, regulationState(data, s, region, NOW).status]));

test('baseline: with every source approved, species show a season status, not "Check rules"', () => {
  const base = statuses(approved());
  assert.deepEqual(base, {lingcod: 'open', rockfish: 'open', halibut: 'open', salmon: 'closed', albacore: 'open', bluefin: 'open', dungeness: 'restricted'});
});

test('an edit to the proposals page removes no species\' season status', () => {
  const base = statuses(approved()), after = statuses(edited('rules-proposals'));
  assert.deepEqual(after, base);
  for (const s of SPECIES) assert.deepEqual(regulationState(edited('rules-proposals'), s, region, NOW).issues, []);
});

test('an edit to the health-advisory page affects only Dungeness crab', () => {
  const base = statuses(approved()), after = statuses(edited('rules-health'));
  assert.equal(after.dungeness, 'unknown');
  assert.ok(regulationState(edited('rules-health'), 'dungeness', region, NOW).issues.includes('rules-health'));
  for (const s of SPECIES.filter(s => s !== 'dungeness')) assert.equal(after[s], base[s], s);
});

test('an edit to the in-season notices page still blocks every species', () => {
  const after = statuses(edited('rules-inseason'));
  for (const s of SPECIES) assert.equal(after[s], 'unknown', s);
});

test('an edit to the regulations booklet still blocks every species (shared dependency, unchanged by policy-A)', () => {
  const after = statuses(edited('rules-book'));
  for (const s of SPECIES) assert.equal(after[s], 'unknown', s);
});

test('proposals and health stay visible as also-check links; no species blocks on proposals', () => {
  for (const s of SPECIES) {
    const p = registry.species[s];
    assert.ok(!p.source_ids.includes('rules-proposals'), s);
    assert.ok(p.also_check_source_ids.includes('rules-proposals'), s);
    assert.equal(p.source_ids.includes('rules-health'), s === 'dungeness', s);
    for (const id of p.also_check_source_ids) assert.ok(registry.sources[id].url, `${s} ${id}`);
  }
});

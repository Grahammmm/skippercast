// SC-LAUNCH-2: a rules card says when its sources were last checked against CDFW, links the species' own
// CDFW page beside the place's page, and calls a check stale by the registry's OWN max_age_hours.
// Provenance and freshness only: no rule, limit, season or boundary value is read differently or edited.
// Timestamp source: the daily feed's regulations.checks[<source>].data_retrieved_at (scripts/refresh_regions.py
// -> regulation_review.coverage -> regulatory_snapshot), reduced by ruleSummary to the species' oldest source.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const {regulationState, ruleSummary, speciesPage, verifiedText} = await import('../web/regs.ts');
const fixture = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const REGION = fixture.region, HOUR = 3600000;
const NOW = Date.parse('2026-09-21T18:00:00Z');

function data(at = NOW) {
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(at - HOUR).toISOString();
  d.rules_review_status = 'reviewed';
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: new Date(at).toISOString()};
  }
  return d;
}
const row = (d, species, at = NOW) => { const state = regulationState(d, species, REGION, at); return {state, summary: ruleSummary(d, species, state, REGION)}; };

test('a check inside the registry max_age_hours renders Verified with its date', () => {
  const r = row(data(), 'salmon');
  assert.equal(verifiedText(r.summary), 'Verified Sep 21');
});

test('a check older than the registry\'s own max_age_hours renders stale, not Verified', () => {
  const d = data(); d.max_age_hours = 24;
  for (const check of Object.values(d.checks)) check.data_retrieved_at = new Date(NOW - 30 * HOUR).toISOString();
  const r = row(d, 'salmon');
  assert.equal(r.state.status, 'unknown');
  assert.match(r.state.reason, /over 24 hours old/);
  assert.equal(r.summary.verified, null);
  assert.equal(verifiedText(r.summary), 'Needs recheck · last check Sep 20');
});

test('a registry cannot loosen the 36 h gate', () => {
  const d = data(); d.max_age_hours = 72;
  for (const check of Object.values(d.checks)) check.data_retrieved_at = new Date(NOW - 40 * HOUR).toISOString();
  assert.equal(row(d, 'salmon').summary.verified, null);
});

test('a species with its own reviewed CDFW page links it beside the place page', () => {
  const d = data();
  const salmon = speciesPage(d, 'salmon', REGION);
  assert.equal(salmon.href, d.sources['rules-salmon'].url);
  assert.equal(salmon.label, `Official ${d.species.salmon.name} rules`);
  assert.equal(row(d, 'salmon').summary.link, d.sources['rules-central'].url, 'the place page is kept');
  assert.equal(speciesPage(d, 'dungeness', REGION).href, d.sources['rules-crab'].url);
  assert.equal(speciesPage(d, 'lingcod', REGION).href, d.sources['rules-groundfish'].url);
  assert.equal(speciesPage(d, 'albacore', REGION), null, 'no species page in the registry: no invented link');
  assert.equal(speciesPage(null, 'salmon', REGION), null);
});

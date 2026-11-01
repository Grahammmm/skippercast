// SC-LAUNCH-2: a rules card says when its sources were last checked against CDFW, links the species' own
// CDFW page beside the place's page, and calls a check stale by the registry's OWN max_age_hours.
// Provenance and freshness only: no rule, limit, season or boundary value is read differently or edited.
// Timestamp source: the daily feed's regulations.checks[<source>].data_retrieved_at (scripts/refresh_regions.py
// -> regulation_review.coverage -> regulatory_snapshot), reduced by ruleSummary to the species' oldest source.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const {areaPageOnly, regulationState, ruleSummary, speciesPage, verifiedText} = await import('../web/regs.ts');
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
  assert.equal(verifiedText(r.summary), 'Not confirmed for your fishing date - open the official rules before you go.');
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
  assert.equal(speciesPage(d, 'albacore', REGION).href, d.sources['rules-tuna-federal'].url, 'the tunas link the reviewed federal rule');
  assert.equal(speciesPage(d, 'bluefin', REGION).href, d.sources['rules-tuna-federal'].url);
  assert.equal(speciesPage(d, 'halibut', REGION), null, 'California halibut has no dedicated reviewed page: no invented link');
  assert.equal(speciesPage(null, 'salmon', REGION), null);
});

test('the committed registry: 24 h interval, 36 h ceiling - a 30 h check is overdue, still gated open, and says so', () => {
  const d = data();
  assert.equal(d.check_interval_hours, 24); assert.equal(d.max_age_hours, 36);
  for (const check of Object.values(d.checks)) check.data_retrieved_at = new Date(NOW - 30 * HOUR).toISOString();
  const r = row(d, 'salmon');
  assert.notEqual(r.state.status, 'unknown', 'inside the 36 h ceiling the rule itself is not withheld');
  assert.equal(r.summary.verified, null, 'overdue is not Verified');
  assert.equal(verifiedText(r.summary), 'Not confirmed for your fishing date - open the official rules before you go.');
  const reef = row(d, 'reef'); assert.equal(reef.summary.verified, null);
});

test('a 1 h check is Verified; a 40 h check is withheld by the 36 h ceiling', () => {
  const d = data();
  for (const check of Object.values(d.checks)) check.data_retrieved_at = new Date(NOW - HOUR).toISOString();
  assert.equal(verifiedText(row(d, 'salmon').summary), 'Verified Sep 21');
  for (const check of Object.values(d.checks)) check.data_retrieved_at = new Date(NOW - 40 * HOUR).toISOString();
  assert.equal(row(d, 'salmon').state.status, 'unknown');
});

test('every card links the place page; species pages exist exactly where the registry lists one', () => {
  const d = data(), got = {};
  for (const id of REGION.species) { const s = row(d, id).summary; assert.ok(s.link.startsWith('https://'), id); got[id] = speciesPage(d, id, REGION)?.href ?? null; }
  assert.deepEqual(Object.keys(got).filter(id => got[id] === null).sort(), ['halibut', 'reef'].filter(id => REGION.species.includes(id)).sort());
});

test('a species with only the area page says so; species pages and the groundfish page do not', () => {
  const d = data();
  const only = id => areaPageOnly(row(d, id).summary, speciesPage(d, id, REGION));
  assert.equal(only('halibut'), true, 'halibut has only the area page');
  assert.equal(only('salmon'), false);
  assert.equal(only('lingcod'), false);
  if (REGION.species.includes('reef')) assert.equal(only('reef'), false, 'reef links the groundfish page');
});

test('committed San Francisco halibut: the area-page note names the area page, never the groundfish summary', () => {
  const sf = JSON.parse(readFileSync(new URL('../regions/bodega-point-reyes/region.json', import.meta.url)));
  const d = JSON.parse(readFileSync(new URL('../dist/' + sf.assets.regulations.replace(/^\//, ''), import.meta.url)));
  const state = regulationState(d, 'halibut', sf), s = ruleSummary(d, 'halibut', state, sf);
  assert.match(s.link, /\/Fishing-Map\/San-Francisco$/);
  assert.equal(areaPageOnly(s, speciesPage(d, 'halibut', sf)), true);
  const reef = ruleSummary(d, 'reef', regulationState(d, 'reef', sf), sf);
  assert.match(reef.link, /Groundfish-Summary$/);
  assert.equal(areaPageOnly(reef, null), false, 'a non-area link never claims to be the area page');
});

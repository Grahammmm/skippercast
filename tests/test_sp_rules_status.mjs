// SP-RULES-STATUS: the captain card's rules line never shows a "Verified" badge while
// web/regs.ts `regulationState` reads unknown. ruleSummary used to set `verified`
// from an empty source-issue list and the reviewed flag alone, so a fresh, reviewed
// registry read on a date outside its rule period, with a review time beyond the
// future tolerance, or for a season that needs a fishing location, said
// "Verified <date>" next to "Check rules". The verified date is a source-check
// statement only, never clearance to fish.
//
// Every case runs the real state and summary functions over the frozen FE-61 registry
// (tests/fixtures/regulations/fe61-v1.json, as tests/test_regs_wrapper.mjs reads it)
// with synthetic fresh source checks and a frozen clock. No legal rule, date window,
// source hash, freshness threshold, geography check or wording is edited here or in
// web/regs.ts. A network-failure sentinel is installed before the module loads.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test, {after} from 'node:test';

const realFetch = globalThis.fetch;
let fetchCalls = 0;
globalThis.fetch = async (...args) => { fetchCalls += 1; throw new Error(`network is not available in this test: ${String(args[0])}`); };
const {CDFW_OCEAN, firstClause, depthLimit, officialURL, regulationState, ruleProfile, ruleSummary, verifiedText} = await import('../web/regs.ts');
after(() => { globalThis.fetch = realFetch; });

const fixture = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const MORRO = fixture.region;
const ORIGINAL = fixture.regulations;
const HOUR = 3600000;
// Frozen clock: 11:00 PDT on the registry's first valid day (valid_from 2026-09-21, valid_through 2026-12-31).
const NOW = Date.parse('2026-09-21T18:00:00Z');

/** The frozen registry, reviewed an hour ago, every source checked unchanged at `at` (tests/test_regs_wrapper.mjs's builder). */
function data(at = NOW) {
  const d = structuredClone(ORIGINAL);
  d.reviewed_at = new Date(at - HOUR).toISOString();
  d.rules_review_status = 'reviewed';
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: new Date(at).toISOString()};
  }
  return d;
}
/** A synthetic latitude band on `species`' window, citing one of its own sources (as the wrapper's `edited`). */
function banded(d, species) {
  const p = d.species[species];
  p.windows = p.windows.map(w => ({...w, geography: {kind: 'latitude-band', south: 34.5, north: 36, source_id: p.source_ids[0], note: 'Synthetic band.'}}));
  return d;
}
const row = (d, species, at = NOW, tripDate = null, tripInstant = null) => {
  const state = regulationState(d, species, MORRO, at, tripDate, tripInstant);
  return {state, summary: ruleSummary(d, species, state, MORRO)};
};
/** The registry's own first clauses, named for the combined reef row, exactly as ruleSummary cuts them. */
function limits(d, species) {
  const ids = species === 'reef' ? ['lingcod', 'rockfish'] : [species], named = ids.length > 1;
  const pick = key => ids.map(id => [d.species[id].name, firstClause(d.species[id][key])]).filter(([, t]) => t).map(([n, t]) => named ? `${n}: ${t}` : t);
  return {bag: pick('bag'), size: pick('size')};
}
/** The reviewed source's official page the row links (unchanged by this fix). */
function link(d, species) {
  const p = d.species[species === 'reef' ? 'lingcod' : species];
  const primary = species === 'reef' ? 'rules-groundfish' : p.primary_source_id || p.source_ids[0];
  return officialURL(d.sources[primary].url, MORRO);
}
/** A2: unknown never carries a verified date or wording; the last parseable check stays as `checked`. */
function assertUnknownUnverified(d, species, {state, summary}, checked, message) {
  assert.equal(state.status, 'unknown', `${message}: state`);
  assert.equal(summary.status, 'unknown', `${message}: summary status`);
  assert.equal(summary.label, 'Check rules', `${message}: summary label`);
  assert.equal(summary.verified, null, `${message}: verified`);
  assert.equal(summary.checked, checked, `${message}: checked`);
  assert.doesNotMatch(verifiedText(summary), /^Verified/, `${message}: wording`);
  assert.equal(verifiedText(summary), checked ? `Needs recheck · last check ${checked}` : 'Not verified', `${message}: wording`);
  assert.equal(summary.depth, null, `${message}: depth withheld`);
  if (d && ruleProfile(d, species === 'reef' ? 'lingcod' : species, MORRO)) {
    assert.deepEqual({bag: summary.bag, size: summary.size}, limits(d, species), `${message}: registry limits`);
    assert.equal(summary.link, link(d, species), `${message}: official link`);
  }
}

test('A1 reviewed in-period open, closed, restricted and scheduled states keep their limits and Verified check date', () => {
  const d = data();
  const restricted = data();
  restricted.species.bluefin.windows = [{start: '2026-01-01', end: '2026-12-31', restriction: 'Synthetic restriction text.'}];
  const OPENER = Date.parse('2026-11-07T08:00:00Z'), opener = data(OPENER);
  for (const [registry, species, at, status, label, depth, verified] of [
    [d, 'lingcod', NOW, 'open', 'Open', 'All depths', 'Sep 21'],
    [d, 'reef', NOW, 'open', 'Open', 'All depths', 'Sep 21'],
    [d, 'halibut', NOW, 'open', 'Open', null, 'Sep 21'],
    [d, 'dungeness', NOW, 'closed', 'Closed', null, 'Sep 21'],
    [restricted, 'bluefin', NOW, 'restricted', 'Open · limits', null, 'Sep 21'],
    [opener, 'dungeness', OPENER, 'scheduled', 'Opener unconfirmed', null, 'Nov 7'],
  ]) {
    const {state, summary} = row(registry, species, at);
    assert.equal(state.status, status, species);
    assert.deepEqual(state.issues, [], species);
    assert.deepEqual(summary, {status, label, ...limits(registry, species), depth, verified, checked: null, link: link(registry, species),
      linkLabel: species === 'reef' ? 'Official groundfish rules' : 'Official rules'}, species);
    assert.equal(verifiedText(summary), `Verified ${verified}`, species);
  }
  assert.equal(depthLimit(d.species.lingcod, '2026-09-21'), 'All depths', 'depth comes from the registry season text');
});

test('A2 expired and not-yet-valid rule periods are unknown with no Verified badge', () => {
  const d = data();
  for (const tripDate of ['2027-01-01', '2027-03-15', '2026-09-20']) {
    for (const species of ['lingcod', 'halibut', 'albacore', 'reef']) {
      const r = row(d, species, NOW, tripDate);
      assert.deepEqual(r.state.issues, [], `${species} ${tripDate}: the source checks themselves are fresh`);
      assert.equal(r.state.reason, 'This date is outside the reviewed rule period. Current-year rules need review.', `${species} ${tripDate}: reason preserved`);
      assertUnknownUnverified(d, species, r, 'Sep 21', `${species} ${tripDate}`);
    }
  }
});

test('A2 a review time beyond the future tolerance is unknown with no Verified badge', () => {
  for (const ahead of [1.5 * HOUR, 30 * HOUR]) {
    const d = data(); d.reviewed_at = new Date(NOW + ahead).toISOString();
    for (const species of ['lingcod', 'salmon', 'reef']) {
      const r = row(d, species);
      assert.deepEqual(r.state.issues, [], `${species}: fresh checks`);
      assert.equal(r.state.reason, 'This date is outside the reviewed rule period. Current-year rules need review.', species);
      assertUnknownUnverified(d, species, r, 'Sep 21', `${species} reviewed ${ahead / HOUR} h ahead`);
    }
  }
  // Inside the existing one-hour tolerance the record is still reviewed (threshold unchanged).
  const d = data(); d.reviewed_at = new Date(NOW + 0.5 * HOUR).toISOString();
  assert.equal(row(d, 'lingcod').summary.verified, 'Sep 21');
});

test('A2 a season that needs a fishing location is unknown with no Verified badge', () => {
  for (const species of ['halibut', 'lingcod', 'albacore']) {
    const d = banded(data(), species), r = row(d, species);
    assert.equal(r.state.label, 'Choose fishing location', species);
    assert.equal(r.state.reason, 'This season applies only within a geographic area. Synthetic band.', `${species}: reason preserved`);
    assert.deepEqual(r.state.issues, [], species);
    assertUnknownUnverified(d, species, r, 'Sep 21', `${species} band`);
  }
});

test('A2 absent registry, unknown target and unreviewed content show no Verified badge', () => {
  for (const [registry, species] of [[null, 'lingcod'], [null, 'reef'], [data(), 'constructor'], [data(), '__proto__'], [data(), 'unsupported-target']]) {
    const r = row(registry, species);
    assert.equal(r.state.reason, 'Regulations unavailable. Open the official CDFW rules before fishing.', species);
    assertUnknownUnverified(registry, species, r, null, `${species} ${registry ? 'registry' : 'none'}`);
    assert.deepEqual([r.summary.bag, r.summary.size, r.summary.link], [[], [], CDFW_OCEAN], species);
  }
  const pending = data(); pending.rules_review_status = 'content-needs-review';
  const r = row(pending, 'lingcod');
  assert.equal(r.state.reason, 'Saved regulatory content needs review. Consult the official rules before fishing.');
  assertUnknownUnverified(pending, 'lingcod', r, 'Sep 21', 'unreviewed content');
});

test('A2 changed and stale sources keep the last parseable check as checked only', () => {
  const changed = data(); changed.checks['rules-groundfish'].status = 'changed';
  let r = row(changed, 'lingcod');
  assert.match(r.state.reason, /^An official source changed after review\./);
  assertUnknownUnverified(changed, 'lingcod', r, 'Sep 21', 'changed');
  const stale = data(); stale.checks['rules-groundfish'].data_retrieved_at = '2026-09-19T00:00:00Z';
  r = row(stale, 'lingcod');
  assert.match(r.state.reason, /^The daily source check is incomplete or over 36 hours old\./);
  assertUnknownUnverified(stale, 'lingcod', r, 'Sep 18', 'stale: the oldest parseable check');
  const unparseable = data(); unparseable.checks['rules-groundfish'].data_retrieved_at = 'not a time';
  assertUnknownUnverified(unparseable, 'lingcod', row(unparseable, 'lingcod'), null, 'unparseable check: no date at all');
});

test('A2 combined reef with one unknown member is unknown with no Verified badge', () => {
  for (const member of ['lingcod', 'rockfish']) {
    const d = banded(data(), member), r = row(d, 'reef');
    const other = member === 'lingcod' ? 'rockfish' : 'lingcod';
    assert.deepEqual(r.state.members.map(m => [m.status, m.issues.length]), member === 'lingcod' ? [['unknown', 0], ['open', 0]] : [['open', 0], ['unknown', 0]]);
    assert.equal(regulationState(d, other, MORRO, NOW).status, 'open', `${other} alone stays open`);
    assert.equal(r.state.reason, 'This season applies only within a geographic area. Synthetic band.');
    assertUnknownUnverified(d, 'reef', r, 'Sep 21', `reef with ${member} banded`);
  }
  // A changed member source (issues present) stays unverified as before.
  const d = data(); d.checks['rules-groundfish'].status = 'changed';
  assertUnknownUnverified(d, 'reef', row(d, 'reef'), 'Sep 21', 'reef with a changed source');
});

test('A3 unknown keeps the registry limits, withholds depth and is never turned open or closed', () => {
  const d = data(), r = row(d, 'reef', NOW, '2027-01-01');
  assert.equal(r.state.status, 'unknown');
  assert.notEqual(r.summary.status, 'open'); assert.notEqual(r.summary.status, 'closed');
  assert.deepEqual(r.summary.bag, ['Lingcod: 2 per person daily', 'Rockfish / rock cod: 10 total rockfish, cabezon and greenlings…']);
  assert.deepEqual(r.summary.size, ['Lingcod: 22 in min total length', 'Rockfish / rock cod: No min length for retained rockfish']);
  assert.equal(r.summary.depth, null);
  // A valid closed season is reviewed evidence, not unreviewed evidence: it keeps its badge.
  const closed = row(d, 'dungeness');
  assert.equal(closed.state.reason, 'Outside the reviewed local season.');
  assert.deepEqual([closed.summary.status, closed.summary.verified, closed.summary.checked], ['closed', 'Sep 21', null]);
  // The registry under test is the frozen FE-61 record, unedited by these cases.
  assert.deepEqual([ORIGINAL.valid_from, ORIGINAL.valid_through], ['2026-09-21', '2026-12-31']);
});

test('A4 a future trip outside valid_through with fresh reviewed checks has empty issues, unknown state and no Verified badge', () => {
  const d = data(), r = row(d, 'lingcod', NOW, '2027-01-02', Date.parse('2027-01-02T16:00:00Z'));
  assert.equal(d.rules_review_status, 'reviewed');
  assert.ok(Object.values(d.checks).every(c => c.data_retrieved_at === new Date(NOW).toISOString()), 'every source check is fresh');
  assert.deepEqual(r.state.issues, []);
  assert.equal(r.state.status, 'unknown');
  assert.equal(r.summary.verified, null);
  assert.equal(verifiedText(r.summary), 'Needs recheck · last check Sep 21');
});

test('A4 the same record inside its valid period still shows Verified', () => {
  const d = data(), r = row(d, 'lingcod', NOW, '2026-12-31', Date.parse('2026-12-31T16:00:00Z'));
  assert.deepEqual(r.state.issues, []);
  assert.equal(r.state.status, 'open');
  assert.equal(r.summary.verified, 'Sep 21');
  assert.equal(verifiedText(r.summary), 'Verified Sep 21');
});

test('no case performed network IO', () => {
  assert.equal(fetchCalls, 0);
});

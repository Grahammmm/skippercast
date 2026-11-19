// F19-14 / SCA-612: absence is a review signal only for a complete, scoped import.
// Default: fixture reference. Opt-in receipt: node tests/test_f19_14_audit.mjs --baseline
// Both modes execute the real import upserts in memory; baseline omits the fixture
// reconciliation step. The same contract assertions intentionally detect the gap.
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import test from 'node:test';
import {importRows, rulesSql} from '../scripts/advisor/import-rules.mjs';
import {migrationSql} from './_advisor_d1.mjs';

const baseline = process.argv.includes('--baseline');
const scope = {origin: 'fixture-feed', jurisdiction: 'fixture-area'};
const t0 = Date.parse('2026-01-01T00:00:00Z');
const t1 = Date.parse('2026-01-02T00:00:00Z');
const file = (jurisdiction, entries) => ({jurisdiction, data: {
  official_map_url: 'https://example.invalid/fixture',
  species: Object.fromEntries(entries.map(([name, note]) => [name, {details: [note]}])),
}});
const prior = [
  ['present', scope.origin, scope.jurisdiction, 'active'],
  ['missing', scope.origin, scope.jurisdiction, 'active'],
  ['manual', null, scope.jurisdiction, 'active'],
  ['retired', scope.origin, scope.jurisdiction, 'retired'],
  ['other-area', scope.origin, 'fixture-neighbor', 'active'],
  ['other-feed', 'fixture-other-feed', scope.jurisdiction, 'active'],
].map(([name, origin, jurisdiction, status]) => {
  const [row] = importRows(t0, [file(jurisdiction, [[name, 'old fixture note']])]);
  return {name, origin, row: {...row, status, updated_by: 'fixture-custodian'}};
});

// Fixture provenance is independent of the last editor and shared citation.
// This reference models a review signal, not a withdrawal or a new legal limit.
function reconcileFixture(db, snapshot, rows) {
  if (snapshot.state !== 'complete') return;
  const present = new Set(rows.map(row => row.id));
  const review = db.prepare("UPDATE advisor_rules SET status='review' WHERE id=? AND status='active'");
  for (const {origin, row} of prior) {
    if (origin === snapshot.origin && row.jurisdiction === snapshot.jurisdiction && !present.has(row.id)) review.run(row.id);
  }
}

for (const [state, expectedReviews] of [
  ['complete', ['present', 'missing']],
  ['partial', ['present']],
  ['failed', []],
]) {
  test(`F19-14 ${baseline ? 'baseline' : 'reference'}: ${state} snapshot only flags eligible rules`, t => {
    const db = new DatabaseSync(':memory:');
    t.after(() => db.close());
    db.exec(migrationSql('0008_advisor_answers'));
    db.exec(rulesSql(prior.map(({row}) => row)));
    const read = db.prepare('SELECT * FROM advisor_rules WHERE id=?');
    const before = prior.map(({row}) => read.get(row.id));

    // Same nonempty payload for complete and partial; a failed import carries no rows.
    const snapshot = {...scope, state, files: state === 'failed' ? [] : [file(scope.jurisdiction, [['present', 'new fixture note']])]};
    const rows = importRows(t1, snapshot.files);
    db.exec(rulesSql(rows));
    if (!baseline) reconcileFixture(db, snapshot, rows);

    const after = prior.map(({row}) => read.get(row.id));
    assert.equal(db.prepare('SELECT count(*) AS n FROM advisor_rules').get().n, prior.length, 'no inserts or deletions');
    const reviews = [];
    for (const [i, {name}] of prior.entries()) {
      assert.ok(after[i], `${name}: rule was not deleted`);
      if (after[i].status === 'review') reviews.push(name);
      if (name === 'present' && state !== 'failed') {
        assert.equal(after[i].gear_notes, 'new fixture note', 'changed present rule was actually upserted');
      } else if (name === 'missing' && state === 'complete') {
        assert.deepEqual({...after[i], status: before[i].status}, {...before[i]}, 'absence alone does not rewrite rule content');
      } else {
        assert.deepEqual(after[i], before[i], `${name}: rule must stay untouched`);
      }
    }
    t.diagnostic(JSON.stringify({snapshot: state, reviews, missing: after[1].status}));
    assert.deepEqual(reviews, expectedReviews, 'only the expected rules need review; missing is eligible only for a complete snapshot');
  });
}

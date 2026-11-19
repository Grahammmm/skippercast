// SCA-578 / F03-13: a review may close only if its requested link is saved in
// that transaction. The review UPDATE can succeed even when the link UPDATE is a no-op.

import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase} from './_advisor_d1.mjs';

globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {decideFleetReview} = await import('../server/fleet/admin/reviews.ts');

const VESSEL = 'a'.repeat(32), REVIEW = 'b'.repeat(32);
const BOAT = 'fixture-boat', OTHER = 'fixture-other', ACTOR = 'fixture-reviewer';
const OPENED = '2026-01-01T00:00:00.000Z', LINKED = '2026-01-02T00:00:00.000Z';
const DECIDED = '2026-01-03T00:00:00.000Z', REPLAYED = '2026-01-04T00:00:00.000Z';
const input = {action: 'same-vessel', vessel_id: VESSEL};

async function scenario({beforeRead, beforeBatch, verify}) {
  const {sql, db} = advisorDatabase();
  try {
    sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,first_seen_at,last_seen_at,created_at,updated_at)
      VALUES(?,'CA','fixture-vessel','Fixture Vessel','FIXTUREVESSEL',?,?,?,?)`).run(VESSEL, OPENED, OPENED, OPENED, OPENED);
    const addBoat = sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,created_at,updated_at)
      VALUES(?,?,'Synthetic Boat','fixture-port','fixture-region',?,?)`);
    for (const id of [BOAT, OTHER]) addBoat.run(id, id, OPENED, OPENED);
    sql.prepare(`INSERT INTO fleet_reviews(id,region,kind,subject_id,opened_at) VALUES(?,'CA','advisor-link',?,?)`).run(REVIEW, BOAT, OPENED);

    const link = id => sql.prepare('UPDATE advisor_boats SET fleet_vessel_id=?,updated_at=? WHERE id=?').run(VESSEL, LINKED, id);
    const review = sql.prepare('SELECT status,decision_json,decided_by,decided_at FROM fleet_reviews WHERE id=?');
    const boats = sql.prepare('SELECT fleet_vessel_id,updated_at FROM advisor_boats WHERE id=?');
    const snapshot = () => ({review: {...review.get(REVIEW)}, subject: {...boats.get(BOAT)}, other: {...boats.get(OTHER)}});
    if (beforeRead) link(beforeRead);
    const brokenCommits = [];
    const racing = {...db, async batch(statements) {
      // Deterministic competing commit after preflight, before the review transaction.
      if (beforeBatch) { link(beforeBatch); beforeBatch = null; }
      const results = await db.batch(statements);
      const {review, subject} = snapshot();
      if (review.status === 'decided' && subject.fleet_vessel_id !== VESSEL) brokenCommits.push(review.status);
      return results;
    }};
    const decide = now => decideFleetReview(racing, REVIEW, input, ACTOR, now);
    const result = await decide(DECIDED);
    await verify({result, snapshot, brokenCommits, decide});
  } finally { sql.close(); }
}

// A fresh link must write the pair in the batch; an existing pair must not be rewritten.
for (const [name, timing, linkedAt] of [
  ['created by the decision', {}, DECIDED],
  ['present before preflight', {beforeRead: BOAT}, LINKED],
  ['created by a concurrent write', {beforeBatch: BOAT}, LINKED],
]) {
  test(`F03-13: link ${name} closes idempotently`, () => scenario({
    ...timing,
    async verify({result, snapshot, brokenCommits, decide}) {
      const saved = snapshot();
      assert.equal(result.status, 'ok');
      assert.equal(result.value.repeated, undefined);
      assert.deepEqual({...saved.review, decision_json: JSON.parse(saved.review.decision_json)}, {
        status: 'decided', decision_json: {...input, boat_id: BOAT}, decided_by: ACTOR, decided_at: DECIDED,
      });
      assert.deepEqual(saved.subject, {fleet_vessel_id: VESSEL, updated_at: linkedAt});
      assert.deepEqual(saved.other, {fleet_vessel_id: null, updated_at: OPENED});
      const repeat = await decide(REPLAYED);
      assert.equal(repeat.status, 'ok');
      assert.equal(repeat.value.repeated, true);
      assert.deepEqual(snapshot(), saved, 'replaying the decision changes neither the link nor history');
      assert.deepEqual(brokenCommits, [], 'no committed decision may lack its link');
    },
  }));
}

test('F03-13: a competing link returns conflict and leaves the review open', () => scenario({
  beforeBatch: OTHER,
  verify({result, snapshot, brokenCommits}) {
    assert.deepEqual({outcome: result.status, ...snapshot(), brokenCommits}, {
      outcome: 'conflict',
      review: {status: 'open', decision_json: null, decided_by: null, decided_at: null},
      subject: {fleet_vessel_id: null, updated_at: OPENED},
      other: {fleet_vessel_id: VESSEL, updated_at: LINKED},
      brokenCommits: [],
    });
  },
}));

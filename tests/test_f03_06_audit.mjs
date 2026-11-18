// SCA-527 / SCA-187 (F03-06): approve only the fleet labels the owner actually reviewed.
// Contract: approval is bound to an atomic comparison of the displayed label set. A replacement or addition between display and
// approval returns conflict and approves nothing; an unchanged set approves exactly once.
// Offline fixture on the real labels.ts and the committed migrations (in-memory node:sqlite). Read-only baseline: it records what
// approveTrip does today (it receives only a trip id) and passes once it meets the contract; other drift fails.
// Protects against: an agent re-importing labels after the owner viewed them and the owner's click relabelling the new set.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: ['https://skippercast.com']};
const {approveTrip, importAgentLabels, APPROVED_PREFIX} = await import('../server/fleet/admin/labels.ts');

const skip = sqliteUnavailable ?? false;
const TRIP = 'a'.repeat(32), OWNER = 'owner-1', AGENT = 'agent:synthetic', T0 = '2026-10-07T12:00:00.000Z';
const range = (h0, h1, label, basis) => ({started_at: `2026-10-07T${h0}:00Z`, ended_at: `2026-10-07T${h1}:00Z`, label, basis});
const SHOWN = [range('08:00', '09:00', 'transit', 'reviewed track A'), range('09:00', '10:00', 'troll-slow', 'reviewed track B')];
const SWAPPED = [range('08:00', '10:00', 'troll-pelagic', 'unseen replacement')];
const ADDED = [...SHOWN, range('10:00', '11:00', 'drift-anchor', 'unseen addition')];

function fixture() {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,departed_at,returned_at,local_date,season,source,rights,classifier_version,computed_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`).run(TRIP, 'synthetic', 'v1', '000000000', '2026-10-07T07:00:00Z', '2026-10-07T13:00:00Z', '2026-10-07', 's', 'synthetic', 'test', 'c1', T0);
  const rows = () => sql.prepare('SELECT id,started_at,ended_at,label,labeller,basis FROM fleet_segment_labels WHERE trip_id=? ORDER BY started_at,id').all(TRIP);
  const propose = async labels => { const r = await importAgentLabels(db, {trip_id: TRIP, labeller: AGENT, labels}, T0); assert.equal(r.status, 200); };
  return {db, rows, propose};
}

// What the owner's page showed: the agent's proposed labels, as ids and content.
const displayed = rows => rows.filter(r => r.labeller.startsWith('agent:')).map(({id, started_at, ended_at, label, basis}) => ({id, started_at, ended_at, label, basis}));
const owned = rows => rows.filter(r => r.labeller === OWNER);

// Reference approver for the contract: one UPDATE whose WHERE clause compares the current agent set with the displayed ids.
async function approveReviewed(db, tripId, owner, reviewedIds) {
  const result = await db.prepare(`UPDATE fleet_segment_labels SET labeller=?,basis=?||labeller||': '||COALESCE(basis,'')
    WHERE trip_id=? AND labeller LIKE 'agent:%'
    AND (SELECT group_concat(id) FROM (SELECT id FROM fleet_segment_labels WHERE trip_id=? AND labeller LIKE 'agent:%' ORDER BY id))=?`)
    .bind(owner, APPROVED_PREFIX, tripId, tripId, [...reviewedIds].sort().join(',')).run();
  return result.meta.changes ? {status: 'ok', approved: result.meta.changes} : {status: 'conflict'};
}
// Synthetic defect: relabels every agent proposal on the trip at click time and never looks at the displayed set (the F03-06 shape).
// It is self-contained, so the negative control keeps working whatever the real handler does.
async function approveIgnoringDisplayed(db, tripId, owner) {
  const result = await db.prepare(`UPDATE fleet_segment_labels SET labeller=?,basis=?||labeller||': '||COALESCE(basis,'')
    WHERE trip_id=? AND labeller LIKE 'agent:%'`).bind(owner, APPROVED_PREFIX, tripId).run();
  return result.meta.changes ? {status: 'ok', approved: result.meta.changes} : {status: 'conflict'};
}

// Every way `approve` breaks the contract on the three scenarios (empty list = contract holds).
async function gaps(approve) {
  const out = [];
  for (const [name, change] of [['replacement', SWAPPED], ['addition', ADDED]]) {
    const f = fixture(); await f.propose(SHOWN);
    const shown = displayed(f.rows()); await f.propose(change);
    const before = JSON.stringify(f.rows().map(r => [r.id, r.labeller, r.basis]));
    const r = await approve(f.db, TRIP, OWNER, shown.map(s => s.id));
    if (r.status !== 'conflict') out.push(`${name}: status ${r.status}, not conflict`);
    if (owned(f.rows()).length) out.push(`${name}: ${owned(f.rows()).length} unseen label(s) approved`);
    if (r.status === 'conflict' && JSON.stringify(f.rows().map(x => [x.id, x.labeller, x.basis])) !== before) out.push(`${name}: conflict changed rows`);
  }
  const f = fixture(); await f.propose(SHOWN);
  const shown = displayed(f.rows());
  const first = await approve(f.db, TRIP, OWNER, shown.map(s => s.id));
  if (first.status !== 'ok' || first.approved !== SHOWN.length) out.push(`unchanged: expected ok/${SHOWN.length}, got ${first.status}/${first.approved}`);
  if (owned(f.rows()).length !== SHOWN.length) out.push('unchanged: not every displayed label approved');
  const again = await approve(f.db, TRIP, OWNER, shown.map(s => s.id));
  if (again.status !== 'conflict') out.push(`unchanged: second approval returned ${again.status}, not conflict`);
  return out;
}

test('positive control: approval compared with the displayed set passes all three scenarios', {skip}, async () => {
  assert.deepEqual(await gaps(approveReviewed), []);
});

test('negative control: a synthetic approver that ignores the displayed set is detected', {skip}, async () => {
  const found = await gaps(approveIgnoringDisplayed);
  assert.deepEqual(found, [
    'replacement: status ok, not conflict', 'replacement: 1 unseen label(s) approved',
    'addition: status ok, not conflict', 'addition: 3 unseen label(s) approved']);
});

test('baseline: the real approveTrip either meets the contract or still shows the recorded gap', {skip}, async () => {
  // Read-only observation of main. The reviewed ids are offered as a fourth argument, which today's handler (trip id and owner only)
  // ignores. A handler that satisfies the whole contract passes; so does today's observed gap. Any other result is unexplained drift.
  const found = await gaps((db, id, owner, ids) => approveTrip(db, id, owner, ids).then(r => ({status: r.status, approved: r.value?.approved})));
  if (found.length) assert.deepEqual(found, [
    'replacement: status ok, not conflict', 'replacement: 1 unseen label(s) approved',
    'addition: status ok, not conflict', 'addition: 3 unseen label(s) approved'], 'approveTrip changed but does not meet the contract');
});

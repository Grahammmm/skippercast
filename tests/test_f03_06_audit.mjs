// SCA-187 (F03-06): a trip's agent labels may change after the owner views them.
// Exercise the real display, import and approval functions against in-memory SQLite.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: ['https://skippercast.com']};
const {approveTrip, importAgentLabels, tripDetail} = await import('../server/fleet/admin/labels.ts');

const skip = sqliteUnavailable ?? false;
const TRIP = 'a'.repeat(32), OWNER = 'owner-1', AGENT = 'agent:synthetic', T0 = '2026-10-07T12:00:00.000Z';
const range = (h0, h1, label, basis) => ({started_at: `2026-10-07T${h0}:00Z`, ended_at: `2026-10-07T${h1}:00Z`, label, basis});
const SHOWN = [range('08:00', '09:00', 'transit', 'reviewed track A'), range('09:00', '10:00', 'troll-slow', 'reviewed track B')];
const SWAPPED = [{...SHOWN[0], label: 'troll-pelagic', basis: 'unseen replacement'}, SHOWN[1]];
const ADDED = [range('10:00', '11:00', 'drift-anchor', 'unseen addition')];

async function fixture(t) {
  const {sql, db} = advisorDatabase();
  t.after(() => sql.close());
  sql.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,departed_at,returned_at,local_date,season,source,rights,classifier_version,computed_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`).run(TRIP, 'synthetic', 'v1', '999000006', '2026-10-07T07:00:00Z', '2026-10-07T13:00:00Z', '2026-10-07', 's', 'synthetic', 'test', 'c1', T0);
  const rows = () => sql.prepare('SELECT * FROM fleet_segment_labels WHERE trip_id=? ORDER BY started_at,id').all(TRIP);
  const propose = async (labels, labeller = AGENT) => {
    const r = await importAgentLabels(db, {trip_id: TRIP, labeller, labels}, T0);
    assert.equal(r.status, 200);
  };
  await propose(SHOWN);
  const shown = (await tripDetail(db, TRIP)).labels;
  return {db, rows, propose, reviewed: shown.map(l => l.id)};
}

test('a same-count replacement after display conflicts and leaves every row unchanged', {skip}, async t => {
  const {db, rows, propose, reviewed} = await fixture(t);
  await propose(SWAPPED);
  const before = rows();
  assert.equal((await approveTrip(db, TRIP, OWNER, reviewed)).status, 'conflict');
  assert.deepEqual(rows(), before);
});

test('an additional proposal at the approval write conflicts, even when every reviewed id still exists', {skip}, async t => {
  const {db, rows, propose, reviewed} = await fixture(t);
  let before;
  const racingDb = {...db, prepare(query) {
    const stmt = db.prepare(query);
    if (/\bUPDATE\s+fleet_segment_labels\b/i.test(query)) {
      // Commit the other agent's addition just before the approval statement executes.
      // A separate read-then-write check can miss it, or approve only the old subset.
      const run = stmt.run.bind(stmt);
      stmt.run = async () => { await propose(ADDED, 'agent:other'); before = rows(); return run(); };
    }
    return stmt;
  }};
  assert.equal((await approveTrip(racingDb, TRIP, OWNER, reviewed)).status, 'conflict');
  assert.equal(before.length, SHOWN.length + ADDED.length);
  assert.deepEqual(rows(), before);
});

test('an unchanged set is approved exactly once regardless of id order', {skip}, async t => {
  const {db, rows, reviewed} = await fixture(t);
  const before = rows();
  const ids = [...reviewed].sort().reverse();
  const first = await approveTrip(db, TRIP, OWNER, ids);
  assert.equal(first.status, 'ok');
  assert.equal(first.value.approved, SHOWN.length);
  const after = before.map(l => ({...l, labeller: OWNER, basis: `approved from ${AGENT}: ${l.basis}`}));
  assert.deepEqual(rows().map(l => ({...l})), after);
  assert.equal((await approveTrip(db, TRIP, OWNER, ids)).status, 'conflict');
  assert.deepEqual(rows().map(l => ({...l})), after);
});
// RF0854-7: the ais_seen_30d lead part means a watched vessel seen in [now-30d, now]; an AIS sighting
// dated after the scoring instant earns nothing. Migration-backed D1, fixed clock, synthetic rows.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {leadInputs, leadScore} from '../server/fleet/leadscore.ts';
import {listOperators, operatorDetail} from '../server/fleet/admin/operators.ts';

const skip = sqliteUnavailable ?? false;
const NOW = '2026-11-09T17:00:00.000Z', T = Date.parse(NOW);
const at = ms => new Date(T + ms).toISOString();
const DAY = 86400e3, AIS_WEIGHT_POINTS = () => leadScore({landing_report_volume: null, reporting_frequency: null, social_presence: null, ais_seen_30d: 1}).parts.find(p => p.part === 'ais_seen_30d').points;

let seq = 0;
function operator(sql, name) {
  const id = `op-synthetic-${String(++seq).padStart(8, '0')}`;
  sql.prepare('INSERT INTO fleet_operators(id,region,slug,name,created_at,updated_at) VALUES(?,?,?,?,?,?)').run(id, 'CA', `synthetic-${seq}`, name, NOW, NOW);
  return id;
}
/** One vessel of `op` with one watch row of the given status and last_seen_at. */
function watch(sql, op, lastSeen, status = 'watched') {
  const vessel = String(++seq).padStart(32, 'a'), mmsi = String(999000000 + seq);
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,operator_id,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,'CA',?,?,?,?,?,?,?,?)`)
    .run(vessel, `boat-${seq}`, `Boat ${seq}`, `BOAT${seq}`, op, NOW, NOW, NOW, NOW);
  sql.prepare(`INSERT INTO fleet_ais_watch(region,mmsi,vessel_id,match_method,confidence,status,first_seen_at,last_seen_at,updated_at) VALUES('CA',?,?,'admin',1,?,?,?,?)`)
    .run(mmsi, vessel, status, lastSeen, lastSeen, lastSeen);
  return mmsi;
}
const ais = async (db, op, now = NOW) => (await leadInputs(db, {sql: 'o.id=?', args: [op]}, now)).get(op).ais_seen_30d;

test('ais_window_excludes_future_but_keeps_known_zero', {skip}, async () => {
  const {sql, db} = advisorDatabase();
  try {
    const recent = operator(sql, 'Recent'), future = operator(sql, 'Future');
    watch(sql, recent, at(-DAY)); const futureMmsi = watch(sql, future, at(DAY));
    assert.equal(await ais(db, recent), 1);
    assert.equal(await ais(db, future), 0, 'future-only is a known zero, not missing');
    const {parts} = leadScore((await leadInputs(db, {sql: 'o.id=?', args: [future]}, NOW)).get(future));
    assert.equal(parts.find(p => p.part === 'ais_seen_30d').points, 0);
    assert.equal(parts.find(p => p.part === 'ais_seen_30d').missing, false);
    for (const ms of [1, DAY, 365 * DAY]) {
      sql.prepare('UPDATE fleet_ais_watch SET last_seen_at=? WHERE mmsi=?').run(at(ms), futureMmsi);
      assert.equal(await ais(db, future), 0, `now+${ms}ms`);
    }
    const {parts: recentParts} = leadScore((await leadInputs(db, {sql: 'o.id=?', args: [recent]}, NOW)).get(recent));
    assert.equal(recentParts.find(p => p.part === 'ais_seen_30d').points, AIS_WEIGHT_POINTS());
    assert.ok(AIS_WEIGHT_POINTS() > 0);
  } finally { sql.close(); }
});

test('ais_window_includes_both_exact_bounds', {skip}, async () => {
  const {sql, db} = advisorDatabase();
  try {
    const op = operator(sql, 'Bounds');
    watch(sql, op, at(0));
    const set = ms => sql.prepare('UPDATE fleet_ais_watch SET last_seen_at=?').run(at(ms));
    assert.equal(await ais(db, op), 1, 'exactly now');
    set(-30 * DAY); assert.equal(await ais(db, op), 1, 'exactly now-30d');
    set(-30 * DAY - 1); assert.equal(await ais(db, op), 0, '1ms before the lower bound');
    set(1); assert.equal(await ais(db, op), 0, '1ms after now');
    set(0);
    for (const spelling of ['2026-11-09T17:00:00Z', '2026-11-09T09:00:00-08:00', 'Mon, 09 Nov 2026 17:00:00 GMT']) {
      assert.equal(await ais(db, op, spelling), 1, spelling);
      set(1); assert.equal(await ais(db, op, spelling), 0, `${spelling} +1ms`); set(0);
      set(-30 * DAY); assert.equal(await ais(db, op, spelling), 1, `${spelling} lower bound`); set(0);
    }
  } finally { sql.close(); }
});

test('ais_window_aggregates_only_watched_rows', {skip}, async () => {
  const {sql, db} = advisorDatabase();
  try {
    const futureRecent = operator(sql, 'FutureRecent'), futureOld = operator(sql, 'FutureOld'), candidateOnly = operator(sql, 'Candidate'),
      rejectedFuture = operator(sql, 'Rejected'), none = operator(sql, 'NoWatch'), other = operator(sql, 'Other');
    watch(sql, futureRecent, at(DAY)); watch(sql, futureRecent, at(-2 * DAY));
    watch(sql, futureOld, at(DAY)); watch(sql, futureOld, at(-40 * DAY));
    watch(sql, candidateOnly, at(-DAY), 'candidate');
    watch(sql, rejectedFuture, at(-DAY), 'rejected'); watch(sql, rejectedFuture, at(DAY));
    watch(sql, other, at(-DAY));
    assert.equal(await ais(db, futureRecent), 1, 'a qualifying row still earns points beside a future one');
    assert.equal(await ais(db, futureOld), 0);
    assert.equal(await ais(db, candidateOnly), null, 'candidate rows supply no evidence');
    assert.equal(await ais(db, rejectedFuture), 0, 'only the future watched row counts; the rejected recent row does not');
    assert.equal(await ais(db, none), null);
    const all = await leadInputs(db, {sql: '1=1', args: []}, NOW);
    assert.deepEqual([...all].map(([id, i]) => [id, i.ais_seen_30d]).sort(),
      [[futureRecent, 1], [futureOld, 0], [candidateOnly, null], [rejectedFuture, 0], [none, null], [other, 1]].sort());
  } finally { sql.close(); }
});

test('operator_views_use_bounded_ais_points_without_writes', {skip}, async () => {
  const {sql, db} = advisorDatabase();
  try {
    const recent = operator(sql, 'Recent'), future = operator(sql, 'Future');
    watch(sql, recent, at(-DAY)); watch(sql, future, at(DAY));
    const dump = () => JSON.stringify([sql.prepare('SELECT * FROM fleet_ais_watch ORDER BY mmsi').all(), sql.prepare('SELECT * FROM fleet_operators ORDER BY id').all()]);
    const before = dump();
    const list = await listOperators(db, {region: 'CA'}, NOW);
    const aisPart = lead => lead.parts.find(p => p.part === 'ais_seen_30d');
    const byId = Object.fromEntries(list.operators.map(o => [o.id, o.lead_score]));
    assert.equal(aisPart(byId[recent]).points, AIS_WEIGHT_POINTS());
    assert.equal(aisPart(byId[future]).points, 0);
    assert.equal(aisPart(byId[future]).raw, 0);
    assert.equal(byId[future].score, 0);
    assert.equal(byId[recent].score, Math.round(AIS_WEIGHT_POINTS()));
    for (const id of [recent, future]) {
      const detail = await operatorDetail(db, id, NOW);
      assert.ok(JSON.stringify(detail.lead_score) === JSON.stringify(byId[id]), 'list and detail agree');
      assert.deepEqual(detail.lead_score.parts.filter(p => p.part !== 'ais_seen_30d').map(p => [p.part, p.raw, p.points]),
        [['landing_report_volume', null, 0], ['reporting_frequency', null, 0], ['social_presence', null, 0]]);
    }
    assert.equal(dump(), before, 'read-only: no stored row changes');
  } finally { sql.close(); }
});

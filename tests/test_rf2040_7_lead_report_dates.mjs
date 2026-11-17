// RF2040-7: report-based lead inputs ignore trips dated after the scoring date (UTC day of `now`).
// Migration-backed D1, fixed clock, synthetic rows; no sender or provider.
import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {leadInputs, leadScore} from '../server/fleet/leadscore.ts';

const skip = sqliteUnavailable ?? false;
const NOW = '2026-11-16T12:00:00.000Z', T = Date.parse(NOW), DAY = 86400e3;
const date = offset => new Date(T + offset * DAY).toISOString().slice(0, 10);

let seq = 0;
function operator(sql) {
  const id = `op-synthetic-${String(++seq).padStart(8, '0')}`, vessel = String(seq).padStart(32, 'b');
  sql.prepare('INSERT INTO fleet_operators(id,region,slug,name,created_at,updated_at) VALUES(?,?,?,?,?,?)').run(id, 'CA', `synthetic-${seq}`, `Op ${seq}`, NOW, NOW);
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,operator_id,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,'CA',?,?,?,?,?,?,?,?)`)
    .run(vessel, `boat-${seq}`, `Boat ${seq}`, `BOAT${seq}`, id, NOW, NOW, NOW, NOW);
  return {id, vessel};
}
/** One trip dated `offset` days from today with the given report kinds paired to it. */
function trip(sql, op, offset, ...kinds) {
  const id = `trip-${++seq}`, d = date(offset);
  sql.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,departed_at,local_date,season,status,source,rights,classifier_version,computed_at)
    VALUES(?,'CA',?,'999000001',?,?,'2026','closed','aisstream','internal-only','v1',?)`).run(id, op.vessel, `${d}T10:00:00.000Z`, d, NOW);
  kinds.forEach((k, i) => sql.prepare(`INSERT INTO fleet_trip_reports(trip_id,report_kind,report_ref,match,confidence,created_at) VALUES(?,?,?,'alias-port-date',0.9,?)`).run(id, k, `ref-${seq}-${i}`, NOW));
}
const inputs = async (db, op) => (await leadInputs(db, {sql: 'o.id=?', args: [op.id]}, NOW)).get(op.id);
const withDb = fn => async () => { const {sql, db} = advisorDatabase(); try { await fn(sql, db); } finally { sql.close(); } };

test('lead_reports_future_only_is_known_zero', {skip}, withDb(async (sql, db) => {
  const op = operator(sql);
  trip(sql, op, 1, 'landing'); trip(sql, op, 7, 'landing', 'advisor');
  const raw = await inputs(db, op);
  assert.equal(raw.landing_report_volume, 0); assert.equal(raw.reporting_frequency, 0);
  const parts = leadScore(raw).parts.filter(p => p.part === 'landing_report_volume' || p.part === 'reporting_frequency');
  assert.ok(parts.every(p => p.points === 0 && p.missing === false));
}));

test('lead_reports_mixed_future_does_not_add_credit', {skip}, withDb(async (sql, db) => {
  const control = operator(sql), mixed = operator(sql);
  for (const op of [control, mixed]) { trip(sql, op, 0, 'landing', 'landing'); trip(sql, op, -10, 'advisor'); trip(sql, op, -20, 'landing'); }
  trip(sql, mixed, 1, 'landing'); trip(sql, mixed, 8, 'landing', 'advisor'); trip(sql, mixed, 30, 'landing');
  const a = await inputs(db, control), b = await inputs(db, mixed);
  assert.ok(isDeepStrictEqual(a, b), 'future trips change nothing');
  assert.equal(b.landing_report_volume, 2, 'duplicate pairings count a trip once; the advisor-only trip is not a landing');
  assert.equal(b.reporting_frequency, 3, 'weeks 0, 1 and 2 of the recent trips');
  assert.equal(leadScore(b).score, leadScore(a).score);
}));

test('lead_reports_date_boundaries', {skip}, withDb(async (sql, db) => {
  const probe = async (offset, kind) => { const op = operator(sql); trip(sql, op, offset, kind); const r = await inputs(db, op); return `${r.landing_report_volume},${r.reporting_frequency}`; };
  assert.equal(await probe(0, 'landing'), '1,1', 'today');
  assert.equal(await probe(-83, 'landing'), '1,1', 'today-83');
  assert.equal(await probe(-84, 'landing'), '1,0', 'today-84');
  assert.equal(await probe(-365, 'landing'), '1,0', 'today-365');
  assert.equal(await probe(-366, 'landing'), '0,0', 'today-366');
  assert.equal(await probe(1, 'landing'), '0,0', 'today+1');
  assert.equal(await probe(0, 'advisor'), '0,1', 'advisor-only today');
}));

test('lead_reports_missing_and_old_controls', {skip}, withDb(async (sql, db) => {
  const none = operator(sql), old = operator(sql), other = operator(sql);
  trip(sql, old, -400, 'landing'); trip(sql, other, 1, 'landing');
  const scoped = await leadInputs(db, {sql: 'o.id IN (?,?)', args: [none.id, old.id]}, NOW);
  assert.equal(scoped.size, 2, 'the out-of-scope operator is excluded');
  assert.equal(scoped.get(none.id).landing_report_volume, null); assert.equal(scoped.get(none.id).reporting_frequency, null);
  assert.equal(scoped.get(old.id).landing_report_volume, 0); assert.equal(scoped.get(old.id).reporting_frequency, 0);
}));

test('lead_reports_reads_do_not_mutate_rows', {skip}, withDb(async (sql, db) => {
  const op = operator(sql); trip(sql, op, -2, 'landing'); trip(sql, op, 3, 'landing');
  const snap = () => JSON.stringify([sql.prepare('SELECT * FROM fleet_trips ORDER BY id').all(), sql.prepare('SELECT * FROM fleet_trip_reports ORDER BY trip_id,report_ref').all()]);
  const before = snap(), first = await inputs(db, op);
  assert.equal(snap(), before);
  assert.ok(isDeepStrictEqual(await inputs(db, op), first));
  assert.equal(first.landing_report_volume, 1);
}));

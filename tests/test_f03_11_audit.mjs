import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase} from './_advisor_d1.mjs';

globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {};
globalThis.BUILD_ID = 'build-test';
const {vesselDetail} = await import('../server/fleet/admin/vessels.ts');

const NOW = '2026-10-31T12:00:00.000Z';
const VESSEL = 'a'.repeat(32), MMSI = '999000101', OTHER_MMSI = '999000102';
const tripId = day => day.toString(16).padStart(32, '0');

// A small page can hide an N+1 regression. Count actual prepared claim reads,
// and use distinct evidence/identity on neighboring rows to catch incorrect grouping.
for (const size of [0, 1, 20]) {
  test(`vessel detail: ${size} displayed trips keep their claims in at most two reads`, async () => {
    const {sql, db} = advisorDatabase();
    try {
      sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,mmsi,state_reg,first_seen_at,last_seen_at,created_at,updated_at)
        VALUES(?,'CA','audit-boat','Audit Boat','AUDITBOAT',?,'synthetic-registration',?,?,?,?)`).run(VESSEL, MMSI, NOW, NOW, NOW, NOW);
      const trip = sql.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,departed_at,local_date,season,status,source,rights,classifier_version,computed_at)
        VALUES(?,'CA',?,?,?,?,'2026','closed','aisstream','internal-only','c1',?)`);
      const segment = sql.prepare('INSERT INTO fleet_segments(id,trip_id,seq,kind,started_at,ended_at) VALUES(?,?,?,?,?,?)');
      const pair = sql.prepare(`INSERT INTO fleet_trip_reports(trip_id,report_kind,report_ref,match,confidence,created_at)
        VALUES(?,?,?,'boat-date',0.9,?)`);
      const report = sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,counts_json,source,status,created_at,updated_at)
        VALUES(?,?,'CA','p','2026-10-01','{}','synthetic-feed','published',?,?)`);
      const seedTrip = (day, mmsi, date = `2026-10-${String(day).padStart(2, '0')}`) => {
        trip.run(tripId(day), VESSEL, mmsi, `${date}T08:00:00.000Z`, date, NOW);
      };
      const seedSegment = (day, seq, kind) => segment.run(`${day}-${seq}`, tripId(day), seq, kind, NOW, NOW);
      for (let day = 21 - size; day <= 20; day++) seedTrip(day, day === 19 ? OTHER_MMSI : MMSI);
      if (size) {
        for (const ref of ['first', 'syndicated']) {
          report.run(ref, `boat-${ref}`, NOW, NOW);
          pair.run(tripId(20), 'advisor', ref, NOW);
        }
        pair.run(tripId(20), 'landing', 'landing-report', NOW);
        seedSegment(20, 0, 'drift-anchor');
        seedSegment(20, 1, 'troll-slow');
        seedSegment(20, 2, 'transit');
      }
      if (size === 20) {
        pair.run(tripId(19), 'advisor', 'missing-advisor', NOW);
        seedSegment(19, 0, 'troll-pelagic');
        seedSegment(18, 0, 'uncertain');
        seedTrip(21, MMSI, '2026-09-30'); // below the page cutoff
        pair.run(tripId(21), 'landing', 'off-page', NOW);
        seedSegment(21, 0, 'drift-anchor');
      }
      const claimReads = [];
      const detail = await vesselDetail({prepare(query) {
        const stmt = db.prepare(query);
        if (!/\b(?:fleet_trip_reports|fleet_segments)\b/.test(query)) return stmt;
        const bind = stmt.bind;
        stmt.bind = (...args) => { claimReads.push(args); return bind.apply(stmt, args); };
        return stmt;
      }}, VESSEL);
      const days = Array.from({length: size}, (_, i) => 20 - i);
      assert.deepEqual(detail.trips.map(({id, mmsi, claims}) => ({id, mmsi, claims: claims.map(c => [c.rung, c.count])})),
        days.map(day => ({id: tripId(day), mmsi: day === 19 ? OTHER_MMSI : MMSI,
          claims: day === 20 ? [['repeated-report', 2], ['ais-linger-verified', 2]] : day === 19 ? [['ais-linger', 1]] : []})));
      assert.ok(claimReads.length <= (size ? 2 : 0), `observed ${claimReads.length} claim reads for ${size} trips`);
      for (const args of claimReads) assert.ok(!args.includes(tripId(21)), 'off-page trip must not be fetched');
    } finally { sql.close(); }
  });
}

import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase} from './_advisor_d1.mjs';

globalThis.REGIONS = {'morro-bay': {daily_feed: 'https://example.invalid/f03-08'}};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {activity, activityDeps} = await import('../server/fleet/activity.ts');
const {pairingDeps} = await import('../server/fleet/pairing.ts');
const NOW = '2026-10-05T12:00:00.000Z';
const report = {id: 'f03-08-example', boat: 'Alpha Example', port: 'Morro Bay', date: '2026-10-01'};

// A conflicted ID used to vanish before pruning, leaving its previously stored match intact.
test('activity refresh retires contradicted landing evidence but not evidence from an unavailable feed', async t => {
  const {sql, db} = advisorDatabase();
  const {now} = activityDeps, {readFeed} = pairingDeps;
  t.after(() => { activityDeps.now = now; pairingDeps.readFeed = readFeed; sql.close(); });
  activityDeps.now = () => new Date(NOW);
  let feed = {reports: [report]};
  pairingDeps.readFeed = async () => { if (feed instanceof Error) throw feed; return feed; };
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,port_id,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES('v-example','CA','alpha-example','Alpha Example','ALPHAEXAMPLE','morro-bay',?,?,?,?)`).run(NOW, NOW, NOW, NOW);
  const trip = sql.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,depart_port_id,return_port_id,departed_at,returned_at,local_date,season,season_part,status,distance_nm,max_offshore_nm,fishing_min,positions_n,gap_min,source,rights,classifier_version,computed_at)
    VALUES(?,'CA','v-example','999000301','morro-bay','morro-bay',?,?,?,'2026','fall','closed',12.5,4.2,70,300,0,'aisstream','internal-only','c1-0123456789abcdef',?)`);
  const seedTrip = (id, date) => trip.run(id, `${date}T15:00:00.000Z`, `${date}T20:00:00.000Z`, date, NOW);
  seedTrip('recent-trip', report.date);
  seedTrip('older-trip', '2026-08-01');
  sql.prepare(`INSERT INTO fleet_trip_reports(trip_id,report_kind,report_ref,match,confidence,created_at)
    VALUES('older-trip','landing',?,'alias-port-date',0.8,?)`).run(report.id, NOW);
  const pairedTrips = () => sql.prepare(`SELECT trip_id FROM fleet_trip_reports WHERE report_kind='landing' AND report_ref=? ORDER BY trip_id`)
    .all(report.id).map(row => row.trip_id);
  const refresh = async () => {
    const result = await activity(db, new Request('https://example.invalid/api/fleet/jobs/activity', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({region: 'CA', processed: {run_id: 'ais-20261005T120000Z', counts: {}}}),
    }));
    assert.equal(result.status, 200, JSON.stringify(result.body));
    return result.body.feeds;
  };
  assert.deepEqual(await refresh(), {read: 1, unavailable: 0, reports: 1});
  assert.deepEqual(pairedTrips(), ['older-trip', 'recent-trip'], 'the clean report pairs with the recent trip');

  feed = new Error('synthetic feed unavailable');
  assert.deepEqual(await refresh(), {read: 0, unavailable: 1, reports: 0});
  assert.deepEqual(pairedTrips(), ['older-trip', 'recent-trip'], 'unavailability preserves the prior pair');

  feed = {reports: [report, {...report, boat: 'Beta Example'}, report]};
  assert.deepEqual(await refresh(), {read: 1, unavailable: 0, reports: 0});
  assert.deepEqual(pairedTrips(), ['older-trip'], 'a conflicted ID loses its in-scope pair, not its out-of-scope pair');
});

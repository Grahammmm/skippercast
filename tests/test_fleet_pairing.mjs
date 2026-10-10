// Catch-log pairing (#345; docs/plans/charter-fleet/design.md § 5 fleet_trip_reports): POST
// /api/fleet/jobs/activity pairs trips with advisor reports (advisor_boats.fleet_vessel_id
// plus local date) and, with `processed`, with landing reports from the daily feed
// (fleet_aliases.alias_norm plus port plus date). Through the Worker against the real
// migrations, with the fleet job verifier, the clock and the feed reader stubbed. Fixtures
// are synthetic (MMSIs 999xxxxxx, invented boats, report ids made up).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const {fleetJobs} = await import('../server/routes/fleet.ts');
const {activityDeps} = await import('../server/fleet/activity.ts');
const {pairingDeps, nameNorm, CONFIDENCE} = await import('../server/fleet/pairing.ts');

const skip = sqliteUnavailable ?? false;
const ORIGIN = 'https://skippercast.com', REGION = 'CA', NOW = '2026-10-05T12:00:00.000Z';
const FEED = globalThis.REGIONS['morro-bay'].daily_feed;
const sha = s => createHash('sha256').update(s, 'utf8').digest('hex').slice(0, 32);
const STAR = sha('CA:example-star'), DAY = sha('CA:example-day');
const A = '999000201', B = '999000202';

let feed = {reports: []}, feedReads = [];
const saved = {};
test.before(() => {
  Object.assign(saved, {verify: fleetJobs.verify, now: activityDeps.now, readFeed: pairingDeps.readFeed});
  fleetJobs.verify = async token => token === 'good' ? {jti: 'run-1'} : false;
  activityDeps.now = () => new Date(NOW);
  pairingDeps.readFeed = async url => { feedReads.push(url); if (feed instanceof Error) throw feed; return feed; };
});
test.after(() => { fleetJobs.verify = saved.verify; activityDeps.now = saved.now; pairingDeps.readFeed = saved.readFeed; });
test.beforeEach(() => { feed = {reports: []}; feedReads = []; });

function database() {
  const {sql, db} = advisorDatabase();
  const vessel = sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,port_id,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)`);
  vessel.run(STAR, REGION, 'example-star', 'Example Star', 'EXAMPLESTAR', 'morro-bay', NOW, NOW, NOW, NOW);
  vessel.run(DAY, REGION, 'example-day', 'Example Day', 'EXAMPLEDAY', 'port-san-luis', NOW, NOW, NOW, NOW);
  const alias = sql.prepare(`INSERT INTO fleet_aliases(vessel_id,alias_norm,alias,kind,source_url,first_seen_at,last_seen_at) VALUES(?,?,?,'report-name','https://example.com/boat',?,?)`);
  alias.run(STAR, 'EXAMPLESTAR2', 'Example Star II', NOW, NOW);
  alias.run(STAR, 'TWINEXAMPLE', 'Twin Example', NOW, NOW);   // also an alias of DAY: ambiguous, pairs nothing
  alias.run(DAY, 'TWINEXAMPLE', 'Twin Example', NOW, NOW);
  return {sql, db};
}
const call = async (db, payload) => {
  const response = await worker.fetch(new Request(ORIGIN + '/api/fleet/jobs/activity', {method: 'POST',
    headers: {'Content-Type': 'application/json', Authorization: 'Bearer good'}, body: JSON.stringify(payload)}), {ASSETS: {fetch: async () => new Response('', {status: 404})}, DB: db, FLEET_ENABLED: 'true'});
  const body = await response.json();
  assert.equal(response.status, 200, JSON.stringify(body));
  return body;
};

function trip(mmsi, departed, {vessel = STAR, port = 'morro-bay'} = {}) {
  return {id: sha(`${mmsi}|${departed}|aisstream`), region: REGION, vessel_id: vessel, mmsi, depart_port_id: port, return_port_id: port,
    departed_at: departed, returned_at: departed.replace('T15', 'T20'), local_date: '2026-10-01', season: '2026', season_part: 'fall',
    status: 'closed', trip_type_inferred: null, distance_nm: 12.5, max_offshore_nm: 4.2, fishing_min: 70, positions_n: 300, gap_min: 0,
    source: 'aisstream', rights: 'internal-only', classifier_version: 'c1-0123456789abcdef', computed_at: NOW};
}
const W = mmsi => ({mmsi, from: '2026-10-01T00:00:00.000Z', to: '2026-10-04T00:00:00.000Z'});
const windowBody = (windows, trips) => ({region: REGION, source: 'aisstream', replace: windows, trips});
const PROCESSED = {region: REGION, processed: {run_id: 'ais-20261005T120000Z', counts: {}}};
const landing = (id, boat, port = 'Morro Bay', date = '2026-10-01') => ({id, date, boat, port, trip_type: '3/4 Day', anglers: 20,
  catches: [{species: 'rockfish', label: 'Rockfish', count: 40, disposition: 'reported'}], source_url: 'https://example.com/counts'});
const pairs = sql => sql.prepare('SELECT trip_id,report_kind,report_ref,match,confidence,created_at FROM fleet_trip_reports ORDER BY report_kind,report_ref').all().map(r => ({...r}));

test('N2 check: a synthetic trip plus a landing report writes one fleet_trip_reports row, and a re-run keeps it', {skip}, async () => {
  const {sql, db} = database();
  try {
    const t = trip(A, '2026-10-01T15:00:00.000Z');
    await call(db, windowBody([W(A)], [t]));
    assert.deepEqual(pairs(sql), [], 'landing reports pair in the sweep, not on the window');
    feed = {reports: [landing('land0001', 'Example Star II')]};
    const body = await call(db, PROCESSED);
    assert.deepEqual(feedReads, [FEED], 'the daily feed of the port\'s region, read once');
    assert.deepEqual(body.feeds, {read: 1, unavailable: 0, reports: 1});
    assert.equal(body.changes.paired_landing, 1);
    assert.deepEqual(pairs(sql), [{trip_id: t.id, report_kind: 'landing', report_ref: 'land0001', match: 'alias-port-date', confidence: CONFIDENCE.landing, created_at: NOW}]);
    // The same run again, and the same window reprocessed: still one row.
    assert.equal((await call(db, PROCESSED)).changes.paired_landing, 0);
    assert.equal((await call(db, windowBody([W(A)], [t]))).changes.unpaired, 0);
    assert.equal(pairs(sql).length, 1);
    // The trip recomputed away: its pairing goes with it.
    assert.equal((await call(db, windowBody([W(A)], []))).changes.unpaired, 1);
    assert.deepEqual(pairs(sql), []);
  } finally { sql.close(); }
});

test('landing reports pair only on a sole vessel name, the trip\'s port and its local date', {skip}, async () => {
  const {sql, db} = database();
  try {
    const star = trip(A, '2026-10-01T15:00:00.000Z'), day = trip(B, '2026-10-01T15:00:00.000Z', {vessel: DAY, port: 'port-san-luis'});
    await call(db, windowBody([W(A), W(B)], [star, day]));
    feed = {reports: [
      landing('by-name', 'The Example Star'),                        // name_norm of STAR
      landing('by-port-label', 'Example Day', 'Avila Beach'),          // DAY at Port San Luis
      landing('twin', 'Twin Example'),                                // alias of both vessels
      landing('wrong-port', 'Example Star', 'Avila Beach'),
      landing('wrong-date', 'Example Star', 'Morro Bay', '2026-10-02'),
      landing('unknown-boat', 'Example Nobody'),
      landing('other-landing', 'Example Star', 'Santa Cruz'),         // not a port of any trip
    ]};
    await call(db, PROCESSED);
    assert.deepEqual(pairs(sql).map(p => [p.trip_id, p.report_ref]), [[star.id, 'by-name'], [day.id, 'by-port-label']]);
  } finally { sql.close(); }
});

test('an unreadable feed skips landing pairs and the run still records processed', {skip}, async () => {
  const {sql, db} = database();
  try {
    await call(db, windowBody([W(A)], [trip(A, '2026-10-01T15:00:00.000Z')]));
    feed = new Error('feed HTTP 502');
    const body = await call(db, PROCESSED);
    assert.deepEqual(body.feeds, {read: 0, unavailable: 1, reports: 0});
    assert.deepEqual(pairs(sql), []);
    assert.ok(sql.prepare("SELECT 1 FROM job_state WHERE key='fleet.ais.CA.processed'").get());
  } finally { sql.close(); }
});

test('advisor reports pair on the window when published and linked, and the sweep drops them once withdrawn', {skip}, async () => {
  const {sql, db} = database();
  try {
    const boat = sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at,fleet_vessel_id) VALUES(?,?,?,'morro-bay','morro-bay','verified',?,?,?)`);
    boat.run('boat-linked', 'example-star-adv', 'Example Star', NOW, NOW, STAR);
    boat.run('boat-unlinked', 'example-other-adv', 'Example Other', NOW, NOW, null);
    const report = sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,counts_json,source,status,created_at,updated_at) VALUES(?,?,'morro-bay','morro-bay',?,'{}',?,?,?,?)`);
    report.run('r-published', 'boat-linked', '2026-10-01', 'sms', 'published', NOW, NOW);
    report.run('r-draft', 'boat-linked', '2026-10-01', 'web', 'draft', NOW, NOW);
    report.run('r-next-day', 'boat-linked', '2026-10-02', 'sms', 'published', NOW, NOW);
    report.run('r-unlinked', 'boat-unlinked', '2026-10-01', 'sms', 'published', NOW, NOW);
    const t = trip(A, '2026-10-01T15:00:00.000Z');
    const body = await call(db, windowBody([W(A)], [t]));
    assert.equal(body.changes.paired_advisor, 1);
    assert.deepEqual(pairs(sql), [{trip_id: t.id, report_kind: 'advisor', report_ref: 'r-published', match: 'boat-date', confidence: CONFIDENCE.advisor, created_at: NOW}]);
    sql.prepare("UPDATE advisor_reports SET status='withdrawn' WHERE id='r-published'").run();
    sql.prepare("UPDATE advisor_reports SET status='published' WHERE id='r-draft'").run();
    const sweep = await call(db, PROCESSED);
    assert.equal(sweep.changes.unpaired, 1);
    assert.deepEqual(pairs(sql).map(p => p.report_ref), ['r-draft'], 'a report published after its trip pairs in the sweep');
  } finally { sql.close(); }
});

test('nameNorm matches the Python name_norm (tests/unit/test_fleet_resolve.py cases)', () => {
  for (const [raw, expected] of [['Sea Example', 'SEAEXAMPLE'], ['The Sea Example', 'SEAEXAMPLE'], ['F/V Sea-Example', 'SEAEXAMPLE'],
    ['M/V sea example ii', 'SEAEXAMPLE2'], ['Example Star IV', 'EXAMPLESTAR4'], ['New Example Star', 'NEWEXAMPLESTAR'],
    ['Niña Example', 'NINAEXAMPLE'], ['X', 'X'], ['The', 'THE'], ['Example XX', 'EXAMPLE20'], ['Reel Example 2', 'REELEXAMPLE2'], ['', '']])
    assert.equal(nameNorm(raw), expected, raw);
});

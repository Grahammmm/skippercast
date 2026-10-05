// Charter fleet AIS job routes (CF-45; docs/plans/charter-fleet/design.md § 11, § 12, § 18):
// POST /api/fleet/jobs/activity (replace-window trips, segments and events; aggregates;
// processed), POST /api/fleet/jobs/heartbeat and GET /api/fleet/jobs/health, through the
// Worker against the real migrations (tests/_advisor_d1.mjs) with the fleet job verifier
// stubbed and a fixture clock. Fixtures are synthetic (MMSIs 999xxxxxx, invented boats).
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
const {activityDeps, STALE_HOURS} = await import('../server/fleet/activity.ts');

const skip = sqliteUnavailable ?? false;
const ORIGIN = 'https://skippercast.com', REGION = 'CA';
const ASSETS = {fetch: async () => new Response('asset', {status: 299})};
const NOW = '2026-10-05T12:00:00.000Z';
const sha = s => createHash('sha256').update(s, 'utf8').digest('hex').slice(0, 32);
const VESSEL = sha('CA:test-boat-1'), OTHER_VESSEL = sha('CA:test-boat-2');
const A = '999000101', B = '999000102';

let verifierSaved, clockSaved, clock = NOW;
test.before(() => {
  verifierSaved = fleetJobs.verify; clockSaved = activityDeps.now;
  fleetJobs.verify = async token => token === 'good' ? {jti: 'run-1'} : false;
  activityDeps.now = () => new Date(clock);
});
test.after(() => { fleetJobs.verify = verifierSaved; activityDeps.now = clockSaved; });

function database() {
  const {sql, db} = advisorDatabase();
  const insert = sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)`);
  insert.run(VESSEL, REGION, 'test-boat-1', 'Test Boat 1', 'TESTBOAT1', NOW, NOW, NOW, NOW);
  insert.run(OTHER_VESSEL, REGION, 'test-boat-2', 'Test Boat 2', 'TESTBOAT2', NOW, NOW, NOW, NOW);
  return {sql, db};
}
const env = db => ({ASSETS, DB: db, FLEET_ENABLED: 'true'});
const AUTH = {Authorization: 'Bearer good'};
async function call(db, path, payload, {headers = AUTH, method = 'POST', environment} = {}) {
  const init = method === 'GET' ? {headers} : {method, headers: {'Content-Type': 'application/json', ...headers}, body: JSON.stringify(payload)};
  const response = await worker.fetch(new Request(ORIGIN + '/api/fleet/jobs/' + path, init), environment ?? env(db));
  return {status: response.status, body: await response.json()};
}

// ---- synthetic derived rows (ids as process.py derives them) ---------------------------
function trip(mmsi, departed, {source = 'aisstream', vessel = VESSEL, status = 'closed', distance = 12.5} = {}) {
  const id = sha(`${mmsi}|${departed}|${source}`);
  const row = {id, region: REGION, vessel_id: vessel, mmsi, depart_port_id: 'port-a', return_port_id: 'port-a', departed_at: departed,
    returned_at: status === 'open' ? null : departed.replace('T08', 'T13'), local_date: departed.slice(0, 10), season: '2026', season_part: 'fall',
    status, trip_type_inferred: null, distance_nm: distance, max_offshore_nm: 4.2, fishing_min: 70, positions_n: 300, gap_min: 0,
    source, rights: source === 'marinecadastre' ? 'noaa-planning-only' : 'internal-only', classifier_version: 'c1-0123456789abcdef', computed_at: NOW};
  const segments = [0, 1, 2].map(seq => ({id: sha(`${id}|${seq}`), trip_id: id, seq, kind: ['transit', 'fishing-drift', 'transit'][seq],
    started_at: departed.replace(':00:00.000Z', `:${10 + seq}:00.000Z`), ended_at: departed.replace(':00:00.000Z', `:${11 + seq}:00.000Z`),
    geometry: '_p~iF~ps|U_ulLnnqC', points_n: 20, mean_sog: 1.2, straightness: 0.4, heading_var: 0.5}));
  const started = segments[1].started_at;
  const events = [{id: sha(`${id}|${started}|drift-anchor`), trip_id: id, segment_id: segments[1].id, vessel_id: vessel, region: REGION,
    kind: 'drift-anchor', lat: 35.3, lon: -120.9, radius_m: 140.5, started_at: started, ended_at: segments[1].ended_at, dwell_min: 40,
    port_id: 'port-a', vessel_class: 'inspected-party', trip_type: null, season: '2026', season_part: 'fall', basis: 'inferred-from-movement',
    source, rights: row.rights, classifier_version: row.classifier_version, species_json: null}];
  return {trip: row, segments, events};
}
const W = (mmsi, from = '2026-10-01T00:00:00.000Z', to = '2026-10-04T00:00:00.000Z') => ({mmsi, from, to});
function replaceBody(windows, parts, source = 'aisstream') {
  return {region: REGION, source, replace: windows, trips: parts.map(p => p.trip), segments: parts.flatMap(p => p.segments), events: parts.flatMap(p => p.events)};
}
const TABLES = ['fleet_trips', 'fleet_segments', 'fleet_events', 'fleet_segment_labels', 'fleet_aggregates', 'fleet_ais_hours', 'job_state'];
const dump = sql => Object.fromEntries(TABLES.map(t => [t, sql.prepare(`SELECT * FROM ${t} ORDER BY 1, 2`).all()]));
const ids = (sql, table) => sql.prepare(`SELECT id FROM ${table} ORDER BY id`).all().map(r => r.id);

test('AIS job routes are dark without FLEET_ENABLED and need the fleet job identity', {skip}, async () => {
  const {sql, db} = database();
  try {
    for (const [path, method] of [['activity', 'POST'], ['heartbeat', 'POST'], [`health?region=${REGION}`, 'GET']]) {
      assert.equal((await call(db, path, {region: REGION}, {method, environment: {ASSETS, DB: db}})).status, 404, path);
      assert.equal((await call(db, path, {region: REGION}, {method, headers: {Authorization: 'Bearer bad'}})).status, 401, path);
    }
  } finally { sql.close(); }
});

test('reprocessing a window twice leaves identical rows', {skip}, async () => {
  const {sql, db} = database();
  try {
    const body = replaceBody([W(A)], [trip(A, '2026-10-01T08:00:00.000Z'), trip(A, '2026-10-02T08:00:00.000Z', {status: 'open'})]);
    const first = await call(db, 'activity', body);
    assert.equal(first.status, 200, JSON.stringify(first.body));
    assert.deepEqual(first.body.changes, {deleted_events: 0, deleted_segments: 0, deleted_trips: 0, trips: 2, segments: 6, events: 2});
    const before = dump(sql);
    const second = await call(db, 'activity', body);
    assert.equal(second.status, 200);
    assert.deepEqual(second.body.changes, {deleted_events: 2, deleted_segments: 6, deleted_trips: 2, trips: 2, segments: 6, events: 2});
    assert.deepEqual(dump(sql), before);
    // A window recomputed with fewer trips (the open one went away) drops it with its children.
    const third = await call(db, 'activity', replaceBody([W(A)], [trip(A, '2026-10-01T08:00:00.000Z')]));
    assert.equal(third.status, 200);
    assert.equal(ids(sql, 'fleet_trips').length, 1);
    assert.equal(ids(sql, 'fleet_segments').length, 3);
    assert.equal(ids(sql, 'fleet_events').length, 1);
  } finally { sql.close(); }
});

test('replace-window touches only the given MMSIs, source and window', {skip}, async () => {
  const {sql, db} = database();
  try {
    const inside = trip(A, '2026-10-02T08:00:00.000Z');
    const outside = trip(A, '2026-10-05T08:00:00.000Z');                                 // A, later departure
    const otherMmsi = trip(B, '2026-10-02T08:00:00.000Z', {vessel: OTHER_VESSEL});        // B, same window
    const backfill = trip(A, '2026-10-02T09:00:00.000Z', {source: 'marinecadastre'});      // A, other source
    assert.equal((await call(db, 'activity', replaceBody([W(A), W(A, '2026-10-05T00:00:00.000Z', '2026-10-06T00:00:00.000Z'), W(B)], [inside, outside, otherMmsi]))).status, 200);
    assert.equal((await call(db, 'activity', replaceBody([W(A)], [backfill], 'marinecadastre'))).status, 200);
    sql.prepare(`INSERT INTO fleet_segment_labels(id,trip_id,started_at,ended_at,label,labeller,basis,created_at) VALUES('label-1',?,?,?,'fishing-drift','agent:test','synthetic',?)`)
      .run(inside.trip.id, inside.segments[1].started_at, inside.segments[1].ended_at, NOW);
    // Every derived row except the replaced trip's own.
    const others = () => ['fleet_trips', 'fleet_segments', 'fleet_events'].map(t =>
      sql.prepare(`SELECT * FROM ${t} ORDER BY id`).all().filter(r => r.id !== inside.trip.id && r.trip_id !== inside.trip.id));
    const untouched = others();
    assert.equal(untouched.flat().length, 3 * 5, 'three other trips, each with three segments and one event');

    // A's aisstream window again, recomputed with a different distance: only that trip and its children change.
    const recomputed = trip(A, '2026-10-02T08:00:00.000Z', {distance: 20.25});
    const result = await call(db, 'activity', replaceBody([W(A)], [recomputed]));
    assert.equal(result.status, 200, JSON.stringify(result.body));
    assert.deepEqual(result.body.changes, {deleted_events: 1, deleted_segments: 3, deleted_trips: 1, trips: 1, segments: 3, events: 1});
    assert.equal(sql.prepare('SELECT distance_nm FROM fleet_trips WHERE id=?').get(inside.trip.id).distance_nm, 20.25);
    assert.deepEqual(others(), untouched);
    assert.deepEqual(ids(sql, 'fleet_trips').sort(), [inside, outside, otherMmsi, backfill].map(p => p.trip.id).sort());
    assert.equal(sql.prepare('SELECT count(*) n FROM fleet_segment_labels').get().n, 1, 'labels survive reprocessing');

    // An empty window deletes that window's trips and nothing else.
    assert.equal((await call(db, 'activity', replaceBody([W(B)], []))).status, 200);
    assert.deepEqual(ids(sql, 'fleet_trips').sort(), [inside, outside, backfill].map(p => p.trip.id).sort());
  } finally { sql.close(); }
});

test('invalid activity is refused with nothing written', {skip}, async () => {
  const {sql, db} = database();
  try {
    const good = trip(A, '2026-10-02T08:00:00.000Z');
    const cases = [
      ['outside its window', replaceBody([W(A, '2026-10-03T00:00:00.000Z', '2026-10-04T00:00:00.000Z')], [good])],
      ['another MMSI window', replaceBody([W(B)], [good])],
      ['source mismatch', replaceBody([W(A)], [good], 'marinecadastre')],
      ['bad trip id', replaceBody([W(A)], [{...good, trip: {...good.trip, id: sha('x')}}])],
      ['unknown vessel', replaceBody([W(A)], [trip(A, '2026-10-02T08:00:00.000Z', {vessel: sha('nobody')})])],
      ['confirmed basis', replaceBody([W(A)], [{...good, events: [{...good.events[0], basis: 'confirmed'}]}])],
      ['orphan segment', {...replaceBody([W(A)], [good]), trips: []}],
      ['unknown field', {...replaceBody([W(A)], [good]), extra: 1}],
      ['rows without a window', {...replaceBody([], [good])}],
      ['backwards window', replaceBody([W(A, '2026-10-04T00:00:00.000Z', '2026-10-01T00:00:00.000Z')], [])],
    ];
    for (const [name, body] of cases) {
      const result = await call(db, 'activity', body);
      assert.equal(result.status, 400, `${name}: ${JSON.stringify(result.body)}`);
    }
    assert.equal(ids(sql, 'fleet_trips').length, 0);
    const big = await call(db, 'activity', {region: REGION, source: 'aisstream', replace: Array(51).fill(W(A))});
    assert.equal(big.status, 400);
  } finally { sql.close(); }
});

test('aggregates upsert, delete listed cells and prune a full rebuild', {skip}, async () => {
  const {sql, db} = database();
  try {
    const cell = (n, computed = NOW, season = '2026') => ({id: sha(`cell-${n}-${season}`), region: REGION, module: 'grid', params_json: '{"module":"grid"}',
      cell_id: `g1000:${n}:1`, lat: 35 + n / 100, lon: -121, season, season_part: null, kind: 'drift-anchor', vessels_n: 2, events_n: 3,
      dwell_min: 90, first_date: '2026-10-01', last_date: '2026-10-02', rights: 'internal-only', computed_at: computed});
    const post = aggregates => call(db, 'activity', {region: REGION, aggregates: {module: 'grid', ...aggregates}});
    assert.equal((await post({season: '2026', cells: [cell(1), cell(2), cell(3)]})).status, 200);
    assert.equal((await post({season: '2025', cells: [cell(9, NOW, '2025')]})).status, 200);
    assert.equal((await post({season: '2026', cells: [{...cell(1), dwell_min: 120}], delete: [cell(3).id]})).status, 200);
    assert.deepEqual(sql.prepare('SELECT cell_id, dwell_min FROM fleet_aggregates WHERE season=? ORDER BY cell_id').all('2026').map(r => ({...r})),
      [{cell_id: 'g1000:1:1', dwell_min: 120}, {cell_id: 'g1000:2:1', dwell_min: 90}]);
    sql.prepare(`INSERT INTO fleet_aggregates(id,region,module,params_json,cell_id,lat,lon,season,kind,rights,computed_at) VALUES(?,?,'h3','{}','h3:x',35,-121,'2026','troll','internal-only',?)`)
      .run(sha('h3-cell'), REGION, NOW);
    const later = '2026-10-05T12:30:00.000Z';
    assert.equal((await post({season: '2026', cells: [cell(2, later), cell(4, later)], prune: later})).status, 200);
    assert.deepEqual(sql.prepare(`SELECT cell_id FROM fleet_aggregates WHERE season=? AND module='grid' ORDER BY cell_id`).all('2026').map(r => r.cell_id), ['g1000:2:1', 'g1000:4:1']);
    assert.equal(sql.prepare(`SELECT count(*) n FROM fleet_aggregates WHERE module='h3'`).get().n, 1, 'a prune never touches another module');
    assert.equal(sql.prepare('SELECT count(*) n FROM fleet_aggregates WHERE season=?').get('2025').n, 1, 'other seasons are never pruned');
    assert.equal((await post({season: '2026', cells: [cell(5, NOW, '2025')]})).status, 400, 'a cell of another season');
    assert.equal((await post({season: '2026', module: 'h3', cells: [cell(5)]})).status, 400, 'a cell of another module');
  } finally { sql.close(); }
});

test('heartbeat stores the listener state and hourly counters idempotently; processed sets job_state', {skip}, async () => {
  const {sql, db} = database();
  try {
    const hours = [{hour: '2026-10-05T10:00:00.000Z', messages: 24000, watched_messages: 500, vessels: 210, reconnects: 1, max_gap_s: 42, dropped: 0},
      {hour: '2026-10-05T11:00:00.000Z', messages: 23000, watched_messages: 450, vessels: 205, reconnects: 0, max_gap_s: 30, dropped: 3}];
    const beat = {source: 'aisstream', written_at: '2026-10-05T11:58:00Z', started_at: '2026-10-04T00:00:00Z', last_message_at: '2026-10-05T11:57:59Z',
      connected: true, messages_per_min: 400, watched_messages_per_min: 8, vessels: 200, reconnects: 3, dropped: 3, queue_depth: 2, watch_size: 12, git_sha: 'abc123'};
    const body = {region: REGION, heartbeat: beat, hours, messages_24h: 47000};
    assert.equal((await call(db, 'heartbeat', body)).status, 200);
    const before = dump(sql);
    assert.equal((await call(db, 'heartbeat', body)).status, 200);
    assert.deepEqual(dump(sql), before);
    assert.deepEqual(sql.prepare('SELECT hour, messages, dropped FROM fleet_ais_hours ORDER BY hour').all().map(r => ({...r})),
      [{hour: '2026-10-05T10:00:00.000Z', messages: 24000, dropped: 0}, {hour: '2026-10-05T11:00:00.000Z', messages: 23000, dropped: 3}]);
    const stored = JSON.parse(sql.prepare('SELECT value FROM job_state WHERE key=?').get('fleet.ais.CA.heartbeat').value);
    assert.equal(stored.last_message_at, beat.last_message_at);
    assert.equal(stored.received_at, NOW);
    assert.equal(stored.messages_24h, 47000);
    assert.equal((await call(db, 'heartbeat', {...body, heartbeat: {...beat, password: 'x'}})).status, 400, 'unknown heartbeat fields are refused');
    assert.equal((await call(db, 'heartbeat', {...body, hours: [{...hours[0], hour: '2026-10-05T10:30:00.000Z'}]})).status, 400, 'hours start on the hour');

    assert.equal((await call(db, 'activity', {region: REGION, processed: {run_id: 'ais-20261005T120000Z', counts: {trips: {trips: 2}}}})).status, 200);
    const processed = JSON.parse(sql.prepare('SELECT value FROM job_state WHERE key=?').get('fleet.ais.CA.processed').value);
    assert.deepEqual(processed, {at: NOW, run_id: 'ais-20261005T120000Z', counts: {trips: {trips: 2}}});
  } finally { sql.close(); }
});

test('health reports stale beyond 3 hours on a fixture clock, with ages and booleans only', {skip}, async () => {
  const {sql, db} = database();
  try {
    const health = async () => (await call(db, `health?region=${REGION}`, null, {method: 'GET'})).body;
    clock = NOW;
    let body = await health();
    assert.equal(body.stale, true, 'nothing pushed yet');
    assert.deepEqual(body.checks.processed, {age_s: null, stale: true});

    await call(db, 'heartbeat', {region: REGION, heartbeat: {written_at: '2026-10-05T12:00:00.000Z', last_message_at: '2026-10-05T12:00:00Z'}, hours: []});
    await call(db, 'activity', {region: REGION, processed: {run_id: 'ais-1', counts: {}}});
    clock = '2026-10-05T15:00:00.000Z';                       // exactly 3 h later: not yet stale
    body = await health();
    assert.equal(body.stale, false, JSON.stringify(body));
    assert.deepEqual(body.checks.heartbeat, {age_s: STALE_HOURS * 3600, stale: false});
    clock = '2026-10-05T15:00:01.000Z';                       // one second more: stale
    body = await health();
    assert.equal(body.stale, true);
    assert.deepEqual(Object.keys(body).sort(), ['checked_at', 'checks', 'region', 'stale', 'stale_after_s']);
    for (const name of ['heartbeat', 'last_message', 'processed']) assert.deepEqual(body.checks[name], {age_s: 3 * 3600 + 1, stale: true});
    assert.equal(JSON.stringify(body).includes('messages'), false, 'no counters or listener state in the health answer');
    assert.equal((await call(db, 'health?region=..', null, {method: 'GET'})).status, 400);
  } finally { clock = NOW; sql.close(); }
});

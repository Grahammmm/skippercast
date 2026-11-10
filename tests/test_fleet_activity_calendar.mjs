// RF1345-8: the AIS job routes (server/fleet/activity.ts) key rows by their written dates and clocks, so a
// date Date.parse would roll into another day (February 30, a non-leap February 29, April 31, 24:00) is
// refused with the field's path and nothing written, while every valid precision is stored verbatim.
// Through the Worker against the real migrations (tests/_advisor_d1.mjs), fleet job verifier stubbed,
// fixture clock. Fixtures are synthetic (MMSIs 999xxxxxx, invented boats).
import test from 'node:test';
import assert from 'node:assert/strict';
import util from 'node:util';
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

const skip = sqliteUnavailable ?? false;
const ORIGIN = 'https://skippercast.com', REGION = 'CA', NOW = '2026-10-05T12:00:00.000Z';
const ASSETS = {fetch: async () => new Response('asset', {status: 299})};
const sha = s => createHash('sha256').update(s, 'utf8').digest('hex').slice(0, 32);
const VESSEL = sha('CA:test-boat-1'), A = '999000101';

let verifierSaved, clockSaved;
test.before(() => {
  verifierSaved = fleetJobs.verify; clockSaved = activityDeps.now;
  fleetJobs.verify = async token => token === 'good' ? {jti: 'run-1'} : false;
  activityDeps.now = () => new Date(NOW);
});
test.after(() => { fleetJobs.verify = verifierSaved; activityDeps.now = clockSaved; });

function database() {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)`)
    .run(VESSEL, REGION, 'test-boat-1', 'Test Boat 1', 'TESTBOAT1', NOW, NOW, NOW, NOW);
  const points = [];
  return {sql, db, points, env: {ASSETS, DB: db, FLEET_ENABLED: 'true', ANALYTICS: {writeDataPoint: p => { if (p.indexes[0] === 'fleet_ais') points.push(p); }}}};
}
async function call(ctx, path, payload) {
  const init = {method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer good'}, body: JSON.stringify(payload)};
  const response = await worker.fetch(new Request(ORIGIN + '/api/fleet/jobs/' + path, init), ctx.env);
  return {status: response.status, body: await response.json()};
}

// Synthetic derived rows; ids derive from the written strings, as process.py derives them.
function trip(departed) {
  const id = sha(`${A}|${departed}|aisstream`);
  const row = {id, region: REGION, vessel_id: VESSEL, mmsi: A, depart_port_id: null, return_port_id: null, departed_at: departed,
    returned_at: departed.replace('T08', 'T13'), local_date: departed.slice(0, 10), season: departed.slice(0, 4), season_part: null, status: 'closed',
    trip_type_inferred: null, distance_nm: 12.5, max_offshore_nm: 4.2, fishing_min: 70, positions_n: 300, gap_min: 0, source: 'aisstream',
    rights: 'internal-only', classifier_version: 'c1-0123456789abcdef', computed_at: NOW};
  const started = departed.replace(':00:00.000Z', ':10:00.000Z'), ended = departed.replace(':00:00.000Z', ':50:00.000Z');
  const segment = {id: sha(`${id}|0`), trip_id: id, seq: 0, kind: 'drift-anchor', started_at: started, ended_at: ended, geometry: null,
    points_n: 20, mean_sog: 1.2, p90_sog: null, distance_nm: null, straightness: 0.4, heading_var: 0.5};
  const event = {id: sha(`${id}|${started}|drift-anchor`), trip_id: id, segment_id: segment.id, vessel_id: VESSEL, region: REGION,
    kind: 'drift-anchor', lat: 35.3, lon: -120.9, radius_m: 140.5, started_at: started, ended_at: ended, dwell_min: 40, port_id: null,
    vessel_class: null, trip_type: null, season: row.season, season_part: null, basis: 'inferred-from-movement', source: 'aisstream',
    rights: 'internal-only', classifier_version: row.classifier_version, species_json: null};
  return {trip: row, segments: [segment], events: [event]};
}
const W = (from = '2026-10-01T00:00:00.000Z', to = '2026-10-04T00:00:00.000Z') => ({mmsi: A, from, to});
const replaceBody = (windows, parts) => ({region: REGION, source: 'aisstream', replace: windows,
  trips: parts.map(p => p.trip), segments: parts.flatMap(p => p.segments), events: parts.flatMap(p => p.events)});
const cell = (n, over = {}) => ({id: sha(`cell-${n}`), region: REGION, module: 'grid', params_json: '{}', cell_id: `g1000:${n}:1`, lat: 35, lon: -121,
  season: '2026', season_part: null, kind: 'drift-anchor', vessels_n: 2, events_n: 3, dwell_min: 90, first_date: '2026-10-01',
  last_date: '2026-10-02', rights: 'internal-only', computed_at: NOW, ...over});
const hour = (h, messages = 100) => ({hour: h, messages, watched_messages: 5, vessels: 9, reconnects: 0, max_gap_s: 10, dropped: 0});
const beat = (over = {}) => ({source: 'aisstream', written_at: '2026-10-05T11:58:00Z', started_at: '2026-10-04T00:00:00Z',
  last_message_at: '2026-10-05T11:57:59Z', connected: true, ...over});

const TABLES = ['fleet_trips', 'fleet_segments', 'fleet_events', 'fleet_segment_labels', 'fleet_trip_reports', 'fleet_aggregates', 'fleet_ais_hours', 'job_state'];
const dump = sql => Object.fromEntries(TABLES.map(t => [t, sql.prepare(`SELECT * FROM ${t} ORDER BY 1, 2`).all().map(r => ({...r}))]));
const storedBeat = sql => JSON.parse(sql.prepare('SELECT value FROM job_state WHERE key=?').get('fleet.ais.CA.heartbeat').value);
const ROLLED = ['2026-02-30', '2025-02-29', '2026-04-31'];

test('invalid_utc_calendar_and_midnight_rollover_refuse', {skip}, async () => {
  const ctx = database();
  try {
    const refuse = async (path, body, error) => {
      const result = await call(ctx, path, body);
      assert.equal(result.status, 400, `${error}: ${JSON.stringify(result.body)}`);
      assert.equal(result.body.error, error);
    };
    for (const day of ROLLED) {
      await refuse('heartbeat', {region: REGION, heartbeat: beat({written_at: `${day}T12:00:00Z`})}, 'heartbeat.written_at: invalid');
      await refuse('heartbeat', {region: REGION, heartbeat: beat({last_message_at: `${day}T12:00:00.123456Z`})}, 'heartbeat.last_message_at: invalid');
      await refuse('heartbeat', {region: REGION, hours: [hour(`${day}T12:00:00.000Z`)]}, 'hours[0].hour: invalid');
      await refuse('activity', replaceBody([W(`${day}T00:00:00.000Z`)], []), 'replace[0].from: invalid');
      await refuse('activity', {region: REGION, aggregates: {module: 'grid', season: '2026', cells: [cell(1, {first_date: day})]}}, 'aggregates.cells[0].first_date: invalid');
    }
    // 24:00 is the next day's 00:00 to Date.parse; as a key it is neither.
    await refuse('heartbeat', {region: REGION, heartbeat: beat({written_at: '2026-11-09T24:00:00.000Z'})}, 'heartbeat.written_at: invalid');
    await refuse('heartbeat', {region: REGION, heartbeat: beat({started_at: '2026-11-09T24:00:00Z'})}, 'heartbeat.started_at: invalid');
    await refuse('heartbeat', {region: REGION, hours: [hour('2026-11-09T24:00:00.000Z')]}, 'hours[0].hour: invalid');
    await refuse('activity', replaceBody([W('2026-10-01T00:00:00.000Z', '2026-10-03T24:00:00.000Z')], []), 'replace[0].to: invalid');
    await refuse('activity', {region: REGION, aggregates: {module: 'grid', season: '2026', prune: '2026-10-05T24:00:00.000Z'}}, 'aggregates.prune: invalid');
    for (const clock of ['2026-11-09T23:60:00Z', '2026-11-09T23:59:60Z', '2026-13-01T00:00:00Z', '2026-00-10T00:00:00Z'])
      await refuse('heartbeat', {region: REGION, heartbeat: beat({written_at: clock})}, 'heartbeat.written_at: invalid');
    assert.ok(util.isDeepStrictEqual(dump(ctx.sql), dump(advisorDatabase().sql)), 'nothing was written');
    assert.equal(ctx.points.length, 0, 'no heartbeat analytics for a refused request');
  } finally { ctx.sql.close(); }
});

test('every_activity_date_kind_uses_real_calendar', {skip}, async () => {
  const ctx = database();
  try {
    const good = trip('2026-10-01T08:00:00.000Z'), later = trip('2026-10-02T08:00:00.000Z');
    const second = (part, field, value) => {   // the valid neighbouring row stays first; the mutated one is second
      const changed = {...later, trip: {...later.trip}, segments: [{...later.segments[0]}], events: [{...later.events[0]}]};
      (part === 'trip' ? changed.trip : part === 'segment' ? changed.segments[0] : changed.events[0])[field] = value;
      return replaceBody([W()], [good, changed]);
    };
    const cells = over => ({region: REGION, aggregates: {module: 'grid', season: '2026', cells: [cell(1), cell(2, over)]}});
    const cases = [
      [replaceBody([W(), W('2026-10-01T00:00:00.000Z', '2026-02-30T00:00:00.000Z')], [good]), 'replace[1].to: invalid'],
      [second('trip', 'departed_at', '2026-04-31T08:00:00.000Z'), 'trips[1].departed_at: invalid'],
      [second('trip', 'returned_at', '2026-10-02T24:00:00.000Z'), 'trips[1].returned_at: invalid'],
      [second('trip', 'local_date', '2026-02-30'), 'trips[1].local_date: invalid'],
      [second('trip', 'computed_at', '2025-02-29T12:00:00.000Z'), 'trips[1].computed_at: invalid'],
      [second('segment', 'started_at', '2026-09-31T08:10:00.000Z'), 'segments[1].started_at: invalid'],
      [second('segment', 'ended_at', '2026-10-02T24:00:00.000Z'), 'segments[1].ended_at: invalid'],
      [second('event', 'started_at', '2026-06-31T08:10:00.000Z'), 'events[1].started_at: invalid'],
      [second('event', 'ended_at', '2026-11-31T08:50:00.000Z'), 'events[1].ended_at: invalid'],
      [cells({first_date: '2026-02-29'}), 'aggregates.cells[1].first_date: invalid'],
      [cells({last_date: '2026-02-31'}), 'aggregates.cells[1].last_date: invalid'],
      [cells({computed_at: '2026-04-31T12:00:00.000Z'}), 'aggregates.cells[1].computed_at: invalid'],
      [{region: REGION, aggregates: {module: 'grid', season: '2026', cells: [cell(1)], prune: '2026-02-30T12:00:00.000Z'}}, 'aggregates.prune: invalid'],
    ];
    for (const [body, error] of cases) {
      const result = await call(ctx, 'activity', body);
      assert.equal(result.status, 400, `${error}: ${JSON.stringify(result.body)}`);
      assert.equal(result.body.error, error);
    }
    assert.equal(ctx.sql.prepare('SELECT count(*) n FROM fleet_trips').get().n, 0);
    assert.equal(ctx.sql.prepare('SELECT count(*) n FROM fleet_aggregates').get().n, 0);
    // The same rows with the neighbouring valid dates are admitted.
    assert.equal((await call(ctx, 'activity', replaceBody([W()], [good, later]))).status, 200);
    assert.equal((await call(ctx, 'activity', cells({}))).status, 200);
  } finally { ctx.sql.close(); }
});

test('mixed_invalid_request_preserves_all_prior_state', {skip}, async () => {
  const ctx = database(), {sql} = ctx;
  try {
    const old = trip('2026-10-01T08:00:00.000Z');
    assert.equal((await call(ctx, 'activity', replaceBody([W()], [old]))).status, 200);
    assert.equal((await call(ctx, 'activity', {region: REGION, aggregates: {module: 'grid', season: '2026', cells: [cell(1), cell(2)]}})).status, 200);
    assert.equal((await call(ctx, 'heartbeat', {region: REGION, heartbeat: beat(), hours: [hour('2026-10-05T10:00:00.000Z')], messages_24h: 9})).status, 200);
    sql.prepare(`INSERT INTO fleet_segment_labels(id,trip_id,started_at,ended_at,label,labeller,basis,created_at) VALUES('label-1',?,?,?,'drift-anchor','agent:test','synthetic',?)`)
      .run(old.trip.id, old.segments[0].started_at, old.segments[0].ended_at, NOW);
    sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run('fleet.ais.CA.processed', '{"at":"2026-10-05T11:00:00.000Z","run_id":"ais-0"}', NOW);
    const before = dump(sql), points = ctx.points.length;
    assert.equal(points, 1, 'the valid heartbeat wrote its fleet_ais point');
    assert.equal(before.fleet_trips.length, 1);
    assert.equal(before.fleet_aggregates.length, 2);

    // A full replacement (delete the window, insert a new trip), cell upsert, delete and prune, with one bad date last.
    const fresh = trip('2026-10-02T08:00:00.000Z');
    const activity = {...replaceBody([W()], [fresh]), aggregates: {module: 'grid', season: '2026', delete: [cell(2).id],
      prune: '2026-10-05T12:30:00.000Z', cells: [cell(3, {computed_at: '2026-10-05T12:30:00.000Z'}), cell(4, {last_date: '2026-02-30'})]},
      processed: {run_id: 'ais-1', counts: {}}};
    let result = await call(ctx, 'activity', activity);
    assert.equal(result.status, 400);
    assert.equal(result.body.error, 'aggregates.cells[1].last_date: invalid');
    // Hour upserts and the heartbeat, with one rolled-over hour or clock after valid ones.
    result = await call(ctx, 'heartbeat', {region: REGION, heartbeat: beat({written_at: '2026-10-05T11:59:00Z'}), messages_24h: 10,
      hours: [hour('2026-10-05T10:00:00.000Z', 999), hour('2026-10-05T11:00:00.000Z'), hour('2026-10-05T24:00:00.000Z')]});
    assert.equal(result.status, 400);
    assert.equal(result.body.error, 'hours[2].hour: invalid');
    result = await call(ctx, 'heartbeat', {region: REGION, heartbeat: beat({last_message_at: '2026-02-29T11:59:00.5Z'}), hours: [hour('2026-10-05T10:00:00.000Z', 999)]});
    assert.equal(result.status, 400);
    assert.equal(result.body.error, 'heartbeat.last_message_at: invalid');

    assert.ok(util.isDeepStrictEqual(dump(sql), before), 'trips, children, labels, cells, hours and job_state unchanged');
    assert.equal(ctx.points.length, points, 'no heartbeat analytics point for a refused request');
  } finally { sql.close(); }
});

test('leap_days_and_all_heartbeat_precisions_stay_literal', {skip}, async () => {
  const ctx = database(), {sql} = ctx;
  try {
    const clocks = ['2024-02-29T12:00:00Z', '2000-02-29T00:00:00Z', '2026-12-31T23:59:59Z', '2026-10-05T11:58:00.1Z', '2026-10-05T11:58:00.12Z',
      '2026-10-05T11:58:00.123Z', '2026-10-05T11:58:00.1234Z', '2026-10-05T11:58:00.12345Z', '2026-10-05T11:58:00.123456Z', '2024-02-29T23:59:59.999999Z'];
    for (const clock of clocks) {
      const result = await call(ctx, 'heartbeat', {region: REGION, heartbeat: beat({written_at: clock, last_message_at: clock})});
      assert.equal(result.status, 200, `${clock}: ${JSON.stringify(result.body)}`);
      const stored = storedBeat(sql);
      assert.equal(stored.written_at, clock, 'written_at kept verbatim');
      assert.equal(stored.last_message_at, clock, 'last_message_at kept verbatim');
    }
    const century = await call(ctx, 'heartbeat', {region: REGION, heartbeat: beat({written_at: '1900-02-29T12:00:00Z'})});
    assert.equal(century.status, 400);
    assert.equal(century.body.error, 'heartbeat.written_at: invalid');

    const hours = ['2024-02-29T00:00:00.000Z', '2024-02-29T23:00:00.000Z', '2000-02-29T05:00:00.000Z'];
    assert.equal((await call(ctx, 'heartbeat', {region: REGION, hours: hours.map(h => hour(h))})).status, 200);
    assert.ok(util.isDeepStrictEqual(sql.prepare('SELECT hour FROM fleet_ais_hours ORDER BY hour').all().map(r => r.hour), [...hours].sort()));

    const leap = trip('2024-02-29T08:00:00.000Z');
    assert.equal((await call(ctx, 'activity', replaceBody([W('2024-02-29T00:00:00.000Z', '2024-03-01T00:00:00.000Z')], [leap]))).status, 200);
    const row = sql.prepare('SELECT departed_at, returned_at, local_date FROM fleet_trips').get();
    assert.ok(util.isDeepStrictEqual({...row}, {departed_at: '2024-02-29T08:00:00.000Z', returned_at: '2024-02-29T13:00:00.000Z', local_date: '2024-02-29'}));
    const cells = {region: REGION, aggregates: {module: 'grid', season: '2026', cells: [cell(1, {first_date: '2000-02-29', last_date: '2024-02-29'})]}};
    assert.equal((await call(ctx, 'activity', cells)).status, 200);
    assert.equal((await call(ctx, 'activity', {region: REGION, aggregates: {module: 'grid', season: '2026', cells: [cell(2, {first_date: '1900-02-29'})]}})).body.error,
      'aggregates.cells[0].first_date: invalid');
  } finally { ctx.sql.close(); }
});

test('optional_clocks_and_valid_replay_keep_existing_contract', {skip}, async () => {
  const ctx = database(), {sql} = ctx;
  try {
    const optional = {region: REGION, heartbeat: {written_at: '2026-10-05T11:58:00.5Z', started_at: null}, hours: [hour('2026-10-05T10:00:00.000Z')]};
    assert.equal((await call(ctx, 'heartbeat', optional)).status, 200);
    assert.equal(storedBeat(sql).started_at, null);
    assert.equal((await call(ctx, 'heartbeat', {region: REGION, heartbeat: null, hours: []})).status, 200, 'a null heartbeat is still accepted');
    const nullDates = {region: REGION, aggregates: {module: 'grid', season: '2026', cells: [cell(1, {first_date: null, last_date: null})]}};
    assert.equal((await call(ctx, 'activity', nullDates)).status, 200);
    const job = replaceBody([W()], [trip('2026-10-01T08:00:00.000Z')]);
    job.trips[0].returned_at = null;
    assert.equal((await call(ctx, 'activity', job)).status, 200);

    // A valid job replayed leaves identical rows.
    const replay = {region: REGION, heartbeat: beat(), hours: [hour('2026-10-05T11:00:00.000Z')], messages_24h: 3};
    assert.equal((await call(ctx, 'heartbeat', replay)).status, 200);
    assert.equal((await call(ctx, 'activity', job)).status, 200);
    const before = dump(sql);
    assert.equal((await call(ctx, 'heartbeat', replay)).status, 200);
    assert.equal((await call(ctx, 'activity', job)).status, 200);
    assert.ok(util.isDeepStrictEqual(dump(sql), before), 'replay leaves identical rows');

    // No new grammar: whitespace, offsets, lower-case z, expanded years and over-long fractions stay refused.
    for (const clock of [' 2026-10-05T11:58:00Z', '2026-10-05T11:58:00Z ', '2026-10-05T11:58:00+00:00', '2026-10-05T11:58:00z',
      '+002026-10-05T11:58:00Z', '2026-10-05T11:58:00.1234567Z', '2026-10-05 11:58:00Z']) {
      const result = await call(ctx, 'heartbeat', {region: REGION, heartbeat: beat({written_at: clock})});
      assert.equal(result.status, 400, JSON.stringify(clock));
    }
    assert.ok(util.isDeepStrictEqual(dump(sql), before), 'refused clocks wrote nothing');
  } finally { ctx.sql.close(); }
});

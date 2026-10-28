// SP1301-EVENT-SEGMENT (SP-13-v2): POST /api/fleet/jobs/activity must refuse an event whose
// segment belongs to a different trip of the same request, before any D1 read or batch.
// Calls server/fleet/activity.ts `activity` directly with a migration-backed in-memory D1
// (tests/_advisor_d1.mjs) wrapped in a call-counting spy. Synthetic inputs only: parameters
// in tests/fixtures/sp1301_event_segment/request.json (invented vessels, 999-series MMSIs,
// fixed clock); every trip/segment/event id is derived here as design § 5 prescribes.
//
// SP1301_SUITE=baseline registers only the A4 pair ('primary regression', 'healthy control')
// so the acceptance helper's baseline mode runs exactly two tests with nothing skipped.
// Docs: docs/engineering/sp1301_event_segment.md.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS ??= {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT ??= read('../deployments/production.json');
const {activity, activityDeps} = await import('../server/fleet/activity.ts');

const FIX = read('./fixtures/sp1301_event_segment/request.json');
const BASELINE_ONLY = process.env.SP1301_SUITE === 'baseline';
const skip = sqliteUnavailable ?? false;
const sha = s => createHash('sha256').update(s, 'utf8').digest('hex').slice(0, 32);
const REGION = FIX.region, SOURCE = FIX.source, NOW = FIX.now;
const VESSELS = Object.fromEntries(FIX.vessels.map(v => [v.key, {...v, id: sha(`${REGION}:${v.slug}`)}]));
const RELATION_ERROR = i => `events[${i}]: segment belongs to another trip`;
const MISSING_ERROR = i => `events[${i}]: trip or segment not in this request`;

let clockSaved;
test.before(() => { clockSaved = activityDeps.now; activityDeps.now = () => new Date(NOW); });
test.after(() => { activityDeps.now = clockSaved; });

// ---- synthetic derived rows -------------------------------------------------------------
function build(spec) {
  const vessel = VESSELS[spec.vessel].id, departed = spec.departed_at;
  const id = sha(`${spec.mmsi}|${departed}|${SOURCE}`);
  const minute = n => departed.replace(':00:00.000Z', `:${String(10 + n).padStart(2, '0')}:00.000Z`);
  const trip = {id, region: REGION, vessel_id: vessel, mmsi: spec.mmsi, depart_port_id: 'port-sp1301', return_port_id: 'port-sp1301',
    departed_at: departed, returned_at: departed.replace(/T0(\d)/, (_, h) => `T1${h}`), local_date: departed.slice(0, 10), season: '2026',
    season_part: 'fall', status: 'closed', trip_type_inferred: null, distance_nm: 9.5, max_offshore_nm: 3.1, fishing_min: 55, positions_n: 240,
    gap_min: 0, source: SOURCE, rights: 'internal-only', classifier_version: FIX.classifier_version, computed_at: NOW};
  const segments = FIX.segment_kinds.map((kind, seq) => ({id: sha(`${id}|${seq}`), trip_id: id, seq, kind, started_at: minute(seq),
    ended_at: minute(seq + 1), geometry: '_p~iF~ps|U_ulLnnqC', points_n: 12, mean_sog: 1.4, p90_sog: 2.2, distance_nm: 0.8,
    straightness: 0.5, heading_var: 0.4}));
  const seg = segments[FIX.event_segment_seq];
  const event = {id: sha(`${id}|${seg.started_at}|${seg.kind}`), trip_id: id, segment_id: seg.id, vessel_id: vessel, region: REGION,
    kind: seg.kind, lat: 35.31, lon: -120.92, radius_m: 120, started_at: seg.started_at, ended_at: seg.ended_at, dwell_min: 60,
    port_id: 'port-sp1301', vessel_class: null, trip_type: null, season: '2026', season_part: 'fall', basis: 'inferred-from-movement',
    source: SOURCE, rights: 'internal-only', classifier_version: FIX.classifier_version, species_json: null};
  return {trip, segments, events: [event], mmsi: spec.mmsi};
}
const [TA, TB] = FIX.trips.map(build);
const PRIOR = build(FIX.prior);
const windowOf = (part, w = FIX.window) => ({mmsi: part.mmsi, from: w.from, to: w.to});
const envelope = (parts, {trips, segments, events} = {}) => ({region: REGION, source: SOURCE, replace: parts.map(p => windowOf(p)),
  trips: trips ?? parts.map(p => p.trip), segments: segments ?? parts.flatMap(p => p.segments), events: events ?? parts.flatMap(p => p.events)});
/** Trip A's own event, but naming trip B's segment of the same seq (everything else valid). */
const crossed = (from, to) => ({...from.events[0], segment_id: to.events[0].segment_id});

// ---- database, spy and calls -------------------------------------------------------------
const TABLES = ['fleet_vessels', 'fleet_trips', 'fleet_segments', 'fleet_events', 'fleet_segment_labels', 'fleet_trip_reports', 'job_state'];
const dump = sql => Object.fromEntries(TABLES.map(t => [t, sql.prepare(`SELECT * FROM ${t} ORDER BY 1, 2`).all().map(r => ({...r}))]));

/** Migration-backed D1 with both vessels, a prior trip outside the test window and a label on it. */
async function seeded() {
  const {sql, db} = advisorDatabase();
  const insert = sql.prepare('INSERT INTO fleet_vessels(id,region,slug,name,name_norm,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)');
  for (const v of Object.values(VESSELS)) insert.run(v.id, REGION, v.slug, v.name, v.name.replace(/\W/g, '').toUpperCase(), NOW, NOW, NOW, NOW);
  const prior = await post(db, {...envelope([PRIOR]), replace: [windowOf(PRIOR, FIX.prior.window)]});
  assert.equal(prior.status, 200, `seed: ${JSON.stringify(prior)}`);
  sql.prepare(`INSERT INTO fleet_segment_labels(id,trip_id,started_at,ended_at,label,labeller,basis,created_at) VALUES('sp1301-label',?,?,?,'drift-anchor','agent:sp1301','synthetic',?)`)
    .run(PRIOR.trip.id, PRIOR.events[0].started_at, PRIOR.events[0].ended_at, NOW);
  return {sql, db};
}
function spy(db) {
  const calls = {prepare: 0, batch: 0};
  return {calls, db: {prepare(q) { calls.prepare += 1; return db.prepare(q); }, async batch(s) { calls.batch += 1; return db.batch(s); }}};
}
async function post(db, payload) {
  const request = new Request('https://skippercast.com/api/fleet/jobs/activity', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  return activity(db, request);
}
/** The answer, or a product exception captured as observed data (never a harness error). */
async function observe(db, payload) {
  try { return await post(db, payload); }
  catch (error) { return {status: 'threw', body: {exception: `${error?.name}: ${error?.message}`}}; }
}
/** Status, body, D1 calls and table state after `payload` against a fresh seeded database. */
async function refusalProbe(payload) {
  const {sql, db} = await seeded();
  try {
    const before = dump(sql), probe = spy(db);
    const result = await observe(probe.db, payload);
    return {result, calls: probe.calls, unchanged: JSON.stringify(dump(sql)) === JSON.stringify(before), after: dump(sql), before};
  } finally { sql.close(); }
}
const eventRows = sql => sql.prepare('SELECT e.id, e.trip_id, e.segment_id, s.trip_id AS segment_trip FROM fleet_events e LEFT JOIN fleet_segments s ON s.id = e.segment_id ORDER BY e.id').all().map(r => ({...r}));
const expectedRelation = parts => parts.map(p => ({id: p.events[0].id, trip_id: p.trip.id, segment_id: p.events[0].segment_id, segment_trip: p.trip.id}))
  .sort((a, b) => a.id < b.id ? -1 : 1);

// ---- A4 pair ------------------------------------------------------------------------------
test('primary regression', {skip}, async t => {
  // A1's first corrected case: events[1] names trip A but trip B's segment.
  const payload = envelope([TA, TB], {events: [TB.events[0], crossed(TA, TB)]});
  const {result, calls, unchanged} = await refusalProbe(payload);
  t.diagnostic(`observed ${JSON.stringify({status: result.status, body: result.body, calls, unchanged})}`);
  assert.deepEqual({status: result.status, body: result.body}, {status: 400, body: {error: RELATION_ERROR(1)}});
  assert.deepEqual(calls, {prepare: 0, batch: 0}, 'no D1 prepare or batch before the refusal');
  assert.equal(unchanged, true, 'synthetic database state unchanged');
});

test('healthy control', {skip}, async t => {
  // The same complete request with events[1] pointing back at trip A's own segment.
  const payload = envelope([TA, TB], {events: [TB.events[0], TA.events[0]]});
  const {sql, db} = await seeded();
  try {
    const result = await observe(db, payload);
    t.diagnostic(`observed ${JSON.stringify(result)}`);
    assert.equal(result.status, 200, JSON.stringify(result.body));
    assert.deepEqual(result.body.changes, {unpaired: 0, deleted_events: 0, deleted_segments: 0, deleted_trips: 0, trips: 2, segments: 8, events: 2, paired_advisor: 0});
    const rows = eventRows(sql).filter(r => r.trip_id !== PRIOR.trip.id);
    assert.deepEqual(rows, expectedRelation([TA, TB]));
  } finally { sql.close(); }
});

if (!BASELINE_ONLY) {
  // ---- A1 -----------------------------------------------------------------------------------
  test('A1: cross-trip segment refused 400 with the indexed event error and no D1 call, either direction', {skip}, async () => {
    const cases = [
      ['A names B at index 1', envelope([TA, TB], {events: [TB.events[0], crossed(TA, TB)]}), 1],
      ['B names A at index 0', envelope([TA, TB], {events: [crossed(TB, TA), TA.events[0]]}), 0],
      ['both crossed, first reported', envelope([TA, TB], {events: [crossed(TA, TB), crossed(TB, TA)]}), 0],
    ];
    for (const [name, payload, index] of cases) {
      const {result, calls, unchanged} = await refusalProbe(payload);
      assert.deepEqual({status: result.status, body: result.body}, {status: 400, body: {error: RELATION_ERROR(index)}}, name);
      assert.deepEqual(calls, {prepare: 0, batch: 0}, `${name}: no D1 prepare or batch`);
      assert.equal(unchanged, true, `${name}: state unchanged`);
    }
  });

  // ---- A2 -----------------------------------------------------------------------------------
  test('A2: correctly paired two-trip request stores each event with its own segment and trip, order-independent and idempotent', {skip}, async () => {
    const forward = envelope([TA, TB]);
    const reversed = {...forward, replace: [...forward.replace].reverse(), trips: [...forward.trips].reverse(),
      segments: [...forward.segments].reverse(), events: [...forward.events].reverse()};
    const one = await seeded(), two = await seeded();
    try {
      const first = await post(one.db, forward), second = await post(two.db, reversed);
      const created = {unpaired: 0, deleted_events: 0, deleted_segments: 0, deleted_trips: 0, trips: 2, segments: 8, events: 2, paired_advisor: 0};
      assert.deepEqual(first, {status: 200, body: {ok: true, windows: 2, changes: created}});
      assert.deepEqual(second, first, 'reordered trips, segments and events give the same answer');
      assert.deepEqual(dump(two.sql), dump(one.sql), 'and the same rows');
      assert.deepEqual(eventRows(one.sql), expectedRelation([TA, TB, PRIOR]));
      assert.equal(one.sql.prepare('SELECT count(*) n FROM fleet_segment_labels').get().n, 1, 'label outside the window survives');
      assert.equal(one.sql.prepare('SELECT count(*) n FROM fleet_trips WHERE id=?').get(PRIOR.trip.id).n, 1, 'trip outside the window survives');
      const before = dump(one.sql), replay = await post(one.db, forward);
      assert.deepEqual(replay, {status: 200, body: {ok: true, windows: 2, changes: {...created, deleted_events: 2, deleted_segments: 8, deleted_trips: 2}}});
      assert.deepEqual(dump(one.sql), before, 'replay leaves identical rows');
    } finally { one.sql.close(); two.sql.close(); }
  });

  // ---- A3 -----------------------------------------------------------------------------------
  test('A3: missing trip, missing segment, duplicate derived segment and isolated cross-trip segment refuse before side effects', {skip}, async () => {
    const phantom = build({key: 'C', vessel: 'alpha', mmsi: TA.mmsi, departed_at: '2026-10-03T08:00:00.000Z'});
    const missingSegment = {...TA.events[0], segment_id: sha(`${TA.trip.id}|${FIX.segment_kinds.length + 5}`)};
    const mislabelled = {...TB.segments[2], trip_id: TA.trip.id};          // B's derived id claimed by trip A
    const cases = [
      ['missing trip', envelope([TA, TB], {events: [TB.events[0], {...phantom.events[0], segment_id: TA.events[0].segment_id}]}), MISSING_ERROR(1)],
      ['missing segment', envelope([TA, TB], {events: [missingSegment, TB.events[0]]}), MISSING_ERROR(0)],
      ['duplicate derived segment', envelope([TA, TB], {segments: [...TA.segments, TA.segments[1], ...TB.segments]}),
        `segments[${TA.segments.length}]: id is not sha256(trip_id|seq) or repeats`],
      ['isolated cross-trip segment', envelope([TA, TB], {events: [crossed(TA, TB)]}), RELATION_ERROR(0)],
      ['segment row claiming another trip\'s derived id', envelope([TA, TB], {segments: [...TA.segments, ...TB.segments.slice(0, 2), mislabelled, TB.segments[3]]}),
        `segments[${TA.segments.length + 2}]: id is not sha256(trip_id|seq) or repeats`],
    ];
    for (const [name, payload, error] of cases) {
      const {result, calls, unchanged} = await refusalProbe(payload);
      assert.deepEqual({status: result.status, body: result.body}, {status: 400, body: {error}}, name);
      assert.deepEqual(calls, {prepare: 0, batch: 0}, `${name}: no D1 prepare or batch`);
      assert.equal(unchanged, true, `${name}: labels and rows outside the windows unchanged`);
    }
  });
}

// Charter fleet job API (CF-11; docs/plans/charter-fleet/design.md § 9, § 12):
// GET /api/fleet/jobs/snapshot and POST /api/fleet/jobs/registry through the
// Worker, against the real migrations (tests/_advisor_d1.mjs) with the fleet job
// verifier stubbed. Idempotency, pinned fields, provenance, decided reviews,
// references, paging and D1's 100-parameter limit. Fixtures are synthetic.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const {fleetJobs} = await import('../server/routes/fleet.ts');
const {jobsDeps, PAGE} = await import('../server/fleet/jobs.ts');
const {MAX_PARAMS} = await import('../server/fleet/registry.ts');
const ids = await import('../server/fleet/ids.ts');

const skip = sqliteUnavailable ?? false;
const ORIGIN = 'https://skippercast.com', REGION = 'CA', RUN = 'run-20261005';
const ASSETS = {fetch: async () => new Response('asset', {status: 299})};
const T0 = '2026-10-05T09:47:00.000Z', T1 = '2026-10-12T09:47:00.000Z';
const sha = s => createHash('sha256').update(s, 'utf8').digest('hex');

/** The D1 fake, also asserting D1's bound-parameter limit and counting statements. */
function database() {
  const {sql, db} = advisorDatabase(), seen = {statements: 0, maxParams: 0};
  const checked = {
    prepare(query) {
      const statement = db.prepare(query);
      const bind = statement.bind.bind(statement);
      statement.bind = (...args) => {
        seen.maxParams = Math.max(seen.maxParams, args.length);
        if (args.length > MAX_PARAMS) throw Error(`D1: too many SQL variables (${args.length})`);
        return bind(...args);
      };
      return statement;
    },
    async batch(statements) { seen.statements += statements.length; return db.batch(statements); },
  };
  return {sql, db: checked, seen};
}

let verifierSaved, clockSaved;
test.before(() => {
  verifierSaved = fleetJobs.verify; clockSaved = jobsDeps.now;
  fleetJobs.verify = async token => token === 'good' ? {jti: 'run-1'} : false;
  jobsDeps.now = () => new Date('2026-10-05T10:00:00.000Z');
});
test.after(() => { fleetJobs.verify = verifierSaved; jobsDeps.now = clockSaved; });

const env = db => ({ASSETS, DB: db, FLEET_ENABLED: 'true'});
const AUTH = {Authorization: 'Bearer good'};
async function post(db, payload, {headers = AUTH, raw} = {}) {
  const response = await worker.fetch(new Request(ORIGIN + '/api/fleet/jobs/registry', {method: 'POST', headers: {'Content-Type': 'application/json', ...headers},
    body: raw ?? JSON.stringify(payload)}), env(db));
  return {status: response.status, body: await response.json()};
}
async function get(db, query, headers = AUTH) {
  const response = await worker.fetch(new Request(ORIGIN + '/api/fleet/jobs/snapshot' + query, {headers}), env(db));
  return {status: response.status, body: await response.json()};
}
const batch = (ops, extra = {}) => ({region: REGION, run_id: RUN, ops, ...extra});

// ---- synthetic fixtures --------------------------------------------------------
const vid = n => sha(`${REGION}:name-port:test-boat-${n}|morro-bay`).slice(0, 32);
const OPERATOR = 'op-test-0000000000000001';
const vessel = (n, extra = {}) => ({op: 'vessel.upsert', id: vid(n), creation_key: `name-port:test-boat-${n}|morro-bay`, slug: `test-boat-${n}`,
  name: `Test Boat ${n}`, name_norm: `TESTBOAT${n}`, operator_id: OPERATOR, port_id: 'morro-bay', vessel_class: 'inspected-party',
  waters_json: ['ocean', 'bay'], mmsi: String(366000000 + n), passengers_max: 30, length_ft: 58.5, website: `https://boat${n}.example.com/`,
  phone_business: '+18055550100', status: 'active', profile_status: 'listed', completeness: 0.5, first_seen_at: T0, last_seen_at: T0, ...extra});
const fact = (n, field, value, extra = {}) => ({op: 'fact.upsert', vessel_id: vid(n), field, value_json: value, source_id: 'fcc-uls',
  source_url: `https://registry.example.gov/vessel/${n}`, method: 'registry', confidence: 0.9, rights: 'public-domain', retrieved_at: T0, ...extra});
const operator = {op: 'operator.upsert', id: OPERATOR, slug: 'test-landing', name: 'Test Landing Sportfishing', website: 'https://landing.example.com/',
  phone_business: '+18055550101', booking_platform: 'fareharbor', seen_at: T0};
const offering = n => ({op: 'offering.upsert', id: sha(`${vid(n)}|HALFDAY|`).slice(0, 32), vessel_id: vid(n), name: 'Half Day', trip_type: 'half-day',
  duration_h: 5, price_cents: 9500, price_basis: 'per-person', capacity: 30, currency: 'USD', departs_local: '06:30', days_json: ['sat', 'sun'],
  season_from: '04-01', season_to: '10-31', target_species_json: ['rockfish', 'lingcod'], booking_url: 'https://landing.example.com/book', status: 'active', seen_at: T0});
const departure = n => ({op: 'departure.upsert', offering_id: offering(n).id, vessel_id: vid(n), date: '2026-10-10', departs_local: '06:30',
  price_cents: 9500, load_text: '12 of 30', source_url: 'https://landing.example.com/schedule', retrieved_at: T0});
const review = {op: 'review.open', kind: 'merge', fingerprint: 'fcc-uls:WDZ0000', subject_id: vid(1), candidate_json: {name: 'TEST BOAT 1', source: 'fcc-uls'},
  proposal_json: {vessels: [vid(1), vid(2)]}, score: 0.72, opened_at: T0};
const change = n => ({op: 'change.record', vessel_id: vid(n), kind: 'new', before_json: null, after_json: {name: `Test Boat ${n}`}, detected_at: T0});
const alias = n => ({op: 'alias.upsert', vessel_id: vid(n), alias: `Test Boat ${n} II`, alias_norm: `TESTBOAT${n}2`, kind: 'former-name',
  source_url: 'https://reports.example.com/boats', first_seen_at: T0, last_seen_at: T0});
const run = {op: 'run.record', step: 'ingest', sink: 'worker', started_at: T0, finished_at: T0, status: 'ok', counts_json: {facts: 3}};

/** Every fleet_* registry table (not fleet_runs, the call log), for before/after comparison. */
const TABLES = ['fleet_operators', 'fleet_vessels', 'fleet_vessel_facts', 'fleet_aliases', 'fleet_offerings', 'fleet_departures', 'fleet_reviews', 'fleet_changes'];
const dump = sql => Object.fromEntries(TABLES.map(t => [t, sql.prepare(`SELECT * FROM ${t} ORDER BY 1, 2`).all()]));
const count = (sql, table) => sql.prepare(`SELECT count(*) n FROM ${table}`).get().n;

function fullBatch(vessels = 3) {
  const ops = [operator];
  for (let n = 1; n <= vessels; n++) ops.push(vessel(n), fact(n, 'mmsi', String(366000000 + n)), fact(n, 'name', `Test Boat ${n}`), alias(n), offering(n), departure(n), change(n));
  ops.push(review, run);
  return ops;
}

test('ids: canonical JSON and the derived ids match an independent SHA-256', {skip}, async () => {
  assert.equal(ids.canonicalJson({b: [2, {d: 1, c: 'é'}], a: null}), '{"a":null,"b":[2,{"c":"é","d":1}]}');
  assert.equal(ids.canonicalJson(1.5), '1.5');
  assert.equal(await ids.vesselId('CA', 'uscg:1234567'), sha('CA:uscg:1234567').slice(0, 32));
  assert.equal(await ids.valueKey({b: 1, a: 2}), sha('{"a":2,"b":1}').slice(0, 16));
  assert.equal(await ids.factId('v', 'mmsi', 'fcc-uls', 'https://x.example', 'k'), sha('v|mmsi|fcc-uls|https://x.example|k').slice(0, 32));
  assert.equal(await ids.reviewId('merge', 'fp'), sha('merge|fp').slice(0, 32));
  assert.equal(await ids.departureId('o', '2026-10-10', ''), sha('o|2026-10-10|').slice(0, 32));
  assert.equal(await ids.changeId('v', 'new', '{"a":1}'), sha('v|new|{"a":1}').slice(0, 32));
  assert.equal(await ids.offeringId('v', 'HALFDAY', ''), sha('v|HALFDAY|').slice(0, 32));
});

test('job routes are dark without FLEET_ENABLED and need the fleet job identity', {skip}, async () => {
  const {sql, db} = database();
  try {
    const off = await worker.fetch(new Request(ORIGIN + '/api/fleet/jobs/snapshot?region=CA', {headers: AUTH}), {ASSETS, DB: db});
    assert.equal(off.status, 404);
    const offPost = await worker.fetch(new Request(ORIGIN + '/api/fleet/jobs/registry', {method: 'POST', headers: AUTH, body: '{}'}), {ASSETS, DB: db});
    assert.equal(offPost.status, 404);
    assert.equal((await get(db, '?region=CA', {})).status, 401);
    assert.equal((await post(db, batch([]), {headers: {Authorization: 'Bearer bad'}})).status, 401);
    assert.equal(count(sql, 'fleet_runs'), 0, 'an unauthenticated call records nothing');
  } finally { sql.close(); }
});

test('posting the same batch twice changes no row the second time', {skip}, async () => {
  const {sql, db, seen} = database();
  try {
    const ops = fullBatch(3), first = await post(db, batch(ops));
    assert.equal(first.status, 200, JSON.stringify(first.body));
    assert.equal(first.body.ops, ops.length);
    assert.ok(first.body.changed > 0);
    assert.equal(count(sql, 'fleet_vessels'), 3);
    assert.equal(count(sql, 'fleet_vessel_facts'), 6);
    assert.equal(count(sql, 'fleet_reviews'), 1);
    const before = dump(sql);
    jobsDeps.now = () => new Date('2026-10-05T11:30:00.000Z');   // a later call: Worker-clock stamps must not move either
    const second = await post(db, batch(ops));
    jobsDeps.now = () => new Date('2026-10-05T10:00:00.000Z');
    assert.equal(second.status, 200);
    assert.equal(second.body.changed, 0, JSON.stringify(second.body.counts));
    for (const kind of Object.keys(second.body.counts)) assert.equal(second.body.counts[kind].changed, 0, kind);
    assert.deepEqual(dump(sql), before);
    // Stored shape: canonical JSON, Worker-set region and run, defaults kept.
    const v = sql.prepare('SELECT * FROM fleet_vessels WHERE id=?').get(vid(1));
    assert.equal(v.region, REGION);
    assert.equal(v.waters_json, '["ocean","bay"]');
    assert.equal(v.map_display_consent, 'none');
    assert.equal(v.pinned_json, '{}');
    assert.equal(v.created_at, '2026-10-05T10:00:00.000Z');
    const f = sql.prepare("SELECT * FROM fleet_vessel_facts WHERE vessel_id=? AND field='mmsi'").get(vid(1));
    assert.equal(f.value_json, '"366000001"');
    assert.equal(f.run_id, RUN);
    assert.equal(f.id, sha([vid(1), 'mmsi', 'fcc-uls', 'https://registry.example.gov/vessel/1', sha('"366000001"').slice(0, 16)].join('|')).slice(0, 32));
    assert.equal(sql.prepare('SELECT run_id FROM fleet_reviews').get().run_id, RUN);
    assert.equal(sql.prepare("SELECT count(*) n FROM fleet_runs WHERE id='run-20261005:ingest'").get().n, 1, 'run.record');
    assert.ok(seen.maxParams <= MAX_PARAMS);
  } finally { sql.close(); }
});

test('a full 500-op batch binds at most 100 parameters per statement and replays with zero changes', {skip}, async () => {
  const {sql, db, seen} = database();
  try {
    const ops = [operator];
    for (let n = 1; ops.length < 500; n++) {
      ops.push(vessel(n));
      for (const field of ['mmsi', 'name', 'website', 'passengers_max']) if (ops.length < 500) ops.push(fact(n, field, `${field}-${n}`));
    }
    assert.equal(ops.length, 500);
    const first = await post(db, batch(ops));
    assert.equal(first.status, 200, JSON.stringify(first.body).slice(0, 500));
    assert.equal(first.body.changed, 500);
    assert.ok(seen.maxParams <= MAX_PARAMS && seen.maxParams > 50, `max params ${seen.maxParams}`);
    assert.ok(seen.statements < 500, `multi-row statements: ${seen.statements}`);
    assert.equal((await post(db, batch(ops))).body.changed, 0);
    const tooMany = await post(db, batch([...ops, operator]));
    assert.equal(tooMany.status, 413);
  } finally { sql.close(); }
});

test('a fact without provenance is rejected with its op index, and nothing is written', {skip}, async () => {
  const {sql, db} = database();
  try {
    const {source_url: _, ...noUrl} = fact(1, 'mmsi', '366000001');
    const cases = [
      [noUrl, /source_url: missing/],
      [fact(1, 'mmsi', '366000001', {source_url: 'http://registry.example.gov/v/1'}), /source_url: not an https URL/],
      [fact(1, 'mmsi', '366000001', {source_url: 'admin:user-1'}), /admin provenance/],
      [fact(1, 'mmsi', '366000001', {source_id: undefined}), null],
      [fact(1, 'mmsi', '366000001', {confidence: 1.2}), /confidence/],
      [fact(1, 'mmsi', '366000001', {method: 'admin'}), /method/],
      [fact(1, 'mmsi', '366000001', {rights: 'all-rights'}), /rights/],
      [fact(1, 'mmsi', null), /null is not a value/],
      [{...fact(1, 'mmsi', '366000001'), color: 'red'}, /color: not a field/],
    ];
    for (const [bad, pattern] of cases) {
      const payload = JSON.parse(JSON.stringify(batch([operator, vessel(1), fact(1, 'name', 'Test Boat 1'), bad])));
      const response = await post(db, payload);
      assert.equal(response.status, 400, JSON.stringify(bad));
      assert.equal(response.body.error, 'invalid operations');
      if (pattern === null) { assert.equal(response.body.errors[0].error, 'source_id: missing'); }
      else assert.match(response.body.errors[0].error, pattern);
      assert.equal(response.body.errors[0].index, 3);
      assert.equal(response.body.errors[0].op, 'fact.upsert');
      for (const table of TABLES) assert.equal(count(sql, table), 0, `${table} after ${JSON.stringify(bad)}`);
    }
    const runs = sql.prepare("SELECT * FROM fleet_runs WHERE id='run-20261005:registry.0'").get();
    assert.equal(runs.status, 'failed');
    assert.equal(runs.step, 'registry');
    assert.equal(runs.sink, 'worker');
    assert.match(runs.error, /index 3/);
  } finally { sql.close(); }
});

test('validation: enums, formats, derived ids, references and slugs', {skip}, async () => {
  const {sql, db} = database();
  try {
    sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at) VALUES('b1','test-boat-9','Test Boat 9','morro-bay','morro-bay','verified',?,?)`).run(T0, T0);
    const bad = [
      [{op: 'vessel.delete', id: vid(1)}, /op: not one of/],
      [vessel(1, {vessel_class: 'yacht'}), /vessel_class/],
      [vessel(1, {waters_json: ['ocean', 'ocean']}), /waters_json/],
      [vessel(1, {mmsi: '12345'}), /mmsi/],
      [vessel(1, {website: 'javascript:alert(1)'}), /website/],
      [vessel(1, {first_seen_at: '2026-10-05'}), /first_seen_at/],
      [vessel(1, {first_seen_at: T1}), /after last_seen_at/],
      [vessel(1, {creation_key: 'uscg:999'}), /creation_key/],
      [vessel(1, {pinned_json: {}}), /pinned_json: not a field/],
      [vessel(1, {map_display_consent: 'named'}), /map_display_consent: not a field/],
      [vessel(1, {operator_id: 'op-unknown-00000000000'}), /operator_id: unknown/],
      [vessel(9), /slug: already taken/],
      [fact(7, 'mmsi', '366000007'), /vessel_id: unknown vessel/],
      [{...fact(1, 'mmsi', '366000001'), id: '0'.repeat(32)}, /derived id/],
      [{...review, id: '0'.repeat(32)}, /derived id/],
      [{...review, kind: 'other'}, /kind/],
      [{...offering(1), trip_type: 'sunset'}, /trip_type/],
      [{...offering(1), departs_local: '25:00'}, /departs_local/],
      [{...departure(1), offering_id: '1'.repeat(32)}, /offering_id: unknown/],
      [{...change(1), kind: 'teleported'}, /kind/],
      [{...run, status: 'great'}, /status/],
    ];
    for (const [op, pattern] of bad) {
      const ops = [operator, vessel(1), offering(1), op], response = await post(db, batch(ops));
      assert.equal(response.status, 400, JSON.stringify(op));
      assert.equal(response.body.errors.length, 1, JSON.stringify(response.body.errors));
      assert.equal(response.body.errors[0].index, 3);
      assert.match(response.body.errors[0].error, pattern, JSON.stringify(op));
    }
    // Two vessels claiming one slug in a request; a vessel of another region.
    const clash = await post(db, batch([operator, vessel(1), vessel(2, {slug: 'test-boat-1'})]));
    assert.deepEqual(clash.body.errors.map(e => e.index), [2]);
    assert.equal((await post(db, batch([operator, vessel(1)]))).status, 200);
    const other = await post(db, {...batch([fact(1, 'mmsi', '366000001')]), region: 'OR'});
    assert.match(other.body.errors[0].error, /unknown vessel in this region/);
    // Envelope checks.
    assert.equal((await post(db, {...batch([]), region: '../x'})).status, 400);
    assert.equal((await post(db, {...batch([]), run_id: ''})).status, 400);
    assert.equal((await post(db, {...batch([]), extra: 1})).status, 400);
    assert.equal((await post(db, {region: REGION, run_id: RUN, ops: {}})).status, 400);
    assert.equal((await post(db, null, {raw: '{"region": "CA",'})).status, 400);
    assert.equal((await post(db, null, {raw: JSON.stringify(batch([{op: 'run.record', step: 'x', sink: 'worker', started_at: T0, status: 'ok', error: 'x'.repeat(1100000)}]))})).status, 413);
    const empty = await post(db, batch([], {batch: 4}));
    assert.equal(empty.status, 200);
    assert.equal(empty.body.changed, 0);
    assert.equal(sql.prepare("SELECT status FROM fleet_runs WHERE id='run-20261005:registry.4'").get().status, 'ok');
  } finally { sql.close(); }
});

test('pinned fields survive an upsert; unpinned fields update; a removal request is never re-listed', {skip}, async () => {
  const {sql, db} = database();
  try {
    assert.equal((await post(db, batch([operator, vessel(1), vessel(2), vessel(3)]))).status, 200);
    sql.prepare('UPDATE fleet_vessels SET name=?, website=?, pinned_json=? WHERE id=?')
      .run('Admin Name', 'https://admin.example.com/', JSON.stringify({name: {by: 'admin-1', at: T0}, website: {by: 'admin-1', at: T0}}), vid(1));
    sql.prepare("UPDATE fleet_vessels SET pinned_json='not json', mmsi='366999999' WHERE id=?").run(vid(2));
    sql.prepare("UPDATE fleet_vessels SET profile_status='hidden', removal_requested_at=? WHERE id=?").run(T0, vid(3));
    const later = {name: 'Pipeline Name', website: 'https://pipeline.example.com/', mmsi: '366111111', profile_status: 'listed', last_seen_at: T1};
    const response = await post(db, batch([vessel(1, later), vessel(2, later), vessel(3, later)]));
    assert.equal(response.status, 200);
    const row = id => sql.prepare('SELECT * FROM fleet_vessels WHERE id=?').get(id);
    const one = row(vid(1));
    assert.equal(one.name, 'Admin Name', 'pinned name kept');
    assert.equal(one.website, 'https://admin.example.com/', 'pinned website kept');
    assert.equal(one.mmsi, '366111111', 'unpinned field updated');
    assert.equal(one.last_seen_at, T1);
    assert.equal(one.updated_at, '2026-10-05T10:00:00.000Z');
    const two = row(vid(2));
    assert.equal(two.mmsi, '366999999', 'unreadable pinned_json pins every field');
    assert.equal(two.name, 'Test Boat 2');
    const three = row(vid(3));
    assert.equal(three.profile_status, 'hidden', 'a removal request is never re-listed by a job');
    assert.equal(three.mmsi, '366111111');
    // Replaying, and an older replay, change nothing more.
    assert.equal((await post(db, batch([vessel(1, later), vessel(2, later), vessel(3, later)]))).body.changed, 0);
    assert.equal((await post(db, batch([vessel(1, {...later, last_seen_at: T0})]))).body.changed, 0, 'last_seen_at never moves back');
    // Omitted fields keep their value; present nulls clear an unpinned field.
    const partial = {op: 'vessel.upsert', id: vid(1), slug: 'test-boat-1', name: 'Pipeline Name', name_norm: 'TESTBOAT1', first_seen_at: T0, last_seen_at: T1, mmsi: null};
    assert.equal((await post(db, batch([partial]))).body.changed, 1);
    assert.equal(row(vid(1)).mmsi, null);
    assert.equal(row(vid(1)).passengers_max, 30);
    assert.equal(row(vid(1)).name, 'Admin Name');
  } finally { sql.close(); }
});

test('review.open never reopens or edits a decided review; snapshot returns decided reviews', {skip}, async () => {
  const {sql, db} = database();
  try {
    assert.equal((await post(db, batch([operator, vessel(1), vessel(2), review]))).status, 200);
    const id = sha('merge|fcc-uls:WDZ0000').slice(0, 32);
    // An open review updates on a repeat (never duplicates).
    const updated = await post(db, batch([{...review, score: 0.8, opened_at: T1}]));
    assert.equal(updated.body.changed, 1);
    let stored = sql.prepare('SELECT * FROM fleet_reviews').all();
    assert.equal(stored.length, 1);
    assert.equal(stored[0].score, 0.8);
    assert.equal(stored[0].opened_at, T0, 'opened_at stays');
    sql.prepare("UPDATE fleet_reviews SET status='decided', decision_json=?, decided_by='admin-1', decided_at=? WHERE id=?").run('{"action":"same-vessel","vessel_id":"' + vid(1) + '"}', T1, id);
    const again = await post(db, batch([{...review, score: 0.5, candidate_json: {name: 'CHANGED'}}]));
    assert.equal(again.status, 200);
    assert.equal(again.body.changed, 0);
    stored = sql.prepare('SELECT * FROM fleet_reviews').get();
    assert.equal(stored.status, 'decided');
    assert.equal(stored.score, 0.8);
    // A second, open review is not in the snapshot; the decided one is, with its decision.
    assert.equal((await post(db, batch([{...review, fingerprint: 'fcc-uls:WDZ0001'}]))).status, 200);
    let cursor = '', pages = 0;
    const reviews = [];
    while (cursor !== null && pages++ < 10) {
      const page = await get(db, `?region=${REGION}${cursor ? '&cursor=' + encodeURIComponent(cursor) : ''}`);
      assert.equal(page.status, 200);
      reviews.push(...page.body.reviews);
      cursor = page.body.next;
    }
    assert.equal(reviews.length, 1);
    assert.equal(reviews[0].id, id);
    assert.equal(reviews[0].status, 'decided');
    assert.deepEqual(reviews[0].decision, {action: 'same-vessel', vessel_id: vid(1)});
    assert.deepEqual(reviews[0].candidate, {name: 'TEST BOAT 1', source: 'fcc-uls'});
    assert.equal(reviews[0].decided_by, undefined, 'who decided stays out of the snapshot');
    // Dismissed reviews are not reopened either.
    sql.prepare("UPDATE fleet_reviews SET status='dismissed' WHERE id=?").run(id);
    assert.equal((await post(db, batch([review]))).body.changed, 0);
  } finally { sql.close(); }
});

test('facts: re-seeing touches, a newer value supersedes the named facts, an older replay never does', {skip}, async () => {
  const {sql, db} = database();
  try {
    const old = fact(1, 'website', 'https://old.example.com/');
    assert.equal((await post(db, batch([operator, vessel(1), old]))).status, 200);
    const oldId = sql.prepare('SELECT id FROM fleet_vessel_facts').get().id;
    const fresh = fact(1, 'website', 'https://new.example.com/', {retrieved_at: T1, supersedes: [oldId]});
    const r = await post(db, {...batch([fresh]), run_id: 'run-20261012'});
    assert.equal(r.body.changed, 2, 'new fact inserted, old superseded');
    const rows = Object.fromEntries(sql.prepare('SELECT * FROM fleet_vessel_facts').all().map(f => [f.value_json, f]));
    const newId = rows['"https://new.example.com/"'].id;
    assert.equal(rows['"https://old.example.com/"'].superseded_by, newId);
    assert.equal(rows['"https://old.example.com/"'].superseded_at, T1);
    assert.equal((await post(db, {...batch([fresh]), run_id: 'run-20261012'})).body.changed, 0);
    // Replaying the old run (old fact at T0) changes nothing: it is not newer than its supersession.
    assert.equal((await post(db, batch([old]))).body.changed, 0);
    // The old value seen again later becomes current again; its run and last_seen move.
    const back = await post(db, {...batch([{...old, retrieved_at: '2026-10-19T09:47:00.000Z'}]), run_id: 'run-20261019'});
    assert.equal(back.body.changed, 1);
    const revived = sql.prepare('SELECT * FROM fleet_vessel_facts WHERE id=?').get(oldId);
    assert.equal(revived.superseded_at, null);
    assert.equal(revived.run_id, 'run-20261019');
    assert.equal(revived.first_seen_at, T0);
    // A supersede never crosses vessel or field.
    const other = fact(1, 'mmsi', '366000001', {retrieved_at: T1, supersedes: [newId]});
    await post(db, batch([other]));
    assert.equal(sql.prepare('SELECT superseded_at FROM fleet_vessel_facts WHERE id=?').get(newId).superseded_at, null);
  } finally { sql.close(); }
});

test('snapshot: paged by section, vessels carry keys, pinned names, aliases and offerings; private columns stay out', {skip}, async () => {
  const {sql, db} = database(), saved = {...PAGE};
  try {
    assert.equal((await post(db, batch(fullBatch(5)))).status, 200);
    sql.prepare(`UPDATE fleet_vessels SET pinned_json='{"name":{"by":"admin-1"}}', removal_requested_at=?, map_display_consent='named' WHERE id=?`).run(T0, vid(2));
    sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,first_seen_at,last_seen_at,created_at,updated_at) VALUES('x','OR','or-boat','OR Boat','ORBOAT',?,?,?,?)`).run(T0, T0, T0, T0);
    PAGE.vessels = 2;
    const vessels = [], operators = [];
    let cursor = null, pages = 0;
    do {
      const page = await get(db, `?region=${REGION}${cursor ? '&cursor=' + encodeURIComponent(cursor) : ''}`);
      assert.equal(page.status, 200, JSON.stringify(page.body));
      assert.ok(page.body.vessels.length <= 2);
      vessels.push(...page.body.vessels); operators.push(...page.body.operators);
      cursor = page.body.next; pages++;
    } while (cursor !== null && pages < 20);
    assert.equal(pages, 1 + 3 + 1, 'operators, three vessel pages, reviews');
    assert.deepEqual(vessels.map(v => v.id), [1, 2, 3, 4, 5].map(vid).sort(), 'every vessel once, other regions excluded');
    assert.deepEqual(operators.map(o => o.id), [OPERATOR]);
    assert.equal(operators[0].consent_status, undefined);
    const two = vessels.find(v => v.id === vid(2));
    assert.deepEqual(two.pinned, ['name']);
    assert.deepEqual(two.waters, ['ocean', 'bay']);
    assert.equal(two.mmsi, '366000002');
    assert.equal(two.removal_requested_at, undefined, 'the request time stays private');
    assert.equal(two.removal_requested, true, 'the flag lets plan-agent and ingest skip it (#346)');
    assert.equal(vessels.find(v => v.id === vid(1)).removal_requested, false);
    assert.equal(two.map_display_consent, undefined);
    assert.equal(two.pinned_json, undefined);
    assert.deepEqual(two.aliases.map(a => a.alias_norm), ['TESTBOAT22']);
    assert.equal(two.offerings.length, 1);
    assert.deepEqual(two.offerings[0].days, ['sat', 'sun']);
    assert.deepEqual(two.offerings[0].target_species, ['rockfish', 'lingcod']);
    assert.equal(two.offerings[0].price_cents, 9500);
    assert.equal(vessels.find(v => v.id === vid(1)).pinned.length, 0);
    for (const bad of ['?region=../x', '', `?region=${REGION}&cursor=z:1`, `?region=${REGION}&cursor=v:%27%3B`]) assert.equal((await get(db, bad)).status, 400, bad);
  } finally { Object.assign(PAGE, saved); sql.close(); }
});

test('snapshot: the first page carries advisor_slugs; vessels carry the winning-source record without values (CF-17)', {skip}, async () => {
  const {sql, db} = database();
  try {
    for (const slug of ['test-boat-9', 'example-skipper'])
      sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,created_at,updated_at) VALUES(?,?,?,'morro-bay','morro-bay',?,?)`).run('b-' + slug, slug, slug, T0, T0);
    const ops = [operator, vessel(1), fact(1, 'mmsi', '366000001'), fact(1, 'name', 'Test Boat 1'),
      fact(1, 'trip_types[]', {name: 'Half Day'}), fact(1, 'name', 'Test Boat One', {source_url: 'https://registry.example.gov/v/1b', retrieved_at: T1})];
    assert.equal((await post(db, batch(ops))).status, 200);
    const old = sha([vid(1), 'name', 'fcc-uls', 'https://registry.example.gov/vessel/1', sha('"Test Boat 1"').slice(0, 16)].join('|')).slice(0, 32);
    sql.prepare('UPDATE fleet_vessel_facts SET superseded_at=? WHERE id=?').run(T1, old);
    const first = await get(db, `?region=${REGION}`);
    assert.deepEqual(first.body.advisor_slugs, ['example-skipper', 'test-boat-9']);
    const page = await get(db, `?region=${REGION}&cursor=v:`);
    assert.equal(page.body.advisor_slugs, undefined, 'only the first page');
    const sources = page.body.vessels[0].sources;
    assert.deepEqual(sources.map(s => s.field).sort(), ['mmsi', 'name'], 'current scalar facts only: no list fields, no superseded fact');
    assert.deepEqual(Object.keys(sources[0]).sort(), ['confidence', 'field', 'id', 'retrieved_at', 'source_id']);
    assert.equal(sources.find(s => s.field === 'name').retrieved_at, T1);
  } finally { sql.close(); }
});

test('an admin or user session without a fleet bearer token gets 401 on both job routes', {skip}, async () => {
  const {sql, db} = database(), sessions = withSessions(worker);
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES('admin-1',?,'admin')").run(T0);
  try {
    for (const owner of ['admin-1', 'someone']) {
      const snap = await sessions.fetch(new Request(ORIGIN + '/api/fleet/jobs/snapshot?region=CA', {headers: {'x-test-owner': owner}}), env(db));
      assert.equal(snap.status, 401, `snapshot as ${owner}`);
      const reg = await sessions.fetch(new Request(ORIGIN + '/api/fleet/jobs/registry', {method: 'POST',
        headers: {'x-test-owner': owner, 'Content-Type': 'application/json', Origin: ORIGIN}, body: JSON.stringify(batch([operator]))}), env(db));
      assert.equal(reg.status, 401, `registry as ${owner}`);
    }
    assert.equal(count(sql, 'fleet_operators'), 0);
    assert.equal(count(sql, 'fleet_runs'), 0);
  } finally { sql.close(); }
});

test('an older replay never overwrites newer vessel, operator or offering values', {skip}, async () => {
  const {sql, db} = database();
  try {
    const newer = [{...operator, name: 'Newer Landing', seen_at: T1}, vessel(1, {name: 'Newer Name', mmsi: '366222222', last_seen_at: T1}),
      {...offering(1), price_cents: 11000, seen_at: T1}];
    const older = [{...operator, name: 'Older Landing'}, vessel(1, {name: 'Older Name', mmsi: '366333333'}), {...offering(1), price_cents: 8000}];
    assert.equal((await post(db, batch(newer))).status, 200);
    const replay = await post(db, batch(older));
    assert.equal(replay.status, 200);
    assert.equal(replay.body.changed, 0, JSON.stringify(replay.body.counts));
    const v = sql.prepare('SELECT * FROM fleet_vessels WHERE id=?').get(vid(1));
    assert.equal(v.name, 'Newer Name');
    assert.equal(v.mmsi, '366222222');
    assert.equal(v.last_seen_at, T1);
    assert.equal(v.first_seen_at, T0, 'first_seen_at may still move back');
    assert.equal(sql.prepare('SELECT name FROM fleet_operators').get().name, 'Newer Landing');
    assert.equal(sql.prepare('SELECT updated_at FROM fleet_operators').get().updated_at, T1);
    const o = sql.prepare('SELECT price_cents, updated_at FROM fleet_offerings').get();
    assert.equal(o.price_cents, 11000);
    assert.equal(o.updated_at, T1);
    // A newer one still lands.
    const T2 = '2026-10-19T09:47:00.000Z';
    const next = await post(db, batch([{...operator, name: 'Next Landing', seen_at: T2}, vessel(1, {name: 'Next Name', last_seen_at: T2}), {...offering(1), price_cents: 12000, seen_at: T2}]));
    assert.equal(next.body.changed, 3);
    assert.equal(sql.prepare('SELECT price_cents FROM fleet_offerings').get().price_cents, 12000);
    // operator.upsert and offering.upsert need seen_at; updated_at itself is the Worker's.
    const {seen_at: _, ...unseen} = operator;
    assert.match((await post(db, batch([unseen]))).body.errors[0].error, /seen_at: missing/);
    assert.match((await post(db, batch([{...operator, updated_at: T1}]))).body.errors[0].error, /updated_at: not a field/);
  } finally { sql.close(); }
});

test('fleet_runs: a failed call never downgrades an ok row; review.open is scoped to its region', {skip}, async () => {
  const {sql, db} = database();
  try {
    assert.equal((await post(db, batch([operator, vessel(1)]))).status, 200);
    const okRow = sql.prepare("SELECT * FROM fleet_runs WHERE id='run-20261005:registry.0'").get();
    assert.equal(okRow.status, 'ok');
    assert.equal((await post(db, batch([{op: 'nope'}]))).status, 400);
    assert.equal((await post(db, batch([operator]))).status, 200);
    assert.deepEqual(sql.prepare("SELECT * FROM fleet_runs WHERE id='run-20261005:registry.0'").get(), okRow, 'the first ok stays');
    // A failed call may be retried into ok.
    assert.equal((await post(db, batch([{op: 'nope'}], {batch: 1}))).status, 400);
    assert.equal(sql.prepare("SELECT status FROM fleet_runs WHERE id='run-20261005:registry.1'").get().status, 'failed');
    assert.equal((await post(db, batch([operator], {batch: 1}))).status, 200);
    assert.equal(sql.prepare("SELECT status FROM fleet_runs WHERE id='run-20261005:registry.1'").get().status, 'ok');
    // The same review id held by another region is not touched from this one.
    const id = sha('merge|fcc-uls:WDZ0000').slice(0, 32);
    sql.prepare("INSERT INTO fleet_reviews(id,region,kind,status,score,opened_at) VALUES(?,'OR','merge','open',0.1,?)").run(id, T0);
    const r = await post(db, batch([{...review, subject_id: null}]));
    assert.equal(r.status, 200);
    assert.equal(r.body.changed, 0);
    const stored = sql.prepare('SELECT region, score FROM fleet_reviews WHERE id=?').get(id);
    assert.deepEqual({...stored}, {region: 'OR', score: 0.1});
  } finally { sql.close(); }
});

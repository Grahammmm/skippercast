// Charter fleet AIS watch list job routes (CF-46; docs/plans/charter-fleet/design.md § 11, § 12):
// GET and POST /api/fleet/jobs/watch through the Worker against the real migrations
// (tests/_advisor_d1.mjs), with the fleet job verifier stubbed and a fixture clock.
// Fixtures are synthetic: MMSIs 999xxxxxx, invented boats and call signs.
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
const {watchDeps, PAGE, MAX_ROWS} = await import('../server/fleet/watch.ts');

const skip = sqliteUnavailable ?? false;
const ORIGIN = 'https://skippercast.com', REGION = 'CA';
const ASSETS = {fetch: async () => new Response('asset', {status: 299})};
const NOW = '2026-10-05T12:00:00.000Z', LATER = '2026-10-05T12:30:00.000Z';
const sha = s => createHash('sha256').update(s, 'utf8').digest('hex').slice(0, 32);
const SEA = sha('CA:sea-example'), HELD = sha('CA:held-example'), FAR = sha('OR:far-example');
const A = '999000201', B = '999000202', C = '999000203';

let verifierSaved, clockSaved, clock = NOW;
test.before(() => {
  verifierSaved = fleetJobs.verify; clockSaved = watchDeps.now;
  fleetJobs.verify = async token => token === 'good' ? {jti: 'run-1'} : false;
  watchDeps.now = () => new Date(clock);
});
test.after(() => { fleetJobs.verify = verifierSaved; watchDeps.now = clockSaved; });

function database() {
  const {sql, db} = advisorDatabase();
  const insert = sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,mmsi,call_sign,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?)`);
  insert.run(SEA, REGION, 'sea-example', 'Sea Example', 'SEAEXAMPLE', null, 'WDX0001', NOW, NOW, NOW, NOW);
  insert.run(HELD, REGION, 'held-example', 'Held Example', 'HELDEXAMPLE', B, null, NOW, NOW, NOW, NOW);   // B is its registry MMSI
  insert.run(FAR, 'OR', 'far-example', 'Far Example', 'FAREXAMPLE', null, null, NOW, NOW, NOW, NOW);
  return {sql, db};
}
const env = db => ({ASSETS, DB: db, FLEET_ENABLED: 'true'});
const AUTH = {Authorization: 'Bearer good'};
async function call(db, path, payload, {headers = AUTH, method = 'POST', environment} = {}) {
  const init = method === 'GET' ? {headers} : {method, headers: {'Content-Type': 'application/json', ...headers}, body: JSON.stringify(payload)};
  const response = await worker.fetch(new Request(ORIGIN + '/api/fleet/jobs/' + path, init), environment ?? env(db));
  return {status: response.status, body: await response.json()};
}
const get = (db, query) => call(db, 'watch?' + new URLSearchParams({region: REGION, ...query}), null, {method: 'GET'});
const post = (db, payload) => call(db, 'watch', {region: REGION, run_id: 'ais-20261005T120000Z', ...payload});

const row = (mmsi, extra = {}) => ({mmsi, vessel_id: SEA, match_method: 'ais-static-name', confidence: 0.7, status: 'candidate',
  ais_name: 'SEA EXAMPLE', ais_call_sign: 'WDX0001', ais_class: 'B', first_seen_at: '2026-10-01T08:00:00.000Z',
  last_seen_at: '2026-10-05T11:00:00.000Z', last_seen_source: 'aisstream', positions_30d: 120, ...extra});
const stored = (sql, mmsi) => ({...sql.prepare('SELECT * FROM fleet_ais_watch WHERE region=? AND mmsi=?').get(REGION, mmsi)});
const fact = (extra = {}) => ({op: 'fact.upsert', vessel_id: SEA, field: 'ais.call_sign', value_json: {mmsi: A, value: 'WDX0009'},
  source_id: 'ais-static', source_url: 'https://aisstream.io/', method: 'ais', confidence: 0.9, rights: 'internal-only',
  retrieved_at: '2026-10-05T11:00:00.000Z', ...extra});
const review = (extra = {}) => ({op: 'review.open', kind: 'mmsi', fingerprint: `${SEA}|${C}`, subject_id: SEA,
  candidate_json: {mmsi: C, ais_name: 'SEA EXAMPLE', home_port_days: 1}, proposal_json: {vessel_id: SEA, mmsi: C},
  score: 0.4, opened_at: NOW, ...extra});

test('watch routes are dark without FLEET_ENABLED and need the fleet job identity', {skip}, async () => {
  const {sql, db} = database();
  try {
    for (const method of ['GET', 'POST']) {
      const path = method === 'GET' ? `watch?region=${REGION}` : 'watch';
      assert.equal((await call(db, path, {region: REGION}, {method, environment: {ASSETS, DB: db}})).status, 404, method);
      assert.equal((await call(db, path, {region: REGION}, {method, headers: {Authorization: 'Bearer bad'}})).status, 401, method);
    }
  } finally { sql.close(); }
});

test('rows upsert idempotently, keep the first and last sightings, and page by MMSI', {skip}, async () => {
  const {sql, db} = database();
  try {
    const first = await post(db, {rows: [row(A), row(C, {vessel_id: null})]});
    assert.equal(first.status, 200, JSON.stringify(first.body));
    assert.deepEqual(first.body, {ok: true, rows: 2, changed: 2});
    const before = stored(sql, A);
    assert.equal(before.updated_at, NOW);
    clock = LATER;
    assert.deepEqual((await post(db, {rows: [row(A), row(C, {vessel_id: null})]})).body, {ok: true, rows: 2, changed: 0});
    assert.deepEqual(stored(sql, A), before, 'the same rows again change nothing, not even updated_at');

    // An older first sighting and a newer last one widen the span; a promotion moves updated_at.
    await post(db, {rows: [row(A, {status: 'watched', match_method: 'geofence-presence', confidence: 0.85,
      first_seen_at: '2026-09-30T08:00:00.000Z', last_seen_at: '2026-10-04T08:00:00.000Z'})]});
    const after = stored(sql, A);
    assert.equal(after.first_seen_at, '2026-09-30T08:00:00.000Z');
    assert.equal(after.last_seen_at, '2026-10-05T11:00:00.000Z', 'an earlier last sighting never moves it back');
    assert.equal(after.status, 'watched');
    assert.equal(after.updated_at, LATER);

    const all = await get(db, {});
    assert.equal(all.status, 200);
    assert.deepEqual(all.body.rows.map(r => r.mmsi), [A, C]);
    assert.equal(all.body.next, null);
    assert.deepEqual((await get(db, {status: 'watched'})).body.rows.map(r => r.mmsi), [A]);
    assert.deepEqual((await get(db, {cursor: A})).body.rows.map(r => r.mmsi), [C]);
    assert.equal((await get(db, {status: 'maybe'})).status, 400);
    assert.equal((await get(db, {cursor: 'x'})).status, 400);
    assert.equal((await call(db, 'watch?region=../x', null, {method: 'GET'})).status, 400);
    assert.ok(PAGE >= 500);
  } finally { sql.close(); clock = NOW; }
});

test('rows are validated before anything is written', {skip}, async () => {
  const {sql, db} = database();
  try {
    const bad = [
      [{rows: [row(A, {status: 'watched', vessel_id: null})]}, 'needs a vessel_id'],
      [{rows: [row(A, {vessel_id: FAR})]}, 'unknown vessel'],
      [{rows: [row(A, {owner: 'x'})]}, 'unknown field'],
      [{rows: [row(A, {updated_at: NOW})]}, 'unknown field'],
      [{rows: [row(A), row(A)]}, 'appears twice'],
      [{rows: [row('0999')]}, 'mmsi'],
      [{rows: [row(A, {match_method: 'guess'})]}, 'match_method'],
      [{rows: [row(A, {confidence: 1.5})]}, 'confidence'],
      [{rows: [row(A, {first_seen_at: '2026-10-06T00:00:00.000Z'})]}, 'first_seen_at after'],
      [{rows: [row(A, {ais_call_sign: 'wdx 1'})]}, 'ais_call_sign'],
      [{rows: []}, 'nothing to do'],
      [{rows: [row(A)], extra: 1}, 'unknown field'],
      [{rows: [row(A)], run_id: '../x'}, 'run_id'],
    ];
    for (const [payload, message] of bad) {
      const result = await post(db, payload);
      assert.equal(result.status, 400, JSON.stringify(payload));
      assert.match(result.body.error, new RegExp(message.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    }
    const many = Array.from({length: MAX_ROWS + 1}, (_, i) => row(String(999100000 + i)));
    assert.equal((await post(db, {rows: many})).status, 413);
    assert.equal(sql.prepare('SELECT count(*) n FROM fleet_ais_watch').get().n, 0);
  } finally { sql.close(); }
});

test('AIS never overrides a registry MMSI', {skip}, async () => {
  const {sql, db} = database();
  try {
    // B is Held Example's registry MMSI: it cannot be watched for another vessel.
    const stolen = await post(db, {rows: [row(B, {status: 'watched', match_method: 'geofence-presence'})]});
    assert.equal(stolen.status, 400);
    assert.match(stolen.body.error, /another vessel's registry MMSI/);
    // Held Example holds B, so another MMSI cannot be watched for it.
    const second = await post(db, {rows: [row(A, {vessel_id: HELD, status: 'watched', match_method: 'geofence-presence'})]});
    assert.equal(second.status, 400);
    assert.match(second.body.error, /registry MMSI is 999000202/);
    // As candidates they are fine, and watching B for its own vessel is too.
    assert.equal((await post(db, {rows: [row(A, {vessel_id: HELD}), row(B, {vessel_id: HELD, status: 'watched', match_method: 'fcc-uls'})]})).status, 200);
    assert.equal(sql.prepare('SELECT mmsi FROM fleet_vessels WHERE id=?').get(HELD).mmsi, B);
    assert.equal(sql.prepare('SELECT mmsi FROM fleet_vessels WHERE id=?').get(SEA).mmsi, null);
  } finally { sql.close(); }
});

test('a rejected row stays rejected unless an admin match replaces it', {skip}, async () => {
  const {sql, db} = database();
  try {
    await post(db, {rows: [row(A, {status: 'rejected', confidence: 0})]});
    assert.deepEqual((await post(db, {rows: [row(A, {status: 'watched', match_method: 'geofence-presence', confidence: 0.85})]})).body,
      {ok: true, rows: 1, changed: 0});
    assert.equal(stored(sql, A).status, 'rejected');
    await post(db, {rows: [row(A, {status: 'watched', match_method: 'admin', confidence: 1})]});
    assert.equal(stored(sql, A).status, 'watched');
  } finally { sql.close(); }
});

test('ops record ais facts and mmsi reviews, and nothing else', {skip}, async () => {
  const {sql, db} = database();
  try {
    const result = await post(db, {ops: [fact(), review()]});
    assert.equal(result.status, 200, JSON.stringify(result.body));
    assert.equal(result.body.ops.count, 2);
    const facts = sql.prepare('SELECT field,method,source_id,rights,value_json FROM fleet_vessel_facts').all().map(r => ({...r}));
    assert.deepEqual(facts, [{field: 'ais.call_sign', method: 'ais', source_id: 'ais-static', rights: 'internal-only',
      value_json: JSON.stringify({mmsi: A, value: 'WDX0009'})}]);
    const reviews = sql.prepare('SELECT id,kind,subject_id,status,run_id FROM fleet_reviews').all().map(r => ({...r}));
    assert.deepEqual(reviews, [{id: sha(`mmsi|${SEA}|${C}`), kind: 'mmsi', subject_id: SEA, status: 'open', run_id: 'ais-20261005T120000Z'}]);
    assert.equal((await post(db, {ops: [fact(), review()]})).body.ops.changed, 0, 'idempotent');
    assert.equal(sql.prepare('SELECT call_sign FROM fleet_vessels WHERE id=?').get(SEA).call_sign, 'WDX0001', 'the registry value stays');

    const refused = [
      fact({field: 'call_sign', value_json: 'WDX0009'}),            // a registry field
      fact({field: 'mmsi', value_json: A}),
      fact({method: 'registry'}),
      fact({source_id: 'fcc-uls'}),
      review({kind: 'merge'}),
      {op: 'vessel.upsert', id: SEA, slug: 'sea-example', name: 'Sea Example', name_norm: 'SEAEXAMPLE', mmsi: A,
        first_seen_at: NOW, last_seen_at: NOW},
    ];
    for (const op of refused) {
      const answer = await post(db, {rows: [row(C, {vessel_id: null})], ops: [op]});
      assert.equal(answer.status, 400, JSON.stringify(op));
      assert.equal(answer.body.error, 'invalid operations');
    }
    const invalid = await post(db, {rows: [row(C, {vessel_id: null})], ops: [fact({vessel_id: FAR})]});
    assert.equal(invalid.status, 400, 'registry validation: a vessel of another region');
    assert.equal(sql.prepare('SELECT count(*) n FROM fleet_ais_watch').get().n, 0, 'a refused request writes no row');
    assert.equal(sql.prepare('SELECT count(*) n FROM fleet_vessel_facts').get().n, 1);
    assert.equal(sql.prepare('SELECT mmsi FROM fleet_vessels WHERE id=?').get(SEA).mmsi, null);
  } finally { sql.close(); }
});

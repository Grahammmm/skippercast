// Charter fleet admin API: reviews and vessels (CF-30; docs/plans/charter-fleet/design.md
// § 5, § 7, § 12, § 13). Through the Worker against the real migrations (tests/_advisor_d1.mjs),
// signed in with the test session helper; the job snapshot and registry routes run with the
// fleet job verifier stubbed. Synthetic vessels, example.com URLs and 555-01XX numbers only.
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
const {default: deployed} = await import('../server/index.ts');
const {fleetJobs} = await import('../server/routes/fleet.ts');
const {jobsDeps} = await import('../server/fleet/jobs.ts');
const worker = withSessions(deployed);

const skip = sqliteUnavailable ?? false;
const ORIGIN = 'https://skippercast.com', REGION = 'CA', ADMIN = 'admin-fleet-1';
const ASSETS = {fetch: async () => new Response('asset', {status: 299})};
const ON = {FLEET_ENABLED: 'true'};
const T0 = '2026-10-01T09:00:00.000Z', T1 = '2026-10-05T09:00:00.000Z';
const sha = s => createHash('sha256').update(s, 'utf8').digest('hex');
const vid = n => sha(`${REGION}:name-port:test-boat-${n}|morro-bay`).slice(0, 32);
const OPERATOR = 'op-test-0000000000000001';

function setup() {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(ADMIN, T0);
  sql.prepare(`INSERT INTO fleet_operators(id,region,slug,name,created_at,updated_at) VALUES(?,?,?,?,?,?)`).run(OPERATOR, REGION, 'test-landing', 'Test Landing', T0, T0);
  const vessel = sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,operator_id,port_id,vessel_class,mmsi,website,phone_business,status,profile_status,
    completeness,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,'morro-bay',?,?,?,?,'active',?,?,?,?,?,?)`);
  vessel.run(vid(1), REGION, 'test-boat-1', 'Test Boat 1', 'TESTBOAT1', OPERATOR, 'inspected-party', '366000001', 'https://boat1.example.com/', '+18055550100', 'listed', 0.6, T0, T0, T0, T0);
  vessel.run(vid(2), REGION, 'test-boat-2', 'Test Boat 2', 'TESTBOAT2', OPERATOR, null, null, null, null, 'hidden', 0.2, T0, T0, T0, T0);
  vessel.run(vid(3), 'OR', 'other-boat-3', 'Other Boat 3', 'OTHERBOAT3', null, 'six-pack', null, null, null, 'listed', 0.9, T0, T0, T0, T0);
  sql.prepare(`INSERT INTO fleet_vessel_facts(id,vessel_id,field,value_json,value_key,source_id,source_url,method,confidence,rights,retrieved_at,first_seen_at,last_seen_at,run_id)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run('f'.repeat(32), vid(1), 'website', '"https://boat1.example.com/"', 'k'.repeat(16), 'operator-site',
    'https://boat1.example.com/', 'page', 0.8, 'facts-only', T0, T0, T0, 'run-0');
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)`).run('boat-a1', 'sea-example', 'Sea Example', 'morro-bay', 'morro-bay', 'verified', T0, T0);
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)`).run('boat-a2', 'tide-example', 'Tide Example', 'morro-bay', 'morro-bay', 'verified', T0, T0);
  const review = sql.prepare(`INSERT INTO fleet_reviews(id,region,kind,subject_id,candidate_json,proposal_json,score,status,opened_at,run_id) VALUES(?,?,?,?,?,?,?,'open',?,?)`);
  const R = {merge: 'a'.repeat(32), mmsi: 'b'.repeat(32), cls: 'c'.repeat(32), link: 'd'.repeat(32), vanished: 'e'.repeat(32), other: '1'.repeat(32)};
  review.run(R.merge, REGION, 'merge', vid(1), JSON.stringify({source_id: 'teck-directory', name: 'TEST BOAT 1'}), JSON.stringify({vessel_id: vid(1), parts: {name: 0.9}}), 0.72, '2026-10-02T00:00:00.000Z', 'run-1');
  review.run(R.mmsi, REGION, 'mmsi', vid(2), JSON.stringify({mmsi: '366000002'}), null, 0.7, '2026-10-02T01:00:00.000Z', 'run-1');
  review.run(R.cls, REGION, 'class', vid(2), null, JSON.stringify({vessel_class: 'six-pack'}), 0.8, '2026-10-02T02:00:00.000Z', 'run-1');
  review.run(R.link, REGION, 'advisor-link', 'boat-a1', null, JSON.stringify({vessel_id: vid(1)}), 0.95, '2026-10-02T03:00:00.000Z', 'run-1');
  review.run(R.vanished, REGION, 'vanished', vid(2), null, null, null, '2026-10-02T04:00:00.000Z', 'run-1');
  review.run(R.other, 'OR', 'merge', vid(3), null, null, 0.7, '2026-10-02T05:00:00.000Z', 'run-1');
  return {sql, db, R};
}

const env = (db, extra = ON) => ({ASSETS, DB: db, ...extra});
async function get(db, path, {owner = ADMIN, extra} = {}) {
  const response = await worker.fetch(new Request(ORIGIN + path, {headers: owner ? {'x-test-owner': owner} : {}}), env(db, extra));
  return {status: response.status, body: await response.json().catch(() => null)};
}
async function post(db, path, payload, {owner = ADMIN, extra} = {}) {
  const response = await worker.fetch(new Request(ORIGIN + path, {method: 'POST', headers: {'Content-Type': 'application/json', Origin: ORIGIN, ...(owner ? {'x-test-owner': owner} : {})},
    body: JSON.stringify(payload)}), env(db, extra));
  return {status: response.status, body: await response.json().catch(() => null)};
}
const row = (sql, q, ...a) => { const r = sql.prepare(q).get(...a); return r ? {...r} : r; };
const pins = (sql, id) => JSON.parse(row(sql, 'SELECT pinned_json FROM fleet_vessels WHERE id=?', id).pinned_json);

let verifierSaved, clockSaved;
test.before(() => {
  verifierSaved = fleetJobs.verify; clockSaved = jobsDeps.now;
  fleetJobs.verify = async token => token === 'good' ? {jti: 'run-1'} : false;
  jobsDeps.now = () => new Date(T1);
});
test.after(() => { fleetJobs.verify = verifierSaved; jobsDeps.now = clockSaved; });

const ROUTES = (R) => [
  ['GET', '/api/admin/fleet/reviews'], ['POST', `/api/admin/fleet/reviews/${R.merge}`], ['GET', '/api/admin/fleet/vessels'],
  ['GET', `/api/admin/fleet/vessels/${vid(1)}`], ['POST', `/api/admin/fleet/vessels/${vid(1)}`], ['POST', `/api/admin/fleet/vessels/${vid(1)}/link-advisor`],
];

test('acceptance 1: non-admins, anonymous callers and FLEET_ENABLED off all get 404 (401 unsigned) and nothing changes', {skip}, async () => {
  const {sql, db, R} = setup();
  try {
    const before = JSON.stringify([sql.prepare('SELECT * FROM fleet_reviews ORDER BY id').all(), sql.prepare('SELECT * FROM fleet_vessels ORDER BY id').all()]);
    const payload = {action: 'new-vessel', fields: {passengers_max: 6}, boat_id: 'boat-a1'};
    for (const [method, path] of ROUTES(R)) {
      const call = (opts) => method === 'GET' ? get(db, path, opts) : post(db, path, payload, opts);
      assert.equal((await call({owner: 'someone-else'})).status, 404, `non-admin ${method} ${path}`);
      assert.equal((await call({extra: {}})).status, 404, `fleet off ${method} ${path}`);
      assert.equal((await call({extra: {TEXT_ADVISOR_ENABLED: 'true'}})).status, 404, `advisor flag only ${method} ${path}`);
      const anonymous = await call({owner: null});
      assert.ok([401, 404].includes(anonymous.status), `anonymous ${method} ${path}: ${anonymous.status}`);
    }
    assert.equal(JSON.stringify([sql.prepare('SELECT * FROM fleet_reviews ORDER BY id').all(), sql.prepare('SELECT * FROM fleet_vessels ORDER BY id').all()]), before);
  } finally { sql.close(); }
});

test('GET reviews: open by default, newest first, filters, actions per kind, paging cursor validated', {skip}, async () => {
  const {sql, db, R} = setup();
  try {
    const all = await get(db, '/api/admin/fleet/reviews');
    assert.equal(all.status, 200);
    assert.deepEqual(all.body.reviews.map(r => r.id), [R.other, R.vanished, R.link, R.cls, R.mmsi, R.merge]);
    const merge = all.body.reviews.find(r => r.id === R.merge);
    assert.deepEqual(merge.actions, ['same-vessel', 'new-vessel', 'dismiss']);
    assert.equal(merge.subject_name, 'Test Boat 1');
    assert.deepEqual(merge.proposal, {vessel_id: vid(1), parts: {name: 0.9}});
    assert.equal(all.body.next, null);
    assert.deepEqual((await get(db, '/api/admin/fleet/reviews?region=CA&kind=mmsi')).body.reviews.map(r => r.id), [R.mmsi]);
    assert.deepEqual((await get(db, '/api/admin/fleet/reviews?status=decided')).body.reviews, []);
    for (const q of ['status=closed', 'kind=nope', 'region=../x', 'cursor=bad']) assert.equal((await get(db, '/api/admin/fleet/reviews?' + q)).status, 400, q);
    const after = await get(db, `/api/admin/fleet/reviews?cursor=${encodeURIComponent(`2026-10-02T03:00:00.000Z|${R.link}`)}`);
    assert.deepEqual(after.body.reviews.map(r => r.id), [R.cls, R.mmsi, R.merge]);
  } finally { sql.close(); }
});

test('acceptance 2: a decided merge comes back in the next job snapshot, and the queue no longer lists it', {skip}, async () => {
  const {sql, db, R} = setup();
  try {
    const decided = await post(db, `/api/admin/fleet/reviews/${R.merge}`, {action: 'same-vessel', note: 'same hull, renamed'});
    assert.equal(decided.status, 200, JSON.stringify(decided.body));
    assert.equal(decided.body.review.status, 'decided');
    assert.equal(decided.body.review.decided_by, ADMIN);
    assert.deepEqual(decided.body.review.decision, {action: 'same-vessel', vessel_id: vid(1), note: 'same hull, renamed'});

    const snapshot = await worker.fetch(new Request(ORIGIN + `/api/fleet/jobs/snapshot?region=${REGION}&cursor=r:`, {headers: {Authorization: 'Bearer good'}}), env(db));
    const body = await snapshot.json();
    assert.equal(snapshot.status, 200);
    assert.deepEqual(body.reviews.map(r => [r.id, r.status, r.decision]), [[R.merge, 'decided', {action: 'same-vessel', vessel_id: vid(1), note: 'same hull, renamed'}]]);
    assert.ok(!(await get(db, '/api/admin/fleet/reviews')).body.reviews.some(r => r.id === R.merge));

    // The same decision again is a repeat; a different one is a conflict; a job cannot reopen it.
    const again = await post(db, `/api/admin/fleet/reviews/${R.merge}`, {action: 'same-vessel'});
    assert.equal(again.status, 200); assert.equal(again.body.repeated, true);
    assert.equal((await post(db, `/api/admin/fleet/reviews/${R.merge}`, {action: 'new-vessel'})).status, 409);
    const reopen = await worker.fetch(new Request(ORIGIN + '/api/fleet/jobs/registry', {method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer good'},
      body: JSON.stringify({region: REGION, run_id: 'run-2', ops: [{op: 'review.open', id: R.merge, kind: 'merge', fingerprint: 'x', opened_at: T1}]})}), env(db));
    assert.equal(reopen.status, 400);   // the id is not sha256(kind|fingerprint); nothing written
    assert.equal(row(sql, 'SELECT status FROM fleet_reviews WHERE id=?', R.merge).status, 'decided');

    const dismissed = await post(db, `/api/admin/fleet/reviews/${R.vanished}`, {action: 'dismiss'});
    assert.equal(dismissed.body.review.status, 'dismissed');
  } finally { sql.close(); }
});

test('decisions validate the action for the kind, the vessel region and the inputs, and write nothing when refused', {skip}, async () => {
  const {sql, db, R} = setup();
  try {
    const refusals = [
      [R.merge, {action: 'set-class', vessel_class: 'six-pack'}],       // not a merge action
      [R.merge, {action: 'explode'}],
      [R.merge, {action: 'same-vessel', vessel_id: vid(3)}],             // another region
      [R.merge, {action: 'same-vessel', vessel_id: 'nope'}],
      [R.merge, {action: 'new-vessel', mmsi: '366000009'}],              // field the action does not use
      [R.merge, {action: 'new-vessel', extra: 1}],
      [R.mmsi, {action: 'set-mmsi', mmsi: '12345'}],
      [R.cls, {action: 'set-class', vessel_class: 'yacht'}],
      [R.vanished, {action: 'set-status', status: 'gone'}],
      [R.merge, {action: 'new-vessel', note: 'x'.repeat(2001)}],
    ];
    for (const [id, payload] of refusals) assert.equal((await post(db, `/api/admin/fleet/reviews/${id}`, payload)).status, 400, JSON.stringify(payload));
    assert.equal((await post(db, `/api/admin/fleet/reviews/${'9'.repeat(32)}`, {action: 'dismiss'})).status, 404);
    assert.equal((await post(db, '/api/admin/fleet/reviews/not-an-id', {action: 'dismiss'})).status, 404);
    assert.equal(row(sql, "SELECT COUNT(*) AS n FROM fleet_reviews WHERE status<>'open'").n, 0);
    assert.equal(row(sql, "SELECT COUNT(*) AS n FROM fleet_vessel_facts WHERE source_id='admin'").n, 0);
  } finally { sql.close(); }
});

test('set-mmsi, set-class and set-status decisions write admin facts and pin; advisor-link sets fleet_vessel_id', {skip}, async () => {
  const {sql, db, R} = setup();
  try {
    const mmsi = await post(db, `/api/admin/fleet/reviews/${R.mmsi}`, {action: 'set-mmsi'});   // mmsi from the candidate, vessel from the subject
    assert.equal(mmsi.status, 200, JSON.stringify(mmsi.body));
    assert.equal(row(sql, 'SELECT mmsi FROM fleet_vessels WHERE id=?', vid(2)).mmsi, '366000002');
    assert.equal(mmsi.body.review.decision.fact_ids.length, 1);
    const cls = await post(db, `/api/admin/fleet/reviews/${R.cls}`, {action: 'set-class'});   // class from the proposal
    assert.equal(cls.status, 200);
    const gone = await post(db, `/api/admin/fleet/reviews/${R.vanished}`, {action: 'set-status', status: 'inactive'});
    assert.equal(gone.status, 200);
    const v2 = row(sql, 'SELECT vessel_class,status,updated_at FROM fleet_vessels WHERE id=?', vid(2));
    assert.deepEqual({...v2}, {vessel_class: 'six-pack', status: 'inactive', updated_at: v2.updated_at});
    assert.ok(v2.updated_at > T0);
    assert.deepEqual(Object.keys(pins(sql, vid(2))).sort(), ['mmsi', 'status', 'vessel_class']);
    const facts = sql.prepare("SELECT field,value_json,source_url,method,confidence,run_id FROM fleet_vessel_facts WHERE vessel_id=? AND source_id='admin' ORDER BY field").all(vid(2)).map(r => ({...r}));
    assert.deepEqual(facts, [
      {field: 'mmsi', value_json: '"366000002"', source_url: `admin:${ADMIN}`, method: 'admin', confidence: 1, run_id: null},
      {field: 'status', value_json: '"inactive"', source_url: `admin:${ADMIN}`, method: 'admin', confidence: 1, run_id: null},
      {field: 'vessel_class', value_json: '"six-pack"', source_url: `admin:${ADMIN}`, method: 'admin', confidence: 1, run_id: null},
    ]);

    const link = await post(db, `/api/admin/fleet/reviews/${R.link}`, {action: 'same-vessel'});
    assert.equal(link.status, 200, JSON.stringify(link.body));
    assert.deepEqual(link.body.review.decision, {action: 'same-vessel', vessel_id: vid(1), boat_id: 'boat-a1'});
    assert.equal(row(sql, 'SELECT fleet_vessel_id FROM advisor_boats WHERE id=?', 'boat-a1').fleet_vessel_id, vid(1));
  } finally { sql.close(); }
});

test('acceptance 3: an admin vessel edit is a fact with source_url admin:<id>, pins the field, and a job upsert cannot overwrite it', {skip}, async () => {
  const {sql, db} = setup();
  try {
    const edit = await post(db, `/api/admin/fleet/vessels/${vid(1)}`, {fields: {website: 'https://boat1.example.org/', passengers_max: 24, waters_json: ['ocean']}});
    assert.equal(edit.status, 200, JSON.stringify(edit.body));
    const website = edit.body.facts.find(f => f.field === 'website' && f.source_id === 'admin');
    assert.equal(website.source_url, `admin:${ADMIN}`);
    assert.equal(website.method, 'admin');
    assert.equal(website.value, 'https://boat1.example.org/');
    assert.equal(edit.body.fields.website.fact_id, website.id);
    assert.equal(edit.body.fields.website.pinned.by, ADMIN);
    assert.equal(edit.body.fields.website.pinned.fact_id, website.id);
    assert.deepEqual(edit.body.vessel.pinned, ['passengers_max', 'waters_json', 'website']);
    assert.deepEqual(edit.body.vessel.waters, ['ocean']);
    assert.ok(edit.body.facts.some(f => f.field === 'waters' && f.source_id === 'admin'));
    assert.ok(edit.body.vessel.updated_at > T0);
    // The operator-site fact stays as history, not superseded (different source).
    assert.equal(edit.body.facts.find(f => f.source_id === 'operator-site').superseded_at, null);

    // A second admin edit supersedes the first admin fact for that field.
    const second = await post(db, `/api/admin/fleet/vessels/${vid(1)}`, {fields: {website: 'https://boat1.example.net/'}});
    const admins = second.body.facts.filter(f => f.field === 'website' && f.source_id === 'admin');
    assert.equal(admins.length, 2);
    assert.equal(admins.filter(f => f.superseded_at === null).length, 1);
    assert.equal(admins.find(f => f.superseded_at !== null).superseded_by, admins.find(f => f.superseded_at === null).id);

    // A job upsert later in time keeps the pinned columns and takes the others.
    const job = await worker.fetch(new Request(ORIGIN + '/api/fleet/jobs/registry', {method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer good'},
      body: JSON.stringify({region: REGION, run_id: 'run-3', ops: [{op: 'vessel.upsert', id: vid(1), slug: 'test-boat-1', name: 'Test Boat 1', name_norm: 'TESTBOAT1',
        website: 'https://job.example.com/', passengers_max: 40, waters_json: ['bay'], length_ft: 60, first_seen_at: T0, last_seen_at: '2026-10-06T00:00:00.000Z'}]})}), env(db));
    assert.equal(job.status, 200);
    assert.deepEqual({...row(sql, 'SELECT website,passengers_max,waters_json,length_ft FROM fleet_vessels WHERE id=?', vid(1))},
      {website: 'https://boat1.example.net/', passengers_max: 24, waters_json: '["ocean"]', length_ft: 60});

    // Unpin releases the column without changing its value.
    const unpinned = await post(db, `/api/admin/fleet/vessels/${vid(1)}`, {unpin: ['passengers_max']});
    assert.equal(unpinned.status, 200);
    assert.deepEqual(unpinned.body.vessel.pinned, ['waters_json', 'website']);
    assert.equal(unpinned.body.vessel.passengers_max, 24);
  } finally { sql.close(); }
});

test('vessel edits: validation, null clears, removal requests, and an unreadable pinned_json is refused', {skip}, async () => {
  const {sql, db} = setup();
  try {
    const bad = [
      {fields: {slug: 'new-slug'}}, {fields: {mmsi: '12'}}, {fields: {website: 'http://boat.example.com/'}}, {fields: {name: 'Renamed'}},
      {fields: {status: null}}, {fields: {operator_id: 'op-test-0000000000000099'}}, {fields: {map_display_consent: 'all'}}, {fields: {}},
      {unpin: ['slug']}, {fields: {mmsi: '366000003'}, unpin: ['mmsi']}, {removal_requested: true}, {other: 1}, {},
    ];
    for (const payload of bad) assert.equal((await post(db, `/api/admin/fleet/vessels/${vid(1)}`, payload)).status, 400, JSON.stringify(payload));
    assert.equal((await post(db, `/api/admin/fleet/vessels/${'0'.repeat(32)}`, {fields: {bunks: 2}})).status, 404);
    assert.equal(row(sql, "SELECT COUNT(*) AS n FROM fleet_vessel_facts WHERE source_id='admin'").n, 0);

    const cleared = await post(db, `/api/admin/fleet/vessels/${vid(1)}`, {fields: {phone_business: null, name: 'Test Boat One', name_norm: 'TESTBOATONE'}});
    assert.equal(cleared.status, 200, JSON.stringify(cleared.body));
    assert.equal(cleared.body.vessel.phone_business, null);
    assert.equal(cleared.body.fields.phone_business.pinned.by, ADMIN);
    assert.ok(cleared.body.facts.some(f => f.field === 'phone_business' && f.value === null && f.source_id === 'admin'));

    const removal = await post(db, `/api/admin/fleet/vessels/${vid(1)}`, {fields: {profile_status: 'hidden', map_display_consent: 'aggregate'}, removal_requested: true});
    assert.equal(removal.status, 200);
    const at = removal.body.vessel.removal_requested_at;
    assert.ok(at);
    const relisted = await post(db, `/api/admin/fleet/vessels/${vid(1)}`, {fields: {profile_status: 'listed'}});
    assert.equal(relisted.body.vessel.removal_requested_at, at, 'the request date is kept when an admin unhides the boat');
    assert.equal(relisted.body.vessel.map_display_consent, 'aggregate');

    sql.prepare("UPDATE fleet_vessels SET pinned_json='not json' WHERE id=?").run(vid(2));
    assert.equal((await post(db, `/api/admin/fleet/vessels/${vid(2)}`, {fields: {bunks: 2}})).status, 409);
  } finally { sql.close(); }
});

test('GET vessels: filters, paging and the detail view', {skip}, async () => {
  const {sql, db} = setup();
  try {
    const all = await get(db, '/api/admin/fleet/vessels');
    assert.equal(all.status, 200);
    assert.deepEqual(all.body.vessels.map(v => v.slug), ['other-boat-3', 'test-boat-1', 'test-boat-2']);
    assert.equal(all.body.vessels[2].open_reviews, 3);
    assert.deepEqual((await get(db, '/api/admin/fleet/vessels?region=CA&class=none')).body.vessels.map(v => v.slug), ['test-boat-2']);
    assert.deepEqual((await get(db, '/api/admin/fleet/vessels?profile_status=listed&completeness_max=0.7')).body.vessels.map(v => v.slug), ['test-boat-1']);
    assert.deepEqual((await get(db, '/api/admin/fleet/vessels?ais=watched')).body.vessels, []);
    assert.deepEqual((await get(db, `/api/admin/fleet/vessels?cursor=TESTBOAT1:${vid(1)}`)).body.vessels.map(v => v.slug), ['test-boat-2']);
    for (const q of ['class=yacht', 'status=gone', 'ais=maybe', 'completeness_max=2', 'cursor=x', 'region=../x']) assert.equal((await get(db, '/api/admin/fleet/vessels?' + q)).status, 400, q);

    const detail = await get(db, `/api/admin/fleet/vessels/${vid(1)}`);
    assert.equal(detail.status, 200);
    assert.equal(detail.body.vessel.slug, 'test-boat-1');
    assert.equal(detail.body.operator.slug, 'test-landing');
    assert.deepEqual(detail.body.fields.website, {value: 'https://boat1.example.com/', pinned: null, fact_id: 'f'.repeat(32)});
    assert.equal(detail.body.open_reviews.length, 1);
    assert.equal((await get(db, `/api/admin/fleet/vessels/${'0'.repeat(32)}`)).status, 404);
    assert.equal((await get(db, '/api/admin/fleet/vessels/nope')).status, 404);
  } finally { sql.close(); }
});

test('link-advisor links and unlinks one advisor boat per vessel', {skip}, async () => {
  const {sql, db} = setup();
  try {
    const link = await post(db, `/api/admin/fleet/vessels/${vid(1)}/link-advisor`, {boat_id: 'boat-a1'});
    assert.equal(link.status, 200, JSON.stringify(link.body));
    assert.deepEqual(link.body.advisor_boats.map(b => b.id), ['boat-a1']);
    assert.equal((await post(db, `/api/admin/fleet/vessels/${vid(1)}/link-advisor`, {boat_id: 'boat-a1'})).status, 200, 'repeat');
    assert.equal((await post(db, `/api/admin/fleet/vessels/${vid(1)}/link-advisor`, {boat_id: 'boat-a2'})).status, 409, 'vessel taken');
    assert.equal((await post(db, `/api/admin/fleet/vessels/${vid(2)}/link-advisor`, {boat_id: 'boat-a1'})).status, 409, 'boat linked elsewhere');
    assert.equal((await post(db, `/api/admin/fleet/vessels/${vid(1)}/link-advisor`, {boat_id: 'no-such-boat'})).status, 400);
    assert.equal((await post(db, `/api/admin/fleet/vessels/${'0'.repeat(32)}/link-advisor`, {boat_id: 'boat-a1'})).status, 404);
    const unlink = await post(db, `/api/admin/fleet/vessels/${vid(1)}/link-advisor`, {boat_id: 'boat-a1', unlink: true});
    assert.equal(unlink.status, 200);
    assert.deepEqual(unlink.body.advisor_boats, []);
    assert.equal(row(sql, 'SELECT fleet_vessel_id FROM advisor_boats WHERE id=?', 'boat-a1').fleet_vessel_id, null);
  } finally { sql.close(); }
});

test('two different decisions by the same admin at the same instant: only the stored one applies its writes', {skip}, async () => {
  const {decideFleetReview} = await import('../server/fleet/admin/reviews.ts');
  const {sql, db, R} = setup();
  try {
    // Hold both batches until both decisions have read the open review, then run them in arrival order.
    // D1 runs one batch at a time, so the held batches run one after the other.
    const pending = [];
    let release, queue = Promise.resolve();
    const both = new Promise(resolve => { release = resolve; });
    const racing = {prepare: q => db.prepare(q), async batch(statements) {
      pending.push(statements); if (pending.length === 2) release();
      await both;
      const run = queue.then(() => db.batch(statements)); queue = run.catch(() => {}); return run;
    }};
    const at = '2026-10-05T12:00:00.000Z';
    const [reject, set] = await Promise.all([
      decideFleetReview(racing, R.mmsi, {action: 'reject-mmsi'}, ADMIN, at),
      decideFleetReview(racing, R.mmsi, {action: 'set-mmsi'}, ADMIN, at),
    ]);
    assert.equal(pending.length, 2, 'both decisions reached the write');
    assert.equal(reject.status, 'ok');
    assert.equal(set.status, 'conflict');
    const stored = row(sql, 'SELECT decision_json FROM fleet_reviews WHERE id=?', R.mmsi);
    assert.deepEqual(JSON.parse(stored.decision_json), {action: 'reject-mmsi', vessel_id: vid(2), mmsi: '366000002'});
    assert.equal(row(sql, 'SELECT mmsi FROM fleet_vessels WHERE id=?', vid(2)).mmsi, null, 'the losing set-mmsi wrote nothing');
    assert.equal(row(sql, "SELECT COUNT(*) AS n FROM fleet_vessel_facts WHERE source_id='admin'").n, 0);
    assert.deepEqual(pins(sql, vid(2)), {});
  } finally { sql.close(); }
});

test('a decision that writes facts is refused (409) on an unreadable pinned_json; one that writes none still decides', {skip}, async () => {
  const {sql, db, R} = setup();
  try {
    sql.prepare("UPDATE fleet_vessels SET pinned_json='[1]' WHERE id=?").run(vid(2));
    assert.equal((await post(db, `/api/admin/fleet/reviews/${R.cls}`, {action: 'set-class'})).status, 409);
    assert.equal(row(sql, 'SELECT status FROM fleet_reviews WHERE id=?', R.cls).status, 'open');
    assert.equal(row(sql, "SELECT COUNT(*) AS n FROM fleet_vessel_facts WHERE source_id='admin'").n, 0);
    assert.equal((await post(db, `/api/admin/fleet/reviews/${R.mmsi}`, {action: 'reject-mmsi'})).status, 200);
  } finally { sql.close(); }
});

test('the link statement is one-to-one by itself: a link that lost a race writes nothing and answers 409', {skip}, async () => {
  const {linkStatements, linkAdvisor} = await import('../server/fleet/admin/vessels.ts');
  const {sql, db} = setup();
  try {
    // The checks pass, then boat-a2 is linked to the vessel before the write runs.
    const first = await linkStatements(db, vid(1), 'boat-a1', false, T1);
    sql.prepare('UPDATE advisor_boats SET fleet_vessel_id=? WHERE id=?').run(vid(1), 'boat-a2');
    const [result] = await db.batch(first.statements);
    assert.equal(result.meta.changes, 0);
    assert.equal(row(sql, 'SELECT fleet_vessel_id FROM advisor_boats WHERE id=?', 'boat-a1').fleet_vessel_id, null);
    // Through the route: a write that changed nothing because of the race is a conflict.
    sql.prepare('UPDATE advisor_boats SET fleet_vessel_id=NULL WHERE id=?').run('boat-a2');
    const racing = {prepare: q => db.prepare(q), async batch(statements) {
      sql.prepare('UPDATE advisor_boats SET fleet_vessel_id=? WHERE id=?').run(vid(1), 'boat-a2'); return db.batch(statements); }};
    assert.equal((await linkAdvisor(racing, vid(1), {boat_id: 'boat-a1'}, T1)).status, 'conflict');
    assert.equal(row(sql, 'SELECT fleet_vessel_id FROM advisor_boats WHERE id=?', 'boat-a1').fleet_vessel_id, null);
  } finally { sql.close(); }
});

// SC1322-01: the fleet jobs snapshot keeps every operator and vessel row, but phone_business and
// email_business are null for a do-not-contact operator and for every vessel whose operator is
// do-not-contact. A vessel with no operator, or whose operator id names no row, keeps its contacts.
// Through the Worker against the real migrations (tests/_advisor_d1.mjs). Fixtures are synthetic.
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
const {jobsDeps, PAGE} = await import('../server/fleet/jobs.ts');

const skip = sqliteUnavailable ?? false;
const ORIGIN = 'https://skippercast.com', REGION = 'CA', RUN = 'run-20261102', T0 = '2026-11-02T09:47:00.000Z';
const ASSETS = {fetch: async () => new Response('asset', {status: 299})};
const AUTH = {Authorization: 'Bearer good'};
const sha = s => createHash('sha256').update(s, 'utf8').digest('hex');

let saved;
test.before(() => {
  saved = [fleetJobs.verify, jobsDeps.now];
  fleetJobs.verify = async token => token === 'good' ? {jti: 'run-1'} : false;
  jobsDeps.now = () => new Date('2026-11-02T10:00:00.000Z');
});
test.after(() => { [fleetJobs.verify, jobsDeps.now] = saved; });

const env = db => ({ASSETS, DB: db, FLEET_ENABLED: 'true'});
async function post(db, ops) {
  const response = await worker.fetch(new Request(ORIGIN + '/api/fleet/jobs/registry', {method: 'POST', headers: {'Content-Type': 'application/json', ...AUTH},
    body: JSON.stringify({region: REGION, run_id: RUN, ops})}), env(db));
  return {status: response.status, body: await response.json()};
}
/** Every snapshot page, in order. */
async function pages(db) {
  const out = [];
  let cursor = null;
  do {
    const response = await worker.fetch(new Request(`${ORIGIN}/api/fleet/jobs/snapshot?region=${REGION}${cursor ? '&cursor=' + encodeURIComponent(cursor) : ''}`, {headers: AUTH}), env(db));
    assert.equal(response.status, 200);
    const body = await response.json();
    out.push(body);
    cursor = body.next;
  } while (cursor !== null && out.length < 50);
  return out;
}
const all = (list, key) => list.flatMap(p => p[key]);
const byId = list => Object.fromEntries(list.map(r => [r.id, r]));

// Operators 1..4 and vessels 1..6: vessel n belongs to operator ((n-1) % 3) + 1, vessel 5 has no operator,
// vessel 6 names an operator id with no row (set in SQL; the registry would refuse it).
const opId = n => `op-test-000000000000000${n}`;
const operator = n => ({op: 'operator.upsert', id: opId(n), slug: `test-landing-${n}`, name: `Test Landing ${n}`, website: `https://landing${n}.example.com/`,
  phone_business: `+1805555010${n}`, email_business: `office${n}@landing${n}.example.com`, booking_platform: 'fareharbor', seen_at: T0});
const vid = n => sha(`${REGION}:name-port:test-boat-${n}|morro-bay`).slice(0, 32);
const vessel = n => ({op: 'vessel.upsert', id: vid(n), creation_key: `name-port:test-boat-${n}|morro-bay`, slug: `test-boat-${n}`, name: `Test Boat ${n}`,
  name_norm: `TESTBOAT${n}`, port_id: 'morro-bay', vessel_class: 'inspected-party', waters_json: ['ocean'], website: `https://boat${n}.example.com/`,
  phone_business: `+1805555020${n}`, email_business: `skipper${n}@boat${n}.example.com`, status: 'active', profile_status: 'listed',
  first_seen_at: T0, last_seen_at: T0, ...(n <= 4 ? {operator_id: opId(((n - 1) % 3) + 1)} : {})});

async function seeded() {
  const {sql, db} = advisorDatabase();
  const response = await post(db, [1, 2, 3, 4].map(operator).concat([1, 2, 3, 4, 5, 6].map(vessel)));
  assert.equal(response.status, 200, JSON.stringify(response.body));
  sql.prepare("UPDATE fleet_vessels SET operator_id='op-missing-0000000000' WHERE id=?").run(vid(6));
  return {sql, db};
}
const status = (sql, n, value) => sql.prepare('UPDATE fleet_operators SET outreach_status=? WHERE id=?').run(value, opId(n));
const NULLED = row => ({...row, phone_business: null, email_business: null});

test('a do-not-contact operator and its vessels stay in the snapshot with null phone/email; nothing else changes', {skip}, async () => {
  const {sql, db} = await seeded();
  try {
    const before = await pages(db);
    const [ops0, vessels0] = [byId(all(before, 'operators')), byId(all(before, 'vessels'))];
    assert.equal(ops0[opId(1)].phone_business, '+18055550101', 'contacts present before the opt-out');
    assert.equal(vessels0[vid(1)].email_business, 'skipper1@boat1.example.com');
    status(sql, 1, 'do-not-contact');
    const after = await pages(db);
    const [ops1, vessels1] = [byId(all(after, 'operators')), byId(all(after, 'vessels'))];
    assert.deepEqual(Object.keys(ops1).sort(), Object.keys(ops0).sort(), 'every operator row stays');
    assert.deepEqual(Object.keys(vessels1).sort(), Object.keys(vessels0).sort(), 'every vessel row stays');
    // DNC operator: row present, contacts null, every other field and the key order as before.
    assert.deepEqual(ops1[opId(1)], NULLED(ops0[opId(1)]));
    assert.deepEqual(Object.keys(ops1[opId(1)]), Object.keys(ops0[opId(1)]), 'key order unchanged');
    assert.equal(ops1[opId(1)].slug, 'test-landing-1');
    // Vessels 1 and 4 belong to the DNC operator; vessel 5 has none, vessel 6 a missing operator.
    for (const n of [1, 4]) {
      assert.deepEqual(vessels1[vid(n)], NULLED(vessels0[vid(n)]), `vessel ${n}`);
      assert.deepEqual(Object.keys(vessels1[vid(n)]), Object.keys(vessels0[vid(n)]), `vessel ${n} key order`);
    }
    for (const n of [2, 3, 5, 6]) assert.deepEqual(vessels1[vid(n)], vessels0[vid(n)], `vessel ${n} unchanged`);
    assert.equal(vessels1[vid(5)].operator_id, null);
    assert.equal(vessels1[vid(5)].phone_business, '+18055550205', 'no operator, no opt-out');
    assert.equal(vessels1[vid(6)].email_business, 'skipper6@boat6.example.com', 'an operator id with no row is no opt-out');
    for (const n of [2, 3, 4]) assert.deepEqual(ops1[opId(n)], ops0[opId(n)], `operator ${n} unchanged`);
    // Lifting the opt-out brings the contacts back: the rows were never changed.
    status(sql, 1, 'none');
    assert.deepEqual(await pages(db), before);
  } finally { sql.close(); }
});

test('every other outreach status keeps the contacts; only the exact do-not-contact value hides them', {skip}, async () => {
  const {sql, db} = await seeded();
  try {
    for (const value of ['none', 'drafted', 'contacted', 'declined', 'replied', 'partner', 'Do-Not-Contact', 'do-not-contact ']) {
      status(sql, 2, value);
      const snap = await pages(db), op = byId(all(snap, 'operators'))[opId(2)], boat = byId(all(snap, 'vessels'))[vid(2)];
      assert.equal(op.phone_business, '+18055550102', value);
      assert.equal(op.email_business, 'office2@landing2.example.com', value);
      assert.equal(boat.phone_business, '+18055550202', value);
      assert.equal(boat.email_business, 'skipper2@boat2.example.com', value);
    }
    status(sql, 2, 'do-not-contact');
    const snap = await pages(db);
    assert.equal(byId(all(snap, 'operators'))[opId(2)].email_business, null);
    assert.equal(byId(all(snap, 'vessels'))[vid(2)].email_business, null);
    assert.equal(byId(all(snap, 'vessels'))[vid(5)].email_business, 'skipper5@boat5.example.com');
  } finally { sql.close(); }
});

test('paging is unchanged with do-not-contact rows mixed in: same ids on every page, same next cursors', {skip}, async () => {
  const {sql, db} = await seeded(), size = {...PAGE};
  try {
    PAGE.operators = 1; PAGE.vessels = 2;
    const shape = list => list.map(p => ({cursor: p.cursor, next: p.next, operators: p.operators.map(o => o.id), vessels: p.vessels.map(v => v.id)}));
    const before = shape(await pages(db));
    assert.equal(before.length, 4 + 3 + 1, 'four operator pages, three vessel pages, reviews');
    status(sql, 1, 'do-not-contact'); status(sql, 3, 'do-not-contact');
    const after = await pages(db);
    assert.deepEqual(shape(after), before);
    const vessels = byId(all(after, 'vessels'));
    assert.deepEqual([1, 2, 3, 4, 5, 6].map(n => vessels[vid(n)].phone_business === null), [true, false, true, true, false, false]);
    assert.deepEqual([1, 2, 3, 4].map(n => byId(all(after, 'operators'))[opId(n)].email_business === null), [true, false, true, false]);
  } finally { Object.assign(PAGE, size); sql.close(); }
});

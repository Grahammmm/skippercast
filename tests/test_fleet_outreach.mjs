// Charter fleet operators, outreach and lead score (CF-32; docs/plans/charter-fleet/design.md
// § 12, § 13; D14, US-S1..S4). Through the Worker against the real migrations, signed in with
// the test session helper. Synthetic operators, example.com URLs and 555-01XX numbers only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: deployed} = await import('../server/index.ts');
const {leadScore} = await import('../server/fleet/leadscore.ts');
const {routeOf, navOf} = await import('../web/admin/route.ts');
const worker = withSessions(deployed);

const skip = sqliteUnavailable ?? false;
const ORIGIN = 'https://skippercast.com', ADMIN = 'admin-fleet-1', ON = {FLEET_ENABLED: 'true'};
const ASSETS = {fetch: async () => new Response('asset', {status: 299})};
const OP_A = 'op-test-0000000000000001', OP_B = 'op-test-0000000000000002';
const T0 = '2026-01-01T00:00:00.000Z';
const ago = days => new Date(Date.now() - days * 86400e3).toISOString();
const vid = n => String(n).repeat(32).slice(0, 32);

function setup() {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(ADMIN, T0);
  const op = sql.prepare('INSERT INTO fleet_operators(id,region,slug,name,phone_business,created_at,updated_at) VALUES(?,?,?,?,?,?,?)');
  op.run(OP_A, 'CA', 'test-landing', 'Test Landing', '+18055550101', T0, T0);
  op.run(OP_B, 'CA', 'quiet-charters', 'Quiet Charters', null, T0, T0);
  const vessel = sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,operator_id,status,profile_status,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES(?,'CA',?,?,?,?,'active','hidden',?,?,?,?)`);
  vessel.run(vid(1), 'test-boat-1', 'Test Boat 1', 'TESTBOAT1', OP_A, T0, T0, T0, T0);
  vessel.run(vid(2), 'test-boat-2', 'Test Boat 2', 'TESTBOAT2', OP_A, T0, T0, T0, T0);
  vessel.run(vid(3), 'quiet-boat-3', 'Quiet Boat 3', 'QUIETBOAT3', OP_B, T0, T0, T0, T0);
  // Operator A: 25 landing-paired trips across 25 days (4 weeks of the last 12), an Instagram link from its own site, AIS seen 3 days ago.
  const trip = sql.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,departed_at,local_date,season,status,source,rights,classifier_version,computed_at)
    VALUES(?,'CA',?,'999000001',?,?,'2026','closed','aisstream','internal-only','v1',?)`);
  const pair = sql.prepare("INSERT INTO fleet_trip_reports(trip_id,report_kind,report_ref,match,confidence,created_at) VALUES(?,?,?,'alias-port-date',0.9,?)");
  for (let i = 0; i < 25; i++) {
    const at = ago(i + 1), id = `trip-${String(i).padStart(2, '0')}`;
    trip.run(id, vid(1 + (i % 2)), at, at.slice(0, 10), at);
    pair.run(id, 'landing', `report-${i}`, at);
  }
  trip.run('trip-old', vid(1), ago(400), ago(400).slice(0, 10), ago(400));
  pair.run('trip-old', 'landing', 'report-old', ago(400));
  // Advisor reports count toward frequency only: 83 days ago is week 11 (the 12th), 84 days ago is outside the 12 weeks.
  for (const d of [83, 84]) { trip.run(`trip-d${d}`, vid(2), ago(d), ago(d).slice(0, 10), ago(d)); pair.run(`trip-d${d}`, 'advisor', `advisor-${d}`, ago(d)); }
  const fact = sql.prepare(`INSERT INTO fleet_vessel_facts(id,vessel_id,field,value_json,value_key,source_id,source_url,method,confidence,rights,retrieved_at,first_seen_at,last_seen_at)
    VALUES(?,?,?,?,?,?,?,'page',0.8,'facts-only',?,?,?)`);
  fact.run('a'.repeat(32), vid(1), 'social.instagram.url', '"https://www.instagram.com/boat.example/"', 'k1', 'operator-site', 'https://boat1.example.com/', T0, T0, T0);
  fact.run('b'.repeat(32), vid(3), 'phone_business', '"+18055550102"', 'k2', 'operator-site', 'https://boat3.example.com/', T0, T0, T0);
  sql.prepare(`INSERT INTO fleet_ais_watch(region,mmsi,vessel_id,match_method,confidence,status,first_seen_at,last_seen_at,updated_at) VALUES('CA','999000001',?,'admin',1,'watched',?,?,?)`)
    .run(vid(1), T0, ago(3), T0);
  return {sql, db};
}

const env = (db, extra = ON) => ({ASSETS, DB: db, ...extra});
async function call(db, method, path, payload, {owner = ADMIN, extra} = {}) {
  const headers = {...(owner ? {'x-test-owner': owner} : {}), ...(method === 'POST' ? {'Content-Type': 'application/json', Origin: ORIGIN} : {})};
  const response = await worker.fetch(new Request(ORIGIN + path, {method, headers, ...(method === 'POST' ? {body: JSON.stringify(payload ?? {})} : {})}), env(db, extra));
  return {status: response.status, body: await response.json().catch(() => null)};
}
const get = (db, path, opts) => call(db, 'GET', path, null, opts);
const post = (db, path, payload, opts) => call(db, 'POST', path, payload, opts);
const row = (sql, q, ...a) => ({...sql.prepare(q).get(...a)});

test('acceptance 1: no route or function sends a message: the modules import no channel, sender, publisher or fetch', () => {
  // Walk the runtime (non-type) imports of the outreach module within server/ and check every file reached.
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../server');
  const seen = new Set(), queue = [resolve(root, 'fleet/admin/operators.ts')];
  while (queue.length) {
    const file = queue.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    const source = readFileSync(file, 'utf8');
    for (const [, spec] of source.matchAll(/^import\s+(?!type\b)[^'"]*from\s+'([^']+)'/gm)) if (spec.startsWith('.') && spec.endsWith('.ts')) queue.push(resolve(dirname(file), spec));
    const imports = [...source.matchAll(/^import\s.*$/gm)].map(m => m[0]).join('\n');
    assert.doesNotMatch(imports, /channels?\/|consumer|publish|social\/|meta\.ts|send|sender|notify|email|twilio|whatsapp/i, `${file} imports a sending module`);
    assert.doesNotMatch(source, /\bfetch\s*\(|\bsend[A-Z]\w*\s*\(|\.send\s*\(|sendMessage|dispatchWorkflow/, `${file} calls a sender`);
  }
  assert.deepEqual([...seen].map(f => f.slice(root.length + 1)).sort(), ['fleet/admin/operators.ts', 'fleet/leadscore.ts']);
});

test('lead score: weights from catalog/fleet/lead-score.json, parts, and missing inputs counted as zero', () => {
  const catalog = read('../catalog/fleet/lead-score.json');
  const full = leadScore({landing_report_volume: 100, reporting_frequency: 12, social_presence: 1, ais_seen_30d: 1});
  assert.equal(full.score, 100);
  assert.deepEqual(full.parts.map(p => [p.part, p.weight]), Object.entries(catalog.weights));
  const none = leadScore({landing_report_volume: null, reporting_frequency: null, social_presence: null, ais_seen_30d: null});
  assert.equal(none.score, 0);
  assert.deepEqual(none.missing, ['landing_report_volume', 'reporting_frequency', 'social_presence', 'ais_seen_30d']);
  const half = leadScore({landing_report_volume: 50, reporting_frequency: 6, social_presence: 0, ais_seen_30d: null});
  assert.deepEqual(half.parts.map(p => p.points), [15, 12.5, 0, 0]);
  assert.equal(half.score, 28); assert.deepEqual(half.missing, ['ais_seen_30d']);
});

test('GET operators: 404 unless admin and FLEET_ENABLED; ranked by lead score computed from D1, with parts', {skip}, async () => {
  const {sql, db} = setup();
  try {
    for (const opts of [{owner: 'someone-else'}, {extra: {}}, {extra: {TEXT_ADVISOR_ENABLED: 'true'}}])
      for (const [method, path] of [['GET', '/api/admin/fleet/operators'], ['GET', `/api/admin/fleet/operators/${OP_A}`], ['POST', `/api/admin/fleet/operators/${OP_A}/outreach`]])
        assert.equal((await call(db, method, path, {kind: 'draft', body: 'x'}, opts)).status, 404, `${method} ${path} ${JSON.stringify(opts)}`);
    assert.equal(row(sql, 'SELECT COUNT(*) AS n FROM fleet_outreach').n, 0);

    const list = await get(db, '/api/admin/fleet/operators?region=CA');
    assert.equal(list.status, 200);
    assert.deepEqual(list.body.operators.map(o => o.id), [OP_A, OP_B]);
    const [a, b] = list.body.operators;
    // A: 25 landing trips of 100 (7.5), weeks 0-3 and 11 of 12 (5/12 * 25 = 10.4), social (25), AIS seen (20) = 62.9 -> 63.
    assert.deepEqual(a.lead_score.parts.map(p => [p.part, p.raw, p.points]),
      [['landing_report_volume', 25, 7.5], ['reporting_frequency', 5, 10.4], ['social_presence', 1, 25], ['ais_seen_30d', 1, 20]]);
    assert.equal(a.lead_score.score, 63); assert.equal(a.vessels, 2);
    // B: its site was read but had no social link (0, not missing); no reports or AIS (missing).
    assert.equal(b.lead_score.score, 0);
    assert.deepEqual(b.lead_score.missing, ['landing_report_volume', 'reporting_frequency', 'ais_seen_30d']);
    for (const q of ['region=../x', 'outreach_status=nope', 'consent_status=nope']) assert.equal((await get(db, '/api/admin/fleet/operators?' + q)).status, 400, q);
    const detail = await get(db, `/api/admin/fleet/operators/${OP_A}`);
    assert.equal(detail.status, 200);
    assert.deepEqual(detail.body.vessels.map(v => v.id), [vid(1), vid(2)]);
    assert.equal(detail.body.lead_score.score, 63);
    assert.equal((await get(db, '/api/admin/fleet/operators/op-missing-000000000')).status, 404);
  } finally { sql.close(); }
});

test('acceptance 2: draft -> approve -> log as sent by owner, and no other transition', {skip}, async () => {
  const {sql, db} = setup();
  try {
    const made = await post(db, `/api/admin/fleet/operators/${OP_A}/outreach`, {kind: 'draft', channel: 'email', body: 'Hello from SkipperCast (synthetic).'});
    assert.equal(made.status, 200, JSON.stringify(made.body));
    const id = made.body.outreach.id;
    assert.equal(made.body.outreach.status, 'draft'); assert.equal(made.body.outreach.created_by, ADMIN);
    assert.equal(row(sql, 'SELECT outreach_status FROM fleet_operators WHERE id=?', OP_A).outreach_status, 'drafted');
    const act = action => post(db, `/api/admin/fleet/outreach/${id}`, {action});
    assert.equal((await act('log-sent')).status, 409, 'a draft must be approved before it is logged');
    assert.equal((await post(db, `/api/admin/fleet/outreach/${id}`, {action: 'send'})).status, 400);
    const approved = await act('approve');
    assert.equal(approved.status, 200);
    assert.equal(approved.body.outreach.status, 'approved'); assert.equal(approved.body.outreach.approved_by, ADMIN); assert.ok(approved.body.outreach.approved_at);
    assert.equal((await act('approve')).status, 409);
    const logged = await act('log-sent');
    assert.equal(logged.status, 200);
    assert.deepEqual([logged.body.outreach.kind, logged.body.outreach.status], ['sent-by-owner', 'logged']);
    assert.equal(row(sql, 'SELECT outreach_status FROM fleet_operators WHERE id=?', OP_A).outreach_status, 'contacted');
    const sent = row(sql, "SELECT created_by,created_at FROM fleet_outreach WHERE kind='note' AND body=?", `Logged as sent by the owner: draft ${id}.`);
    assert.equal(sent.created_by, ADMIN); assert.ok(Math.abs(Date.parse(sent.created_at) - Date.now()) < 60e3);
    for (const again of ['approve', 'discard', 'log-sent']) assert.equal((await act(again)).status, 409, again);

    const other = (await post(db, `/api/admin/fleet/operators/${OP_A}/outreach`, {kind: 'draft', body: 'Second draft.'})).body.outreach.id;
    assert.equal((await post(db, `/api/admin/fleet/outreach/${other}`, {action: 'discard'})).body.outreach.status, 'discarded');
    assert.equal((await post(db, `/api/admin/fleet/outreach/${other}`, {action: 'approve'})).status, 409);
    // Notes and replies are logged entries, not drafts: they take no action, and sent-by-owner cannot be created directly.
    const noteId = (await post(db, `/api/admin/fleet/operators/${OP_A}/outreach`, {kind: 'reply', channel: 'phone', body: 'Called back.'})).body.outreach.id;
    assert.equal((await post(db, `/api/admin/fleet/outreach/${noteId}`, {action: 'approve'})).status, 404);
    assert.equal((await post(db, `/api/admin/fleet/operators/${OP_A}/outreach`, {kind: 'sent-by-owner', body: 'x'})).status, 400);
    assert.equal((await get(db, `/api/admin/fleet/operators/${OP_A}/outreach`)).body.outreach.length, 4);   // draft, discarded draft, reply, log-sent note
  } finally { sql.close(); }
});

test('acceptance 3: do-not-contact blocks new drafts and approving or logging old ones', {skip}, async () => {
  const {sql, db} = setup();
  try {
    const old = (await post(db, `/api/admin/fleet/operators/${OP_B}/outreach`, {kind: 'draft', body: 'Draft before the request.'})).body.outreach.id;
    assert.equal((await post(db, `/api/admin/fleet/operators/${OP_B}`, {outreach_status: 'do-not-contact', outreach_note: 'Asked by phone.'})).status, 200);
    const logged = row(sql, "SELECT body,created_by,created_at FROM fleet_outreach WHERE operator_id=? AND kind='note'", OP_B);
    assert.equal(logged.body, 'Outreach status drafted -> do-not-contact. Asked by phone.'); assert.equal(logged.created_by, ADMIN);
    assert.ok(Math.abs(Date.parse(logged.created_at) - Date.now()) < 60e3);
    // do-not-contact operators rank last whatever their score (A outscores B).
    sql.prepare("UPDATE fleet_operators SET outreach_status=CASE id WHEN ? THEN 'do-not-contact' ELSE 'none' END").run(OP_A);
    assert.deepEqual((await get(db, '/api/admin/fleet/operators')).body.operators.map(o => o.id), [OP_B, OP_A]);
    sql.prepare("UPDATE fleet_operators SET outreach_status=CASE id WHEN ? THEN 'do-not-contact' ELSE 'none' END").run(OP_B);
    const refused = await post(db, `/api/admin/fleet/operators/${OP_B}/outreach`, {kind: 'draft', body: 'Should not exist.'});
    assert.equal(refused.status, 409);
    assert.equal(row(sql, "SELECT COUNT(*) AS n FROM fleet_outreach WHERE operator_id=? AND body='Should not exist.'", OP_B).n, 0);
    assert.equal((await post(db, `/api/admin/fleet/outreach/${old}`, {action: 'approve'})).status, 409);
    assert.equal((await post(db, `/api/admin/fleet/outreach/${old}`, {action: 'discard'})).status, 200);
    assert.equal((await post(db, `/api/admin/fleet/operators/${OP_B}/outreach`, {kind: 'note', body: 'Asked not to be contacted.'})).status, 200);
    assert.equal(row(sql, 'SELECT outreach_status FROM fleet_operators WHERE id=?', OP_B).outreach_status, 'do-not-contact');
  } finally { sql.close(); }
});

test('acceptance 4: consent changes record who and when, need a note, and revocation takes effect at once', {skip}, async () => {
  const {sql, db} = setup();
  try {
    const path = `/api/admin/fleet/operators/${OP_A}`;
    assert.equal((await post(db, path, {consent_status: 'content-sharing'})).status, 400, 'a note is required');
    assert.equal((await post(db, path, {consent_status: 'friends', consent_note: 'x'})).status, 400);
    assert.equal((await post(db, path, {consent_status: 'partner', consent_scope: ['billboards'], consent_note: 'x'})).status, 400);
    const granted = await post(db, path, {consent_status: 'content-sharing', consent_scope: ['profile', 'photos'], consent_note: 'Email reply, synthetic.'});
    assert.equal(granted.status, 200, JSON.stringify(granted.body));
    const op = granted.body.operator;
    assert.equal(op.consent_status, 'content-sharing'); assert.equal(op.consent_recorded_by, ADMIN);
    assert.ok(Math.abs(Date.parse(op.consent_recorded_at) - Date.now()) < 60e3);
    assert.deepEqual(op.consent_scope, {scope: ['profile', 'photos'], note: 'Email reply, synthetic.'});
    assert.equal(op.consent_revoked_at, null);
    const revoked = await post(db, path, {revoke_consent: true, consent_note: 'Phoned to withdraw.'});
    assert.equal(revoked.status, 200);
    assert.ok(revoked.body.operator.consent_revoked_at); assert.equal(revoked.body.operator.consent_recorded_by, ADMIN);
    assert.equal((await post(db, path, {revoke_consent: true, consent_note: 'again'})).status, 409);
    assert.equal((await post(db, path, {consent_status: 'partner', revoke_consent: true, consent_note: 'x'})).status, 400);
    const history = sql.prepare("SELECT body,created_by,status FROM fleet_outreach WHERE operator_id=? AND kind='note' ORDER BY created_at,body").all(OP_A).map(r => ({...r}));
    assert.equal(history.length, 2);
    assert.ok(history.every(h => h.created_by === ADMIN && h.status === 'logged'));
    assert.match(history.map(h => h.body).join('\n'), /Consent unknown -> content-sharing; scope: profile, photos\. Email reply/);
    assert.match(history.map(h => h.body).join('\n'), /Consent revoked \(was content-sharing\)\. Phoned to withdraw\./);
    assert.equal((await post(db, path, {unknown: 1})).status, 400);
  } finally { sql.close(); }
});

test('admin routes: #fleet-operators?region= and #fleet-operator/<id> open the operator views', () => {
  assert.deepEqual(routeOf('#fleet-operators?region=CA'), {view: 'fleet-operators', arg: 'CA'});
  assert.deepEqual(routeOf(`#fleet-operator/${OP_A}`), {view: 'fleet-operator', arg: OP_A});
  assert.equal(navOf('fleet-operator'), 'fleet-operators');
  assert.equal(routeOf('#fleet-operator/short').view, 'queue');
});

// SCA-540 / F01-05. Synthetic D1, object keys and a recording channel only.
// Default: qualify the contract against a reference control, not shipped code.
// Opt-in probe: node tests/test_f01_05_audit.mjs --baseline
// The probe runs the same contract against the real consumer starting at its
// `forget` action. A violation fails the probe; it is not a required CI check.
import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase, fakeBucket} from './_advisor_d1.mjs';

const BASELINE = process.argv.includes('--baseline');
const AT = '2026-10-03T15:00:00.000Z', NOW = Date.parse(AT);
const OWNED = ['advisor/media/subject/original', 'advisor/exports/subject/export', 'advisor/derived/photo/thumb'];
const OTHER = 'advisor/media/other/original';
const OWNED_JOBS = ['advisor.flow.subject', 'advisor.link.subject', 'advisor.link.reverse'];
const RECEIPT = 'advisor.forget.fixture-receipt', TTL = 60_000, LIMIT = 2;
const FAULT = 'injected cleanup failure';

function fixture(t) {
  const {db, sql} = advisorDatabase();
  t.after(() => sql.close());
  const run = (query, ...args) => sql.prepare(query).run(...args);
  // The address is an opaque fake for the recording channel, not a number or session.
  run("INSERT INTO advisor_contacts(id,channel,web_session,last_seen_at,created_at,updated_at) VALUES('subject','web','fixture-address',?,?,?)", AT, AT, AT);
  run("INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES('request','subject','in','web','DELETE','queued',?)", AT);
  run("INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,created_at,updated_at) VALUES('boat','fixture-boat','Fixture Boat','fixture','fixture','subject',?,?)", AT, AT);
  run("INSERT INTO advisor_media(id,contact_id,message_id,kind,mime,bytes,r2_key,sha256,created_at) VALUES('photo','subject','request','image','image/jpeg',1,?,'synthetic',?)", OWNED[0], AT);
  run("INSERT INTO advisor_reports(id,boat_id,contact_id,region,port,report_date,counts_json,source,media_id,created_at,updated_at) VALUES('report','boat','subject','fixture','fixture','2026-10-03','[]','count-board','photo',?,?)", AT, AT);
  for (const [key, value] of [[OWNED_JOBS[0], {flow: 'register'}], [OWNED_JOBS[1], {phone_contact_id: 'other'}],
    [OWNED_JOBS[2], {phone_contact_id: 'subject'}], ['advisor.link.unrelated', {phone_contact_id: 'other'}]]) {
    run('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)', key, JSON.stringify(value), AT);
  }
  const bucket = fakeBucket([...OWNED, OTHER]);
  const saved = () => JSON.parse(sql.prepare('SELECT value FROM job_state WHERE key=?').get(RECEIPT)?.value ?? 'null');
  const state = () => ({
    objects: OWNED.filter(key => bucket.store.has(key)),
    contact: sql.prepare("SELECT count(*) n FROM advisor_contacts WHERE id='subject'").get().n,
    inbound: sql.prepare("SELECT count(*) n FROM advisor_messages WHERE direction='in' AND contact_id='subject'").get().n,
    media: sql.prepare("SELECT count(*) n FROM advisor_media WHERE contact_id='subject'").get().n,
    jobs: OWNED_JOBS.filter(key => sql.prepare('SELECT 1 FROM job_state WHERE key=?').get(key)),
  });
  const notices = [];
  return {db, sql, bucket, saved, state, notices, notice: status => notices.push({status, request: saved(), ...state()})};
}

function bindings(f, failure) {
  const bucket = failure === 'missing bucket' ? undefined : {...f.bucket, async delete(keys) {
    if (failure === 'storage fault' && keys.includes(OWNED[1])) throw Error(FAULT);
    await f.bucket.delete(keys);
  }};
  // Force a real transaction rollback after all deletes were attempted.
  const db = failure === 'D1 rollback' ? {...f.db, async batch(statements) {
    return f.db.batch([...statements, {async run() { throw Error(FAULT); }}]);
  }} : f.db;
  return {db, bucket};
}

// Fixture-only design: an opaque receipt exposes status for one minute, not a
// delivery address. Expiring the acknowledgement must not cancel pending work.
// A fresh step resumes from D1 and deletes at most LIMIT objects per attempt.
function reference(f) {
  const receipt = {status: 'pending', owner: 'subject', expires: NOW + TTL};
  f.sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(RECEIPT, JSON.stringify(receipt), AT);
  f.notice('pending');
}
const statusAt = (f, now) => { const row = f.saved(); return row && now < row.expires ? row.status : null; };
async function resume(f, failure, now = NOW + 1) {
  const {db, bucket} = bindings(f, failure);
  const receipt = f.saved();
  if (receipt?.status !== 'pending' || !bucket) return;
  const remaining = f.state().objects;
  try {
    for (const key of remaining.slice(0, LIMIT)) await bucket.delete([key]);
    if (remaining.length > LIMIT) return;
    const owner = receipt.owner;
    await db.batch([
      db.prepare('DELETE FROM advisor_messages WHERE contact_id=?').bind(owner),
      db.prepare('UPDATE advisor_reports SET contact_id=NULL,media_id=NULL WHERE contact_id=?').bind(owner),
      db.prepare('DELETE FROM advisor_media WHERE contact_id=?').bind(owner),
      db.prepare('UPDATE advisor_boats SET owner_contact_id=NULL WHERE owner_contact_id=?').bind(owner),
      db.prepare('DELETE FROM advisor_contacts WHERE id=?').bind(owner),
      db.prepare("DELETE FROM job_state WHERE key IN (?,?) OR (key LIKE 'advisor.link.%' AND json_extract(value,'$.phone_contact_id')=?)")
        .bind(`advisor.flow.${owner}`, `advisor.link.${owner}`, owner),
      db.prepare('UPDATE job_state SET value=? WHERE key=?').bind(JSON.stringify({status: 'complete', expires: receipt.expires}), RECEIPT),
    ]);
  } catch (error) {
    if (error.message !== FAULT) throw error;
    return;
  }
  if (statusAt(f, now) === 'complete') f.notice('complete');
}

async function baseline(f, failure) {
  // Minimal build-time globals; never load a deployed configuration or adapter.
  Object.assign(globalThis, {REGIONS: {}, DEPLOYMENT: {}, SHELLS: {}, BUILD_ID: 'audit-fixture'});
  globalThis.fetch = () => assert.fail('offline audit must not fetch');
  const {consumeAdvisor, ADVISOR_QUEUE_NAME} = await import('../server/advisor/consumer.ts');
  const {t} = await import('../server/advisor/strings.ts');
  const {db, bucket} = bindings(f, failure);
  const message = {body: {message_id: 'request'}, attempts: 1, ack() {}, retry() {}};
  await consumeAdvisor({queue: ADVISOR_QUEUE_NAME, messages: [message]},
    {DB: db, ADVISOR_MEDIA: bucket, TEXT_ADVISOR_ENABLED: 'true'}, {
      now: () => NOW,
      handler: async () => ({intent: 'forget', actions: [{type: 'forget', language: 'en'}]}),
      channel: {async send({text}) {
        f.notice(text === t('en', 'forget_done') ? 'complete' : 'other');
        return {status: 'sent', providerId: null};
      }},
    });
}

const intact = {contact: 1, inbound: 1, media: 1, jobs: OWNED_JOBS};
const clean = {objects: [], contact: 0, inbound: 0, media: 0, jobs: []};
for (const [scenario, remaining] of [
  ['healthy', [OWNED[2]]], ['missing bucket', OWNED], ['storage fault', OWNED.slice(1)], ['D1 rollback', []],
]) {
  test(`${BASELINE ? 'baseline' : 'reference'}: ${scenario}`, async t => {
    const f = fixture(t);
    const before = {objects: OWNED, ...intact};
    if (BASELINE) await baseline(f, scenario);
    else reference(f);
    const pending = {status: 'pending', owner: 'subject', expires: NOW + TTL};
    const accepted = structuredClone(f.notices);
    if (!BASELINE) {
      // On rollback, exhaust the first bounded chunk before failing the final D1 batch.
      if (scenario === 'D1 rollback') await resume(f, 'healthy');
      await resume(f, scenario);
    }
    assert.deepEqual({accepted, notices: f.notices.map(n => n.status), request: f.saved(), state: f.state()}, {
      accepted: [{status: 'pending', request: pending, ...before}], notices: ['pending'], request: pending,
      state: {objects: remaining, ...intact},
    }, 'acknowledge persisted work, not completion; retain ownership and retry metadata until both stores succeed');
    assert.equal(statusAt(f, NOW), 'pending');
    assert.equal(statusAt(f, NOW + TTL), null, 'acknowledgement expires, not the deletion request');
    if (BASELINE) return;
    // A fresh worker needs no inbound delivery or in-memory state from the previous attempt.
    const now = scenario === 'missing bucket' ? NOW + TTL : NOW + 1;
    if (scenario === 'missing bucket') {
      await resume(f, 'healthy', now);
      assert.deepEqual(f.state(), {objects: [OWNED[2]], ...intact}, 'restored binding still uses bounded steps');
    }
    await resume(f, 'healthy', now);
    const completed = {status: 'complete', expires: NOW + TTL};
    assert.deepEqual(f.saved(), completed, 'the receipt no longer retains contact recovery data');
    assert.deepEqual(f.notices.slice(1), now < completed.expires ? [{status: 'complete', request: completed, ...clean}] : []);
    assert.deepEqual(f.state(), clean);
    assert.equal(f.sql.prepare('SELECT count(*) n FROM advisor_messages').get().n, 0);
    assert.equal(statusAt(f, now), now < completed.expires ? 'complete' : null);
    assert.equal(statusAt(f, NOW + TTL), null);
    assert.deepEqual([...f.bucket.store], [OTHER]);
    assert.deepEqual(f.sql.prepare('SELECT key FROM job_state WHERE key<>?').all(RECEIPT).map(r => r.key), ['advisor.link.unrelated']);
    assert.deepEqual(f.sql.prepare('SELECT id,owner_contact_id FROM advisor_boats').all().map(r => ({...r})), [{id: 'boat', owner_contact_id: null}]);
    assert.deepEqual(f.sql.prepare('SELECT id,boat_id,contact_id,media_id FROM advisor_reports').all().map(r => ({...r})),
      [{id: 'report', boat_id: 'boat', contact_id: null, media_id: null}]);
  });
}

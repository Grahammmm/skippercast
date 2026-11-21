// F03-01 / SCA-526. The normal Node suite runs the valid reference control.
// To apply the same contract to the unchanged implementation, opt in with:
//   node tests/test_f03_01_audit.mjs --baseline
// A failed contract assertion in that replay is an audit finding, not a CI gate.
import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {advisorSettings} from '../server/advisor/settings.ts';

// Supply the bundler globals without reading deployment configuration.
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {consumeAdvisor, ADVISOR_QUEUE_NAME} = await import('../server/advisor/consumer.ts');
const {shareAnglerPhoto} = await import('../server/advisor/tools/share_angler_photo.ts');
const {shareKey} = await import('../server/advisor/intake/anglers.ts');

const baseline = process.argv.includes('--baseline');
const at = '2026-10-01T00:00:00Z';
const contactId = 'synthetic-angler';
const mode = baseline ? 'implementation baseline' : 'valid reference';

// Synthetic reference only. In baseline mode both consent values use the
// real tool; no reference write or reply is injected into that replay.
async function referenceNo(db, id, state) {
  if (state === 'posted') return {result: {note: 'This photo was already posted; we cannot promise removal of published copies.'}};
  await db.batch([
    db.prepare("UPDATE advisor_media SET publish_state='private' WHERE id=? AND publish_state='queued'").bind(id),
    db.prepare("UPDATE advisor_reviews SET status='rejected' WHERE kind='media' AND ref_id=? AND reason='angler_photo' AND status='open'").bind(id),
    db.prepare("DELETE FROM job_state WHERE key=? AND json_extract(value,'$.media_id')=?").bind(shareKey(contactId), id),
  ]);
  return {result: {shared: false}};
}

function fixture(t) {
  assert.equal(sqliteUnavailable, null);
  const {db, sql} = advisorDatabase();
  t.after(() => sql.close());
  t.mock.method(globalThis, 'fetch', () => assert.fail('unexpected network request'));
  const env = {DB: db, TEXT_ADVISOR_ENABLED: 'true'};
  sql.prepare("INSERT INTO advisor_contacts(id,channel,last_seen_at,created_at,updated_at) VALUES(?,'web',?,?,?)").run(contactId, at, at, at);
  const add = sql.prepare(`INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,publish_state,created_at)
    VALUES(?,?,'image','image/png',0,'synthetic-only','unused',?,?)`);
  for (const [id, state] of [['a', 'private'], ['b', 'private'], ['c', 'posted']]) add.run(id, contactId, state, at);
  const photoState = id => sql.prepare('SELECT publish_state FROM advisor_media WHERE id=?').get(id)?.publish_state;
  const snapshot = () => ({
    media: ['a', 'b', 'c'].map(photoState),
    open: sql.prepare("SELECT ref_id FROM advisor_reviews WHERE status='open' AND kind='media' ORDER BY ref_id").all().map(r => r.ref_id),
    pendingCredit: sql.prepare("SELECT json_extract(value,'$.media_id') AS media FROM job_state WHERE key=?").get(shareKey(contactId))?.media ?? null,
  });

  let seq = 0;
  async function consent(media_id, value) {
    const id = `synthetic-turn-${++seq}`;
    sql.prepare("INSERT INTO advisor_messages(id,contact_id,direction,channel,status,created_at) VALUES(?,?,'in','web','queued',?)").run(id, contactId, at);
    let reply, acked = false, retried = false;
    const message = {body: {message_id: id}, attempts: 1, ack() { acked = true; }, retry() { retried = true; }};
    await consumeAdvisor({queue: ADVISOR_QUEUE_NAME, messages: [message]}, env, {
      now: () => Date.parse(at), channelFor: () => null,
      handler: async ctx => {
        const outcome = baseline || value
          ? await shareAnglerPhoto.run({media_id, consent: value}, {...ctx, db, language: 'en', settings: advisorSettings(env)})
          : await referenceNo(db, media_id, photoState(media_id));
        reply = outcome.result;
        return {actions: outcome.actions ?? [], intent: 'photo.share'};
      },
    });
    return {acked, retried, reply, state: snapshot()};
  }
  return {sql, consent, snapshot};
}

const queued = {media: ['queued', 'queued', 'posted'], open: ['a', 'b'], pendingCredit: 'a'};
const withdrawn = {media: ['private', 'queued', 'posted'], open: ['b'], pendingCredit: null};
async function queueBoth({consent}) {
  assert.equal((await consent('b', true)).reply?.shared, true);
  const yes = await consent('a', true);
  assert.equal(yes.acked, true);
  assert.equal(yes.reply?.shared, true);
  assert.deepEqual(yes.state, queued, 'real yes queues both photos and gives each an open review');
}

test(`F03-01 ${mode}: yes, no, repeated no; only photo A is withdrawn`, async t => {
  const f = fixture(t);
  await queueBoth(f);
  const no = await f.consent('a', false);
  const again = await f.consent('a', false);
  assert.equal(no.acked && again.acked, true);
  assert.deepEqual(again.state, no.state, 'repeated no is harmless');
  assert.deepEqual(no.state, withdrawn, `withdrawal must match the tool's guidance: ${JSON.stringify(no.reply)}`);
  assert.equal(no.reply?.shared, false);
  assert.equal(again.reply?.shared, false);
});

for (const [table, row] of [['advisor_media', 'id'], ['advisor_reviews', 'ref_id']]) {
  test(`F03-01 ${mode}: a blocked write to ${table} leaves both records and does not acknowledge success`, async t => {
    const f = fixture(t);
    await queueBoth(f);
    // Fail either persistence leg, including an implementation that deletes
    // rather than closes a review. The other leg must not visibly commit.
    for (const op of ['UPDATE', 'DELETE']) f.sql.exec(`CREATE TRIGGER block_${op} BEFORE ${op} ON ${table}
      WHEN OLD.${row}='a' BEGIN SELECT RAISE(ABORT, 'synthetic withdrawal failure'); END`);
    const no = await f.consent('a', false);
    assert.deepEqual({state: no.state, acked: no.acked, retried: no.retried},
      {state: queued, acked: false, retried: true}, 'a failed withdrawal is not reported as complete');
  });
}

test(`F03-01 ${mode}: an already posted photo is not represented as unshared`, async t => {
  const f = fixture(t);
  const before = f.snapshot();
  const no = await f.consent('c', false);
  assert.deepEqual(no.state, before);
  assert.equal(no.acked, true);
  assert.notEqual(no.reply?.shared, false, 'must not indicate an already posted copy is unshared');
  assert.match(no.reply?.note ?? '', /already\s+(?:posted|published|shared)/i);
  assert.doesNotMatch(no.reply.note, /\b(?:will|shall|guarantee to)\s+(?:be\s+)?(?:remove|removed|delete|deleted|take down|taken down)\b/i);
});

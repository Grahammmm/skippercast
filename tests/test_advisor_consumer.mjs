// Text Advisor queue consumer (server/advisor/consumer.ts): ack, retry and
// dead-letter paths with a fake MessageBatch like tests/test_trip_queue.mjs,
// idempotent outbound rows across a retry, the held/dropped switches, the
// hourly apology throttle, the 45 s hard stop (fake timers) and the inline
// runner, against the real migrations in an in-memory SQLite.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {ADVISOR_QUEUES} from '../scripts/wrangler_config.mjs';
import {outboundId} from '../server/advisor/ids.ts';
import {reviewId} from '../server/advisor/contacts.ts';

// server/analytics.ts reaches the Worker config through server/http.ts, which needs the build-time globals.
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {consumeAdvisor, consumeAdvisorDeadLetters, runInline, warmUpHandler, reason, ADVISOR_QUEUE_NAME, ADVISOR_DLQ_NAME, TURN_TIMEOUT_MS,
  WARM_UP_TEXT, STILL_WORKING_TEXT, APOLOGY_TEXT, ERROR_NOTICE_MS} = await import('../server/advisor/consumer.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-03T15:00:00Z');
const ON = {TEXT_ADVISOR_ENABLED: 'true'};

/** A MessageBatch as the Workers runtime hands it to queue(). */
function batchOf(queue, bodies, attempts = 1) {
  const messages = bodies.map((body, i) => ({id: `m${i}`, body, attempts, timestamp: new Date(T0), outcome: null, delay: undefined,
    ack() { this.outcome = 'ack'; }, retry(options) { this.outcome = 'retry'; this.delay = options?.delaySeconds; }}));
  return {queue, messages, ackAll() { for (const m of messages) m.ack(); }, retryAll() { for (const m of messages) m.retry(); }};
}

/** A channel that records every send; `results` is consumed in order, then 'sent'. */
function channel(results = []) {
  const sent = [];
  return {sent, async send(message) {
    sent.push(structuredClone(message));
    const next = results.shift();
    if (next instanceof Error) throw next;
    return next ?? {providerId: `p-${sent.length}`, status: 'sent'};
  }};
}

/** A database with one active contact and one queued inbound message. */
function setup({status = 'queued', contactStatus = 'active', lastNotice = null} = {}) {
  const {sql, db} = advisorDatabase(), at = new Date(T0).toISOString();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,status,last_seen_at,last_error_notice_at,created_at,updated_at) VALUES('c1','h1','ENC-BLOB','imessage',?,?,?,?,?)`).run(contactStatus, at, lastNotice, at, at);
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES('in1','c1','in','imessage','g1','hi',?,?)`).run(status, at);
  return {sql, db};
}
const row = (sql, id) => sql.prepare('SELECT * FROM advisor_messages WHERE id=?').get(id);
const outbound = sql => sql.prepare("SELECT * FROM advisor_messages WHERE direction='out' ORDER BY created_at,id").all();
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const sink = () => { const points = []; return {points, ANALYTICS: {writeDataPoint: p => points.push(structuredClone(p))}}; };

test('queue names match the deploy config and the stub handler warms up', async () => {
  assert.deepEqual(ADVISOR_QUEUES.consumers.map(c => c.queue), [ADVISOR_QUEUE_NAME, ADVISOR_DLQ_NAME]);
  assert.equal(ADVISOR_QUEUES.consumers[0].dead_letter_queue, ADVISOR_DLQ_NAME);
  assert.deepEqual(await warmUpHandler({contact: {status: 'active'}}), {actions: [{type: 'send_text', text: WARM_UP_TEXT}], intent: 'stub'});
  assert.deepEqual(await warmUpHandler({contact: {status: 'stopped'}}), {actions: [], intent: 'stub'}, 'no outbound to a stopped contact');
  assert.equal(TURN_TIMEOUT_MS, 45000);
  assert.equal(reason(Error('send to +18055550100 failed ' + 'x'.repeat(400))).length, 200);
  assert.match(reason(Error('send to +18055550100 failed')), /\[redacted\]/);
});

test('outbound ids are sha256(message_id:index)[:32]', async () => {
  assert.equal(await outboundId('in1', 0), createHash('sha256').update('in1:0').digest('hex').slice(0, 32));
  assert.notEqual(await outboundId('in1', 0), await outboundId('in1', 1));
});

dbTest('a queued message runs the stub: one sent reply, inbound done with intent, message acked', async () => {
  const {sql, db} = setup(), ch = channel(), {points, ANALYTICS} = sink();
  const batch = batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}]);
  const {value: result} = await quiet(() => consumeAdvisor(batch, {...ON, DB: db, ANALYTICS}, {channel: ch, now: () => T0}));
  assert.equal(batch.messages[0].outcome, 'ack');
  assert.deepEqual({done: result.done, sends: result.sends, retried: result.retried}, {done: 1, sends: 1, retried: 0});
  assert.equal(row(sql, 'in1').status, 'done'); assert.equal(row(sql, 'in1').intent, 'stub');
  const [out] = outbound(sql);
  assert.equal(out.id, await outboundId('in1', 0));
  assert.deepEqual({status: out.status, body: out.body, provider_id: out.provider_id, in_reply_to: out.in_reply_to, contact_id: out.contact_id, channel: out.channel},
    {status: 'sent', body: WARM_UP_TEXT, provider_id: 'p-1', in_reply_to: 'in1', contact_id: 'c1', channel: 'imessage'});
  assert.equal(out.sent_at, new Date(T0).toISOString());
  assert.deepEqual(ch.sent, [{id: out.id, to: 'ENC-BLOB', text: WARM_UP_TEXT}], 'the adapter gets the encrypted address; it decrypts');
  const [turn] = points.filter(p => p.indexes[0] === 'advisor_turn');
  assert.deepEqual(turn.blobs, ['advisor_turn', 'stub', 'done']);
  assert.deepEqual(turn.doubles.slice(1), [1, 1, 0]);
  assert.doesNotMatch(JSON.stringify(points), /in1|c1|ENC-BLOB|warming/, 'no ids or bodies in analytics');
});

dbTest('missing, malformed or already-handled messages are acked and dropped without a send', async () => {
  const {sql, db} = setup({status: 'done'}), ch = channel();
  const batch = batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}, {message_id: 'nope'}, {}, {message_id: 'bad id!'}]);
  const {value: result} = await quiet(() => consumeAdvisor(batch, {...ON, DB: db}, {channel: ch}));
  assert.deepEqual(batch.messages.map(m => m.outcome), ['ack', 'ack', 'ack', 'ack']);
  assert.equal(result.invalid, 4); assert.equal(ch.sent.length, 0); assert.equal(outbound(sql).length, 0);
});

dbTest('a handler throw retries with backoff, puts the inbound back to queued with a redacted reason', async () => {
  const {sql, db} = setup(), ch = channel();
  const handler = async () => { throw Error('model said no to +18055550100 ' + 'y'.repeat(300)); };
  for (const [attempts, delay] of [[1, 20], [3, 60], [20, 300]]) {
    const batch = batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}], attempts);
    await quiet(() => consumeAdvisor(batch, {...ON, DB: db}, {channel: ch, handler}));
    assert.equal(batch.messages[0].outcome, 'retry'); assert.equal(batch.messages[0].delay, delay);
    const r = row(sql, 'in1');
    assert.equal(r.status, 'queued'); assert.ok(r.error.length <= 200); assert.match(r.error, /\[redacted\]/); assert.doesNotMatch(r.error, /8055550100/);
  }
  assert.equal(ch.sent.length, 0);
});

dbTest('a retry after a partial apply never resends a sent text; the outbound ids are the same', async () => {
  const {sql, db} = setup();
  const actions = [{type: 'send_text', text: 'one'}, {type: 'review_open', kind: 'conversation', refId: 'in1', reason: 'low_confidence'}, {type: 'send_text', text: 'two'}];
  const handler = async () => ({actions, intent: 'advice.rig'});
  // First delivery: the first text is sent, the second send throws (the provider may or may not have it).
  let calls = 0;
  const flaky = {async send(m) { calls++; if (calls === 2) throw Error('socket hang up'); return {providerId: 'p' + calls, status: 'sent'}; }};
  const first = batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}]);
  await quiet(() => consumeAdvisor(first, {...ON, DB: db}, {channel: flaky, handler}));
  assert.equal(first.messages[0].outcome, 'ack', 'a send that threw is recorded unknown, not retried blindly');
  const ids = [await outboundId('in1', 0), await outboundId('in1', 2)];
  assert.deepEqual(outbound(sql).map(r => [r.id, r.status]).sort(), [[ids[0], 'sent'], [ids[1], 'unknown']].sort());
  // Re-delivery of the same message (e.g. the ack was lost): nothing is sent again.
  sql.prepare("UPDATE advisor_messages SET status='queued' WHERE id='in1'").run();
  const ch = channel(), again = batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}], 2);
  await quiet(() => consumeAdvisor(again, {...ON, DB: db}, {channel: ch, handler}));
  assert.equal(ch.sent.length, 0, 'sent and unknown rows are skipped');
  assert.equal(outbound(sql).length, 2);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_reviews').get().n, 1, 'the review UPSERT does not duplicate');
  assert.equal(sql.prepare('SELECT id FROM advisor_reviews').get().id, await reviewId('conversation', 'in1', 'low_confidence'));
});

dbTest('a failed send is retried on the next delivery; a row left sending by a crash becomes unknown', async () => {
  const {sql, db} = setup();
  const handler = async () => ({actions: [{type: 'send_text', text: 'a'}, {type: 'send_text', text: 'b'}], intent: 'stub'});
  const failing = channel([{providerId: null, status: 'failed', error: 'relay 502'}]);
  await quiet(() => consumeAdvisor(batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}]), {...ON, DB: db}, {channel: failing, handler}));
  const [a, b] = [await outboundId('in1', 0), await outboundId('in1', 1)];
  assert.equal(row(sql, a).status, 'failed'); assert.equal(row(sql, a).error, 'relay 502'); assert.equal(row(sql, a).sent_at, null);
  assert.equal(row(sql, b).status, 'sent');
  sql.prepare("UPDATE advisor_messages SET status='queued' WHERE id='in1'").run();
  sql.prepare("UPDATE advisor_messages SET status='sending' WHERE id=?").run(b);   // simulate a crash mid-send
  const ch = channel();
  await quiet(() => consumeAdvisor(batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}], 2), {...ON, DB: db}, {channel: ch, handler}));
  assert.deepEqual(ch.sent.map(m => m.text), ['a'], 'only the failed one is sent again');
  assert.equal(row(sql, a).status, 'sent'); assert.equal(row(sql, b).status, 'unknown');
});

dbTest('contact_update writes only whitelisted fields; log goes through advisorLog', async () => {
  const {sql, db} = setup();
  const handler = async () => ({intent: 'intake.name', actions: [
    {type: 'contact_update', fields: {display_name: ' Capt.\u0007 Ray ', language: 'es', role: 'skipper', status: 'blocked', phone_hash: 'x', messages_today: 99}},
    {type: 'contact_update', fields: {language: 'fr', role: 'god'}},
    {type: 'log', event: 'advisor_test_event', fields: {to: '+18055550100'}},
  ]});
  const {lines} = await quiet(() => consumeAdvisor(batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}]), {...ON, DB: db}, {channel: channel(), handler, now: () => T0 + 1000}));
  const c = sql.prepare('SELECT * FROM advisor_contacts WHERE id=?').get('c1');
  assert.deepEqual({display_name: c.display_name, language: c.language, role: c.role, status: c.status, phone_hash: c.phone_hash, messages_today: c.messages_today},
    {display_name: 'Capt. Ray', language: 'es', role: 'skipper', status: 'active', phone_hash: 'h1', messages_today: 0});
  assert.equal(c.updated_at, new Date(T0 + 1000).toISOString());
  const logged = lines.map(l => { try { return JSON.parse(l); } catch { return {}; } }).find(l => l.event === 'advisor_test_event');
  assert.equal(logged.to, '[redacted]');
  assert.ok(lines.some(l => l.includes('advisor_contact_field_rejected')));
});

dbTest('ADVISOR_REPLIES_ENABLED=false holds: acked, no handler call, nothing sent', async () => {
  const {sql, db} = setup(), ch = channel();
  let called = false;
  const batch = batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}]);
  const {value: result} = await quiet(() => consumeAdvisor(batch, {...ON, ADVISOR_REPLIES_ENABLED: 'false', DB: db}, {channel: ch, handler: async () => { called = true; return {actions: [], intent: 'x'}; }}));
  assert.equal(batch.messages[0].outcome, 'ack'); assert.equal(called, false); assert.equal(ch.sent.length, 0);
  assert.equal(row(sql, 'in1').status, 'held'); assert.equal(result.held, 1);
});

dbTest('TEXT_ADVISOR_ENABLED off: every message acked, the row dropped, no handler call', async () => {
  const {sql, db} = setup(), ch = channel();
  let called = false;
  const batch = batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}, {message_id: 'missing'}]);
  const {value: result} = await quiet(() => consumeAdvisor(batch, {DB: db}, {channel: ch, handler: async () => { called = true; }}));
  assert.deepEqual(batch.messages.map(m => m.outcome), ['ack', 'ack']); assert.equal(called, false);
  assert.equal(row(sql, 'in1').status, 'dropped'); assert.equal(result.dropped, 2); assert.equal(ch.sent.length, 0);
});

dbTest('dead letters: acked, inbound failed, one apology per contact per hour', async () => {
  const {sql, db} = setup();
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES('in2','c1','in','imessage','g2','again','queued',?)`).run(new Date(T0).toISOString());
  const ch = channel(), env = {...ON, DB: db};
  const batch = batchOf(ADVISOR_DLQ_NAME, [{message_id: 'in1'}, {message_id: 'in2'}, {message_id: 'gone'}]);
  const {value: dead} = await quiet(() => consumeAdvisorDeadLetters(batch, env, {channel: ch, now: () => T0}));
  assert.deepEqual(batch.messages.map(m => m.outcome), ['ack', 'ack', 'ack']);
  assert.deepEqual(dead, {dead: 3, failed: 2, apologies: 1});
  assert.equal(row(sql, 'in1').status, 'failed'); assert.equal(row(sql, 'in2').status, 'failed');
  assert.deepEqual(ch.sent.map(m => m.text), [APOLOGY_TEXT]);
  assert.equal(ch.sent[0].id, await outboundId('in1', 'error'));
  assert.equal(sql.prepare('SELECT last_error_notice_at v FROM advisor_contacts').get().v, new Date(T0).toISOString());
  // Within the hour: no second apology. After it: one more.
  for (const [id, at, expected] of [['in3', T0 + ERROR_NOTICE_MS - 1000, 1], ['in4', T0 + ERROR_NOTICE_MS, 2]]) {
    sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES(?,'c1','in','imessage',?,'x','processing',?)`).run(id, id, new Date(at).toISOString());
    await quiet(() => consumeAdvisorDeadLetters(batchOf(ADVISOR_DLQ_NAME, [{message_id: id}]), env, {channel: ch, now: () => at}));
    assert.equal(ch.sent.length, expected, `${id}: apologies so far`);
  }
});

dbTest('dead letters send no apology to a stopped contact or when replies are off', async () => {
  for (const [opts, env] of [[{contactStatus: 'stopped'}, ON], [{}, {...ON, ADVISOR_REPLIES_ENABLED: 'false'}]]) {
    const {sql, db} = setup(opts), ch = channel();
    await quiet(() => consumeAdvisorDeadLetters(batchOf(ADVISOR_DLQ_NAME, [{message_id: 'in1'}]), {...env, DB: db}, {channel: ch}));
    assert.equal(row(sql, 'in1').status, 'failed'); assert.equal(ch.sent.length, 0);
  }
});

dbTest('the 45 s hard stop: the signal aborts, "Still working" is sent once, one retry after 20 s, then failure', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const {sql, db} = setup(), ch = channel(), env = {...ON, DB: db};
  let signal, started;
  const handler = input => { signal = input.signal; started(); return new Promise(() => {}); };
  const run = async attempts => {
    const batch = batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}], attempts);
    const ready = new Promise(resolve => { started = resolve; });
    const pending = quiet(() => consumeAdvisor(batch, env, {channel: ch, handler, now: () => T0}));
    await ready;
    t.mock.timers.tick(TURN_TIMEOUT_MS - 1);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(signal.aborted, false, 'not before 45 s');
    t.mock.timers.tick(1);
    await pending;
    assert.equal(signal.aborted, true);
    return batch.messages[0];
  };
  const first = await run(1);
  assert.equal(first.outcome, 'retry'); assert.equal(first.delay, 20);
  assert.equal(row(sql, 'in1').status, 'queued'); assert.equal(row(sql, 'in1').error, 'timeout');
  assert.deepEqual(ch.sent.map(m => m.text), [STILL_WORKING_TEXT]);
  const second = await run(2);
  assert.equal(second.outcome, 'ack', 'the one retry also timed out: give up');
  assert.equal(row(sql, 'in1').status, 'failed');
  assert.deepEqual(ch.sent.map(m => m.text), [STILL_WORKING_TEXT, APOLOGY_TEXT], '"Still working" is not repeated');
});

dbTest('runInline processes one message without a queue; a failure goes straight to the apology', async () => {
  const {sql, db} = setup(), ch = channel();
  const result = (await quiet(() => runInline({...ON, DB: db}, 'in1', {channel: ch}))).value;
  assert.equal(result.done, 1); assert.equal(row(sql, 'in1').status, 'done'); assert.deepEqual(ch.sent.map(m => m.text), [WARM_UP_TEXT]);
  const other = setup(), ch2 = channel();
  const failed = (await quiet(() => runInline({...ON, DB: other.db}, 'in1', {channel: ch2, handler: async () => { throw Error('boom'); }}))).value;
  assert.equal(failed.failed, 1); assert.equal(row(other.sql, 'in1').status, 'failed'); assert.deepEqual(ch2.sent.map(m => m.text), [APOLOGY_TEXT]);
});

dbTest('without a channel (before TA-C1) a send is recorded failed, the turn still completes', async () => {
  const {sql, db} = setup();
  await quiet(() => consumeAdvisor(batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}]), {...ON, DB: db}));
  const [out] = outbound(sql);
  assert.equal(out.status, 'failed'); assert.equal(out.error, 'no-channel'); assert.equal(row(sql, 'in1').status, 'done');
});

dbTest('the Worker queue() routes advisor batches and records a queue_batch point', async () => {
  const {default: worker} = await import('../server/index.ts');
  const {sql, db} = setup(), {points, ANALYTICS} = sink();
  const batch = batchOf(ADVISOR_QUEUE_NAME, [{message_id: 'in1'}]);
  await quiet(() => worker.queue(batch, {...ON, DB: db, ANALYTICS}));
  assert.equal(batch.messages[0].outcome, 'ack'); assert.equal(row(sql, 'in1').status, 'done');
  const dead = batchOf(ADVISOR_DLQ_NAME, [{message_id: 'in1'}]);
  await quiet(() => worker.queue(dead, {...ON, DB: db, ANALYTICS}));
  assert.equal(dead.messages[0].outcome, 'ack');
  const batches = points.filter(p => p.indexes[0] === 'queue_batch');
  assert.deepEqual(batches.map(p => p.blobs), [['queue_batch', ADVISOR_QUEUE_NAME, 'ok'], ['queue_batch', ADVISOR_DLQ_NAME, 'dead']]);
  assert.equal(batches[0].doubles[0], 1); assert.equal(batches[0].doubles[4], 1, 'checked = messages done');
});

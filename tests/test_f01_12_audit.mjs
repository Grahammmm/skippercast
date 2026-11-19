import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase} from './_advisor_d1.mjs';
import {createTwilio} from '../server/advisor/channels/twilio.ts';
import {deriveKeys, encryptPhone} from '../server/advisor/contacts.ts';

// Supply bundler globals without loading deployment configuration.
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {consumeAdvisor, ADVISOR_QUEUE_NAME} = await import('../server/advisor/consumer.ts');

const at = '2026-10-03T15:00:00.000Z';
const sid = 'SM' + 'b'.repeat(32);
const envValues = {
  TEXT_ADVISOR_ENABLED: 'true',
  ADVISOR_PHONE_KEY: Buffer.alloc(32, 7).toString('base64'),
  TWILIO_ACCOUNT_SID: 'AC' + 'a'.repeat(32),
  TWILIO_AUTH_TOKEN: 'synthetic-only',
  TWILIO_FROM: '+15555550100',
};

for (const loseResponse of [true, false]) {
  // A transport retry creates a second SMS, and recording 'failed' would let
  // the consumer retry the same outbound row on queue replay.
  test(`F01-12: ${loseResponse ? 'accepted create with lost response stays unknown on replay' : 'acknowledged create is recorded sent'}`, async t => {
    const {sql, db} = advisorDatabase();
    t.after(() => sql.close());
    const noNetwork = t.mock.method(globalThis, 'fetch', () => assert.fail('unexpected real fetch'));
    const phone = await encryptPhone(await deriveKeys(envValues.ADVISOR_PHONE_KEY), '+15555550101');
    sql.prepare("INSERT INTO advisor_contacts(id,phone_enc,channel,status,last_seen_at,created_at,updated_at) VALUES('c1',?,'sms','active',?,?,?)")
      .run(phone, at, at, at);
    sql.prepare("INSERT INTO advisor_messages(id,contact_id,direction,channel,status,created_at) VALUES('in1','c1','in','sms','queued',?)").run(at);

    const accepted = [];
    const channel = createTwilio({fetcher: async (url, {method, body}) => {
      assert.equal(new URL(url).pathname, `/2010-04-01/Accounts/${envValues.TWILIO_ACCOUNT_SID}/Messages.json`);
      assert.equal(method, 'POST');
      accepted.push(new URLSearchParams(body).get('Body')); // provider commits before responding
      if (loseResponse) throw new TypeError('connection lost after acceptance');
      return Response.json({sid, status: 'queued'}, {status: 201});
    }});
    const env = {...envValues, DB: db};
    const deps = {channel, now: () => Date.parse(at), handler: async () => ({intent: 'stub', actions: [{type: 'send_text', text: 'fixture reply'}]})};
    async function deliver(attempts) {
      const outcomes = [];
      const message = {body: {message_id: 'in1'}, attempts, ack() { outcomes.push('ack'); }, retry() { outcomes.push('retry'); }};
      const result = await consumeAdvisor({queue: ADVISOR_QUEUE_NAME, messages: [message]}, env, deps);
      assert.deepEqual(outcomes, ['ack']);
      return result.sends;
    }
    const stored = () => sql.prepare("SELECT status, provider_id, sent_at, error FROM advisor_messages WHERE direction='out'").all().map(row => ({...row}));
    const sends = await deliver(1);
    assert.deepEqual({accepted, sends, rows: stored()}, {
      accepted: ['fixture reply'], sends: loseResponse ? 0 : 1,
      rows: [loseResponse
        ? {status: 'unknown', provider_id: null, sent_at: null, error: 'network'}
        : {status: 'sent', provider_id: sid, sent_at: at, error: null}],
    });
    if (loseResponse) {
      // Force the action to replay, not just the consumer's already-done shortcut.
      sql.exec("UPDATE advisor_messages SET status='queued' WHERE id='in1'");
      assert.equal(await deliver(2), 0);
      assert.deepEqual(accepted, ['fixture reply']);
      assert.deepEqual(stored(), [{status: 'unknown', provider_id: null, sent_at: null, error: 'network'}]);
    }
    assert.equal(noNetwork.mock.callCount(), 0);
  });
}

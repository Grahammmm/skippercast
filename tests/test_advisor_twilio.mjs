// Text Advisor Twilio channel (server/advisor/channels/twilio.ts, TA-C2):
// X-Twilio-Signature vectors computed here with node:crypto from a known token
// and URL (independent of the adapter's WebCrypto code), form parsing with
// media, STOP and HELP reaching the engine as text, the inbound route's TwiML
// reply, send (body shape, MediaUrl, StatusCallback, 21610), the status
// callback, media fetch and health, and relay-check --twilio. Offline: a fake
// fetcher plays Twilio; an in-memory SQLite has the real migrations.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import {readFileSync, readdirSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const {createTwilio, signedData, twilioSignature, verifySignature, publicUrl, inboundFromParams, isTwilioMediaUrl, TWIML_EMPTY, MAX_MEDIA_BYTES, OPTED_OUT} = await import('../server/advisor/channels/twilio.ts');
const {ADAPTERS, channelFor, adapterForMedia, splitForChannel} = await import('../server/advisor/channels/index.ts');
const {deriveKeys, encryptPhone, phoneHash} = await import('../server/advisor/contacts.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const FIXTURES = new URL('./fixtures/advisor/twilio/', import.meta.url);
// Fixtures carry Twilio's documented placeholder account SID (a realistic-looking one trips
// GitHub secret scanning); it is swapped for the test account built here.
const SID_PLACEHOLDER = 'AC' + 'X'.repeat(32);
const fixture = name => JSON.parse(readFileSync(new URL(name, FIXTURES), 'utf8').replaceAll(SID_PLACEHOLDER, SID));
const KEY = Buffer.alloc(32, 7).toString('base64');
const TOKEN = 'tok_' + 'b'.repeat(40);
const SID = 'AC' + '0123456789abcdef'.repeat(2);
const AUTH = 'twilio-auth-token-0123456789abcdef';
const ON = {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_PHONE_KEY: KEY, ADVISOR_WEBHOOK_TOKEN: TOKEN, ADVISOR_NUMBER: '+15555550100'};
const TW = {TWILIO_ACCOUNT_SID: SID, TWILIO_AUTH_TOKEN: AUTH, TWILIO_FROM: '+15555550100'};
const BASIC = 'Basic ' + Buffer.from(`${SID}:${AUTH}`).toString('base64');
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

/** The reference signature, the way Twilio's docs describe it: base64(HMAC-SHA1(token, url + sorted key+value)). */
function reference(token, url, params) {
  const data = url + Object.keys(params).sort().map(k => k + params[k]).join('');
  return createHmac('sha1', token).update(data, 'utf8').digest('base64');
}
const inboundPath = (token = TOKEN) => `/api/advisor/inbound/twilio/${token}`;
const statusPath = (token = TOKEN) => `/api/advisor/inbound/twilio-status/${token}`;

/** A signed Twilio POST. `signFor` is the URL the signature covers (default: the public URL for `path`). */
function twilioRequest(path, params, {host = 'skippercast.com', signFor, token = AUTH, signature, order} = {}) {
  const sig = signature ?? reference(token, signFor ?? `https://skippercast.com${path}`, params);
  const keys = order ?? Object.keys(params);
  const body = keys.map(k => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`).join('&');
  return new Request(`https://${host}${path}`, {method: 'POST', body,
    headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-Twilio-Signature': sig, 'cf-connecting-ip': '203.0.113.9'}});
}

/** A fake Twilio: answers by URL path from `routes` (path suffix -> {status, body} | Response | function | Error). Records calls. */
function fakeTwilio(routes = {}) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const u = new URL(url);
    calls.push({url: u, method: init.method ?? 'GET', headers: init.headers ?? {}, body: init.body, redirect: init.redirect, signal: init.signal});
    const key = Object.keys(routes).find(k => u.pathname.endsWith(k) || u.href === k);
    let answer = key ? routes[key] : undefined;
    if (typeof answer === 'function') answer = await answer(u, init, calls.length);
    if (answer instanceof Error) throw answer;
    if (answer instanceof Response) return answer;
    if (answer === undefined) return new Response('{"code":20404,"status":404}', {status: 404});
    return new Response(JSON.stringify(answer.body), {status: answer.status ?? 200, headers: {'Content-Type': 'application/json'}});
  };
  return {calls, fetch};
}

// ---- fixtures -------------------------------------------------------------------

test('every fixture says where its shape comes from and carries only fictional numbers', () => {
  const names = readdirSync(FIXTURES).filter(f => f.endsWith('.json'));
  for (const required of ['inbound-text', 'inbound-mms', 'inbound-stop', 'inbound-help', 'status-delivered', 'status-undelivered', 'send-response', 'send-error-21610', 'account'])
    assert.ok(names.includes(`${required}.json`), required);
  for (const name of names) {
    const f = fixture(name);
    assert.ok(typeof f._source === 'string' && f._source.length > 20, name);
    assert.ok('params' in f || 'response' in f, name);
    for (const m of JSON.stringify(f).matchAll(/\+1\d{10}/g)) assert.match(m[0], /^\+1555/, `${name}: ${m[0]}`);
  }
});

// ---- signature ------------------------------------------------------------------

test('signature: the adapter matches the reference HMAC-SHA1 and verifies it', async () => {
  const url = 'https://skippercast.com/api/advisor/inbound/twilio/x?a=1';
  const params = fixture('inbound-text.json').params;
  const expected = reference(AUTH, url, params);
  assert.equal(await twilioSignature(AUTH, url, params), expected);
  assert.equal(signedData('https://a.test/p', {b: '2', a: '1', B: '0'}), 'https://a.test/pB0a1b2', 'keys sorted by code unit, key then value');
  const form = new URLSearchParams(params);
  assert.equal(await verifySignature(AUTH, url, form, expected), true);
  assert.equal(await verifySignature('another-token', url, form, expected), false, 'wrong token');
  assert.equal(await verifySignature(AUTH, url.replace('skippercast.com', 'evil.example'), form, expected), false, 'wrong host');
  assert.equal(await verifySignature(AUTH, url, new URLSearchParams({...params, Body: 'tampered'}), expected), false, 'altered body');
  assert.equal(await verifySignature(AUTH, url, form, null), false);
  assert.equal(await verifySignature(AUTH, url, form, 'not base64!'), false);
  assert.equal(await verifySignature('', url, form, expected), false, 'no token never verifies');
  // Reordered parameters: the body order does not matter, the signed order is sorted.
  const reversed = new URLSearchParams(Object.entries(params).reverse());
  assert.equal(await verifySignature(AUTH, url, reversed, expected), true, 'reordered params');
});

test('publicUrl comes from ADVISOR_PUBLIC_BASE + path + query, never the Host header', () => {
  const request = new Request('https://worker.example.workers.dev/api/advisor/inbound/twilio/t?x=1', {headers: {Host: 'evil.example'}});
  assert.equal(publicUrl(request, {}), 'https://skippercast.com/api/advisor/inbound/twilio/t?x=1');
  assert.equal(publicUrl(request, {ADVISOR_PUBLIC_BASE: 'https://staging.example.test/'}), 'https://staging.example.test/api/advisor/inbound/twilio/t?x=1');
});

test('normalize: 401 for a wrong token, a signature for another host or a different account; accepted on any Host when signed for the public URL', async () => {
  const tw = createTwilio(), env = {...ON, ...TW}, params = fixture('inbound-text.json').params;
  const ok = await tw.normalize(twilioRequest(inboundPath(), params, {host: 'skippercast.example.workers.dev'}), env);
  assert.ok(Array.isArray(ok), 'the Host header is ignored: the signature covers the public URL');
  assert.equal(await tw.normalize(twilioRequest(inboundPath(), params, {token: 'wrong-token'}), env), 'unauthorized');
  assert.equal(await tw.normalize(twilioRequest(inboundPath(), params, {host: 'evil.example', signFor: `https://evil.example${inboundPath()}`}), env), 'unauthorized', 'signed for the request host');
  assert.equal(await tw.normalize(twilioRequest(inboundPath(), params, {order: Object.keys(params).reverse()}), env).then(r => Array.isArray(r)), true, 'reordered body');
  assert.equal(await tw.normalize(twilioRequest(inboundPath(), {...params, AccountSid: 'AC' + 'f'.repeat(32)}), env), 'unauthorized', 'another account');
  assert.equal(await tw.normalize(twilioRequest(inboundPath(), params), {...ON}), 'unauthorized', 'not configured');
  const big = new Request(`https://skippercast.com${inboundPath()}`, {method: 'POST', body: 'Body=' + 'x'.repeat(70000)});
  await assert.rejects(tw.normalize(big, env), /body too large/);
});

// ---- form parsing -----------------------------------------------------------------

test('form parsing: a text, an MMS with NumMedia=2, STOP and HELP as plain text', async () => {
  const env = {...ON, ...TW};
  for (const name of ['inbound-text.json', 'inbound-mms.json', 'inbound-stop.json', 'inbound-help.json']) {
    const f = fixture(name), result = inboundFromParams(new URLSearchParams(f.params), env);
    assert.ok(Array.isArray(result), name);
    const [m] = result;
    assert.deepEqual({channel: m.channel, providerId: m.providerId, from: m.from, to: m.to, text: m.text, isGroup: m.isGroup, media: m.media.length},
      {channel: 'sms', providerId: f.params.MessageSid, from: f._expect.from, to: '+15555550100', text: f._expect.text, isGroup: false, media: f._expect.media}, name);
    assert.ok(!('raw' in m));
  }
  const [mms] = inboundFromParams(new URLSearchParams(fixture('inbound-mms.json').params), env);
  assert.deepEqual(mms.media.map(m => [m.providerRef, m.mime]), [[fixture('inbound-mms.json').params.MediaUrl0, 'image/jpeg'], [fixture('inbound-mms.json').params.MediaUrl1, 'image/png']]);
  const base = fixture('inbound-mms.json').params;
  const {value: hostile} = await quiet(() => inboundFromParams(new URLSearchParams({...base, MediaUrl1: 'https://evil.example/x.jpg'}), env));
  assert.equal(hostile[0].media.length, 1, 'a media URL off api.twilio.com is never fetched');
  const {value: noBody, lines} = await quiet(() => inboundFromParams(new URLSearchParams({...base, Body: '', NumMedia: '0'}), env));
  assert.equal(noBody, 'ignore'); assert.ok(lines.some(l => l.includes('advisor_twilio_dropped') && l.includes('empty')));
  assert.equal((await quiet(() => inboundFromParams(new URLSearchParams({...base, From: '+447700900123'}), env))).value, 'ignore', 'non-NANP');
  assert.equal((await quiet(() => inboundFromParams(new URLSearchParams(fixture('status-delivered.json').params), env))).value, 'ignore', 'a status callback is not an inbound');
  assert.equal((await quiet(() => inboundFromParams(new URLSearchParams({...base, MessageSid: 'bogus', SmsMessageSid: 'bogus'}), env))).value, 'ignore');
});

// ---- inbound route ----------------------------------------------------------------

const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
function queue() { const sent = []; return {sent, async send(body) { sent.push(body); }}; }

dbTest('inbound route: token, signature, TwiML reply; STOP and HELP stored as text for the engine; duplicates ignored', async () => {
  const {sql, db} = advisorDatabase(), q = queue(), env = {ASSETS, ...ON, ...TW, DB: db, ADVISOR_QUEUE: q};
  const {value: wrong, lines} = await quiet(() => worker.fetch(twilioRequest(inboundPath('wrong'), fixture('inbound-text.json').params, {signFor: `https://skippercast.com${inboundPath('wrong')}`}), env));
  assert.equal(wrong.status, 401); assert.ok(!lines.join('\n').includes(TOKEN));
  const {value: unsigned} = await quiet(() => worker.fetch(twilioRequest(inboundPath(), fixture('inbound-text.json').params, {token: 'wrong-token'}), env));
  assert.equal(unsigned.status, 401); assert.equal((await unsigned.json()).error, 'Unauthorized');
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_messages').get().n, 0);
  for (const name of ['inbound-text.json', 'inbound-stop.json', 'inbound-help.json', 'inbound-mms.json']) {
    const {value: response} = await quiet(() => worker.fetch(twilioRequest(inboundPath(), fixture(name).params), env));
    assert.equal(response.status, 200, name);
    assert.match(response.headers.get('content-type'), /^text\/xml/);
    assert.equal(await response.text(), TWIML_EMPTY);
  }
  const rows = sql.prepare("SELECT * FROM advisor_messages WHERE direction='in' ORDER BY created_at, rowid").all();
  assert.deepEqual(rows.map(r => [r.channel, r.body, r.status]), [['sms', fixture('inbound-text.json')._expect.text, 'queued'], ['sms', 'STOP', 'queued'], ['sms', 'HELP', 'queued'], ['sms', 'Count board from today', 'queued']]);
  assert.deepEqual(rows.map(r => r.provider_id), ['inbound-text.json', 'inbound-stop.json', 'inbound-help.json', 'inbound-mms.json'].map(n => fixture(n).params.MessageSid));
  assert.equal(q.sent.length, 4);
  const media = sql.prepare('SELECT * FROM advisor_media ORDER BY provider_ref').all();
  assert.deepEqual(media.map(m => [m.provider_ref, m.mime, m.r2_key, m.publish_state]).sort(),
    [[fixture('inbound-mms.json').params.MediaUrl0, 'image/jpeg', '', 'private'], [fixture('inbound-mms.json').params.MediaUrl1, 'image/png', '', 'private']].sort());
  const contact = sql.prepare('SELECT * FROM advisor_contacts').get();
  assert.equal(contact.phone_hash, await phoneHash(await deriveKeys(KEY), '+15555550101')); assert.equal(contact.channel, 'sms');
  // Twilio retries a webhook it thinks failed: the same MessageSid changes nothing.
  const {value: again} = await quiet(() => worker.fetch(twilioRequest(inboundPath(), fixture('inbound-text.json').params), env));
  assert.equal(again.status, 200); assert.equal(await again.text(), TWIML_EMPTY);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_messages').get().n, 4); assert.equal(q.sent.length, 4);
  assert.equal((await worker.fetch(twilioRequest(inboundPath(), fixture('inbound-text.json').params), {ASSETS, DB: db})).status, 404, 'gated like every advisor path');
});

dbTest('inbound route: rate limited by PUBLIC_LIMITER; 64 KB cap is a 400; no storage is a 503', async () => {
  const {db} = advisorDatabase(), keys = [];
  const limiter = {async limit({key}) { keys.push(key); return {success: false}; }};
  const limited = await worker.fetch(twilioRequest(inboundPath(), fixture('inbound-text.json').params), {ASSETS, ...ON, ...TW, DB: db, PUBLIC_LIMITER: limiter});
  assert.equal(limited.status, 429); assert.deepEqual(keys, ['advisor-inbound:203.0.113.9']);
  const big = new Request(`https://skippercast.com${inboundPath()}`, {method: 'POST', body: 'Body=' + 'x'.repeat(70000), headers: {'X-Twilio-Signature': 'x'}});
  const {value: tooBig, lines} = await quiet(() => worker.fetch(big, {ASSETS, ...ON, ...TW, DB: db}));
  assert.equal(tooBig.status, 400);
  const {value: broken} = await quiet(() => worker.fetch(twilioRequest(inboundPath(), fixture('inbound-text.json').params), {ASSETS, ...ON, ...TW}));
  assert.equal(broken.status, 503);
  assert.ok(!lines.join('\n').includes(TOKEN));
});

// ---- send -------------------------------------------------------------------------

async function phoneEnc(number = '+15555550101') { return encryptPhone(await deriveKeys(KEY), number); }

test('send: To decrypted inside send, From, Body, StatusCallback, Basic auth, providerId = sid', async () => {
  const t = fakeTwilio({'/Messages.json': {status: 201, body: fixture('send-response.json').response}});
  const tw = createTwilio({fetcher: t.fetch});
  const result = await tw.send({id: 'o'.repeat(32), to: await phoneEnc(), text: 'Rockfish are biting.'}, {...ON, ...TW});
  assert.deepEqual(result, {providerId: fixture('send-response.json').response.sid, status: 'sent'});
  const [call] = t.calls;
  assert.equal(call.url.href, `https://api.twilio.com/2010-04-01/Accounts/${SID}/Messages.json`);
  assert.equal(call.method, 'POST'); assert.equal(call.headers.Authorization, BASIC);
  assert.equal(call.headers['Content-Type'], 'application/x-www-form-urlencoded');
  const form = new URLSearchParams(call.body);
  assert.deepEqual([...form.keys()].sort(), ['Body', 'From', 'StatusCallback', 'To']);
  assert.equal(form.get('To'), '+15555550101'); assert.equal(form.get('From'), '+15555550100'); assert.equal(form.get('Body'), 'Rockfish are biting.');
  assert.equal(form.get('StatusCallback'), `https://skippercast.com/api/advisor/inbound/twilio-status/${TOKEN}`);
  assert.ok(call.signal instanceof AbortSignal, '15 s timeout');
});

dbTest('send: MediaUrl per media key from its advisor_media row (public route), at most 10; private media is refused', async () => {
  const {sql, db} = advisorDatabase(), at = '2026-10-03T15:00:00.000Z';
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,channel,last_seen_at,created_at,updated_at) VALUES('c1','h','sms',?,?,?)`).run(at, at, at);
  const media = (id, key, state) => sql.prepare(`INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,publish_state,created_at) VALUES(?,'c1','image','image/jpeg',10,?,'s',?,?)`).run(id, key, state, at);
  media('m1', 'advisor/media/c1/m1.jpg', 'approved'); media('m2', 'advisor/media/c1/m2.jpg', 'posted'); media('m3', 'advisor/media/c1/m3.jpg', 'private');
  const t = fakeTwilio({'/Messages.json': {status: 201, body: fixture('send-response.json').response}});
  const tw = createTwilio({fetcher: t.fetch}), env = {...ON, ...TW, DB: db, ADVISOR_PUBLIC_BASE: 'https://skippercast.com'};
  const sent = await tw.send({id: 'x', to: await phoneEnc(), mediaKeys: ['advisor/derived/m1/public.jpg', 'advisor/media/c1/m2.jpg']}, env);
  assert.equal(sent.status, 'sent');
  const form = new URLSearchParams(t.calls[0].body);
  assert.deepEqual(form.getAll('MediaUrl'), ['https://skippercast.com/media/m1.jpg', 'https://skippercast.com/media/m2.jpg']);
  assert.equal(form.has('Body'), false, 'media only: no Body');
  assert.deepEqual(await tw.send({id: 'x', to: await phoneEnc(), text: 'hi', mediaKeys: ['advisor/media/c1/m3.jpg']}, env), {providerId: null, status: 'failed', error: 'media-not-public'});
  assert.deepEqual(await tw.send({id: 'x', to: await phoneEnc(), mediaKeys: ['advisor/media/c1/none.jpg']}, env), {providerId: null, status: 'failed', error: 'media-missing'});
  assert.equal((await tw.send({id: 'x', to: await phoneEnc(), mediaKeys: Array(11).fill('advisor/media/c1/m1.jpg')}, env)).error, 'too-many-media');
  assert.equal(t.calls.length, 1, 'nothing sent for a refused media set');
});

dbTest('send: 21610 stops the contact and fails with opted-out; other 4xx fail without retry; network errors retry once; timeout is unknown', async () => {
  const {sql, db} = advisorDatabase(), at = '2026-10-03T15:00:00.000Z';
  const hash = await phoneHash(await deriveKeys(KEY), '+15555550101');
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,channel,status,last_seen_at,created_at,updated_at) VALUES('c1',?,'sms','active',?,?,?)`).run(hash, at, at, at);
  const env = {...ON, ...TW, DB: db}, to = await phoneEnc();
  const optOut = fakeTwilio({'/Messages.json': {status: 400, body: fixture('send-error-21610.json').response}});
  const {value: result, lines} = await quiet(() => createTwilio({fetcher: optOut.fetch}).send({id: 'x', to, text: 'hi'}, env));
  assert.deepEqual(result, {providerId: null, status: 'failed', error: 'opted-out'});
  assert.equal(sql.prepare("SELECT status FROM advisor_contacts WHERE id='c1'").get().status, 'stopped');
  assert.equal(optOut.calls.length, 1, 'no retry on a 4xx');
  assert.ok(lines.some(l => l.includes('advisor_twilio_opted_out')) && !lines.join('\n').includes('5555550101'));
  assert.equal(OPTED_OUT, 21610);
  const bad = fakeTwilio({'/Messages.json': {status: 400, body: {code: 21211, message: 'Invalid To', status: 400}}});
  assert.deepEqual(await createTwilio({fetcher: bad.fetch}).send({id: 'x', to, text: 'hi'}, env), {providerId: null, status: 'failed', error: 'twilio-21211'});
  assert.equal(bad.calls.length, 1);
  const flaky = fakeTwilio({'/Messages.json': (_u, _i, n) => n === 1 ? new TypeError('fetch failed') : {status: 201, body: fixture('send-response.json').response}});
  assert.equal((await createTwilio({fetcher: flaky.fetch}).send({id: 'x', to, text: 'hi'}, env)).status, 'sent');
  assert.equal(flaky.calls.length, 2, 'one retry on a network error');
  const slow = fakeTwilio({'/Messages.json': () => Object.assign(new Error('timed out'), {name: 'TimeoutError'})});
  assert.deepEqual(await createTwilio({fetcher: slow.fetch}).send({id: 'x', to, text: 'hi'}, env), {providerId: null, status: 'unknown', error: 'timeout'});
  assert.equal(slow.calls.length, 1, 'never retried after a timeout');
  const down = fakeTwilio({'/Messages.json': {status: 503, body: {code: 20500, status: 503}}});
  assert.equal((await createTwilio({fetcher: down.fetch}).send({id: 'x', to, text: 'hi'}, env)).status, 'unknown', 'a 5xx may have been accepted');
  assert.equal(down.calls.length, 1);
});

test('send: not configured, no phone key, bad address and empty all fail before any call', async () => {
  const t = fakeTwilio(), tw = createTwilio({fetcher: t.fetch}), to = await phoneEnc();
  assert.equal((await tw.send({id: 'x', to, text: 'hi'}, {...ON})).error, 'not-configured');
  assert.equal((await tw.send({id: 'x', to, text: 'hi'}, {...ON, ...TW, TWILIO_FROM: ''})).error, 'not-configured', 'TWILIO_FROM stays unset until a port');
  assert.equal((await tw.send({id: 'x', to, text: 'hi'}, {...TW})).error, 'no-phone-key');
  assert.equal((await tw.send({id: 'x', to: 'garbage', text: 'hi'}, {...ON, ...TW})).error, 'bad-address');
  assert.equal((await tw.send({id: 'x', to, text: '  '}, {...ON, ...TW})).error, 'empty');
  assert.equal(t.calls.length, 0);
});

// ---- status callback --------------------------------------------------------------

dbTest('status callback: signed, by provider_id; delivered -> sent, undelivered -> failed with ErrorCode, 21610 stops; 204', async () => {
  const {sql, db} = advisorDatabase(), at = '2026-10-03T15:00:00.000Z', env = {ASSETS, ...ON, ...TW, DB: db};
  const out = fixture('status-delivered.json').params.MessageSid;
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,channel,last_seen_at,created_at,updated_at) VALUES('c1','h','sms',?,?,?)`).run(at, at, at);
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES('o1','c1','out','sms',?,'x','unknown',?)`).run(out, at);
  const post = (params, opts) => quiet(() => worker.fetch(twilioRequest(statusPath(), params, opts), env));
  const unsigned = (await post(fixture('status-delivered.json').params, {token: 'wrong-token'})).value;
  assert.equal(unsigned.status, 401);
  assert.equal(sql.prepare("SELECT status FROM advisor_messages WHERE id='o1'").get().status, 'unknown');
  const wrongToken = await quiet(() => worker.fetch(twilioRequest(statusPath('nope'), fixture('status-delivered.json').params, {signFor: `https://skippercast.com${statusPath('nope')}`}), env));
  assert.equal(wrongToken.value.status, 401);
  const delivered = (await post(fixture('status-delivered.json').params)).value;
  assert.equal(delivered.status, 204);
  let row = sql.prepare("SELECT * FROM advisor_messages WHERE id='o1'").get();
  assert.equal(row.status, 'sent'); assert.ok(row.sent_at);
  // Queued/sending callbacks change nothing.
  assert.equal((await post({...fixture('status-delivered.json').params, MessageStatus: 'queued', SmsStatus: 'queued'})).value.status, 204);
  assert.equal(sql.prepare("SELECT status FROM advisor_messages WHERE id='o1'").get().status, 'sent');
  assert.equal((await post(fixture('status-undelivered.json').params)).value.status, 204);
  row = sql.prepare("SELECT * FROM advisor_messages WHERE id='o1'").get();
  assert.deepEqual({status: row.status, error: row.error}, {status: 'failed', error: fixture('status-undelivered.json')._expect.error});
  await post({...fixture('status-undelivered.json').params, MessageStatus: 'failed', SmsStatus: 'failed', ErrorCode: '21610'});
  assert.equal(sql.prepare("SELECT status FROM advisor_contacts WHERE id='c1'").get().status, 'stopped');
  // An unknown sid is acknowledged and changes nothing.
  assert.equal((await post({...fixture('status-delivered.json').params, MessageSid: 'SM' + 'e'.repeat(32), SmsSid: 'SM' + 'e'.repeat(32)})).value.status, 204);
});

// ---- media, health, capabilities --------------------------------------------------

test('fetchMediaByRef: Basic auth to api.twilio.com only; the CDN redirect is followed without credentials; other URLs rejected', async () => {
  const mediaUrl = fixture('inbound-mms.json').params.MediaUrl0;
  const t = fakeTwilio({[mediaUrl]: () => new Response(null, {status: 307, headers: {Location: 'https://media.example-cdn.test/signed/abc'}}),
    'https://media.example-cdn.test/signed/abc': () => new Response('jpeg-bytes', {status: 200})});
  const tw = createTwilio({fetcher: t.fetch}), env = {...TW};
  assert.equal(await (await tw.fetchMediaByRef(mediaUrl, env)).text(), 'jpeg-bytes');
  assert.equal(t.calls[0].headers.Authorization, BASIC); assert.equal(t.calls[0].redirect, 'manual');
  assert.equal(t.calls[1].url.host, 'media.example-cdn.test'); assert.equal(t.calls[1].headers.Authorization, undefined, 'credentials never leave api.twilio.com');
  for (const ref of ['https://evil.example/x.jpg', 'http://api.twilio.com/x', 'https://api.twilio.com.evil.example/x', 'https://user:pw@api.twilio.com/x', 'guid-123'])
    await assert.rejects(tw.fetchMediaByRef(ref, env), /not a Twilio media URL/, ref);
  await assert.rejects(tw.fetchMediaByRef(mediaUrl, {}), /not configured/);
  assert.equal(t.calls.length, 2);
  assert.equal(isTwilioMediaUrl(mediaUrl), true);
  assert.equal(adapterForMedia('sms', mediaUrl).name, 'twilio');
  // The direct InboundMedia.fetch takes the same path.
  const [m] = inboundFromParams(new URLSearchParams(fixture('inbound-mms.json').params), {...ON}, t.fetch);
  assert.equal(await (await m.media[0].fetch(env)).text(), 'jpeg-bytes');
});

test('health: GET the account; 200 is ok', async () => {
  const t = fakeTwilio({[`/Accounts/${SID}.json`]: {status: 200, body: fixture('account.json').response}});
  const tw = createTwilio({fetcher: t.fetch});
  assert.deepEqual(await tw.health({...TW}), {ok: true, detail: 'account active'});
  assert.equal(t.calls[0].url.href, `https://api.twilio.com/2010-04-01/Accounts/${SID}.json`); assert.equal(t.calls[0].headers.Authorization, BASIC);
  const denied = createTwilio({fetcher: fakeTwilio({[`/Accounts/${SID}.json`]: {status: 401, body: {code: 20003}}}).fetch});
  assert.deepEqual(await denied.health({...TW}), {ok: false, detail: 'account http-401'});
  assert.deepEqual(await tw.health({}), {ok: false, detail: 'not-configured'});
  assert.deepEqual(await tw.health({...TW, TWILIO_ACCOUNT_SID: 'not-a-sid'}), {ok: false, detail: 'not-configured'});
});

test('registered in ADAPTERS with the planned capabilities; SMS split rules apply', () => {
  assert.equal(ADAPTERS.twilio.name, 'twilio');
  assert.equal(channelFor({ADVISOR_CHANNEL: 'twilio'}, {phone_enc: 'x', web_session: null}), ADAPTERS.twilio);
  assert.deepEqual(ADAPTERS.twilio.capabilities, {media: true, maxMediaBytes: 5 * 1024 * 1024, typing: false, read: false, segments: 3});
  assert.equal(MAX_MEDIA_BYTES, 5 * 1024 * 1024);
  assert.equal(ADAPTERS.twilio.typing, undefined); assert.equal(ADAPTERS.twilio.markRead, undefined);
  const chunks = splitForChannel('word '.repeat(300), ADAPTERS.twilio);
  assert.ok(chunks.length > 1 && chunks.every(c => c.length <= 480));
});

// ---- relay-check --twilio -------------------------------------------------------

test('relay-check --twilio: checks the account, sends one SMS, prints the sid, never the token', async () => {
  const {runTwilioChecks, parseArgs} = await import('../scripts/advisor/relay-check.mjs');
  const args = parseArgs(['--twilio', '--to', '+15555550101']);
  assert.equal(args.twilio, true);
  const t = fakeTwilio({[`/Accounts/${SID}.json`]: {status: 200, body: fixture('account.json').response}, '/Messages.json': {status: 201, body: fixture('send-response.json').response}});
  const lines = [];
  const {passed, results, sid} = await runTwilioChecks({env: TW, args, fetcher: t.fetch, log: l => lines.push(l)});
  assert.equal(passed, true);
  assert.deepEqual(results.map(r => [r.name, r.ok]), [['environment', true], ['account', true], ['send SMS', true]]);
  assert.equal(sid, fixture('send-response.json').response.sid);
  const form = new URLSearchParams(t.calls[1].body);
  assert.equal(form.get('To'), '+15555550101'); assert.equal(form.get('From'), '+15555550100'); assert.match(form.get('Body'), /relay check/);
  assert.ok(t.calls.every(c => c.headers.Authorization === BASIC));
  const out = lines.join('\n');
  assert.ok(out.includes(sid), 'prints the sid');
  for (const secret of [AUTH, '5555550101', SID]) assert.ok(!out.includes(secret), secret);
  const missing = await runTwilioChecks({env: {}, args, fetcher: t.fetch, log: () => {}});
  assert.equal(missing.passed, false); assert.match(missing.results[0].detail, /missing TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM/);
  const noSend = await runTwilioChecks({env: {TWILIO_ACCOUNT_SID: SID, TWILIO_AUTH_TOKEN: AUTH}, args: parseArgs(['--twilio', '--no-send']), fetcher: t.fetch, log: () => {}});
  assert.equal(noSend.passed, true, 'TWILIO_FROM is only needed to send');
  const denied = await runTwilioChecks({env: TW, args, fetcher: fakeTwilio({[`/Accounts/${SID}.json`]: {status: 401, body: {code: 20003}}}).fetch, log: () => {}});
  assert.equal(denied.passed, false); assert.match(denied.results[1].detail, /HTTP 401.*20003/);
});

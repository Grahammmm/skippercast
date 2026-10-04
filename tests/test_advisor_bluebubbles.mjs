// Text Advisor BlueBubbles channel (server/advisor/channels/, server/routes/advisor.ts):
// every recorded webhook shape normalizes as 03 specifies, the token-guarded
// inbound route (401, dedupe, inbound row + placeholder media rows, queue or
// inline), send (chat GUID, multipart, 200-with-error), health, the split
// rules, and the relay-down hold and release. Offline: a fake fetcher plays the
// relay; an in-memory SQLite has the real migrations.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const {createBlueBubbles, normalizePayload, envelopeError, serverInfoDetail, skipReason} = await import('../server/advisor/channels/bluebubbles.ts');
const {splitForChannel, channelFor, ADAPTERS, IMESSAGE_CHUNK, SMS_CHUNK, ChannelNotImplemented} = await import('../server/advisor/channels/index.ts');
const {consumeAdvisor, releaseHeld, ADVISOR_QUEUE_NAME, WARM_UP_TEXT, HOLD_MAX_MS, RELEASE_BATCH} = await import('../server/advisor/consumer.ts');
const {advisorCron, RELAY_KEY} = await import('../server/advisor/cron.ts');
const {deriveKeys, encryptPhone, phoneHash} = await import('../server/advisor/contacts.ts');
const {outboundId} = await import('../server/advisor/ids.ts');
const {sameSecret} = await import('../server/routes/advisor.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const FIXTURES = new URL('./fixtures/advisor/bluebubbles/', import.meta.url);
const fixture = name => JSON.parse(readFileSync(new URL(name, FIXTURES)));
const KEY = Buffer.alloc(32, 7).toString('base64');
const TOKEN = 'tok_' + 'a'.repeat(40);
const T0 = Date.parse('2026-10-03T15:00:00Z');
const ON = {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_PHONE_KEY: KEY, ADVISOR_WEBHOOK_TOKEN: TOKEN, ADVISOR_NUMBER: '+15555550100'};
const RELAY = {BLUEBUBBLES_URL: 'https://relay.example.test/', BLUEBUBBLES_PASSWORD: 'pw&secret', CF_ACCESS_CLIENT_ID: 'id.access', CF_ACCESS_CLIENT_SECRET: 'access-secret'};
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

/** A fake relay: answers by path from `routes` (path -> body object | function(url, init) -> Response | Error). Records calls. */
function relay(routes = {}) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const u = new URL(url), path = u.pathname.replace(/^\/api\/v1\//, '');
    calls.push({url: u, path, method: init.method ?? 'GET', headers: init.headers ?? {}, body: init.body, signal: init.signal});
    let answer = routes[path] ?? routes[path.replace(/\/[^/]+\/(typing|read|download)$/, '/*/$1')];
    if (typeof answer === 'function') answer = await answer(u, init, calls.length);
    if (answer instanceof Error) throw answer;
    if (answer instanceof Response) return answer;
    if (answer === undefined) return new Response('{"status":404,"message":"not found"}', {status: 404});
    return new Response(JSON.stringify(answer), {status: 200, headers: {'Content-Type': 'application/json'}});
  };
  return {calls, fetch};
}
const OK_SEND = {status: 200, message: 'Message sent!', data: {guid: 'GUID-SENT-1', error: 0}};

// ---- normalize ----------------------------------------------------------------

test('every fixture is a {type, data} webhook or a {status, data} response with only fictional numbers', () => {
  const names = readdirSync(FIXTURES).filter(f => f.endsWith('.json'));
  for (const required of ['text', 'photo', 'video', 'sms-mms', 'reaction', 'group', 'outbound-echo', 'send-error', 'updated-message', 'new-server'])
    assert.ok(names.includes(`${required}.json`), required);
  for (const name of names) {
    const f = fixture(name);
    assert.ok(typeof f._source === 'string' && f._source.length > 20, `${name} says where its shape comes from`);
    assert.ok('type' in f || 'status' in f, name);
    for (const m of JSON.stringify(f).matchAll(/\+1\d{10}/g)) assert.match(m[0], /^\+1555/, `${name}: ${m[0]}`);
  }
});

test('webhook fixtures normalize as 03 specifies', async () => {
  const env = {...ON};
  for (const name of readdirSync(FIXTURES).filter(f => f.endsWith('.json'))) {
    const f = fixture(name);
    if (!('type' in f)) continue;
    const {value: result, lines} = await quiet(() => normalizePayload(f, env));
    const expect = f._expect;
    if (expect.inbound) {
      assert.ok(Array.isArray(result), name); assert.equal(result.length, 1, name);
      const [m] = result;
      assert.equal(m.channel, expect.channel, name); assert.equal(m.from, expect.from, name);
      assert.equal(m.providerId, f.data.guid, name); assert.equal(m.to, '+15555550100', name);
      assert.equal(m.media.length, expect.media, name); assert.equal(m.isGroup, false, name);
      assert.equal(m.receivedAt, new Date(f.data.dateCreated).toISOString(), name);
      if ('text' in expect) assert.equal(m.text, expect.text, name);
      assert.ok(!('raw' in m), 'raw payload never carried');
      for (const [i, media] of m.media.entries()) {
        const a = f.data.attachments[i];
        assert.deepEqual({providerRef: media.providerRef, mime: media.mime, bytes: media.bytes, name: media.name, width: media.width, height: media.height},
          {providerRef: a.guid, mime: a.mimeType, bytes: a.totalBytes, name: a.transferName, width: a.width, height: a.height}, name);
        assert.equal(typeof media.fetch, 'function');
      }
    } else {
      assert.equal(result, 'ignore', name);
      if (expect.ignore && !['other', 'new-server'].includes(expect.ignore)) assert.ok(lines.some(l => l.includes('advisor_bluebubbles_dropped') && l.includes(expect.ignore)), `${name}: logged ${expect.ignore}`);
      if (expect.ignore === 'new-server') assert.ok(lines.some(l => l.includes('advisor_bluebubbles_new_server')));
    }
  }
});

test('skip rules: from-me, reactions, itemType, groups by style or ;+; GUID, empty, non-NANP sender', async () => {
  const base = fixture('text.json').data;
  assert.equal(skipReason(base), null);
  assert.equal(skipReason({...base, isFromMe: true}), 'from-me');
  assert.equal(skipReason({...base, associatedMessageType: 2000}), 'reaction');
  assert.equal(skipReason({...base, associatedMessageGuid: 'p:0/X'}), 'reaction');
  assert.equal(skipReason({...base, itemType: 1}), 'item-type');
  assert.equal(skipReason({...base, chats: [{guid: 'iMessage;-;+15555550101', style: 43}]}), 'group');
  assert.equal(skipReason({...base, chats: [{guid: 'iMessage;+;chat1', style: 45}]}), 'group');
  const run = data => quiet(() => normalizePayload({type: 'new-message', data}, ON));
  assert.equal((await run({...base, text: '  ￼ '})).value, 'ignore', 'no text, no media');
  const intl = await run({...base, handle: {address: '+447700900123', service: 'iMessage'}});
  assert.equal(intl.value, 'ignore'); assert.ok(intl.lines.some(l => l.includes('not-nanp') && l.includes('"count":1')));
  assert.ok(!intl.lines.join('\n').includes('447700900123'), 'the dropped number is never logged');
  const email = await run({...base, handle: {address: 'someone@example.test', service: 'iMessage'}});
  assert.equal(email.value, 'ignore', 'an Apple Account email handle has no number to text back');
  assert.equal((await run({...base, handle: {address: '(555) 555-0101', service: 'SMS'}})).value[0].from, '+15555550101');
});

test('attachment fetch is authenticated: password query and Access headers, through the injected fetcher', async () => {
  const r = relay({'attachment/*/download': () => new Response('bytes', {status: 200})});
  const bb = createBlueBubbles({fetcher: r.fetch});
  const env = {...ON, ...RELAY};
  const request = new Request('https://skippercast.com/x', {method: 'POST', body: JSON.stringify(fixture('photo.json'))});
  const [m] = await bb.normalize(request, env);
  const response = await m.media[0].fetch(env);
  assert.equal(await response.text(), 'bytes');
  const call = r.calls[0];
  assert.equal(call.url.pathname, `/api/v1/attachment/${encodeURIComponent(m.media[0].providerRef)}/download`);
  assert.equal(call.url.searchParams.get('password'), 'pw&secret');
  assert.equal(call.headers['CF-Access-Client-Id'], 'id.access'); assert.equal(call.headers['CF-Access-Client-Secret'], 'access-secret');
});

test('normalize caps the webhook body at 64 KB', async () => {
  const bb = createBlueBubbles();
  const big = new Request('https://skippercast.com/x', {method: 'POST', body: JSON.stringify({type: 'new-message', data: {text: 'x'.repeat(70000)}})});
  await assert.rejects(bb.normalize(big, ON), /body too large/);
});

// ---- split ----------------------------------------------------------------------

test('splitForChannel: limits, paragraph then sentence boundaries, (n/m) prefixes on SMS only', () => {
  const bb = {name: 'bluebubbles'}, tw = {name: 'twilio'}, web = {name: 'web'};
  assert.deepEqual(splitForChannel('  short  ', bb, 'imessage'), ['short']);
  assert.deepEqual(splitForChannel('', bb, 'imessage'), []);
  const para = n => `Paragraph ${n}. ` + 'Rockfish were steady on the reef. '.repeat(8).trim();
  const long = [1, 2, 3, 4, 5].map(para).join('\n\n');
  const im = splitForChannel(long, bb, 'imessage');
  assert.ok(im.length >= 2 && im.every(c => c.length <= IMESSAGE_CHUNK), 'iMessage chunks within 1,000');
  assert.ok(im.every(c => c.startsWith('Paragraph')), 'split at paragraph boundaries');
  assert.ok(im.every(c => !/^\(\d+\/\d+\)/.test(c)), 'no prefix on iMessage');
  for (const [adapter, channel] of [[bb, 'sms'], [tw, undefined], [tw, 'imessage']]) {
    const sms = splitForChannel(long, adapter, channel);
    assert.ok(sms.length >= 3, 'more chunks on SMS');
    assert.ok(sms.every(c => c.length <= SMS_CHUNK), 'SMS chunks within 480 including the prefix');
    assert.ok(!/^\(/.test(sms[0]), 'the first chunk has no prefix');
    sms.slice(1).forEach((c, i) => assert.ok(c.startsWith(`(${i + 2}/${sms.length}) `), c.slice(0, 12)));
    assert.equal(sms.map(c => c.replace(/^\(\d+\/\d+\) /, '')).join(' ').replace(/\s+/g, ' '), long.replace(/\s+/g, ' '), 'nothing lost or reordered');
  }
  // One paragraph longer than the limit splits at sentences; a sentence longer than the limit at words.
  const sentences = Array.from({length: 40}, (_, i) => `Sentence number ${i} is here.`).join(' ');
  const bySentence = splitForChannel(sentences, bb, 'sms');
  assert.ok(bySentence.every(c => /\.$/.test(c)), 'chunks end at a sentence boundary');
  const words = splitForChannel(Array.from({length: 300}, () => 'lingcod').join(' '), bb, 'imessage');
  assert.ok(words.every(c => c.length <= IMESSAGE_CHUNK && !c.startsWith(' ') && !c.endsWith(' ')));
  assert.deepEqual(splitForChannel(long, web), [long], 'web is never split');
});

// ---- channelFor -----------------------------------------------------------------

test('channelFor: web for a web-only contact, else ADVISOR_CHANNEL; web is a stub until TA-C3 (TA-C2 replaced twilio)', async () => {
  assert.equal(channelFor({}, {phone_enc: 'x', web_session: null}).name, 'bluebubbles');
  assert.equal(channelFor({ADVISOR_CHANNEL: 'twilio'}, {phone_enc: 'x', web_session: null}).name, 'twilio');
  assert.equal(channelFor({}, {phone_enc: null, web_session: 'h'}).name, 'web');
  assert.equal(ADAPTERS.bluebubbles.name, 'bluebubbles');
  // TA-C2: the Twilio adapter is real now; unconfigured, it fails the send instead of throwing.
  assert.deepEqual(await ADAPTERS.twilio.send({id: 'x', to: 'y'}, {}), {providerId: null, status: 'failed', error: 'not-configured'});
  await assert.rejects(ADAPTERS.web.send({id: 'x', to: 'y'}, {}), ChannelNotImplemented);
  await assert.rejects(ADAPTERS.web.normalize(new Request('https://x.test'), {}), /not implemented/);
});

// ---- send -----------------------------------------------------------------------

async function phoneEnc(number = '+15555550101') { return encryptPhone(await deriveKeys(KEY), number); }

test('send: decrypts the address, iMessage GUID from the channel hint, apple-script, providerId = data.guid', async () => {
  const r = relay({'message/text': OK_SEND}), bb = createBlueBubbles({fetcher: r.fetch});
  const to = await phoneEnc();
  const result = await bb.send({id: 'out-1', to, text: 'Hello', channelHint: 'imessage'}, {...ON, ...RELAY});
  assert.deepEqual(result, {providerId: 'GUID-SENT-1', status: 'sent'});
  assert.equal(r.calls.length, 1, 'no availability check when the channel is known');
  const call = r.calls[0];
  assert.equal(call.method, 'POST'); assert.equal(call.url.origin + call.url.pathname, 'https://relay.example.test/api/v1/message/text');
  assert.equal(call.url.searchParams.get('password'), 'pw&secret');
  assert.equal(call.headers['CF-Access-Client-Id'], 'id.access'); assert.equal(call.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(call.body), {chatGuid: 'iMessage;-;+15555550101', tempGuid: 'out-1', message: 'Hello', method: 'apple-script'});
  assert.ok(call.signal instanceof AbortSignal);
});

test('send: SMS GUID from the hint; private-api method when enabled; first contact uses the availability check', async () => {
  const to = await phoneEnc('+15555550102');
  let r = relay({'message/text': OK_SEND});
  await createBlueBubbles({fetcher: r.fetch}).send({id: 'o', to, text: 'Hi', channelHint: 'sms'}, {...ON, ...RELAY, BLUEBUBBLES_PRIVATE_API: 'true'});
  assert.deepEqual(JSON.parse(r.calls[0].body), {chatGuid: 'SMS;-;+15555550102', tempGuid: 'o', message: 'Hi', method: 'private-api'});
  for (const [available, guid] of [[true, 'iMessage;-;+15555550102'], [false, 'SMS;-;+15555550102']]) {
    r = relay({'handle/availability/imessage': {status: 200, message: 'ok', data: {available}}, 'message/text': OK_SEND});
    await createBlueBubbles({fetcher: r.fetch}).send({id: 'o', to, text: 'Hi'}, {...ON, ...RELAY});
    assert.equal(r.calls[0].path, 'handle/availability/imessage'); assert.equal(r.calls[0].url.searchParams.get('address'), '+15555550102');
    assert.equal(JSON.parse(r.calls[1].body).chatGuid, guid);
  }
  r = relay({'handle/availability/imessage': new Response('', {status: 500}), 'message/text': OK_SEND});
  await quiet(() => createBlueBubbles({fetcher: r.fetch}).send({id: 'o', to, text: 'Hi'}, {...ON, ...RELAY}));
  assert.equal(JSON.parse(r.calls[1].body).chatGuid, 'SMS;-;+15555550102', 'SMS when availability is unknown');
});

test('send: media is a multipart attachment after the text, read from R2', async () => {
  const r = relay({'message/text': OK_SEND, 'message/attachment': {status: 200, message: 'ok', data: {guid: 'GUID-ATT'}}});
  const bytes = new Uint8Array([0xff, 0xd8, 0xff, 0xd9]);
  const bucket = {async get(key) { return key === 'advisor/derived/m1/public.jpg' ? {size: bytes.length, httpMetadata: {contentType: 'image/jpeg'}, arrayBuffer: async () => bytes.buffer} : null; }};
  const env = {...ON, ...RELAY, ADVISOR_MEDIA: bucket}, to = await phoneEnc();
  const result = await createBlueBubbles({fetcher: r.fetch}).send({id: 'o2', to, text: 'Here it is', mediaKeys: ['advisor/derived/m1/public.jpg'], channelHint: 'imessage'}, env);
  assert.deepEqual(result, {providerId: 'GUID-SENT-1', status: 'sent'});
  assert.deepEqual(r.calls.map(c => c.path), ['message/text', 'message/attachment'], 'text first, then the photo');
  const form = r.calls[1].body;
  assert.ok(form instanceof FormData);
  assert.equal(form.get('chatGuid'), 'iMessage;-;+15555550101'); assert.equal(form.get('name'), 'public.jpg'); assert.equal(form.get('tempGuid'), 'o2-m0');
  const file = form.get('attachment');
  assert.equal(file.type, 'image/jpeg'); assert.deepEqual(new Uint8Array(await file.arrayBuffer()), bytes);
  assert.equal(r.calls[1].headers['Content-Type'], undefined, 'fetch sets the multipart boundary itself');
  // Photo missing after the text went out: unknown, so a retry never resends the text.
  const missing = await createBlueBubbles({fetcher: relay({'message/text': OK_SEND}).fetch}).send({id: 'o3', to, text: 'x', mediaKeys: ['nope'], channelHint: 'sms'}, env);
  assert.equal(missing.status, 'unknown'); assert.equal(missing.error, 'media-missing');
});

test('send: a 200 whose body carries error is a failure; HTTP errors fail; a timeout is unknown; one retry on a network error only', async () => {
  const to = await phoneEnc(), env = {...ON, ...RELAY}, msg = {id: 'o', to, text: 'x', channelHint: 'sms'};
  const smsError = fixture('send-sms-error-response.json');
  assert.equal(envelopeError(smsError), 'relay-error');
  assert.equal(envelopeError({status: 200, data: {guid: 'g', error: 0}}), null);
  assert.equal(envelopeError({status: 200, data: {guid: 'g', error: 4}}), 'message-error-4');
  let result = await createBlueBubbles({fetcher: relay({'message/text': smsError}).fetch}).send(msg, env);
  assert.deepEqual(result, {providerId: null, status: 'failed', error: 'relay-error'});
  const fourHundred = relay({'message/text': new Response('{"status":400}', {status: 400})});
  result = await createBlueBubbles({fetcher: fourHundred.fetch}).send(msg, env);
  assert.deepEqual(result, {providerId: null, status: 'failed', error: 'http-400'}); assert.equal(fourHundred.calls.length, 1, 'no retry on 4xx');
  const flaky = relay({'message/text': (_u, _i, n) => n === 1 ? new TypeError('network connection lost') : OK_SEND});
  result = await createBlueBubbles({fetcher: flaky.fetch}).send(msg, env);
  assert.equal(result.status, 'sent'); assert.equal(flaky.calls.length, 2, 'one retry after a network error');
  const down = relay({'message/text': new TypeError('network')});
  result = await createBlueBubbles({fetcher: down.fetch}).send(msg, env);
  assert.deepEqual(result, {providerId: null, status: 'failed', error: 'network'}); assert.equal(down.calls.length, 2, 'only one retry');
  const slow = relay({'message/text': () => { const e = new Error('timed out'); e.name = 'TimeoutError'; return e; }});
  result = await createBlueBubbles({fetcher: slow.fetch}).send(msg, env);
  assert.deepEqual(result, {providerId: null, status: 'unknown', error: 'timeout'}); assert.equal(slow.calls.length, 1, 'never retried: the relay may have sent it');
  assert.equal((await createBlueBubbles().send(msg, {...ON})).error, 'not-configured');
  assert.equal((await createBlueBubbles({fetcher: relay().fetch}).send({...msg, to: 'garbage'}, env)).error, 'bad-address');
  assert.equal((await createBlueBubbles({fetcher: relay().fetch}).send(msg, {...RELAY})).error, 'no-phone-key');
  assert.ok(!JSON.stringify(result).includes('pw&secret'));
});

test('typing and markRead only with the Private API', async () => {
  const to = await phoneEnc(), r = relay({'chat/*/typing': {status: 200}, 'chat/*/read': {status: 200}}), bb = createBlueBubbles({fetcher: r.fetch});
  await bb.typing(to, true, {...ON, ...RELAY}); await bb.markRead(to, {...ON, ...RELAY});
  assert.equal(r.calls.length, 0, 'skipped without BLUEBUBBLES_PRIVATE_API');
  const env = {...ON, ...RELAY, BLUEBUBBLES_PRIVATE_API: 'true'};
  await bb.typing(to, true, env); await bb.typing(to, false, env); await bb.markRead(to, env);
  assert.deepEqual(r.calls.map(c => [c.method, decodeURIComponent(c.url.pathname)]), [
    ['POST', '/api/v1/chat/iMessage;-;+15555550101/typing'], ['DELETE', '/api/v1/chat/iMessage;-;+15555550101/typing'], ['POST', '/api/v1/chat/iMessage;-;+15555550101/read']]);
});

test('health: ping then server/info, parsed into version and Private API state', async () => {
  const info = fixture('server-info.json');
  let r = relay({ping: {status: 200, message: 'Ping received!', data: 'pong'}, 'server/info': info});
  assert.deepEqual(await createBlueBubbles({fetcher: r.fetch}).health({...RELAY}), {ok: true, detail: 'version 1.9.9, private API on, helper connected, macOS 15.1'});
  assert.deepEqual(r.calls.map(c => c.path), ['ping', 'server/info']);
  assert.equal(serverInfoDetail({server_version: '1.9.9<script>', private_api: false}), 'version 1.9.9script, private API off');
  r = relay({ping: new Response('bad gateway', {status: 502})});
  assert.deepEqual(await createBlueBubbles({fetcher: r.fetch}).health({...RELAY}), {ok: false, detail: 'ping http-502'});
  assert.deepEqual(await createBlueBubbles().health({}), {ok: false, detail: 'not-configured'});
  assert.equal(ADAPTERS.bluebubbles.capabilities.media, true);
});

// ---- inbound route ----------------------------------------------------------------

const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const post = (env, payload, token = TOKEN, init = {}) => worker.fetch(new Request(`https://skippercast.com/api/advisor/inbound/bluebubbles/${token}`,
  {method: 'POST', headers: {'Content-Type': 'application/json', 'cf-connecting-ip': '203.0.113.9', ...init.headers}, body: typeof payload === 'string' ? payload : JSON.stringify(payload)}), {ASSETS, ...env});
function queue() { const sent = []; return {sent, async send(body) { sent.push(body); }}; }

test('sameSecret compares in constant time and never accepts an empty secret', async () => {
  assert.equal(await sameSecret('abc', 'abc'), true);
  assert.equal(await sameSecret('abd', 'abc'), false);
  assert.equal(await sameSecret('', ''), false);
  assert.equal(await sameSecret('abc', ''), false);
});

dbTest('a wrong or missing token is a 401 with a counted log; the body is never read', async () => {
  const {sql, db} = advisorDatabase();
  for (const [env, token] of [[{...ON, DB: db}, 'wrong'], [{...ON, DB: db, ADVISOR_WEBHOOK_TOKEN: undefined}, TOKEN]]) {
    const {value: response, lines} = await quiet(() => post(env, fixture('text.json'), token));
    assert.equal(response.status, 401); assert.equal((await response.json()).error, 'Unauthorized');
    const line = lines.find(l => l.includes('advisor_webhook_unauthorized'));
    assert.ok(line && line.includes('"count":1')); assert.ok(!line.includes(TOKEN) && !line.includes('wrong'));
  }
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_messages').get().n, 0);
  assert.equal((await post({TEXT_ADVISOR_ENABLED: 'false', DB: db}, fixture('text.json'))).status, 404, 'gated like every advisor path');
});

dbTest('rate limited by PUBLIC_LIMITER when bound; body over 64 KB is a 400', async () => {
  const {db} = advisorDatabase(), keys = [];
  const limiter = {async limit({key}) { keys.push(key); return {success: false}; }};
  const limited = await post({...ON, DB: db, PUBLIC_LIMITER: limiter}, fixture('text.json'));
  assert.equal(limited.status, 429); assert.deepEqual(keys, ['advisor-inbound:203.0.113.9']);
  const {value: big, lines} = await quiet(() => post({...ON, DB: db}, JSON.stringify({type: 'new-message', data: {text: 'x'.repeat(70000)}})));
  assert.equal(big.status, 400); assert.equal((await big.json()).error, 'body too large');
  const {value: broken, lines: more} = await quiet(() => post({...ON, DB: undefined}, fixture('text.json')));
  assert.equal(broken.status, 503);
  assert.ok(![...lines, ...more].join('\n').includes(TOKEN), 'the token in the path never reaches a log line');
});

dbTest('a text: contact created, inbound row queued, message enqueued, 200 {}; a second delivery is a no-op', async () => {
  const {sql, db} = advisorDatabase(), q = queue(), env = {...ON, DB: db, ADVISOR_QUEUE: q};
  const {value: response} = await quiet(() => post(env, fixture('text.json')));
  assert.equal(response.status, 200); assert.deepEqual(await response.json(), {});
  const rows = sql.prepare('SELECT * FROM advisor_messages').all();
  assert.equal(rows.length, 1);
  const [row] = rows;
  assert.deepEqual({direction: row.direction, channel: row.channel, provider_id: row.provider_id, body: row.body, status: row.status, media_json: row.media_json},
    {direction: 'in', channel: 'imessage', provider_id: fixture('text.json').data.guid, body: fixture('text.json').data.text, status: 'queued', media_json: null});
  assert.deepEqual(q.sent, [{message_id: row.id}]);
  const contact = sql.prepare('SELECT * FROM advisor_contacts').get();
  assert.equal(contact.id, row.contact_id); assert.equal(contact.channel, 'imessage');
  assert.equal(contact.phone_hash, await phoneHash(await deriveKeys(KEY), '+15555550101'));
  assert.ok(!JSON.stringify(contact).includes('5555550101'), 'no number stored in clear');
  const {value: again, lines} = await quiet(() => post(env, fixture('text.json')));
  assert.equal(again.status, 200); assert.deepEqual(await again.json(), {});
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_messages').get().n, 1); assert.equal(q.sent.length, 1, 'not enqueued twice');
  assert.ok(lines.some(l => l.includes('advisor_webhook_duplicate')));
});

dbTest('media: placeholder advisor_media rows (private, r2_key empty, provider_ref, claimed mime) listed in media_json', async () => {
  const {sql, db} = advisorDatabase(), q = queue(), env = {...ON, DB: db, ADVISOR_QUEUE: q};
  for (const name of ['photo.json', 'video.json', 'sms-mms.json']) assert.equal((await quiet(() => post(env, fixture(name)))).value.status, 200);
  const messages = sql.prepare('SELECT * FROM advisor_messages ORDER BY created_at, rowid').all();
  assert.deepEqual(messages.map(m => m.channel), ['imessage', 'imessage', 'sms']);
  assert.equal(messages[1].body, null, 'media-only: no body');
  for (const [i, name] of ['photo.json', 'video.json', 'sms-mms.json'].entries()) {
    const ids = JSON.parse(messages[i].media_json), a = fixture(name).data.attachments[0];
    assert.equal(ids.length, 1);
    const media = sql.prepare('SELECT * FROM advisor_media WHERE id=?').get(ids[0]);
    assert.deepEqual({contact_id: media.contact_id, message_id: media.message_id, kind: media.kind, mime: media.mime, bytes: media.bytes, width: media.width, height: media.height,
      r2_key: media.r2_key, publish_state: media.publish_state, provider_ref: media.provider_ref, exif_stripped: media.exif_stripped},
    {contact_id: messages[i].contact_id, message_id: messages[i].id, kind: a.mimeType.startsWith('video/') ? 'video' : 'image', mime: a.mimeType, bytes: a.totalBytes,
      width: a.width, height: a.height, r2_key: '', publish_state: 'private', provider_ref: a.guid, exif_stripped: 0}, name);
  }
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_contacts').get().n, 3);
  // A duplicate photo delivery adds no media rows.
  await quiet(() => post(env, fixture('photo.json')));
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_media').get().n, 3);
});

dbTest('ignored webhooks store nothing and answer 200 {}', async () => {
  const {sql, db} = advisorDatabase(), q = queue(), env = {...ON, DB: db, ADVISOR_QUEUE: q};
  for (const name of ['reaction.json', 'group.json', 'outbound-echo.json', 'new-server.json', 'typing.json']) {
    const {value: response} = await quiet(() => post(env, fixture(name)));
    assert.equal(response.status, 200, name); assert.deepEqual(await response.json(), {}, name);
  }
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_messages').get().n, 0);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_contacts').get().n, 0);
  assert.equal(q.sent.length, 0);
});

dbTest('without a queue the consumer runs inline: the stub reply goes out through BlueBubbles', async () => {
  const {sql, db} = advisorDatabase();
  const r = relay({'message/text': OK_SEND});
  const saved = ADAPTERS.bluebubbles;
  ADAPTERS.bluebubbles = createBlueBubbles({fetcher: r.fetch});
  try {
    const {value: response} = await quiet(() => post({...ON, ...RELAY, DB: db}, fixture('text.json')));
    assert.equal(response.status, 200);
  } finally { ADAPTERS.bluebubbles = saved; }
  const inbound = sql.prepare("SELECT * FROM advisor_messages WHERE direction='in'").get();
  const out = sql.prepare("SELECT * FROM advisor_messages WHERE direction='out'").get();
  assert.equal(inbound.status, 'done');
  assert.deepEqual({status: out.status, provider_id: out.provider_id, body: out.body, channel: out.channel}, {status: 'sent', provider_id: 'GUID-SENT-1', body: WARM_UP_TEXT, channel: 'imessage'});
  const sent = JSON.parse(r.calls[0].body);
  assert.deepEqual(sent, {chatGuid: 'iMessage;-;+15555550101', tempGuid: out.id, message: WARM_UP_TEXT, method: 'apple-script'}, 'last channel picks the GUID; tempGuid is the outbound id');
});

dbTest('updated-message confirms an unknown row as sent; message-send-error marks it failed', async () => {
  const {sql, db} = advisorDatabase(), env = {...ON, DB: db}, at = new Date(T0).toISOString();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,channel,last_seen_at,created_at,updated_at) VALUES('c1','h','imessage',?,?,?)`).run(at, at, at);
  const delivered = fixture('updated-message.json').data.guid;
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES('o1','c1','out','imessage',?,'x','unknown',?)`).run(delivered, at);
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES('0123456789abcdef0123456789abcdef','c1','out','imessage','x','sent',?)`).run(at);
  assert.equal((await quiet(() => post(env, fixture('updated-message.json')))).value.status, 200);
  const o1 = sql.prepare("SELECT * FROM advisor_messages WHERE id='o1'").get();
  assert.equal(o1.status, 'sent'); assert.ok(o1.sent_at);
  assert.equal((await quiet(() => post(env, fixture('send-error.json')))).value.status, 200);
  const failed = sql.prepare("SELECT * FROM advisor_messages WHERE id='0123456789abcdef0123456789abcdef'").get();
  assert.deepEqual({status: failed.status, error: failed.error}, {status: 'failed', error: 'relay-error-22'}, 'matched by tempGuid = our outbound id');
  // An updated-message with an error code also fails the row.
  await quiet(() => post(env, {type: 'updated-message', data: {...fixture('updated-message.json').data, error: 4, isDelivered: false, dateDelivered: null}}));
  assert.equal(sql.prepare("SELECT status FROM advisor_messages WHERE id='o1'").get().status, 'failed');
});

dbTest('GET /api/advisor/health reports the relay state and check time, never the URL', async () => {
  const {sql, db} = advisorDatabase();
  sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(RELAY_KEY, JSON.stringify({state: 'down', failures: 3, checked_at: '2026-10-03T15:00:00.000Z', last_ok_at: null}), 'x');
  const response = await worker.fetch(new Request('https://skippercast.com/api/advisor/health'), {ASSETS, ...ON, ...RELAY, DB: db});
  const text = await response.text();
  assert.deepEqual(JSON.parse(text).relay, {state: 'down', checked_at: '2026-10-03T15:00:00.000Z'});
  for (const leak of ['relay.example.test', 'pw&secret', 'access-secret']) assert.ok(!text.includes(leak), leak);
});

// ---- relay-down hold and release ---------------------------------------------------

async function heldSetup({relayDown = true, channel = 'imessage', contactStatus = 'active'} = {}) {
  const {sql, db} = advisorDatabase(), at = new Date(T0).toISOString();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,status,last_seen_at,created_at,updated_at) VALUES('c1','h1',?,?,?,?,?,?)`).run(await phoneEnc(), channel, contactStatus, at, at, at);
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES('in1','c1','in',?,'g1','hi','queued',?)`).run(channel, at);
  if (relayDown) sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(RELAY_KEY, JSON.stringify({state: 'down', failures: 3, checked_at: at, last_ok_at: null}), at);
  return {sql, db};
}
const batch = () => {
  const m = {id: 'm', body: {message_id: 'in1'}, attempts: 1, outcome: null, ack() { this.outcome = 'ack'; }, retry() { this.outcome = 'retry'; }};
  return {queue: ADVISOR_QUEUE_NAME, messages: [m], ackAll() {}, retryAll() {}};
};
const recorder = (name = 'bluebubbles') => { const sent = []; return {sent, name, async send(m) { sent.push(m); return {providerId: `p${sent.length}`, status: 'sent'}; }}; };

dbTest('relay down: a BlueBubbles send is written held and not attempted; the turn completes', async () => {
  const {sql, db} = await heldSetup(), ch = recorder();
  const {value} = await quiet(() => consumeAdvisor(batch(), {...ON, DB: db}, {channelFor: () => ch, now: () => T0}));
  assert.equal(value.done, 1); assert.equal(value.sends, 0); assert.equal(ch.sent.length, 0);
  const out = sql.prepare("SELECT * FROM advisor_messages WHERE direction='out'").get();
  assert.deepEqual({status: out.status, error: out.error, body: out.body, id: out.id}, {status: 'held', error: 'relay-down', body: WARM_UP_TEXT, id: await outboundId('in1', 0)});
  // Another adapter (twilio) is not held by the Mac relay's state.
  const other = await heldSetup(), tw = recorder('twilio');
  await quiet(() => consumeAdvisor(batch(), {...ON, DB: other.db}, {channelFor: () => tw, now: () => T0}));
  assert.equal(tw.sent.length, 1);
});

dbTest('a long reply is split for the channel: one outbound row per chunk, in order, with (n/m) on SMS', async () => {
  const {sql, db} = await heldSetup({relayDown: false, channel: 'sms'}), ch = recorder(), gaps = [];
  const text = Array.from({length: 30}, (_, i) => `Line ${i} about the bite at Morro Bay today.`).join(' ');
  const handler = async () => ({actions: [{type: 'send_text', text}], intent: 'test'});
  await quiet(() => consumeAdvisor(batch(), {...ON, DB: db}, {channelFor: () => ch, handler, sleep: async ms => { gaps.push(ms); }, now: () => T0}));
  assert.ok(ch.sent.length >= 3);
  assert.deepEqual(gaps, Array(ch.sent.length - 1).fill(300), '300 ms between chunks');
  assert.ok(ch.sent.every(m => m.text.length <= 480 && m.channelHint === 'sms'));
  assert.ok(ch.sent.slice(1).every((m, i) => m.text.startsWith(`(${i + 2}/${ch.sent.length}) `)));
  const rows = sql.prepare("SELECT id FROM advisor_messages WHERE direction='out'").all().map(r => r.id).sort();
  const expected = [await outboundId('in1', 0), ...await Promise.all(ch.sent.slice(1).map((_, i) => outboundId('in1', `0.${i + 1}`)))].sort();
  assert.deepEqual(rows, expected, 'chunk 0 keeps the action id; chunk n is "<index>.<n>"');
});

dbTest('releaseHeld: nothing while the relay is down (old rows still age out); oldest first once up; stopped contacts fail', async () => {
  const {sql, db} = await heldSetup(), ch = recorder(), env = {...ON, DB: db};
  const insert = (id, minutesAgo, body, contact = 'c1') => sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,media_json,status,error,created_at) VALUES(?,?,'out','imessage',?,?,'held','relay-down',?)`)
    .run(id, contact, body, id === 'h-media' ? '["advisor/derived/m1/public.jpg"]' : null, new Date(T0 - minutesAgo * 60000).toISOString());
  insert('h-old', 7 * 60, 'too old'); insert('h2', 30, 'second'); insert('h1', 60, 'first'); insert('h-media', 10, 'photo');
  let {value} = await quiet(() => releaseHeld(env, {channelFor: () => ch}, T0));
  assert.deepEqual(value, {released: 0, failed: 0, aged: 1, skipped: 'relay-down'});
  assert.deepEqual({...sql.prepare("SELECT status,error FROM advisor_messages WHERE id='h-old'").get()}, {status: 'failed', error: 'held-expired'});
  assert.equal(ch.sent.length, 0);
  sql.prepare('UPDATE job_state SET value=? WHERE key=?').run(JSON.stringify({state: 'up', failures: 0, checked_at: 'x', last_ok_at: 'x'}), RELAY_KEY);
  ({value} = await quiet(() => releaseHeld(env, {channelFor: () => ch, sleep: async () => {}}, T0)));
  assert.deepEqual(value, {released: 3, failed: 0, aged: 0, skipped: null});
  assert.deepEqual(ch.sent.map(m => m.text), ['first', 'second', 'photo'], 'oldest first');
  assert.deepEqual(ch.sent[2].mediaKeys, ['advisor/derived/m1/public.jpg'], 'held media keys are kept on the row');
  assert.ok(ch.sent.every(m => m.channelHint === 'imessage' && m.to.length > 20));
  assert.deepEqual({...sql.prepare("SELECT status,provider_id FROM advisor_messages WHERE id='h1'").get()}, {status: 'sent', provider_id: 'p1'});
  ({value} = await quiet(() => releaseHeld(env, {channelFor: () => ch}, T0)));
  assert.equal(value.released, 0, 'released rows are never sent again');
  sql.prepare("UPDATE advisor_contacts SET status='stopped'").run(); insert('h3', 5, 'after stop');
  ({value} = await quiet(() => releaseHeld(env, {channelFor: () => ch}, T0)));
  assert.equal(value.failed, 1); assert.deepEqual({...sql.prepare("SELECT status,error FROM advisor_messages WHERE id='h3'").get()}, {status: 'failed', error: 'stopped'});
});

dbTest('releaseHeld sends at most 50 per tick; with ADVISOR_CHANNEL=twilio it runs even while the Mac is down', async () => {
  const {sql, db} = await heldSetup(), ch = recorder('twilio');
  for (let i = 0; i < RELEASE_BATCH + 5; i++) sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES(?,'c1','out','imessage','x','held',?)`).run(`h${String(i).padStart(3, '0')}`, new Date(T0 - 60000 + i).toISOString());
  const {value} = await quiet(() => releaseHeld({...ON, ADVISOR_CHANNEL: 'twilio', DB: db}, {channelFor: () => ch, sleep: async () => {}}, T0));
  assert.equal(value.released, RELEASE_BATCH); assert.equal(sql.prepare("SELECT COUNT(*) n FROM advisor_messages WHERE status='held'").get().n, 5);
  assert.equal(HOLD_MAX_MS, 6 * 3600000);
});

dbTest('advisorCron runs the release after the watchdog: a recovered relay sends the held rows on that tick', async () => {
  const {sql, db} = await heldSetup(), ch = recorder();
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES('h1','c1','out','imessage','held text','held',?)`).run(new Date(T0 - 60000).toISOString());
  const ping = relay({ping: {status: 200, message: 'pong'}});
  const {value} = await quiet(() => advisorCron({...ON, ...RELAY, DB: db}, T0, {fetcher: ping.fetch, consumer: {channelFor: () => ch, sleep: async () => {}}}));
  assert.equal(value, 'ok');
  assert.deepEqual(ch.sent.map(m => m.text), ['held text']);
  assert.equal(sql.prepare("SELECT status FROM advisor_messages WHERE id='h1'").get().status, 'sent');
});

// ---- scripts/advisor/relay-check.mjs ----------------------------------------------

test('relay-check: pings, prints server info, checks availability, sends both, never prints a secret', async () => {
  const {runChecks, parseArgs, e164: checkE164, masked} = await import('../scripts/advisor/relay-check.mjs');
  assert.deepEqual(parseArgs(['--to', '+15555550101']), {to: '+15555550101', send: true, timeout: 15000, twilio: false, help: false});
  assert.equal(parseArgs(['--no-send']).send, false);
  assert.throws(() => parseArgs(['--nope']), /unknown argument/);
  assert.equal(checkE164('(555) 555-0101'), '+15555550101'); assert.equal(checkE164('+447700900123'), null);
  assert.equal(masked('+15555550101'), '+1••••••0101');
  const env = {BLUEBUBBLES_URL: 'https://relay.example.test', BLUEBUBBLES_PASSWORD: 'pw-very-secret', CF_ACCESS_CLIENT_ID: 'id.access', CF_ACCESS_CLIENT_SECRET: 'access-secret-value'};
  const r = relay({ping: {status: 200, message: 'Ping received!'}, 'server/info': fixture('server-info.json'),
    'handle/availability/imessage': {status: 200, data: {available: true}}, 'message/text': (_u, init) => JSON.parse(init.body).chatGuid.startsWith('SMS') ? fixture('send-sms-error-response.json') : OK_SEND});
  const lines = [];
  const {passed, results} = await runChecks({env, args: parseArgs(['--to', '+15555550101']), fetcher: r.fetch, log: l => lines.push(l)});
  assert.equal(passed, false, 'the SMS send failed');
  assert.deepEqual(results.map(x => [x.name, x.ok]), [['environment', true], ['ping', true], ['server info', true], ['iMessage availability', true], ['send iMessage', true], ['send SMS', false]]);
  assert.deepEqual(r.calls.map(c => c.path), ['ping', 'server/info', 'handle/availability/imessage', 'message/text', 'message/text']);
  assert.ok(r.calls.every(c => c.headers['CF-Access-Client-Secret'] === 'access-secret-value' && c.url.searchParams.get('password') === 'pw-very-secret'));
  assert.deepEqual(r.calls.slice(3).map(c => JSON.parse(c.body).chatGuid), ['iMessage;-;+15555550101', 'SMS;-;+15555550101']);
  const out = lines.join('\n');
  assert.match(out, /BlueBubbles 1\.9\.9, macOS 15\.1, Private API loaded/);
  assert.match(out, /FAIL: 5\/6 checks passed/);
  for (const secret of ['pw-very-secret', 'access-secret-value', 'id.access', '5555550101']) assert.ok(!out.includes(secret), secret);
  const missing = await runChecks({env: {}, args: parseArgs(['--no-send']), fetcher: r.fetch, log: () => {}});
  assert.equal(missing.passed, false); assert.match(missing.results[0].detail, /missing BLUEBUBBLES_URL/);
});

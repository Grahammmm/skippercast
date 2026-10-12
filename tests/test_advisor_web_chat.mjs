// Text Advisor web chat (TA-C3; docs/plans/text-advisor/03-channels.md § Web
// adapter, 08 § Web chat): the sc_adv cookie (issued once, reused), the message
// round trip through the stub handler and the per-request collector, media id
// ownership, the 8 MB image-only upload, the Origin check, the rate limit and
// the 40 s "pending" answer. Offline: real migrations in node:sqlite, a memory R2.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {memoryBucket} from './_advisor_r2.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const {webChat, WEB_UPLOAD_BYTES} = await import('../server/routes/advisor.ts');
const {web, normalizeWeb, createWebCollector, webSessionOf, webSessionCookie, newWebSession, WEB_COOKIE_MAX_AGE, WEB_BODY_BYTES} = await import('../server/advisor/channels/web.ts');
const {ADAPTERS, channelFor, splitForChannel} = await import('../server/advisor/channels/index.ts');
const {WARM_UP_TEXT, warmUpHandler} = await import('../server/advisor/consumer.ts');
const {sha256} = await import('../server/advisor/ids.ts');
const {CHAT_COPY, CHAT_MAX_PHOTO_BYTES} = await import('../web/advisor/copy.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const ORIGIN = 'https://skippercast.com';
const ON = {TEXT_ADVISOR_ENABLED: 'true'};
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const call = (path, env, init = {}) => worker.fetch(new Request(ORIGIN + path, {method: 'POST', ...init, headers: {Origin: ORIGIN, 'cf-connecting-ip': '203.0.113.9', ...init.headers}}), {ASSETS, ...env});
const message = (env, payload, cookie, headers = {}) => call('/api/advisor/web/message', env, {body: JSON.stringify(payload), headers: {'Content-Type': 'application/json', ...(cookie ? {Cookie: `sc_adv=${cookie}`} : {}), ...headers}});
const cookieOf = response => { const set = response.headers.get('Set-Cookie'); return set ? /^sc_adv=([\w-]+);/.exec(set)?.[1] ?? null : null; };
const setup = () => { const {sql, db} = advisorDatabase(); return {sql, db, env: {...ON, DB: db, ADVISOR_MEDIA: memoryBucket()}}; };
const errorBody = async response => { const {request_id: _id, ...rest} = await response.json(); return rest; };

// A small JPEG (SOI, APP0, DQT, SOF0, DHT, SOS + data, EOI) the media intake can walk and strip.
const seg = (marker, payload) => Buffer.from([0xff, marker, (payload.length + 2) >> 8, (payload.length + 2) & 255, ...payload]);
function jpeg(fill = 0) {
  return Buffer.concat([Buffer.from([0xff, 0xd8]), seg(0xe0, [...Buffer.from('JFIF\0'), 1, 1, 0, 0, 1, 0, 1, 0, 0]),
    seg(0xdb, [0, ...new Array(64).fill(1)]), seg(0xc0, [8, 0, 16, 0, 16, 1, 1, 0x11, 0]), seg(0xc4, [0, ...new Array(16).fill(0)]),
    seg(0xda, [1, 1, 0, 0, 63, 0]), Buffer.from([0x12, 0x34, fill, 0x56]), Buffer.from([0xff, 0xd9])]);
}
const form = (content, name = 'photo.jpg', type = 'image/jpeg') => { const f = new FormData(); f.append('file', new File([content], name, {type})); return f; };
const upload = (env, content, cookie, extra = {}) => call('/api/advisor/web/upload', env, {body: form(content, extra.name, extra.type), headers: cookie ? {Cookie: `sc_adv=${cookie}`} : {}});

// ---- the adapter ---------------------------------------------------------------

test('the web adapter is registered: media true, never split, no typing or read receipts, always healthy', async () => {
  assert.equal(ADAPTERS.web, web);
  assert.deepEqual(web.capabilities, {media: true, maxMediaBytes: 8 * 1024 * 1024, typing: false, read: false, segments: null});
  assert.deepEqual(await web.health({}), {ok: true, detail: 'web chat is served by the Worker'});
  assert.equal(channelFor({}, {phone_enc: null, web_session: 'h'}), web, 'a web-only contact gets the web adapter');
  assert.deepEqual(splitForChannel('a'.repeat(3000), web), ['a'.repeat(3000)]);
  // Outside a request nothing is listening: recorded failed, not unknown, and never thrown.
  assert.deepEqual(await web.send({id: 'x', to: 'h', text: 'hi'}, {}), {providerId: null, status: 'failed', error: 'web-no-request'});
});

test('the sc_adv cookie: 32 random bytes base64url, HttpOnly, Secure, SameSite=Lax, 90 days', () => {
  const a = newWebSession(), b = newWebSession();
  assert.match(a, /^[\w-]{43}$/); assert.notEqual(a, b);
  assert.equal(Buffer.from(a, 'base64url').length, 32);
  assert.equal(webSessionCookie(a), `sc_adv=${a}; Max-Age=7776000; Path=/; Secure; HttpOnly; SameSite=Lax`);
  assert.equal(WEB_COOKIE_MAX_AGE, 90 * 86400);
  const req = cookie => new Request(ORIGIN, {headers: {Cookie: cookie}});
  assert.equal(webSessionOf(req(`theme=dark; sc_adv=${a}; other=1`)), a);
  assert.equal(webSessionOf(req('sc_adv=short')), null, 'malformed value is ignored');
  assert.equal(webSessionOf(req('xsc_adv=' + a)), null);
  assert.equal(webSessionOf(new Request(ORIGIN)), null);
});

test('the collector records each send as sent, and fails them after close', async () => {
  const collector = createWebCollector();
  assert.deepEqual(await collector.send({id: 'o1', to: 'h', text: 'one'}), {providerId: 'o1', status: 'sent'});
  await collector.send({id: 'o2', to: 'h', mediaKeys: ['advisor/derived/m1/public.jpg']});
  assert.deepEqual(collector.replies, [{id: 'o1', text: 'one', mediaKeys: []}, {id: 'o2', text: '', mediaKeys: ['advisor/derived/m1/public.jpg']}]);
  collector.close();
  assert.deepEqual(await collector.send({id: 'o3', to: 'h', text: 'late'}), {providerId: null, status: 'failed', error: 'web-closed'});
  assert.equal(collector.replies.length, 2);
});

test('normalizeWeb validates the JSON body', async () => {
  const session = newWebSession();
  const run = (body, s = session) => normalizeWeb(new Request(ORIGIN, {method: 'POST', body: typeof body === 'string' ? body : JSON.stringify(body)}), {}, s);
  const [msg] = await run({text: '  hello\r\nthere  '});
  assert.deepEqual({channel: msg.channel, from: msg.from, text: msg.text, media: msg.media, mediaIds: msg.mediaIds, isGroup: msg.isGroup},
    {channel: 'web', from: session, text: 'hello\nthere', media: [], mediaIds: [], isGroup: false});
  assert.match(msg.providerId, /^web:[0-9a-f-]{36}$/);
  assert.equal(await run({text: 'hi'}, null), 'unauthorized');
  for (const [body, why] of [[{}, /empty/], [{text: '   '}, /empty/], [{text: 5}, /string/], [{text: 'x'.repeat(2001)}, /too long/],
    ['not json', /JSON/], [[1, 2], /JSON/], [{text: 'hi', media_ids: 'm1'}, /media_ids/], [{text: 'hi', media_ids: ['a', 'b', 'c', 'd', 'e']}, /media_ids/],
    [{text: 'hi', media_ids: ['bad id!']}, /media_ids/], [{text: 'x'.repeat(WEB_BODY_BYTES)}, /too large/]]) {
    await assert.rejects(run(body), why, JSON.stringify(body).slice(0, 40));
  }
});

// ---- POST /api/advisor/web/message -----------------------------------------------

dbTest('the first message issues the cookie, round-trips through the stub handler, and later messages reuse the cookie', async () => {
  const {sql, env} = setup();
  const {value: first} = await quiet(() => message(env, {text: 'Where are the rockfish?'}));
  assert.equal(first.status, 200);
  assert.equal(first.headers.get('Cache-Control'), 'no-store');
  const cookie = cookieOf(first);
  assert.match(first.headers.get('Set-Cookie'), /^sc_adv=[\w-]{43}; Max-Age=7776000; Path=\/; Secure; HttpOnly; SameSite=Lax$/);
  const data = await first.json();
  assert.equal(data.replies.length, 1);
  assert.deepEqual({...data.replies[0], id: 'x'}, {id: 'x', text: WARM_UP_TEXT, links: [], media: []});
  assert.match(data.replies[0].id, /^[0-9a-f]{32}$/);
  assert.deepEqual(data.contact, {language: 'en', linked: false});

  const contacts = sql.prepare('SELECT * FROM advisor_contacts').all();
  assert.equal(contacts.length, 1);
  assert.deepEqual({web_session: contacts[0].web_session, phone_hash: contacts[0].phone_hash, channel: contacts[0].channel, source: contacts[0].source},
    {web_session: await sha256(cookie), phone_hash: null, channel: 'web', source: 'web'}, 'the cookie is stored hashed; first touch is the site');
  const rows = sql.prepare('SELECT direction,channel,body,status,provider_id,id,in_reply_to FROM advisor_messages ORDER BY created_at,direction').all();
  assert.deepEqual(rows.map(r => [r.direction, r.channel, r.body, r.status]), [['in', 'web', 'Where are the rockfish?', 'done'], ['out', 'web', WARM_UP_TEXT, 'sent']]);
  assert.equal(rows[1].id, data.replies[0].id, 'the reply id is the outbound row id');

  const {value: second} = await quiet(() => message(env, {text: 'And lingcod? [via qr]'}, cookie));
  assert.equal(second.status, 200);
  assert.equal(second.headers.get('Set-Cookie'), null, 'no new cookie once one is set');
  assert.equal((await second.json()).replies[0].text, WARM_UP_TEXT);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_contacts').get().n, 1, 'same contact');
  assert.equal(sql.prepare("SELECT source FROM advisor_contacts").get().source, 'web', 'first touch kept');
  assert.equal(sql.prepare("SELECT COUNT(*) n FROM advisor_messages WHERE body='And lingcod?'").get().n, 1, 'marker stripped');

  // A malformed cookie is replaced by a fresh session rather than refused.
  const {value: third} = await quiet(() => message(env, {text: 'hi'}, 'bad'));
  assert.equal(third.status, 200); assert.ok(cookieOf(third)); assert.notEqual(cookieOf(third), cookie);
});

dbTest('a first message carrying a deep-link marker records that source instead of web', async () => {
  const {sql, env} = setup();
  await quiet(() => message(env, {text: 'Hi SkipperCast [via ig]'}));
  assert.equal(sql.prepare('SELECT source FROM advisor_contacts').get().source, 'ig');
});

dbTest('a stopped web contact is stored but gets no reply from the stub handler', async () => {
  const {sql, env} = setup();
  const {value: first} = await quiet(() => message(env, {text: 'hi'}));
  const cookie = cookieOf(first);
  sql.prepare("UPDATE advisor_contacts SET status='stopped'").run();
  const {value: response} = await quiet(() => message(env, {text: 'still there?'}, cookie));
  assert.deepEqual((await response.json()).replies, []);
});

dbTest('media_ids must be this visitor\'s own unused stored images', async () => {
  const {sql, env} = setup();
  const {value: a} = await quiet(() => upload(env, jpeg(1)));
  assert.equal(a.status, 200);
  const alice = cookieOf(a), {media_id: aliceMedia} = await a.json();
  assert.match(aliceMedia, /^[\w-]{22}$/);
  const {value: b} = await quiet(() => upload(env, jpeg(2)));
  const bob = cookieOf(b), {media_id: bobMedia} = await b.json();
  assert.notEqual(alice, bob);

  const {value: stolen} = await quiet(() => message(env, {text: 'look', media_ids: [bobMedia]}, alice));
  assert.equal(stolen.status, 400); assert.deepEqual(await errorBody(stolen), {error: 'unknown media'});
  const {value: unknown} = await quiet(() => message(env, {text: 'look', media_ids: ['nope']}, alice));
  assert.equal(unknown.status, 400);
  assert.equal(sql.prepare("SELECT COUNT(*) n FROM advisor_messages WHERE direction='in'").get().n, 0, 'nothing stored on a refused message');

  const {value: ok} = await quiet(() => message(env, {text: '', media_ids: [aliceMedia]}, alice));
  assert.equal(ok.status, 200, 'a photo alone is a message');
  const row = sql.prepare("SELECT id,body,media_json FROM advisor_messages WHERE direction='in'").get();
  assert.deepEqual({body: row.body, media: JSON.parse(row.media_json)}, {body: null, media: [aliceMedia]});
  assert.equal(sql.prepare('SELECT message_id FROM advisor_media WHERE id=?').get(aliceMedia).message_id, row.id, 'attached to the message');
  const {value: reused} = await quiet(() => message(env, {text: 'again', media_ids: [aliceMedia]}, alice));
  assert.equal(reused.status, 400, 'a media id is used once');
  // A rejected upload cannot be referenced either.
  sql.prepare("UPDATE advisor_media SET publish_state='rejected' WHERE id=?").run(bobMedia);
  assert.equal((await quiet(() => message(env, {text: 'x', media_ids: [bobMedia]}, bob))).value.status, 400);
});

dbTest('the turn runs past 40 s: the answer is {replies: [], pending: true} and the late reply is not lost', async t => {
  const {sql, env} = setup();
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const saved = {...webChat};
  webChat.timeoutMs = 20;
  webChat.handler = async input => { await gate; return warmUpHandler(input); };
  t.after(() => { webChat.timeoutMs = saved.timeoutMs; delete webChat.handler; });
  const pending = [];
  const ctx = {waitUntil: p => pending.push(p), passThroughOnException() {}};
  const request = new Request(ORIGIN + '/api/advisor/web/message', {method: 'POST', body: JSON.stringify({text: 'slow one'}), headers: {Origin: ORIGIN, 'Content-Type': 'application/json'}});
  const {value: response} = await quiet(() => worker.fetch(request, {ASSETS, ...env}, ctx));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {replies: [], pending: true});
  assert.ok(cookieOf(response), 'the cookie is still issued');
  assert.equal(pending.length, 1, 'the turn continues under waitUntil');
  release();
  await quiet(() => Promise.all(pending));
  assert.deepEqual(sql.prepare("SELECT direction,status,error FROM advisor_messages ORDER BY direction").all().map(r => [r.direction, r.status, r.error]),
    [['in', 'done', null], ['out', 'failed', 'web-closed']], 'the reply after the answer is recorded, not delivered');
});

test('the timeout default is 40 s', () => { assert.equal(webChat.timeoutMs, 40000); assert.equal(webChat.handler, undefined); });

dbTest('hardening: the turn gets the client address hashed (ConsumerDeps.ipHash), the same for one address whatever the cookie, never the address itself', async t => {
  const {env} = setup();
  const seen = [];
  webChat.handler = async input => { seen.push(input.deps.ipHash); return warmUpHandler(input); };
  t.after(() => { delete webChat.handler; });
  const key = {...env, ADVISOR_PHONE_KEY: Buffer.alloc(32, 7).toString('base64')};
  await message(key, {text: 'one'}, null);
  await message(key, {text: 'two'}, null);
  await message(key, {text: 'three'}, null, {'cf-connecting-ip': '198.51.100.4'});
  assert.equal(seen.length, 3);
  assert.ok(seen.every(h => /^[0-9a-f]{32}$/.test(h)), 'hashed');
  assert.equal(seen[0], seen[1], 'two fresh cookies, one address, one key');
  assert.notEqual(seen[0], seen[2]);
  assert.ok(!seen.some(h => h.includes('203') || h.includes('198')));
});

dbTest('Origin, rate limit, dark switch and storage', async () => {
  const {env} = setup();
  const foreign = await message(env, {text: 'hi'}, null, {Origin: 'https://evil.example'});
  assert.equal(foreign.status, 400); assert.deepEqual(await errorBody(foreign), {error: 'origin rejected'});
  const none = await worker.fetch(new Request(ORIGIN + '/api/advisor/web/message', {method: 'POST', body: '{"text":"hi"}'}), {ASSETS, ...env});
  assert.equal(none.status, 400, 'no Origin header');
  const localDev = await quiet(() => message({...env, EXTRA_ORIGINS: 'http://localhost:8787'}, {text: 'hi'}, null, {Origin: 'http://localhost:8787'}));
  assert.equal(localDev.value.status, 200, 'EXTRA_ORIGINS applies, as for private mutations');

  const keys = [];
  const limiter = {async limit({key}) { keys.push(key); return {success: false}; }};
  for (const path of ['/api/advisor/web/message', '/api/advisor/web/upload']) {
    const limited = await call(path, {...env, PUBLIC_LIMITER: limiter}, {body: '{"text":"hi"}'});
    assert.equal(limited.status, 429, path); assert.equal(limited.headers.get('Retry-After'), '60');
  }
  assert.deepEqual(keys, ['advisor-web:203.0.113.9', 'advisor-web:203.0.113.9']);

  for (const path of ['/api/advisor/web/message', '/api/advisor/web/upload']) {
    assert.equal((await call(path, {DB: env.DB}, {body: '{"text":"hi"}'})).status, 404, `${path} dark`);
  }
  const noDb = await message({...ON}, {text: 'hi'});
  assert.equal(noDb.status, 503);
});

// ---- POST /api/advisor/web/upload --------------------------------------------------

dbTest('upload: images only, at most 8 MB, stored stripped and private for this visitor', async () => {
  const {sql, env} = setup();
  const {value: ok} = await quiet(() => upload(env, jpeg()));
  assert.equal(ok.status, 200);
  const cookie = cookieOf(ok), {media_id: id} = await ok.json();
  const row = sql.prepare('SELECT m.*, c.web_session FROM advisor_media m JOIN advisor_contacts c ON c.id=m.contact_id WHERE m.id=?').get(id);
  assert.deepEqual({kind: row.kind, mime: row.mime, stripped: row.exif_stripped, state: row.publish_state, message: row.message_id, session: row.web_session},
    {kind: 'image', mime: 'image/jpeg', stripped: 1, state: 'private', message: null, session: await sha256(cookie)});
  assert.ok(env.ADVISOR_MEDIA.objects.has(row.r2_key));

  // The same cookie keeps the same contact.
  const {value: again} = await quiet(() => upload(env, jpeg(9), cookie));
  assert.equal(again.headers.get('Set-Cookie'), null);
  assert.equal(sql.prepare('SELECT COUNT(DISTINCT contact_id) n FROM advisor_media').get().n, 1);

  // Not an image: a video, an HTML file named .jpg.
  const mp4 = Buffer.concat([Buffer.from([0, 0, 0, 24]), Buffer.from('ftypisom'), Buffer.alloc(200)]);
  for (const [content, name, type] of [[mp4, 'clip.mp4', 'video/mp4'], [Buffer.from('<html><script>alert(1)</script></html>'.padEnd(100)), 'x.jpg', 'image/jpeg']]) {
    const {value: refused} = await quiet(() => upload(env, content, cookie, {name, type}));
    assert.equal(refused.status, 415, name); assert.deepEqual(await errorBody(refused), {error: CHAT_COPY.photoType});
  }
  // Over 8 MB: refused by the stream cap (a FormData body declares no length here), and up front by a declared length.
  const big = Buffer.concat([jpeg().subarray(0, 20), Buffer.alloc(WEB_UPLOAD_BYTES + 10)]);
  const {value: tooBig} = await quiet(() => upload(env, big, cookie));
  assert.equal(tooBig.status, 413); assert.deepEqual(await errorBody(tooBig), {error: 'That photo is too large.'});
  const declared = await call('/api/advisor/web/upload', env, {body: 'x', headers: {'Content-Length': String(WEB_UPLOAD_BYTES + 70 * 1024), 'Content-Type': 'multipart/form-data; boundary=b', Cookie: `sc_adv=${cookie}`}});
  assert.equal(declared.status, 413, 'declared length over the cap: refused before reading');
  const multipart = new Response(form(big)), type = multipart.headers.get('content-type'), body = new Uint8Array(await multipart.arrayBuffer());
  const chunked = new ReadableStream({start(c) { for (let i = 0; i < body.length; i += 1 << 20) c.enqueue(body.subarray(i, i + (1 << 20))); c.close(); }});
  const {value: streamed} = await quiet(() => worker.fetch(new Request(ORIGIN + '/api/advisor/web/upload', {method: 'POST', body: chunked, duplex: 'half', headers: {Origin: ORIGIN, 'Content-Type': type, Cookie: `sc_adv=${cookie}`}}), {ASSETS, ...env}));
  assert.equal(streamed.status, 413, 'no content-length: the stream cap applies');
  assert.equal(sql.prepare("SELECT COUNT(*) n FROM advisor_media WHERE publish_state='rejected'").get().n, 4, 'refused uploads read past the first bytes are kept as rejected rows');
  assert.equal(env.ADVISOR_MEDIA.objects.size, 2, 'nothing refused reached the bucket');
  assert.equal(WEB_UPLOAD_BYTES, CHAT_MAX_PHOTO_BYTES, 'the island checks the same cap');

  const {value: noFile} = await quiet(() => call('/api/advisor/web/upload', env, {body: 'x', headers: {'Content-Type': 'text/plain', Cookie: `sc_adv=${cookie}`}}));
  assert.equal(noFile.status, 400);
  assert.equal((await upload({...ON, DB: env.DB}, jpeg(), cookie)).status, 503, 'no bucket');
});

dbTest('a blocked web visitor\'s upload answers 404', async () => {
  const {sql, env} = setup();
  const {value: ok} = await quiet(() => upload(env, jpeg()));
  const cookie = cookieOf(ok);
  sql.prepare("UPDATE advisor_contacts SET status='blocked'").run();
  assert.equal((await quiet(() => upload(env, jpeg(3), cookie))).value.status, 404);
});

test('/chat.html is dark with the advisor and served as its page shell when on', async () => {
  globalThis.SHELLS['/chat.html'] = '/chat.0123456789.html';
  const assets = {fetch: async request => new Response(new URL(request.url).pathname, {status: 200})};
  const off = await worker.fetch(new Request(ORIGIN + '/chat.html'), {ASSETS: assets});
  assert.equal(off.status, 404); assert.deepEqual(await errorBody(off), {error: 'Not found'});
  const on = await worker.fetch(new Request(ORIGIN + '/chat.html'), {ASSETS: assets, ...ON});
  assert.equal(on.status, 200); assert.equal(await on.text(), '/chat.0123456789');
  assert.equal(on.headers.get('Cache-Control'), 'no-store');
});

// FE-55: the v2 masthead shows its chat entry only when a cookieless HEAD of /chat.html is ok.
test('HEAD and GET /chat.html answer 404 with the advisor off, so the masthead entry stays hidden', async () => {
  globalThis.SHELLS['/chat.html'] = '/chat.0123456789.html';
  const assets = {fetch: async request => new Response(request.method === 'HEAD' ? null : new URL(request.url).pathname, {status: 200})};
  for (const method of ['HEAD', 'GET']) {
    for (const env of [{}, {TEXT_ADVISOR_ENABLED: 'false'}, {TEXT_ADVISOR_ENABLED: ''}]) {
      const off = await worker.fetch(new Request(ORIGIN + '/chat.html', {method}), {ASSETS: assets, ...env});
      assert.equal(off.status, 404, `${method} with ${JSON.stringify(env)}`);
    }
    const on = await worker.fetch(new Request(ORIGIN + '/chat.html', {method}), {ASSETS: assets, ...ON});
    assert.equal(on.ok, true, `${method} with the advisor on`);
  }
});

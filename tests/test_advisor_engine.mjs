// Text Advisor engine (server/advisor/engine.ts; docs/plans/text-advisor/04-advisor-engine.md):
// stage 0 guards and stage 1 commands (table-driven, no fetcher), language
// detection (en/es table and the two-in-a-row switch), stage 2 flows (upload
// link, media-only, the text admin fallback, the web phone link), the model
// turn against recorded Messages API responses (tests/fixtures/advisor/engine/*.json:
// the six few-shots, rules_without_tool, tool_loop, pause_turn, HTTP 529), the
// post-processing helpers, the consumer's new appliers (STOP/START, forget,
// export and its route, send_file, notifyAdmin) and the golden conversations
// 2, 3 and 6-9 of 11 (tests/fixtures/advisor/engine/conversations/*.json). Offline:
// real migrations in node:sqlite, a memory R2, a fake fetcher.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {memoryBucket} from './_advisor_r2.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const engine = await import('../server/advisor/engine.ts');
const {runTurn, engineHandler, rulesGuard, statesRuleNumber, stripMarkdown, capReply, buildMessages, STAGE_TWO_FLOWS, MAX_TOOL_ROUNDS, MAX_TOKENS, TEMPERATURE} = engine;
const {detectLanguage, chooseLanguage, parseCommand, COMMANDS} = await import('../server/advisor/intents.ts');
const {consumeAdvisor, runInline, notifyAdmin, ADVISOR_QUEUE_NAME} = await import('../server/advisor/consumer.ts');
const {t} = await import('../server/advisor/strings.ts');
const {deriveKeys, phoneHash, encryptPhone, reviewId} = await import('../server/advisor/contacts.ts');
const {sha256, outboundId} = await import('../server/advisor/ids.ts');
const {verifyExportToken, mintExportToken, exportKey} = await import('../server/advisor/exports.ts');
const {linkKey} = await import('../server/advisor/tools/offer_text_link.ts');
const {default: worker} = await import('../server/index.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-03T17:00:00Z');   // Saturday 10:00 in Morro Bay
const ON = {TEXT_ADVISOR_ENABLED: 'true'};
const KEY = Buffer.alloc(32, 7).toString('base64');
const ADMIN_ID = 'admin-contact-1';
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const iso = ms => new Date(ms).toISOString();

// ---- fixtures ------------------------------------------------------------------------

/** A database with one contact. */
function setup({contact = {}, env = {}} = {}) {
  const {sql, db} = advisorDatabase();
  const c = {id: 'c1', phone_hash: 'h1', phone_enc: 'ENC', web_session: null, channel: 'imessage', role: 'angler', language: 'en', status: 'active', home_port: null, boat_id: null, display_name: null, ...contact};
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,web_session,channel,role,language,status,home_port,boat_id,display_name,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run(c.id, c.phone_hash, c.phone_enc, c.web_session, c.channel, c.role, c.language, c.status, c.home_port, c.boat_id, c.display_name, iso(T0), iso(T0), iso(T0));
  return {sql, db, env: {...ON, DB: db, ADVISOR_NUMBER: '+15555550199', ...env}};
}
let seq = 0;
/** Store an inbound message for a contact; returns the row. `ago` minutes before T0. */
function inbound(sql, body, {contact = 'c1', ago = 0, media = null, intent = null, status = 'processing', channel} = {}) {
  const id = `in${++seq}`, ch = channel ?? sql.prepare('SELECT channel FROM advisor_contacts WHERE id=?').get(contact)?.channel ?? 'imessage';
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,media_json,intent,status,created_at) VALUES(?,?,'in',?,?,?,?,?,?,?)`)
    .run(id, contact, ch, `p-${id}`, body, media ? JSON.stringify(media) : null, intent, status, iso(T0 - ago * 60000));
  return sql.prepare('SELECT * FROM advisor_messages WHERE id=?').get(id);
}
const contactRow = (sql, id = 'c1') => sql.prepare('SELECT * FROM advisor_contacts WHERE id=?').get(id);
const texts = result => result.actions.filter(a => a.type === 'send_text').map(a => a.text);
/** Mark the contact as seen before (an earlier message), so no welcome is added. */
const seen = sql => inbound(sql, 'earlier', {ago: 60 * 30, status: 'done'});

/** A fake Messages API: replays `responses` in order and records every request body. */
function fakeApi(responses) {
  const requests = [], queue = [...responses];
  return {requests, remaining: () => queue.length, async fetcher(url, init) {
    assert.equal(url, 'https://api.anthropic.com/v1/messages');
    assert.equal(init.headers['anthropic-version'], '2023-06-01');
    requests.push(JSON.parse(init.body));
    const next = queue.shift();
    if (!next) throw Error('fake API: no response left');
    return new Response(JSON.stringify(next.body), {status: next.status, headers: {'content-type': 'application/json'}});
  }};
}
const engineFixtures = readdirSync(new URL('./fixtures/advisor/engine/', import.meta.url)).filter(f => f.endsWith('.json')).sort();
const engineFixture = name => read(`./fixtures/advisor/engine/${name}.json`);
// The data tools (TA-E2) read the regional feeds; the engine tests serve the committed
// fixtures (tests/fixtures/feeds/) offline, with the daily feed's NWS alert moved to
// T0's day so the planning case has an advisory in its window.
const ALERT_DAY = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles'}).format(new Date(T0));
function fixtureFeeds() {
  const daily = read('./fixtures/feeds/daily-latest.json'), intel = read('./fixtures/feeds/intelligence.json');
  for (const source of Object.values(daily.sources)) for (const a of source?.data?.alerts ?? [])
    for (const k of ['sent', 'effective', 'onset', 'expires', 'ends']) if (typeof a[k] === 'string') a[k] = ALERT_DAY + a[k].slice(10);
  return async url => /intelligence\.json$/.test(url) ? intel : /latest\.json$/.test(url) ? daily : Promise.reject(Error(`no fixture for ${url}`));
}
const run = (env, contact, message, deps = {}) => runTurn({env, contact, message, now: T0, deps: {sleep: async () => {}, clock: () => T0, feeds: fixtureFeeds(), ...deps}});

// ---- stage 0 --------------------------------------------------------------------------

dbTest('stage 0: soft switch, blocked and stopped contacts get nothing and no model call', async () => {
  const api = fakeApi([]);
  const cases = [
    {name: 'replies off', env: {ADVISOR_REPLIES_ENABLED: 'false'}, contact: {}, intent: 'held'},
    {name: 'blocked', env: {}, contact: {status: 'blocked'}, intent: 'blocked'},
    {name: 'stopped', env: {}, contact: {status: 'stopped'}, intent: 'stopped'},
    {name: 'stopped, HELP', env: {}, contact: {status: 'stopped'}, intent: 'stopped', body: 'HELP'},
  ];
  for (const c of cases) {
    const {sql, env} = setup({contact: c.contact, env: {ANTHROPIC_API_KEY: 'k', ...c.env}});
    const result = await quiet(() => run(env, contactRow(sql), inbound(sql, c.body ?? 'what is biting'), {fetcher: api.fetcher}));
    assert.deepEqual(result.value, {actions: [], intent: c.intent}, c.name);
  }
  assert.equal(api.requests.length, 0);
});

dbTest('stage 0: the daily message cap answers once a day and keeps the counter on the contact; STOP and HELP still work', async () => {
  const {sql, env} = setup({env: {ADVISOR_DAILY_MESSAGES_PER_CONTACT: '3', ANTHROPIC_API_KEY: 'k'}, contact: {home_port: 'morro-bay'}});
  for (let i = 0; i < 3; i++) inbound(sql, `q${i}`, {ago: 10 + i, status: 'done'});
  inbound(sql, 'yesterday', {ago: 60 * 20, status: 'done'});   // 2026-10-02 21:00 local: not today
  const first = await run(env, contactRow(sql), inbound(sql, 'one more'));
  assert.equal(first.intent, 'capped');
  assert.deepEqual(texts(first), ["You've hit today's limit with me. Back tomorrow, or see https://skippercast.com/ports/morro-bay?s=txt"]);
  assert.deepEqual([contactRow(sql).messages_today, contactRow(sql).messages_day], [4, '2026-10-03']);
  const second = await run(env, contactRow(sql), inbound(sql, 'and another'));
  assert.deepEqual(second, {actions: [], intent: 'capped'}, 'the capped reply goes out once a day');
  assert.equal((await run(env, contactRow(sql), inbound(sql, 'HELP'))).intent, 'help', 'HELP works past the cap');
  assert.equal((await run(env, contactRow(sql), inbound(sql, 'stop'))).intent, 'stop', 'STOP works past the cap');
});

dbTest('stage 3 caps: per-contact LLM cap answers once; the global cap answers "swamped"; neither calls the model', async () => {
  const api = fakeApi([]);
  const one = setup({env: {ANTHROPIC_API_KEY: 'k', ADVISOR_DAILY_LLM_PER_CONTACT: '0'}});
  seen(one.sql);
  const capped = await run(one.env, contactRow(one.sql), inbound(one.sql, 'what is biting'), {fetcher: api.fetcher});
  assert.equal(capped.intent, 'capped'); assert.equal(texts(capped).length, 1);
  assert.deepEqual((await run(one.env, contactRow(one.sql), inbound(one.sql, 'again?'), {fetcher: api.fetcher})).actions, []);
  const all = setup({env: {ANTHROPIC_API_KEY: 'k', ADVISOR_GLOBAL_DAILY_LLM: '0'}});
  seen(all.sql);
  const swamped = (await quiet(() => run(all.env, contactRow(all.sql), inbound(all.sql, 'what is biting'), {fetcher: api.fetcher}))).value;
  assert.equal(swamped.intent, 'global_cap');
  assert.deepEqual(texts(swamped), ["I'm swamped right now. Try again in a bit, or see https://skippercast.com/?s=txt"]);
  assert.equal(api.requests.length, 0);
  const counter = all.sql.prepare("SELECT count FROM request_limits WHERE id LIKE 'global:advisor-llm:%'").get();
  assert.equal(counter.count, 1, 'the request_limits UPSERT counted the attempt');
});

// ---- stage 1 ----------------------------------------------------------------------------

test('commands table: every 04 word in en and es, exact match after trim and lower-case', () => {
  const table = {
    stop: ['stop', 'STOP', ' Stop. ', 'stopall', 'unsubscribe', 'cancel', 'end', 'quit', 'alto', 'parar'],
    start: ['start', 'unstop', 'yes', 'empezar'],
    help: ['help', 'HELP', 'ayuda', '?'],
    forget: ['forget me', 'Forget  me', 'delete my data', 'olvídame', 'borra mis datos'],
    delete: ['delete', 'DELETE', 'borrar'],
    export: ['send me my data', 'export', 'mis datos'],
    upload_link: ['send me a link', 'link'],
  };
  for (const [command, words] of Object.entries(table)) for (const w of words) assert.equal(parseCommand(w), command, w);
  for (const w of ['stop please', 'help me rig for lingcod', 'stopping by', 'yes I want to go Saturday', '', 'end of the season']) assert.equal(parseCommand(w), null, w);
  assert.ok(Object.keys(COMMANDS).length >= 25);
});

dbTest('STOP, START, HELP replies and actions (HELP is the runbook wording, word for word)', async () => {
  const runbook = readFileSync(new URL('../docs/operations/runbooks/advisor-port-to-twilio.md', import.meta.url), 'utf8');
  const help = /### HELP and STOP wording[\s\S]*?\n> (.+)\n/.exec(runbook)[1];
  const {sql, env} = setup();
  seen(sql);
  const h = await run(env, contactRow(sql), inbound(sql, 'help'));
  assert.deepEqual(h, {actions: [{type: 'send_text', text: help}], intent: 'help'});
  assert.equal(t('en', 'help'), help);
  const s = await run(env, contactRow(sql), inbound(sql, 'STOP'));
  assert.deepEqual(s, {actions: [{type: 'send_text', text: "Done. You won't hear from me unless you text START."}, {type: 'set_status', status: 'stopped'}], intent: 'stop'});
  const es = await run(env, contactRow(sql), inbound(sql, 'alto'));
  assert.equal(texts(es)[0], 'Listo. No sabrás de mí a menos que escribas START.', 'a Spanish command answers in Spanish');
  sql.prepare("UPDATE advisor_contacts SET status='stopped'").run();
  const start = await run(env, contactRow(sql), inbound(sql, 'START'));
  assert.equal(start.intent, 'start');
  assert.deepEqual(start.actions[0], {type: 'set_status', status: 'active'});
  assert.match(texts(start)[0], /Msg & data rates may apply\. Reply HELP for help, STOP to opt out\./);
  // On Twilio SMS, Twilio confirms STOP itself and refuses ours (21610): only the status changes.
  const tw = setup({contact: {channel: 'sms'}, env: {ADVISOR_CHANNEL: 'twilio'}});
  assert.deepEqual((await run(tw.env, contactRow(tw.sql), inbound(tw.sql, 'stop'))).actions, [{type: 'set_status', status: 'stopped'}]);
  // "yes" is START only for a stopped contact; otherwise it is an ordinary message.
  const active = setup();
  seen(active.sql);
  assert.equal((await run(active.env, contactRow(active.sql), inbound(active.sql, 'yes'))).intent, 'unconfigured');
});

dbTest('forget me asks; DELETE within a day runs forget; DELETE out of the blue is just a message', async () => {
  const {sql, env} = setup();
  seen(sql);
  const ask = await run(env, contactRow(sql), inbound(sql, 'forget me', {ago: 5}));
  assert.deepEqual(ask, {actions: [{type: 'send_text', text: "Reply DELETE to erase everything I have about this number. This can't be undone."}], intent: 'forget.ask'});
  sql.prepare("UPDATE advisor_messages SET intent='forget.ask' WHERE body='forget me'").run();
  assert.deepEqual(await run(env, contactRow(sql), inbound(sql, 'DELETE')), {actions: [{type: 'forget', language: 'en'}], intent: 'forget'});
  const other = setup();
  seen(other.sql);
  assert.notEqual((await run(other.env, contactRow(other.sql), inbound(other.sql, 'delete'))).intent, 'forget');
  assert.deepEqual(await run(env, contactRow(sql), inbound(sql, 'mis datos')), {actions: [{type: 'export', language: 'es'}], intent: 'export'});
});

// ---- language --------------------------------------------------------------------------

test('detectLanguage: the stopword table', () => {
  const table = [
    ['¿Qué está picando en Morro Bay hoy?', 'es'],
    ['hola, quiero saber si hay rocote para el sábado', 'es'],
    ['¿Cómo está el mar mañana?', 'es'],
    ['Buenos días, ¿vale la pena salir por lingcod con este viento?', 'es'],
    ["What's biting out of Morro Bay?", 'en'],
    ['Is Saturday worth going for rockfish?', 'en'],
    ['how should I rig for lingcod from a kayak', 'en'],
    ['lingcod', null],
    ['ok', null],
    ['Morro Bay rockfish', null],
    ['', null],
  ];
  for (const [text, expected] of table) assert.equal(detectLanguage(text), expected, text);
});

test('chooseLanguage: one message switches the reply; two in a row switch the stored language', () => {
  assert.deepEqual(chooseLanguage('en', 'es', null), {reply: 'es', store: null});
  assert.deepEqual(chooseLanguage('en', 'es', 'en'), {reply: 'es', store: null});
  assert.deepEqual(chooseLanguage('en', 'es', 'es'), {reply: 'es', store: 'es'});
  assert.deepEqual(chooseLanguage('es', null, 'en'), {reply: 'es', store: null}, 'undetected and media-only keep the stored language');
  assert.deepEqual(chooseLanguage('es', 'es', 'en'), {reply: 'es', store: null});
});

dbTest('a second Spanish message in a row stores es', async () => {
  const {sql, env} = setup();
  inbound(sql, '¿Qué está picando en Morro Bay hoy?', {ago: 3, status: 'done'});
  const result = await quiet(() => run(env, contactRow(sql), inbound(sql, '¿Y cómo está el mar para el sábado?')));
  assert.deepEqual(result.value.actions.find(a => a.type === 'contact_update'), {type: 'contact_update', fields: {language: 'es'}});
  assert.equal(texts(result.value).at(-1), 'SkipperCast se está preparando. Vuelve a escribir pronto.');
});

// ---- stage 2 ----------------------------------------------------------------------------

dbTest('stage 2: the upload link, media-only messages, and the welcome for a new contact', async () => {
  const {sql, env} = setup({env: {ADVISOR_PHONE_KEY: KEY}});
  const first = await run(env, contactRow(sql), inbound(sql, 'send me a link'));
  assert.equal(first.intent, 'upload_link');
  const [welcome, card, link] = first.actions;
  assert.match(welcome.text, /^SkipperCast here\. .*Msg & data rates may apply\. Reply HELP for help, STOP to opt out\.$/);
  assert.equal(card.type, 'send_file', 'iMessage gets the contact card as a file');
  assert.equal(card.name, 'SkipperCast.vcf'); assert.equal(card.fallbackUrl, 'https://skippercast.com/contact.vcf');
  assert.match(Buffer.from(card.inlineBytes, 'base64').toString(), /^BEGIN:VCARD\r\n/);
  assert.match(link.text, /^Send full-size photos or videos here, good for 24 hours: https:\/\/skippercast\.com\/u\/[\w-]+$/);
  const media = await run(env, contactRow(sql), inbound(sql, null, {media: ['m1']}));
  assert.deepEqual(media, {actions: [{type: 'send_text', text: t('en', 'media_ack')}], intent: 'media'}, 'only the acknowledgement; the welcome went once');
  const sms = setup({contact: {channel: 'sms'}});
  const smsFirst = await run(sms.env, contactRow(sms.sql), inbound(sms.sql, null, {media: ['m1']}));
  assert.deepEqual(smsFirst.actions[1], {type: 'send_text', text: 'Save my number: https://skippercast.com/contact.vcf'}, 'SMS gets the card link');
});

dbTest('stage 2 extension point: a registered flow runs before the model', async t2 => {
  const {sql, env} = setup();
  seen(sql);
  // TA-I1's skipper flow, TA-I2's report flow and TA-I3's angler flow are registered at import; the test flow goes after them and only it is removed.
  assert.deepEqual(STAGE_TWO_FLOWS.map(f => f.name), ['skipper', 'reports', 'anglers']);
  STAGE_TWO_FLOWS.push({name: 'test', run: async f => f.text === 'y' ? {actions: [{type: 'send_text', text: 'published'}], intent: 'report.confirm'} : null});
  t2.after(() => { STAGE_TWO_FLOWS.splice(STAGE_TWO_FLOWS.findIndex(f => f.name === 'test'), 1); });
  assert.deepEqual(await run(env, contactRow(sql), inbound(sql, 'y')), {actions: [{type: 'send_text', text: 'published'}], intent: 'report.confirm'});
  assert.equal((await quiet(() => run(env, contactRow(sql), inbound(sql, 'nonsense')))).value.intent, 'unconfigured', 'anything else falls through');
});

dbTest('text admin fallback: only the configured admin-test contact, only ok/no <code>, only skipper and media reviews', async () => {
  const {sql, env} = setup({contact: {id: ADMIN_ID, role: 'admin-test'}, env: {ADVISOR_ADMIN_CONTACT_ID: ADMIN_ID}});
  seen(sql);
  const at = iso(T0);
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at) VALUES('b1','example-boat','Example Boat','morro-bay','morro-bay','pending',?,?)`).run(at, at);
  const skipper = await reviewId('skipper', 'b1', 'new_skipper'), conversation = await reviewId('conversation', 'in1', 'refused');
  for (const [id, kind, ref, reason] of [[skipper, 'skipper', 'b1', 'new_skipper'], [conversation, 'conversation', 'in1', 'refused']])
    sql.prepare(`INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,?,?,?,'open',?)`).run(id, kind, ref, reason, at);
  const admin = contactRow(sql, ADMIN_ID);
  const ok = await run(env, admin, inbound(sql, `OK ${skipper.slice(0, 6)}`, {contact: ADMIN_ID}));
  assert.deepEqual(ok.actions[0], {type: 'admin_review', reviewId: skipper, decision: 'approved'});
  assert.equal(ok.intent, 'admin.approved');
  const notReachable = await run(env, admin, inbound(sql, `ok ${conversation.slice(0, 6)}`, {contact: ADMIN_ID}));
  assert.equal(notReachable.intent, 'admin.not_found', 'a conversation review is not reachable by text');
  // Anyone else typing the same thing is an ordinary message.
  const other = setup({env: {ADVISOR_ADMIN_CONTACT_ID: ADMIN_ID}});
  seen(other.sql);
  assert.equal((await quiet(() => run(other.env, contactRow(other.sql), inbound(other.sql, `ok ${skipper.slice(0, 6)}`)))).value.intent, 'unconfigured');
  const wrongRole = setup({contact: {id: ADMIN_ID, role: 'angler'}, env: {ADVISOR_ADMIN_CONTACT_ID: ADMIN_ID}});
  seen(wrongRole.sql);
  assert.notEqual((await quiet(() => run(wrongRole.env, contactRow(wrongRole.sql, ADMIN_ID), inbound(wrongRole.sql, `ok ${skipper.slice(0, 6)}`, {contact: ADMIN_ID})))).value.intent, 'admin.approved');

  // The consumer applies it: the boat is verified, the review decided.
  const ch = recorder();
  const msg = inbound(sql, `ok ${skipper.slice(0, 6)}`, {contact: ADMIN_ID, status: 'queued'});
  await quiet(() => consumeAdvisor(batchOf(msg.id), env, {channelFor: () => ch, handler: engineHandler, now: () => T0}));
  assert.deepEqual({...sql.prepare("SELECT status,verified_at FROM advisor_boats WHERE id='b1'").get()}, {status: 'verified', verified_at: at});
  assert.equal(sql.prepare('SELECT status FROM advisor_reviews WHERE id=?').get(skipper).status, 'approved');
  assert.match(ch.sent.at(-1).text, /^Done: approved skipper [0-9a-f]{6}\.$/);
});

dbTest('notifyAdmin texts the admin-test contact for new skipper and media reviews only, once per review', async () => {
  const {sql, db, env} = setup({contact: {id: ADMIN_ID, role: 'admin-test'}, env: {ADVISOR_ADMIN_CONTACT_ID: ADMIN_ID}});
  const angler = 'c2', at = iso(T0);
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)`).run(angler, 'h2', 'ENC2', 'imessage', at, at, at);
  const msg = inbound(sql, 'photo', {contact: angler, status: 'queued'});
  const ch = recorder();
  const handler = async () => ({actions: [{type: 'review_open', kind: 'media', refId: 'm1', reason: 'angler_photo'}, {type: 'review_open', kind: 'conversation', refId: msg.id, reason: 'refused'}], intent: 'test'});
  // The admin's text goes through the admin's own channel (channelFor), never the turn's channel (a web collector).
  await quiet(() => consumeAdvisor(batchOf(msg.id), env, {channelFor: () => ch, handler, now: () => T0}));
  const code = (await reviewId('media', 'm1', 'angler_photo')).slice(0, 6);
  assert.deepEqual(ch.sent.map(m => m.text), [`New media review (angler_photo). Reply OK ${code} to approve or NO ${code} to reject.`]);
  assert.equal(await notifyAdmin({...env, ADVISOR_ADMIN_CONTACT_ID: undefined}, {id: 'x'.repeat(32), kind: 'media', reason: 'r'}), false);
  assert.equal(await notifyAdmin(env, {id: 'y'.repeat(32), kind: 'post', reason: 'r'}), false);
  void db;
});

// ---- stage 3: recorded model turns -------------------------------------------------------

test('fixtures: every recorded case is complete', () => {
  const required = ['first-contact', 'whats-biting', 'trip-planning-advisory', 'fish-id-rules', 'rig-question', 'refusal', 'rules-without-tool', 'tool-loop', 'pause-turn', 'http-529'];
  const names = engineFixtures.map(f => f.replace(/\.json$/, ''));
  for (const name of required) assert.ok(names.includes(name), name);
  for (const name of names) { const f = engineFixture(name); assert.ok(f._source && f.description && f.message !== undefined && f.exchanges.length && f.expect, name); }
});

for (const file of engineFixtures) {
  const name = file.replace(/\.json$/, '');
  dbTest(`model turn: ${name}`, async () => {
    const f = engineFixture(name);
    const {sql, env} = setup({env: {ANTHROPIC_API_KEY: 'k', ADVISOR_PHONE_KEY: KEY}});
    if (!f.contact?.new) seen(sql);
    const api = fakeApi(f.exchanges.map(e => e.response));
    const message = inbound(sql, f.message, {media: f.media ? ['m-fixture'] : null});
    const attempt = quiet(() => run(env, contactRow(sql), message, {fetcher: api.fetcher}));
    if (f.expect.throws) { await assert.rejects(attempt, new RegExp(f.expect.throws)); assert.equal(api.requests.length, 2, 'one retry'); return; }
    const {value: result} = await attempt;
    assert.equal(api.remaining(), 0, 'every recorded response was used');
    // Request shape (04 § stage 3).
    for (const request of api.requests) {
      assert.equal(request.max_tokens, MAX_TOKENS); assert.equal(request.temperature, TEMPERATURE); assert.equal(request.model, 'claude-sonnet-5');
      assert.deepEqual(request.system[0].cache_control, {type: 'ephemeral'}, 'the system prompt is cached');
      assert.match(request.system[0].text, /^You are SkipperCast/);
      assert.match(request.system[1].text, /^CONTACT BRIEF/); assert.equal(request.system[1].cache_control, undefined);
      assert.deepEqual(request.tools.at(-1).cache_control, {type: 'ephemeral'}, 'the tools are cached');
      assert.equal(request.tools.filter(t => t.cache_control).length, 1);
      assert.equal(request.messages[0].role, 'user');
    }
    f.exchanges.forEach((exchange, i) => {
      const want = exchange.request, got = api.requests[i];
      if (!want) return;
      const lastUser = [...got.messages].reverse().find(m => m.role === 'user');
      const lastAssistant = [...got.messages].reverse().find(m => m.role === 'assistant');
      const asText = c => typeof c === 'string' ? c : JSON.stringify(c);
      if (want.last_user_contains) assert.match(asText(lastUser.content), new RegExp(want.last_user_contains.replace(/[[\]]/g, '\\$&')));
      if (want.last_assistant_contains) assert.ok(asText(lastAssistant.content).includes(want.last_assistant_contains));
      for (const tool of want.tools_include ?? []) assert.ok(got.tools.some(t => t.name === tool), tool);
      for (const tool of want.tools_exclude ?? []) assert.ok(!got.tools.some(t => t.name === tool), tool);
      if (want.tool_result_for) {
        const block = lastUser.content.find(b => b.type === 'tool_result' && b.tool_use_id === want.tool_result_for);
        assert.ok(block, want.tool_result_for);
        for (const part of [].concat(want.tool_result_contains ?? [])) assert.ok(block.content.includes(part), `${part} in ${want.tool_result_for}`);
      }
    });
    const e = f.expect, sent = texts(result);
    assert.equal(result.intent, e.intent);
    assert.equal(sent.length, e.texts + (f.contact?.new ? 0 : 0));
    const reply = sent.at(-1);
    for (const s of e.reply_contains ?? []) assert.ok(reply.includes(s), `${s} in ${reply}`);
    for (const s of e.reply_not_contains ?? []) assert.ok(!reply.includes(s), `${s} not in ${reply}`);
    if (e.reply_starts_with) assert.ok(reply.startsWith(e.reply_starts_with), `starts with ${e.reply_starts_with}: ${reply}`);
    for (const pattern of e.reply_not_matching ?? []) assert.doesNotMatch(reply, new RegExp(pattern));
    for (const s of e.first_text_contains ?? []) assert.ok(sent[0].includes(s), s);
    assert.ok(!/\{\{|\*\*/.test(reply), 'no placeholder or markdown survives');
    assert.ok(reply.length <= 480, 'three segments at most');
    if (e.actions) assert.deepEqual(result.actions.map(a => a.type), e.actions);
    const reviews = result.actions.filter(a => a.type === 'review_open');
    if (e.review) assert.deepEqual(reviews, [{type: 'review_open', kind: 'conversation', refId: message.id, reason: e.review}]);
    else assert.deepEqual(reviews, []);
    if (e.executed) assert.equal(api.requests.length, e.executed + 1, 'the fifth tool_use is not executed');
    assert.ok(result.usage.input_tokens > 0 && result.usage.output_tokens > 0);
    assert.equal(result.usage.turns, api.requests.length);
  });
}

dbTest('the tool loop executes at most four rounds', () => { assert.equal(MAX_TOOL_ROUNDS, 4); });

dbTest('messages: the last 12 turns or 48 hours, alternating, images as notes, failed outbound skipped', async () => {
  const {sql, env} = setup({env: {ANTHROPIC_API_KEY: 'k'}});
  inbound(sql, 'too old', {ago: 60 * 49, status: 'done'});
  for (let i = 14; i >= 1; i--) inbound(sql, `q${i}`, {ago: i * 2, status: 'done'});
  inbound(sql, null, {ago: 1, media: ['a', 'b'], status: 'done'});
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES('o1','c1','out','imessage','an answer','sent',?)`).run(iso(T0 - 90000));
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES('o2','c1','out','imessage','never sent','failed',?)`).run(iso(T0 - 80000));
  const api = fakeApi([{status: 200, body: {content: [{type: 'text', text: 'ok'}], stop_reason: 'end_turn', usage: {input_tokens: 1, output_tokens: 1}}}]);
  await quiet(() => run(env, contactRow(sql), inbound(sql, 'now'), {fetcher: api.fetcher}));
  const messages = api.requests[0].messages;
  const all = JSON.stringify(messages);
  assert.ok(!all.includes('too old') && !all.includes('never sent') && !all.includes('q14'));
  assert.ok(all.includes('[2 photos]') && all.includes('an answer'));
  assert.ok(messages.every((m, i) => i === 0 || m.role !== messages[i - 1].role), 'alternating');
  assert.equal(messages.at(-1).role, 'user'); assert.match(messages.at(-1).content, /now$/);
  assert.deepEqual(buildMessages([], 'hi'), [{role: 'user', content: 'hi'}]);
});

dbTest('tools are filtered by role: anglers never see skipper tools; offer_text_link only on the web', async () => {
  const names = async contact => {
    const {sql, env} = setup({contact, env: {ANTHROPIC_API_KEY: 'k'}});
    seen(sql);
    const api = fakeApi([{status: 200, body: {content: [{type: 'text', text: 'ok'}], stop_reason: 'end_turn', usage: {}}}]);
    await quiet(() => run(env, contactRow(sql), inbound(sql, 'hello there'), {fetcher: api.fetcher}));
    return api.requests[0].tools.map(t => t.name);
  };
  const angler = await names({}), skipper = await names({role: 'skipper'}), web = await names({phone_hash: null, phone_enc: null, web_session: 'w'.repeat(64), channel: 'web'});
  assert.ok(!angler.includes('read_count_board') && !angler.includes('register_boat') === false && angler.includes('share_angler_photo'));
  assert.ok(skipper.includes('read_count_board') && skipper.includes('add_crew') && !skipper.includes('share_angler_photo'));
  assert.ok(web.includes('offer_text_link') && !angler.includes('offer_text_link'));
  for (const list of [angler, skipper, web]) assert.ok(!list.some(n => /verify|approve|publish|admin/.test(n)), 'no admin tools');
});

dbTest('the hard-stop signal aborts the model call', async () => {
  const {sql, env} = setup({env: {ANTHROPIC_API_KEY: 'k'}});
  seen(sql);
  const controller = new AbortController();
  const fetcher = (_url, init) => new Promise((_, reject) => init.signal.addEventListener('abort', () => reject(init.signal.reason)));
  const pending = quiet(() => runTurn({env, contact: contactRow(sql), message: inbound(sql, 'slow?'), now: T0, deps: {fetcher}, signal: controller.signal}));
  controller.abort(Error('advisor turn timed out'));
  await assert.rejects(pending, /timed out/);
});

// ---- post-processing -------------------------------------------------------------------

test('rules guard: numbers next to inch, ", limit, bag, season, closed, open', () => {
  const fire = ['Keep them over 14 inch minimum.', 'Lingcod need to be 22 inches.', 'It has to be 22" long.', 'The bag limit is 10.', 'Limit of 2 per person.', '10 fish limit.',
    'The season opens April 1.', 'Closed until May 15.', 'It is open through Dec 31 this year.', 'La temporada abre el 1 de abril.', 'Mínimo 35 pulgadas.', '5 fish bag.'];
  const pass = ['Seas 5 ft at 9 s.', 'NW wind 10-15 kt.', '18 anglers had limits of rockfish Fri.', 'We had 9 lingcod.', 'Open water is calm.', 'Fish 40-120 ft.', 'Is Saturday worth it?'];
  for (const s of fire) assert.ok(statesRuleNumber(s), s);
  for (const s of pass) assert.ok(!statesRuleNumber(s), s);
  const guarded = rulesGuard('Lingcod run big this week. They must be 22 inches, 2 fish limit. Good luck!', 'en');
  assert.deepEqual(guarded, {text: 'Lingcod run big this week. Check the current CDFW rules for that: {{link:rules}} Good luck!', fired: true});
  assert.equal(rulesGuard('Seas 5 ft.', 'en').fired, false);
  assert.match(rulesGuard('Tienen que medir 22 pulgadas.', 'es').text, /^Revisa las reglas vigentes de CDFW/);
});

test('stripMarkdown and capReply', () => {
  assert.equal(stripMarkdown('**Lings:** use a *big* swimbait\n- one\n- two\n# Head\n[page](https://x.test)'), 'Lings: use a big swimbait\none\ntwo\nHead\npage');
  const link = 'https://skippercast.com/ports/morro-bay?s=txt';
  const long = Array.from({length: 20}, (_, i) => `Sentence number ${i} is here.`).join(' ') + ' ' + link;
  const capped = capReply(long, [link]);
  assert.ok(capped.length <= 480); assert.ok(capped.endsWith(link)); assert.match(capped, /^Sentence number 0/);
  assert.equal(capReply('short', []), 'short');
});

// ---- consumer appliers --------------------------------------------------------------------

function batchOf(id) {
  const m = {id: 'm', body: {message_id: id}, attempts: 1, outcome: null, ack() { this.outcome = 'ack'; }, retry() { this.outcome = 'retry'; }};
  return {queue: ADVISOR_QUEUE_NAME, messages: [m], ackAll() {}, retryAll() {}};
}
function recorder(name = 'bluebubbles') { const sent = []; return {sent, name, async send(m) { sent.push(structuredClone(m)); return {providerId: `${name}-${sent.length}`, status: 'sent'}; }}; }

dbTest('consumer: STOP then START through the engine; nothing is sent while stopped', async () => {
  const {sql, env} = setup();
  seen(sql);
  const ch = recorder();
  const go = async body => { const m = inbound(sql, body, {status: 'queued'}); await quiet(() => consumeAdvisor(batchOf(m.id), env, {channel: ch, handler: engineHandler, now: () => T0})); return m; };
  await go('STOP');
  assert.equal(contactRow(sql).status, 'stopped');
  assert.deepEqual(ch.sent.map(m => m.text), ["Done. You won't hear from me unless you text START."]);
  await go('what is biting');
  assert.equal(ch.sent.length, 1, 'silence while stopped');
  await go('START');
  assert.equal(contactRow(sql).status, 'active');
  assert.match(ch.sent.at(-1).text, /^SkipperCast here\./);
});

dbTest('consumer: forget sends the confirmation first, then deletes everything about the contact', async () => {
  const {sql, env} = setup({env: {ADVISOR_MEDIA: memoryBucket({'advisor/media/c1/m1.jpg': 'x', 'advisor/exports/c1/2026-10-01.json': '{}'})}});
  seen(sql);
  const ask = inbound(sql, 'forget me', {ago: 2, intent: 'forget.ask', status: 'done'});
  void ask;
  const ch = recorder();
  const m = inbound(sql, 'delete', {status: 'queued'});
  await quiet(() => consumeAdvisor(batchOf(m.id), env, {channel: ch, handler: engineHandler, now: () => T0}));
  assert.deepEqual(ch.sent.map(x => x.text), ['Done. Everything I had about this number is erased. Text me anytime to start fresh.']);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_contacts').get().n, 0);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_messages').get().n, 0);
  assert.equal(env.ADVISOR_MEDIA.objects.size, 0);
});

dbTest('consumer: export writes the JSON to R2 and texts a signed 24 h link that the route serves', async () => {
  const bucket = memoryBucket();
  const {sql, env} = setup({env: {ADVISOR_MEDIA: bucket, ADVISOR_PHONE_KEY: KEY}});
  seen(sql);
  const ch = recorder();
  const m = inbound(sql, 'send me my data', {status: 'queued'});
  await quiet(() => consumeAdvisor(batchOf(m.id), env, {channel: ch, handler: engineHandler, now: () => T0}));
  const key = 'advisor/exports/c1/2026-10-03.json';
  assert.ok(bucket.objects.has(key));
  const data = JSON.parse(new TextDecoder().decode(bucket.objects.get(key).bytes));
  assert.equal(data.contact.id, 'c1'); assert.ok(!JSON.stringify(data).includes('ENC'), 'phone_enc never exported');
  const [text] = ch.sent.map(x => x.text);
  const url = /https:\/\/skippercast\.com(\/api\/advisor\/export\/[\w-]+)$/.exec(text);
  assert.ok(url, text);
  const keys = await deriveKeys(KEY);
  const token = url[1].split('/').pop();
  assert.deepEqual(await verifyExportToken(keys, token, T0), {contactId: 'c1', key});
  assert.equal(await verifyExportToken(keys, token, T0 + 24 * 3600000 + 1000), null, 'expires after 24 h');
  assert.equal(await verifyExportToken(keys, token.slice(0, -2) + (token.endsWith('A') ? 'BB' : 'AA'), T0), null, 'tampered');
  // The route (now-relative expiry, so mint a fresh token).
  const fresh = await mintExportToken(keys, 'c1', key);
  const response = await worker.fetch(new Request(`https://skippercast.com/api/advisor/export/${fresh}`), {ASSETS: {fetch: async () => new Response('', {status: 404})}, ...env});
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.equal((await response.json()).contact.id, 'c1');
  const bad = await worker.fetch(new Request('https://skippercast.com/api/advisor/export/nope'), {ASSETS: {fetch: async () => new Response('', {status: 404})}, ...env});
  assert.equal(bad.status, 404);
  assert.throws(() => exportKey('c1', 'yesterday'));
  await assert.rejects(mintExportToken(keys, 'c2', key), /invalid export/, 'a key of another contact');
});

dbTest('consumer: send_file attaches on BlueBubbles and falls back to the link elsewhere', async () => {
  const {sql, env} = setup();
  seen(sql);
  const action = {type: 'send_file', name: 'SkipperCast.vcf', mime: 'text/vcard', inlineBytes: Buffer.from('BEGIN:VCARD').toString('base64'), caption: "Here's my contact card.", fallbackUrl: 'https://skippercast.com/contact.vcf'};
  const bb = recorder('bluebubbles'), tw = recorder('twilio');
  const one = inbound(sql, 'x', {status: 'queued'});
  await quiet(() => consumeAdvisor(batchOf(one.id), env, {channel: bb, handler: async () => ({actions: [action], intent: 'test'}), now: () => T0}));
  assert.deepEqual(bb.sent[0].files, [{name: 'SkipperCast.vcf', mime: 'text/vcard', base64: action.inlineBytes}]);
  assert.equal(bb.sent[0].text, "Here's my contact card.");
  const two = inbound(sql, 'y', {status: 'queued'});
  await quiet(() => consumeAdvisor(batchOf(two.id), env, {channel: tw, handler: async () => ({actions: [action], intent: 'test'}), now: () => T0}));
  assert.equal(tw.sent[0].text, "Here's my contact card. https://skippercast.com/contact.vcf"); assert.equal(tw.sent[0].files, undefined);
});

// ---- golden conversations (11 § engine golden conversations 6-9) ------------------------

const conversations = readdirSync(new URL('./fixtures/advisor/engine/conversations/', import.meta.url)).filter(f => f.endsWith('.json')).sort();
test('golden conversations 2 (en, es), 3, 4 and 6-9 exist', () => {
  // TA-I1: 2 up to the consent step, 3 the crew add and remove; TA-I2: 2 on through the count board, Y, a correction and a catch photo, 3 the crew member's board.
  // TA-I3: 4, the angler's fish IDs and photo sharing.
  for (const n of ['02-skipper-registers', '02-skipper-registers-es', '03-crew', '04-fish-id', '06-stop-start-help-forget', '07-off-topic-abuse-injection', '08-caps', '09-web-phone-link']) assert.ok(conversations.includes(`${n}.json`), n);
});

for (const file of conversations) {
  dbTest(`golden conversation ${file}`, async () => {
    const convo = read(`./fixtures/advisor/engine/conversations/${file}`);
    const contact = convo.contact ?? {};
    const {sql, env} = setup({contact, env: {ANTHROPIC_API_KEY: 'k', ADVISOR_PHONE_KEY: KEY, ADVISOR_MEDIA: memoryBucket(), ...convo.env}});
    if (convo.seen !== false) seen(sql);
    // TA-I1: boats that exist before the conversation (golden 3's verified boat).
    for (const b of convo.boats ?? []) sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)`)
      .run(b.id, b.slug, b.name, b.port, b.region ?? 'morro-bay', b.owner ?? null, b.status ?? 'pending', iso(T0 - 86400000), iso(T0 - 86400000));
    // TA-I3: rules rows the conversation quotes (golden 4), jurisdiction-wide like the importer writes them.
    for (const [i, r] of (convo.rules ?? []).entries()) sql.prepare(`INSERT INTO advisor_rules(id,region,jurisdiction,species_key,species_label,size_min_in,size_max_in,bag_limit,bag_notes,season_open,season_close,depth_limit_ft,area_notes,gear_notes,source_name,source_url,reviewed_at,review_due,status,updated_by,updated_at)
      VALUES(?,'*','california-central',?,?,?,?,?,NULL,?,?,?,NULL,NULL,'CDFW Central Region rules','https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central',?,?,?,'test',?)`)
      .run(`rule${i}`, r.species_key, r.species_label, r.size_min_in ?? null, r.size_max_in ?? null, r.bag_limit ?? null, r.season_open ?? null, r.season_close ?? null, r.depth_limit_ft ?? null, r.reviewed_at, r.review_due, r.status, iso(T0));
    const keys = await deriveKeys(KEY);
    const byNumber = async e164 => sql.prepare('SELECT * FROM advisor_contacts WHERE phone_hash=?').get(await phoneHash(keys, e164));
    const phoneChannel = recorder('bluebubbles'), webChannel = recorder('web');
    // TA-I2: a model entry {"vision": "<file>"} replays a vision fixture (tests/fixtures/advisor/vision/) through the same fetcher.
    const api = fakeApi(convo.turns.flatMap(turn => turn.model ?? []).map(r => r.vision ? {status: 200, body: read(`./fixtures/advisor/vision/${r.vision}`)} : r));
    let step = 0, randomValue = convo.random ?? 0.123456;
    for (const turn of convo.turns) {
      step++;
      // TA-I1: `from` is another sender's number (a crew member texting back).
      const who = turn.from ? await byNumber(turn.from) : contactRow(sql, contact.id ?? 'c1');
      assert.ok(who, `step ${step}: the contact exists`);
      const phoneBefore = phoneChannel.sent.length, apiBefore = api.requests.length;
      // TA-I2: `media` is the message's stored photos ({id, image}: a PNG under tests/fixtures/advisor/vision/images/), already downloaded.
      for (const x of turn.media ?? []) {
        const bytes = readFileSync(new URL(`./fixtures/advisor/vision/images/${x.image}`, import.meta.url)), key = `advisor/media/${who.id}/${x.id}.png`;
        env.ADVISOR_MEDIA.objects.set(key, {bytes: new Uint8Array(bytes), httpMetadata: {}});
        sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,publish_state,created_at) VALUES(?,?,?,'image','image/png',?,?,'x','private',?)`)
          .run(x.id, who.id, who.boat_id ?? null, bytes.length, key, iso(T0));
      }
      const m = inbound(sql, turn.in ?? null, {contact: who.id, status: 'queued', ago: -(step / 60), media: turn.media ? turn.media.map(x => x.id) : null});
      const before = {phone: phoneChannel.sent.length, web: webChannel.sent.length};
      const actions = [];
      const handler = async input => { const r = await engineHandler(input); actions.push(...r.actions); return r; };
      const isWeb = !who.phone_enc;
      await quiet(() => consumeAdvisor(batchOf(m.id), env, {
        channel: isWeb ? webChannel : undefined, channelFor: () => phoneChannel, handler, now: () => T0 + step * 1000,
        engine: {fetcher: api.fetcher, clock: () => T0 + step * 1000, sleep: async () => {}, random: () => randomValue},
      }));
      const replies = (isWeb ? webChannel : phoneChannel).sent.slice(isWeb ? before.web : before.phone).map(x => x.text ?? '');
      const reply = replies.join('\n');
      const e = turn.expect;
      const row = sql.prepare('SELECT intent,status,error FROM advisor_messages WHERE id=?').get(m.id);
      const intent = row?.intent;
      if (row && row.status !== 'done') assert.fail(`step ${step}: ${row.status} ${row.error}`);
      if (e.intent) assert.equal(intent, e.intent, `step ${step} intent`);
      for (const s of e.reply_contains ?? []) assert.ok(reply.includes(s), `step ${step}: "${s}" in "${reply}"`);
      for (const s of e.reply_not_contains ?? []) assert.ok(!reply.includes(s), `step ${step}: "${s}" not in "${reply}"`);
      if (e.no_reply) assert.equal(replies.length, 0, `step ${step}: silent`);
      if (e.actions) assert.deepEqual([...new Set(actions.map(a => a.type))].sort(), [...e.actions].sort(), `step ${step} actions`);
      if (e.status) assert.equal(contactRow(sql, who.id)?.status, e.status, `step ${step} status`);
      if (e.review) assert.ok(sql.prepare('SELECT 1 FROM advisor_reviews WHERE reason=?').get(e.review), `step ${step} review ${e.review}`);
      if (e.code_texted) {
        const code = phoneChannel.sent.at(-1).text;
        assert.match(code, /^Your SkipperCast code is \d{6}\. If you didn't ask for it, ignore this text\.$/);
        const pending = JSON.parse(sql.prepare('SELECT value FROM job_state WHERE key=?').get(linkKey(who.id)).value);
        assert.equal(pending.code_hash, await sha256(/\d{6}/.exec(code)[0]), 'only the hash is stored');
        assert.ok(!sql.prepare("SELECT body FROM advisor_messages WHERE direction='out'").all().some(r => /\d{6}/.test(r.body ?? '')), 'the code is never stored in clear');
      }
      if (e.merged) {
        const phone = sql.prepare('SELECT * FROM advisor_contacts WHERE phone_hash=?').get(await phoneHash(await deriveKeys(KEY), e.merged));
        assert.ok(phone, 'phone contact exists');
        assert.equal(sql.prepare("SELECT COUNT(*) n FROM advisor_contacts WHERE id=?").get(who.id).n, 0, 'the web contact is gone');
        assert.equal(sql.prepare("SELECT COUNT(*) n FROM advisor_messages WHERE contact_id=?").get(who.id).n, 0);
        assert.ok(sql.prepare("SELECT COUNT(*) n FROM advisor_messages WHERE contact_id=? AND direction='in'").get(phone.id).n >= 3, 'web history moved');
        assert.equal(phone.web_session, contact.web_session, 'the web session now belongs to the phone contact');
      }
      if (e.contact_gone) assert.ok(!contactRow(sql, who.id), 'the contact is gone');
      // TA-I1: a text to another number (the crew invite), rows in D1, and the model's contact brief.
      for (const x of e.texted ?? []) {
        const target = await byNumber(x.to);
        assert.ok(target, `step ${step}: a contact for the texted number`);
        const hit = phoneChannel.sent.slice(phoneBefore).find(m => m.to === target.phone_enc);
        assert.ok(hit, `step ${step}: a text went to that number`);
        for (const part of x.contains ?? []) assert.ok(hit.text.includes(part), `step ${step}: "${part}" in "${hit.text}"`);
      }
      for (const q of e.rows ?? []) assert.deepEqual({...sql.prepare(q.sql).get()}, q.row, `step ${step}: ${q.sql}`);
      for (const part of e.tool_results_exclude ?? []) for (const request of api.requests.slice(apiBefore))
        for (const block of request.messages.flatMap(m => Array.isArray(m.content) ? m.content : []).filter(b => b.type === 'tool_result'))
          assert.ok(!block.content.includes(part), `step ${step}: the tool result never echoes "${part}"`);
      for (const part of e.brief_contains ?? []) {
        const request = api.requests.slice(apiBefore)[0];
        assert.ok(request, `step ${step}: a model call`);
        assert.ok(request.system[1].text.includes(part), `step ${step}: "${part}" in the brief`);
      }
    }
    assert.equal(api.remaining(), 0, 'every recorded model response was used');
    void encryptPhone; void outboundId;
  });
}

dbTest('runInline with the engine: a new contact without an API key gets the warm-up text only', async () => {
  const {sql, env} = setup();
  const ch = recorder();
  const m = inbound(sql, 'hi', {status: 'queued'});
  await quiet(() => runInline(env, m.id, {channel: ch, handler: engineHandler}));
  assert.deepEqual(ch.sent.map(x => x.text), ['SkipperCast is warming up. Check back soon.']);
});

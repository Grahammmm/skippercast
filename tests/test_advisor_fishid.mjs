// Fish ID and angler photo sharing (server/advisor/answers/fishid.ts,
// server/advisor/intake/anglers.ts, the identify_fish and share_angler_photo
// tools; docs/plans/text-advisor/06-angler-answers.md § Fish ID and § Angler
// photos, 04 § stage 2, 10 § TA-I3): the three reply shapes, the protected
// warning at >= 0.3, the rules lines (current, stale, none, a look-alike with a
// different rule), the AC-1 offer only at >= 0.6 and never for skippers or
// crew, YES within 24 h, the credit asked once, "anonymous", and skipper media
// still going through TA-I2's intake. Golden conversation 4 runs in
// tests/test_advisor_engine.mjs. Offline: real migrations in node:sqlite, a
// memory R2, recorded vision answers.
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
const F = await import('../server/advisor/answers/fishid.ts');
const A = await import('../server/advisor/intake/anglers.ts');
const {engineHandler} = await import('../server/advisor/engine.ts');
const {consumeAdvisor, ADVISOR_QUEUE_NAME} = await import('../server/advisor/consumer.ts');
const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');
const {t} = await import('../server/advisor/strings.ts');
const {THRESHOLDS} = await import('../server/advisor/vision/index.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-03T17:00:00Z');   // Saturday 10:00 in Morro Bay
const HOUR = 3600000;
const KEY = Buffer.alloc(32, 7).toString('base64');
const iso = ms => new Date(ms).toISOString();
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const vfixture = name => read(`./fixtures/advisor/vision/${name}`);
const png = readFileSync(new URL('./fixtures/advisor/vision/images/fish.png', import.meta.url));
const input = name => vfixture(name).content[0].input;
const fishId = (candidates, extra = {}) => ({candidates, needs_better_photo: false, reason: null, provider: 'claude', model: 'm', ms: 1, ...extra});
const C = (species_key, confidence, label = species_key, cues = []) => ({species_key, label, confidence, cues});

// ---- fixtures ------------------------------------------------------------------------

const RULE = {vermilion: {bag_limit: 2, season_open: '2026-04-01', season_close: '2026-12-31'}, canary: {bag_limit: 2, season_open: '2026-04-01', season_close: '2026-12-31'},
  copper: {bag_limit: 1, season_open: '2026-04-01', season_close: '2026-12-31'}, yelloweye: {bag_limit: 0}, rockfish: {bag_limit: 10, season_open: '2026-04-01', season_close: '2026-12-31'},
  lingcod: {size_min_in: 22, bag_limit: 2, season_open: '2026-04-01', season_close: '2026-12-31'}};
function addRule(sql, key, over = {}) {
  const r = {size_min_in: null, size_max_in: null, bag_limit: null, season_open: null, season_close: null, depth_limit_ft: null, status: 'active', reviewed_at: '2026-10-01', review_due: '2026-12-31', ...RULE[key], ...over};
  sql.prepare(`INSERT INTO advisor_rules(id,region,jurisdiction,species_key,species_label,size_min_in,size_max_in,bag_limit,season_open,season_close,depth_limit_ft,source_name,source_url,reviewed_at,review_due,status,updated_by,updated_at)
    VALUES(?,'*','california-central',?,?,?,?,?,?,?,?,'CDFW Central Region rules','https://wildlife.ca.gov/Fishing/Ocean',?,?,?,'test',?)`)
    .run(`r-${key}`, key, key, r.size_min_in, r.size_max_in, r.bag_limit, r.season_open, r.season_close, r.depth_limit_ft, r.reviewed_at, r.review_due, r.status, iso(T0));
}
function setup({contact = {}, rules = ['vermilion', 'canary', 'yelloweye', 'lingcod', 'copper'], boat = null} = {}) {
  const {sql, db} = advisorDatabase();
  const c = {id: 'c1', role: 'angler', language: 'en', boat_id: null, home_port: 'morro-bay', ...contact};
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,home_port,status,last_seen_at,created_at,updated_at) VALUES(?,'h1','ENC','imessage',?,?,?,?,'active',?,?,?)`)
    .run(c.id, c.role, c.language, c.boat_id, c.home_port, iso(T0), iso(T0), iso(T0));
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES('seen','c1','in','imessage','earlier','done',?)`).run(iso(T0 - 30 * 24 * HOUR));
  if (boat) sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,status,consent_photos_at,created_at,updated_at) VALUES('b1','rita-g','Rita G','morro-bay','morro-bay','c1','pending',?,?,?)`)
    .run(boat.consent ?? null, iso(T0 - 30 * 24 * HOUR), iso(T0 - 30 * 24 * HOUR));
  for (const k of rules) addRule(sql, k);
  const bucket = memoryBucket();
  return {sql, db, bucket, env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_NUMBER: '+15555550199', ADVISOR_PHONE_KEY: KEY, ADVISOR_MEDIA: bucket, ANTHROPIC_API_KEY: 'k', ADVISOR_VISION_PROVIDERS: 'claude'}};
}
function addMedia(sql, bucket, id, {boat = null, kind = 'image', state = 'private'} = {}) {
  const key = `advisor/media/c1/${id}.png`;
  bucket.objects.set(key, {bytes: new Uint8Array(png), httpMetadata: {}});
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,publish_state,created_at) VALUES(?,'c1',?,?,'image/png',?,?,'x',?,?)`).run(id, boat, kind, png.length, key, state, iso(T0));
  return id;
}
let seq = 0;
function inbound(sql, body, {media = null, at = T0} = {}) {
  const id = `in${++seq}`;
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,media_json,status,created_at) VALUES(?,'c1','in','imessage',?,?,'queued',?)`).run(id, body, media ? JSON.stringify(media) : null, iso(at));
  return id;
}
/** Vision answers by forced tool name; a chat call (no tool_choice) is answered by `chat` or fails the test. */
function api(vision = {}, chat = null) {
  const calls = [];
  return {calls, fetcher: async (_url, init) => {
    const body = JSON.parse(init.body), name = body.tool_choice?.name ?? 'chat';
    calls.push(name);
    const answer = name === 'chat' ? chat?.shift() : vision[name];
    if (!answer) throw Error(`no answer for ${name}`);
    return new Response(JSON.stringify(answer), {status: 200, headers: {'content-type': 'application/json'}});
  }};
}
const batchOf = id => ({queue: ADVISOR_QUEUE_NAME, messages: [{id: 'm', body: {message_id: id}, attempts: 1, ack() {}, retry() {}}], ackAll() {}, retryAll() {}});
let sends = 0;
function recorder() { const sent = []; return {sent, name: 'bluebubbles', async send(m) { sent.push(structuredClone(m)); return {providerId: `p${++sends}`, status: 'sent'}; }}; }
/** One message through the consumer and the engine. */
async function say(env, sql, body, {media = null, at = T0, vision = {}, chat = null} = {}) {
  const id = inbound(sql, body, {media, at});
  const a = api(vision, chat), ch = recorder();
  await quiet(() => consumeAdvisor(batchOf(id), env, {channelFor: () => ch, handler: engineHandler, now: () => at, engine: {fetcher: a.fetcher, clock: () => at, sleep: async () => {}}}));
  const row = sql.prepare('SELECT status,error,intent FROM advisor_messages WHERE id=?').get(id);
  assert.equal(row.status, 'done', `${body}: ${row.error}`);
  return {texts: ch.sent.map(x => x.text), intent: row.intent, calls: a.calls};
}
const FISH = name => ({record_classification: vfixture('classify-fish.json'), record_fish_id: vfixture(name)});
const share = sql => { const r = sql.prepare("SELECT value FROM job_state WHERE key='advisor.share.c1'").get(); return r ? JSON.parse(r.value) : null; };
const media = (sql, id) => ({...sql.prepare('SELECT publish_state,credit FROM advisor_media WHERE id=?').get(id)});

// ---- the reply shapes (06 § fish ID step 2) ----------------------------------------------

dbTest('three bands: high "That\'s a", medium "Looks like ..., could be ...", ask "Not sure from this one" with no rules', async () => {
  const {db} = setup();
  const deps = {db, region: 'morro-bay', now: T0, language: 'en'};
  const high = await F.answerFor(fishId(input('fish-id-vermilion-high.json').candidates), deps);
  assert.equal(high.band, 'high');
  assert.equal(high.text, "That's a vermilion rockfish. Red body with grey or dark mottling. Rules (CDFW Central Region rules, checked Oct 1): bag 2, open Apr 1 to Dec 31. Double-check before you keep it: {{link:rules:vermilion}}");
  const medium = await F.answerFor(fishId(input('fish-id-canary-vermilion.json').candidates), deps);
  assert.equal(medium.band, 'medium');
  assert.match(medium.text, /^Looks like a canary rockfish, could be a vermilion rockfish: check for smooth lower jaw \(canary rockfish\) against small rough scales on the underside of the lower jaw \(vermilion rockfish\)\. /);
  assert.equal(medium.second_rules, null, 'canary and vermilion have the same rule here: no "if it\'s a" line');
  const ask = await F.answerFor(fishId(input('fish-id-blurry.json').candidates, {needs_better_photo: true, reason: 'blurry'}), deps);
  assert.equal(ask.band, 'ask');
  assert.equal(ask.text, "Not sure from this one. It's blurry: can you send a side-on shot with the fins spread?");
  assert.equal(ask.rules, null);
  // Low confidence without needs_better_photo is still "ask", with the generic reason; so is an empty result.
  assert.match((await F.answerFor(fishId([C('vermilion', 0.59)]), deps)).text, /^Not sure from this one\. I can't tell it apart from its look-alikes:/);
  assert.equal((await F.answerFor(fishId([], {needs_better_photo: true, reason: 'no_fish'}), deps)).text, "Not sure from this one. I can't find a fish in it: can you send a side-on shot with the fins spread?");
  // The band edges are the 07 thresholds.
  assert.equal((await F.answerFor(fishId([C('vermilion', THRESHOLDS.fishHigh)]), deps)).band, 'high');
  assert.equal((await F.answerFor(fishId([C('vermilion', THRESHOLDS.fishHigh - 0.001)]), deps)).band, 'medium');
  assert.equal((await F.answerFor(fishId([C('vermilion', THRESHOLDS.fishMedium)]), deps)).band, 'medium');
  for (const a of [high, medium, ask]) { assert.doesNotMatch(a.text, /\d\s*%/); assert.ok(a.text.length <= 480); }
});

dbTest('medium with a look-alike whose rule differs: "If it\'s a {second}: ..." after the top rule', async () => {
  const {db} = setup();
  const a = await F.answerFor(fishId([C('vermilion', 0.7, 'Vermilion rockfish'), C('copper', 0.2, 'Copper rockfish')]), {db, region: 'morro-bay', now: T0, language: 'en'});
  assert.equal(a.second_rules.bag_limit, 1);
  assert.match(a.text, /Rules \(CDFW Central Region rules, checked Oct 1\): bag 2, open Apr 1 to Dec 31\. If it's a copper rockfish: bag 1, open Apr 1 to Dec 31\. Double-check before you keep it: \{\{link:rules:vermilion\}\}$/);
});

dbTest('rules: stale row says "due for review" with no numbers; no row sends to CDFW; a sub-species falls back to its group row', async () => {
  const {sql, db} = setup({rules: ['rockfish']});
  addRule(sql, 'lingcod', {status: 'review'});
  const deps = {db, region: 'morro-bay', now: T0, language: 'en'};
  const stale = await F.answerFor(fishId([C('lingcod', 0.95, 'Lingcod')]), deps);
  assert.equal(stale.rules.stale, true);
  assert.match(stale.text, /this rule is due for review, so double-check with CDFW before you keep it: \{\{link:rules:lingcod\}\}$/);
  assert.doesNotMatch(stale.text, /22|bag 2/, 'a stale rule is never quoted with numbers');
  // A rule past review_due is stale too.
  sql.prepare("UPDATE advisor_rules SET status='active', review_due='2026-09-30' WHERE species_key='lingcod'").run();
  assert.equal((await F.answerFor(fishId([C('lingcod', 0.95)]), deps)).rules.stale, true);
  const group = await F.answerFor(fishId([C('vermilion', 0.9, 'Vermilion rockfish')]), deps);
  assert.equal(group.rules.applies_as, 'group');
  assert.match(group.text, /bag 10/);
  const none = await F.answerFor(fishId([C('cabezon', 0.9, 'Cabezon')]), deps);
  assert.match(none.text, /I have no reviewed rule for it, so check the current CDFW rules before you keep it: \{\{link:rules:cabezon\}\}$/);
  const unknown = await F.answerFor(fishId([C(null, 0.9, 'Sunfish')]), deps);
  assert.match(unknown.text, /^That's a sunfish\. .*\{\{link:rules\}\}$/);
  assert.deepEqual(F.ruleParts({size_min_in: 22, size_max_in: null, bag_limit: 0, season_open: null, season_close: null, depth_limit_ft: 120}, 'en'), ['22 in. minimum', 'no take', '120 ft depth limit']);
  assert.deepEqual(F.ruleParts({size_min_in: null, size_max_in: null, bag_limit: 5, season_open: null, season_close: null, depth_limit_ft: null}, 'es'), ['límite 5 por persona', 'abierta todo el año']);
  assert.equal(F.monthDay('2026-12-31', 'es'), '31 dic');
});

// ---- the protected warning (07 § thresholds, 06 step 4 as resolved) ---------------------------

dbTest('protected: a must-release candidate at >= 0.3 adds the release line in any band; 0.29 does not; canary (a sub-bag species) does not', async () => {
  const {db} = setup();
  const deps = {db, region: 'morro-bay', now: T0, language: 'en'};
  const line = /If it's a yelloweye rockfish, it must be released: use a descending device\./;
  assert.match((await F.answerFor(fishId([C('vermilion', 0.55), C('yelloweye', 0.3)]), deps)).text, line, 'ask band, yelloweye at exactly 0.3');
  assert.doesNotMatch((await F.answerFor(fishId([C('vermilion', 0.55), C('yelloweye', 0.29)]), deps)).text, line, 'below 0.3: no warning');
  assert.match((await F.answerFor(fishId([C('yelloweye', 0.9)]), deps)).text, /^That's a yelloweye rockfish\. .*must be released.*no take/);
  assert.match((await F.answerFor(fishId([C('vermilion', 0.7), C('yelloweye', 0.31)]), deps)).text, line, 'medium band');
  const both = await F.answerFor(fishId([C('vermilion', 0.4), C('yelloweye', 0.35), C('cowcod', 0.31)]), deps);
  assert.match(both.text, /If it's a yelloweye rockfish or cowcod, it must be released/);
  assert.deepEqual(both.protected, ['yelloweye', 'cowcod']);
  assert.doesNotMatch((await F.answerFor(fishId([C('canary', 0.9)]), deps)).text, /must be released/, 'canary is must_release: false');
  // The warning also comes on a blurry photo (needs_better_photo).
  assert.match((await F.answerFor(fishId([C('yelloweye', 0.4)], {needs_better_photo: true, reason: 'blurry'}), deps)).text, line);
});

// ---- the AC-1 offer -------------------------------------------------------------------------

test('offerShare: only at >= 0.6 and never for skippers or crew', () => {
  for (const [band, conf, role, want] of [['high', 0.9, 'angler', true], ['medium', 0.6, 'angler', true], ['medium', 0.6, 'admin-test', true], ['ask', 0.59, 'angler', false],
    ['high', 0.9, 'skipper', false], ['high', 0.9, 'crew', false]]) {
    assert.equal(F.offerShare({offer_eligible: band !== 'ask' && conf >= 0.6}, role), want, `${band} ${conf} ${role}`);
  }
});

dbTest('engine: a fish photo from an angler gets the ID, the offer and the offer state, with no chat model call; the photo stays private', async () => {
  const {sql, env, bucket} = setup();
  addMedia(sql, bucket, 'm1');
  const r = await say(env, sql, null, {media: ['m1'], vision: FISH('fish-id.json')});   // the TA-V1 fixture: vermilion 0.62
  assert.equal(r.intent, 'fishid.medium');
  assert.deepEqual(r.calls, ['record_classification', 'record_fish_id'], 'vision only: no chat call');
  assert.match(r.texts[0], /^Looks like a vermilion rockfish, could be a canary rockfish: /);
  assert.equal(r.texts[1], t('en', 'fishid_offer'));
  assert.deepEqual(media(sql, 'm1'), {publish_state: 'private', credit: null});
  assert.equal(share(sql).step, 'offered');
  // A blurry photo: no offer, no state.
  const b = setup();
  addMedia(b.sql, b.bucket, 'm2');
  const blurry = await say(b.env, b.sql, null, {media: ['m2'], vision: FISH('fish-id-blurry.json')});
  assert.deepEqual([blurry.intent, blurry.texts.length, share(b.sql)], ['fishid.ask', 1, null]);
});

dbTest('engine: a non-fish photo gets "Nice shot", and "id" then identifies it; YES shares it', async () => {
  const {sql, env, bucket} = setup();
  addMedia(sql, bucket, 'm1');
  const shot = await say(env, sql, null, {media: ['m1'], vision: {record_classification: vfixture('classify-deck-person.json')}});
  assert.deepEqual([shot.intent, shot.texts], ['media.nice_shot', ['Nice shot. Want me to ID a fish, or can we share this with credit?']]);
  assert.deepEqual(share(sql), {step: 'offered', media_id: 'm1', asked_at: iso(T0), id_offered: true});
  const id = await say(env, sql, 'ID it', {at: T0 + 60000, vision: {record_fish_id: vfixture('fish-id-vermilion-high.json')}});
  assert.equal(id.intent, 'fishid.high');
  assert.deepEqual(id.calls, ['record_fish_id'], 'the cached classification is not re-run');
  const yes = await say(env, sql, 'yes', {at: T0 + 120000});
  assert.equal(yes.intent, 'photo.share');
  assert.deepEqual(media(sql, 'm1'), {publish_state: 'queued', credit: null});
});

dbTest('consent: yes / sí / sure / ok within 24 h share; after 24 h or after another message the offer is ignored', async () => {
  for (const word of ['yes', 'Sí', 'sure', 'OK', 'claro']) {
    const {sql, env, bucket} = setup();
    addMedia(sql, bucket, 'm1');
    await say(env, sql, null, {media: ['m1'], vision: FISH('fish-id-vermilion-high.json')});
    const r = await say(env, sql, word, {at: T0 + 23 * HOUR});
    assert.equal(r.intent, 'photo.share', word);
    assert.equal(media(sql, 'm1').publish_state, 'queued', word);
    assert.deepEqual({...sql.prepare('SELECT kind,ref_id,reason,status FROM advisor_reviews').get()}, {kind: 'media', ref_id: 'm1', reason: 'angler_photo', status: 'open'});
  }
  // After 24 h: the yes is an ordinary message (here: no API key, the warm-up text), nothing is shared.
  const late = setup();
  addMedia(late.sql, late.bucket, 'm1');
  await say(late.env, late.sql, null, {media: ['m1'], vision: FISH('fish-id-vermilion-high.json')});
  const lateEnv = {...late.env, ANTHROPIC_API_KEY: undefined};
  assert.equal((await say(lateEnv, late.sql, 'yes', {at: T0 + 25 * HOUR})).intent, 'unconfigured');
  assert.equal(media(late.sql, 'm1').publish_state, 'private');
  // Another message first: the offer lapses (its state is deleted) and a later yes shares nothing.
  const other = setup();
  addMedia(other.sql, other.bucket, 'm1');
  await say(other.env, other.sql, null, {media: ['m1'], vision: FISH('fish-id-vermilion-high.json')});
  const otherEnv = {...other.env, ANTHROPIC_API_KEY: undefined};
  await say(otherEnv, other.sql, 'is it any good to eat?', {at: T0 + HOUR});
  assert.equal(share(other.sql), null);
  await say(otherEnv, other.sql, 'yes', {at: T0 + 2 * HOUR});
  assert.equal(media(other.sql, 'm1').publish_state, 'private');
});

dbTest('credit: asked once; a name or "anonymous" is stored; the next shared photo reuses it without asking', async () => {
  const {sql, env, bucket} = setup();
  addMedia(sql, bucket, 'm1'); addMedia(sql, bucket, 'm2');
  await say(env, sql, null, {media: ['m1'], vision: FISH('fish-id-vermilion-high.json')});
  const yes = await say(env, sql, 'yes');
  assert.deepEqual(yes.texts, ["Thanks! How should we credit you? A first name is fine, or 'anonymous'."]);
  const name = await say(env, sql, 'anonymous');
  assert.deepEqual([name.intent, name.texts], ['photo.credit', [t('en', 'share_queued_anonymous')]]);
  assert.deepEqual(media(sql, 'm1'), {publish_state: 'queued', credit: 'anonymous'});
  await say(env, sql, null, {media: ['m2'], vision: FISH('fish-id-lingcod-high.json')});
  const again = await say(env, sql, 'sure');
  assert.deepEqual(again.texts, [t('en', 'share_queued_anonymous')], 'not asked again');
  assert.deepEqual(media(sql, 'm2'), {publish_state: 'queued', credit: 'anonymous'});
  // A reply that is not a name leaves the photo queued without a credit and goes on.
  const n = setup();
  addMedia(n.sql, n.bucket, 'm1');
  await say(n.env, n.sql, null, {media: ['m1'], vision: FISH('fish-id-vermilion-high.json')});
  await say(n.env, n.sql, 'yes');
  const q = await say({...n.env, ANTHROPIC_API_KEY: undefined}, n.sql, 'how deep were they biting today?');
  assert.equal(q.intent, 'unconfigured');
  assert.deepEqual([media(n.sql, 'm1'), share(n.sql)], [{publish_state: 'queued', credit: null}, null]);
});

test('parseCredit: names, "anonymous" in both languages, and replies that are not a name', () => {
  for (const [text, want] of [['Sam', 'Sam'], ['  Rosa M. ', 'Rosa M'], ["call me Joe", 'Joe'], ['me llamo Lupe', 'Lupe'], ['Anonymous', 'anonymous'], ['anónimo', 'anonymous'], ['no name', 'anonymous'],
    ['"Captain Mike"', 'Captain Mike'], ['yes', null], ['no', null], ['how deep were they biting today?', null], ['12345', null], ['a'.repeat(41), null], ['one two three four five', null], ['', null]]) {
    assert.equal(A.parseCredit(text), want, text);
  }
});

// ---- skippers, crew and the tools ------------------------------------------------------------

dbTest('a skipper\'s fish photo still goes through TA-I2 intake (queued to the boat with consent), never the fish ID or the AC-1 offer', async () => {
  const {sql, env, bucket} = setup({contact: {role: 'skipper', boat_id: 'b1'}, boat: {consent: iso(T0 - 24 * HOUR)}});
  addMedia(sql, bucket, 'm1', {boat: 'b1'});
  const r = await say(env, sql, null, {media: ['m1'], vision: FISH('fish-id-vermilion-high.json')});
  assert.equal(r.intent, 'media.photo');
  assert.deepEqual(r.calls, ['record_classification']);
  assert.ok(!r.texts.some(x => /That's a|Reply YES/.test(x)));
  assert.deepEqual(media(sql, 'm1'), {publish_state: 'queued', credit: 'Rita G'});
  // A skipper without a boat (or crew whose link ended) gets the plain acknowledgement, not the angler path.
  const lone = setup({contact: {role: 'skipper'}});
  addMedia(lone.sql, lone.bucket, 'm1');
  const ack = await say(lone.env, lone.sql, null, {media: ['m1'], vision: FISH('fish-id-vermilion-high.json')});
  assert.deepEqual([ack.intent, ack.calls], ['media', []]);
});

dbTest('identify_fish: the 06 reply, candidates and rules for the model; only the contact\'s own photo', async () => {
  const {sql, env, bucket, db} = setup();
  addMedia(sql, bucket, 'm1');
  const a = api(FISH('fish-id-canary-vermilion.json'));
  const ctx = {env, contact: sql.prepare("SELECT * FROM advisor_contacts WHERE id='c1'").get(), message: {id: 'x'}, deps: {fetcher: a.fetcher, clock: () => T0}, db, language: 'en', settings: advisorSettings(env), now: T0};
  const out = (await quiet(() => TOOL_BY_NAME.get('identify_fish').run({media_id: 'm1'}, ctx))).value.result;
  assert.equal(out.band, 'medium');
  assert.match(out.reply, /^Looks like a canary rockfish, could be a vermilion rockfish/);
  assert.equal(out.rules.stale, false);
  assert.equal(out.rules_link, '{{link:rules:canary}}');
  assert.match(out.share_offer, /share_angler_photo with media_id m1/);
  assert.deepEqual(a.calls, ['record_fish_id'], 'identify_fish does not classify first');
  assert.deepEqual((await TOOL_BY_NAME.get('identify_fish').run({media_id: 'someone-else'}, ctx)).result, {error: 'no such photo from this person'});
});

dbTest('share_angler_photo: consent true queues and asks the credit; false shares nothing; another contact\'s photo is refused', async () => {
  const {sql, env, bucket, db} = setup();
  addMedia(sql, bucket, 'm1');
  const ctx = {env, contact: sql.prepare("SELECT * FROM advisor_contacts WHERE id='c1'").get(), message: {id: 'x'}, deps: {}, db, language: 'es', settings: advisorSettings(env), now: T0};
  const no = await TOOL_BY_NAME.get('share_angler_photo').run({media_id: 'm1', consent: false}, ctx);
  assert.deepEqual([no.result.shared, no.actions], [false, [{type: 'share_state', state: null}]]);
  const yes = await TOOL_BY_NAME.get('share_angler_photo').run({media_id: 'm1', consent: true}, ctx);
  assert.equal(yes.result.credit_question_sent, true);
  assert.deepEqual(yes.actions.map(x => x.type), ['angler_share', 'review_open', 'share_state', 'send_text']);
  assert.equal(yes.actions.at(-1).text, "¡Gracias! ¿Cómo te damos crédito? Basta con tu nombre, o 'anónimo'.");
  assert.deepEqual(yes.actions[1], {type: 'review_open', kind: 'media', refId: 'm1', reason: 'angler_photo'});
  assert.deepEqual((await TOOL_BY_NAME.get('share_angler_photo').run({media_id: 'nope', consent: true}, ctx)).result, {error: 'no such photo from this person'});
  assert.deepEqual(TOOL_BY_NAME.get('share_angler_photo').roles, ['angler']);
});

dbTest('Spanish: the reply shapes and the offer in Spanish, with Spanish species names', async () => {
  const {sql, env, bucket} = setup({contact: {language: 'es'}});
  addMedia(sql, bucket, 'm1');
  const r = await say(env, sql, null, {media: ['m1'], vision: FISH('fish-id-vermilion-high.json')});
  assert.match(r.texts[0], /^Es un colorado\. Reglas \(CDFW Central Region rules, revisadas 1 oct\): límite 2 por persona, abierta del 1 abr al 31 dic\. Confírmalo antes de quedártelo: https:/);
  assert.equal(r.texts[1], t('es', 'fishid_offer'));
  const sí = await say(env, sql, 'sí');
  assert.equal(sí.intent, 'photo.share');
});

dbTest('vision unavailable or too large: a plain line or the upload link, never a guess', async () => {
  const {sql, env, bucket} = setup();
  addMedia(sql, bucket, 'm1');
  const down = await say(env, sql, null, {media: ['m1'], vision: {}});
  assert.deepEqual([down.intent, down.texts], ['fishid.unavailable', [t('en', 'fishid_unavailable')]]);
  const big = setup();
  big.bucket.objects.set('advisor/media/c1/m9.png', {bytes: new Uint8Array(5 * 1024 * 1024), httpMetadata: {}});
  big.sql.prepare(`INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,publish_state,created_at) VALUES('m9','c1','image','image/png',?, 'advisor/media/c1/m9.png','x','private',?)`).run(5 * 1024 * 1024, iso(T0));
  const r = await say(big.env, big.sql, null, {media: ['m9']});
  assert.equal(r.intent, 'media.upload_link');
  assert.match(r.texts[0], /^That photo is too big for me to read by text\. Send it through this link, good for 24 hours: https:\/\/skippercast\.com\/u\//);
});

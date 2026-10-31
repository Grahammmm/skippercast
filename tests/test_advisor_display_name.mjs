// RF1300-4: one display-name cleaner (server/advisor/display-name.ts) used by
// update_profile and the consumer's contact_update: NFC, whitespace runs to one
// space, control/zero-width/bidi characters removed, trimmed, cut to 60 code
// points (never half a surrogate pair); null when nothing visible is left.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';

const {cleanDisplayName, DISPLAY_NAME_MAX} = await import('../server/advisor/display-name.ts');
const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const {consumeAdvisor, ADVISOR_QUEUE_NAME} = await import('../server/advisor/consumer.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-03T15:00:00Z');
const loneSurrogate = s => /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(s);

test('bidi overrides, isolates and marks are removed', () => {
  assert.equal(cleanDisplayName('Ray\u202Eevil'), 'Rayevil');
  assert.equal(cleanDisplayName('\u2067Ray\u2069'), 'Ray');
  assert.equal(cleanDisplayName('\u200FRay'), 'Ray');
  assert.equal(cleanDisplayName('\u202AR\u202Ba\u202Cy\u202D\u2066\u2068'), 'Ray');
});

test('zero-width characters, word joiner, invisible operators and BOM are removed', () => {
  assert.equal(cleanDisplayName('R\u200Ba\u200Dy\uFEFF'), 'Ray');
  assert.equal(cleanDisplayName('R\u200Ca\u200Ey\u2060\u2061\u2064'), 'Ray');
  assert.equal(cleanDisplayName('Ray\uFEFFSmith'), 'Ray Smith', 'U+FEFF is \\s in JS: inside a name it becomes a space');
});

test('C0, DEL and C1 controls are removed, not spaced', () => {
  assert.equal(cleanDisplayName('Ray\u0085Smith'), 'RaySmith', 'U+0085 is not \\s in JS');
  assert.equal(cleanDisplayName('\u009B31m'), '31m');
  assert.equal(cleanDisplayName('R\u0000a\u007Fy\u001B'), 'Ray');
});

test('nothing visible left is null; update_profile rejects it and saves nothing', async () => {
  for (const s of ['\u200B\u202E ', '', '   ', '\t\n', '\uFEFF\u2066\u0085']) assert.equal(cleanDisplayName(s), null, JSON.stringify(s));
  const ctx = {env: {}, contact: {id: 'c1', role: 'angler', language: 'en', status: 'active'}, message: {id: 'in1'}, deps: {}, db: null,
    language: 'en', settings: advisorSettings({}), now: T0};
  const run = input => TOOL_BY_NAME.get('update_profile').run(input, ctx);
  assert.deepEqual(await run({display_name: '\u200B\u202E '}), {result: {saved: [], rejected: ['display_name']}, actions: []});
  assert.deepEqual(await run({display_name: 'Ray\u202E', language: 'en'}),
    {result: {saved: ['display_name', 'language'], rejected: []}, actions: [{type: 'contact_update', fields: {display_name: 'Ray', language: 'en'}}]});
});

test('whitespace runs collapse to one space and the ends are trimmed', () => {
  assert.equal(cleanDisplayName('  Capt.\t\tRay  '), 'Capt. Ray');
  assert.equal(cleanDisplayName('Ray\nSmith'), 'Ray Smith');
  assert.equal(cleanDisplayName(' Capt.\u0007 Ray '), 'Capt. Ray');
});

test('the cut is 60 code points, never half a surrogate pair, and counts only what is kept', () => {
  assert.equal(DISPLAY_NAME_MAX, 60);
  const fish = cleanDisplayName('a'.repeat(59) + '\u{1F3A3}' + 'b');
  assert.equal(fish, 'a'.repeat(59) + '\u{1F3A3}');
  assert.equal(Array.from(fish).length, 60);
  assert.equal(fish.length, 61, 'the emoji stays a full pair (61 UTF-16 units)');
  assert.ok(!loneSurrogate(fish));
  assert.equal(cleanDisplayName('a'.repeat(61)), 'a'.repeat(60));
  assert.equal(cleanDisplayName('a'.repeat(60) + 'b'), 'a'.repeat(60));
  assert.equal(cleanDisplayName('a\u200B'.repeat(60) + 'b'), 'a'.repeat(60), 'removed characters do not use up the 60');
  assert.equal(cleanDisplayName('a'.repeat(59) + ' b'), 'a'.repeat(59), 'a space left at the cut is trimmed');
});

test('NFC: a combining accent becomes one code point', () => {
  const jose = cleanDisplayName('Jose\u0301');
  assert.equal(jose, 'Jos\u00E9');
  assert.equal(jose.length, 4);
});

test('non-strings are null', () => {
  for (const v of [5, null, undefined, {}, ['Ray'], true]) assert.equal(cleanDisplayName(v), null, String(v));
});

dbTest('consumer contact_update stores the cleaned name; an invisible-only name stores null', async () => {
  const {sql, db} = advisorDatabase(), at = new Date(T0).toISOString();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,status,display_name,last_seen_at,created_at,updated_at) VALUES('c1','h1','ENC-BLOB','imessage','active','Old',?,?,?)`).run(at, at, at);
  const name = () => sql.prepare("SELECT display_name FROM advisor_contacts WHERE id='c1'").get().display_name;
  const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}; console.log = console.warn = console.error = () => {}; try { return await fn(); } finally { Object.assign(console, saved); } };
  const turn = async (id, display_name) => {
    sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES(?,'c1','in','imessage',?,'hi','queued',?)`).run(id, 'g-' + id, at);
    const handler = async () => ({intent: 'intake.name', actions: [{type: 'contact_update', fields: {display_name}}]});
    const batch = {queue: ADVISOR_QUEUE_NAME, messages: [{id: 'm0', body: {message_id: id}, attempts: 1, timestamp: new Date(T0), ack() {}, retry() {}}], ackAll() {}, retryAll() {}};
    await quiet(() => consumeAdvisor(batch, {TEXT_ADVISOR_ENABLED: 'true', DB: db}, {channel: {async send() { return {providerId: 'p', status: 'sent'}; }}, handler, now: () => T0}));
  };
  await turn('in1', 'Ray\u202E');
  assert.equal(name(), 'Ray');
  await turn('in2', '  Capt.\t\u2067Ray\u2069  ');
  assert.equal(name(), 'Capt. Ray');
  await turn('in3', '\u200B');
  assert.equal(name(), null);
});

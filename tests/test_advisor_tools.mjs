// Text Advisor tools (server/advisor/tools/; docs/plans/text-advisor/04-advisor-engine.md
// § Tools): the registry (every tool in 04's table, unique names, valid
// schemas, role filtering, cache_control on the last definition), the
// dispatcher's error handling, the stubs' "not built yet" answer, and the
// executors built here: update_profile, escalate, send_upload_link,
// send_contact_card, offer_text_link (codes, limits, hashing). Offline.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const {TOOLS, TOOL_BY_NAME, toolsForRole, claudeTools, dispatchTool, NOT_BUILT, isWebOnly} = await import('../server/advisor/tools/index.ts');
const {linkCode, takeDaily, LINK_CODES_PER_DAY, LINK_CODE_TTL_MS} = await import('../server/advisor/tools/offer_text_link.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');
const {deriveKeys, phoneHash, decryptPhone} = await import('../server/advisor/contacts.ts');
const {verifyUploadToken} = await import('../server/advisor/media.ts');
const {sha256} = await import('../server/advisor/ids.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-03T17:00:00Z');
const KEY = Buffer.alloc(32, 7).toString('base64');
const contact = (over = {}) => ({id: 'c1', phone_hash: 'h', phone_enc: 'ENC', web_session: null, channel: 'imessage', role: 'angler', language: 'en', status: 'active', ...over});
const ctx = (over = {}, env = {}) => ({env: {ADVISOR_NUMBER: '+15555550199', ...env}, contact: contact(over.contact), message: {id: 'in1'}, deps: {}, db: over.db ?? null,
  language: 'en', settings: advisorSettings({ADVISOR_NUMBER: '+15555550199', ...env}), now: T0, ...over, ...(over.contact ? {contact: contact(over.contact)} : {})});

const STUBS = ['get_port_report', 'get_conditions', 'get_species', 'get_strategy', 'get_trips', 'identify_fish',
  'read_count_board', 'propose_report', 'edit_report', 'propose_post', 'register_boat', 'add_crew', 'remove_crew', 'share_angler_photo'];
const BUILT = ['update_profile', 'escalate', 'send_upload_link', 'send_contact_card', 'offer_text_link', 'get_rules'];   // get_rules: TA-A0 (tests/test_advisor_rules.mjs)

test('the registry has every tool in 04 § Tools, once, with a valid schema and an intent', () => {
  assert.deepEqual(TOOLS.map(t => t.name).sort(), [...STUBS, ...BUILT].sort());
  assert.equal(TOOL_BY_NAME.size, TOOLS.length);
  for (const tool of TOOLS) {
    assert.match(tool.name, /^[a-z_]{3,40}$/);
    assert.ok(tool.description.length > 30, tool.name);
    assert.equal(tool.input_schema.type, 'object', tool.name);
    assert.equal(tool.input_schema.additionalProperties, false, tool.name);
    for (const r of tool.input_schema.required ?? []) assert.ok(r in tool.input_schema.properties, `${tool.name}.${r}`);
    assert.match(tool.intent, /^[a-z][\w.]{1,30}$/);
    assert.ok(tool.roles.length);
    assert.doesNotThrow(() => JSON.stringify(tool.input_schema));
  }
});

test('claudeTools: Messages API definitions; only the last carries cache_control', () => {
  const defs = claudeTools(TOOLS);
  assert.deepEqual(Object.keys(defs[0]).sort(), ['description', 'input_schema', 'name']);
  assert.deepEqual(defs.at(-1).cache_control, {type: 'ephemeral'});
  assert.equal(defs.filter(d => d.cache_control).length, 1);
});

test('toolsForRole: anglers, skippers, crew, admin-test and web visitors', () => {
  const names = c => toolsForRole(contact(c)).map(t => t.name);
  const angler = names({}), skipper = names({role: 'skipper'}), crew = names({role: 'crew'}), admin = names({role: 'admin-test'});
  const web = names({phone_enc: null, phone_hash: null, web_session: 'w', channel: 'web'});
  for (const s of ['read_count_board', 'propose_report', 'edit_report', 'propose_post', 'add_crew', 'remove_crew']) assert.ok(!angler.includes(s), s);
  for (const s of ['read_count_board', 'propose_report', 'edit_report', 'propose_post', 'add_crew', 'remove_crew']) assert.ok(skipper.includes(s), s);
  assert.ok(crew.includes('propose_report') && !crew.includes('add_crew'), 'crew cannot manage crew');
  assert.ok(angler.includes('share_angler_photo') && !skipper.includes('share_angler_photo'));
  assert.ok(angler.includes('register_boat'), 'anyone may register a boat (it makes them a skipper)');
  assert.deepEqual(admin, angler, 'admin-test is an angler to the model: no admin tool exists');
  assert.ok(web.includes('offer_text_link') && !angler.includes('offer_text_link') && !skipper.includes('offer_text_link'));
  assert.equal(isWebOnly(contact({phone_enc: null, web_session: 'w'})), true);
});

test('stubs answer {unavailable: true, reason: "not built yet"} with no action', async () => {
  for (const name of STUBS) assert.deepEqual(await TOOL_BY_NAME.get(name).run({}, ctx()), {result: NOT_BUILT}, name);
  assert.deepEqual(NOT_BUILT, {unavailable: true, reason: 'not built yet'});
});

test('dispatchTool: unknown or disallowed tools and throwing executors are error results, never exceptions', async () => {
  const allowed = toolsForRole(contact());
  assert.deepEqual(await dispatchTool('read_count_board', {}, ctx(), allowed), {result: {error: 'unknown tool'}, isError: true});
  assert.deepEqual(await dispatchTool('drop_tables', {}, ctx(), allowed), {result: {error: 'unknown tool'}, isError: true});
  const boom = [{name: 'boom', roles: ['angler'], run: async () => { throw Error('nope'); }}];
  assert.deepEqual(await dispatchTool('boom', 'not an object', ctx(), boom), {result: {error: 'nope'}, isError: true});
});

test('update_profile: known ports and species only; name cleaned; language en/es', async () => {
  const run = input => TOOL_BY_NAME.get('update_profile').run(input, ctx());
  assert.deepEqual(await run({home_port: 'morro-bay', targets: ['Lingcod', 'california-halibut', 'unicorn'], display_name: ' Capt.\u0007 Ray ', language: 'es'}), {
    result: {saved: ['display_name', 'home_port', 'targets', 'language'], rejected: []},
    actions: [{type: 'contact_update', fields: {display_name: 'Capt. Ray', home_port: 'morro-bay', targets_json: '["lingcod","halibut"]', language: 'es'}}]});
  assert.deepEqual(await run({home_port: 'atlantis', targets: ['unicorn'], language: 'fr'}), {result: {saved: [], rejected: ['home_port', 'targets', 'language']}, actions: []});
});

test('escalate: a conversation review on this message; unknown reasons become needs_human', async () => {
  const tool = TOOL_BY_NAME.get('escalate');
  assert.deepEqual(await tool.run({reason: 'abuse'}, ctx()), {result: {flagged: true}, actions: [{type: 'review_open', kind: 'conversation', refId: 'in1', reason: 'abuse'}]});
  assert.equal((await tool.run({reason: 'drop everything'}, ctx())).actions[0].reason, 'needs_human');
});

test('send_upload_link: a 24 h token for this contact, as its own text; unavailable without the key', async () => {
  const tool = TOOL_BY_NAME.get('send_upload_link');
  const out = await tool.run({}, ctx({}, {ADVISOR_PHONE_KEY: KEY}));
  const token = /\/u\/([\w-]+)$/.exec(out.actions[0].text)[1];
  assert.equal(await verifyUploadToken(await deriveKeys(KEY), token, T0), 'c1');
  assert.deepEqual(out.result, {sent: true, note: 'the link was sent as its own message'});
  const none = await tool.run({}, ctx());
  assert.deepEqual(none.result, {sent: false, reason: 'not available right now'});
  assert.equal(none.actions[0].text, "I can't make an upload link right now. Try again later.");
});

test('send_contact_card: a vCard file on iMessage, the /contact.vcf link on SMS and web, nothing without a number', async () => {
  const tool = TOOL_BY_NAME.get('send_contact_card');
  const imessage = await tool.run({}, ctx());
  assert.equal(imessage.actions[0].type, 'send_file');
  assert.match(Buffer.from(imessage.actions[0].inlineBytes, 'base64').toString(), /TEL;TYPE=CELL,VOICE:\+15555550199/);
  const sms = await tool.run({}, ctx({contact: {channel: 'sms'}}));
  assert.deepEqual(sms.actions, [{type: 'send_text', text: 'Save my number: https://skippercast.com/contact.vcf'}]);
  const noNumber = await tool.run({}, {...ctx(), settings: advisorSettings({})});
  assert.deepEqual(noNumber, {result: {sent: false, reason: 'not available right now'}});
});

test('linkCode: six digits from the injected random or the CSPRNG', () => {
  assert.equal(linkCode(() => 0.123456), '123456');
  assert.equal(linkCode(() => 0), '000000');
  assert.equal(linkCode(() => 0.9999999), '999999');
  assert.match(linkCode(), /^\d{6}$/);
});

dbTest('offer_text_link: a code action with only hashes and the encrypted number; 3 codes a day; refuses bad numbers', async () => {
  const {db} = advisorDatabase();
  const tool = TOOL_BY_NAME.get('offer_text_link');
  const web = {contact: {id: 'w1', phone_enc: null, phone_hash: null, web_session: 'x', channel: 'web'}, db, deps: {random: () => 0.654321}};
  const c = ctx(web, {ADVISOR_PHONE_KEY: KEY});
  const out = await tool.run({phone: '(805) 555-0123'}, c);
  const [action] = out.actions;
  const keys = await deriveKeys(KEY);
  assert.deepEqual({type: action.type, phoneHash: action.phoneHash, codeHash: action.codeHash, expiresAt: action.expiresAt, codeText: action.codeText},
    {type: 'link_start', phoneHash: await phoneHash(keys, '+18055550123'), codeHash: await sha256('654321'), expiresAt: T0 + LINK_CODE_TTL_MS, codeText: '654321'});
  assert.equal(await decryptPhone(keys, action.phoneEnc), '+18055550123');
  assert.ok(!JSON.stringify(out.result).includes('555'), 'the number is never echoed to the model');
  for (let i = 1; i < LINK_CODES_PER_DAY; i++) assert.equal((await tool.run({phone: '805-555-0123'}, c)).result.sent, true);
  assert.deepEqual((await tool.run({phone: '805-555-0123'}, c)).result, {sent: false, reason: 'too many codes today; try tomorrow'});
  assert.deepEqual((await tool.run({phone: '12345'}, ctx(web, {ADVISOR_PHONE_KEY: KEY}))).result, {sent: false, reason: 'not a US mobile number'});
  assert.deepEqual((await tool.run({phone: '805-555-0123'}, ctx({...web, contact: {...web.contact, id: 'w2'}}))).result, {sent: false, reason: 'texting is not set up yet'});
  assert.equal(await takeDaily(db, 'k', 1, T0), true); assert.equal(await takeDaily(db, 'k', 1, T0), false); assert.equal(await takeDaily(db, 'k', 1, T0 + 86400000), true, 'a new day');
});

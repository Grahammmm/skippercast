// Text Advisor tools (server/advisor/tools/; docs/plans/text-advisor/04-advisor-engine.md
// § Tools): the registry (every tool in 04's table, unique names, valid
// schemas, role filtering, cache_control on the last definition), the
// dispatcher's error handling, the stubs' "not built yet" answer, and the
// executors built here: update_profile, escalate, send_upload_link,
// send_contact_card, offer_text_link (codes, limits, hashing), and the TA-E2
// data tools (get_port_report, get_conditions, get_species, get_strategy,
// get_trips) with their answers/ modules: the confidence ladder and comfort
// rubric pinned to dist/bite-evidence.js and web/score.ts, the conditions
// parser and advisories on the committed feed fixtures (tests/fixtures/feeds/),
// date words, port and species resolution, the public-grounds allowlist and the
// no-coordinate rule. Offline: feeds come from deps.feeds.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');

const {TOOLS, TOOL_BY_NAME, toolsForRole, claudeTools, dispatchTool, NOT_BUILT, stubTool, isWebOnly} = await import('../server/advisor/tools/index.ts');
const {linkCode, takeDaily, LINK_CODES_PER_DAY, LINK_CODE_TTL_MS, CODE_OFFERED} = await import('../server/advisor/tools/offer_text_link.ts');
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

const STUBS = [];   // TA-S1 built propose_post, the last stub (tests/test_advisor_social_drafts.mjs)
const BUILT = ['update_profile', 'escalate', 'send_upload_link', 'send_contact_card', 'offer_text_link', 'get_rules',   // get_rules: TA-A0 (tests/test_advisor_rules.mjs)
  'get_port_report', 'get_conditions', 'get_species', 'get_strategy', 'get_trips',                                      // TA-E2, below
  'register_boat', 'add_crew', 'remove_crew',                                                                           // TA-I1 (tests/test_advisor_skippers.mjs)
  'read_count_board', 'propose_report', 'edit_report',                                                                  // TA-I2 (tests/test_advisor_reports.mjs)
  'identify_fish', 'share_angler_photo',                                                                                // TA-I3 (tests/test_advisor_fishid.mjs)
  'propose_post'];                                                                                                      // TA-S1 (tests/test_advisor_social_drafts.mjs)

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

test('stubs answer {unavailable: true, reason: "not built yet"} with no action (none are left; stubTool keeps the shape for later tools)', async () => {
  for (const name of STUBS) assert.deepEqual(await TOOL_BY_NAME.get(name).run({}, ctx()), {result: NOT_BUILT}, name);
  assert.deepEqual(NOT_BUILT, {unavailable: true, reason: 'not built yet'});
  const stub = stubTool({name: 'later_tool', description: 'x'.repeat(40), input_schema: {type: 'object', properties: {}}, roles: ['angler'], intent: 'later'});
  assert.deepEqual(await stub.run({}, ctx()), {result: NOT_BUILT});
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
  // TA-A6: the result carries the line to send in the reply language.
  assert.deepEqual(await tool.run({reason: 'abuse'}, ctx()), {result: {flagged: true, reply: "I'm going to stop here."}, actions: [{type: 'review_open', kind: 'conversation', refId: 'in1', reason: 'abuse'}]});
  const other = await tool.run({reason: 'drop everything'}, ctx());
  assert.deepEqual([other.actions[0].reason, other.result.reply], ['needs_human', "I've flagged this for the team."]);
  assert.equal((await tool.run({reason: 'complaint'}, ctx({language: 'es'}))).result.reply, 'Se lo pasé al equipo.');
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
  assert.deepEqual(out.result, {...CODE_OFFERED}, 'the same answer for any valid number (the consumer\'s outbound guard decides; tests/test_advisor_outbound.mjs)');
  for (let i = 1; i < LINK_CODES_PER_DAY; i++) assert.equal((await tool.run({phone: '805-555-0123'}, c)).result.sent, true);
  assert.deepEqual((await tool.run({phone: '805-555-0123'}, c)).result, {sent: false, reason: 'too many codes today; try tomorrow'});
  assert.deepEqual((await tool.run({phone: '12345'}, ctx(web, {ADVISOR_PHONE_KEY: KEY}))).result, {sent: false, reason: 'not a US mobile number'});
  assert.deepEqual((await tool.run({phone: '805-555-0123'}, ctx({...web, contact: {...web.contact, id: 'w2'}}))).result, {sent: false, reason: 'texting is not set up yet'});
  assert.equal(await takeDaily(db, 'k', 1, T0), true); assert.equal(await takeDaily(db, 'k', 1, T0), false); assert.equal(await takeDaily(db, 'k', 1, T0 + 86400000), true, 'a new day');
});

// ---- TA-E2: the data tools -----------------------------------------------------------------

const {reportEvidence: serverEvidence, validFeed: serverValidFeed, CONFIDENCE_WORDS} = await import('../server/advisor/answers/confidence.ts');
const comfort = await import('../server/advisor/answers/comfort.ts');
const conditions = await import('../server/advisor/answers/conditions.ts');
const {resolvePort, resolveSpecies, findPort, landingNames} = await import('../server/advisor/answers/resolve.ts');
const advice = await import('../server/advisor/answers/advice.ts');
const {AD2_LINE} = await import('../server/advisor/tools/get_strategy.ts');
const {MAX_REPORT_AGE_DAYS} = await import('../server/advisor/tools/get_port_report.ts');
const {TRIP_TYPE_DAYS} = await import('../server/advisor/tools/get_trips.ts');
const {resolveLinks} = await import('../server/advisor/links.ts');

const DAILY = () => read('./fixtures/feeds/daily-latest.json');
const INTEL = () => read('./fixtures/feeds/intelligence.json');
const feedsFrom = (daily = DAILY(), intel = INTEL()) => async url => /intelligence\.json$/.test(url) ? intel : /latest\.json$/.test(url) ? daily : Promise.reject(Error('no feed'));
const FEED_NOW = Date.parse('2026-09-28T19:00:00Z');   // Mon 12:00 in Morro Bay: the fixtures' day
const dataCtx = (over = {}) => ({env: {}, contact: {id: 'c1', role: 'angler', home_port: 'morro-bay', ...(over.contact ?? {})}, message: {id: 'in1'},
  deps: {feeds: over.feeds ?? feedsFrom(), ...(over.fetcher ? {fetcher: over.fetcher} : {})}, db: over.db ?? null, language: 'en', settings: advisorSettings({}), now: over.now ?? FEED_NOW});
const COORD = /\d{2}\.\d{3,}|°/;

// The tests/test_evidence.mjs feed: seven days of lingcod reports from two boats with full page coverage.
function evidenceFeed(now) {
  const data = {schema_version: 1, generated_at: new Date(now).toISOString(), sources: {}, reports: [], health: {}, catch_probability: null, bite_score: null};
  for (let i = 1; i <= 7; i++) {
    const date = `2026-09-${21 - i}`;
    data.sources['catches-' + date] = {status: 'ok', data_retrieved_at: data.generated_at};
    data.reports.push({id: String(i), date, boat: 'Boat ' + (i % 2), catches: [{species: 'lingcod', count: 2}], ground_id: null});
  }
  return data;
}

test('confidence: the server ladder equals dist/bite-evidence.js on the test_evidence feeds and the daily fixture', async () => {
  // dist/bite-evidence.js reads the active region at import: give it one.
  globalThis.localStorage ??= {getItem: () => null, setItem: () => {}, removeItem: () => {}};
  const {reportEvidence: appEvidence, validFeed: appValidFeed} = await import('../dist/bite-evidence.js');
  const now = Date.parse('2026-09-21T16:00:00Z');
  const cases = [];
  const base = evidenceFeed(now);
  cases.push([base, 'lingcod', now], [base, 'halibut', now], [base, 'reef', now], [base, 'lingcod', now + 40 * 3600000]);
  const gap = evidenceFeed(now); gap.sources['catches-2026-09-20'].status = 'retained'; cases.push([gap, 'lingcod', now]);
  const zero = evidenceFeed(now); for (const r of zero.reports) r.catches[0].count = 0; cases.push([zero, 'lingcod', now]);
  const mixed = evidenceFeed(now); mixed.reports[0].catches.push({species: 'rockfish', count: 20}); mixed.reports[1].catches = [{species: 'rockfish', count: 10}];
  cases.push([mixed, 'reef', now], [mixed, 'lingcod', now], [mixed, 'rockfish', now]);
  for (const t of ['reef', 'lingcod', 'rockfish', 'halibut', 'salmon']) cases.push([DAILY(), t, FEED_NOW], [DAILY(), t, Date.parse('2026-09-28T03:00:00Z')]);
  for (const [feed, target, at] of cases) {
    const app = appEvidence(feed, target, at), server = serverEvidence(feed, target, at);
    for (const k of ['confidence', 'fresh', 'boats', 'days', 'coverage', 'start', 'end', 'named', 'catch_probability', 'bite_score']) assert.deepEqual(server[k], app[k], `${target} ${k}`);
    assert.deepEqual(server.reports.map(r => r.id), app.reports.map(r => r.id));
  }
  assert.equal(serverEvidence(base, 'lingcod', now).confidence, 'Moderate');
  assert.equal(serverEvidence(gap, 'lingcod', now).confidence, 'Low');
  assert.equal(serverEvidence(base, 'halibut', now).confidence, 'Insufficient');
  assert.equal(serverValidFeed(DAILY()), appValidFeed(DAILY()));
  assert.deepEqual(CONFIDENCE_WORDS, ['Insufficient', 'Low', 'Moderate']);
});

test('comfort: the server copy scores the 150 golden cases exactly as web/score.ts', async () => {
  const score = await import('../web/score.ts');
  const golden = read('./fixtures/score-golden.json');
  for (const [i, c] of golden.cases.entries()) {
    assert.equal(comfort.hourComfort(c.c, c.other, c.gust, c.factors), score.hourScores(c.c, c.other, score.controlModeFor(c.species), c.gust, c.factors).comfort, `case ${i}`);
    assert.equal(comfort.limitedComfort(c.c.wind ?? 0, c.c.sea.height ?? 0, c.gust, c.factors), score.limitedScores(c.c.wind ?? 0, c.c.sea.height ?? 0, c.gust, 'boat-comfort', c.factors).comfort, `limited ${i}`);
  }
  for (const k of Object.keys(comfort.COMFORT)) if (k in score.THRESHOLDS) assert.equal(comfort.COMFORT[k], score.THRESHOLDS[k], k);
  for (const r of [null, {conditions: 8}, {conditions: 7}, {conditions: 5}, {conditions: 3.9}, {conditions: 9, hazard: true}]) assert.equal(comfort.verdictFor(r), score.verdictFor(r));
  assert.deepEqual(comfort.REFERENCE_BOAT, {sea: 1, wind: 1, chopPeriod: 6});
  assert.ok(!Object.values(comfort.COMFORT_WORD).includes('go'), 'never a word that reads as a clearance');
});

test('dates: weekdays in English and Spanish, tomorrow/mañana, the weekend as two days, ISO, and the 7-day horizon', () => {
  const sat = Date.parse('2026-10-03T17:00:00Z');   // Saturday 10:00 Pacific
  const wed = Date.parse('2026-09-30T17:00:00Z');   // Wednesday
  const d = (text, now = wed) => conditions.parseTripDate(text, now);
  const table = [
    ['Saturday', ['2026-10-03']], ['sat', ['2026-10-03']], ['el sábado', ['2026-10-03']], ['sabado', ['2026-10-03']],
    ['domingo', ['2026-10-04']], ['Friday', ['2026-10-02']], ['viernes', ['2026-10-02']], ['wednesday', ['2026-09-30']],
    ['tomorrow', ['2026-10-01']], ['mañana', ['2026-10-01']], ['manana temprano', ['2026-10-01']], ['pasado mañana', ['2026-10-02']],
    ['today', ['2026-09-30']], ['hoy', ['2026-09-30']], ['this weekend', ['2026-10-03', '2026-10-04']], ['el fin de semana', ['2026-10-03', '2026-10-04']],
    ['2026-10-05', ['2026-10-05']], ['next thursday', ['2026-10-08']], ['', ['2026-09-30']],
  ];
  for (const [text, dates] of table) assert.deepEqual(d(text).dates, dates, text);
  assert.equal(d('').parsed, false);
  assert.deepEqual(d('this weekend', sat).dates, ['2026-10-03', '2026-10-04'], 'on Saturday the weekend is today and tomorrow');
  assert.deepEqual(d('weekend', Date.parse('2026-10-04T17:00:00Z')).dates, ['2026-10-04'], 'on Sunday only Sunday is left');
  assert.equal(d('2026-10-07').beyond_horizon, false);
  assert.equal(d('2026-10-08').beyond_horizon, true, 'eight days out');
  assert.equal(d('next thursday').beyond_horizon, true);
  assert.equal(d('2026-09-29').past, true);
});

test('ports and species: names, aliases and local words in English and Spanish', () => {
  const ports = [['MB', 'morro-bay'], ['out of Morro', 'morro-bay'], ['Morro Bay', 'morro-bay'], ['Cayucos', 'morro-bay'], ['Avila', 'port-san-luis'],
    ['Port San Luis', 'port-san-luis'], ['PSL', 'port-san-luis'], ['avila beach', 'port-san-luis'], ['Half Moon Bay', 'pillar-point'], ['santa cruz', 'santa-cruz'],
    ['desde Morro Bay mañana', 'morro-bay'], ['port-san-luis', 'port-san-luis'], ['Monterey', 'monterey'], ['the moon', null]];
  for (const [text, port] of ports) assert.equal(findPort(text), port, text);
  assert.deepEqual(resolvePort('what is biting', {home_port: 'port-san-luis'}), {port: 'port-san-luis', from: 'home_port'});
  assert.deepEqual(resolvePort('what is biting', {home_port: null}, {regionDefault: 'morro-bay'}), {port: 'morro-bay', from: 'default'});
  assert.deepEqual(resolvePort('Avila?', {home_port: 'morro-bay'}), {port: 'port-san-luis', from: 'text'});
  assert.deepEqual(landingNames('port-san-luis').sort(), ['Avila', 'Avila Beach', 'Port San Luis'], 'the daily feed calls PSL "Avila Beach"');
  const species = [['lings', 'lingcod'], ['ling cod', 'lingcod'], ['reds', 'vermilion'], ['vermilion', 'vermilion'], ['WSB', 'white-seabass'], ['white sea bass', 'white-seabass'],
    ['halis', 'halibut'], ['California halibut', 'halibut'], ['pacific halibut', 'pacific-halibut'], ['crab', 'dungeness'], ['cabbies', 'cabezon'], ['rock cod', 'rockfish'],
    ['lenguado', 'halibut'], ['cabezón', 'cabezon'], ['rocote', 'rockfish'], ['cangrejo', 'dungeness'], ['salmón', 'salmon'], ['kings', 'salmon'], ['calico', 'kelp-bass'],
    ['jurel', 'yellowtail'], ['lingcod', 'lingcod'], ['unicorn', null]];
  for (const [text, key] of species) assert.equal(resolveSpecies(text)?.key ?? null, key, text);
  const synonyms = read('../catalog/advisor/species-synonyms.json').species;
  const known = new Set([...read('../catalog/species.json').species.map(s => s.id), ...read('../catalog/advisor/species-extra.json').species.filter(e => !e.same_as_parent).map(e => e.key)]);
  for (const key of Object.keys(synonyms)) assert.ok(known.has(key), `${key} is a catalog or species-extra key`);
  const aliases = read('../catalog/advisor/port-aliases.json').ports, seen = new Map();
  assert.deepEqual(Object.keys(aliases).sort(), read('../catalog/home-ports.json').ports.map(p => p.id).sort(), 'every home port has an entry');
  for (const [id, a] of Object.entries(aliases)) for (const alias of a.aliases) { assert.ok(!seen.has(alias.toLowerCase()), `${alias} is shared`); seen.set(alias.toLowerCase(), id); }
});

test('conditions: the window parser reads wind, gusts, seas, swell and comfort from the intelligence fixture', async () => {
  const region = REGIONS['morro-bay'];
  const intel = INTEL(), day = conditions.windowConditions(intel, region, 'central', '2026-09-28', {start: 17, end: 19});
  assert.equal(day.available, true);
  // The same hours read with the trip checker's own sampler (server/alert-policy.ts samplePoint).
  const {samplePoint} = await import('../server/alert-policy.ts');
  const point = region.forecast_points.findIndex(p => p.id === 'central'), m = intel.forecast.models, times = m.gfs_global.data[point].hourly.time;
  const max = (model, key, unit) => Math.max(...times.map(t => samplePoint(m[model].data[point], key, t, unit)));
  const min = (model, key, unit) => Math.min(...times.map(t => samplePoint(m[model].data[point], key, t, unit)));
  assert.deepEqual(day.wind_kt, [Math.round(min('gfs_global', 'wind_speed_10m', 'kn')), Math.round(max('gfs_global', 'wind_speed_10m', 'kn'))]);
  assert.equal(day.gusts_kt, Math.round(max('gfs_global', 'wind_gusts_10m', 'kn')));
  const seas = times.map(t => Math.max(samplePoint(m.ncep_gfswave016.data[point], 'wave_height', t, 'ft'), samplePoint(m.ecmwf_wam.data[point], 'wave_height', t, 'ft')));
  assert.deepEqual(day.seas_ft, [Math.round(Math.min(...seas)), Math.round(Math.max(...seas))]);
  assert.deepEqual(day.swell_ft, [Math.round(min('ncep_gfswave016', 'swell_wave_height', 'ft')), Math.round(max('ncep_gfswave016', 'swell_wave_height', 'ft'))]);
  assert.equal(day.swell_period_s, Math.round(samplePoint(m.ncep_gfswave016.data[point], 'swell_wave_period', times[1], 's')));
  assert.equal(day.wind_from, conditions.compass(samplePoint(m.gfs_global.data[point], 'wind_direction_10m', times[1], '°')));
  assert.deepEqual([day.wind_kt, day.seas_ft, day.wind_from, day.swell_from], [[15, 19], [7, 7], 'NW', 'S'], 'the values themselves');
  // Comfort: the rubric on the roughest hour, for the reference boat.
  const worst = Math.min(...times.map(t => conditions.rateHour(conditions.readHour(intel, point, t))));
  assert.equal(day.comfort, comfort.COMFORT_WORD[comfort.verdictFor({conditions: worst})]);
  assert.equal(day.comfort, 'rough');
  assert.equal(day.comfort_for, 'a mid-size center console');
  const none = conditions.windowConditions(INTEL(), region, 'central', '2026-09-29');
  assert.equal(none.available, false);
  assert.match(none.reason, /does not cover/);
  assert.equal(conditions.windowConditions({...INTEL(), region_id: 'elsewhere'}, region, 'central', '2026-09-28', {start: 17, end: 19}).available, false);
  assert.equal(conditions.windowConditions(INTEL(), region, 'nowhere', '2026-09-28', {start: 17, end: 19}).available, false);
});

test('conditions: advisories come from the daily feed alerts for the region zones and only when they overlap the window', () => {
  const zones = conditions.regionZones(REGIONS['morro-bay']);
  assert.deepEqual(zones, ['PZZ645', 'PZZ670']);
  const [from, to] = conditions.windowEpochs('2026-09-28', 'America/Los_Angeles');
  assert.equal(new Date(from).toISOString(), '2026-09-28T13:00:00.000Z');
  const hits = conditions.advisoriesFrom(DAILY(), zones, from, to);
  assert.deepEqual(hits.map(a => [a.event, a.zone]), [['Small Craft Advisory', 'PZZ645']]);
  const [nf, nt] = conditions.windowEpochs('2026-09-29', 'America/Los_Angeles');
  assert.deepEqual(conditions.advisoriesFrom(DAILY(), zones, nf, nt), [], 'ended the night before');
  const daily = DAILY();
  daily.sources['alerts-PZZ645'].data.alerts.push({event: 'Gale Warning', onset: '2026-09-28T08:00:00-07:00', ends: '2026-09-28T20:00:00-07:00'},
    {event: 'Rip Current Statement', onset: '2026-09-28T08:00:00-07:00'});
  assert.deepEqual(conditions.advisoriesFrom(daily, zones, from, to).map(a => a.event), ['Gale Warning', 'Small Craft Advisory'], 'gale first; not boating alerts dropped');
});

test('get_conditions: advisory first, the window and comfort word, the horizon, and no percent sign anywhere', async () => {
  const tool = TOOL_BY_NAME.get('get_conditions');
  const out = (await tool.run({port: 'port-san-luis', date: 'today'}, dataCtx())).result;
  assert.equal(out.port, 'port-san-luis');
  assert.deepEqual(out.dates, ['2026-09-28']);
  assert.equal(out.lead_with_advisory, true);
  assert.equal(Object.keys(out).indexOf('advisories') < Object.keys(out).indexOf('days'), true, 'advisories come before the numbers');
  assert.equal(out.advisories[0].event, 'Small Craft Advisory');
  assert.match(out.note, /SMALL CRAFT ADVISORY/);
  assert.match(out.note, /Check the latest NWS forecast before you go\./);
  const evening = (await tool.run({port: 'MB', date: '2026-09-28', start_hour: 17, end_hour: 19}, dataCtx())).result;
  assert.equal(evening.port, 'morro-bay', 'an alias resolves');
  assert.deepEqual([evening.days[0].wind_kt, evening.days[0].comfort], [[15, 19], 'rough']);
  for (const r of [out, evening]) assert.doesNotMatch(JSON.stringify(r), /\d\s*%/);
  const far = (await tool.run({port: 'morro-bay', date: 'next thursday'}, dataCtx({now: Date.parse('2026-09-30T17:00:00Z')}))).result;
  assert.deepEqual([far.beyond_horizon, far.days], [true, undefined]);
  const weekend = (await tool.run({port: 'morro-bay', date: 'fin de semana'}, dataCtx())).result;
  assert.deepEqual(weekend.dates, ['2026-10-03', '2026-10-04']);
  assert.equal(weekend.days.length, 2);
  const noFeeds = (await tool.run({port: 'morro-bay', date: 'today'}, dataCtx({feeds: async () => { throw Error('offline'); }}))).result;
  assert.deepEqual([noFeeds.advisories_checked, noFeeds.days[0].available], [false, false]);
  assert.match(noFeeds.note, /could not be checked/);
});

/** Seed a boat and its published reports. */
function seedBoats(sql) {
  const iso = '2026-09-01T00:00:00Z';
  const boat = (id, slug, name, status, port = 'morro-bay', booking = null) => sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,booking_url,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)`)
    .run(id, slug, name, 'Example Landing', port, 'morro-bay', booking, status, iso, iso);
  const report = (id, boatId, date, verified, tripType, status = 'published', port = 'morro-bay') => sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,published_at,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, boatId, 'morro-bay', port, date, tripType, 20,
      JSON.stringify([{species_key: 'rockfish', label: 'vermilion', kept: 40, released: 0}, {species_key: 'lingcod', label: 'lings', kept: 8, released: 2}]), `text-${id}`, status, verified, `${date}T22:00:00Z`, iso, iso);
  boat('b1', 'example-one', 'Example Boat One', 'verified', 'morro-bay', 'https://example.com/book');
  boat('b2', 'example-two', 'Example Boat Two', 'pending');
  boat('b3', 'example-three', 'Example Boat Three', 'verified', 'morro-bay', 'http://example.com/insecure');
  boat('b4', 'example-four', 'Example Boat Four', 'verified', 'port-san-luis');
  report('r1', 'b1', '2026-09-27', 1, 'full-day');
  report('r2', 'b2', '2026-09-26', 0, 'half-day');
  report('r3', 'b1', '2026-09-10', 1, 'half-day');     // 18 days old: not a "recent" report, but a trip type
  report('r4', 'b1', '2026-09-25', 1, null, 'draft');
  report('r5', 'b3', '2026-06-01', 1, 'overnight');     // older than 60 days
  report('r6', 'b1', '2026-09-20', 1, 'full-day');
  for (let i = 0; i < 6; i++) report(`m${i}`, 'b1', `2026-09-2${i}`, 1, 'full-day', 'published', 'morro-bay');
}

dbTest('get_port_report: the day\'s answer (composed when none is stored, never a second model call), five recent published skipper reports (unverified as "a boat", 14 days), the landing reports with their label', async () => {
  const {sql, db} = advisorDatabase();
  seedBoats(sql);
  const noModel = async () => { throw Error('get_port_report must not call the model'); };
  const out = (await TOOL_BY_NAME.get('get_port_report').run({port: 'Morro'}, dataCtx({db, fetcher: noModel}))).result;
  assert.equal(out.port, 'morro-bay');
  // TA-A1: no stored answer yet, so the same facts composed without a model call, and nothing stored.
  assert.equal(out.daily.source, 'composed');
  assert.match(out.daily.text, /^Morro Bay, Mon Sep 28: SMALL CRAFT ADVISORY posted for today\. Example Boat One reported yesterday: 40 vermilion, 8 lings\. Another boat reported Sat: /);
  assert.ok(out.daily.text.endsWith('https://skippercast.com/ports/morro-bay?s=txt'));
  assert.ok(out.daily.text.length <= 480);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_daily_answers').get().n, 0, 'the tool never stores a composed answer');
  assert.equal(out.skipper_reports.length, 5);
  assert.ok(out.skipper_reports.every(r => r.date >= '2026-09-14'), `at most ${MAX_REPORT_AGE_DAYS} days`);
  assert.deepEqual(out.skipper_reports.map(r => r.date), [...out.skipper_reports.map(r => r.date)].sort().reverse(), 'newest first');
  const anon = out.skipper_reports.find(r => !r.verified);
  assert.deepEqual([anon.boat, anon.boat_link], ['a boat', undefined]);
  const named = out.skipper_reports.find(r => r.verified);
  assert.deepEqual([named.boat, named.boat_link], ['Example Boat One', '{{link:boat:example-one}}']);
  assert.equal(out.skipper_reports[0].age, 'yesterday');
  assert.ok(!JSON.stringify(out).includes('Example Boat Two'), 'an unverified boat is never named');
  assert.ok(!out.skipper_reports.some(r => r.date === '2026-09-25' && r.trip_type === null), 'drafts are not reports');
  assert.equal(out.landing.label, 'reported by the landing');
  assert.deepEqual(out.landing.reports.map(r => r.boat), ['Starfire'], 'only Morro Bay\'s landing reports');
  assert.deepEqual(out.landing.recent_activity.find(a => a.target === 'reef'), {target: 'reef', species: ['lingcod', 'rockfish'], confidence: 'Low', trips: 1, boats: 1, days: 1});
  assert.equal(out.freshness.newest_landing_report, '2026-09-27');
  assert.equal(out.catch_probability, null);
  assert.doesNotMatch(JSON.stringify(out), /\d\s*%|probab(?!ility":null)/i);
  const psl = (await TOOL_BY_NAME.get('get_port_report').run({port: 'port-san-luis'}, dataCtx({db}))).result;
  assert.deepEqual(psl.landing.reports.map(r => r.boat), ['Sunny Day'], 'the feed\'s "Avila Beach" is Port San Luis');
  const offline = (await TOOL_BY_NAME.get('get_port_report').run({port: 'morro-bay'}, dataCtx({db, feeds: async () => { throw Error('down'); }}))).result;
  assert.deepEqual(offline.landing, {available: false});
  // A stored answer whose inputs are current is returned as it is.
  const {currentInputsHash} = await import('../server/advisor/answers/reports.ts');
  const hash = await currentInputsHash({DB: db}, 'morro-bay', '2026-09-28', {feeds: feedsFrom()}, FEED_NOW);
  sql.prepare("INSERT INTO advisor_daily_answers(key,text_en,text_es,inputs_hash,generated_at) VALUES('morro-bay:2026-09-28','Stored en','Stored es',?,?)").run(hash, '2026-09-28T12:30:00Z');
  const stored = (await TOOL_BY_NAME.get('get_port_report').run({port: 'morro-bay'}, dataCtx({db, fetcher: noModel}))).result;
  assert.deepEqual([stored.daily.source, stored.daily.text], ['stored', 'Stored en']);
  const storedEs = (await TOOL_BY_NAME.get('get_port_report').run({port: 'morro-bay'}, {...dataCtx({db, fetcher: noModel}), language: 'es'})).result;
  assert.equal(storedEs.daily.text, 'Stored es');
  // TA-A6: the landing's attribution label in the reply language.
  assert.equal(storedEs.landing.label, 'reportado por el muelle');
});

test('get_species: catalog claims with sources, look-alike cues, the group, and the release note; no rule', async () => {
  const tool = TOOL_BY_NAME.get('get_species');
  const verm = (await tool.run({species_key: 'reds'})).result;
  assert.equal(verm.species_key, 'vermilion');
  assert.deepEqual(verm.group, {species_key: 'rockfish', name: 'Rockfish'});
  assert.ok(verm.claims.length && verm.claims.every(c => /^https:\/\//.test(c.source)));
  assert.deepEqual(verm.lookalikes.map(l => l.species_key), ['canary', 'yelloweye']);
  assert.ok(verm.identify.cues.length >= 2);
  assert.equal(verm.protected, null);
  const ye = (await tool.run({species_key: 'yelloweye'})).result;
  assert.equal(ye.protected.must_release, true);
  const hal = (await tool.run({species_key: 'California halibut'})).result;
  assert.equal(hal.species_key, 'halibut');
  assert.ok(hal.identify, 'halibut uses california-halibut\'s cues');
  for (const r of [verm, ye, hal]) assert.doesNotMatch(JSON.stringify(r), /\b\d+\s*(?:in|inch|inches)\b|bag limit/i);
  assert.deepEqual((await tool.run({species_key: 'unicorn'})).result.error, 'unknown species');
  // TA-A6: in Spanish the cues are lookalikes.json's cues_es.
  const es = (await tool.run({species_key: 'colorado'}, {language: 'es'})).result;
  assert.equal(es.identify.cues[0], 'cuerpo rojo con manchas grises u oscuras');
  assert.equal(es.lookalikes[0].cues.at(-1), 'mandíbula inferior lisa');
});

test('public grounds: every allowlisted name is a charter-grounds label and carries no coordinate', () => {
  const labels = new Set(read('../dist/data/charter-grounds.json').grounds.map(g => g.label));
  const allow = read('../catalog/advisor/public-grounds.json');
  for (const [region, list] of Object.entries(allow.regions)) {
    assert.ok(REGIONS[region] || region === 'morro-bay', region);
    for (const g of list) {
      assert.ok(labels.has(g.name), `${g.name} is a published charter-ground name`);
      assert.ok(['reef', 'bank', 'edge'].includes(g.kind));
      assert.doesNotMatch(JSON.stringify(g), COORD, g.name);
      assert.equal(g.general_depth_ft.length, 2);
    }
  }
});

test('get_strategy: rig and areas from the catalogs; only allowlisted names; never a coordinate; missing fields stay null', async () => {
  const plans = read('../dist/regions/morro-bay/search-plans.json');
  const planNames = [...new Set(plans.features.map(f => f.properties.name))];
  assert.ok(planNames.includes('SC-AREA-001') && planNames.includes('Estero Bay shallow sand & mud'));
  const all = [];
  for (const key of ['lingcod', 'rockfish', 'vermilion', 'halibut', 'salmon', 'dungeness', 'albacore', 'bluefin', 'reef']) {
    const s = advice.strategyFor(key, 'morro-bay', [...planNames, 'Secret Hole', 'Capt. Example\'s pinnacle']);
    assert.ok(s, key);
    all.push(s);
    for (const a of s.areas) assert.ok(read('../catalog/advisor/public-grounds.json').regions['morro-bay'].some(g => g.name === a.name), `${a.name} is allowlisted`);
    const text = JSON.stringify(s);
    assert.doesNotMatch(text, COORD, key);
    for (const n of ['SC-AREA', 'Secret Hole', 'pinnacle', 'Estero Bay shallow sand & mud']) assert.ok(!text.includes(n), `${n} dropped for ${key}`);
  }
  const ling = all[0];
  assert.deepEqual(ling.areas.map(a => a.name), ['Pecho Rock', 'Diablo coast', 'Morro Bay coast']);
  assert.match(ling.rig, /dropper-loop/);
  assert.match(ling.bait_or_lure, /swimbait/);
  assert.equal(ling.line, null, 'the catalogs give no line spec: null, never invented');
  assert.deepEqual(ling.depth_band_ft, [25, 195]);
  assert.ok(ling.source_notes.length);
  assert.deepEqual(all[3].areas, [], 'no public halibut ground: no area names');
  assert.deepEqual(advice.publicAreas('southern-california', 'lingcod', ['Pecho Rock']), [], 'the allowlist is per region');
  assert.equal(advice.publicOnly('Fish 35.17938, -120.81661 at dawn. Drift the edge.'), 'Drift the edge.');
  assert.equal(advice.publicOnly('Try 35° 10.5′ N.'), null);
});

dbTest('get_strategy: first_time until the contact has asked a strategy question, then not; the AD-2 line is in the prompt', async () => {
  const {sql, db} = advisorDatabase();
  const tool = TOOL_BY_NAME.get('get_strategy');
  const first = (await tool.run({species_key: 'lings'}, dataCtx({db}))).result;
  assert.equal(first.species_key, 'lingcod');
  assert.equal(first.first_time, true);
  assert.ok(first.note.includes(AD2_LINE));
  assert.doesNotMatch(JSON.stringify(first), COORD);
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,intent,status,created_at) VALUES('old','c1','in','imessage','rig?','strategy','done','2026-09-01T00:00:00Z')`).run();
  const again = (await tool.run({species_key: 'halibut'}, dataCtx({db}))).result;
  assert.equal(again.first_time, false);
  assert.ok(!again.note.includes(AD2_LINE));
  const {systemPrompt, REQUIRED_PHRASES} = await import('../server/advisor/prompts/system.ts');
  assert.ok(REQUIRED_PHRASES.includes(AD2_LINE));
  assert.ok(systemPrompt('en').includes(AD2_LINE) && systemPrompt('es').includes(AD2_LINE));
  // Search-plan names read from ASSETS pass through the allowlist too.
  const assets = {fetch: async () => Response.json({features: [{properties: {name: 'SC-AREA-007', species: ['reef']}}, {properties: {name: 'Pecho Rock', species: ['reef']}}]})};
  const viaAssets = (await tool.run({species_key: 'rockfish'}, {...dataCtx({db}), env: {ASSETS: assets}})).result;
  assert.ok(!JSON.stringify(viaAssets).includes('SC-AREA'));
  assert.equal(viaAssets.areas[0].name, 'Pecho Rock', 'a named plan area that is allowlisted comes first');
});

// ---- TA-A2: the planning brief (06 § planning, FR-2, AD-4) --------------------------------------

const planning = await import('../server/advisor/answers/planning.ts');
const {statesRuleNumber} = await import('../server/advisor/reply.ts');
const LADDER = /\b(?:Insufficient|Low|Moderate|High)\b/g;
/** A rules row as scripts/advisor/import-rules.mjs writes it (jurisdiction-wide). */
function addRule(sql, key, over = {}) {
  const r = {season_open: '04-01', season_close: '12-31', bag_limit: 10, status: 'active', reviewed_at: '2026-09-01', review_due: '2026-12-31', ...over};
  sql.prepare(`INSERT INTO advisor_rules(id,region,jurisdiction,species_key,species_label,bag_limit,season_open,season_close,source_name,source_url,reviewed_at,review_due,status,updated_by,updated_at)
    VALUES(?,'*','california-central',?,?,?,?,?,'CDFW Central Region rules','https://wildlife.ca.gov/Fishing/Ocean',?,?,?,'test','2026-09-01T00:00:00Z')`)
    .run(`rule-${key}`, key, key, r.bag_limit, r.season_open, r.season_close, r.reviewed_at, r.review_due, r.status);
}
/** The daily fixture with its NWS alert moved to [onset, ends] (local ISO times). */
function alertFeed(onset, ends) {
  const daily = DAILY();
  const alert = daily.sources['alerts-PZZ645'].data.alerts[0];
  Object.assign(alert, {sent: onset, effective: onset, onset, expires: ends, ends});
  return daily;
}
const plan = (input, over = {}) => TOOL_BY_NAME.get('get_conditions').run(input, {...dataCtx(over), ...(over.language ? {language: over.language} : {})}).then(r => r.result);

dbTest('planning brief: advisory first, then the season, the recent reports, one ladder phrase and the closer; no percentage', async () => {
  const {sql, db} = advisorDatabase();
  seedBoats(sql);
  addRule(sql, 'rockfish');
  const out = await plan({port: 'morro-bay', date: 'today', species: 'rockfish'}, {db});
  const keys = Object.keys(out);
  assert.ok(keys.indexOf('advisory_line') < keys.indexOf('days') && keys.indexOf('days') < keys.indexOf('planning'), 'the advisory comes before the numbers and the brief');
  assert.equal(out.advisory_line, 'SMALL CRAFT ADVISORY posted for today.');
  assert.equal(out.lead_with_advisory, true);
  const p = out.planning;
  assert.deepEqual([p.species_key, p.species_name], ['rockfish', 'rockfish']);
  assert.deepEqual([p.season.status, p.season.stale, p.season.checked], ['open', false, '2026-09-01']);
  assert.equal(p.season.line, 'The rockfish season shows open for that day. Sizes and limits: {{link:rules:rockfish}}');
  // The daily answer's inputs: published reports of the last three days, the unverified boat as "a boat", only rockfish lines.
  assert.deepEqual(p.recent_activity.skipper_reports.map(r => [r.date, r.boat, r.counts.map(c => c.label)]),
    [['2026-09-27', 'Example Boat One', ['vermilion']], ['2026-09-26', 'a boat', ['vermilion']], ['2026-09-25', 'Example Boat One', ['vermilion']]]);
  assert.equal(p.recent_activity.skipper_reports[0].day, 'Sun');
  assert.deepEqual([p.recent_activity.landing.label, p.recent_activity.landing.trips], ['reported by the landing', 1]);
  assert.deepEqual([p.confidence, p.confidence_phrase], ['Low', 'recent reported activity: Low']);
  assert.equal(p.closer, 'Check the latest NWS forecast before you go.');
  assert.match(p.note, /advisory_line first/);
  const json = JSON.stringify(out);
  assert.doesNotMatch(json, /\d\s*%/);
  assert.doesNotMatch(json, /\bprobab|\bchance|\bodds\b|\blikely\b|\bhotspot/i);
  assert.deepEqual(json.match(LADDER), ['Low', 'Low'], 'one ladder word, in confidence and its phrase only');
  for (const line of [p.season.line, out.advisory_line, p.confidence_phrase, p.closer]) assert.equal(statesRuleNumber(line), false, line);
  assert.ok(json.length < 4000, `fits the engine's 4000-character tool result (${json.length})`);
  // A long brief is trimmed to fit the engine's tool-result limit (a cut JSON would not parse): headlines first, then old reports.
  const counts = Array.from({length: 10}, () => ({label: 'vermilion rockfish', kept: 10, released: 1}));
  const big = {filler: 'y'.repeat(2200), advisories: Array.from({length: 4}, () => ({event: 'Gale Warning', headline: 'x'.repeat(200), zone: 'PZZ645', onset: null, ends: null})),
    planning: {recent_activity: {skipper_reports: Array.from({length: 3}, () => ({date: '2026-09-27', day: 'Sun', boat: 'B', counts: [...counts]}))}}};
  const fitted = planning.fit(big);
  assert.ok(JSON.stringify(fitted).length <= 3900);
  assert.deepEqual([fitted.advisories.length, fitted.advisories[0].headline, fitted.planning.recent_activity.skipper_reports.length], [4, null, 2]);
  // Without a species, get_conditions is what it was: no brief.
  const plain = await plan({port: 'morro-bay', date: 'today'}, {db});
  assert.equal(plain.planning, undefined);
  assert.equal(plain.advisory_line, out.advisory_line);
});

dbTest('planning brief: a closed season comes first in the note; a stale row says double-check; no row sends to CDFW', async () => {
  const {sql, db} = advisorDatabase();
  addRule(sql, 'lingcod', {season_open: '2026-04-01', season_close: '2026-09-15'});
  addRule(sql, 'halibut', {status: 'review'});
  addRule(sql, 'rockfish', {season_open: '2026-04-01', season_close: '2026-09-15', review_due: '2026-09-01'});
  const ling = (await plan({port: 'morro-bay', date: 'today', species: 'lings'}, {db})).planning;
  assert.deepEqual([ling.species_key, ling.season.status, ling.season.stale], ['lingcod', 'closed', false]);
  assert.equal(ling.season.line, 'The lingcod season is closed for that day: {{link:rules:lingcod}}');
  assert.match(ling.note, /advisory_line first.*then a closed season/);
  const hali = (await plan({port: 'morro-bay', date: 'today', species: 'halibut'}, {db})).planning;
  assert.deepEqual([hali.season.status, hali.season.stale], ['open', true]);
  assert.match(hali.season.line, /due for review, so double-check before you go/);
  const reds = (await plan({port: 'morro-bay', date: 'today', species: 'vermilion'}, {db})).planning;
  assert.deepEqual([reds.season.status, reds.season.stale], ['closed', true], 'a vermilion uses the rockfish row, past its review date');
  assert.match(reds.season.line, /shows closed for that day, but that rule is due for review, so double-check/);
  assert.equal(reds.confidence, 'Low', 'the landing\'s rockfish trip counts for a vermilion');
  const salmon = (await plan({port: 'morro-bay', date: 'today', species: 'salmon'}, {db})).planning;
  assert.deepEqual([salmon.season.status, salmon.confidence], ['no_rule', 'Insufficient']);
  assert.equal(salmon.season.line, 'I have no reviewed rule for Chinook salmon, so check the current CDFW rules: {{link:rules:salmon}}');
  const crab = (await plan({port: 'morro-bay', date: 'today', species: 'cangrejo'}, {db})).planning;
  assert.deepEqual([crab.species_key, crab.confidence], ['dungeness', 'Insufficient'], 'boat reports are no crab evidence');
  const unknown = (await plan({port: 'morro-bay', date: 'today', species: 'unicorn fish'}, {db})).planning;
  assert.deepEqual([unknown.species_key, unknown.season, unknown.confidence], [null, null, 'Insufficient']);
  assert.match(unknown.note, /not recognised/);
});

dbTest('planning brief: beyond seven days says so with no numbers; the weekend is two days with the advisory on the day it covers', async () => {
  const {db} = advisorDatabase();
  const wed = Date.parse('2026-09-30T17:00:00Z');
  const far = await plan({port: 'morro-bay', date: 'next thursday', species: 'rockfish'}, {db, now: wed});
  assert.deepEqual([far.beyond_horizon, far.days, far.advisories], [true, undefined, undefined]);
  assert.equal(far.horizon_line, "The forecast only reaches 7 days out, so I can't call the weather for Thu yet. Ask me again closer to the day.");
  assert.equal(far.planning.season.status, 'no_rule', 'the season and the recent activity still come back');
  const fri = Date.parse('2026-10-02T19:00:00Z');
  const satOnly = feedsFrom(alertFeed('2026-10-03T12:00:00-07:00', '2026-10-03T23:00:00-07:00'));
  const weekend = await plan({port: 'morro-bay', date: 'this weekend', species: 'rockfish'}, {db, now: fri, feeds: satOnly});
  assert.deepEqual(weekend.dates, ['2026-10-03', '2026-10-04']);
  assert.equal(weekend.days.length, 2);
  assert.equal(weekend.advisory_line, 'SMALL CRAFT ADVISORY posted for tomorrow.');
  const both = feedsFrom(alertFeed('2026-10-03T12:00:00-07:00', '2026-10-04T23:00:00-07:00'));
  assert.equal((await plan({port: 'morro-bay', date: 'this weekend', species: 'rockfish'}, {db, now: Date.parse('2026-09-30T17:00:00Z'), feeds: both})).advisory_line,
    'SMALL CRAFT ADVISORY posted for Sat and Sun.');
  const es = await plan({port: 'morro-bay', date: 'el fin de semana', species: 'rocote'}, {db, now: Date.parse('2026-09-30T17:00:00Z'), feeds: both, language: 'es'});
  assert.equal(es.advisory_line, 'SMALL CRAFT ADVISORY (aviso del NWS) para el sábado y el domingo.');
  assert.deepEqual([es.planning.species_name, es.planning.confidence_phrase, es.planning.closer],
    ['rocote', 'actividad reciente reportada: Low', 'Revisa el pronóstico más reciente del NWS antes de salir.']);
  assert.equal(es.planning.season.line, 'No tengo una regla revisada para rocote, así que revisa las reglas vigentes de CDFW: {{link:rules:rockfish}}');
  assert.equal(es.planning.recent_activity.landing.label, 'reportado por el muelle', 'TA-A6: the brief is in the reply language throughout');
  const calm = await plan({port: 'morro-bay', date: 'this weekend', species: 'rockfish'}, {db, now: Date.parse('2026-10-05T17:00:00Z')});
  assert.deepEqual([calm.lead_with_advisory, calm.advisory_line], [false, undefined]);
  for (const r of [far, weekend, es, calm]) assert.doesNotMatch(JSON.stringify(r), /\d\s*%/);
});

dbTest('planning brief: the ladder is the landing\'s for the species (Moderate on the test_evidence feed); a skipper report lifts Insufficient to Low, never further', async () => {
  const {sql, db} = advisorDatabase();
  const now = Date.parse('2026-09-21T19:00:00Z');
  const feed = evidenceFeed(now);
  for (const r of feed.reports) r.port = 'Morro Bay';
  const ling = (await plan({port: 'morro-bay', date: 'today', species: 'lingcod'}, {db, now, feeds: feedsFrom(feed)})).planning;
  assert.deepEqual([ling.confidence, ling.confidence_phrase], ['Moderate', 'recent reported activity: Moderate']);
  assert.equal(ling.recent_activity.landing.trips, 7);
  const rock = (await plan({port: 'morro-bay', date: 'today', species: 'rockfish'}, {db, now, feeds: feedsFrom(feed)})).planning;
  assert.equal(rock.confidence, 'Insufficient', 'lingcod trips are not rockfish evidence');
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,status,created_at,updated_at) VALUES('b1','example-one','Example Boat One','Example Landing','morro-bay','morro-bay','verified','2026-09-01','2026-09-01')`).run();
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,published_at,created_at,updated_at)
    VALUES('r1','b1','morro-bay','morro-bay','2026-09-20','full-day',20,?,'text-r1','published',1,'2026-09-20T22:00:00Z','2026-09-20','2026-09-20')`)
    .run(JSON.stringify([{species_key: 'rockfish', label: 'vermilion', kept: 30, released: 0}]));
  const lifted = (await plan({port: 'morro-bay', date: 'today', species: 'rockfish'}, {db, now, feeds: feedsFrom(feed)})).planning;
  assert.deepEqual([lifted.confidence, lifted.recent_activity.skipper_reports.length], ['Low', 1]);
  for (const p of [ling, rock, lifted]) {
    assert.ok(CONFIDENCE_WORDS.includes(p.confidence));
    assert.equal(JSON.stringify(p).match(LADDER).length, 2, 'exactly one confidence phrase');
  }
});

test('leadsWithAdvisory: the event in capitals in the first sentence', () => {
  const ev = ['Small Craft Advisory'];
  assert.equal(planning.leadsWithAdvisory('SMALL CRAFT ADVISORY posted for Sat. Seas 7 ft.', ev), true);
  assert.equal(planning.leadsWithAdvisory('Hay SMALL CRAFT ADVISORY el sábado. Olas de 7 pies.', ev), true, 'Spanish keeps the NWS name');
  assert.equal(planning.leadsWithAdvisory('Seas 7 ft. SMALL CRAFT ADVISORY posted for Sat.', ev), false, 'not first');
  assert.equal(planning.leadsWithAdvisory('Small craft advisory for Sat.', ev), false, 'not in capitals');
});

dbTest('get_trips: verified boats only, by most recent report; trip types from 60 days; few when under two; https booking links only', async () => {
  const {sql, db} = advisorDatabase();
  seedBoats(sql);
  const tool = TOOL_BY_NAME.get('get_trips');
  const out = (await tool.run({port: 'MB'}, dataCtx({db}))).result;
  assert.deepEqual(out.boats.map(b => b.name), ['Example Boat One', 'Example Boat Three']);
  assert.equal(out.few, false);
  const one = out.boats[0];
  assert.deepEqual(one.trip_types, ['full-day', 'half-day']);
  assert.deepEqual([one.booking_url, one.boat_page, one.landing], ['https://example.com/book', '{{link:boat:example-one}}', 'Example Landing']);
  assert.deepEqual([out.boats[1].trip_types, out.boats[1].booking_url], [[], null], 'old trips and an http link are left out');
  assert.ok(!JSON.stringify(out).includes('Example Boat Two'), 'pending boats are not listed');
  const psl = (await tool.run({port: 'Avila'}, dataCtx({db}))).result;
  assert.deepEqual([psl.boats.map(b => b.name), psl.few], [['Example Boat Four'], true]);
  assert.match(psl.note, /the boats I work with so far/);
  const none = (await tool.run({port: 'monterey'}, dataCtx({db}))).result;
  assert.deepEqual([none.boats, none.few, none.link], [[], true, '{{link:port:monterey}}']);
});

// ---- TA-A5: get_trips, clause by clause (06 § trips for newcomers, AD-3) ------------------------

/** Boats whose name order differs from their report order, plus the statuses and reports each 06 clause turns on. */
function seedTrips(sql, {extra = 0} = {}) {
  const iso = '2026-07-01T00:00:00Z';
  const boat = (id, name, status, {landing = 'Example Landing', booking = null, port = 'morro-bay'} = {}) => sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,booking_url,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)`)
    .run(id, `slug-${id}`, name, landing, port, 'morro-bay', booking, status, iso, iso);
  const report = (id, boatId, date, tripType, status = 'published') => sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,published_at,created_at,updated_at)
      VALUES(?,?,'morro-bay','morro-bay',?,?,20,'[]',?,?,1,?,?,?)`).run(id, boatId, date, tripType, `text-${id}`, status, status === 'published' ? `${date}T22:00:00Z` : null, iso, iso);
  boat('alpha', 'Alpha Example', 'verified', {booking: 'https://example.com/alpha'});
  boat('zulu', 'Zulu Example', 'verified', {landing: 'Other Landing'});
  boat('mike', 'Mike Example', 'verified', {landing: null});
  boat('rej', 'Rejected Example', 'rejected');
  boat('pend', 'Pending Example', 'pending');
  report('a1', 'alpha', '2026-09-10', 'full-day');
  report('a2', 'alpha', '2026-07-30', 'overnight');    // exactly 60 days before 2026-09-28: in
  report('a3', 'alpha', '2026-07-29', 'half-day');     // 61 days: out
  report('z1', 'zulu', '2026-09-27', 'half-day');
  report('z2', 'zulu', '2026-09-28', 'overnight', 'draft');            // a draft is not a report
  report('z3', 'zulu', '2026-09-26', 'full-day', 'withdrawn');
  report('r1', 'rej', '2026-09-28', 'full-day');
  report('p1', 'pend', '2026-09-28', 'full-day');
  for (let i = 0; i < extra; i++) { boat(`x${i}`, `Extra ${String(i).padStart(2, '0')}`, 'verified'); report(`x${i}`, `x${i}`, '2026-09-01', 'full-day'); }
}

dbTest('get_trips (06 § trips): verified boats only, with landing, https booking link and boat page; trip types from the last 60 days; newest report first; never ranked', async () => {
  const {sql, db} = advisorDatabase();
  seedTrips(sql);
  const out = (await TOOL_BY_NAME.get('get_trips').run({port: 'morro-bay'}, dataCtx({db}))).result;
  // Verified boats only: rejected and pending boats never appear, even with the newest reports.
  assert.deepEqual(out.boats.map(b => b.name), ['Zulu Example', 'Alpha Example', 'Mike Example'], 'by most recent published report, not by name; no report last');
  assert.ok(!/Rejected Example|Pending Example/.test(JSON.stringify(out)));
  const [zulu, alpha, mike] = out.boats;
  // Landing, booking link (https only) and the boat page placeholder, which links.ts resolves to the boat page.
  assert.deepEqual([zulu.landing, alpha.landing, mike.landing], ['Other Landing', 'Example Landing', null]);
  assert.deepEqual([alpha.booking_url, zulu.booking_url], ['https://example.com/alpha', null]);
  assert.equal(alpha.boat_page, '{{link:boat:slug-alpha}}');
  assert.equal(resolveLinks(`Book or read more: ${alpha.boat_page}`, 'https://skippercast.com').text, 'Book or read more: https://skippercast.com/boats/slug-alpha?s=txt');
  // Trip types: distinct values from published reports of the last 60 days (the 60th day counts, the 61st does not; drafts and withdrawn reports never).
  assert.deepEqual(alpha.trip_types, ['full-day', 'overnight']);
  assert.deepEqual(zulu.trip_types, ['half-day']);
  assert.deepEqual(mike.trip_types, []);
  assert.deepEqual([zulu.last_report, alpha.last_report, mike.last_report], ['2026-09-27', '2026-09-10', null], 'a draft never counts as the latest report');
  assert.equal(TRIP_TYPE_DAYS, 60);
  // Never ranks: no score, rating or "best" anywhere, and the note says the order is not a ranking.
  for (const b of out.boats) assert.deepEqual(Object.keys(b).sort(), ['boat_page', 'booking_url', 'landing', 'last_report', 'name', 'trip_types']);
  assert.doesNotMatch(JSON.stringify(out), /\b(?:rank(?!ed)|score|rating|best|top pick|recommended)\b/i);
  assert.match(out.note, /not ranked/); assert.match(out.note, /Never recommend one boat over another/);
  assert.deepEqual([out.few, out.link], [false, '{{link:port:morro-bay}}']);
});

dbTest('get_trips (06 § trips): under two verified boats is few with the port link; two is not; at most twelve boats', async () => {
  const one = advisorDatabase();
  one.sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at) VALUES('b1','only-one','Only Example','morro-bay','morro-bay','verified','2026-09-01','2026-09-01')`).run();
  one.sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at) VALUES('b2','not-yet','Not Yet Example','morro-bay','morro-bay','pending','2026-09-01','2026-09-01')`).run();
  const few = (await TOOL_BY_NAME.get('get_trips').run({port: 'Morro Bay'}, dataCtx({db: one.db}))).result;
  assert.deepEqual([few.boats.map(b => b.name), few.few, few.link], [['Only Example'], true, '{{link:port:morro-bay}}'], 'a pending boat does not make two');
  assert.match(few.note, /the boats I work with so far/); assert.match(few.note, /link the port page/);
  one.sql.prepare("UPDATE advisor_boats SET status='verified' WHERE id='b2'").run();
  assert.equal((await TOOL_BY_NAME.get('get_trips').run({port: 'morro-bay'}, dataCtx({db: one.db}))).result.few, false);
  const many = advisorDatabase();
  seedTrips(many.sql, {extra: 14});
  const list = (await TOOL_BY_NAME.get('get_trips').run({port: 'morro-bay'}, dataCtx({db: many.db}))).result.boats;
  assert.equal(list.length, 12);
  assert.deepEqual(list.slice(0, 2).map(b => b.name), ['Zulu Example', 'Alpha Example']);
});

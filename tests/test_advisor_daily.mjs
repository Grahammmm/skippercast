// Text Advisor daily port answers (server/advisor/answers/reports.ts, prompts/daily.ts;
// docs/plans/text-advisor/06-angler-answers.md § "What's biting", TA-A1): the inputs
// hash (a publish changes it, a pending report or a failed feed read does not
// replace a stored answer), the three answer shapes (skipper reports, landing
// reports only, nothing at all), unverified boats anonymised, at most 480
// characters, no percentage, no follow offer, Spanish always present, the
// 05:30 slot once a day for every active port, and the pre-router (a plain
// "what's biting" is answered without a chat model call). Offline: node:sqlite,
// the committed feed fixtures (tests/fixtures/feeds/) and the recorded
// generation responses in tests/fixtures/advisor/daily/.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const daily = await import('../server/advisor/answers/reports.ts');
const {portForQuestion, currentInputsHash, dailyInputs, dailyAnswer, composeDaily, acceptable, plainDailyQuestion, activePorts, pregenerateDaily, DAILY_MAX} = daily;
const {DAILY_TOOL, dailyPrompt, DAILY_BODY_MAX} = await import('../server/advisor/prompts/daily.ts');
const {SLOTS, advisorCron, SLOT_PREFIX} = await import('../server/advisor/cron.ts');
const {runTurn} = await import('../server/advisor/engine.ts');
const {publishReport} = await import('../server/advisor/intake/reports.ts');
const {t} = await import('../server/advisor/strings.ts');
const {forgetContact} = await import('../server/advisor/contacts.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const NOW = Date.parse('2026-09-28T19:00:00Z');   // Mon 12:00 in Morro Bay: the feed fixtures' day
const DATE = '2026-09-28';
const iso = ms => new Date(ms).toISOString();
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const LINK = 'https://skippercast.com/ports/morro-bay?s=txt';

// The intelligence fixture holds three evening hours of 28 Sep; moved to 07:00-09:00 local so the
// 06:00-14:00 fishing window has numbers (wind 15-19 kt NW, seas 7 ft at 17 s, rough).
function intelInWindow() {
  const intel = read('./fixtures/feeds/intelligence.json');
  const delta = Date.parse('2026-09-28T14:00:00Z') / 1000 - intel.forecast.models.gfs_global.data[0].hourly.time[0];
  const walk = o => {
    if (Array.isArray(o)) { o.forEach(walk); return; }
    if (!o || typeof o !== 'object') return;
    for (const [k, v] of Object.entries(o)) if (k === 'time' && Array.isArray(v) && v.every(Number.isFinite)) o[k] = v.map(x => x + delta); else walk(v);
  };
  walk(intel.forecast);
  return intel;
}
/** A feed reader over the fixtures; `drop` removes the landing reports, `fail` makes a feed unreadable. */
function feeds({drop = false, fail = null} = {}) {
  const d = read('./fixtures/feeds/daily-latest.json'), intel = intelInWindow();
  if (drop) d.reports = [];
  return async url => {
    if (/intelligence\.json$/.test(url)) { if (fail === 'intelligence') throw Error('down'); return intel; }
    if (/latest\.json$/.test(url)) { if (fail === 'daily') throw Error('down'); return d; }
    throw Error(`no fixture for ${url}`);
  };
}
/** A fake Messages API replaying `bodies` (status 200 unless given) and recording every request. */
function fakeApi(responses) {
  const requests = [], queue = [...responses];
  return {requests, remaining: () => queue.length, async fetcher(url, init) {
    assert.equal(url, 'https://api.anthropic.com/v1/messages');
    assert.equal(init.headers['anthropic-version'], '2023-06-01');
    requests.push(JSON.parse(init.body));
    const next = queue.shift();
    if (!next) throw Error('fake API: no response left');
    return new Response(JSON.stringify(next.body), {status: next.status ?? 200, headers: {'content-type': 'application/json'}});
  }};
}
const fixture = name => read(`./fixtures/advisor/daily/${name}.json`).response;
/** The fixture with its en/es replaced. */
const withTexts = (name, en, es) => { const r = structuredClone(fixture(name)); Object.assign(r.body.content[0].input, {en, es}); return r; };
const noModel = async () => { throw Error('no model call expected'); };

function setup(env = {}) {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,status,last_seen_at,created_at,updated_at) VALUES('owner','ho','ENC','imessage','skipper','en','active',?,?,?)`).run(iso(NOW), iso(NOW), iso(NOW));
  const boat = (id, slug, name, status, port = 'morro-bay') => sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,owner_contact_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)`)
    .run(id, slug, name, 'Example Landing', port, 'morro-bay', 'owner', status, '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z');
  boat('b1', 'example-one', 'Example Boat One', 'verified');
  boat('b2', 'example-two', 'Example Boat Two', 'pending');
  return {sql, db, env: {DB: db, ANTHROPIC_API_KEY: 'k', ...env}};
}
const COUNTS = JSON.stringify([{species_key: 'vermilion', label: 'vermilion', kept: 40, released: 0}, {species_key: 'lingcod', label: 'lingcod', kept: 8, released: 2}]);
function report(sql, id, boatId, date, {verified = 1, status = 'published', port = 'morro-bay'} = {}) {
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,published_at,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, boatId, 'morro-bay', port, date, 'full-day', 20, COUNTS, `text-${id}`, status, verified, status === 'published' ? `${date}T22:00:00Z` : null, iso(NOW), iso(NOW));
}
const twoReports = sql => { report(sql, 'r1', 'b1', '2026-09-27'); report(sql, 'r2', 'b2', '2026-09-26', {verified: 0}); };
const stored = (sql, key = `morro-bay:${DATE}`) => sql.prepare('SELECT * FROM advisor_daily_answers WHERE key=?').get(key);

// ---- the question -----------------------------------------------------------------------------

test('plainDailyQuestion: the four plain forms with an optional port and "today"; anything more goes to the model', () => {
  const cases = [
    ["What's biting?", {language: 'en', port: null}],
    ['whats biting today', {language: 'en', port: null}],
    ["what's biting out of Morro Bay?", {language: 'en', port: 'morro-bay'}],
    ['hey what is biting at port san luis', {language: 'en', port: 'port-san-luis'}],
    ["How's the fishing in Avila?", {language: 'en', port: 'port-san-luis'}],
    ["what's biting in Cayucos", {language: 'en', port: 'morro-bay'}],
    ['¿Qué está picando?', {language: 'es', port: null}],
    ['que esta picando en morro bay', {language: 'es', port: 'morro-bay'}],
    ['¿Cómo está la pesca hoy?', {language: 'es', port: null}],
    ["What's biting for lingcod?", null],
    ["what's been biting out of Morro Bay, any lingcod?", null],
    ["what's biting out of Narnia", null],
    ['is Saturday worth going', null],
    ['', null],
  ];
  for (const [q, want] of cases) assert.deepEqual(plainDailyQuestion(q), want, q);
});

test('portForQuestion: the port named, else the home port, else the region default\'s first port', () => {
  assert.deepEqual(portForQuestion('out of Avila', {home_port: 'morro-bay'}), {port: 'port-san-luis', from: 'text'});
  assert.deepEqual(portForQuestion("what's biting", {home_port: 'port-san-luis'}), {port: 'port-san-luis', from: 'home_port'});
  assert.deepEqual(portForQuestion("what's biting", {home_port: null}), {port: 'morro-bay', from: 'default'});
});

test('activePorts: every catalog port of a region whose status is active (Morro Bay and Port San Luis today)', () => {
  assert.deepEqual(activePorts(), ['morro-bay', 'port-san-luis']);
});

// ---- the inputs hash --------------------------------------------------------------------------

dbTest('the inputs hash changes when a report publishes or a rule goes stale, not for a pending report; publishing deletes the stored answer', async () => {
  const {sql, db, env} = setup();
  const h0 = await currentInputsHash(env, 'morro-bay', DATE, {feeds: feeds()}, NOW);
  assert.match(h0, /^[0-9a-f]{64}$/);
  assert.equal(await currentInputsHash(env, 'morro-bay', DATE, {feeds: feeds()}, NOW), h0, 'stable for the same inputs');
  report(sql, 'p1', 'b1', '2026-09-27', {status: 'pending_confirm', verified: 0});
  assert.equal(await currentInputsHash(env, 'morro-bay', DATE, {feeds: feeds()}, NOW), h0, 'a pending report is not an input');
  report(sql, 'x1', 'b1', '2026-09-27', {port: 'port-san-luis'});
  assert.equal(await currentInputsHash(env, 'morro-bay', DATE, {feeds: feeds()}, NOW), h0, 'another port\'s report is not an input');
  report(sql, 'old', 'b1', '2026-09-20');
  assert.equal(await currentInputsHash(env, 'morro-bay', DATE, {feeds: feeds()}, NOW), h0, 'a report older than three days is not an input');

  // A stored answer, then the real publish path (intake/reports.ts publishReport).
  const first = await quiet(() => dailyAnswer(env, 'morro-bay', DATE, 'en', {feeds: feeds(), fetcher: fakeApi([fixture('generate-landing-only')]).fetcher, clock: () => NOW}));
  assert.equal(first.value.inputs_hash, h0);
  assert.ok(stored(sql));
  assert.equal(await publishReport(db, {id: 'owner'}, 'p1', NOW), true);
  assert.equal(stored(sql), undefined, 'the publish deleted the port\'s answer');
  const h1 = await currentInputsHash(env, 'morro-bay', DATE, {feeds: feeds()}, NOW);
  assert.notEqual(h1, h0, 'a published report changes the hash');
  // Even with the row still there (an edit to a published report bumps its version), the hash would differ.
  sql.prepare("UPDATE advisor_reports SET version=2 WHERE id='p1'").run();
  assert.notEqual(await currentInputsHash(env, 'morro-bay', DATE, {feeds: feeds()}, NOW), h1, 'an edit (new version) changes the hash');

  // The rules used: a rockfish row that goes stale.
  const rule = status => sql.prepare(`INSERT OR REPLACE INTO advisor_rules(id,region,jurisdiction,species_key,species_label,bag_limit,season_open,season_close,source_name,source_url,reviewed_at,review_due,status,updated_by,updated_at)
    VALUES('rr','*','california-central','rockfish','Rockfish',10,'2026-04-01','2026-12-31','CDFW','https://wildlife.ca.gov/','2026-09-01','2026-12-31',?,'test',?)`).run(status, iso(NOW));
  rule('active');
  const h2 = await currentInputsHash(env, 'morro-bay', DATE, {feeds: feeds()}, NOW);
  const inputs = await dailyInputs(env, 'morro-bay', DATE, {feeds: feeds()}, NOW);
  assert.deepEqual(inputs.rules.find(r => r.species_key === 'rockfish'), {species_key: 'rockfish', open: true, stale: false});
  rule('review');
  assert.notEqual(await currentInputsHash(env, 'morro-bay', DATE, {feeds: feeds()}, NOW), h2, 'a rule going stale changes the hash');
});

// ---- the three answers ------------------------------------------------------------------------

dbTest('skipper reports: one forced-tool call returns both languages; stored with the hash; the unverified boat is "another boat" and never named', async () => {
  const {sql, env} = setup();
  twoReports(sql);
  const api = fakeApi([fixture('generate-skipper-reports')]);
  const {value: a} = await quiet(() => dailyAnswer(env, 'morro-bay', DATE, 'en', {feeds: feeds(), fetcher: api.fetcher, clock: () => NOW}));
  assert.equal(api.requests.length, 1, 'one model call');
  const req = api.requests[0];
  assert.deepEqual(req.tool_choice, {type: 'tool', name: 'record_daily_answer'});
  assert.deepEqual(req.tools, [DAILY_TOOL]);
  assert.equal(req.temperature, 0);
  const prompt = req.messages[0].content;
  assert.ok(!prompt.includes('Example Boat Two'), 'the unverified boat\'s name never reaches the model');
  assert.ok(prompt.includes('"boat":"a boat"') && prompt.includes('"boat":"Example Boat One"'));
  assert.ok(prompt.includes('SMALL CRAFT ADVISORY posted for today. Conditions: seas 7 ft at 17 s, wind 15-19 kt from the NW, rough for a mid-size center console.'), 'the conditions sentence is given, not left to the model');
  assert.equal(a.source, 'model');
  assert.equal(a.text, a.text_en);
  assert.ok(a.text_en.startsWith('Morro Bay, Mon Sep 28: SMALL CRAFT ADVISORY posted for today. Example Boat One reported Sun'));
  assert.ok(a.text_en.endsWith(LINK) && a.text_es.endsWith(LINK), 'the link resolved at the end of both');
  assert.match(a.text_es, /^Morro Bay, lun 28 sept: .*Otro barco reportó/);
  for (const text of [a.text_en, a.text_es]) {
    assert.ok(text.length <= DAILY_MAX, `${text.length} <= 480`);
    assert.ok(!text.includes('Example Boat Two'));
    assert.doesNotMatch(text, /%/);
  }
  const row = stored(sql);
  assert.deepEqual([row.text_en, row.text_es, row.inputs_hash], [a.text_en, a.text_es, await currentInputsHash(env, 'morro-bay', DATE, {feeds: feeds()}, NOW)]);
  // Asked again (either language): the stored row, no model call.
  const again = await dailyAnswer(env, 'morro-bay', DATE, 'es', {feeds: feeds(), fetcher: noModel, clock: () => NOW});
  assert.deepEqual([again.source, again.text], ['cache', a.text_es]);
});

dbTest('no skipper reports: the answer says so and falls back to the landing\'s label, attributed; a model answer without the label is not stored', async () => {
  const {sql, env} = setup();
  const api = fakeApi([fixture('generate-landing-only')]);
  const {value: a} = await quiet(() => dailyAnswer(env, 'morro-bay', DATE, 'en', {feeds: feeds(), fetcher: api.fetcher, clock: () => NOW}));
  assert.equal(a.source, 'model');
  assert.match(a.text_en, /No skipper reports from the last three days\. The landing reports Starfire .*recent reported activity: Low\./);
  assert.match(a.text_es, /No hay reportes de capitanes .*El muelle reporta .*Low\./);
  // A model answer that drops the label or the "no skipper reports" sentence: the composed text instead.
  for (const [en, es] of [
    ['Morro Bay, Mon Sep 28: The landing reports Starfire on Sun with bocaccio. Full picture: {{link:port:morro-bay}}', 'Morro Bay, lun 28 sept: El muelle reporta al Starfire. Todo el detalle: {{link:port:morro-bay}}'],
    ['Morro Bay, Mon Sep 28: The landing reports Starfire on Sun; recent reported activity: Low. Full picture: {{link:port:morro-bay}}', 'Morro Bay, lun 28 sept: El muelle reporta al Starfire; actividad reciente reportada: Low. Todo el detalle: {{link:port:morro-bay}}'],
  ]) {
    sql.prepare('DELETE FROM advisor_daily_answers').run();
    const bad = fakeApi([withTexts('generate-landing-only', en, es)]);
    const {value} = await quiet(() => dailyAnswer(env, 'morro-bay', DATE, 'en', {feeds: feeds(), fetcher: bad.fetcher, clock: () => NOW}));
    assert.equal(value.source, 'composed', en);
    assert.match(value.text_en, /^Morro Bay, Mon Sep 28: SMALL CRAFT ADVISORY posted for today\. No skipper reports from the last three days\. The landing reports 1 trip with rockfish and lingcod this week; recent reported activity: Low\. Conditions: /);
  }
});

dbTest('nothing at all: "No reports from the last three days for {port} yet." and the conditions, no model call, no follow offer, no link', async () => {
  const {sql, env} = setup();
  const {value: a} = await quiet(() => dailyAnswer(env, 'morro-bay', DATE, 'en', {feeds: feeds({drop: true}), fetcher: noModel, clock: () => NOW}));
  assert.equal(a.source, 'composed');
  assert.equal(a.text_en, 'SMALL CRAFT ADVISORY posted for today. No reports from the last three days for Morro Bay yet. Conditions: seas 7 ft at 17 s, wind 15-19 kt from the NW, rough for a mid-size center console.');
  assert.equal(a.text_es, 'SMALL CRAFT ADVISORY (aviso del NWS) para hoy. Todavía no hay reportes de los últimos tres días para Morro Bay. Condiciones: mar de 7 pies a 17 s, viento de 15-19 nudos del NW, duro para una lancha mediana de consola central.');
  for (const text of [a.text_en, a.text_es]) assert.doesNotMatch(text, /text you|want me|te aviso|\?/i, 'the FR-3 follow offer is Next');
  assert.ok(stored(sql), 'stored like any answer');
});

dbTest('a model answer with a percentage, odds, a rule number, a follow offer or no Spanish is refused; a long one is capped at 480 with its link', async () => {
  const {sql, env} = setup();
  twoReports(sql);
  const good = fixture('generate-skipper-reports').body.content[0].input;
  const bad = [
    ['Morro Bay, Mon Sep 28: a 70% chance of limits today. {{link:port:morro-bay}}', good.es],
    ['Morro Bay, Mon Sep 28: good odds for lingcod. {{link:port:morro-bay}}', good.es],
    ['Morro Bay, Mon Sep 28: Example Boat One limited out. Rockfish bag limit is 10. {{link:port:morro-bay}}', good.es],
    [good.en + ' Want me to text you when a new report comes in?', good.es],
    [good.en, good.es.replace('Todo el detalle', '70 por ciento. Todo el detalle')],
    [good.en, ''],
    [good.en, null],
  ];
  for (const [en, es] of bad) {
    sql.prepare('DELETE FROM advisor_daily_answers').run();
    const api = fakeApi([withTexts('generate-skipper-reports', en, es)]);
    const {value} = await quiet(() => dailyAnswer(env, 'morro-bay', DATE, 'en', {feeds: feeds(), fetcher: api.fetcher, clock: () => NOW}));
    assert.equal(value.source, 'composed', String(en).slice(0, 60) + ' / ' + String(es).slice(0, 30));
    assert.ok(value.text_es.length > 0, 'Spanish is always there');
    assert.doesNotMatch(value.text_en + value.text_es, /%|por ciento/);
  }
  sql.prepare('DELETE FROM advisor_daily_answers').run();
  const long = good.en.replace(' Full picture:', ' ' + 'Example Boat One also saw a few cabezon on the inside reefs and some blues on the drift. '.repeat(4) + 'Full picture:');
  const {value} = await quiet(() => dailyAnswer(env, 'morro-bay', DATE, 'en', {feeds: feeds(), fetcher: fakeApi([withTexts('generate-skipper-reports', long, good.es)]).fetcher, clock: () => NOW}));
  assert.equal(value.source, 'model');
  assert.ok(value.text_en.length <= 480, `${value.text_en.length}`);
  assert.ok(value.text_en.endsWith(LINK), 'the cap keeps the link');
});

dbTest('the model failing (HTTP 500), no API key, or the global LLM cap: the composed answer, both languages', async () => {
  for (const [name, env, api] of [
    ['500', {}, fakeApi([{status: 500, body: {type: 'error'}}])],
    ['no key', {ANTHROPIC_API_KEY: undefined}, null],
    ['global cap', {ADVISOR_GLOBAL_DAILY_LLM: '0'}, null],
  ]) {
    const {sql, env: e} = setup(env);
    twoReports(sql);
    const {value} = await quiet(() => dailyAnswer(e, 'morro-bay', DATE, 'en', {feeds: feeds(), fetcher: api?.fetcher ?? noModel, clock: () => NOW}));
    assert.equal(value.source, 'composed', name);
    assert.equal(value.text_en, `Morro Bay, Mon Sep 28: SMALL CRAFT ADVISORY posted for today. Example Boat One reported yesterday: 40 vermilion, 8 lingcod. Another boat reported Sat: 40 vermilion, 8 lingcod. Conditions: seas 7 ft at 17 s, wind 15-19 kt from the NW, rough for a mid-size center console. Full picture: ${LINK}`);
    assert.equal(value.text_es, `Morro Bay, lun 28 sept: SMALL CRAFT ADVISORY (aviso del NWS) para hoy. Example Boat One reportó ayer: 40 vermilion, 8 lingcod. Otro barco reportó el sáb: 40 vermilion, 8 lingcod. Condiciones: mar de 7 pies a 17 s, viento de 15-19 nudos del NW, duro para una lancha mediana de consola central. Todo el detalle: ${LINK}`);
  }
});

dbTest('a feed that fails to load does not replace today\'s stored answer; without a stored answer the degraded one is made', async () => {
  const {sql, env} = setup();
  twoReports(sql);
  const {value: good} = await quiet(() => dailyAnswer(env, 'morro-bay', DATE, 'en', {feeds: feeds(), fetcher: fakeApi([fixture('generate-skipper-reports')]).fetcher, clock: () => NOW}));
  for (const fail of ['daily', 'intelligence']) {
    const kept = await dailyAnswer(env, 'morro-bay', DATE, 'en', {feeds: feeds({fail}), fetcher: noModel, clock: () => NOW});
    assert.deepEqual([kept.source, kept.text], ['cache', good.text_en], fail);
  }
  sql.prepare('DELETE FROM advisor_daily_answers').run();
  const {value: degraded} = await quiet(() => dailyAnswer(env, 'morro-bay', DATE, 'en', {feeds: feeds({fail: 'intelligence'}), fetcher: fakeApi([{status: 529, body: {}}]).fetcher, clock: () => NOW}));
  assert.equal(degraded.source, 'composed');
  assert.match(degraded.text_en, /Today's forecast isn't in yet\./);
});

test('composeDaily and acceptable on hand-built inputs: the 06 example passes, and every text is plain', () => {
  const example = "Morro Bay, Sat Oct 3: 3 boats reported Fri—limits of rockfish for most trips (vermilion, copper), lingcod 8–14 per boat, a few cabezon. Seas 4–5 ft at 9 s, wind light until noon. Rockfish open; check depth limits. Full picture: {{link:port:morro-bay}}";
  assert.equal(acceptable(example, '{{link:port:morro-bay}}'), example, 'the 06 example is a valid answer');
  assert.equal(acceptable('**Morro Bay**: 3 boats.', '{{link:port:morro-bay}}'), 'Morro Bay: 3 boats. {{link:port:morro-bay}}', 'markdown stripped, link added');
  for (const [text, why] of [['A 70% day.', 'percent'], ['Good odds today.', 'odds'], ['Probably limits.', 'probability'], ['Hay 70 por ciento.', 'por ciento'],
    ['Rockfish bag limit is 10.', 'rule number'], ['Lingcod 22 inch minimum.', 'size'], ['Season closes Dec 31.', 'season date'],
    ['Want me to text you when one comes in?', 'follow offer'], ['¿Quieres que te avise?', 'follow offer (es)'], [42, 'not text'], ['   ', 'empty']])
    assert.equal(acceptable(text, '{{link:port:morro-bay}}'), null, why);
  assert.equal(acceptable('No skipper reports. The landing reports 1 trip; recent reported activity: Low.', '{{link:port:x}}', ['Low']), 'No skipper reports. The landing reports 1 trip; recent reported activity: Low. {{link:port:x}}');
  assert.equal(acceptable('No skipper reports. The landing reports 1 trip; activity is slow.', '{{link:port:x}}', ['Low']), null, 'the label must be there');
  const inputs = {port: 'port-san-luis', port_name: 'Port San Luis · Avila Beach', region: 'morro-bay', date: '2026-10-03', feeds: {daily: true, intelligence: true},
    skipper_reports: [{id: 'a', version: 1, date: '2026-10-03', boat: 'a boat', verified: false, trip_type: null, anglers: null, counts: [{label: 'halibut', species_key: 'halibut', kept: null, released: 3}]}],
    landing: {available: true, reports: [], activity: []}, conditions: {available: false, advisories: [], day: null}, rules: []};
  assert.equal(composeDaily(inputs, 'en'), 'Port San Luis · Avila Beach, Sat Oct 3: Another boat reported today: 3 halibut released. Today\'s forecast isn\'t in yet. Full picture: {{link:port:port-san-luis}}');
  assert.equal(composeDaily(inputs, 'es'), 'Port San Luis · Avila Beach, sáb 3 oct: Otro barco reportó hoy: 3 halibut liberados. El pronóstico de hoy todavía no llega. Todo el detalle: {{link:port:port-san-luis}}');
});

test('the prompt: a fixed template with the facts as JSON, the two fallbacks, no odds, no follow offer, the length', () => {
  const p = dailyPrompt({port: 'morro-bay'}, '{{link:port:morro-bay}}');
  for (const phrase of ['Use only the facts below', '"a boat"', 'No skipper reports from the last three days.', 'The landing reports', 'SMALL CRAFT ADVISORY',
    'Never give odds, a chance, a percentage, a probability', 'do not offer to text them later', `At most ${DAILY_BODY_MAX} characters`, 'End both versions with exactly: {{link:port:morro-bay}}', '(tú)'])
    assert.ok(p.includes(phrase), phrase);
  assert.ok(p.endsWith('FACTS\n{"port":"morro-bay"}'));
  assert.deepEqual(DAILY_TOOL.input_schema.required, ['en', 'es']);
  assert.ok(DAILY_BODY_MAX < 480, 'room for the resolved link');
});

// ---- the slot ---------------------------------------------------------------------------------

dbTest('the daily-answers slot runs once a local day at 05:30 and pre-generates every active port; a later tick serves the stored rows', async () => {
  const {sql, env} = setup({TEXT_ADVISOR_ENABLED: 'true'});
  twoReports(sql);
  const day = '2026-09-28', slot = SLOTS.find(s => s.name === 'daily-answers');
  assert.ok(slot);
  // Morro Bay has skipper reports (one generation); Port San Luis has the landing's Sunny Day trip (one generation).
  const psl = withTexts('generate-landing-only',
    'Port San Luis, Mon Sep 28: SMALL CRAFT ADVISORY posted for today. No skipper reports from the last three days. The landing reports Sunny Day on Sun with rockcod; recent reported activity: Low. Full picture: {{link:port:port-san-luis}}',
    'Port San Luis, lun 28 sept: SMALL CRAFT ADVISORY (aviso del NWS) para hoy. No hay reportes de capitanes de los últimos tres días. El muelle reporta al Sunny Day el dom con rocote; actividad reciente reportada: Low. Todo el detalle: {{link:port:port-san-luis}}');
  const api = fakeApi([fixture('generate-skipper-reports'), psl]);
  const deps = {daily: {feeds: feeds(), fetcher: api.fetcher}};
  const ran = [];
  // Every 15-minute tick from local midnight to 08:00 on 28 Sep (PDT: 07:00Z to 15:00Z).
  for (let tick = Date.parse(`${day}T07:00:00Z`); tick < Date.parse(`${day}T15:00:00Z`); tick += 15 * 60000) {
    const before = sql.prepare('SELECT COUNT(*) n FROM advisor_daily_answers').get().n;
    const {value} = await quiet(() => advisorCron(env, tick, deps));
    assert.equal(value, 'ok', iso(tick));
    if (sql.prepare('SELECT COUNT(*) n FROM advisor_daily_answers').get().n !== before) ran.push(iso(tick));
  }
  assert.deepEqual(ran, ['2026-09-28T12:30:00.000Z'], '05:30 PDT, once');
  assert.equal(api.requests.length, 2, 'one generation per active port');
  assert.equal(api.remaining(), 0);
  assert.deepEqual(sql.prepare('SELECT key FROM advisor_daily_answers ORDER BY key').all().map(r => r.key), ['morro-bay:2026-09-28', 'port-san-luis:2026-09-28']);
  assert.equal(sql.prepare('SELECT value FROM job_state WHERE key=?').get(SLOT_PREFIX + 'daily-answers').value, day);
  // The first "what's biting" after the slot is the stored text.
  const hit = await dailyAnswer(env, 'port-san-luis', day, 'en', {feeds: feeds(), fetcher: noModel, clock: () => Date.parse(`${day}T16:00:00Z`)});
  assert.equal(hit.source, 'cache');
  assert.ok(hit.text.startsWith('Port San Luis, Mon Sep 28: SMALL CRAFT ADVISORY'));
});

dbTest('pregenerateDaily throws when a port failed, so the slot releases its claim and retries', async () => {
  const broken = {DB: {prepare() { throw Error('D1 down'); }}};
  await assert.rejects(quiet(() => pregenerateDaily(broken, NOW, {feeds: feeds()})).then(r => r.value), /daily answers failed for 2 of 2 ports/);
});

// ---- the pre-router ---------------------------------------------------------------------------

function contact(sql, over = {}) {
  const c = {id: 'c1', channel: 'imessage', role: 'angler', language: 'en', home_port: null, ...over};
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,status,home_port,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,'active',?,?,?,?)`)
    .run(c.id, `h-${c.id}`, 'ENC', c.channel, c.role, c.language, c.home_port, iso(NOW), iso(NOW), iso(NOW));
  // An earlier message, so no welcome.
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES(?,?,'in','imessage',?,'earlier','done',?)`).run(`e-${c.id}`, c.id, `pe-${c.id}`, iso(NOW - 86400000));
  return () => sql.prepare('SELECT * FROM advisor_contacts WHERE id=?').get(c.id);
}
let seq = 0;
function inbound(sql, body, contactId = 'c1') {
  const id = `in${++seq}`;
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES(?,?,'in','imessage',?,?,'processing',?)`).run(id, contactId, `p-${id}`, body, iso(NOW));
  return sql.prepare('SELECT * FROM advisor_messages WHERE id=?').get(id);
}
const texts = r => r.actions.filter(a => a.type === 'send_text').map(a => a.text);
const turn = (env, row, message, deps = {}) => runTurn({env: {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_NUMBER: '+15555550199', ...env}, contact: row, message, now: NOW, deps: {sleep: async () => {}, clock: () => NOW, feeds: feeds(), ...deps}});

dbTest('pre-router: a plain "what\'s biting" with a stored answer makes no model call at all; the home-port question goes once', async () => {
  const {sql, db, env} = setup();
  twoReports(sql);
  const row = contact(sql);
  await quiet(() => dailyAnswer(env, 'morro-bay', DATE, 'en', {feeds: feeds(), fetcher: fakeApi([fixture('generate-skipper-reports')]).fetcher, clock: () => NOW}));
  const answer = stored(sql);
  const first = await turn(env, row(), inbound(sql, "What's biting?"), {fetcher: noModel});
  assert.equal(first.intent, 'reports.daily.cache');
  assert.deepEqual(texts(first), [answer.text_en, t('en', 'ask_home_port')]);
  assert.deepEqual(first.actions.find(a => a.type === 'mark_once'), {type: 'mark_once', key: 'homeport.c1'});
  sql.prepare("INSERT INTO job_state(key,value,updated_at) VALUES('advisor.once.homeport.c1','1',?)").run(iso(NOW));   // the consumer's mark_once
  const second = await turn(env, row(), inbound(sql, 'whats biting out of morro bay'), {fetcher: noModel});
  assert.deepEqual(texts(second), [answer.text_en], 'asked once');
  const es = await turn(env, row(), inbound(sql, '¿Qué está picando en Morro Bay?'), {fetcher: noModel});
  assert.deepEqual(texts(es), [answer.text_es], 'Spanish question, Spanish answer');
  // Forget me removes the one-time marker with the rest of the contact.
  await forgetContact(db, undefined, 'c1', new Date(NOW));
  assert.equal(sql.prepare("SELECT COUNT(*) n FROM job_state WHERE key='advisor.once.homeport.c1'").get().n, 0);
  // A contact with a home port is not asked; Port San Luis has no stored answer and the landing-only facts: one generation, shared.
  const {sql: s2, env: e2} = setup();
  const r2 = contact(s2, {home_port: 'port-san-luis'});
  const psl = withTexts('generate-landing-only',
    'Port San Luis, Mon Sep 28: No skipper reports from the last three days. The landing reports Sunny Day on Sun with rockcod; recent reported activity: Low. Full picture: {{link:port:port-san-luis}}',
    'Port San Luis, lun 28 sept: No hay reportes de capitanes de los últimos tres días. El muelle reporta al Sunny Day el dom con rocote; actividad reciente reportada: Low. Todo el detalle: {{link:port:port-san-luis}}');
  const api = fakeApi([psl]);
  const gen = await quiet(() => turn(e2, r2(), inbound(s2, "how's the fishing"), {fetcher: api.fetcher}));
  assert.equal(gen.value.intent, 'reports.daily.model');
  assert.equal(api.requests.length, 1);
  assert.equal(api.requests[0].tool_choice.name, 'record_daily_answer', 'the one call is the generation, not a chat turn');
  assert.deepEqual(texts(gen.value), ['Port San Luis, Mon Sep 28: No skipper reports from the last three days. The landing reports Sunny Day on Sun with rockcod; recent reported activity: Low. Full picture: https://skippercast.com/ports/port-san-luis?s=txt']);
  const cached = await turn(e2, r2(), inbound(s2, "how's the fishing"), {fetcher: noModel});
  assert.equal(cached.intent, 'reports.daily.cache');
});

dbTest('pre-router: anything more than the plain question, or a preview region\'s port, goes on to the model', async () => {
  const {sql, env} = setup({ANTHROPIC_API_KEY: undefined});
  const row = contact(sql);
  for (const q of ["What's biting for lingcod?", "what's biting out of San Diego", 'any rockfish today?'])
    assert.equal((await quiet(() => turn(env, row(), inbound(sql, q), {fetcher: noModel}))).value.intent, 'unconfigured', q);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM advisor_daily_answers').get().n, 0);
});

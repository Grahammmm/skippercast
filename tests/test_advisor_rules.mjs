// Text Advisor rules table (TA-A0; docs/plans/text-advisor/02-data-model.md §
// advisor_rules, 06 § fish ID step 3, OP-6): the importer
// (scripts/advisor/import-rules.mjs) maps every species in every published
// regulations file to a row and is idempotent; lookupRules returns active and
// review rows (review rows stale), never retired, stale also past review_due,
// group rules for a sub-species; markJurisdictionForReview; the real get_rules
// tool; and the engine's rules guard with a real get_rules call that returned a
// stale row (recorded response: the reply keeps its rule and says
// "double-check"). Offline: real migrations in node:sqlite, a fake Messages API.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json'),
  'crescent-city': read('../regions/crescent-city/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const importer = await import('../scripts/advisor/import-rules.mjs');
const {lookupRules, markJurisdictionForReview, isStale, ruleKeys} = await import('../server/advisor/answers/rules.ts');
const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');
const {runTurn} = await import('../server/advisor/engine.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-04T17:00:00Z');   // Sunday 10:00 in Morro Bay
const DAY = 86400000;

/** Every published regulations file, as the importer finds it (jurisdictions/*.json -> dist/<asset>, plus dist/data/regulations*.json). */
function regulationFiles() {
  const paths = new Set(readdirSync(new URL('../jurisdictions/', import.meta.url)).filter(f => f.endsWith('.json'))
    .map(f => `dist/${read(`../jurisdictions/${f}`).regulations_asset}`));
  for (const f of readdirSync(new URL('../dist/data/', import.meta.url))) if (/^regulations.*\.json$/.test(f)) paths.add(`dist/data/${f}`);
  return [...paths].map(p => ({path: p, data: read(`../${p}`)}));
}

function seeded(now = T0) {
  const {sql, db} = advisorDatabase();
  sql.exec(importer.rulesSql(importer.importRows(now)));
  return {sql, db};
}

// ---- the importer --------------------------------------------------------------------

test('the importer reads every regulations file: one per jurisdiction, each species in each file becomes a row', () => {
  const files = regulationFiles();
  assert.equal(files.length, 5, 'central, mendocino, northern, san-francisco, southern');
  const pairs = files.flatMap(f => Object.keys(f.data.species).map(s => `${f.data.jurisdiction_id}:${s}`));
  assert.equal(pairs.length, 46, 'species entries across the five files (7 + 7 + 7 + 6 + 19)');
  const rows = importer.importRows(T0);
  for (const pair of pairs) {
    const [jurisdiction, species] = pair.split(':');
    const row = rows.find(r => r.jurisdiction === jurisdiction && r.file_species === species && r.species_key === importer.speciesKeyFor(species));
    assert.ok(row, pair);
    assert.notEqual(row.species_key, 'other', `${pair} maps to a catalog key`);
  }
  assert.deepEqual(new Set(rows.map(r => r.jurisdiction)), new Set(['california-central', 'california-mendocino', 'california-northern', 'california-san-francisco', 'california-southern']));
});

test('the importer maps names to catalog or species-extra keys; unknown names become "other" with the label kept', () => {
  assert.equal(importer.speciesKeyFor('lingcod'), 'lingcod');
  assert.equal(importer.speciesKeyFor('california-halibut'), 'halibut', 'a same_as_parent synonym is canonicalised');
  assert.equal(importer.speciesKeyFor('vermilion'), 'vermilion');
  assert.equal(importer.speciesKeyFor('greenling'), 'kelp-greenling');
  assert.equal(importer.speciesKeyFor('pacific-halibut'), 'pacific-halibut');
  // TA-A3: quillback is a species-extra key now (it joined the no-retention list), so it maps to itself.
  assert.equal(importer.speciesKeyFor('quillback'), 'quillback');
  assert.equal(importer.speciesKeyFor('sunset'), 'other');
  const central = importer.importRows(T0).filter(r => r.jurisdiction === 'california-central');
  // The rockfish text names its sub-limits and its no-retention species: each gets a row.
  for (const key of ['copper', 'canary', 'vermilion', 'yelloweye', 'quillback', 'cowcod', 'bronzespotted', 'cabezon', 'kelp-greenling']) assert.ok(central.some(r => r.species_key === key), key);
  const others = central.filter(r => r.species_key === 'other').map(r => r.species_label).sort();
  assert.deepEqual(others, ['Sunset rockfish']);
  assert.equal(central.find(r => r.species_key === 'quillback').bag_limit, 0, 'quillback: no retention is a 0 bag');
  assert.equal(central.find(r => r.species_key === 'yelloweye').bag_limit, 0, 'no retention is a 0 bag');
  assert.equal(central.find(r => r.species_key === 'vermilion').bag_limit, 2);
  assert.equal(importer.importRows(T0).find(r => r.jurisdiction === 'california-northern' && r.species_key === 'vermilion').bag_limit, 4, 'the northern file says 4');
});

test('the importer reads sizes, bags, seasons and sources from the file; every row starts in review for 90 days or to the season end', () => {
  const rows = importer.importRows(T0), row = (j, k) => rows.find(r => r.jurisdiction === `california-${j}` && r.species_key === k);
  const ling = row('central', 'lingcod');
  assert.deepEqual([ling.size_min_in, ling.bag_limit, ling.season_open, ling.season_close], [22, 2, '2026-04-01', '2026-12-31']);
  assert.equal(ling.source_name, 'CDFW Central Region rules');
  assert.match(ling.source_url, /^https:\/\/wildlife\.ca\.gov\//);
  assert.equal(row('central', 'dungeness').size_min_in, 5.75);
  assert.equal(row('central', 'dungeness').source_name, 'CDFW crab');
  assert.equal(row('southern', 'lobster').size_min_in, 3.25);
  const closed = row('northern', 'salmon');
  assert.deepEqual([closed.season_open, closed.season_close, closed.bag_limit], [null, null, 0]);
  assert.match(closed.area_notes, /^Closed: /);
  for (const r of rows) {
    assert.equal(r.status, 'review', `${r.jurisdiction}/${r.species_key}`);
    assert.equal(r.region, '*');
    assert.equal(r.reviewed_at, new Date(T0).toISOString());
    assert.ok(r.review_due <= '2027-01-02' && r.review_due >= '2026-10-04', r.review_due);
    assert.ok(r.source_name && /^https:\/\//.test(r.source_url), `${r.jurisdiction}/${r.species_key} has a source`);
  }
  assert.equal(row('central', 'lingcod').review_due, '2026-12-31', 'the season end is sooner than 90 days');
  assert.equal(row('central', 'salmon').review_due, '2027-01-02', 'a season already over: 90 days');
  assert.equal(row('mendocino', 'pacific-halibut').review_due, '2026-11-15');
});

dbTest('the importer SQL is idempotent: twice is the same table; a changed row goes back to review; retired stays retired', () => {
  const {sql} = seeded();
  const snapshot = () => sql.prepare('SELECT * FROM advisor_rules ORDER BY id').all();
  const first = snapshot();
  assert.equal(first.length, importer.importRows(T0).length);
  assert.equal(new Set(first.map(r => r.id)).size, first.length, 'one row per (jurisdiction, region, species_key[, label])');
  sql.exec(importer.rulesSql(importer.importRows(T0 + DAY)));
  assert.deepEqual(snapshot(), first, 'a re-run with the same content changes nothing, not even reviewed_at');
  // An admin approved one row and retired another; the next import keeps both decisions while the content is unchanged.
  const ling = first.find(r => r.jurisdiction === 'california-central' && r.species_key === 'lingcod');
  const cab = first.find(r => r.jurisdiction === 'california-central' && r.species_key === 'cabezon');
  sql.prepare("UPDATE advisor_rules SET status='active' WHERE id=?").run(ling.id);
  sql.prepare("UPDATE advisor_rules SET status='retired' WHERE id=?").run(cab.id);
  sql.exec(importer.rulesSql(importer.importRows(T0 + 2 * DAY)));
  assert.equal(sql.prepare('SELECT status FROM advisor_rules WHERE id=?').get(ling.id).status, 'active');
  // The source file changed: the row is re-imported and needs review again; a retired row stays retired.
  const changed = importer.importRows(T0 + 3 * DAY).map(r => r.id === ling.id || r.id === cab.id ? {...r, bag_notes: r.bag_notes + ' (changed)'} : r);
  sql.exec(importer.rulesSql(changed));
  assert.equal(sql.prepare('SELECT status FROM advisor_rules WHERE id=?').get(ling.id).status, 'review');
  assert.equal(sql.prepare('SELECT status FROM advisor_rules WHERE id=?').get(cab.id).status, 'retired');
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM advisor_rules').get().n, first.length);
});

test('the importer prints SQL by default and runs wrangler with --file only on --apply', () => {
  const lines = [], calls = [];
  assert.equal(importer.main([], {log: l => lines.push(l), run: () => { throw Error('no'); }, now: T0}), 0);
  assert.match(lines.join('\n'), /^INSERT INTO advisor_rules\(/);
  assert.equal(importer.main(['--apply'], {log: () => {}, run: (cmd, args) => { calls.push([cmd, args]); return {status: 0}; }, now: T0}), 0);
  assert.equal(calls[0][0], 'npx');
  assert.deepEqual(calls[0][1].slice(0, 7), ['--yes', 'wrangler', 'd1', 'execute', 'skippercast', '--remote', '--file']);
  assert.throws(() => importer.main(['--force']), /unknown option/);
});

// ---- lookupRules ---------------------------------------------------------------------

test('staleness: review rows are stale; active rows are stale only past review_due', () => {
  assert.equal(isStale({status: 'review', review_due: '2099-01-01'}, '2026-10-04'), true);
  assert.equal(isStale({status: 'active', review_due: '2026-10-04'}, '2026-10-04'), false, 'due today is still current');
  assert.equal(isStale({status: 'active', review_due: '2026-10-03'}, '2026-10-04'), true);
  assert.deepEqual(ruleKeys('vermilion'), {species: ['vermilion'], group: ['rockfish']});
  assert.deepEqual(ruleKeys('reef'), {species: ['lingcod', 'rockfish'], group: []});
  assert.deepEqual(ruleKeys('california-halibut'), {species: ['halibut'], group: []}, 'a synonym is its catalog key');
});

dbTest('lookupRules: the region\'s jurisdiction only; review rows stale; retired never; past review_due stale; a sub-species gets its group', async () => {
  const {sql, db} = seeded();
  const central = await lookupRules(db, {region: 'morro-bay', speciesKey: 'lingcod', now: T0});
  assert.equal(central.length, 1);
  assert.equal(central[0].jurisdiction, 'california-central');
  assert.equal(central[0].stale, true, 'imported rows are in review');
  assert.equal(central[0].source_name, 'CDFW Central Region rules');
  assert.equal(central[0].reviewed_at, new Date(T0).toISOString());
  assert.equal((await lookupRules(db, {region: 'crescent-city', speciesKey: 'lingcod', now: T0}))[0].jurisdiction, 'california-northern');
  assert.deepEqual(await lookupRules(db, {region: 'nowhere', speciesKey: 'lingcod', now: T0}), []);
  // Active: not stale until review_due passes.
  sql.prepare("UPDATE advisor_rules SET status='active' WHERE jurisdiction='california-central' AND species_key='lingcod'").run();
  assert.equal((await lookupRules(db, {region: 'morro-bay', speciesKey: 'lingcod', now: T0}))[0].stale, false);
  assert.equal((await lookupRules(db, {region: 'morro-bay', speciesKey: 'lingcod', now: Date.parse('2027-01-01T20:00:00Z')}))[0].stale, true, 'past review_due');
  // Retired rows never come back.
  sql.prepare("UPDATE advisor_rules SET status='retired' WHERE jurisdiction='california-central' AND species_key='lingcod'").run();
  assert.deepEqual(await lookupRules(db, {region: 'morro-bay', speciesKey: 'lingcod', now: T0}), []);
  // A vermilion question gets the vermilion row and the rockfish group's row.
  const verm = await lookupRules(db, {region: 'morro-bay', speciesKey: 'vermilion', now: T0});
  assert.deepEqual(verm.map(r => [r.species_key, r.applies_as]), [['rockfish', 'group'], ['vermilion', 'species']]);
  // A region-specific row comes before the jurisdiction's.
  sql.prepare(`INSERT INTO advisor_rules(id,region,jurisdiction,species_key,species_label,bag_limit,source_name,source_url,reviewed_at,review_due,status,updated_by,updated_at)
    VALUES('local1','morro-bay','california-central','halibut','California halibut',3,'CDFW test page','https://wildlife.ca.gov/x','2026-10-01T00:00:00Z','2026-12-01','active','admin','2026-10-01T00:00:00Z')`).run();
  const halibut = await lookupRules(db, {region: 'morro-bay', speciesKey: 'halibut', now: T0});
  assert.deepEqual(halibut.map(r => [r.region, r.stale]), [['morro-bay', false], ['*', true]]);
  assert.ok(!('id' in halibut[0]) && !('updated_by' in halibut[0]));
});

dbTest('markJurisdictionForReview puts every active row of one jurisdiction back into review', async () => {
  const {sql, db} = seeded();
  sql.exec("UPDATE advisor_rules SET status='active'");
  assert.equal(await markJurisdictionForReview(db, 'california-central', T0), sql.prepare("SELECT COUNT(*) AS n FROM advisor_rules WHERE jurisdiction='california-central'").get().n);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM advisor_rules WHERE jurisdiction='california-central' AND status<>'review'").get().n, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM advisor_rules WHERE jurisdiction<>'california-central' AND status<>'active'").get().n, 0);
  assert.equal(sql.prepare("SELECT updated_by FROM advisor_rules WHERE jurisdiction='california-central' LIMIT 1").get().updated_by, 'rule-watch');
  assert.equal(await markJurisdictionForReview(db, 'california-central', T0), 0, 'nothing active is left');
});

// ---- the get_rules tool --------------------------------------------------------------

const ctx = (db, contact = {}) => ({env: {}, contact: {id: 'c1', role: 'angler', home_port: 'morro-bay', ...contact}, message: {id: 'm1'}, deps: {}, db,
  language: 'en', settings: advisorSettings({}), now: T0});

dbTest('get_rules: the table for the contact region, with source, checked date and stale; never a retired row', async () => {
  const {sql, db} = seeded();
  const tool = TOOL_BY_NAME.get('get_rules');
  const out = await tool.run({species_key: 'Lingcod'}, ctx(db));
  assert.equal(out.actions, undefined);
  assert.equal(out.result.region, 'morro-bay');
  assert.equal(out.result.rules.length, 1);
  assert.deepEqual([out.result.rules[0].size_min_in, out.result.rules[0].bag_limit, out.result.rules[0].stale, out.result.rules[0].checked], [22, 2, true, '2026-10-04']);
  assert.equal(out.result.rules[0].source_name, 'CDFW Central Region rules');
  assert.equal(out.result.any_stale, true);
  assert.equal(out.result.link, '{{link:rules:lingcod}}');
  // Another region by id; an unknown region falls back to the contact's.
  assert.equal((await tool.run({species_key: 'sheephead', region: 'southern-california'}, ctx(db))).result.rules[0].jurisdiction, undefined, 'internal columns stay out');
  assert.equal((await tool.run({species_key: 'sheephead', region: 'southern-california'}, ctx(db))).result.rules[0].bag_limit, 2);
  assert.equal((await tool.run({species_key: 'lingcod', region: 'atlantis'}, ctx(db))).result.region, 'morro-bay');
  sql.exec("UPDATE advisor_rules SET status='retired' WHERE species_key='lingcod'");
  const none = await tool.run({species_key: 'lingcod'}, ctx(db));
  assert.deepEqual(none.result.rules, []);
  assert.match(none.result.note, /check the current CDFW rules/);
  assert.ok(!JSON.stringify(none.result).includes('"unavailable"'), 'an empty answer is a real answer');
});

// ---- the engine's rules guard with a real get_rules call ------------------------------

function fakeApi(responses) {
  const requests = [], queue = [...responses];
  return {requests, async fetcher(_url, init) {
    requests.push(JSON.parse(init.body));
    const next = queue.shift();
    return new Response(JSON.stringify(next), {status: 200, headers: {'content-type': 'application/json'}});
  }};
}
const usage = {input_tokens: 100, output_tokens: 40};
function turnSetup(db, sql) {
  const iso = new Date(T0).toISOString();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,status,home_port,last_seen_at,created_at,updated_at) VALUES('c1','h1','ENC','imessage','angler','en','active','morro-bay',?,?,?)`).run(iso, iso, iso);
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES('old','c1','in','imessage','p-old','earlier','done',?)`).run(new Date(T0 - DAY).toISOString());
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES('in1','c1','in','imessage','p-in1','can I keep a vermilion?','processing',?)`).run(iso);
  return {env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_NUMBER: '+15555550199', ANTHROPIC_API_KEY: 'k'},
    contact: sql.prepare("SELECT * FROM advisor_contacts WHERE id='c1'").get(), message: sql.prepare("SELECT * FROM advisor_messages WHERE id='in1'").get()};
}

dbTest('rules guard: a real get_rules call that returned a stale row lets the reply quote it with "double-check" (recorded response)', async () => {
  const {sql, db} = seeded();
  const fixture = read('./fixtures/advisor/engine/tools/rules-stale-row.json');
  const api = fakeApi(fixture.exchanges.map(e => e.response.body));
  const {env, contact, message} = turnSetup(db, sql);
  const result = await runTurn({env, contact, message, now: T0, deps: {fetcher: api.fetcher, clock: () => T0, sleep: async () => {}}});
  const toolResult = JSON.parse(api.requests[1].messages.at(-1).content[0].content);
  assert.equal(toolResult.rules.find(r => r.species_key === 'vermilion').stale, true, 'the model saw a stale row');
  const reply = result.actions.find(a => a.type === 'send_text').text;
  assert.equal(result.intent, 'rules');
  assert.ok(reply.includes('double-check'), reply);
  for (const s of fixture.expect.reply_contains) assert.ok(reply.includes(s), `${s} in ${reply}`);
  assert.deepEqual(result.actions.filter(a => a.type === 'review_open'), [], 'the guard did not fire: a real get_rules call satisfied it');
  void usage;
});

dbTest('rules guard: a real get_rules call that returned no rows still counts as called (the model was told to send people to CDFW)', async () => {
  const {sql, db} = advisorDatabase();   // empty table
  const api = fakeApi([
    {content: [{type: 'tool_use', id: 't1', name: 'get_rules', input: {species_key: 'vermilion'}}], stop_reason: 'tool_use', usage},
    {content: [{type: 'text', text: 'I have no reviewed rule for vermilion yet, so check the current CDFW rules: {{link:rules:vermilion}}'}], stop_reason: 'end_turn', usage},
  ]);
  const {env, contact, message} = turnSetup(db, sql);
  const result = await runTurn({env, contact, message, now: T0, deps: {fetcher: api.fetcher, clock: () => T0, sleep: async () => {}}});
  assert.deepEqual(JSON.parse(api.requests[1].messages.at(-1).content[0].content).rules, []);
  assert.deepEqual(result.actions.filter(a => a.type === 'review_open'), []);
  assert.match(result.actions.find(a => a.type === 'send_text').text, /\/species\/vermilion\?s=txt#rules/);
});

dbTest('migration 0008 adds advisor_rules and advisor_daily_answers with their indexes', () => {
  const {sql} = advisorDatabase();
  const cols = t => sql.prepare(`PRAGMA table_info(${t})`).all().map(c => c.name);
  assert.deepEqual(cols('advisor_rules'), importer.COLUMNS);
  assert.deepEqual(cols('advisor_daily_answers'), ['key', 'text_en', 'text_es', 'inputs_hash', 'generated_at']);
  const idx = sql.prepare("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='advisor_rules'").all().map(r => r.name).sort();
  assert.deepEqual(idx.filter(n => !n.startsWith('sqlite_')), ['rule_due', 'rule_lookup']);
});

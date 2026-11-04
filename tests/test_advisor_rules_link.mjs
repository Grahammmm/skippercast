// RF1230-13: get_rules only hands the model a rules placeholder that resolves.
// A known species key (catalog or extra, synonyms canonicalised) keeps
// {{link:rules:<key>}}; anything else gets the general {{link:rules}} (the
// app's regulations card), never a rules:<raw> link that links.ts drops or, with
// a space in it, leaves in the reply as literal braces. Offline: node:sqlite.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json'),
  'crescent-city': read('../regions/crescent-city/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const importer = await import('../scripts/advisor/import-rules.mjs');
const {TOOL_BY_NAME} = await import('../server/advisor/tools/index.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');
const {resolveLinks} = await import('../server/advisor/links.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-04T17:00:00Z');
const BASE = 'https://advisor.example';
const ctx = db => ({env: {}, contact: {id: 'c1', role: 'angler', home_port: 'morro-bay'}, message: {id: 'm1'}, deps: {}, db,
  language: 'en', settings: advisorSettings({}), now: T0});
const seeded = () => { const {sql, db} = advisorDatabase(); sql.exec(importer.rulesSql(importer.importRows(T0))); return db; };
const tool = TOOL_BY_NAME.get('get_rules');
const run = async (db, species_key) => (await tool.run({species_key}, ctx(db))).result;
const reply = link => resolveLinks(`Check the current CDFW rules: ${link}`, BASE);

dbTest('a known species keeps its rules link; case and spaces are normalised', async () => {
  const db = seeded();
  for (const asked of ['lingcod', 'Lingcod ']) {
    const out = await run(db, asked);
    assert.equal(out.species_key, 'lingcod', asked);
    assert.equal(out.link, '{{link:rules:lingcod}}', asked);
    assert.equal(out.rules.length, 1, asked);
  }
  assert.deepEqual(reply('{{link:rules:lingcod}}').links, [`${BASE}/species/lingcod?s=txt#rules`]);
});

dbTest('a synonym keeps the tool\'s key and resolves to the canonical species page', async () => {
  const out = await run(seeded(), 'california-halibut');
  assert.equal(out.species_key, 'halibut');
  assert.equal(out.link, '{{link:rules:halibut}}');
  assert.deepEqual(reply(out.link).links, [`${BASE}/species/halibut?s=txt#rules`]);
});

dbTest('an unknown species with a space gets the general rules link, which resolves and leaves no braces', async () => {
  const out = await run(seeded(), 'sea dragon');
  assert.equal(out.species_key, 'sea dragon', 'the echoed key is unchanged');
  assert.equal(out.link, '{{link:rules}}');
  const r = reply(out.link);
  assert.deepEqual(r.links, [`${BASE}/?s=txt#species-regulations`]);
  assert.ok(!r.text.includes('{{'), r.text);
  // The old link would have stayed in the reply as literal braces.
  assert.ok(reply('{{link:rules:sea dragon}}').text.includes('{{'), 'the raw link was unresolvable');
});

dbTest('a placeholder-safe unknown key or punctuation gets the general link, never a dropped one', async () => {
  const db = seeded();
  for (const asked of ['zzz-unknown', 'blobfish?']) {
    const out = await run(db, asked);
    assert.equal(out.link, '{{link:rules}}', asked);
    assert.equal(reply(out.link).links.length, 1, asked);
  }
  assert.deepEqual(reply('{{link:rules:zzz-unknown}}').links, [], 'the raw link would have been dropped');
});

dbTest('an empty or non-string species_key gets the general link and does not throw', async () => {
  const db = seeded();
  for (const asked of ['', '   ', 42, null, undefined]) {
    const out = await run(db, asked);
    assert.equal(out.link, '{{link:rules}}', String(asked));
    assert.deepEqual(out.rules, [], String(asked));
  }
});

dbTest('an empty rules table and an unknown species: no rows, the CDFW note, the general link', async () => {
  const {db} = advisorDatabase();   // empty table
  const out = await run(db, 'sea dragon');
  assert.deepEqual(out.rules, []);
  assert.equal(out.any_stale, false);
  assert.equal(out.note, 'No reviewed rule for this species here: say to check the current CDFW rules and give the link. Do not state a number.');
  assert.equal(out.link, '{{link:rules}}');
  // A known species on the same empty table keeps its own link.
  assert.equal((await run(db, 'vermilion')).link, '{{link:rules:vermilion}}');
});

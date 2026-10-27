// SP-15-v1 / SP1504-RULE-JURISDICTIONS. Complete real module, real ruleKeys,
// real catalogs and migration-backed in-memory SQLite; no planner doubles.
import {installOffline, offlineEnv} from './fixtures/sp1504_rule_jurisdictions/offline.mjs';
import test, {after} from 'node:test';
// Install before the dynamic product import below, also in ordinary suite runs;
// this module owns the restore and attempted-boundary check.
after(installOffline());
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

if (sqliteUnavailable) throw new Error(sqliteUnavailable); // never silently skip
const read = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const oldGlobals = new Map(['REGIONS', 'DEPLOYMENT', 'BUILD_ID', 'ADVISOR_ASSETS'].map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
globalThis.REGIONS = {'southern-california': read('../regions/southern-california/region.json'), 'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.BUILD_ID = 'synthetic-sp1504';
globalThis.ADVISOR_ASSETS = {};
after(() => { for (const [key, descriptor] of oldGlobals) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
}});
const {speciesRules, speciesPage} = await import('../server/advisor/pages/species.ts');
const fixture = read('./fixtures/sp1504_rule_jurisdictions/rows.json');
const rows = new Map(fixture.rows.map(row => [row.id, {...fixture.defaults, ...row}]));
const SOUTH = 'california-southern', NORTH = 'california-northern';

async function withDatabase(ids, run) {
  const {sql, db} = advisorDatabase();
  try {
    for (const id of ids) {
      const row = rows.get(id);
      assert.ok(row, `unknown synthetic row ${id}`);
      const columns = Object.keys(row);
      sql.prepare(`INSERT INTO advisor_rules (${columns.join(',')}) VALUES (${columns.map(() => '?').join(',')})`).run(...Object.values(row));
    }
    // Product gets a read-only D1 facade, not the seeding handle or a live store.
    const readonly = {prepare(query) {
      if (!/^SELECT\b/i.test(query.trim())) throw new Error('SP1504_STORE_WRITE_FORBIDDEN');
      return db.prepare(query);
    }};
    return await run(readonly);
  } finally { sql.close(); }
}
const expected = ids => ids.map(id => ({row: rows.get(id), group: rows.get(id).species_key === 'rockfish'}));
const actual = selected => selected.map(({row, group}) => ({row: {...row}, group}));
async function select(ids, first = SOUTH) {
  return withDatabase(ids, async db => actual(await speciesRules(db, 'vermilion', first)));
}

test('primary regression', async () => {
  const result = await select(['own-south', 'parent-north']);
  assert.deepEqual(result, expected(['own-south', 'parent-north']), 'A1_JURISDICTION_FALLBACK: southern own must not hide northern parent');
});
test('healthy control', async () => {
  assert.deepEqual(await select(['parent-north']), expected(['parent-north']));
});

// Baseline defines EXACTLY the unchanged pair above; focused defines every A1-A4 case.
// The same pair runs green in focused, without pattern-induced skipped tests.
if (process.env.SP1504_MODE !== 'baseline') {
  test('A2 own rows suppress parent only in their jurisdiction, not per region', async () => {
    const input = ['parent-south', 'parent-north', 'own-south-regional', 'own-south'];
    assert.deepEqual(await select(input), expected(['own-south-regional', 'own-south', 'parent-north']));
    // A regional own row still suppresses this jurisdiction's global parent:
    // this change must not broaden within-jurisdiction regional fallback.
    assert.deepEqual(await select(['parent-south', 'own-south-regional', 'parent-north']), expected(['own-south-regional', 'parent-north']));
  });
  test('A3 parent-only keeps complete row content, default jurisdiction and regional ordering', async () => {
    const input = ['parent-central', 'parent-north', 'parent-north-regional', 'parent-south'];
    assert.deepEqual(await select(input, NORTH), expected(['parent-north-regional', 'parent-north', 'parent-central', 'parent-south']));
    assert.deepEqual(await select([...input].reverse(), NORTH), expected(['parent-north-regional', 'parent-north', 'parent-central', 'parent-south']));
  });
  test('A3 own-only preserves every own row and ordering', async () => {
    assert.deepEqual(await select(['own-south', 'own-south-regional']), expected(['own-south-regional', 'own-south']));
    assert.deepEqual(await select(['own-south-regional', 'own-south']), expected(['own-south-regional', 'own-south']));
  });
  test('A3 mixed membership independent of input and default jurisdiction', async () => {
    const input = ['parent-central', 'parent-south', 'own-south', 'parent-north', 'own-south-regional', 'parent-north-regional'];
    const southFirst = ['own-south-regional', 'own-south', 'parent-central', 'parent-north-regional', 'parent-north'];
    const northFirst = ['parent-north-regional', 'parent-north', 'parent-central', 'own-south-regional', 'own-south'];
    assert.deepEqual(await select(input), expected(southFirst));
    assert.deepEqual(await select([...input].reverse()), expected(southFirst));
    assert.deepEqual(await select(input, NORTH), expected(northFirst));
    assert.deepEqual(await select(input, null), expected(['parent-central', ...northFirst.filter(id => id !== 'parent-central')]));
  });
  test('A3 empty, unrelated and retired own rows do not hide active or review parents', async () => {
    assert.deepEqual(await select([]), []);
    assert.deepEqual(await select(['unrelated', 'retired-own-north']), []);
    assert.deepEqual(await select(['retired-own-north', 'parent-north', 'unrelated']), expected(['parent-north']));
  });
  test('A4 actual species page retains source, jurisdiction, region and review qualifiers in both languages', async () => {
    await withDatabase(['own-south', 'parent-south', 'parent-north', 'parent-central', 'own-south-regional'], async db => {
      for (const language of ['en', 'es']) {
        const page = await speciesPage(offlineEnv(db), 'vermilion', language,
          {publicBase: 'https://example.invalid', number: null, regionDefault: 'southern-california'},
          {clock: () => Date.parse('2026-09-28T19:00:00Z')});
        assert.equal(typeof page, 'string');
        const rules = page.match(/<section class="adv-card" id="rules"[\s\S]*?<\/section>/)?.[0];
        assert.ok(rules);
        assert.equal((rules.match(/<article class="adv-rule/g) || []).length, 4);
        assert.ok(!rules.includes('Synthetic southern rockfish'));
        assert.ok(rules.includes('Synthetic regional vermilion') && rules.includes('Southern California'));
        assert.equal((rules.match(/href="https:\/\/example.invalid\/synthetic-rules" rel="noopener">Synthetic CDFW source/g) || []).length, 4);
        assert.equal((rules.match(/adv-state-review/g) || []).length, 2, 'review status and expired active row remain stale');
        assert.ok(rules.indexOf(language === 'en' ? 'CDFW Southern region' : 'Región Southern de CDFW') < rules.indexOf('Synthetic central rockfish'));
        assert.ok(rules.includes(language === 'en' ? 'CDFW Northern region' : 'Región Northern de CDFW'));
        assert.ok(rules.includes(language === 'en' ? 'Group rule: Synthetic northern rockfish' : 'Regla del grupo: Synthetic northern rockfish'));
        assert.ok(rules.includes(language === 'en' ? 'This rule is due for review. Check the source before you keep a fish.' : 'Esta regla está pendiente de revisión. Revisa la fuente antes de quedarte un pez.'));
        const reviewedDate = new Intl.DateTimeFormat(language === 'en' ? 'en-US' : 'es-MX', {year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'}).format(new Date('2026-06-01T12:00:00Z'));
        assert.ok(rules.includes(`${language === 'en' ? 'Reviewed' : 'Revisada'}</dt><dd>${reviewedDate}</dd>`));
      }
    });
  });
}

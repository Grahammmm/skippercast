// SP-14-v1 A1-A4. Complete public answerFor, real migrations, synthetic rows.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
await import('./fixtures/sp1408_lookalike_rule/bootstrap.mjs');
const {advisorDatabase, sqliteUnavailable} = await import('./_advisor_d1.mjs');
if (sqliteUnavailable) throw Error(sqliteUnavailable); // Never convert capability failure into a skip.
const fixture = JSON.parse(readFileSync(new URL('./fixtures/sp1408_lookalike_rule/cases.json', import.meta.url), 'utf8'));
const globals = ['REGIONS', 'DEPLOYMENT', 'SHELLS', 'BUILD_ID'];
const saved = new Map(globals.map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
function restore() {
  for (const [k, descriptor] of saved) {
    if (descriptor) Object.defineProperty(globalThis, k, descriptor);
    else delete globalThis[k];
  }
}
function inject() {
  globalThis.REGIONS = {[fixture.region]: {jurisdiction_id: fixture.jurisdiction}};
  globalThis.DEPLOYMENT = {};
  globalThis.SHELLS = {};
  globalThis.BUILD_ID = 'sp1408-synthetic';
}
inject(); // Includes any import-time bound defaults.
const {answerFor} = await import('../server/advisor/answers/fishid.ts');
restore();
const idFor = (candidates = [fixture.top, fixture.second], extra = {}) => ({
  candidates: structuredClone(candidates), needs_better_photo: false, reason: null,
  provider: 'claude', model: 'synthetic-no-invocation', ms: 0, ...extra,
});
function row(sql, key, over = {}) {
  const r = {...fixture.row, ...over};
  sql.prepare(`INSERT INTO advisor_rules(id,region,jurisdiction,species_key,species_label,size_min_in,size_max_in,bag_limit,season_open,season_close,depth_limit_ft,source_name,source_url,reviewed_at,review_due,status,updated_by,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(`synthetic-${key}`, '*', fixture.jurisdiction, key, key,
    r.size_min_in, r.size_max_in, r.bag_limit, r.season_open, r.season_close, r.depth_limit_ft,
    r.source_name, r.source_url, r.reviewed_at, r.review_due, r.status, 'synthetic', fixture.now);
}
function scenario(name, fn) {
  test(name, {concurrency: false}, async () => {
    const before = Object.getOwnPropertyDescriptor(globalThis, 'fetch');
    inject();
    const {sql, db} = advisorDatabase();
    const answer = (language = 'en', id = idFor()) => answerFor(id, {db, region: fixture.region, now: Date.parse(fixture.now), language});
    try { await fn({sql, db, answer}); }
    finally { sql.close(); restore(); Object.defineProperty(globalThis, 'fetch', before); }
  });
}
const text = (language, ...keys) => keys.map(k => fixture[k][language]).join(' ');
const links = s => (s.match(/\{\{link:rules(?::[^}]+)?\}\}/g) || []).length;

// Exactly this pair is registered in baseline; no filtering-induced skips.
scenario('primary regression', async ({sql, answer}) => {
  row(sql, fixture.second.species_key);
  for (const language of ['en', 'es']) {
    const a = await answer(language);
    assert.equal(a.band, 'medium');
    assert.equal(a.rules, null);
    assert.equal(a.second_rules.bag_limit, 0);
    assert.equal(a.second_rules.source_url, fixture.row.source_url);
    assert.equal(a.text, text(language, 'prefix', 'none', 'secondCurrent'), `SP1408_PRIMARY_SEMANTIC_MISMATCH_${language}`);
    assert.equal(links(a.text), 1);
  }
});
scenario('healthy control', async ({sql, answer}) => {
  row(sql, fixture.top.species_key, {bag_limit: 2});
  row(sql, fixture.second.species_key);
  for (const language of ['en', 'es']) {
    const a = await answer(language);
    assert.equal(a.text, text(language, 'prefix', 'topCurrent', 'secondCurrent', 'link'));
    assert.equal(links(a.text), 1);
  }
});

if (process.env.SP1408_SUITE !== 'baseline') {
  scenario('A2 stale second never quotes numeric limits', async ({sql, answer}) => {
    row(sql, fixture.second.species_key, {status: 'review', size_min_in: 97, depth_limit_ft: 321});
    for (const language of ['en', 'es']) {
      const a = await answer(language);
      assert.equal(a.second_rules.stale, true);
      assert.equal(a.text, text(language, 'prefix', 'none', 'secondStale'));
      assert.doesNotMatch(a.text, /97|321|no take|no se puede quedar/);
    }
    sql.prepare("UPDATE advisor_rules SET status='active', review_due='2026-09-01'").run();
    for (const language of ['en', 'es']) assert.equal((await answer(language)).text, text(language, 'prefix', 'none', 'secondStale'));
  });
  scenario('A2 missing second keeps unchanged no-rule reply', async ({answer}) => {
    for (const language of ['en', 'es']) {
      const a = await answer(language);
      assert.equal(a.second_rules, null);
      assert.equal(a.text, text(language, 'prefix', 'none'));
    }
  });
  scenario('A3 null top key keeps generic no-rule branch', async ({sql, answer}) => {
    row(sql, fixture.second.species_key);
    for (const language of ['en', 'es']) {
      const a = await answer(language, idFor([{...fixture.top, species_key: null}, fixture.second]));
      assert.equal(a.rules, null);
      assert.equal(a.second_rules.bag_limit, 0); // Existing metadata, not newly displayed or selected.
      assert.equal(a.text, `${fixture.prefix[language]} ${fixture.none[language].replace(':sp1408-top', '')}`);
    }
  });
  scenario('A3 one candidate high and ask do not widen selection', async ({sql, answer}) => {
    row(sql, fixture.second.species_key);
    for (const language of ['en', 'es']) {
      const single = await answer(language, idFor([fixture.top]));
      assert.equal(single.second_rules, null);
      assert.ok(single.text.endsWith(fixture.none[language]));
      assert.equal(links(single.text), 1);
      const high = await answer(language, idFor([{...fixture.top, confidence: 0.85}, fixture.second]));
      assert.equal(high.band, 'high');
      assert.equal(high.second_rules, null);
      assert.ok(high.text.endsWith(fixture.none[language]));
      assert.doesNotMatch(high.text, /no take|no se puede quedar/);
      for (const id of [idFor([{...fixture.top, confidence: 0.599}, fixture.second]), idFor(undefined, {needs_better_photo: true, reason: 'blurry'}), idFor([])]) {
        const a = await answer(language, id);
        assert.equal(a.band, 'ask');
        assert.equal(a.rules, null);
        assert.equal(a.second_rules, null);
        assert.equal(links(a.text), 0);
      }
    }
  });
  scenario('A3 identical rules and same species suppress second sentence', async ({sql, answer}) => {
    row(sql, fixture.top.species_key, {bag_limit: 2});
    row(sql, fixture.second.species_key, {bag_limit: 2});
    for (const language of ['en', 'es']) {
      const a = await answer(language);
      assert.equal(a.second_rules, null);
      assert.equal(a.text, text(language, 'prefix', 'topCurrent', 'link'));
      const same = await answer(language, idFor([fixture.top, {...fixture.top, confidence: 0.2}]));
      assert.equal(same.second_rules, null);
      assert.equal(links(same.text), 1);
    }
  });
  scenario('A3 protected warning precedes caveat and lookalike rule', async ({sql, answer}) => {
    row(sql, 'yelloweye');
    const second = {species_key: 'yelloweye', label: 'Yelloweye rockfish', confidence: 0.3, cues: []};
    for (const [language, warning, rule] of [
      ['en', "If it's a yelloweye rockfish, it must be released: use a descending device.", "If it's a yelloweye rockfish: no take."],
      ['es', 'Si es ojo amarillo, hay que liberarlo: usa un descendedor.', 'Si es un ojo amarillo: no se puede quedar.'],
    ]) {
      const a = await answer(language, idFor([fixture.top, second]));
      assert.deepEqual(a.protected, ['yelloweye']);
      assert.ok(a.text.includes(`${warning} ${fixture.none[language]} ${rule}`), a.text);
      const below = await answer(language, idFor([fixture.top, {...second, confidence: 0.299}]));
      assert.deepEqual(below.protected, []);
      assert.ok(below.text.endsWith(`${fixture.none[language]} ${rule}`));
      // A third candidate can trigger the pre-existing protection but never rule lookup/composition.
      const third = await answer(language, idFor([fixture.top, fixture.second, second]));
      assert.deepEqual(third.protected, ['yelloweye']);
      assert.equal(third.second_rules, null);
      assert.ok(third.text.endsWith(fixture.none[language]));
    }
  });
  scenario('A2 stale top keeps second before stale caveat with one link', async ({sql, answer}) => {
    row(sql, fixture.top.species_key, {status: 'review', bag_limit: 2});
    row(sql, fixture.second.species_key);
    for (const language of ['en', 'es']) {
      const a = await answer(language);
      assert.ok(a.text.startsWith(`${fixture.prefix[language]} ${fixture.secondCurrent[language]} `));
      assert.equal(links(a.text), 1);
      assert.doesNotMatch(a.text, /bag 2|límite 2/);
    }
  });
}

import test, {after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {attempts, restoreOffline} from './fixtures/sp1406_alert_check/bootstrap.mjs';

// Install all sentinels and synthetic region configuration BEFORE product imports.
const FIXTURE = JSON.parse(readFileSync(new URL('./fixtures/sp1406_alert_check/cases.json', import.meta.url), 'utf8'));
const descriptors = ['REGIONS', 'DEPLOYMENT'].map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]);
globalThis.REGIONS = {'morro-bay': structuredClone(FIXTURE.region)};
globalThis.DEPLOYMENT = {default_region: 'morro-bay'};
const {tripConditions, planningBrief} = await import('../server/advisor/answers/planning.ts');
const {advisorDatabase, sqliteUnavailable} = await import('./_advisor_d1.mjs');
const BASELINE = process.env.SP1406_ALERT_CHECK_SUITE === 'baseline';
const MISSING = 'NWS advisories could not be checked: say so and point to the NWS forecast.';
after(() => {
  try { assert.deepEqual(attempts, [], 'no network/model/storage/process side effects'); }
  finally {
    for (const [key, descriptor] of descriptors) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
    }
    restoreOffline();
  }
});

const healthy = () => structuredClone(FIXTURE.healthy_sources);
function daily(sources) { return {...structuredClone(FIXTURE.daily), sources: structuredClone(sources)}; }
async function run(sources, {zones = FIXTURE.region.marine_zones, language = 'en', feed = daily(sources), brief = false} = {}) {
  const previous = globalThis.REGIONS;
  const calls = [];
  globalThis.REGIONS = {'morro-bay': {...structuredClone(FIXTURE.region), marine_zones: structuredClone(zones)}};
  const read = async url => {
    calls.push(url);
    if (url === FIXTURE.region.daily_feed) return structuredClone(feed);
    if (url === FIXTURE.region.intelligence_feed) return structuredClone(FIXTURE.intel);
    throw Error('unexpected synthetic feed URL');
  };
  const opts = {now: Date.parse(FIXTURE.now), language, read, deps: {feeds: read}};
  let db;
  try {
    let out;
    if (brief) {
      assert.equal(sqliteUnavailable, null, 'migration-backed memory DB is required; never skip');
      db = advisorDatabase();
      out = await planningBrief({DB: db.db}, {port: 'morro-bay', date: 'today', species: 'rockfish'}, opts);
    } else out = await tripConditions({port: 'morro-bay', date: 'today'}, opts);
    assert.ok(!out.error, 'full module must reach its semantic result');
    assert.ok(calls.includes(FIXTURE.region.daily_feed) && calls.includes(FIXTURE.region.intelligence_feed));
    assert.deepEqual(attempts, []);
    return out;
  } finally { db?.sql.close(); globalThis.REGIONS = previous; }
}
function incomplete(out) {
  assert.equal(out.advisories_checked, false, 'missing or invalid required-zone evidence is not a complete check');
  assert.equal(out.advisories_as_of, null);
  assert.ok(out.note.includes(MISSING));
}

// A4: baseline registers ONLY this unchanged pair, not skipped/filtered peers.
test('primary regression', async t => {
  const out = await run({});
  t.diagnostic('observed=' + JSON.stringify({advisories_checked: out.advisories_checked, advisories_as_of: out.advisories_as_of, advisories: out.advisories, note: out.note}));
  incomplete(out);
  assert.deepEqual(out.advisories, []);
  assert.equal(out.lead_with_advisory, false);
});
test('healthy control', async () => {
  const sources = healthy();
  // Equal times isolate completeness in the control; oldest/order is tested separately below.
  sources['alerts-PZZ670'].checked_at = sources['alerts-PZZ645'].checked_at;
  const out = await run(sources);
  assert.equal(out.advisories_checked, true);
  assert.equal(out.advisories_as_of, sources['alerts-PZZ645'].checked_at);
  assert.deepEqual(out.advisories, []);
  assert.equal(out.lead_with_advisory, false);
  assert.equal(out.advisory_line, undefined);
  assert.ok(!out.note.includes(MISSING));
});

if (!BASELINE) {
  test('A1 one missing required zone and unrelated successful zone', async () => {
    const sources = healthy();
    delete sources['alerts-PZZ670'];
    sources['alerts-UNRELATED'] = {...healthy()['alerts-PZZ670'], checked_at: '2026-09-28T19:00:00Z'};
    incomplete(await run(sources));
  });
  test('A1 missing daily feed', async () => { incomplete(await run({}, {feed: null})); });
  for (const status of FIXTURE.invalid_statuses) test(`A1 invalid status ${JSON.stringify(status)}`, async () => {
    const sources = healthy(); sources['alerts-PZZ670'].status = status;
    incomplete(await run(sources));
  });
  test('A1 missing status', async () => {
    const sources = healthy(); delete sources['alerts-PZZ670'].status;
    incomplete(await run(sources));
  });
  for (const alerts of FIXTURE.invalid_alerts) test(`A1 non-array alerts ${JSON.stringify(alerts)}`, async () => {
    const sources = healthy(); sources['alerts-PZZ670'].data.alerts = alerts;
    incomplete(await run(sources));
  });
  test('A1 absent data or alerts and non-object source', async () => {
    for (const value of [null, [], 'ok', 1, {status: 'ok', checked_at: FIXTURE.now}, {status: 'ok', checked_at: FIXTURE.now, data: {}}]) {
      const sources = healthy(); sources['alerts-PZZ670'] = value;
      incomplete(await run(sources));
    }
  });
  for (const checked_at of FIXTURE.invalid_times) test(`A1 invalid checked_at ${JSON.stringify(checked_at)}`, async () => {
    const sources = healthy(); sources['alerts-PZZ670'].checked_at = checked_at;
    incomplete(await run(sources));
  });
  test('A1 missing checked_at', async () => {
    const sources = healthy(); delete sources['alerts-PZZ670'].checked_at;
    incomplete(await run(sources));
  });
  test('A2 oldest required check independent of source insertion and unrelated zones', async () => {
    const sources = healthy();
    sources['alerts-UNRELATED'] = {status: 'ok', checked_at: '2001-01-01T00:00:00Z', data: {alerts: []}};
    for (const entries of [Object.entries(sources), Object.entries(sources).reverse()]) {
      const out = await run(Object.fromEntries(entries));
      assert.equal(out.advisories_checked, true);
      assert.equal(out.advisories_as_of, '2026-09-28T17:00:00Z');
      assert.deepEqual(out.advisories, []);
      assert.ok(!out.note.includes(MISSING));
    }
  });
  test('A2 compare timestamp instants not lexicographic strings; no new elapsed-age threshold', async () => {
    const sources = healthy();
    sources['alerts-PZZ645'].checked_at = '2000-01-01T12:00:00+10:00';
    sources['alerts-PZZ670'].checked_at = '2000-01-01T03:00:00Z';
    const out = await run(sources);
    assert.equal(out.advisories_checked, true);
    assert.equal(Date.parse(out.advisories_as_of), Date.parse('2000-01-01T02:00:00Z'));
    assert.ok(!out.note.includes(MISSING));
  });
  test('A2 no configured required zones is not a complete check', async () => { incomplete(await run(healthy(), {zones: {}})); });
  for (const language of ['en', 'es']) test(`A3 warning survives missing evidence and complete check in ${language}`, async () => {
    const sources = healthy();
    sources['alerts-PZZ645'].data.alerts = [FIXTURE.small_craft, FIXTURE.gale];
    const complete = await run(sources, {language, brief: true});
    const partialSources = structuredClone(sources); delete partialSources['alerts-PZZ670'];
    const partial = await run(partialSources, {language, brief: true});
    incomplete(partial);
    assert.equal(complete.advisories_checked, true);
    assert.equal(complete.advisories_as_of, '2026-09-28T17:00:00Z');
    assert.ok(!complete.note.includes(MISSING));
    const expectedLine = language === 'en' ? 'GALE WARNING posted for today. SMALL CRAFT ADVISORY posted for today.'
      : 'GALE WARNING (aviso del NWS) para hoy. SMALL CRAFT ADVISORY (aviso del NWS) para hoy.';
    for (const out of [partial, complete]) {
      assert.deepEqual(out.advisories.map(a => [a.event, a.zone]), [['Gale Warning', 'PZZ645'], ['Small Craft Advisory', 'PZZ645']]);
      assert.equal(out.lead_with_advisory, true);
      assert.equal(out.advisory_line, expectedLine);
      assert.ok(Object.keys(out).indexOf('advisory_line') < Object.keys(out).indexOf('days'));
      assert.equal(out.planning.closer, language === 'en' ? 'Check the latest NWS forecast before you go.' : 'Revisa el pronóstico más reciente del NWS antes de salir.');
      assert.ok(out.note.includes(out.planning.closer));
      assert.equal(out.planning.season.status, 'no_rule');
      assert.equal(out.planning.confidence, 'Insufficient');
    }
    assert.deepEqual(partial.advisories, complete.advisories);
    assert.deepEqual(partial.days, complete.days);
    assert.deepEqual(partial.planning, complete.planning);
    assert.equal(partial.forecast_issued, FIXTURE.intel.completed_at);
  });
  test('A3 known warnings survive a non-ok check status', async () => {
    const sources = healthy(); sources['alerts-PZZ645'].status = 'retained';
    sources['alerts-PZZ645'].data.alerts = [FIXTURE.gale];
    const out = await run(sources);
    incomplete(out);
    assert.equal(out.advisories[0].event, 'Gale Warning');
    assert.equal(out.advisory_line, 'GALE WARNING posted for today.');
    assert.equal(out.lead_with_advisory, true);
  });
}

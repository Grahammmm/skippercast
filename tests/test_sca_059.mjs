import assert from 'node:assert/strict';
import test from 'node:test';
import region from '../regions/morro-bay/region.json' with {type: 'json'};
import {advisorDatabase} from './_advisor_d1.mjs';

const port = 'morro-bay', date = '2026-09-28';
const now = Date.parse(`${date}T19:00:00Z`), hour = 3600000;
const published = '2026-09-27T19:00:00Z';
const dailyUrl = 'https://example.invalid/latest.json', forecastUrl = 'https://example.invalid/intelligence.json';
Object.assign(globalThis, {REGIONS: {[port]: {...region, daily_feed: dailyUrl, intelligence_feed: forecastUrl}}, DEPLOYMENT: {allowed_origins: []}, ADVISOR_ASSETS: {}});
const {dailyAnswer, dailyInputs, currentInputsHash} = await import('../server/advisor/answers/reports.ts');
const {getPortReport} = await import('../server/advisor/tools/get_port_report.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');

const catchReport = {id: 'synthetic-catch', date: '2026-09-27', port: 'Morro Bay', boat: 'Example Landing Boat', catches: [{species: 'lingcod', count: 73}]};
const unavailable = /Landing reports: Not available\./;
const retainedCatch = /Example Landing Boat|\b73\b|The landing reports \d+ trip/;

function fixture(t, {age = 37, reports = [catchReport], advisories = []} = {}) {
  const {sql, db} = advisorDatabase();
  t.after(() => sql.close());
  const feed = {schema_version: 1, region_id: port, generated_at: new Date(now - age * hour).toISOString(),
    reports, health: {}, sources: {[`alerts-${region.marine_zones.coastal}`]: {status: 'ok', data: {alerts: advisories}}},
    catch_probability: null, bite_score: null};
  const denyRequest = t.mock.method(globalThis, 'fetch', async () => { throw Error('External requests forbidden'); });
  t.after(() => assert.equal(denyRequest.mock.callCount(), 0));
  const env = {DB: db, ANTHROPIC_API_KEY: 'synthetic-not-a-key'};
  const deps = {clock: () => now, feeds: async url => {
    if (url === dailyUrl) return feed;
    assert.equal(url, forecastUrl);
    return {region_id: port};
  }};
  return {sql, env, deps, tool: async (language = 'en') => (await getPortReport.run({port}, {
    env, db, now, deps, contact: {home_port: port}, settings: advisorSettings(env), language,
  })).result};
}

test('text tool marks an in-window catch in a stale feed unavailable and withholds landing activity', async t => {
  const {tool} = fixture(t, {advisories: [{event: 'Gale Warning', onset: `${date}T15:00:00Z`, ends: `${date}T20:00:00Z`}]});
  const out = await tool();
  assert.equal(out.landing.available, false);
  assert.equal(out.landing.reports, undefined);
  assert.equal(out.landing.recent_activity, undefined);
  assert.equal(out.freshness.newest_landing_report, null);
  assert.match(out.landing.note, unavailable);
  assert.match(out.daily.text, unavailable);
  assert.match(out.daily.text, /^GALE WARNING posted for today\./);
  assert.doesNotMatch(JSON.stringify(out), retainedCatch);
});

test('daily composition with a stale feed preserves a published skipper report, not cached landing counts', async t => {
  const {sql, env, deps, tool} = fixture(t);
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)`)
    .run('synthetic-boat', 'example-skipper', 'Example Skipper Boat', port, port, 'verified', published, published);
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,port,region,report_date,counts_json,source,status,verified,published_at,created_at,updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`).run('synthetic-skipper-report', 'synthetic-boat', port, port, '2026-09-27',
    JSON.stringify([{species_key: 'rockfish', label: 'rockfish', kept: 3}]), 'synthetic', 'published', 1, published, published, published);
  const hashWhileFresh = await currentInputsHash(env, port, date, deps, now - hour);
  sql.prepare('INSERT INTO advisor_daily_answers(key,text_en,text_es,inputs_hash,generated_at) VALUES (?,?,?,?,?)')
    .run(`${port}:${date}`, 'The landing reports 1 trip. Example Landing Boat: 73 lingcod.', 'El muelle reporta 73 lingcod.', hashWhileFresh, published);
  const daily = await dailyAnswer(env, port, date, 'en', deps);
  assert.equal(daily.source, 'composed');
  assert.match(daily.text, unavailable);
  assert.match(daily.text, /Example Skipper Boat reported yesterday: 3 rockfish\./);
  assert.doesNotMatch(daily.text, retainedCatch);
  assert.match(daily.text_es, /Reportes del muelle: No disponibles\./);
  assert.equal(sql.prepare('SELECT inputs_hash FROM advisor_daily_answers').get().inputs_hash, hashWhileFresh);
  const out = await tool('es');
  assert.match(out.landing.note, /Reportes del muelle: No disponibles\./);
  assert.equal(out.skipper_reports[0].counts[0].kept, 3);
});

for (const reports of [[], [catchReport]]) {
  test(`a fresh ${reports.length ? 'positive' : 'empty'} feed remains available at 36 hours`, async t => {
    const {env, deps, tool} = fixture(t, {age: 36, reports});
    const out = await tool();
    assert.equal(out.landing.available, true);
    assert.equal(out.landing.reports.length, reports.length);
    const inputs = await dailyInputs(env, port, date, deps, now);
    assert.equal(inputs.landing.available, true);
    assert.equal(inputs.landing.reports.length, reports.length);
    assert.doesNotMatch(out.daily.text, unavailable);
    if (reports.length) assert.match(out.daily.text, /The landing reports 1 trip.*recent reported activity: Low\./);
    else assert.match(out.daily.text, /No reports from the last three days for Morro Bay yet\./);
  });
}

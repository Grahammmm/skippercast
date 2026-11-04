// SC2007-05: a boating advisory overlapping the fishing window makes the advisor's comfort word
// 'rough' and names the advisory, as the brief does (web/brief/verdict.ts); numbers stay as measured.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {isDeepStrictEqual} from 'node:util';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const conditions = await import('../server/advisor/answers/conditions.ts');
const {tripConditions} = await import('../server/advisor/answers/planning.ts');
const {dailyInputs} = await import('../server/advisor/answers/reports.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');

const REGION = REGIONS['morro-bay'], ZONES = conditions.regionZones(REGION);
const DAILY = () => read('./fixtures/feeds/daily-latest.json');
const SCA = {event: 'Small Craft Advisory'};
const NOT_ROUGH = ['comfortable', 'bumpy'];

/** The intelligence fixture with calm numbers, its three hours repeated at each start (epoch s). */
function calmIntel(starts, run = null) {
  const intel = read('./fixtures/feeds/intelligence.json'), t0 = intel.forecast.models.gfs_global.data[0].hourly.time[0];
  const calm = {wind_speed_10m: 5, wind_gusts_10m: 7, wave_height: 1.5, wind_wave_height: 0.5, swell_wave_height: 1, secondary_swell_wave_height: 0.5};
  for (const model of Object.values(intel.forecast.models)) {
    if (run !== null && model?.meta) model.meta.last_run_initialisation_time = run;   // keeps the model run fresh for a later `now`
    for (const p of model.data ?? []) {
      if (!p?.hourly) continue;
      const h = p.hourly, base = h.time;
      for (const k of Object.keys(h)) if (k !== 'time') h[k] = starts.flatMap(() => h[k].map(v => v !== null && k in calm ? calm[k] : v));
      h.time = starts.flatMap(s => base.map(t => t - t0 + s));
    }
  }
  return intel;
}
const at = iso => Date.parse(iso) / 1000;
const SEP28 = () => calmIntel([at('2026-09-28T14:00:00Z')]);   // 07:00-09:00 PDT on 28 Sep
const alert = (event, onset, ends) => ({event, headline: `${event} synthetic`, onset, ends});
const dailyWith = (...alerts) => { const d = DAILY(); d.sources['alerts-PZZ645'].data.alerts = alerts; return d; };

test('an available day that reads comfortable or bumpy reads rough under a Small Craft Advisory; numbers unchanged', () => {
  const plain = conditions.windowConditions(SEP28(), REGION, 'central', '2026-09-28');
  assert.equal(plain.available, true);
  assert.ok(NOT_ROUGH.includes(plain.comfort), `baseline reads ${plain.comfort}`);
  assert.equal('advisory' in plain, false);
  const day = conditions.windowConditions(SEP28(), REGION, 'central', '2026-09-28', conditions.WINDOW, null, [SCA]);
  assert.equal(day.comfort, 'rough');
  assert.equal(day.advisory, 'Small Craft Advisory');
  for (const k of ['available', 'wind_kt', 'wind_from', 'gusts_kt', 'seas_ft', 'sea_period_s', 'swell_ft', 'swell_period_s', 'swell_from', 'models_agree', 'comfort_for', 'window', 'date']) {
    assert.ok(isDeepStrictEqual(day[k], plain[k]), `${k} as measured`);
  }
});

test('no advisories: output byte-identical to the call without advisories (no advisory key)', () => {
  const five = conditions.windowConditions(SEP28(), REGION, 'central', '2026-09-28', conditions.WINDOW);
  const six = conditions.windowConditions(SEP28(), REGION, 'central', '2026-09-28', conditions.WINDOW, null, []);
  assert.equal(JSON.stringify(six), JSON.stringify(five));
  assert.equal(JSON.stringify(conditions.windowConditions(SEP28(), REGION, 'central', '2026-09-28')), JSON.stringify(five));
});

test('an unavailable day stays unknown with no advisory key, whatever the advisory', () => {
  for (const day of [conditions.windowConditions(SEP28(), REGION, 'central', '2026-09-30', conditions.WINDOW, null, [SCA]),
    conditions.windowConditions({...SEP28(), region_id: 'elsewhere'}, REGION, 'central', '2026-09-28', conditions.WINDOW, null, [SCA]),
    conditions.windowConditions(SEP28(), REGION, 'nowhere', '2026-09-28', conditions.WINDOW, null, [SCA])]) {
    assert.deepEqual([day.available, day.comfort, 'advisory' in day], [false, 'unknown', false]);
  }
});

test('two advisories: the advisory named is the first in advisoriesFrom order (gale before small craft)', () => {
  const daily = dailyWith(alert('Small Craft Advisory', '2026-09-28T06:00:00-07:00', '2026-09-28T20:00:00-07:00'),
    alert('Gale Warning', '2026-09-28T08:00:00-07:00', '2026-09-28T20:00:00-07:00'));
  const [from, to] = conditions.windowEpochs('2026-09-28', REGION.timezone);
  const found = conditions.advisoriesFrom(daily, ZONES, from, to);
  assert.deepEqual(found.map(a => a.event), ['Gale Warning', 'Small Craft Advisory']);
  const day = conditions.windowConditions(SEP28(), REGION, 'central', '2026-09-28', conditions.WINDOW, null, found);
  assert.deepEqual([day.comfort, day.advisory], ['rough', 'Gale Warning']);
});

test('an advisory outside the window is excluded by advisoriesFrom and leaves comfort unchanged', () => {
  const daily = dailyWith(alert('Small Craft Advisory', '2026-09-28T16:00:00-07:00', '2026-09-28T23:00:00-07:00'),
    alert('Gale Warning', '2026-09-27T12:00:00-07:00', '2026-09-28T05:00:00-07:00'));
  const [from, to] = conditions.windowEpochs('2026-09-28', REGION.timezone);
  const found = conditions.advisoriesFrom(daily, ZONES, from, to);
  assert.deepEqual(found, []);
  const day = conditions.windowConditions(SEP28(), REGION, 'central', '2026-09-28', conditions.WINDOW, null, found);
  assert.ok(NOT_ROUGH.includes(day.comfort));
  assert.equal('advisory' in day, false);
});

test('get_conditions over a two-day ask: only the day the advisory overlaps reads rough', async () => {
  const intel = calmIntel([at('2026-10-03T14:00:00Z'), at('2026-10-04T14:00:00Z')], at('2026-10-03T12:00:00Z'));   // 07:00-09:00 PDT Sat and Sun
  const daily = dailyWith(alert('Small Craft Advisory', '2026-10-04T06:00:00-07:00', '2026-10-04T18:00:00-07:00'),
    alert('Gale Warning', '2026-10-03T16:00:00-07:00', '2026-10-03T22:00:00-07:00'));   // after Saturday's window
  const feeds = async url => /intelligence\.json$/.test(url) ? intel : /latest\.json$/.test(url) ? daily : Promise.reject(Error('no feed'));
  const out = await tripConditions({port: 'morro-bay', date: 'this weekend'},
    {now: Date.parse('2026-10-03T17:00:00Z'), language: 'en', contact: {home_port: 'morro-bay'}, settings: advisorSettings({}), deps: {feeds}});
  assert.deepEqual(out.dates, ['2026-10-03', '2026-10-04']);
  const [sat, sun] = out.days;
  assert.deepEqual([sat.available, sun.available], [true, true]);
  assert.ok(NOT_ROUGH.includes(sat.comfort), `Saturday reads ${sat.comfort}`);
  assert.equal('advisory' in sat, false);
  assert.deepEqual([sun.comfort, sun.advisory], ['rough', 'Small Craft Advisory']);
  assert.ok(isDeepStrictEqual([sun.wind_kt, sun.seas_ft], [sat.wind_kt, sat.seas_ft]), 'the same numbers both days');
});

test('daily report inputs: an advisory in the window makes conditions.day.comfort rough; without it, not', {skip: sqliteUnavailable || false}, async () => {
  const {sql, db} = advisorDatabase();
  try {
    const NOW = Date.parse('2026-09-28T19:00:00Z');
    const run = daily => dailyInputs({DB: db}, 'morro-bay', '2026-09-28', {feeds: async url => /intelligence\.json$/.test(url) ? SEP28() : /latest\.json$/.test(url) ? daily : Promise.reject(Error('no feed'))}, NOW);
    const rough = (await run(DAILY())).conditions;   // the fixture's Small Craft Advisory, 12:00-23:00 on 28 Sep
    assert.deepEqual([rough.available, rough.advisories, rough.day.comfort], [true, ['Small Craft Advisory'], 'rough']);
    const quiet = (await run(dailyWith())).conditions;
    assert.deepEqual(quiet.advisories, []);
    assert.ok(NOT_ROUGH.includes(quiet.day.comfort), `reads ${quiet.day.comfort}`);
    assert.ok(isDeepStrictEqual([quiet.day.wind_kt, quiet.day.seas_ft], [rough.day.wind_kt, rough.day.seas_ft]));
  } finally { sql.close(); }
});

test('an old (held) model run keeps the advisory rough word and its name; without an advisory a calm word is held at unknown', () => {
  const held = {state: 'held', ageHours: 20};
  const rough = conditions.withForecastClock(conditions.windowConditions(SEP28(), REGION, 'central', '2026-09-28', conditions.WINDOW, null, [SCA]), held);
  assert.deepEqual([rough.comfort, rough.advisory, 'comfort_held' in rough], ['rough', 'Small Craft Advisory', false]);
  const calm = conditions.withForecastClock(conditions.windowConditions(SEP28(), REGION, 'central', '2026-09-28'), held);
  assert.deepEqual([calm.comfort, 'advisory' in calm], ['unknown', false]);
});

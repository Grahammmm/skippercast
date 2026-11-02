// BF-stale-never-calmer: aged forecast data never wears a calm label. One age ladder on every
// surface that can say calm (brief verdict, coast assessment, trip alert policy, text-advisor
// comfort word); the exact limit of each is pinned, and aging never turns a non-calm result calm.
// Synthetic feeds, values invented.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {boatVerdict, feedReader, ALERT_CHECK_MISSING} from '../web/brief/verdict.ts';
import {assess} from '../packages/coast/src/assessment.ts';
import {slo} from '../packages/coast/src/counties.ts';
import {assessTrip} from '../server/alert-policy.ts';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {forecastClock} = await import('../server/advisor/answers/forecast-clock.ts');
const {withForecastClock, windowConditions} = await import('../server/advisor/answers/conditions.ts');
const {COMFORT_WORD} = await import('../server/advisor/answers/comfort.ts');
const {tripConditions} = await import('../server/advisor/answers/planning.ts');
const {dailyInputs} = await import('../server/advisor/answers/reports.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');

const H = 3600;
const LADDER = [['0 h', 0], ['17:59:59', 18 * H - 1], ['18 h', 18 * H], ['18 h + 1 s', 18 * H + 1], ['35:59:59', 36 * H - 1], ['36 h', 36 * H], ['36 h + 1 s', 36 * H + 1], ['2 h ahead', -2 * H]];
const LIMIT = (limit, calm, other, beyond = other) => LADDER.map(([, age]) => age < 0 ? beyond : age <= limit ? calm : age <= 36 * H ? other : beyond);

/** Run the ladder; check the pinned labels and that, by age, nothing after a non-calm rung is calm again. */
function ladder(surface, run, expected, calm) {
  const got = LADDER.map(([, age]) => run(age));
  for (const [i, [rung]] of LADDER.entries()) console.log(`${surface.padEnd(22)} ${rung.padEnd(11)} → ${got[i]}`);
  assert.deepEqual(got, expected, surface);
  const aged = LADDER.map(([, age], i) => [age, got[i]]).filter(([age]) => age >= 0).sort((a, b) => a[0] - b[0]);
  const first = aged.findIndex(([, label]) => label !== calm);
  if (first >= 0) assert.ok(aged.slice(first).every(([, label]) => label !== calm), `${surface}: aging turned a non-calm result calm`);
  assert.notEqual(got.at(-1), calm, `${surface}: a run dated ahead is never fresh`);
}

// ---- brief verdict (tests/test_brief_verdict.mjs forecast()) ----
const TZ = 'America/Los_Angeles', DATE = '2026-10-13', NOW = new Date('2026-10-13T12:00:00Z');
const START = Date.parse('2026-10-13T07:00:00Z') / 1000, TIMES = Array.from({length: 48}, (_, i) => START + i * 3600);
const BASE = {wind_speed_10m: 6, wind_gusts_10m: 9, wind_direction_10m: 315, ecmwf_wind: 6, ecmwf_gust: 9, wave_height: 2.5, wave_period: 11, wind_wave_height: 0.3, wind_wave_period: 4,
  swell_wave_height: 2.4, swell_wave_period: 11, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200, wam: 2.5};
const ROUGH = {wind_speed_10m: 28, wind_gusts_10m: 36, ecmwf_wind: 28, ecmwf_gust: 36, wave_height: 10, wam: 10, wind_wave_height: 6, wind_wave_period: 5};
const UNITS = {wind_speed_10m: 'kn', wind_gusts_10m: 'kn', wind_direction_10m: '°', wave_height: 'ft', wave_period: 's', wind_wave_height: 'ft', wind_wave_period: 's',
  swell_wave_height: 'ft', swell_wave_period: 's', swell_wave_direction: '°', secondary_swell_wave_height: 'ft', secondary_swell_wave_direction: '°'};
function forecast(ageS, {over = {}, ages = {}} = {}) {
  const v = {...BASE, ...over};
  const series = keys => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(([k]) => [k, UNITS[k]]))}, hourly: {time: TIMES, ...Object.fromEntries(keys.map(([k, src]) => [k, TIMES.map(() => v[src ?? k])]))}});
  const run = (id, keys) => ({id, issued: NOW.getTime() / 1000 - (ages[id] ?? ageS), end: TIMES.at(-1), data: series(keys)});
  return {region: 'morro-bay', retrieved: NOW.getTime(), point: {id: 'morro-bay', lat: 35.37, lon: -120.9}, models: {
    gfs_global: run('gfs_global', [['wind_speed_10m'], ['wind_gusts_10m'], ['wind_direction_10m']]),
    ncep_gfswave016: run('ncep_gfswave016', ['wave_height', 'wave_period', 'wind_wave_height', 'wind_wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction', 'secondary_swell_wave_height', 'secondary_swell_wave_direction'].map(k => [k])),
    ecmwf_ifs025: run('ecmwf_ifs025', [['wind_speed_10m', 'ecmwf_wind'], ['wind_gusts_10m', 'ecmwf_gust']]),
    ecmwf_wam: run('ecmwf_wam', [['wave_height', 'wam']])}};
}
const brief = (over = {}) => ({profile: 'boat', date: DATE, sunrise: '2026-10-13T14:10:00Z', sunset: '2026-10-14T01:30:00Z', alerts: [], missing: [], bar: null, shore: null, spear: null, kayak: null, tiles: [], ...over});
const briefAt = (age, opts, b = brief()) => boatVerdict(b, forecast(age, opts), NOW, TZ).verdict;
const feedReaderOldest = f => feedReader(f, NOW).oldestMs;

// ---- coast assessment (tests/fixtures/coast/skippercast-report.json, its advisory removed) ----
const REPORT = read('./fixtures/coast/skippercast-report.json'), AREA = slo.areas.find(a => a.id === 'central');
const COAST_NOW = new Date(Date.parse(REPORT.generatedAt) + 10 * 60_000), ago = s => new Date(COAST_NOW.getTime() - s * 1000).toISOString();
function coastAt({issued = H, fetched = 600, alerts = 600} = {}) {
  const sources = REPORT.sources.map(s => s.id === 'nws-alerts' ? {...s, fetchedAt: ago(alerts)} : s.id.startsWith('nws-') ? {...s, issuedAt: ago(issued), fetchedAt: ago(fetched)} : s);
  const forecasts = REPORT.forecasts.map(f => ({...f, hours: f.hours.map(h => ({...h, waveFt: 3}))}));   // the fixture's 4.003 ft is just over the boat limit
  const a = assess({...REPORT, forecasts, alerts: [], sources}, AREA, 'boat', COAST_NOW, slo.timezone);
  return a.status === 'Unknown' ? 'Unknown' : a.windows.length ? 'calm' : a.status;
}

// ---- trip alert policy (tests/test_alert_dst_window.mjs intel, completed) ----
const REGION = {id: 'r', timezone: TZ, forecast_points: [{id: 'p', latitude: 1, longitude: 2}]}, P_NOW = Date.parse('2026-10-31T20:00:00Z');
const TRIP = {point: 'p', date: '2026-10-31', species: 'rockfish', start_hour: 7, end_hour: 12, wind_limit: 15, gust_limit: 20, sea_limit: 6};
const RULES = {valid_from: '2026-01-01', valid_through: '2026-12-31', species: {rockfish: {windows: [{start: '2026-01-01', end: '2026-12-31'}], source_ids: []}}};
const P_TIMES = Array.from({length: 14}, (_, i) => Date.parse('2026-10-31T10:00:00Z') / 1000 + i * 3600);
function policyIntel(ageS, {completed = 600} = {}) {
  const pt = (units, values) => [{hourly_units: {time: 'unixtime', ...units}, hourly: {time: P_TIMES, ...Object.fromEntries(Object.entries(values).map(([k, x]) => [k, P_TIMES.map(() => x)]))}}];
  const wind = pt({wind_speed_10m: 'kn', wind_gusts_10m: 'kn', visibility: 'm', weather_code: 'wmo code'}, {wind_speed_10m: 5, wind_gusts_10m: 8, visibility: 20000, weather_code: 0});
  const wave = pt({wave_height: 'ft', wave_period: 's', wind_wave_height: 'ft'}, {wave_height: 2, wave_period: 10, wind_wave_height: 0.5});
  const ids = ['gfs_global', 'ecmwf_ifs025', 'ncep_gfswave016', 'ecmwf_wam'];
  return {region_id: 'r', completed_at: new Date(P_NOW - completed * 1000).toISOString(), sources: Object.fromEntries(ids.map(id => [`model-${id}`, {status: 'ok'}])),
    forecast: {requested_points: [['p', 1, 2]], models: Object.fromEntries(ids.map((id, i) => [id, {data: i < 2 ? wind : wave, error: null, meta: {last_run_initialisation_time: P_NOW / 1000 - ageS, data_end_time: P_TIMES.at(-1) + 86400}}]))}};
}
const policy = intel => assessTrip(TRIP, REGION, intel, RULES, [], P_NOW);

// ---- text advisor (tests/fixtures/feeds/intelligence.json, re-timed to the morning window) ----
const A_NOW = Date.parse('2026-09-28T12:00:00Z'), A_DATE = '2026-09-28';   // 5 am in Morro Bay
const A_TIMES = Array.from({length: 9}, (_, i) => Date.parse('2026-09-28T13:00:00Z') / 1000 + i * 3600);   // 6 am-2 pm
const CALM = {wind_speed_10m: 5, wind_gusts_10m: 7, wind_direction_10m: 315, wave_height: 2, wave_period: 11, wind_wave_height: 0.3, wind_wave_period: 4,
  swell_wave_height: 1.9, swell_wave_period: 11, swell_wave_direction: 290, secondary_swell_wave_height: 0.3, secondary_swell_wave_direction: 200};
const A_ROUGH = {...CALM, wind_speed_10m: 28, wind_gusts_10m: 36, wave_height: 10, wind_wave_height: 6, wind_wave_period: 5};
function intelAt(ageS, {values = CALM, ages = {}, completed = A_NOW, edit = () => {}} = {}) {
  const intel = read('./fixtures/feeds/intelligence.json');
  intel.completed_at = new Date(completed).toISOString();
  for (const [id, m] of Object.entries(intel.forecast.models)) {
    for (const point of m.data) for (const key of Object.keys(point.hourly)) point.hourly[key] = key === 'time' ? A_TIMES : A_TIMES.map(() => values[key] ?? 0);
    m.meta.last_run_initialisation_time = A_NOW / 1000 - (ages[id] ?? ageS);
  }
  edit(intel);
  return intel;
}
const feeds = intel => async url => /intelligence\.json$/.test(url) ? intel : /latest\.json$/.test(url) ? read('./fixtures/feeds/daily-latest.json') : Promise.reject(Error('no feed'));
const trip = (intel, date = A_DATE) => tripConditions({port: 'morro-bay', date}, {now: A_NOW, language: 'en', deps: {feeds: feeds(intel)}, contact: null, settings: advisorSettings({})});
const stmt = {bind: () => stmt, all: async () => ({results: []}), first: async () => null, run: async () => ({meta: {changes: 0}})};
const daily = intel => dailyInputs({DB: {prepare: () => stmt}}, 'morro-bay', A_DATE, {feeds: feeds(intel)}, A_NOW);
const advisorWord = async (age, opts) => { const d = (await trip(intelAt(age, opts))).days[0]; return d.available ? d.comfort : 'unavailable'; };

test('brief verdict: Comfortable through 18 h, Marginal to 36 h, Unknown after and for a run dated ahead', () => {
  ladder('brief verdict', age => briefAt(age), LIMIT(18 * H, 'comfortable', 'marginal', 'unknown'), 'comfortable');
  assert.match(boatVerdict(brief(), forecast(18 * H + 1), NOW, TZ).held, /forecast run is 18 h old/);
  ladder('brief, alert check gone', age => briefAt(age, {}, brief({missing: [ALERT_CHECK_MISSING]})), LIMIT(-1, 'comfortable', 'marginal', 'unknown'), 'comfortable');
});

test('coast assessment: a window through 18 h, Unknown past it or ahead; the alert check at 2 h ± 1 s', () => {
  ladder('coast assessment', age => coastAt({issued: age}), LIMIT(18 * H, 'calm', 'Unknown'), 'calm');
  assert.deepEqual([2 * H - 1, 2 * H, 2 * H + 1, -2 * H].map(alerts => coastAt({alerts})), ['calm', 'calm', 'Unknown', 'Unknown'], 'nws-alerts age');
  assert.deepEqual([2 * H, 2 * H + 1].map(fetched => coastAt({fetched})), ['calm', 'Unknown'], 'forecast fetch age');
});

test('trip alert policy: within limits through 36 h, unverified past it or ahead; the feed clock at 3 h ± 1 s', () => {
  ladder('trip alert policy', age => policy(policyIntel(age)).status, LIMIT(36 * H, 'within limits', 'within limits', 'unverified'), 'within limits');
  assert.deepEqual([3 * H - 1, 3 * H, 3 * H + 1, -2 * H].map(completed => policy(policyIntel(H, {completed})).status), ['within limits', 'within limits', 'unverified', 'unverified'], 'feed completed_at');
  // A cached feed rebuilt now still flags the old runs.
  assert.ok(policy(policyIntel(40 * H, {completed: 0})).issues.includes('gfs_global is unavailable or stale'));
});

test('text advisor: comfortable through 18 h, held at unknown to 36 h, unavailable after and for a run dated ahead', async () => {
  const words = [];
  for (const [, age] of LADDER) words.push(await advisorWord(age));
  ladder('text advisor', age => words[LADDER.findIndex(([, a]) => a === age)], LIMIT(18 * H, 'comfortable', 'unknown', 'unavailable'), 'comfortable');
  const held = await trip(intelAt(20 * H));
  assert.equal(held.days[0].comfort_held, 'forecast run is 20 h old');
  assert.deepEqual([held.forecast_age_hours, (await trip(intelAt(H))).forecast_age_hours], [20, 1]);
  const gone = (await trip(intelAt(40 * H))).days[0];
  assert.deepEqual([gone.available, gone.wind_kt, gone.comfort, gone.reason], [false, null, 'unknown', 'forecast run is more than 36 hours old or has no run time']);
  // The daily inputs read the same clock.
  assert.equal((await daily(intelAt(H))).conditions.day.comfort, 'comfortable');
  assert.deepEqual((await daily(intelAt(20 * H))).conditions.day, {...(await daily(intelAt(H))).conditions.day, comfort: 'unknown', comfort_held: 'forecast run is 20 h old'});
  assert.deepEqual((await daily(intelAt(40 * H))).conditions, {available: false, advisories: (await daily(intelAt(H))).conditions.advisories, day: null});
});

test('mixed ages: the oldest run governs; a model with an error is missing, not stale', async () => {
  const ages = {gfs_global: H, ecmwf_ifs025: H, ncep_gfswave016: H, ecmwf_wam: 20 * H};
  assert.equal(briefAt(H, {ages}), 'marginal');
  assert.deepEqual(forecastClock(intelAt(H, {ages}), A_NOW), {state: 'held', ageHours: 20});
  assert.equal(await advisorWord(H, {ages}), 'unknown');
  const errored = intelAt(H, {ages, edit: i => { i.forecast.models.ecmwf_wam.error = 'timeout'; }});
  assert.deepEqual(forecastClock(errored, A_NOW), {state: 'fresh', ageHours: 1});
  const day = (await trip(errored)).days[0];
  assert.deepEqual(day, windowConditions(errored, globalThis.REGIONS['morro-bay'], 'central', A_DATE, {start: 6, end: 14}), 'unchanged when fresh');
  assert.deepEqual(forecastClock(intelAt(H, {edit: i => { for (const m of Object.values(i.forecast.models)) m.error = 'down'; }}), A_NOW), {state: 'unusable', ageHours: null});
});

test('missing clock: no meta or a non-finite run time on a model with data is unusable, never fresh', async () => {
  for (const edit of [i => { delete i.forecast.models.gfs_global.meta; }, i => { i.forecast.models.ecmwf_wam.meta.last_run_initialisation_time = NaN; },
    i => { i.forecast.models.ncep_gfswave016.meta.last_run_initialisation_time = '1790618400'; }]) {
    assert.deepEqual(forecastClock(intelAt(H, {edit}), A_NOW), {state: 'unusable', ageHours: null});
    assert.equal(await advisorWord(H, {edit}), 'unavailable');
  }
});

test('cached and out-of-order feeds: completed_at never makes old runs new; the oldest run counts, not the first', async () => {
  assert.deepEqual(forecastClock(intelAt(20 * H, {completed: A_NOW}), A_NOW).state, 'held');
  assert.deepEqual(forecastClock(intelAt(40 * H, {completed: A_NOW}), A_NOW).state, 'unusable');
  assert.deepEqual(forecastClock(intelAt(H, {completed: A_NOW - 30 * H}), A_NOW), {state: 'fresh', ageHours: 1}, 'an old completed_at does not age fresh runs');
  const reversed = intelAt(H, {ages: {gfs_global: 19 * H}, edit: i => { i.forecast.models = Object.fromEntries(Object.entries(i.forecast.models).reverse()); }});
  assert.deepEqual(forecastClock(reversed, A_NOW), {state: 'held', ageHours: 19});
  assert.deepEqual(forecastClock(intelAt(H, {ages: {ecmwf_wam: -2 * H}}), A_NOW).state, 'unusable', 'one run dated ahead');
  assert.equal(feedReaderOldest(forecast(H, {ages: {ecmwf_wam: -2 * H}})), H * 1000, 'the brief reads a run dated ahead as missing, not as the freshest');
});

test('a rough day stays rough or unknown as it ages; never comfortable or bumpy', async () => {
  assert.deepEqual([H, 20 * H, 40 * H].map(age => briefAt(age, {over: ROUGH})), ['rough', 'rough', 'unknown']);
  const words = [];
  for (const age of [H, 20 * H, 40 * H]) words.push(await advisorWord(age, {values: A_ROUGH}));
  assert.deepEqual(words, ['rough', 'rough', 'unavailable']);
});

test('no calm word by another route: held and unusable results carry no "comfortable"; the note is unchanged', async () => {
  const fresh = await trip(intelAt(H));
  for (const age of [20 * H, 40 * H]) {
    const out = await trip(intelAt(age));
    const bare = JSON.stringify({...out, days: out.days.map(({reason, comfort_held, ...d}) => d)});
    assert.doesNotMatch(bare, /comfortable/i, `trip ${age / H} h`);
    assert.equal(out.note, fresh.note, 'note byte-identical');
    const {comfort_held, ...day} = (await daily(intelAt(age))).conditions.day ?? {};
    assert.doesNotMatch(JSON.stringify(day), /comfortable/i, `daily ${age / H} h`);
  }
  assert.ok(!Object.values(COMFORT_WORD).includes('go'));
});

test('two dates in one turn each get their own result; the clock is pure', () => {
  const day = date => Object.freeze({date, window: '06:00-14:00', available: true, wind_kt: [5, 5], wind_from: 'NW', gusts_kt: 7, seas_ft: [2, 2], sea_period_s: 11, swell_ft: [2, 2], swell_period_s: 11, swell_from: 'W', comfort: 'comfortable', comfort_for: 'x', models_agree: true});
  const a = day('2026-09-28'), b = day('2026-09-29');
  const held = withForecastClock(a, {state: 'held', ageHours: 20}), fresh = withForecastClock(b, {state: 'fresh', ageHours: 1});
  assert.deepEqual([held.comfort, held.comfort_held, fresh.comfort, fresh.comfort_held, a.comfort], ['unknown', 'forecast run is 20 h old', 'comfortable', undefined, 'comfortable']);
  const intel = intelAt(20 * H);
  assert.deepEqual(forecastClock(intel, A_NOW), forecastClock(intel, A_NOW));
  assert.deepEqual(forecastClock(intel, A_NOW - 10 * H * 1000), {state: 'fresh', ageHours: 10}, 'nothing cached from the call before');
});

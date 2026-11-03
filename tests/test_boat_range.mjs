// MYB-2: every boat verdict, score and limit sentence is rated for the saved
// boat, the boat is named on screen, and a boat far from the 23 ft reference
// carries the model-limits sentence (web/boat-range.ts). No saved boat rates
// exactly as before. The server advisor rates the reference boat unless the
// request sends valid factors. Synthetic feeds, values invented.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import {BOAT_KEY, boatFactors} from '../dist/boat-handling.js';
import {BOAT_MODEL_NOTE, BOAT_NOTE_RANGE_FT, REFERENCE_BOAT_NAME, boatBasisName, boatRangeNote} from '../web/boat-range.ts';
import {boatVerdict, briefVerdict} from '../web/brief/verdict.ts';
import {rateComfort, REFERENCE_BOAT} from '../web/score.ts';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
const conditions = await import('../server/advisor/answers/conditions.ts');

const TZ = 'America/Los_Angeles', DATE = '2026-10-13';
const NOW = new Date('2026-10-13T12:00:00Z'); // 5 am PDT
const SUNRISE = '2026-10-13T14:10:00Z', SUNSET = '2026-10-14T01:30:00Z';
const START = Date.parse('2026-10-08T07:00:00Z') / 1000;
const TIMES = Array.from({length: 8 * 24}, (_, i) => START + i * 3600);
const UNITS = {wind_speed_10m: 'kn', wind_gusts_10m: 'kn', wind_direction_10m: '°', wave_height: 'ft', wave_period: 's', wind_wave_height: 'ft', wind_wave_period: 's',
  swell_wave_height: 'ft', swell_wave_period: 's', swell_wave_direction: '°', secondary_swell_wave_height: 'ft', secondary_swell_wave_direction: '°'};
const V = {wind_speed_10m: 13, wind_gusts_10m: 17, wind_direction_10m: 315, ecmwf_wind: 13, ecmwf_gust: 17, wave_height: 4, wave_period: 9, wind_wave_height: 1.2, wind_wave_period: 4,
  swell_wave_height: 3.6, swell_wave_period: 10, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200, wam: 4};

/** A parsed ConditionsForecast at one point, every hour the same (as tests/test_brief_verdict.mjs builds it). */
function forecast(now = NOW) {
  const series = keys => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(([k]) => [k, UNITS[k]]))},
    hourly: {time: TIMES, ...Object.fromEntries(keys.map(([k, src]) => [k, TIMES.map(() => V[src ?? k])]))}});
  const run = (id, keys) => ({id, issued: now.getTime() / 1000 - 4 * 3600, end: TIMES.at(-1), data: series(keys)});
  return {region: 'morro-bay', retrieved: NOW.getTime(), point: {id: 'morro-bay', lat: 35.37, lon: -120.9}, models: {
    gfs_global: run('gfs_global', [['wind_speed_10m'], ['wind_gusts_10m'], ['wind_direction_10m']]),
    ncep_gfswave016: run('ncep_gfswave016', ['wave_height', 'wave_period', 'wind_wave_height', 'wind_wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction', 'secondary_swell_wave_height', 'secondary_swell_wave_direction'].map(k => [k])),
    ecmwf_ifs025: run('ecmwf_ifs025', [['wind_speed_10m', 'ecmwf_wind'], ['wind_gusts_10m', 'ecmwf_gust']]),
    ecmwf_wam: run('ecmwf_wam', [['wave_height', 'wam']]),
  }};
}
const brief = () => ({profile: 'boat', date: DATE, sunrise: SUNRISE, sunset: SUNSET, alerts: [], missing: [], bar: null, shore: null, spear: null, kayak: null, tiles: []});
const SKIFF = {name: '', loa_ft: 17, hull: 'flat', layout: 'skiff'};
const CABIN = {name: 'Sea Biscuit', loa_ft: 32, hull: 'deep-v', layout: 'pilothouse'};
const pick = v => [v.verdict, v.limit, v.window, v.score, v.held];

test('the model-limits sentence: none inside 18.4-27.6 ft or with no length, the standing sentence outside, at the exact boundaries', () => {
  assert.deepEqual(BOAT_NOTE_RANGE_FT, {min: 18.4, max: 27.6});
  for (const loa of [18.4, 23, 27.6, null, undefined, NaN, '17', Infinity]) assert.equal(boatRangeNote(loa), null, String(loa));
  for (const loa of [18.3, 27.7, 17, 32, 8, 70]) assert.equal(boatRangeNote(loa), BOAT_MODEL_NOTE, String(loa));
  assert.equal(BOAT_MODEL_NOTE, 'Ratings are a planing-hull rule-of-thumb model tuned on a 23 ft boat, not a sea-keeping calculation.');
});

test('the boat named: the saved name, else "your <n> ft boat", else the reference boat; a name-only boat never throws', () => {
  assert.equal(boatBasisName(null), REFERENCE_BOAT_NAME);
  assert.equal(boatBasisName(undefined), 'the reference 23 ft boat');
  assert.equal(boatBasisName(CABIN), 'Sea Biscuit');
  assert.equal(boatBasisName(SKIFF), 'your 17 ft boat');
  assert.equal(boatBasisName({name: '  ', loa_ft: 18.35}), 'your 18.4 ft boat');
  assert.equal(boatBasisName({name: 'Skiff', loa_ft: null}), 'Skiff');
  assert.equal(boatBasisName({name: '', loa_ft: null}), 'your boat');
  assert.equal(boatBasisName({name: '17 ft boat', loa_ft: 17}), 'your 17 ft boat', 'the first-use automatic name');
  assert.equal(boatRangeNote({name: 'Skiff', loa_ft: null}.loa_ft), null);
});

test('no saved boat: verdict, window, limit and score are the same strings and numbers as before', () => {
  const f = forecast(), before = boatVerdict(brief(), f, NOW, TZ);
  assert.deepEqual(pick(boatVerdict(brief(), f, NOW, TZ, REFERENCE_BOAT)), pick(before));
  assert.deepEqual(pick(boatVerdict(brief(), f, NOW, TZ, boatFactors(null))), pick(before), 'boat-handling with nothing saved is the reference');
  assert.deepEqual(pick(briefVerdict(brief(), f, NOW, TZ)), pick(before));
  assert.equal(before.score, rateComfort({wind: 13, gust: 17, wind_from: 315, sea: 4, sea_period: 9, chop: 1.2, chop_period: 4, swell: 3.6, swell_period: 10, swell_from: 300,
    secondary: 0.5, secondary_from: 200, other_wind: 13, other_gust: 17, other_sea: 4}).score, 'the reference score of the one fixture hour');
});

test('a saved 17 ft skiff and a 32 ft cabin rate the same forecast differently from the reference', () => {
  const f = forecast(), ref = boatVerdict(brief(), f, NOW, TZ);
  const skiff = boatVerdict(brief(), f, NOW, TZ, boatFactors(SKIFF)), cabin = briefVerdict(brief(), f, NOW, TZ, boatFactors(CABIN));
  assert.ok(skiff.score < ref.score && ref.score < cabin.score, `${skiff.score} < ${ref.score} < ${cabin.score}`);
  assert.notEqual(skiff.verdict, ref.verdict);
  assert.notEqual(cabin.verdict, ref.verdict);
  assert.notEqual(skiff.limit, cabin.limit);
  assert.equal(boatRangeNote(SKIFF.loa_ft), BOAT_MODEL_NOTE, 'the 17 ft boat carries the sentence');
  assert.equal(boatRangeNote(23), null, 'a 23 ft boat does not');
});

test('the brief names the saved boat in its basis, rates for it and shows the sentence under the verdict', async () => {
  const store = new Map([[BOAT_KEY, JSON.stringify({schema_version: 1, boat: SKIFF})]]);
  globalThis.localStorage = {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k)};
  const out = join(await mkdtemp(join(tmpdir(), 'boat-range-')), 'brief.mjs'), root = new URL('..', import.meta.url).pathname;
  await build({stdin: {resolveDir: root, loader: 'ts', contents: `
      export * from './web/brief/Brief.tsx';
      export {Brief} from './web/app/Desktop.tsx';
      export {regionInfo} from './web/app/App.tsx';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  const m = await import(pathToFileURL(out).href);
  m.regionInfo.value = {id: 'monterey-point-sur', name: 'Monterey', center: [36.62, -121.9], timezone: TZ};
  m.dailyFeed.value = montereyDaily;
  const now = new Date('2026-10-09T12:00:00Z'); // 5 am PDT, the morning still ahead
  m.regionalForecast.value = {...forecast(now), region: 'monterey-point-sur'};
  try {
    const lead = m.leadBrief(now), skiff = m.currentVerdict(lead, now), ref = briefVerdict(lead, m.regionalForecast.value, now, TZ);
    assert.ok(skiff.score !== null && skiff.score < ref.score, `the lead rates the saved boat: ${skiff.score} < ${ref.score}`);
    assert.deepEqual(pick(skiff), pick(briefVerdict(lead, m.regionalForecast.value, now, TZ, boatFactors(SKIFF))));
    const html = m.render(m.h(m.Verdict, {now}));
    assert.ok(html.includes(`<p class="app-verdict-limit">${skiff.limit}`), 'the skiff limit leads');
    assert.ok(html.includes(` Worst hour: ${skiff.score}/10.`), 'the skiff score is the one shown');
    assert.ok(html.includes('Comfort rating for your 17 ft boat, not a bite forecast or a safety clearance.'), 'the basis names the boat');
    assert.ok(!html.includes('reference 23 ft boat'));
    assert.ok(html.includes(`<p class="app-verdict-boat-note">${BOAT_MODEL_NOTE}</p>`), 'the sentence under the verdict');
    assert.equal(html.split(BOAT_MODEL_NOTE).length - 1, 2, 'and in the basis popover');
    store.set(BOAT_KEY, JSON.stringify({schema_version: 1, boat: {name: 'Sea Biscuit', loa_ft: 23}}));
    const named = m.render(m.h(m.Verdict, {now: NOW}));
    assert.ok(named.includes('Comfort rating for Sea Biscuit, not a bite forecast'));
    assert.ok(!named.includes(BOAT_MODEL_NOTE), 'inside the range only the existing text shows');
    assert.equal(m.comfortBasis(null).slice(0, 72), 'Comfort rating for the reference 23 ft boat, not a bite forecast or a sa');
  } finally { m.regionInfo.value = null; m.dailyFeed.value = null; m.regionalForecast.value = null; delete globalThis.localStorage; }
});

test('no saved boat, then a 17 ft boat saved through the first-use step: the next verdict in the same session rates and names it', async () => {
  const store = new Map();
  globalThis.localStorage = {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k)};
  const out = join(await mkdtemp(join(tmpdir(), 'boat-first-use-')), 'brief.mjs'), root = new URL('..', import.meta.url).pathname;
  await build({stdin: {resolveDir: root, loader: 'ts', contents: `
      export * from './web/brief/Brief.tsx';
      export {regionInfo} from './web/app/App.tsx';
      export {saveFirstUse} from './web/boat-entry.ts';
      export {activeBoatFactors} from './dist/boat-handling.js';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  const m = await import(pathToFileURL(out).href);
  m.regionInfo.value = {id: 'monterey-point-sur', name: 'Monterey', center: [36.62, -121.9], timezone: TZ};
  m.dailyFeed.value = montereyDaily;
  const now = new Date('2026-10-09T12:00:00Z');
  m.regionalForecast.value = {...forecast(now), region: 'monterey-point-sur'};
  try {
    const lead = m.leadBrief(now), ref = briefVerdict(lead, m.regionalForecast.value, now, TZ);
    assert.deepEqual(pick(m.currentVerdict(lead, now)), pick(ref), 'nothing saved: the reference boat');
    const before = m.render(m.h(m.Verdict, {now}));
    assert.ok(before.includes('Comfort rating for the reference 23 ft boat'));
    assert.ok(before.includes(` Worst hour: ${ref.score}/10.`));
    assert.deepEqual(m.activeBoatFactors(), boatFactors(null));
    assert.equal(m.saveFirstUse({lengthFt: '17', profile: 'boat'}, globalThis.localStorage).boat, true);
    const want = briefVerdict(lead, m.regionalForecast.value, now, TZ, boatFactors({loa_ft: 17})), after = m.currentVerdict(lead, now);
    assert.ok(want.score < ref.score, `${want.score} < ${ref.score}`);
    assert.deepEqual(pick(after), pick(want), 'the saved 17 ft boat is rated, not the cached reference');
    assert.deepEqual(m.activeBoatFactors(), boatFactors({loa_ft: 17}), 'every activeBoatFactors caller sees the new boat');
    const html = m.render(m.h(m.Verdict, {now}));
    assert.ok(html.includes('Comfort rating for your 17 ft boat, not a bite forecast'), 'the basis names the saved boat');
    assert.ok(html.includes(` Worst hour: ${want.score}/10.`), 'and the score shown is the 17 ft one');
    assert.ok(html.includes(`<p class="app-verdict-limit">${want.limit}`));
    store.delete(BOAT_KEY);
    assert.deepEqual(pick(m.currentVerdict(lead, now)), pick(ref), 'cleared: back to the reference');
  } finally { m.regionInfo.value = null; m.dailyFeed.value = null; m.regionalForecast.value = null; delete globalThis.localStorage; }
});

test('server rateHour: no boat is the reference score; valid factors scale it; bad factors are clamped or rejected', () => {
  const intel = read('./fixtures/feeds/intelligence.json'), region = REGIONS['morro-bay'];
  const point = region.forecast_points.findIndex(p => p.id === 'central');
  const h = conditions.readHour(intel, point, intel.forecast.models.gfs_global.data[point].hourly.time[0]);
  assert.equal(conditions.rateHour(h), rateComfort(h).score);
  assert.equal(conditions.rateHour(h, REFERENCE_BOAT), conditions.rateHour(h));
  const big = conditions.requestBoat(boatFactors(CABIN));
  assert.ok(conditions.rateHour(h, big) > conditions.rateHour(h), 'a bigger boat scores the same hour higher');
  assert.deepEqual(conditions.requestBoat({sea: 9, wind: 0.1, chopPeriod: 5}), {sea: 2.6, wind: 0.6, chopPeriod: 5}, 'clamped like boatFactors');
  for (const bad of [null, undefined, 'boat', {}, {sea: NaN, wind: 1, chopPeriod: 6}, {sea: 1, wind: Infinity, chopPeriod: 6}, {sea: '1', wind: 1, chopPeriod: 6},
    {sea: 1, wind: 1, chopPeriod: 0}, {sea: 1, wind: 1, chopPeriod: -3}, {sea: 1, wind: 1}]) assert.equal(conditions.requestBoat(bad), null, JSON.stringify(bad));
  const ref = conditions.windowConditions(intel, region, 'central', '2026-09-28', {start: 17, end: 19});
  assert.equal(ref.comfort_for, 'a mid-size center console');
  assert.equal(conditions.windowConditions(intel, region, 'central', '2026-09-28', {start: 17, end: 19}, null).comfort, ref.comfort);
  const own = conditions.windowConditions(intel, region, 'central', '2026-09-28', {start: 17, end: 19}, big);
  assert.equal(own.comfort_for, 'your boat');
});

test('the no-boat trip-dialog wording is unchanged', async () => {
  const src = await readFile(new URL('../web/app/TripAlerts.tsx', import.meta.url), 'utf8');
  assert.ok(src.includes("'Limits start from the reference 23 ft boat. Set your boat to tailor them.'"));
});

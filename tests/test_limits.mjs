// Issue #542: your own comfort limits per profile. The model and clamping
// (packages/coast/src/limits.ts), the brief's windows and verdicts using them
// (daily.ts buildDaily, web/brief/model.ts), hazard rules that no limit can
// relax, the device storage with its failure fallback (web/limits.ts), and the
// panel (web/app/LimitsPanel.tsx) rendered to a string.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import fixture from './fixtures/coast/skippercast-report.json' with {type: 'json'};

const {LIMIT_BOUNDS, clampLimits, defaultLimits, sameLimits, stricterFields, looserFields, limitsText} = await import('../packages/coast/src/limits.ts');
const {WINDOW_LIMITS} = await import('../packages/coast/src/assessment.ts');
const {SPEAR} = await import('../packages/coast/src/spear.ts');
const {buildDaily} = await import('../packages/coast/src/daily.ts');
const {crossingHours} = await import('../packages/coast/src/bar-conditions.ts');
const {slo} = await import('../packages/coast/src/counties.ts');
const {buildCoastBrief} = await import('../web/brief/model.ts');
const {configureStore, STORAGE_KEYS} = await import('../web/state.ts');
const limitsStore = await import('../web/limits.ts');

const HOUR = 3_600_000;
const ROOT = new URL('..', import.meta.url).pathname;
const now = new Date(Date.parse(fixture.generatedAt) + 10 * 60_000);
const date = '2026-10-09';
const area = slo.areas.find(a => a.id === 'central');
const start = Date.parse(fixture.forecasts[1].hours[0].at);
const iso = ms => new Date(ms).toISOString();

/** The fixture report with steady conditions (a north, cross-shore breeze at Morro Bay) and an optional nearshore site. */
function report({site = false, wave = 2, period = 10, nearFt = 2, nearS = 10, wind = 5, gust = 8, dir = 0, alerts = []} = {}) {
  const hours = Array.from({length: 48}, (_, i) => ({at: iso(start + i * HOUR), windKnots: wind, gustKnots: gust, windDirectionDeg: dir, waveFt: wave, wavePeriodS: period, swellFt: Math.max(0, wave - 0.5), swellPeriodS: period, airTempF: 60, precipPct: 0}));
  const out = structuredClone(fixture);
  out.alerts = alerts;
  out.forecasts = out.forecasts.map(f => f.id === 'central' ? {...f, hours} : f);
  if (site) out.nearshore = [{id: 'mop-test', name: 'Morro Strand', areaId: 'central', lat: 35.4, lon: -120.87, sourceId: 'cdip', issuedAt: iso(now.getTime() - 2 * HOUR), fetchedAt: iso(now.getTime() - 20 * 60_000),
    hours: Array.from({length: 16}, (_, i) => ({at: iso(start - 3 * HOUR + i * 3 * HOUR), waveFt: nearFt, periodS: nearS, directionDeg: 280, qualityFlag: null, secondaryFlag: null})),
    url: 'https://cdip.ucsd.edu', kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 180, waterDepthM: 15, depthDatum: 'MSL', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: iso(start + 42 * HOUR)}];
  return out;
}
const loosest = mode => Object.fromEntries(Object.entries(LIMIT_BOUNDS[mode]).map(([k, b]) => [k, b.max]));

test('defaults are the brief\'s own window limits; spear adds the surge band', () => {
  assert.deepEqual(defaultLimits('boat'), {wind: WINDOW_LIMITS.boat.wind, gust: WINDOW_LIMITS.boat.gust, seas: WINDOW_LIMITS.boat.wave});
  for (const mode of ['shore', 'kayak']) assert.deepEqual(defaultLimits(mode), {wind: 8, gust: 12, seas: 3});
  assert.deepEqual(defaultLimits('spear'), {wind: 8, gust: 12, seas: 3, surge: SPEAR.windowMaxSurge});
  // Every default sits inside its bounds, and kayak seas can only be tightened.
  for (const mode of ['boat', 'shore', 'spear', 'kayak']) for (const [field, b] of Object.entries(LIMIT_BOUNDS[mode])) {
    const value = defaultLimits(mode)[field];
    assert.ok(value >= b.min && value <= b.max, `${mode} ${field}`);
  }
  assert.equal(LIMIT_BOUNDS.kayak.seas.max, defaultLimits('kayak').seas);
});

test('clamping: bounds, step, unreadable values, and Heavy surge never allowed', () => {
  assert.deepEqual(clampLimits('boat', {wind: 99, gust: -3, seas: 4.3}), {wind: 20, gust: 6, seas: 4.5});
  assert.deepEqual(clampLimits('boat', {wind: 'x', gust: null, seas: NaN}), defaultLimits('boat'));
  assert.deepEqual(clampLimits('boat', {wind: '12'}), {...defaultLimits('boat'), wind: 12}, 'a form string reads as a number');
  assert.deepEqual(clampLimits('shore', null), defaultLimits('shore'));
  assert.equal(clampLimits('spear', {surge: 'Heavy'}).surge, 'Moderate', 'Heavy surge falls back to the default');
  assert.equal(clampLimits('spear', {surge: 'Strong'}).surge, 'Strong');
  assert.equal(clampLimits('boat', {surge: 'Strong'}).surge, undefined, 'surge is spear only');
  assert.equal(clampLimits('kayak', {seas: 6}).seas, 3, 'kayak seas cannot be loosened');
  assert.ok(sameLimits('boat', clampLimits('boat', {}), defaultLimits('boat')));
  assert.deepEqual(stricterFields('spear', {wind: 6, gust: 12, seas: 4, surge: 'Low'}), {fields: ['wind'], surge: true});
  assert.deepEqual(looserFields('spear', {wind: 6, gust: 12, seas: 4, surge: 'Low'}), {fields: ['seas'], surge: false});
  assert.equal(limitsText('shore', defaultLimits('shore')), 'wind 8 kt, gusts 12 kt, surf 3 ft');
  assert.equal(limitsText('spear', defaultLimits('spear')), 'wind 8 kt, gusts 12 kt, seas 3 ft, surge moderate');
});

test('without limits, and with limits equal to the defaults, the brief is unchanged', () => {
  for (const mode of ['boat', 'shore', 'spear', 'kayak']) {
    const plain = buildDaily(report(), slo, area, mode, date, now);
    const same = buildDaily(report(), slo, area, mode, date, now, defaultLimits(mode));
    assert.deepEqual(same, plain, mode);
    assert.deepEqual(plain.limits, {values: defaultLimits(mode), custom: false, loosened: false, text: null});
  }
});

test('a looser limit opens a window the defaults would not, and says "using your limits"', () => {
  const windy = report({wind: 12, gust: 17});
  const base = buildDaily(windy, slo, area, 'boat', date, now);
  assert.deepEqual(base.windows, [], '12 kt is over the 10 kt default');
  const mine = buildDaily(windy, slo, area, 'boat', date, now, {wind: 14, gust: 20});
  assert.ok(mine.windows.length > 0);
  assert.match(mine.windows[0].reasons[0], /^Using your limits \(wind 14 kt, gusts 20 kt, seas 4 ft\)/);
  assert.equal(mine.limits.custom, true);
  assert.equal(mine.limits.loosened, true);
  assert.match(mine.summary, /Using your limits: wind 14 kt, gusts 20 kt, seas 4 ft, looser than the defaults \(wind 10 kt, gusts 15 kt, seas 4 ft\)\./);
  assert.equal(mine.status, 'Mixed');
  assert.equal(base.status, 'Caution');
});

test('a stricter limit removes windows, counts the hours it left out, and caps Calmer hours at Marginal', () => {
  const base = buildDaily(report(), slo, area, 'boat', date, now);
  assert.ok(base.windows.length > 0);
  const strict = buildDaily(report(), slo, area, 'boat', date, now, {wind: 4});
  assert.deepEqual(strict.windows, []);
  assert.equal(strict.limits.loosened, false);
  assert.match(strict.limits.text, /^Using your limits: wind 4 kt, gusts 15 kt, seas 4 ft\. Your limits leave out \d+ hours the default limits would suggest\.$/);
  assert.ok(strict.summary.includes(strict.limits.text));
  // Shore: a Calmer hour over the user's wind limit reads Marginal and names the limit.
  const shore = buildDaily(report(), slo, area, 'shore', date, now);
  const calmer = shore.shore.hours.find(h => h.verdict === 'Calmer');
  assert.ok(calmer, 'the fixture has a Calmer shore hour');
  const capped = buildDaily(report(), slo, area, 'shore', date, now, {wind: 4}).shore.hours.find(h => h.at === calmer.at);
  assert.equal(capped.verdict, 'Marginal');
  assert.ok(capped.reasons.includes('wind over your 4 kt (your limits)'));
  // A looser limit never lifts an hour's verdict.
  const loose = buildDaily(report({wind: 12, gust: 17}), slo, area, 'shore', date, now, loosest('shore'));
  const strictShore = buildDaily(report({wind: 12, gust: 17}), slo, area, 'shore', date, now);
  assert.deepEqual(loose.shore.hours.map(h => h.verdict), strictShore.shore.hours.map(h => h.verdict));
});

test('spear: a stricter surge band blocks nearshore windows; Heavy is never reachable', () => {
  // 2 ft at 10 s nearshore is 40 ft²·s, Moderate surge: inside the default, over a Low limit.
  const base = buildDaily(report({site: true, nearFt: 2, nearS: 10}), slo, area, 'spear', date, now);
  assert.ok(base.windows.length > 0);
  const low = buildDaily(report({site: true, nearFt: 2, nearS: 10}), slo, area, 'spear', date, now, {surge: 'Low'});
  assert.deepEqual(low.windows, []);
  const heavy = buildDaily(report({site: true, nearFt: 5, nearS: 16}), slo, area, 'spear', date, now, {...loosest('spear'), surge: 'Heavy'});
  assert.deepEqual(heavy.windows, [], 'Heavy surge stays out whatever the limit says');
});

test('hazard rules are never relaxed by the loosest limits', () => {
  const alert = {id: 'sca', event: 'Small Craft Advisory', headline: 'Small Craft Advisory in effect', description: '', effective: null, expires: null, url: 'https://weather.gov'};
  for (const mode of ['boat', 'shore', 'spear', 'kayak']) {
    const alerted = buildDaily(report({alerts: [alert]}), slo, area, mode, date, now, loosest(mode));
    assert.deepEqual(alerted.windows, [], `${mode}: an alert withholds windows`);
    assert.equal(alerted.status, 'Caution');
  }
  // Long-period swell (2.5 ft or more at 15 s or longer) stays out of a boat window with seas up to 8 ft allowed.
  assert.deepEqual(buildDaily(report({wave: 3, period: 16}), slo, area, 'boat', date, now, loosest('boat')).windows, []);
  // Shore sneaker-wave caution from the nearshore model.
  const sneaker = buildDaily(report({site: true, nearFt: 2, nearS: 18}), slo, area, 'shore', date, now, loosest('shore'));
  assert.deepEqual(sneaker.windows, []);
  assert.equal(sneaker.status, 'Caution');
  // Kayak offshore wind (from 80° at Morro Bay) with the wind limit loosened.
  const offshore = buildDaily(report({dir: 80}), slo, area, 'kayak', date, now, loosest('kayak'));
  assert.deepEqual(offshore.windows, []);
  assert.equal(offshore.status, 'Caution');
  // A hazardous bar hour: no window leaves or returns then.
  const bar = buildDaily(report({site: true, nearFt: 4, wave: 3, dir: 300}), slo, area, 'boat', date, now, loosest('boat'));
  assert.ok(bar.bar.hazardous.length > 0);
  for (const window of bar.windows) assert.ok(!crossingHours(bar.bar, window.start, window.end).some(h => h.band === 'Hazardous'), window.start);
  assert.equal(bar.status, 'Caution');
});

test('the brief model passes the limits through', () => {
  const windy = report({wind: 12, gust: 17});
  const brief = buildCoastBrief({report: windy, county: slo, areaId: 'central', profile: 'boat', date, now, limits: {wind: 14, gust: 20}});
  assert.equal(brief.limits.custom, true);
  assert.ok(brief.windows.length > 0);
  assert.match(brief.deck, /Using your limits/);
  assert.equal(buildCoastBrief({report: windy, county: slo, areaId: 'central', profile: 'boat', date, now}).limits.custom, false);
});

const memory = () => {const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), map: m};};

test('storage: saved per profile, clamped, equal-to-default clears, reset, and bad JSON reads as none', () => {
  const store = memory();
  configureStore({storage: store});
  limitsStore.loadLimits();
  assert.deepEqual(limitsStore.savedLimits.value, {});
  assert.deepEqual(limitsStore.saveLimits('boat', {wind: 50, gust: 18, seas: 4}), {wind: 20, gust: 18, seas: 4});
  assert.deepEqual(JSON.parse(store.map.get(STORAGE_KEYS.limits)), {boat: {wind: 20, gust: 18, seas: 4}});
  assert.equal(limitsStore.hasOwnLimits('boat'), true);
  assert.equal(limitsStore.hasOwnLimits('shore'), false);
  assert.deepEqual(limitsStore.limitsFor('shore'), defaultLimits('shore'));
  limitsStore.savedLimits.value = {};
  assert.deepEqual(limitsStore.loadLimits(), {boat: {wind: 20, gust: 18, seas: 4}}, 'reloads from storage');
  limitsStore.saveLimits('boat', defaultLimits('boat'));
  assert.equal(limitsStore.hasOwnLimits('boat'), false, 'saving the defaults clears the entry');
  limitsStore.saveLimits('spear', {wind: 6, gust: 10, seas: 2, surge: 'Low'});
  limitsStore.resetLimits('spear');
  assert.deepEqual(limitsStore.savedLimits.value, {});
  assert.deepEqual(limitsStore.parseLimits('{not json'), {});
  assert.deepEqual(limitsStore.parseLimits('[1,2]'), {});
  assert.deepEqual(limitsStore.parseLimits(JSON.stringify({boat: {wind: 99}, dinghy: {wind: 3}, shore: 'x'})), {boat: {wind: 20, gust: 15, seas: 4}});
  configureStore({storage: null});
});

test('storage failure: limits still hold for the page, and a fresh load starts from the defaults', () => {
  const broken = {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('quota'); }};
  configureStore({storage: broken});
  assert.deepEqual(limitsStore.loadLimits(), {});
  assert.doesNotThrow(() => limitsStore.saveLimits('kayak', {wind: 6}));
  assert.equal(limitsStore.limitsFor('kayak').wind, 6, 'kept in memory');
  assert.doesNotThrow(() => limitsStore.resetLimits('kayak'));
  limitsStore.saveLimits('kayak', {wind: 6});
  assert.deepEqual(limitsStore.loadLimits(), {}, 'nothing was stored');
  configureStore({storage: null});
});
// Re-recorded for #551: default windows lost only hours a hazard rule flags (a hazardous bar mid-window, offshore-estimate
// sneaker swell for shore, long-period swell under a kayak, Rough shore or spear hours) and the short pieces those split off.
const DEFAULT_DIGEST = '5e76d4c141f11c062b2dccef887b2691b493d2dd001687de5f946c44bd3c9f32';

/** report() with hour-to-hour variation, so a day mixes Rough and gentler hours. */
function varied(opts) {
  const out = report(opts);
  const f = out.forecasts.find(x => x.id === 'central');
  f.hours = f.hours.map((h, i) => ({...h, windKnots: h.windKnots + (i % 5), gustKnots: h.gustKnots + (i % 7), waveFt: h.waveFt + (i % 3) * 0.5}));
  if (out.nearshore) out.nearshore[0].hours = out.nearshore[0].hours.map((h, i) => ({...h, waveFt: h.waveFt + (i % 3)}));
  return out;
}
const GRID = [];
for (const site of [false, true]) for (const [wind, gust] of [[2, 5], [6, 10], [10, 16], [14, 22]]) for (const wave of [1, 3, 5]) for (const period of [8, 16])
  GRID.push({site, wind, gust, wave, period, dir: 0, nearFt: wave, nearS: period});
const windowHours = (brief, profileHours) => brief.windows.flatMap(w => profileHours.filter(h => Date.parse(h.at) >= Date.parse(w.start) && Date.parse(h.at) < Date.parse(w.end)));

test('default-limit windows match the recorded digest', () => {
  // A digest of every default window over a grid of shore, spear, kayak and boat days. A change here moves the
  // defaults: re-record it only on purpose, and say in the commit which hours moved and why.
  const rows = [];
  for (const mode of ['boat', 'shore', 'spear', 'kayak']) for (const opts of GRID) {
    const brief = buildDaily(varied(opts), slo, area, mode, date, now);
    rows.push([mode, brief.status, brief.windows.map(w => [w.start, w.end, w.label, w.reasons])]);
  }
  assert.ok(rows.some(row => row[2].length), 'the grid has default windows');
  assert.equal(createHash('sha256').update(JSON.stringify(rows)).digest('hex'), DEFAULT_DIGEST);
});

test('looser limits never put a shore or spear window over an hour that profile grades Rough', () => {
  let rough = 0, windows = 0;
  for (const [mode, limits] of [['shore', loosest('shore')], ['shore', {wind: 15, gust: 20}], ['spear', loosest('spear')], ['spear', {...loosest('spear'), surge: 'Strong'}], ['spear', {wind: 14, gust: 20}]]) for (const opts of GRID) {
    const brief = buildDaily(varied(opts), slo, area, mode, date, now, limits);
    const hours = brief[mode].hours;
    rough += hours.filter(h => h.verdict === 'Rough').length;
    windows += brief.windows.length;
    for (const h of windowHours(brief, hours)) assert.notEqual(h.verdict, 'Rough', `${mode} ${JSON.stringify(limits)} ${JSON.stringify(opts)} ${h.at}: ${h.reasons.join(', ')}`);
  }
  assert.ok(rough > 0 && windows > 0, 'the grid has Rough hours and windows');
  // The reported case: Shore at wind 15, gusts 20 with surf from the offshore estimate.
  const shore = buildDaily(varied({wind: 10, gust: 14, wave: 3, period: 16, dir: 0}), slo, area, 'shore', date, now, {wind: 15, gust: 20});
  for (const h of windowHours(shore, shore.shore.hours)) assert.notEqual(h.verdict, 'Rough', h.at);
});

test("a stricter kayak seas limit is checked against the kayak verdict's own seas figure", () => {
  const day = buildDaily(report({wave: 2}), slo, area, 'kayak', date, now);
  assert.ok(day.windows.length > 0);
  const seas = day.kayak.hours.find(h => h.seas.heightFt !== null)?.seas.heightFt;
  assert.ok(Number.isFinite(seas), 'the kayak profile grades a seas figure');
  const under = buildDaily(report({wave: 2}), slo, area, 'kayak', date, now, {seas: Math.ceil(seas * 2) / 2});
  assert.ok(under.windows.length > 0, 'a limit at the kayak seas figure keeps the windows');
  const over = buildDaily(report({wave: 2}), slo, area, 'kayak', date, now, {seas: Math.floor(seas * 2) / 2 - 0.5});
  assert.deepEqual(over.windows, [], 'a limit under the kayak seas figure removes them');
});

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'limits-')), 'limits.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {LimitsForm, LimitsControl, fieldLabel} from './web/app/LimitsPanel.tsx';
      export {saveLimits, resetLimits} from './web/limits.ts';
      export {LowerExposure} from './web/brief/Brief.tsx';
      export {configureStore, profile} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

test('panel: labelled number fields with default and range, surge for spear only, Save and Reset to defaults', async () => {
  const {LimitsForm, LimitsControl, render, h, configureStore: configure, saveLimits, resetLimits, profile} = await load();
  configure({storage: null});
  const boat = render(h(LimitsForm, {profile: 'boat'}));
  for (const field of ['wind', 'gust', 'seas']) {
    const id = boat.match(new RegExp(`<input id="([^"]+-${field})"`))?.[1];
    assert.ok(id, field);
    assert.ok(boat.includes(`<label for="${id}">`), `${field} has a label`);
    assert.ok(boat.includes(`aria-describedby="${id}-hint"`));
  }
  assert.match(boat, /Highest sustained wind/);
  assert.match(boat, /Highest seas/);
  assert.match(boat, /Default 10 · 4–20/);
  assert.match(boat, /min="4" max="20" step="1"/);
  assert.match(boat, /Boat uses the default limits\./);
  assert.ok(!boat.includes('Highest surge'));
  assert.match(boat, /<button[^>]*type="submit"[^>]*>Save<\/button>/);
  assert.match(boat, />Reset to defaults<\/button>/);
  assert.match(render(h(LimitsForm, {profile: 'shore'})), /Highest surf/);
  const spear = render(h(LimitsForm, {profile: 'spear'}));
  assert.match(spear, /Highest surge/);
  assert.ok(!spear.includes('>Heavy<'), 'Heavy is not offered');
  saveLimits('spear', {wind: 6});
  assert.match(render(h(LimitsForm, {profile: 'spear'})), /Spear uses your limits\./);
  assert.match(render(h(LimitsForm, {profile: 'spear'})), /value="6"/);
  resetLimits('spear');
  // The trigger names the active profile and says when its limits are set.
  profile.value = 'kayak';
  const desktop = render(h(LimitsControl, {}));
  assert.match(desktop, /aria-haspopup="dialog"/);
  assert.match(desktop, /title="Your limits for Kayak"/);
  assert.match(desktop, /Your limits<\/button>/);
  assert.match(render(h(LimitsControl, {compact: true})), /aria-label="Your limits for Kayak"/);
  saveLimits('kayak', {wind: 6});
  assert.match(render(h(LimitsControl, {compact: true})), /Your limits for Kayak \(set\)/);
  resetLimits('kayak');
  profile.value = 'boat';
});

test('Lower exposure keeps the safety caveat visible beside the "using your limits" note', async () => {
  const {LowerExposure, render, h} = await load();
  const windy = report({wind: 12, gust: 17});
  const mine = buildCoastBrief({report: windy, county: slo, areaId: 'central', profile: 'boat', date, now, limits: {wind: 14, gust: 20}});
  assert.match(mine.windows[0].reasons[0], /^Using your limits/);
  const html = render(h(LowerExposure, {brief: mine}));
  assert.match(html, /Harbor entrance and full return route need a separate check\. Using your limits \(wind 14 kt/);
  const plain = buildCoastBrief({report: report(), county: slo, areaId: 'central', profile: 'boat', date, now});
  const text = render(h(LowerExposure, {brief: plain}));
  assert.match(text, /Harbor entrance and full return route need a separate check/);
  assert.ok(!text.includes('Using your limits'));
});

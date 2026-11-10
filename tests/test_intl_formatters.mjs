// SC1407-04 (#1762 R2): the shared bounded formatter cache (packages/coast/src/date-format.ts) and the nine hot
// sites that read it (daily.ts dateKey, offsetMinutes, dayInfo, hourText, clockText and the spear sentence;
// verdict.ts local(); RulesCard.tsx RulesLine; PlanView.tsx targetRules). Synthetic and offline.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {isDeepStrictEqual} from 'node:util';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname, HELPER = join(ROOT, 'packages/coast/src/date-format.ts');
const ZONES = ['UTC', 'America/Los_Angeles'];
// Ordinary, UTC and Pacific midnights, a UTC/Pacific calendar disagreement, the 2026 spring change (1:59:59 am
// PST, then 3 am PDT) and the 2026 fall change (1 am and 1:30 am PDT, then the repeated 1 am and 1:30 am PST).
const INSTANTS = ['2026-06-15T19:00:00Z', '2026-01-01T00:00:00Z', '2026-07-04T07:00:00Z', '2026-03-08T07:30:00Z',
  '2026-03-08T09:00:00Z', '2026-03-08T09:59:59Z', '2026-03-08T10:00:00Z', '2026-03-08T11:00:00Z',
  '2026-11-01T08:00:00Z', '2026-11-01T08:30:00Z', '2026-11-01T09:00:00Z', '2026-11-01T09:30:00Z', '2026-11-01T10:00:00Z'].map(s => new Date(s));
// The nine sites' patterns as main constructed them before this change (timeZone aside), pinned here independently.
const ORIGINAL = {
  'daily dateKey': ['en-US', {year: 'numeric', month: '2-digit', day: '2-digit'}],
  'daily offsetMinutes': ['en-US', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'}],
  'daily dayInfo weekday': ['en-US', {weekday: 'long'}],
  'daily hourText': ['en-US', {hour: 'numeric'}],
  'daily clockText': ['en-US', {hour: 'numeric', minute: '2-digit'}],
  'daily spear best hour': ['en-US', {hour: 'numeric'}],
  'verdict local': ['en-CA', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23'}],
  'RulesCard day': ['en-CA', {year: 'numeric', month: '2-digit', day: '2-digit'}],
  'PlanView date': ['en-CA', {year: 'numeric', month: '2-digit', day: '2-digit'}],
};
const sorted = options => Object.fromEntries(Object.entries(options).sort(([a], [b]) => a < b ? -1 : 1));
const original = (locale, options) => Object.values(ORIGINAL).some(([l, o]) => l === locale && isDeepStrictEqual(sorted(o), sorted(options)));

let fresh = 0;
/** An isolated helper instance: its own cache, untouched by other tests or bundles. */
const helper = async () => (await import(`${pathToFileURL(HELPER).href}?instance=${++fresh}`)).dateTimeFormat;
const Native = Intl.DateTimeFormat;
/** Counts native constructions (including refused ones) until the returned restore() runs. */
function spy() {
  const calls = [];
  Intl.DateTimeFormat = class extends Native { constructor(locale, options) { calls.push([locale, {...options}]); super(locale, options); } };
  return {calls, restore: () => { Intl.DateTimeFormat = Native; }};
}
const same = (cached, locale, tz, options, at) => {
  const native = new Native(locale, {...options, timeZone: tz});
  assert.equal(cached.format(at), native.format(at), `${locale} ${tz} ${JSON.stringify(options)} ${at.toISOString()}`);
  assert.ok(isDeepStrictEqual(cached.formatToParts(at), native.formatToParts(at)), `parts ${locale} ${tz} ${at.toISOString()}`);
};

test('formatter_same_tuple_reuses_and_constructs_once', async () => {
  const dateTimeFormat = await helper(), s = spy();
  try {
    const options = Object.freeze({year: 'numeric', month: '2-digit', day: '2-digit'}), before = JSON.stringify(options);
    const first = dateTimeFormat('en-US', 'UTC', options);
    for (const again of [{year: 'numeric', month: '2-digit', day: '2-digit'}, {day: '2-digit', year: 'numeric', month: '2-digit'}, {month: '2-digit', day: '2-digit', year: 'numeric', hour: undefined}]) assert.equal(dateTimeFormat('en-US', 'UTC', again), first);
    assert.equal(s.calls.length, 1, 'one construction for one tuple');
    assert.equal(JSON.stringify(options), before, 'caller options untouched');
    for (const at of INSTANTS) same(first, 'en-US', 'UTC', options, at);
  } finally { s.restore(); }
});

test('formatter_zone_locale_and_pattern_are_distinct', async () => {
  const dateTimeFormat = await helper();
  const patterns = [['en-US', {hour: 'numeric'}], ['en-CA', {hour: 'numeric'}], ['en-US', {hour: '2-digit'}], ['en-US', {hour: 'numeric', minute: '2-digit'}],
    ['en-US', {hour: 'numeric', hourCycle: 'h23'}], ['en-US', {hour: 'numeric', hour12: false}], ['en-US', {weekday: 'long'}], ...Object.values(ORIGINAL)];
  const seen = new Map();
  for (const tz of ZONES) for (const [locale, options] of patterns) {
    const f = dateTimeFormat(locale, tz, options), key = JSON.stringify([locale, tz, sorted(options)]);
    if (seen.has(key)) assert.equal(seen.get(key), f, `${key} reuses`); else seen.set(key, f);
    for (const at of INSTANTS) same(f, locale, tz, options, at);
  }
  assert.equal(new Set(seen.values()).size, seen.size, 'no two distinct tuples share a formatter');
  const day = tz => dateTimeFormat('en-CA', tz, ORIGINAL['PlanView date'][1]).format(new Date('2026-03-08T07:30:00Z'));
  assert.deepEqual([day('UTC'), day('America/Los_Angeles')], ['2026-03-08', '2026-03-07'], 'two zones never share a calendar day');
  const hour = at => dateTimeFormat('en-US', 'America/Los_Angeles', {hour: 'numeric', minute: '2-digit'}).format(new Date(at));
  assert.deepEqual(['2026-11-01T08:30:00Z', '2026-11-01T09:30:00Z', '2026-03-08T09:59:59Z', '2026-03-08T10:00:00Z'].map(hour), ['1:30 AM', '1:30 AM', '1:59 AM', '3:00 AM']);
});

test('formatter_64_entry_fifo_cap', async () => {
  const dateTimeFormat = await helper(), zones = Intl.supportedValuesOf('timeZone').slice(0, 300), s = spy();
  try {
    const get = i => dateTimeFormat('en-US', zones[i], {hour: 'numeric'});
    const kept = Array.from({length: 64}, (_, i) => get(i));
    assert.equal(s.calls.length, 64);
    assert.equal(get(0), kept[0], 'a hit while full');
    assert.equal(s.calls.length, 64, 'hits construct nothing');
    get(64);
    assert.equal(s.calls.length, 65);
    for (let i = 1; i <= 64; i++) assert.ok(get(i) === (kept[i] ?? get(i)), `entry ${i} retained`);
    assert.equal(s.calls.length, 65, 'the 64 newest are retained');
    const first = get(0);
    assert.notEqual(first, kept[0], 'the oldest was dropped although it was the last hit (FIFO, hits do not reorder)');
    assert.equal(s.calls.length, 66);
    for (let i = 65; i < 300; i++) get(i);
    const calls = s.calls.length;
    for (let i = 236; i < 300; i++) get(i);
    assert.equal(s.calls.length, calls, 'after churn the newest 64 still hit');
    get(235);
    assert.equal(s.calls.length, calls + 1, 'the 65th newest is gone, so at most 64 are kept');
  } finally { s.restore(); }
});

test('formatter_native_refusals_do_not_poison_or_evict', async () => {
  const dateTimeFormat = await helper(), zones = Intl.supportedValuesOf('timeZone').slice(0, 64), s = spy();
  try {
    const kept = zones.map(tz => dateTimeFormat('en-US', tz, {hour: 'numeric'}));
    const refusal = (locale, tz) => { try { new Native(locale, {timeZone: tz, hour: 'numeric'}); } catch (error) { return error; } assert.fail('native accepted'); };
    for (const [locale, tz] of [['en-US', 'Not/AZone'], ['en-US', ''], ['!!', 'UTC']]) {
      const expected = refusal(locale, tz);
      for (let i = 0; i < 3; i++) assert.throws(() => dateTimeFormat(locale, tz, {hour: 'numeric'}), {name: 'RangeError', message: expected.message});
    }
    const before = s.calls.length;
    zones.forEach((tz, i) => assert.equal(dateTimeFormat('en-US', tz, {hour: 'numeric'}), kept[i], `${tz} not evicted`));
    assert.equal(s.calls.length, before, 'refusals neither cached nor evicted anything');
    same(dateTimeFormat('en-US', 'America/Los_Angeles', {weekday: 'long'}), 'en-US', 'America/Los_Angeles', {weekday: 'long'}, INSTANTS[9]);
  } finally { s.restore(); }
});

test('formatter_verdict_source_guard_is_narrow', () => {
  // tests/test_brief_agreement.mjs puts exactly this import and expression back to the old bytes before its digest,
  // so a changed locale or option at local() no longer matches and breaks that pin.
  const source = readFileSync(join(ROOT, 'web/brief/verdict.ts'), 'utf8'), [locale, options] = ORIGINAL['verdict local'];
  const literal = `{${Object.entries(options).map(([k, v]) => `${k}: '${v}'`).join(', ')}}`;
  assert.equal(source.split(`dateTimeFormat('${locale}', tz, ${literal})`).length, 2);
  assert.equal(source.split('dateTimeFormat(').length, 2, 'one helper call in verdict.ts');
  assert.equal(source.split("import {dateTimeFormat} from '../../packages/coast/src/date-format.ts';\n").length, 2);
  assert.doesNotMatch(source, /Intl\.DateTimeFormat/);
});

// The real sites, bundled twice: once with the cache, once with an uncached adapter that only accepts the
// pinned original patterns. Both record every helper request so the sites' locale/options are checked too.
const ENTRY = `
  export {availableDays, buildDaily, dateKey} from './packages/coast/src/daily.ts';
  export {slo} from './packages/coast/src/counties.ts';
  export {windowHours} from './web/brief/verdict.ts';
  export {targetRules} from './web/app/PlanView.tsx';
  export {RulesLine} from './web/app/RulesCard.tsx';
  export {regionInfo} from './web/app/App.tsx';
  export {markData} from './web/map/marks.ts';
  export {regsData} from './web/regs.ts';
  export * as state from './web/state.ts';
  export {render} from 'preact-render-to-string'; export {h} from 'preact';`;
const record = (name, body) => ({name, setup: b => {
  b.onResolve({filter: /date-format\.ts$/}, args => args.namespace === name ? undefined : {path: HELPER, namespace: name});
  b.onLoad({filter: /.*/, namespace: name}, () => ({resolveDir: ROOT, loader: 'js', contents: `${body}
    export function dateTimeFormat(locale, timeZone, options) { (globalThis.__sc1407 ??= []).push([locale, timeZone, {...options}]); return make(locale, timeZone, options); }`}));
}});
const cachedPlugin = record('cached', `import {dateTimeFormat as make} from ${JSON.stringify(HELPER)};`);
const oraclePlugin = record('oracle', `const ORIGINAL = ${JSON.stringify(Object.values(ORIGINAL))};
  const sorted = o => JSON.stringify(Object.entries(o).sort(([a], [b]) => a < b ? -1 : 1));
  function make(locale, timeZone, options) {
    if (!ORIGINAL.some(([l, o]) => l === locale && sorted(o) === sorted(options))) throw Error('not an original pattern: ' + locale + ' ' + JSON.stringify(options));
    return new Intl.DateTimeFormat(locale, {timeZone, ...options});
  }`);
const bundles = {};
async function bundle(kind) {
  if (bundles[kind]) return bundles[kind];
  const out = join(await mkdtemp(join(tmpdir(), `intl-${kind}-`)), 'sites.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: ENTRY}, bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent',
    jsx: 'automatic', jsxImportSource: 'preact', plugins: [kind === 'cached' ? cachedPlugin : oraclePlugin, ...rendererPlugins]});
  return bundles[kind] = await import(pathToFileURL(out).href);
}

const HOUR = 3_600_000, iso = ms => new Date(ms).toISOString();
const report0 = JSON.parse(readFileSync(new URL('./fixtures/coast/skippercast-report.json', import.meta.url), 'utf8'));
const RULES = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url), 'utf8'));
/** The spear test's calm report (tests/test_spear.mjs) with a nearshore site, so every profile reaches its hour text. */
function report(now) {
  const start = Date.parse(report0.forecasts[1].hours[0].at), out = structuredClone(report0);
  const hours = Array.from({length: 48}, (_, i) => ({at: iso(start + i * HOUR), windKnots: 5, gustKnots: 8, waveFt: 4.5, wavePeriodS: 11, swellFt: 4, swellPeriodS: 11, airTempF: 60, precipPct: 0}));
  out.alerts = []; out.forecasts = out.forecasts.map(f => f.id === 'central' ? {...f, hours} : f);
  out.nearshore = [{id: 'mop-test', name: 'Morro Rock', areaId: 'central', lat: 35.37, lon: -120.87, sourceId: 'cdip', issuedAt: iso(now - 2 * HOUR), fetchedAt: iso(now - 20 * 60_000),
    hours: Array.from({length: 16}, (_, i) => ({at: iso(start - 3 * HOUR + i * 3 * HOUR), waveFt: 1.5, periodS: 11, directionDeg: 280, qualityFlag: null, secondaryFlag: null})),
    url: 'https://cdip.ucsd.edu', kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 180, waterDepthM: 15, depthDatum: 'MSL', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: iso(start + 42 * HOUR)}];
  out.chlorophyll = {mgM3: 0.8, sampleAt: '2026-10-08T12:00:00Z', cells: 6, label: 'NOAA VIIRS chlorophyll', url: 'https://coastwatch.noaa.gov'};
  return out;
}
const caught = fn => { try { return {ok: fn()}; } catch (error) { return {name: error.name, message: error.message}; } };

/** Everything the nine sites produce for one zone, read through one bundle. */
function sites(m, tz) {
  const out = {}, county = {...m.slo, timezone: tz}, area = m.slo.areas.find(a => a.id === 'central');
  const now = new Date(Date.parse(report0.generatedAt) + 10 * 60_000), r = report(now.getTime());
  for (const mode of ['boat', 'shore', 'spear', 'kayak']) out[`daily ${mode}`] = m.buildDaily(r, county, area, mode, '2026-10-09', now);
  for (const at of INSTANTS) {
    out[`dateKey ${at.toISOString()}`] = m.dateKey(at, tz);
    out[`days ${at.toISOString()}`] = m.availableDays(r, county, area, at);
  }
  for (const date of ['2026-03-08', '2026-11-01', '2026-06-15']) {
    const base = Date.parse(`${date}T00:00:00Z`), hours = Array.from({length: 40}, (_, i) => base + i * HOUR);
    out[`window ${date}`] = m.windowHours(hours, date, tz, null, null, new Date(base));
    out[`window sun ${date}`] = m.windowHours(hours, date, tz, iso(base + 14 * HOUR), iso(base + 26 * HOUR), new Date(base));
  }
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL('https://s.test/map?region=morro-bay&profile=boat&view=plan&target=halibut');
  m.regionInfo.value = {id: 'morro-bay', name: 'Morro Bay', timezone: tz, center: [35, -121], rules: {...RULES.region, timezone: tz}};
  m.markData.value = {region: {...RULES.region, timezone: tz}, atlas: null};
  m.regsData.value = {region: RULES.region.id, data: structuredClone(RULES.regulations)};
  try {
    for (const at of INSTANTS) out[`plan ${at.toISOString()}`] = m.targetRules(at);
    out.rules = m.render(m.h(m.RulesLine, {mark: {id: 'spot:a', name: 'a', kind: 'Reef mark', reading: '', source: '', basis: ''}}));
  } finally { m.regionInfo.value = null; m.markData.value = null; m.regsData.value = null; }
  out.refusals = [caught(() => m.dateKey('not a date', tz)), caught(() => m.dateKey(INSTANTS[0], 'Not/AZone')),
    caught(() => m.windowHours([NaN], '2026-03-08', tz, null, null, INSTANTS[0])), caught(() => m.windowHours([INSTANTS[0].getTime()], '2026-03-08', 'Not/AZone', null, null, INSTANTS[0]))];
  return out;
}

test('formatter_all_nine_real_sites_match_original', async () => {
  const cached = await bundle('cached'), oracle = await bundle('oracle');
  for (const tz of ZONES) {
    globalThis.__sc1407 = [];
    const got = sites(cached, tz), requests = globalThis.__sc1407;
    globalThis.__sc1407 = [];
    const want = sites(oracle, tz);
    for (const key of Object.keys(want)) assert.ok(isDeepStrictEqual(got[key], want[key]), `${tz} ${key} matches the uncached original patterns`);
    for (const [locale, zone, options] of requests) assert.ok(original(locale, options) && [tz, 'Not/AZone'].includes(zone), `${locale} ${zone} ${JSON.stringify(options)} is an original site pattern`);
    for (const [name, [locale, options]] of Object.entries(ORIGINAL)) assert.ok(requests.some(([l, , o]) => l === locale && isDeepStrictEqual(sorted(o), sorted(options))), `${name} was exercised`);
    assert.match(got['daily spear'].summary, /Calmest daylight hour: \d{1,2} (AM|PM) \(/, 'the spear sentence ran with a best hour');
    assert.deepEqual(got.refusals.map(r => r.name), ['RangeError', 'RangeError', 'RangeError', 'RangeError']);
    assert.equal(got.refusals[0].message, 'Invalid date');
    assert.equal(got['plan 2026-03-08T07:30:00.000Z'].state.today, tz === 'UTC' ? '2026-03-08' : '2026-03-07');
    assert.equal(got['plan 2026-11-01T08:30:00.000Z'].state.today, '2026-11-01');
  }
  // Churn the cached bundle's cache well past its cap, then every site still reads the same.
  for (const tz of Intl.supportedValuesOf('timeZone').slice(0, 130)) cached.dateKey(INSTANTS[0], tz);
  const again = sites(cached, 'America/Los_Angeles'), want = sites(oracle, 'America/Los_Angeles');
  for (const key of Object.keys(want)) assert.ok(isDeepStrictEqual(again[key], want[key]), `after eviction ${key}`);
});

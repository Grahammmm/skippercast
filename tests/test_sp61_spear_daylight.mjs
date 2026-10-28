// SP61: exercise the complete real modules, with pre-import offline defaults.
import test, {after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {resolve} from 'node:path';

const ownRoot = fileURLToPath(new URL('../', import.meta.url));
let sourceRoot = ownRoot, scenario = 'all';
for (let i = 2; i < process.argv.length; i++) {
  const arg = process.argv[i];
  if (arg === '--source-root' && process.argv[i + 1]) sourceRoot = resolve(process.argv[++i]);
  else if (arg === '--scenario' && process.argv[i + 1] === 'baseline-control') scenario = process.argv[++i];
  else throw Error(`Unsupported SP61 argument: ${arg}`);
}
const saved = new Map(['fetch', 'localStorage', 'sessionStorage'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
let fetchCalls = 0, storageCalls = 0;
const offlineFetch = () => {fetchCalls++; throw Error('SP61 offline fetch sentinel');};
const offlineStorage = Object.fromEntries(['getItem', 'setItem', 'removeItem', 'clear', 'key'].map(key => [key, () => {storageCalls++; throw Error('SP61 storage sentinel');}]));
Object.defineProperties(globalThis, {
  fetch: {configurable: true, writable: true, value: offlineFetch},
  localStorage: {configurable: true, value: offlineStorage},
  sessionStorage: {configurable: true, value: offlineStorage},
});
after(() => {
  try {
    assert.equal(fetchCalls, 0, 'No network use, including bound defaults');
    assert.equal(storageCalls, 0, 'No storage use');
    console.log('@SP61_OFFLINE ' + JSON.stringify({fetchCalls, storageCalls, checks: 2}));
  } finally {
    for (const [key, descriptor] of saved) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
});
const fixture = JSON.parse(readFileSync(new URL('./fixtures/sp61_spear_daylight/night-only.json', import.meta.url), 'utf8'));
const moduleURL = name => pathToFileURL(resolve(sourceRoot, 'packages/coast/src', name)).href;
const {spearHours, spearDay} = await import(moduleURL('spear.ts'));
const {sunrise, sunset} = fixture;
const HOUR = 3_600_000;
const iso = t => new Date(t).toISOString();
const hour = (at, patch = {}) => ({...fixture.hour, at, ...patch});
function readings(hours) {
  return spearHours({hours, forecastHours: hours, site: undefined, observations: [], tideEvents: [], chlorophyll: fixture.chlorophyll});
}
// Assertion calls are counted independently of Node's test-case count.
function checkCase(name, fn) {
  test(name, async () => {
    let checks = 0;
    const a = new Proxy(assert, {get(target, key) {
      const value = target[key];
      return typeof value === 'function' ? (...args) => {checks++; return value(...args);} : value;
    }});
    try {
      await fn(a);
      console.log('@SP61_CASE ' + JSON.stringify({name, status: 'pass', checks}));
    } catch (error) {
      console.log('@SP61_CASE ' + JSON.stringify({name, status: 'fail', checks, code: error.code ?? null, message: error.message}));
      throw error;
    }
  });
}

checkCase('A1 primary: known daylight night-only best is null', a => {
  const inputs = [structuredClone(fixture.hour)], inputBefore = structuredClone(inputs);
  const hours = readings(inputs), before = structuredClone(hours);
  const day = spearDay(hours, sunrise, sunset);
  a.equal(day.best, null, 'SP61_A4_NIGHT_BEST_MUST_BE_NULL');
  a.equal(day.surge, null);
  a.equal(day.basis, null);
  a.equal(day.clarity.band, 'Unknown');
  a.deepEqual(day.clarity.missing, ['daylight forecast hours']);
  a.equal(day.hours, hours, 'Preserve the original readings array identity');
  a.deepEqual(day.hours, before);
  a.deepEqual(hours, before);
  a.deepEqual(inputs, inputBefore);
  a.equal(hours[0].surge.band, 'Low', 'Retained night reading remains informative');
});
checkCase('A3 positive control: unknown daylight retains all-hour fallback', a => {
  const hours = readings([fixture.hour]);
  const day = spearDay(hours, null, null);
  a.equal(day.best, hours[0]);
  a.deepEqual(day.surge, {min: 'Low', max: 'Low'});
  a.equal(day.basis, 'offshore');
  a.deepEqual(day.clarity, hours[0].clarity);
  a.equal(day.hours, hours);
});
if (scenario === 'all') {
  checkCase('A2 boundaries: sunrise and sunset equality qualify; crossing sunset does not', a => {
    const rise = Date.parse(sunrise), set = Date.parse(sunset);
    for (const t of [rise, set - HOUR]) {
      const hours = readings([hour(iso(t))]);
      a.equal(spearDay(hours, sunrise, sunset).best, hours[0]);
    }
    for (const t of [rise - 1, set - HOUR + 1, set]) {
      const day = spearDay(readings([hour(iso(t))]), sunrise, sunset);
      a.equal(day.best, null);
      a.equal(day.surge, null);
      a.equal(day.basis, null);
      a.equal(day.clarity.band, 'Unknown');
    }
  });
  checkCase('A2 mixed: a better night cannot set best, surge range, clarity or basis', a => {
    const hours = readings([fixture.hour, hour(sunrise, {waveFt: 2.5, wavePeriodS: 10})]);
    // Explicit in-memory SpearHour boundary values; not claimed as JSON producer payloads.
    hours[0].clarity = {band: 'Likely poor', drivers: ['night only'], missing: [], gaps: []};
    hours[0].surge.basis = 'nearshore';
    hours[1].clarity = {band: 'Fair', drivers: ['day only'], missing: [], gaps: []};
    a.equal(hours[0].verdict, 'Calmer');
    a.equal(hours[1].verdict, 'Marginal');
    const before = structuredClone(hours), day = spearDay(hours, sunrise, sunset);
    a.equal(day.best, hours[1]);
    a.deepEqual(day.surge, {min: 'Moderate', max: 'Moderate'});
    a.equal(day.clarity, hours[1].clarity);
    a.equal(day.basis, 'offshore');
    a.deepEqual(hours, before);
  });
  checkCase('A2 empty: no readings are invented', a => {
    for (const [rise, set] of [[sunrise, sunset], [null, null]]) {
      const hours = [], day = spearDay(hours, rise, set);
      a.equal(day.hours, hours);
      a.deepEqual(day.hours, []);
      a.equal(day.best, null);
      a.equal(day.surge, null);
      a.equal(day.basis, null);
      a.equal(day.clarity.band, 'Unknown');
      a.deepEqual(day.clarity.missing, [rise ? 'daylight forecast hours' : 'forecast hours']);
    }
  });
  checkCase('A3 missing or unparsable sun clocks preserve fallback', a => {
    const hours = readings([fixture.hour]);
    for (const [rise, set] of [[null, sunset], [sunrise, null], ['bad', sunset], [sunrise, 'bad'], ['', sunset], [sunrise, '']]) {
      const day = spearDay(hours, rise, set);
      a.equal(day.best, hours[0]);
      a.equal(day.basis, 'offshore');
      a.deepEqual(day.surge, {min: 'Low', max: 'Low'});
      a.equal(day.clarity, hours[0].clarity);
    }
  });
  checkCase('A3 normal ordering, early ties and Rough/Unknown exclusions remain', a => {
    const early = readings([hour(sunrise)])[0];
    const later = structuredClone(early); later.at = iso(Date.parse(sunrise) + HOUR);
    const rough = structuredClone(early); rough.verdict = 'Rough';
    const unknown = structuredClone(early); unknown.verdict = 'Unknown';
    const hours = [later, unknown, rough, early], before = structuredClone(hours);
    a.equal(spearDay(hours, sunrise, sunset).best, early);
    a.equal(spearDay([rough, unknown], sunrise, sunset).best, null);
    a.deepEqual(hours, before);
    const marginal = structuredClone(early); marginal.verdict = 'Marginal';
    a.equal(spearDay([marginal, later], sunrise, sunset).best, later);
    const moderate = structuredClone(later); moderate.surge.band = 'Moderate';
    a.equal(spearDay([moderate, early], sunrise, sunset).best, early);
  });
  checkCase('A3 buildDaily: night-only summary withholds best and hazard windows stay screened', async a => {
    const {buildDaily, windowHourHazards} = await import(moduleURL('daily.ts'));
    const {slo} = await import(moduleURL('counties.ts'));
    const area = slo.areas.find(item => item.id === 'central');
    const now = new Date('2026-10-24T03:00:00.000Z');
    const makeReport = hours => ({schemaVersion: 1, countyId: 'slo', generatedAt: now.toISOString(),
      forecasts: [{id: area.id, sourceId: 'synthetic-forecast', hours}], observations: [], tides: [], tideEvents: [], alerts: [],
      sources: ['synthetic-forecast', 'nws-alerts'].map(id => ({id, label: id, url: 'https://example.invalid/', kind: id === 'nws-alerts' ? 'report' : 'forecast', outcome: 'ok', fetchedAt: now.toISOString(), issuedAt: now.toISOString()})),
      catches: [], catchStatus: 'unknown', visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, habitatStatus: 'unknown', chlorophyll: fixture.chlorophyll});
    const report = makeReport([hour(now.toISOString()), hour(iso(now.getTime() + HOUR))]);
    const before = structuredClone(report);
    const night = buildDaily(report, slo, area, 'spear', '2026-10-23', now);
    a.equal(night.hours.length, 2, 'Fresh forecast reached daily integration');
    a.ok(night.sunrise && night.sunset, 'Astronomy is known');
    a.ok(night.hours.every(h => Date.parse(h.at) >= Date.parse(night.sunset)));
    a.equal(night.spear.best, null);
    a.equal(night.spear.surge, null);
    a.equal(night.spear.basis, null);
    a.equal(night.spear.clarity.band, 'Unknown');
    a.doesNotMatch(night.summary, /Calmest daylight hour:/);
    a.match(night.summary, /No daylight hour reads calmer or marginal/);
    a.deepEqual(night.windows, []);
    a.deepEqual(report, before);
    // Genuine positive day plus separate hazard cases, through the unchanged consumer.
    const times = [16, 17, 18, 19, 20].map(h => `2026-10-24T${h}:00:00.000Z`);
    const calm = buildDaily(makeReport(times.map(t => hour(t))), slo, area, 'spear', '2026-10-24', now);
    a.ok(calm.windows.length > 0, 'Healthy daylight windows remain possible');
    a.match(calm.summary, /Calmest daylight hour:/);
    for (const patch of [{waveFt: 3, wavePeriodS: 14}, {waveFt: 5, wavePeriodS: 16}]) {
      const day = buildDaily(makeReport(times.map(t => hour(t, patch))), slo, area, 'spear', '2026-10-24', now);
      a.equal(day.hours.length, 5);
      a.ok(day.spear.hours.every(h => h.verdict === 'Rough'));
      a.deepEqual(day.windows, []);
      for (const h of day.hours) a.ok(windowHourHazards({hour: h, sunrise: day.sunrise, sunset: day.sunset, nearJudged: false, spear: day.spear.hours.find(x => x.at === h.at)}).length > 0);
    }
  });
}

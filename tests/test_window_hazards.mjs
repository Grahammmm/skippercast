// Issue #551: no suggested brief window, for any profile and any comfort limits,
// may hold an hour the profile grades Rough or an hour a hazard rule flags
// (packages/coast/src/daily.ts windowHourHazards). A seeded, offline property
// test over random days and limits, and the three cases the issue reported.
import test from 'node:test';
import assert from 'node:assert/strict';
import fixture from './fixtures/coast/skippercast-report.json' with {type: 'json'};

const {buildDaily, windowHourHazards} = await import('../packages/coast/src/daily.ts');
const {LIMIT_BOUNDS, LIMIT_SURGE_BANDS} = await import('../packages/coast/src/limits.ts');
const {slo} = await import('../packages/coast/src/counties.ts');

const HOUR = 3_600_000;
const now = new Date(Date.parse(fixture.generatedAt) + 10 * 60_000);
const area = slo.areas.find(a => a.id === 'central');
const start = Date.parse(fixture.forecasts[1].hours[0].at);
const iso = ms => new Date(ms).toISOString();
const MODES = ['boat', 'shore', 'spear', 'kayak'];

/** The fixture report with one generated day pattern for the central area: hour-to-hour variation, optional nearshore site and alert. */
function report({site = false, wave = 2, waveStep = 0, period = 10, swellS = period, nearFt = 2, nearStep = 0, nearS = 10, wind = 5, windStep = 0, gust = 8, gustStep = 0, dir = 0, alerts = []} = {}) {
  const hours = Array.from({length: 48}, (_, i) => ({at: iso(start + i * HOUR), windKnots: wind + windStep * (i % 5), gustKnots: gust + gustStep * (i % 7), windDirectionDeg: dir,
    waveFt: wave + waveStep * (i % 3), wavePeriodS: period, swellFt: Math.max(0, wave - 0.5), swellPeriodS: swellS, airTempF: 60, precipPct: 0}));
  const out = structuredClone(fixture);
  out.alerts = alerts;
  out.forecasts = out.forecasts.map(f => f.id === 'central' ? {...f, hours} : f);
  if (site) out.nearshore = [{id: 'mop-test', name: 'Morro Strand', areaId: 'central', lat: 35.4, lon: -120.87, sourceId: 'cdip', issuedAt: iso(now.getTime() - 2 * HOUR), fetchedAt: iso(now.getTime() - 20 * 60_000),
    hours: Array.from({length: 16}, (_, i) => ({at: iso(start - 3 * HOUR + i * 3 * HOUR), waveFt: nearFt + nearStep * (i % 3), periodS: nearS, directionDeg: 280, qualityFlag: null, secondaryFlag: null})),
    url: 'https://cdip.ucsd.edu', kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 180, waterDepthM: 15, depthDatum: 'MSL', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: iso(start + 42 * HOUR)}];
  return out;
}
const covered = (brief, at) => brief.windows.some(w => Date.parse(at) >= Date.parse(w.start) && Date.parse(at) < Date.parse(w.end));
const at = (list, hour) => list?.find(x => x.at === hour.at);

/**
 * Each hazard read straight from the brief's own readings, not through windowHourHazards, so the property
 * checks the rule rather than restating it. Returns the reasons an hour must stay out of every window.
 */
function hazards(brief, mode, hour) {
  const out = [], t = Date.parse(hour.at);
  if (!brief.sunrise || !brief.sunset || t < Date.parse(brief.sunrise) || t + HOUR > Date.parse(brief.sunset)) out.push('darkness');
  const bar = at(brief.bar?.hours, hour), shore = at(brief.shore?.hours, hour), spear = at(brief.spear?.hours, hour), kayak = at(brief.kayak?.hours, hour);
  const nearJudged = mode === 'shore' ? shore?.surf.basis === 'nearshore' : mode === 'spear' ? spear?.surge.basis === 'nearshore' : false;
  if (!nearJudged && hour.waveFt >= 2.5 && (hour.wavePeriodS >= 15 || hour.swellPeriodS >= 15)) out.push('long-period swell');
  if (bar?.band === 'Hazardous') out.push('hazardous bar');
  if (shore?.surf.sneaker) out.push('sneaker swell');
  if (spear?.surge.band === 'Heavy') out.push('heavy surge');
  for (const reading of [shore, spear, kayak]) if (reading?.verdict === 'Rough') out.push('Rough');
  if (kayak?.wind.side === 'offshore') out.push('offshore wind');
  if (kayak?.launchCaution) out.push('launch surf');
  return out;
}
function assertClean(brief, mode, context) {
  if (brief.alerts.length) assert.deepEqual(brief.windows, [], `${context}: a marine alert withholds every window`);
  for (const hour of brief.hours) if (covered(brief, hour.at)) {
    const found = hazards(brief, mode, hour);
    assert.deepEqual(found, [], `${context} ${hour.at}`);
  }
}

/** A small seeded generator (mulberry32), so a failure replays exactly. */
function rng(seed) {
  return () => {seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296;};
}
const ALERT = {id: 'sca', event: 'Small Craft Advisory', headline: 'Small Craft Advisory in effect', description: '', effective: null, expires: null, url: 'https://weather.gov'};
const WEIRD = [NaN, Infinity, -Infinity, -5, 0, 1e308, '1e400', 'abc', null, undefined, {}, [], '  ', '0x10', 99, -0];

test('property: no window hour is Rough or hazard-flagged, for every profile, under defaults and random limits', () => {
  const random = rng(551), pick = list => list[Math.floor(random() * list.length)];
  let windows = 0, flaggedDays = 0;
  for (let run = 0; run < 400; run++) {
    const mode = MODES[run % 4];
    const opts = {site: random() < 0.6, wave: pick([1, 1.5, 2, 2.5, 3, 4]), waveStep: pick([0, 0.5]), period: pick([6, 8, 10, 12, 14, 16, 18]), swellS: pick([8, 12, 14, 15, 16, 18]),
      nearFt: pick([1, 2, 3, 4, 6]), nearStep: pick([0, 1]), nearS: pick([8, 10, 14, 16, 18]), wind: pick([1, 3, 5, 7, 10, 14]), windStep: pick([0, 1]), gust: pick([3, 6, 9, 12, 16, 22]), gustStep: pick([0, 1]),
      dir: pick([0, 80, 270, 300]), alerts: random() < 0.1 ? [ALERT] : []};
    const date = pick(['2026-10-09', '2026-10-10']);
    const kind = random();
    const bounds = LIMIT_BOUNDS[mode];
    const limits = kind < 0.25 ? undefined
      : kind < 0.5 ? Object.fromEntries(Object.entries(bounds).map(([field, b]) => [field, b.max]))
      : kind < 0.8 ? Object.fromEntries(Object.entries(bounds).map(([field, b]) => [field, b.min + Math.round(random() * (b.max - b.min) / b.step) * b.step]))
      : {wind: pick(WEIRD), gust: pick(WEIRD), seas: pick(WEIRD)};
    if (limits && mode === 'spear') limits.surge = pick([...LIMIT_SURGE_BANDS, 'Heavy', null, 'toString']);
    const brief = buildDaily(report(opts), slo, area, mode, date, now, limits);
    windows += brief.windows.length;
    if (brief.hours.some(hour => hazards(brief, mode, hour).length)) flaggedDays++;
    assertClean(brief, mode, `run ${run} ${mode} ${JSON.stringify(opts)} limits ${JSON.stringify(limits)}`);
  }
  assert.ok(windows > 40, `the runs suggest windows (${windows})`);
  assert.ok(flaggedDays > 100, `the runs include flagged hours (${flaggedDays})`);
});

test('windowHourHazards: each rule on its own, and nothing for a calm daylight hour', () => {
  const hour = {at: '2026-10-09T20:00:00.000Z', windKnots: 5, gustKnots: 8, windDirectionDeg: 0, waveFt: 2, wavePeriodS: 10, swellFt: 1.5, swellPeriodS: 10, airTempF: 60, precipPct: 0};
  const day = {sunrise: '2026-10-09T14:00:00.000Z', sunset: '2026-10-10T01:30:00.000Z', nearJudged: false};
  assert.deepEqual(windowHourHazards({hour, ...day}), []);
  assert.deepEqual(windowHourHazards({hour, ...day, sunset: '2026-10-09T20:30:00.000Z'}), ['darkness'], 'the hour must end before sunset');
  assert.deepEqual(windowHourHazards({hour, ...day, sunrise: null}), ['darkness'], 'unknown daylight is not daylight');
  const long = {...hour, waveFt: 2.5, swellPeriodS: 16};
  assert.deepEqual(windowHourHazards({hour: long, ...day}), ['long-period swell']);
  assert.deepEqual(windowHourHazards({hour: long, ...day, nearJudged: true}), [], 'a spear or shore nearshore model judges the hour instead');
  assert.deepEqual(windowHourHazards({hour, ...day, bar: {band: 'Hazardous'}}), ['hazardous bar']);
  assert.deepEqual(windowHourHazards({hour, ...day, bar: {band: 'Caution'}}), []);
  assert.deepEqual(windowHourHazards({hour, ...day, shore: {verdict: 'Marginal', surf: {sneaker: true}}}), ['sneaker-wave swell']);
  assert.deepEqual(windowHourHazards({hour, ...day, shore: {verdict: 'Rough', surf: {sneaker: false}}}), ['shore Rough']);
  assert.deepEqual(windowHourHazards({hour, ...day, spear: {verdict: 'Rough', surge: {band: 'Heavy'}}}), ['heavy surge', 'spear Rough']);
  const kayak = {verdict: 'Marginal', wind: {side: 'cross-shore'}, launchCaution: false};
  assert.deepEqual(windowHourHazards({hour, ...day, kayak}), []);
  assert.deepEqual(windowHourHazards({hour, ...day, kayak: {...kayak, wind: {side: 'offshore'}}}), ['offshore wind']);
  assert.deepEqual(windowHourHazards({hour, ...day, kayak: {...kayak, launchCaution: true}}), ['launch surf']);
  assert.deepEqual(windowHourHazards({hour, ...day, kayak: {...kayak, verdict: 'Rough'}}), ['kayak Rough']);
});

test('issue case 1, boat: a hazardous bar hour in the middle of a window splits it', () => {
  // Nearshore swell steps to 4 ft at the ebb mid-afternoon; departure and return both read clear.
  const day = buildDaily(report({site: true, nearFt: 2, nearStep: 1, wave: 1}), slo, area, 'boat', '2026-10-09', now);
  const hazardous = day.bar.hazardous.filter(hour => Date.parse(hour.at) >= Date.parse(day.sunrise) && Date.parse(hour.at) + HOUR <= Date.parse(day.sunset));
  assert.ok(hazardous.length > 0, 'a daylight hour reads a hazardous bar');
  assert.ok(day.windows.length > 0, 'calm hours either side still make windows');
  for (const hour of hazardous) assert.ok(!covered(day, hour.at), hour.at);
  // The same day with your loosest limits.
  const loose = buildDaily(report({site: true, nearFt: 2, nearStep: 1, wave: 1}), slo, area, 'boat', '2026-10-09', now, {wind: 20, gust: 25, seas: 8});
  for (const hour of hazardous) assert.ok(!covered(loose, hour.at), hour.at);
});

test('issue case 2, shore: long-period swell keeps hours out when the surf is the offshore estimate', () => {
  // 2 ft offshore seas at 8 s carry a 1.5 ft swell at 16 s: under the generic 2.5 ft rule, but a sneaker-wave hour.
  const day = buildDaily(report({wave: 2, period: 8, swellS: 16}), slo, area, 'shore', '2026-10-09', now);
  const sneaker = day.shore.hours.filter(hour => hour.surf.sneaker);
  assert.ok(sneaker.length > 0 && sneaker.every(hour => hour.surf.basis === 'offshore'));
  for (const hour of sneaker) assert.ok(!covered(day, hour.at), hour.at);
  assert.deepEqual(day.windows, []);
  assert.equal(day.status, 'Caution');
});

test('issue case 3, spear: an hour graded Rough from offshore surge is never in a window', () => {
  // 3 ft at 14 s offshore is Strong surge: within the generic 3 ft rule, but the spear verdict reads Rough.
  for (const limits of [undefined, {wind: 12, gust: 18, seas: 5, surge: 'Strong'}]) {
    const day = buildDaily(report({wave: 3, period: 14}), slo, area, 'spear', '2026-10-09', now, limits);
    const rough = day.spear.hours.filter(hour => hour.verdict === 'Rough');
    assert.ok(rough.length > 0 && rough.every(hour => hour.surge.basis === 'offshore'));
    for (const hour of rough) assert.ok(!covered(day, hour.at), `${JSON.stringify(limits)} ${hour.at}`);
  }
});

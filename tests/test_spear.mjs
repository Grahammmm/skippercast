// Issue #542: the spearfishing reading (packages/coast/src/spear.ts) and its
// place in the daily brief (daily.ts buildDaily, web/brief/model.ts).
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import util from 'node:util';
import fixture from './fixtures/coast/skippercast-report.json' with {type: 'json'};
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import montereyForecast from './fixtures/brief/monterey-forecast.json' with {type: 'json'};

const {SPEAR, surgeEnergy, surgeBand, surge, chop, clarity, recentEnergy, spearVerdict, spearHours, spearDay} = await import('../packages/coast/src/spear.ts');
const {buildDaily} = await import('../packages/coast/src/daily.ts');
const {reportPanel} = await import('../packages/coast/src/presentation.ts');
const {slo} = await import('../packages/coast/src/counties.ts');
const {buildCoastBrief, buildRegionalBrief, chlorophyllNear, regionalReport} = await import('../web/brief/model.ts');

const HOUR = 3_600_000;
const now = new Date(Date.parse(fixture.generatedAt) + 10 * 60_000);
const date = '2026-10-09';
const area = slo.areas.find(a => a.id === 'central');
const start = Date.parse(fixture.forecasts[1].hours[0].at);
const iso = ms => new Date(ms).toISOString();

/** The fixture report with calm wind, 4.5 ft offshore seas and optional nearshore site and chlorophyll. */
function report({site = false, chl = 0.8, wave = 4.5, nearFt = 1.5, nearS = 11} = {}) {
  const hours = Array.from({length: 48}, (_, i) => ({at: iso(start + i * HOUR), windKnots: 5, gustKnots: 8, waveFt: wave, wavePeriodS: 11, swellFt: wave - 0.5, swellPeriodS: 11, airTempF: 60, precipPct: 0}));
  const out = structuredClone(fixture);
  out.alerts = [];
  out.forecasts = out.forecasts.map(f => f.id === 'central' ? {...f, hours} : f);
  if (site) out.nearshore = [{id: 'mop-test', name: 'Morro Rock', areaId: 'central', lat: 35.37, lon: -120.87, sourceId: 'cdip', issuedAt: iso(now.getTime() - 2 * HOUR), fetchedAt: iso(now.getTime() - 20 * 60_000),
    hours: Array.from({length: 16}, (_, i) => ({at: iso(start - 3 * HOUR + i * 3 * HOUR), waveFt: nearFt, periodS: nearS, directionDeg: 280, qualityFlag: null, secondaryFlag: null})),
    url: 'https://cdip.ucsd.edu', kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 180, waterDepthM: 15, depthDatum: 'MSL', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: iso(start + 42 * HOUR)}];
  out.chlorophyll = chl === null ? null : {mgM3: chl, sampleAt: '2026-10-08T12:00:00Z', cells: 6, label: 'NOAA VIIRS chlorophyll', url: 'https://coastwatch.noaa.gov'};
  return out;
}

test('surge energy is H² · T with the long-period factor, banded by the SPEAR table', () => {
  assert.equal(surgeEnergy(2, 10), 40);
  assert.equal(surgeEnergy(3, 14), 3 * 3 * 14 * 1.25);
  assert.equal(surgeEnergy(2, 16), 2 * 2 * 16 * 1.5);
  assert.equal(surgeEnergy(null, 10), null);
  assert.equal(surgeEnergy(2, 0), null);
  assert.equal(surgeBand(null), 'Unknown');
  assert.equal(surgeBand(surgeEnergy(1.5, 10)), 'Low');
  assert.equal(surgeBand(surgeEnergy(3, 12)), 'Moderate');
  // Same height, longer period: the long-period factor lifts it a band.
  assert.equal(surgeBand(surgeEnergy(3, 14)), 'Strong');
  assert.equal(surgeBand(surgeEnergy(5, 15)), 'Heavy');
});

test('surge prefers a nearshore sample and otherwise takes the larger offshore component', () => {
  const hour = {at: iso(start), windKnots: 5, gustKnots: 8, waveFt: 4, wavePeriodS: 9, swellFt: 3.5, swellPeriodS: 16};
  const near = surge(hour, {at: hour.at, waveFt: 1.5, periodS: 11, directionDeg: null, qualityFlag: null, secondaryFlag: null});
  assert.deepEqual([near.basis, near.band, near.heightFt], ['nearshore', 'Low', 1.5]);
  const off = surge(hour);
  // 3.5² · 16 · 1.5 = 294 beats 4² · 9 = 144: the long-period swell sets the band.
  assert.deepEqual([off.basis, off.band, off.periodS], ['offshore', 'Heavy', 16]);
  assert.equal(surge({...hour, waveFt: null, swellFt: null}).band, 'Unknown');
});

test('chop bands follow wind and gust', () => {
  assert.equal(chop(6, 10).band, 'Light');
  assert.equal(chop(6, 14).band, 'Choppy');
  assert.equal(chop(11, 16).band, 'Choppy');
  assert.equal(chop(14, 20).band, 'Rough');
  assert.equal(chop(null, 10).band, 'Unknown');
});

const at = '2026-10-09T18:00:00Z';
const chl = mgM3 => ({mgM3, sampleAt: '2026-10-08T12:00:00Z', cells: 4, label: 'chl', url: 'https://example.com'});
const base = {chlorophyll: chl(0.8), at, rainPct: 0, rainHoursCovered: 72, recentEnergy: 30, recentHoursCovered: 48, windKnots: 5};
const CHL_NOTE = 'Clarity estimate: satellite chlorophyll is an offshore area average and may read clearer than the shoreline';

test('clarity: each driver moves the band, and the estimate stays labelled', () => {
  assert.equal(clarity(base).band, 'Likely good');
  assert.deepEqual(clarity(base).gaps, [CHL_NOTE]);
  const cases = [
    [{chlorophyll: chl(2.5)}, 'Fair', /some green water/],
    [{chlorophyll: chl(6)}, 'Likely poor', /green water likely/],
    [{rainPct: 40}, 'Fair', /rain chance up to 40%/],
    [{rainPct: 80}, 'Likely poor', /runoff likely/],
    [{recentEnergy: 150}, 'Fair', /moderate swell in the past 2 days/],
    [{recentEnergy: 300}, 'Likely poor', /stirred sediment likely/],
    [{windKnots: 11}, 'Fair', /wind 11 kt: some chop/],
    [{windKnots: 18}, 'Likely poor', /surface chop/],
  ];
  for (const [patch, band, driver] of cases) {
    const k = clarity({...base, ...patch});
    assert.equal(k.band, band, JSON.stringify(patch));
    assert.ok(k.drivers.some(d => driver.test(d)), JSON.stringify(k.drivers));
  }
  // Three fair drivers together read as likely poor.
  assert.equal(clarity({...base, chlorophyll: chl(2), rainPct: 35, windKnots: 11}).band, 'Likely poor');
});

test('clarity: missing chlorophyll or recent swell says Unknown and names what is missing', () => {
  const none = clarity({...base, chlorophyll: null});
  assert.equal(none.band, 'Unknown');
  assert.deepEqual(none.missing, ['satellite chlorophyll']);
  const old = clarity({...base, chlorophyll: {...chl(0.5), sampleAt: '2026-10-01T12:00:00Z'}});
  assert.deepEqual([old.band, old.missing], ['Unknown', ['a recent chlorophyll reading']]);
  const both = clarity({...base, chlorophyll: null, recentEnergy: null});
  assert.deepEqual(both.missing, ['satellite chlorophyll', 'recent swell']);
  // Rain and wind gaps are listed but do not blank the band.
  const gaps = clarity({...base, rainPct: null, windKnots: null});
  assert.equal(gaps.band, 'Likely good');
  assert.deepEqual(gaps.gaps, [CHL_NOTE, 'Clarity estimate: recent rain unknown', 'Clarity estimate: wind unknown']);
  assert.ok(clarity({...base, rainHoursCovered: 18}).gaps.includes('Clarity estimate: rain before the forecast began is unchecked'));
});

test('clarity: a mostly unchecked swell look-back caps the band at Fair and says so', () => {
  const SWELL_GAP = 'Clarity estimate: swell before the forecast began is unchecked';
  const covered = clarity({...base, recentHoursCovered: 36});
  assert.equal(covered.band, 'Likely good');
  assert.ok(!covered.gaps.includes(SWELL_GAP));
  const short = clarity({...base, recentHoursCovered: 6});
  assert.equal(short.band, 'Fair');
  assert.ok(short.gaps.includes(SWELL_GAP));
  // The cap never improves a worse band.
  assert.equal(clarity({...base, recentHoursCovered: 6, recentEnergy: 300}).band, 'Likely poor');
});

test('recentEnergy counts the covered hours of the 48 h look-back', () => {
  const t = Date.parse(at);
  const hourly = n => Array.from({length: n}, (_, i) => ({at: iso(t - i * HOUR), waveFt: 2, wavePeriodS: 10}));
  assert.deepEqual(recentEnergy(t, {forecastHours: hourly(49), site: undefined, observations: []}), {energy: 40, covered: 48});
  // Forecast from the current hour only, plus the latest buoy reading.
  const fresh = recentEnergy(t, {forecastHours: hourly(1), site: undefined, observations: [{observedAt: iso(t - 3 * HOUR), waveFt: 6, wavePeriodS: 12}]});
  assert.deepEqual(fresh, {energy: 432, covered: 2});
  // A three-hour nearshore model sample covers its interval.
  const site = {temporalResolutionMinutes: 180, hours: Array.from({length: 16}, (_, i) => ({at: iso(t - i * 3 * HOUR), waveFt: 1, periodS: 10}))};
  assert.equal(recentEnergy(t, {forecastHours: [], site, observations: []}).covered, 47);
  assert.deepEqual(recentEnergy(t, {forecastHours: [], site: undefined, observations: []}), {energy: null, covered: 0});
  // spearHours wires it through: the forecast alone starts at this hour, so Likely good is withheld.
  const hours = [{at, windKnots: 5, gustKnots: 8, waveFt: 1.8, wavePeriodS: 10, precipPct: 0}];
  const out = spearHours({hours, forecastHours: hours, site: undefined, observations: [], tideEvents: [], chlorophyll: chl(0.8)});
  assert.equal(out[0].clarity.band, 'Fair');
  assert.ok(out[0].clarity.gaps.includes('Clarity estimate: swell before the forecast began is unchecked'));
});

test('verdict: surge and chop decide, clarity weighs in, high tide is a mild bonus', () => {
  const s = band => ({band, energy: 1, heightFt: 1, periodS: 10, basis: 'nearshore'});
  const w = band => ({band, windKnots: 5, gustKnots: 8});
  const k = band => ({band, drivers: [], missing: [], gaps: []});
  assert.equal(spearVerdict(s('Low'), w('Light'), k('Likely good'), false).verdict, 'Calmer');
  assert.equal(spearVerdict(s('Moderate'), w('Light'), k('Fair'), false).verdict, 'Marginal');
  assert.equal(spearVerdict(s('Moderate'), w('Light'), k('Fair'), true).verdict, 'Calmer');
  assert.equal(spearVerdict(s('Low'), w('Choppy'), k('Likely good'), false).verdict, 'Marginal');
  assert.equal(spearVerdict(s('Strong'), w('Light'), k('Fair'), false).verdict, 'Rough');
  assert.equal(spearVerdict(s('Heavy'), w('Light'), k('Likely good'), true).verdict, 'Rough');
  assert.equal(spearVerdict(s('Low'), w('Rough'), k('Likely good'), true).verdict, 'Rough');
  const unknown = spearVerdict(s('Unknown'), w('Light'), k('Likely good'), false);
  assert.deepEqual([unknown.verdict, unknown.score], ['Unknown', null]);
  assert.ok(spearVerdict(s('Low'), w('Light'), k('Unknown'), true).reasons.includes('near high tide'));
  assert.equal(SPEAR.score.highTide < 0 && Math.abs(SPEAR.score.highTide) < SPEAR.score.calmer, true);
});

test('spearHours reads the high tide, recent swell and rain windows; spearDay rolls up daylight', () => {
  const hours = [0, 1, 2].map(i => ({at: iso(Date.parse(at) + i * HOUR), windKnots: 5, gustKnots: 8, waveFt: 1.8, wavePeriodS: 10, precipPct: 70}));
  const out = spearHours({hours, forecastHours: hours, site: undefined, observations: [], tideEvents: [{at: iso(Date.parse(at) - 30 * 60_000), heightFt: 5, type: 'H'}], chlorophyll: chl(0.8)});
  assert.equal(out[0].highTide, true);
  assert.equal(out[2].highTide, false);
  assert.equal(out[0].clarity.band, 'Likely poor');
  assert.match(out[0].clarity.drivers.join(), /runoff likely/);
  const day = spearDay(out, iso(Date.parse(at) - HOUR), iso(Date.parse(at) + 3 * HOUR));
  assert.deepEqual(day.surge, {min: 'Low', max: 'Low'});
  assert.equal(day.basis, 'offshore');
  assert.equal(day.clarity.band, 'Likely poor');
  assert.equal(day.best?.at, out[0].at);
});

test('buildDaily spear: a fresh nearshore model sets surge windows, status, headline and deck', () => {
  const daily = buildDaily(report({site: true}), slo, area, 'spear', date, now);
  assert.ok(daily.spear);
  assert.equal(daily.spear.basis, 'nearshore');
  assert.match(daily.headline, /^Low surge · Clarity estimate: fair$/);
  assert.match(daily.summary, /Surge from the Morro Rock nearshore model: 1\.5 ft at 11 s\./);
  assert.match(daily.summary, /Clarity is an estimate, not a measurement: fair \(chlorophyll 0\.8 mg\/m³: low; moderate swell in the past 2 days\)/);
  assert.match(daily.summary, /Calmest daylight hour:/);
  // 4.5 ft offshore fails the generic 3 ft rule; the low nearshore surge opens windows.
  assert.ok(daily.windows.length > 0);
  assert.equal(daily.windows[0].label, 'Lower surge & wind');
  assert.equal(daily.status, 'Mixed');
  assert.ok(daily.missing.includes('Underwater visibility is estimated, not measured; entry, exit and currents need a local check'));
  assert.ok(!daily.missing.some(m => m.startsWith('Surge judged from offshore swell')));
});

test('buildDaily spear without a nearshore model: offshore surge, generic windows, missing chlorophyll named', () => {
  const daily = buildDaily(report({chl: null}), slo, area, 'spear', date, now);
  assert.equal(daily.spear.basis, 'offshore');
  assert.deepEqual(daily.windows, []);
  assert.equal(daily.status, 'Caution');
  assert.match(daily.headline, /surge · Clarity unknown$/);
  assert.match(daily.summary, /offshore swell, so sheltered coves may be calmer/);
  assert.match(daily.summary, /Clarity unknown: needs satellite chlorophyll\./);
  assert.ok(daily.missing.includes('Clarity estimate needs satellite chlorophyll'));
  assert.ok(daily.missing.includes('Surge judged from offshore swell where no fresh nearshore model covers the hour'));
  // Heavy nearshore surge closes the spear windows.
  assert.deepEqual(buildDaily(report({site: true, nearFt: 5, nearS: 15}), slo, area, 'spear', date, now).windows, []);
  // Boat and shore carry no spear reading and keep their wind and seas headline.
  assert.equal(buildDaily(report({site: true}), slo, area, 'boat', date, now).spear, null);
  assert.match(buildDaily(report({site: true}), slo, area, 'boat', date, now).headline, /kt winds/);
});

test('brief rendering for spear: headline, deck, surge in the swell tile, clarity metric', () => {
  const brief = buildCoastBrief({report: report({site: true}), county: slo, areaId: 'central', profile: 'spear', date, now, at: iso(start + 18 * HOUR)});
  assert.match(brief.headline, /surge · Clarity estimate/);
  assert.match(brief.deck, /estimate, not a measurement/);
  assert.equal(brief.status, 'Mixed');
  assert.ok(brief.spear);
  assert.match(brief.tiles.find(t => t.id === 'swell').detail, /· low surge$/);
  const html = reportPanel(report({site: true}), slo, area, 'spear', date, now);
  assert.match(html, /<span>Clarity<\/span>/);
  assert.match(html, /<span class="data-kind">Estimate<\/span>/);
  assert.match(html, /Lower surge\. Confirm the visibility\./);
  assert.match(html, /Lower surge &amp; wind\. Local checks required\./);
});

const chlorophyllFeed = (samples, status = 'ok') => ({...montereyDaily, sources: {...montereyDaily.sources, chlorophyll: {id: 'chlorophyll', name: 'NOAA VIIRS chlorophyll', kind: 'grid', url: 'https://coastwatch.noaa.gov', checked_at: now.toISOString(), status,
  data: {sample_at: '2026-10-08T12:00:00Z', samples}}}});

test('chlorophyllNear: median of valid nearby cells; gaps and failed grids stay unknown', () => {
  const feed = chlorophyllFeed([
    {latitude: 36.62, longitude: -121.92, chlorophyll: 1}, {latitude: 36.65, longitude: -121.9, chlorophyll: 3},
    {latitude: 36.6, longitude: -121.95, chlorophyll: 2}, {latitude: 36.62, longitude: -121.92, chlorophyll: null},
    {latitude: 37.2, longitude: -122.4, chlorophyll: 20},
  ]);
  assert.deepEqual(chlorophyllNear(feed, 36.62, -121.9), {mgM3: 2, sampleAt: '2026-10-08T12:00:00Z', cells: 3, label: 'NOAA VIIRS chlorophyll', url: 'https://coastwatch.noaa.gov'});
  assert.equal(chlorophyllNear(feed, 34, -120), null);
  assert.equal(chlorophyllNear(chlorophyllFeed([{latitude: 36.62, longitude: -121.9, chlorophyll: 1}], 'failed'), 36.62, -121.9), null);
  assert.equal(chlorophyllNear(montereyDaily, 36.62, -121.9), null);
  const place = {id: 'monterey', name: 'Monterey', lat: 36.62, lon: -121.9, timezone: 'America/Los_Angeles', port: 'Monterey'};
  assert.equal(regionalReport(feed, montereyForecast, place).report.chlorophyll.mgM3, 2);
  const brief = buildRegionalBrief({daily: feed, forecast: montereyForecast, place, profile: 'spear', date: '2026-10-08', now});
  assert.ok(brief.spear);
  assert.notEqual(brief.spear.clarity.band, 'Unknown');
});

// RF1915-5: the look-back walks its 48 fixed slots, never the declared sample spacing.
const SPEAR_URL = new URL('../packages/coast/src/spear.ts', import.meta.url).href;
/** Run `body` (a function body over `{recentEnergy, spearHours, args}`) in a child process; the parent's timeout, not a test-callback timeout, enforces liveness. */
function inChild(body, args, timeoutMs = 20_000) {
  const code = `const m = await import(${JSON.stringify(SPEAR_URL)}); const args = JSON.parse(process.argv[1]); const out = await (async ({recentEnergy, spearHours, args}) => {${body}})({...m, args}); console.log(JSON.stringify(out));`;
  const r = spawnSync(process.execPath, ['--input-type=module', '-e', code, JSON.stringify(args)], {encoding: 'utf8', timeout: timeoutMs});
  assert.ok(!r.error, `child did not return within ${timeoutMs} ms (${r.error?.code}): recentEnergy is not bounded`);
  assert.equal(r.status, 0, r.stderr);
  return JSON.parse(r.stdout.trim().split('\n').pop());
}
const SPAN_AT = Date.parse(at);
const oneSample = minutes => ({forecastHours: [], site: {temporalResolutionMinutes: minutes, hours: [{at, waveFt: 2, periodS: 10}]}, observations: []});
const CHILD_SAMPLE = 'const t = Date.parse(args.at); return args.minutes.map(s => recentEnergy(t, {forecastHours: [], site: {temporalResolutionMinutes: s === "Infinity" ? Infinity : s === "-Infinity" ? -Infinity : s === "NaN" ? NaN : Number(s), hours: [{at: args.at, waveFt: 2, periodS: 10}]}, observations: []}));';

test('recentEnergy oversized finite spacing returns within bounded child lifetime', () => {
  const [out] = inChild(CHILD_SAMPLE, {at, minutes: ['1e20']});
  assert.deepEqual(out, {energy: 40, covered: 48});
});

test('recentEnergy nonfinite spacing cannot stall slot enumeration', () => {
  const [inf, nan, negInf] = inChild(CHILD_SAMPLE, {at, minutes: ['Infinity', 'NaN', '-Infinity']});
  assert.deepEqual(inf, {energy: 40, covered: 48});
  // NaN credits no slot but the energy still counts; -Infinity keeps the one-slot minimum span.
  assert.deepEqual(nan, {energy: 40, covered: 0});
  assert.deepEqual(negInf, {energy: 40, covered: 1});
  const input = oneSample(Infinity), hoursBefore = structuredClone(input.site.hours);
  recentEnergy(SPAN_AT, input);
  assert.equal(input.site.temporalResolutionMinutes, Infinity);
  assert.ok(util.isDeepStrictEqual(input.site.hours, hoursBefore), 'inputs are not modified');
});

/** The previous loop, kept as an oracle for spans that terminate. */
function legacyCovered(offsets, spanHours) {
  const hours = new Set(), half = Math.floor(spanHours / 2);
  for (const k of offsets) for (let i = k - half; i <= k + half; i++) if (i >= 0 && i < 48) hours.add(i);
  return hours.size;
}

test('recentEnergy bounded slots preserve legacy intervals', () => {
  for (const span of [1, 2, 3, 4, 24, 48]) {
    for (const k of [0, 1, 2, 23, 24, 25, 46, 47, 48]) {
      const sample = {at: iso(SPAN_AT - k * HOUR), waveFt: 2, periodS: 10};
      const got = recentEnergy(SPAN_AT, {forecastHours: [], site: {temporalResolutionMinutes: span * 60, hours: [sample]}, observations: []});
      assert.deepEqual(got, {energy: 40, covered: legacyCovered([k], span)}, `span ${span} h, offset ${k} h`);
    }
  }
  // The existing 16-sample three-hour and current-hour-only expectations hold.
  const site = {temporalResolutionMinutes: 180, hours: Array.from({length: 16}, (_, i) => ({at: iso(SPAN_AT - i * 3 * HOUR), waveFt: 1, periodS: 10}))};
  assert.equal(recentEnergy(SPAN_AT, {forecastHours: [], site, observations: []}).covered, 47);
  assert.equal(recentEnergy(SPAN_AT, {forecastHours: [{at, waveFt: 2, wavePeriodS: 10}], site: undefined, observations: []}).covered, 1);
});

test('recentEnergy admission and overlap remain unchanged', () => {
  const none = {forecastHours: [], site: undefined, observations: []};
  const rejected = {
    forecastHours: [{at: 'not a time', waveFt: 9, wavePeriodS: 10}, {at: iso(SPAN_AT + HOUR), waveFt: 9, wavePeriodS: 10}, {at: iso(SPAN_AT - 49 * HOUR), waveFt: 9, wavePeriodS: 10}, {at, waveFt: null, wavePeriodS: null}],
    site: undefined, observations: [{observedAt: 'bad', waveFt: 9, wavePeriodS: 10}],
  };
  assert.deepEqual(recentEnergy(SPAN_AT, rejected), {energy: null, covered: 0});
  assert.deepEqual(recentEnergy(SPAN_AT, none), {energy: null, covered: 0});
  // Forecast, site and buoy samples of the same hour deduplicate coverage and keep the largest energy.
  const overlap = recentEnergy(SPAN_AT, {forecastHours: [{at, waveFt: 2, wavePeriodS: 10}], site: {temporalResolutionMinutes: 60, hours: [{at, waveFt: 3, periodS: 10}]}, observations: [{observedAt: at, waveFt: 1, wavePeriodS: 10}]});
  assert.deepEqual(overlap, {energy: 90, covered: 1});
  // Null or absent spacing is three hours, like 180 minutes.
  const sample = [{at: iso(SPAN_AT - 10 * HOUR), waveFt: 2, periodS: 10}];
  const spans = [null, undefined, 180].map(m => recentEnergy(SPAN_AT, {forecastHours: [], site: {temporalResolutionMinutes: m, hours: sample}, observations: []}));
  assert.deepEqual(spans[0], {energy: 40, covered: 3});
  assert.ok(util.isDeepStrictEqual(spans[0], spans[1]) && util.isDeepStrictEqual(spans[1], spans[2]), 'null, absent and 180 min agree');
});

test('spearHours oversized spacing completes without changing ordinary readings', () => {
  const hour = {at, windKnots: 5, gustKnots: 8, waveFt: 1.8, wavePeriodS: 10, precipPct: 0};
  const child = inChild('return spearHours({hours: [args.hour], forecastHours: [args.hour], site: {temporalResolutionMinutes: 1e20, hours: [{at: args.hour.at, waveFt: 2, periodS: 10}]}, observations: [], tideEvents: [], chlorophyll: args.chl})[0].clarity;', {hour, chl: chl(0.8)});
  assert.ok(!child.gaps.includes('Clarity estimate: swell before the forecast began is unchecked'), 'a 48-hour cover clears the look-back gap');
  // Ordinary readings: a missing site, and the 35/36 covered-hour clarity gate.
  const SWELL_GAP = 'Clarity estimate: swell before the forecast began is unchecked';
  const reading = n => spearHours({hours: [hour], forecastHours: Array.from({length: n}, (_, i) => ({...hour, at: iso(SPAN_AT - i * HOUR)})), site: undefined, observations: [], tideEvents: [], chlorophyll: chl(0.8)})[0].clarity;
  assert.ok(reading(35).gaps.includes(SWELL_GAP));
  assert.equal(reading(35).band, 'Fair');
  assert.ok(!reading(36).gaps.includes(SWELL_GAP));
  assert.equal(reading(36).band, 'Likely good');
  assert.ok(reading(1).gaps.includes(SWELL_GAP));
});

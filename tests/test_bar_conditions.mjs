// Issue #542: the harbour bar / entrance check for the boat brief
// (packages/coast/src/bar-conditions.ts) and its place in the daily brief
// (daily.ts buildDaily, presentation.ts, web/brief/model.ts).
import test from 'node:test';
import assert from 'node:assert/strict';
import fixture from './fixtures/coast/skippercast-report.json' with {type: 'json'};
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import montereyForecast from './fixtures/brief/monterey-forecast.json' with {type: 'json'};

const {BAR, BAR_CHECK, entranceFor, barTide, barSwell, windAgainstEbb, barBand, barHours, barDay, crossingHours} = await import('../packages/coast/src/bar-conditions.ts');
const {buildDaily} = await import('../packages/coast/src/daily.ts');
const {reportPanel} = await import('../packages/coast/src/presentation.ts');
const {slo} = await import('../packages/coast/src/counties.ts');
const {buildCoastBrief, buildRegionalBrief} = await import('../web/brief/model.ts');

const HOUR = 3_600_000;
const now = new Date(Date.parse(fixture.generatedAt) + 10 * 60_000);
const date = '2026-10-09';
const area = slo.areas.find(a => a.id === 'central');
const start = Date.parse(fixture.forecasts[1].hours[0].at);
const iso = ms => new Date(ms).toISOString();
const morro = entranceFor('slo', 'central');
// The fixture's tide events on 9 October (UTC): high 16:12, low 22:40, so mid-ebb runs 17:49 to 21:03 (10:49 AM to 2:03 PM PDT).
const events = fixture.tideEvents;
const at = text => Date.parse(`2026-10-09T${text}:00.000Z`);

/** The fixture report with light wind, small offshore seas, an optional nearshore site and per-hour overrides. */
function report({site = false, wave = 3, period = 10, swellPeriod = 10, nearFt = 2, nearS = 10, wind = 5, gust = 8, dir = 300, hour = () => ({})} = {}) {
  const hours = Array.from({length: 48}, (_, i) => {
    const base = {at: iso(start + i * HOUR), windKnots: wind, gustKnots: gust, windDirectionDeg: dir, waveFt: wave, wavePeriodS: period, swellFt: wave - 0.5, swellPeriodS: swellPeriod, airTempF: 60, precipPct: 0};
    return {...base, ...hour(Date.parse(base.at))};
  });
  const out = structuredClone(fixture);
  out.alerts = [];
  out.forecasts = out.forecasts.map(f => f.id === 'central' ? {...f, hours} : f);
  if (site) out.nearshore = [{id: 'mop-test', name: 'Morro Bay entrance', areaId: 'central', lat: 35.37, lon: -120.87, sourceId: 'cdip', issuedAt: iso(now.getTime() - 2 * HOUR), fetchedAt: iso(now.getTime() - 20 * 60_000),
    hours: Array.from({length: 16}, (_, i) => ({at: iso(start - 3 * HOUR + i * 3 * HOUR), waveFt: nearFt, periodS: nearS, directionDeg: 280, qualityFlag: null, secondaryFlag: null})),
    url: 'https://cdip.ucsd.edu', kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 180, waterDepthM: 15, depthDatum: 'MSL', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: iso(start + 42 * HOUR)}];
  return out;
}

test('entrances: only the four regulated bars of 33 CFR 165.1196', () => {
  assert.deepEqual(morro, {name: 'Morro Bay entrance', seawardDeg: 260});
  assert.equal(entranceFor('morro-bay', 'morro-bay').name, 'Morro Bay entrance');
  assert.equal(entranceFor('humboldt-bay-cape-mendocino', 'humboldt-bay-cape-mendocino').name, 'Humboldt Bay entrance');
  assert.equal(entranceFor('fort-bragg-point-arena', 'fort-bragg-point-arena').name, 'Noyo River entrance');
  assert.equal(entranceFor('crescent-city', 'crescent-city').name, 'Crescent City Harbor entrance');
  // Entrances with no bearing stay null: wind against the ebb is not judged there.
  assert.equal(entranceFor('crescent-city', 'crescent-city').seawardDeg, null);
  // Cambria, Avila, Monterey, unknown and inherited keys get no bar check.
  assert.deepEqual([entranceFor('slo', 'north'), entranceFor('slo', 'south'), entranceFor('monterey-point-sur', 'monterey-point-sur'), entranceFor(undefined, 'central'),
    entranceFor('slo', 'constructor'), entranceFor('constructor', 'central'), entranceFor('slo', 'toString')], [null, null, null, null, null, null, null]);
});

test('tide: ebb from high to low, mid-ebb in the middle half, flood, and unknown without events either side', () => {
  assert.deepEqual(barTide(at('19:00'), events), {stage: 'ebb', midEbb: true, fraction: 0.43});
  const early = barTide(at('17:00'), events);
  assert.deepEqual([early.stage, early.midEbb], ['ebb', false]);
  assert.equal(barTide(at('22:00'), events).midEbb, false, 'late ebb');
  assert.deepEqual([barTide(at('23:00'), events).stage, barTide(at('23:00'), events).midEbb], ['flood', false]);
  assert.deepEqual(barTide(at('19:00'), []), {stage: null, midEbb: false, fraction: null});
  assert.equal(barTide(at('19:00'), events.filter(e => Date.parse(e.at) <= at('19:00'))).stage, null, 'no event after');
  assert.deepEqual([BAR.midEbb.from, BAR.midEbb.to], [0.25, 0.75]);
});

test('swell: nearshore wins, offshore seas are an estimate, long period from any component with enough height', () => {
  const hour = {at: iso(at('19:00')), windKnots: 5, gustKnots: 8, waveFt: 5, wavePeriodS: 9, swellFt: 3, swellPeriodS: 15};
  const near = barSwell(hour, {at: hour.at, waveFt: 3, periodS: 11});
  assert.deepEqual(near, {heightFt: 3, periodS: 11, basis: 'nearshore', longPeriodS: 15});
  assert.deepEqual(barSwell(hour), {heightFt: 5, periodS: 9, basis: 'offshore', longPeriodS: 15});
  assert.equal(barSwell({...hour, swellFt: 1.5}).longPeriodS, 9, 'a 1.5 ft long-period partition is below BAR.longPeriod.minFt');
  assert.equal(barSwell({...hour, waveFt: null}).basis, null);
  assert.equal(barSwell(undefined).heightFt, null);
});

test('wind against the ebb: an ebb, a bearing, enough wind, blowing in', () => {
  const ebb = barTide(at('19:00'), events), flood = barTide(at('23:00'), events);
  assert.equal(windAgainstEbb({windKnots: 12, windDirectionDeg: 280}, ebb, 260), true);
  assert.equal(windAgainstEbb({windKnots: 12, windDirectionDeg: 280}, flood, 260), false, 'flood');
  assert.equal(windAgainstEbb({windKnots: 8, windDirectionDeg: 280}, ebb, 260), false, 'below 10 kt');
  assert.equal(windAgainstEbb({windKnots: 12, windDirectionDeg: 80}, ebb, 260), false, 'offshore wind runs with the ebb');
  assert.equal(windAgainstEbb({windKnots: 12, windDirectionDeg: null}, ebb, 260), false, 'no direction');
  assert.equal(windAgainstEbb({windKnots: 12, windDirectionDeg: 280}, ebb, null), false, 'no bearing');
});

test('band: each driver, and never better than No bar flag', () => {
  const mid = barTide(at('19:00'), events), early = barTide(at('17:00'), events), flood = barTide(at('23:00'), events), none = barTide(at('19:00'), []);
  const near = (heightFt, periodS = 10, longPeriodS = null) => ({heightFt, periodS, basis: 'nearshore', longPeriodS});
  const off = heightFt => ({heightFt, periodS: 10, basis: 'offshore', longPeriodS: null});
  const band = (tide, swell, wind = false) => barBand(tide, swell, wind).band;
  // Height alone.
  assert.equal(band(flood, near(1.5)), 'No bar flag');
  assert.equal(band(flood, near(4)), 'Caution');
  assert.equal(band(flood, near(8)), 'Hazardous');
  // Ebb steepening: a caution from 2 ft on any ebb; mid-ebb against the caution height is hazardous.
  assert.equal(band(early, near(2)), 'Caution');
  assert.equal(band(early, near(4)), 'Caution');
  assert.equal(band(mid, near(4)), 'Hazardous');
  assert.equal(band(mid, near(1.5)), 'No bar flag');
  // Long-period swell: a caution on any tide; on an ebb with the caution height, hazardous.
  assert.equal(band(flood, near(2, 15, 15)), 'Caution');
  assert.equal(band(early, near(4, 15, 15)), 'Hazardous');
  assert.equal(band(flood, near(4, 15, 15)), 'Caution');
  // Wind blowing in against the ebb.
  assert.equal(band(early, near(1.5), true), 'Caution');
  // Offshore estimate: its own, higher scale, labelled in the reasons.
  assert.equal(band(flood, off(5)), 'No bar flag');
  assert.equal(band(flood, off(6)), 'Caution');
  assert.equal(band(mid, off(6)), 'Hazardous');
  assert.equal(band(flood, off(10)), 'Hazardous');
  assert.match(barBand(flood, off(5)).reasons[0], /^5 ft at 10 s swell \(offshore estimate\)$/);
  // Missing inputs: no swell is Unknown; no tide phase with small swell is Unknown (the ebb cannot be ruled out); big swell still reads.
  assert.deepEqual(barBand(mid, {heightFt: null, periodS: null, basis: null, longPeriodS: null}), {band: 'Unknown', reasons: ['Swell unknown']});
  assert.deepEqual(barBand(none, {heightFt: null, periodS: null, basis: null, longPeriodS: null}).reasons, ['Swell unknown', 'tide phase unknown']);
  assert.equal(band(none, near(1.5)), 'Unknown');
  assert.equal(band(none, near(2)), 'Caution');
  assert.equal(band(none, near(8)), 'Hazardous');
  assert.deepEqual(barBand(mid, near(4, 15, 15), true).reasons, ['4 ft at 15 s swell', 'long-period swell (15 s)', 'mid-ebb tide', 'wind blowing in against the ebb']);
});

test('day roll-up and crossing hours', () => {
  const hours = barHours({hours: [17, 18, 19, 20, 21, 22, 23].map(h => ({at: iso(at(`${h}:00`)), windKnots: 5, gustKnots: 8, waveFt: 4, wavePeriodS: 10})), site: undefined, entrance: morro, tideEvents: events});
  const day = barDay(morro, hours);
  // 4 ft offshore: caution on the ebb (17Z, 22Z), hazardous nowhere (offshore caution is 6 ft), flood at 23Z below 6 ft has no bar flag.
  assert.deepEqual(hours.map(h => h.band), ['Caution', 'Caution', 'Caution', 'Caution', 'Caution', 'Caution', 'No bar flag']);
  assert.equal(day.worst, 'Caution');
  assert.equal(day.basis, 'offshore');
  assert.equal(day.tideUnknown, false);
  assert.deepEqual(crossingHours(day, iso(at('18:00')), iso(at('22:00'))).map(h => h.at), [iso(at('18:00')), iso(at('21:00')), iso(at('22:00'))]);
  assert.equal(barDay(morro, []).worst, null);
});

test('buildDaily boat at Morro Bay: a hazardous bar caps status, names the hours, and drops windows that cross then', () => {
  // Nearshore 4 ft: hazardous at mid-ebb (11 AM to 3 PM PDT), caution otherwise. Offshore 3 ft keeps the generic boat windows open.
  const daily = buildDaily(report({site: true, nearFt: 4}), slo, area, 'boat', date, now);
  assert.ok(daily.bar);
  assert.equal(daily.bar.basis, 'nearshore');
  // The day's three mid-ebbs: 07:00 and 08:00 UTC (just after midnight PDT), 18:00 to 21:00 UTC, and 06:00 UTC on the 10th (11 PM PDT).
  assert.deepEqual(daily.bar.hazardous.map(h => h.at), [...['07', '08', 18, 19, 20, 21].map(h => iso(at(`${h}:00`))), '2026-10-10T06:00:00.000Z']);
  assert.equal(daily.status, 'Caution');
  assert.match(daily.headline, /^Bar hazardous 12 AM–2 AM, 11 AM–3 PM and 11 PM–12 AM \(estimate\) · 5 kt winds · 3 ft offshore seas$/);
  assert.match(daily.summary, /Morro Bay entrance bar \(estimate\): hazardous .*\(4 ft at 10 s swell, mid-ebb tide\)\. Windows that leave or return then are not suggested\./);
  assert.match(daily.summary, /Ebb timing is from Port San Luis tide predictions/);
  assert.ok(daily.summary.includes(BAR_CHECK));
  assert.ok(!/\bsafe\b/.test(daily.summary), 'never calls the bar safe');
  // The daylight window leaves and returns in caution hours (early ebb, flood), so it stays, with the bar named in its reasons.
  assert.ok(daily.windows.length > 0);
  for (const window of daily.windows) {
    assert.ok(!crossingHours(daily.bar, window.start, window.end).some(h => h.band === 'Hazardous'), window.start);
    assert.ok(window.reasons.some(r => /bar caution or unknown at departure or return/.test(r)));
  }
  assert.ok(!daily.missing.some(m => /Bar swell is an offshore estimate/.test(m)));
  // A window that would start at 11 AM (strong wind before) is dropped when the bar is hazardous then, kept when it is only a caution.
  const calmFrom = t => t >= at('18:00') ? {} : {windKnots: 18, gustKnots: 24};
  const blocked = buildDaily(report({site: true, nearFt: 4, hour: calmFrom}), slo, area, 'boat', date, now);
  assert.ok(!blocked.windows.some(w => Date.parse(w.start) === at('18:00')));
  const open = buildDaily(report({site: true, nearFt: 2, hour: calmFrom}), slo, area, 'boat', date, now);
  assert.ok(open.windows.some(w => Date.parse(w.start) === at('18:00')));
  assert.equal(open.bar.hazardous.length, 0);
  assert.equal(open.status, 'Mixed');
  assert.match(open.summary, /Morro Bay entrance bar \(estimate\): caution /);
  // The coast panel leads with the bar.
  assert.match(reportPanel(report({site: true, nearFt: 4}), slo, area, 'boat', date, now), /The bar sets the terms\. Check the bar status\./);
});

test('buildDaily boat: wind against the ebb, offshore estimate and missing tide listed, no bar flag never safe', () => {
  // Offshore 2 ft with a 12 kt westerly: the ebb hours read caution for wind blowing in.
  const windy = buildDaily(report({wave: 2, wind: 12, gust: 14, dir: 280}), slo, area, 'boat', date, now);
  assert.equal(windy.bar.basis, 'offshore');
  assert.ok(windy.bar.hours.filter(h => h.tide.stage === 'ebb').every(h => h.windAgainst && h.band === 'Caution'));
  assert.ok(windy.missing.includes('Bar swell is an offshore estimate where no fresh nearshore model covers the hour'));
  // Offshore 2 ft, light wind: every hour reads No bar flag, and the deck still says that is not a safe bar.
  const calm = buildDaily(report({wave: 2}), slo, area, 'boat', date, now);
  assert.equal(calm.bar.worst, 'No bar flag');
  assert.match(calm.summary, /no hour reads hazardous or caution on this rough check, which does not mean the bar is safe\./);
  assert.ok(calm.summary.includes(BAR_CHECK));
  assert.ok(!calm.headline.startsWith('Bar'));
  // No tide events: listed, and small swell reads Unknown rather than no bar flag.
  const noTide = report({wave: 2});
  noTide.tideEvents = [];
  const blind = buildDaily(noTide, slo, area, 'boat', date, now);
  assert.ok(blind.missing.includes('Tide phase unknown: the bar check cannot time the ebb'));
  assert.ok(blind.bar.hours.every(h => h.band === 'Unknown'));
  assert.match(blind.summary, /Morro Bay entrance bar: not judged \(2 ft at 10 s swell \(offshore estimate\), tide phase unknown\)\./);
  // Cambria, Avila and the other profiles carry no bar reading.
  assert.equal(buildDaily(report(), slo, slo.areas.find(a => a.id === 'north'), 'boat', date, now).bar, null);
  assert.equal(buildDaily(report(), slo, area, 'shore', date, now).bar, null);
  assert.equal(buildDaily(report(), slo, area, 'spear', date, now).bar, null);
});

test('brief rendering for boat: bar band in the tide tile, carried on the brief; regional places without a bar get none', () => {
  const brief = buildCoastBrief({report: report({site: true, nearFt: 4}), county: slo, areaId: 'central', profile: 'boat', date, now, at: iso(at('19:00'))});
  assert.ok(brief.bar);
  assert.match(brief.headline, /^Bar hazardous/);
  assert.match(brief.tiles.find(t => t.id === 'tide').detail, /mid-ebb · bar hazardous \(estimate\) · Port San Luis/);
  assert.match(brief.deck, /check the Coast Guard bar status \(VHF 16 or 22A\) or the harbor patrol/);
  const flood = buildCoastBrief({report: report({site: true, nearFt: 1}), county: slo, areaId: 'central', profile: 'boat', date, now, at: iso(at('23:00'))});
  assert.match(flood.tiles.find(t => t.id === 'tide').detail, /flood · no bar flag \(estimate\)/);
  const place = {id: 'monterey-point-sur', name: 'Monterey', lat: 36.62, lon: -121.9, timezone: 'America/Los_Angeles', port: 'Monterey'};
  const monterey = buildRegionalBrief({daily: montereyDaily, forecast: montereyForecast, place, profile: 'boat', date: '2026-10-08', now});
  assert.equal(monterey.bar, null);
  assert.ok(!/bar (hazardous|caution|likely)/.test(monterey.tiles.find(t => t.id === 'tide').detail));
});

test('regional brief at a regulated bar reads the regional feeds as they are', () => {
  // The same Monterey feeds keyed as Morro Bay's region: the bar check runs on the regional tide events and offshore forecast.
  const daily = {...montereyDaily, region_id: 'morro-bay'};
  const place = {id: 'morro-bay', name: 'Morro Bay & Avila', lat: 35.37, lon: -120.86, timezone: 'America/Los_Angeles', port: 'Morro Bay'};
  const brief = buildRegionalBrief({daily, forecast: montereyForecast, place, profile: 'boat', date: '2026-10-08', now});
  assert.ok(brief.bar);
  assert.equal(brief.bar.entrance.name, 'Morro Bay entrance');
  if (brief.bar.hours.length) {
    assert.ok(brief.bar.hours.every(h => h.swell.basis !== 'nearshore'));
    assert.ok(brief.deck.includes(BAR_CHECK));
  }
});

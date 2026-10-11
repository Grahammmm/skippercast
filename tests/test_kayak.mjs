// Issue #542: the kayak reading (packages/coast/src/kayak.ts) and its place in
// the daily brief (daily.ts buildDaily, web/brief/model.ts).
import test from 'node:test';
import assert from 'node:assert/strict';
import fixture from './fixtures/coast/skippercast-report.json' with {type: 'json'};
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import montereyForecast from './fixtures/brief/monterey-forecast.json' with {type: 'json'};

const {KAYAK, kayakWind, kayakSeas, launchCaution, fogAt, kayakVerdict, kayakHours, kayakDay, kayakWindowOk, kayakWindText} = await import('../packages/coast/src/kayak.ts');
const {surf, seaward} = await import('../packages/coast/src/shore-conditions.ts');
const {buildDaily} = await import('../packages/coast/src/daily.ts');
const {slo} = await import('../packages/coast/src/counties.ts');
const {buildCoastBrief, buildRegionalBrief} = await import('../web/brief/model.ts');

const HOUR = 3_600_000;
const now = new Date(Date.parse(fixture.generatedAt) + 10 * 60_000);
const date = '2026-10-09';
const area = slo.areas.find(a => a.id === 'central');
const start = Date.parse(fixture.forecasts[1].hours[0].at);
const iso = ms => new Date(ms).toISOString();
// Morro Bay faces 260°: wind from 80° is offshore, from 0° cross-shore, from 260° onshore.
const sea = seaward('slo', 'central');

/** The fixture report with a north (cross-shore) breeze, small seas and an optional nearshore site. */
function report({site = false, wave = 1.5, period = 10, nearFt = 2, nearS = 10, wind = 5, gust = 8, dir = 0, alerts = []} = {}) {
  const hours = Array.from({length: 48}, (_, i) => ({at: iso(start + i * HOUR), windKnots: wind, gustKnots: gust, windDirectionDeg: dir, waveFt: wave, wavePeriodS: period, swellFt: Math.max(0, wave - 0.5), swellPeriodS: period, airTempF: 60, precipPct: 0}));
  const out = structuredClone(fixture);
  out.alerts = alerts;
  out.forecasts = out.forecasts.map(f => f.id === 'central' ? {...f, hours} : f);
  if (site) out.nearshore = [{id: 'mop-test', name: 'Morro Strand', areaId: 'central', lat: 35.4, lon: -120.87, sourceId: 'cdip', issuedAt: iso(now.getTime() - 2 * HOUR), fetchedAt: iso(now.getTime() - 20 * 60_000),
    hours: Array.from({length: 16}, (_, i) => ({at: iso(start - 3 * HOUR + i * 3 * HOUR), waveFt: nearFt, periodS: nearS, directionDeg: 280, qualityFlag: null, secondaryFlag: null})),
    url: 'https://cdip.ucsd.edu', kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 180, waterDepthM: 15, depthDatum: 'MSL', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: iso(start + 42 * HOUR)}];
  return out;
}

test('wind: bands stricter than boat, Calmer limit 10 kt and 15 kt gusts, offshore from the vetted bearing', () => {
  assert.equal(sea, 260);
  assert.deepEqual(KAYAK.wind.moderate, {wind: 10, gust: 15});
  const band = (windKnots, gustKnots) => kayakWind({windKnots, gustKnots, windDirectionDeg: 0}, sea).band;
  assert.deepEqual([band(6, 10), band(10, 15), band(10, 16), band(14, 20), band(15, 20)], ['Light', 'Moderate', 'Fresh', 'Fresh', 'Strong']);
  assert.equal(kayakWind({windKnots: null, gustKnots: 5}, sea).band, 'Unknown');
  assert.equal(kayakWind({windKnots: 5, gustKnots: 8, windDirectionDeg: 80}, sea).side, 'offshore');
  assert.equal(kayakWind({windKnots: 5, gustKnots: 8, windDirectionDeg: 260}, sea).side, 'onshore');
  assert.equal(kayakWind({windKnots: 5, gustKnots: 8, windDirectionDeg: 0}, sea).side, 'cross-shore');
  assert.equal(kayakWind({windKnots: 5, gustKnots: 8, windDirectionDeg: 80}, null).side, null, 'no bearing: speed only');
  assert.equal(kayakWindText({min: 'Light', max: 'Fresh'}), 'Light to fresh');
});

test('seas, chop, launch surf and fog alerts', () => {
  assert.deepEqual([1.5, 2.5, 4, 5].map(waveFt => kayakSeas({waveFt, wavePeriodS: 10}).band), ['Small', 'Moderate', 'Large', 'Heavy']);
  assert.equal(kayakSeas({waveFt: 2, wavePeriodS: 7}).chop, true);
  assert.equal(kayakSeas({waveFt: 2, wavePeriodS: 9}).chop, false, 'longer period is not chop');
  assert.equal(kayakSeas({waveFt: 1.5, wavePeriodS: 5}).chop, false, 'too small to count');
  assert.equal(kayakSeas({waveFt: null, wavePeriodS: 5}).band, 'Unknown');
  const hour = {at: iso(start), windKnots: 5, gustKnots: 8, waveFt: 4, wavePeriodS: 12};
  assert.equal(launchCaution(surf(hour)), true, '4 ft offshore estimate reaches the 3 ft line');
  assert.equal(launchCaution(surf({...hour, waveFt: 2})), false);
  assert.equal(launchCaution(surf(hour, {at: hour.at, waveFt: 2, periodS: 10})), false, 'the nearshore model wins');
  assert.equal(launchCaution(surf(hour, {at: hour.at, waveFt: 3, periodS: 10})), true);
  const fog = {event: 'Dense Fog Advisory', effective: iso(start), expires: iso(start + 3 * HOUR)};
  assert.equal(fogAt(start + HOUR, [fog]), true);
  assert.equal(fogAt(start + 4 * HOUR, [fog]), false, 'expired');
  assert.equal(fogAt(start + HOUR, [{...fog, event: 'Small Craft Advisory'}]), false, 'not a fog alert');
});

test('verdict: wind leads, offshore wind penalised and cautioned, fog and darkness cap at Rough, never implies safety', () => {
  const calm = kayakSeas({waveFt: 1.5, wavePeriodS: 10}), noSurf = surf({waveFt: 1.5, wavePeriodS: 10});
  const w = (windKnots, gustKnots, dir = 0) => kayakWind({windKnots, gustKnots, windDirectionDeg: dir}, sea);
  assert.equal(kayakVerdict(w(5, 8), calm, noSurf, true, false).verdict, 'Calmer');
  assert.equal(kayakVerdict(w(10, 15), calm, noSurf, true, false).verdict, 'Calmer');
  assert.equal(kayakVerdict(w(12, 18), calm, noSurf, true, false).verdict, 'Marginal');
  assert.equal(kayakVerdict(w(16, 22), calm, noSurf, true, false).verdict, 'Rough');
  // Offshore: a Moderate offshore breeze is Rough, and even a light one carries a caution.
  const off = kayakVerdict(w(10, 15, 80), calm, noSurf, true, false);
  assert.equal(off.verdict, 'Rough');
  assert.match(off.cautions[0], /^Offshore wind: it carries a kayak away from shore/);
  const lightOff = kayakVerdict(w(5, 8, 80), calm, noSurf, true, false);
  assert.equal(lightOff.verdict, 'Calmer');
  assert.ok(lightOff.cautions.some(c => c.startsWith('Offshore wind')));
  // Seas and chop: 2.5 ft at 7 s with light wind scores Moderate seas plus chop.
  const chop = kayakVerdict(w(5, 8), kayakSeas({waveFt: 2.5, wavePeriodS: 7}), surf({waveFt: 2.5, wavePeriodS: 7}), true, false);
  assert.equal(chop.verdict, 'Marginal');
  assert.ok(chop.reasons.includes('short-period chop'));
  // Launch surf caution.
  const launch = kayakVerdict(w(5, 8), calm, surf({waveFt: 1.5, wavePeriodS: 10}, {waveFt: 3.5, periodS: 14}), true, false);
  assert.ok(launch.cautions.some(c => /Surf at the launch \(3\.5 ft\)/.test(c)));
  // Fog and darkness cap.
  assert.equal(kayakVerdict(w(5, 8), calm, noSurf, true, true).verdict, 'Rough');
  assert.equal(kayakVerdict(w(5, 8), calm, noSurf, false, false).verdict, 'Rough');
  assert.equal(kayakVerdict(w(5, 8), calm, noSurf, null, false).verdict, 'Calmer', 'unknown daylight is listed, not capped');
  assert.equal(kayakVerdict(kayakWind({windKnots: null}, sea), calm, noSurf, true, false).verdict, 'Unknown');
  const all = [off, lightOff, chop, launch].flatMap(v => [...v.reasons, ...v.cautions]).join(' ');
  assert.doesNotMatch(all, /\bsafe\b|guarantee|go out|all clear/i, 'reasons never imply safety');
});

test('kayakHours and kayakDay: daylight scope, best hour, offshore and launch lists, windows', () => {
  const hours = Array.from({length: 24}, (_, i) => ({at: iso(start + i * HOUR), windKnots: i < 12 ? 5 : 16, gustKnots: i < 12 ? 8 : 22, windDirectionDeg: i === 3 ? 80 : 0, waveFt: 1.5, wavePeriodS: 10}));
  const sunrise = iso(start + 2 * HOUR), sunset = iso(start + 20 * HOUR);
  const out = kayakHours({hours, site: undefined, seawardDeg: sea, alerts: [], sunrise, sunset});
  assert.equal(out[0].daylight, false);
  assert.equal(out[0].verdict, 'Rough');
  const day = kayakDay(out, sea);
  assert.equal(day.best.at, out[2].at, 'earliest calmest daylight hour');
  assert.deepEqual(day.offshore.map(h => h.at), [out[3].at]);
  assert.deepEqual(day.wind, {min: 'Light', max: 'Strong'});
  assert.equal(kayakWindowOk(out[2]), true);
  assert.equal(kayakWindowOk(out[3]), false, 'offshore wind');
  assert.equal(kayakWindowOk(out[14]), false, 'strong wind');
  assert.equal(kayakWindowOk(undefined), undefined);
  const noSun = kayakDay(kayakHours({hours, site: undefined, seawardDeg: null, alerts: [], sunrise: null, sunset: null}), null);
  assert.equal(noSun.daylightUnknown, true);
  assert.equal(noSun.bearingKnown, false);
});

test('buildDaily kayak: wind headline, Mixed status, kayak windows and missing inputs', () => {
  const daily = buildDaily(report(), slo, area, 'kayak', date, now);
  assert.ok(daily.kayak);
  assert.equal(daily.shore, null);
  assert.equal(daily.spear, null);
  assert.match(daily.headline, /^Light wind · calmer at \d{1,2} (AM|PM)$/);
  assert.equal(daily.status, 'Mixed');
  assert.ok(daily.windows.length > 0);
  assert.equal(daily.windows[0].label, 'Lower wind & seas');
  assert.match(daily.summary, /Calmest daylight hour:/);
  assert.match(daily.summary, /leave your plan with someone ashore\.$/);
  assert.ok(daily.missing.includes('Launch and landing surf, drift and the paddle back need a local check'));
  assert.ok(daily.missing.includes('Launch surf is an offshore estimate where no fresh nearshore model covers the hour'));
  assert.ok(daily.missing.includes('Fog and visibility are read only from marine alerts; check the marine forecast'));
  // Offshore wind: caution, headline and deck say so, no windows.
  const off = buildDaily(report({dir: 80}), slo, area, 'kayak', date, now);
  assert.match(off.headline, /offshore wind at times$/);
  assert.equal(off.status, 'Caution');
  assert.match(off.summary, /Offshore wind from \d{1,2} (AM|PM): it carries a kayak away from shore/);
  assert.deepEqual(off.windows, []);
  // A breeze a boat would accept (10 kt, gust 15) still gives a kayak no window, and fresh wind none calmer.
  assert.deepEqual(buildDaily(report({wind: 10, gust: 15}), slo, area, 'kayak', date, now).windows, []);
  const fresh = buildDaily(report({wind: 16, gust: 22}), slo, area, 'kayak', date, now);
  assert.match(fresh.headline, /^Strong wind · no calmer hour$/);
  assert.equal(fresh.status, 'Caution');
  // Launch surf from the nearshore model.
  const surfy = buildDaily(report({site: true, nearFt: 3.5}), slo, area, 'kayak', date, now);
  assert.equal(surfy.status, 'Caution');
  assert.match(surfy.summary, /Surf at the launch reaches about 3\.5 ft \(Morro Strand nearshore model\)/);
  assert.ok(!surfy.missing.some(m => m.startsWith('Launch surf is an offshore estimate')));
  // Fog alert caps every hour and the alert leads the headline.
  const fogAlert = {id: 'fog', event: 'Dense Fog Advisory', headline: 'Dense fog advisory until noon', description: '', effective: iso(start - HOUR), expires: iso(start + 48 * HOUR), url: 'https://www.weather.gov'};
  const foggy = buildDaily(report({alerts: [fogAlert]}), slo, area, 'kayak', date, now);
  assert.equal(foggy.headline, 'Dense Fog Advisory');
  assert.equal(foggy.status, 'Caution');
  assert.ok(foggy.kayak.fog);
  assert.ok(foggy.kayak.hours.every(h => h.verdict === 'Rough'));
  // Other profiles carry no kayak reading.
  for (const mode of ['boat', 'shore', 'spear']) assert.equal(buildDaily(report(), slo, area, mode, date, now).kayak, null);
});

test('buildDaily kayak: speed only where the stretch of coast has no vetted bearing', () => {
  const south = slo.areas.find(a => a.id === 'south');
  const r = report({dir: 80});
  r.forecasts = r.forecasts.filter(f => f.id !== 'south').map(f => f.id === 'central' ? {...f, id: 'south'} : f);
  const avila = buildDaily(r, slo, south, 'kayak', date, now);
  assert.ok(avila.kayak.hours.length);
  assert.ok(avila.kayak.hours.every(h => h.wind.side === null));
  assert.ok(avila.missing.includes('Offshore wind cannot be told apart for this stretch of coast; wind judged on speed only'));
  assert.match(avila.summary, /Whether the wind blows offshore here is unknown; wind is judged on speed only\./);
});

test('brief rendering for kayak: headline, caveat, wind side and seas in the tiles, regional brief', () => {
  const at = iso(start + 18 * HOUR);
  const brief = buildCoastBrief({report: report({dir: 80, wave: 2.5, period: 7}), county: slo, areaId: 'central', profile: 'kayak', date, now, at});
  assert.equal(brief.profile, 'kayak');
  assert.ok(brief.kayak);
  assert.equal(brief.shore, null);
  assert.match(brief.headline, /offshore wind at times$/);
  assert.equal(brief.caveat, 'Wind, offshore drift and surf at the launch set a kayak day; a forecast cannot clear a paddle.');
  assert.match(brief.tiles.find(t => t.id === 'wind').detail, /from E · light offshore$/);
  assert.match(brief.tiles.find(t => t.id === 'swell').detail, /^7 s · offshore forecast · moderate seas · short-period chop$/);
  // Outside a coast report binding the place has no shoreline bearing.
  const place = {id: 'monterey', name: 'Monterey', lat: 36.62, lon: -121.9, timezone: 'America/Los_Angeles', port: 'Monterey'};
  const regional = buildRegionalBrief({daily: montereyDaily, forecast: montereyForecast, place, profile: 'kayak', date: '2026-10-08', now});
  assert.ok(regional.kayak);
  assert.ok(regional.kayak.hours.every(h => h.wind.side === null));
  assert.equal(regional.caveat, brief.caveat);
});

// Issue #542: the shore-fishing reading (packages/coast/src/shore-conditions.ts)
// and its place in the daily brief (daily.ts buildDaily, web/brief/model.ts).
import test from 'node:test';
import assert from 'node:assert/strict';
import fixture from './fixtures/coast/skippercast-report.json' with {type: 'json'};
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import montereyForecast from './fixtures/brief/monterey-forecast.json' with {type: 'json'};

const {SHORE, surf, sneakerScore, seaward, shoreWind, tidePhase, isTwilight, shoreVerdict, shoreHours, shoreDay, surfWindowOk} = await import('../packages/coast/src/shore-conditions.ts');
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
const sea = seaward('slo', 'central');

/** The fixture report with light wind, offshore seas and an optional nearshore site. */
function report({site = false, wave = 3, period = 10, swellPeriod = 10, nearFt = 2, nearS = 10, wind = 5, gust = 8, dir = 90} = {}) {
  const hours = Array.from({length: 48}, (_, i) => ({at: iso(start + i * HOUR), windKnots: wind, gustKnots: gust, windDirectionDeg: dir, waveFt: wave, wavePeriodS: period, swellFt: wave - 0.5, swellPeriodS: swellPeriod, airTempF: 60, precipPct: 0}));
  const out = structuredClone(fixture);
  out.alerts = [];
  out.forecasts = out.forecasts.map(f => f.id === 'central' ? {...f, hours} : f);
  if (site) out.nearshore = [{id: 'mop-test', name: 'Morro Strand', areaId: 'central', lat: 35.4, lon: -120.87, sourceId: 'cdip', issuedAt: iso(now.getTime() - 2 * HOUR), fetchedAt: iso(now.getTime() - 20 * 60_000),
    hours: Array.from({length: 16}, (_, i) => ({at: iso(start - 3 * HOUR + i * 3 * HOUR), waveFt: nearFt, periodS: nearS, directionDeg: 280, qualityFlag: null, secondaryFlag: null})),
    url: 'https://cdip.ucsd.edu', kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 180, waterDepthM: 15, depthDatum: 'MSL', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: iso(start + 42 * HOUR)}];
  return out;
}

test('surf: nearshore bands, an offshore estimate on its own scale, and the sneaker caution', () => {
  const hour = {at: iso(start), windKnots: 5, gustKnots: 8, waveFt: 5.5, wavePeriodS: 9, swellFt: 3, swellPeriodS: 11};
  const near = surf(hour, {at: hour.at, waveFt: 2.5, periodS: 11, directionDeg: null, qualityFlag: null, secondaryFlag: null});
  assert.deepEqual([near.basis, near.band, near.heightFt, near.sneaker], ['nearshore', 'Small', 2.5, false]);
  // 5.5 ft offshore seas are Moderate on the offshore scale (3/6/9 ft); 5.5 ft at the nearshore point would be Large.
  const off = surf(hour);
  assert.deepEqual([off.basis, off.band], ['offshore', 'Moderate']);
  assert.deepEqual(SHORE.surf.offshore, {small: 3, moderate: 6, large: 9});
  assert.equal(surf(hour, {at: hour.at, waveFt: 5.5, periodS: 9}).band, 'Large');
  // Typical Central Coast seas of 4 to 7 ft read Moderate to Large, not Heavy.
  assert.deepEqual([4, 7].map(waveFt => surf({...hour, waveFt}).band), ['Moderate', 'Large']);
  assert.equal(surf({...hour, waveFt: 2.5}).band, 'Small');
  assert.equal(surf({...hour, waveFt: 9.5}).band, 'Heavy');
  assert.equal(surf({...hour, waveFt: null}).band, 'Unknown');
  // A long-period swell partition with enough height triggers the caution even when the combined period is short.
  const longSwell = surf({...hour, swellFt: 2, swellPeriodS: 16});
  assert.deepEqual([longSwell.sneaker, longSwell.longPeriodS, longSwell.sneakerScore], [true, 16, 1.5]);
  assert.equal(surf({...hour, swellFt: 1, swellPeriodS: 18}).sneaker, false, 'too small to count');
  // Nearshore path: a short local peak period does not hide a long-period offshore swell partition.
  const nearShort = {at: hour.at, waveFt: 2, periodS: 8, directionDeg: null, qualityFlag: null, secondaryFlag: null};
  const hidden = surf({...hour, swellFt: 1.8, swellPeriodS: 15}, nearShort);
  assert.deepEqual([hidden.basis, hidden.band, hidden.sneaker, hidden.longPeriodS], ['nearshore', 'Small', true, 15]);
  assert.equal(surf({...hour, swellFt: 1.2, swellPeriodS: 15}, nearShort).sneaker, false, 'offshore partition too small');
  assert.equal(surf({...hour, swellFt: 3, swellPeriodS: 13}, nearShort).sneaker, false, 'offshore partition too short');
  assert.equal(sneakerScore(13), 0);
  assert.equal(sneakerScore(14), 1.5);
  assert.equal(sneakerScore(18), 2.5);
});

test('wind: speed bands, and onshore / offshore from the vetted shoreline bearing', () => {
  // Vetted bearings only: Morro Bay faces a little south of west, Cambria and San Simeon southwest.
  assert.equal(sea, 260);
  assert.equal(seaward('slo', 'north'), 230);
  // Avila faces south and Pismo west: no single bearing, so none; regional places and unknown keys have none either.
  assert.deepEqual([seaward('slo', 'south'), seaward('monterey', 'monterey'), seaward(undefined, 'central'), seaward('slo', 'constructor')], [null, null, null, null]);
  // Cambria: a northwest wind runs along the shore (cross-shore), not onshore; a southwest wind is onshore.
  const cambria = seaward('slo', 'north');
  assert.equal(shoreWind({windKnots: 14, gustKnots: 20, windDirectionDeg: 315}, cambria).side, 'cross-shore');
  assert.equal(shoreWind({windKnots: 14, gustKnots: 20, windDirectionDeg: 225}, cambria).side, 'onshore');
  assert.equal(shoreWind({windKnots: 14, gustKnots: 20, windDirectionDeg: 45}, cambria).side, 'offshore');
  assert.equal(shoreWind({windKnots: 6, gustKnots: 10, windDirectionDeg: 270}, sea).side, 'onshore');
  assert.equal(shoreWind({windKnots: 6, gustKnots: 10, windDirectionDeg: 90}, sea).side, 'offshore');
  assert.equal(shoreWind({windKnots: 6, gustKnots: 10, windDirectionDeg: 0}, sea).side, 'cross-shore');
  assert.equal(shoreWind({windKnots: 6, gustKnots: 10, windDirectionDeg: 270}, sea).band, 'Light');
  assert.equal(shoreWind({windKnots: 12, gustKnots: 18}, sea).band, 'Breezy');
  assert.equal(shoreWind({windKnots: 9, gustKnots: 24}, sea).band, 'Strong');
  // Without a direction (or a shoreline bearing), speed only.
  assert.deepEqual([shoreWind({windKnots: 6, gustKnots: 10}, sea).side, shoreWind({windKnots: 6, gustKnots: 10, windDirectionDeg: 270}, null).side], [null, null]);
  assert.equal(shoreWind({windKnots: null, gustKnots: 10}, sea).band, 'Unknown');
});

test('tide phase: rising, the two hours around high, falling, very low', () => {
  const t0 = Date.parse('2026-10-09T12:00:00Z');
  const events = [{at: iso(t0), heightFt: -0.4, type: 'L'}, {at: iso(t0 + 6 * HOUR), heightFt: 5, type: 'H'}, {at: iso(t0 + 12 * HOUR), heightFt: 1, type: 'L'}];
  assert.equal(tidePhase(t0 + 3 * HOUR, events).phase, 'rising');
  assert.equal(tidePhase(t0 + 5 * HOUR, events).phase, 'high');
  assert.equal(tidePhase(t0 + 7 * HOUR, events).phase, 'high');
  assert.equal(tidePhase(t0 + 9 * HOUR, events).phase, 'falling');
  assert.equal(tidePhase(t0 + 3 * HOUR, events).bonus, true);
  assert.equal(tidePhase(t0 + 9 * HOUR, events).bonus, false);
  const low = tidePhase(t0 + 20 * 60_000, events);
  assert.deepEqual([low.phase, low.heightFt, low.veryLow], ['low', -0.4, true]);
  // The curve gives the height between events.
  assert.equal(tidePhase(t0 + 3 * HOUR, events, [{at: iso(t0 + 3 * HOUR), heightFt: -0.1}]).veryLow, true);
  assert.equal(tidePhase(t0 + 14 * HOUR, events).phase, null, 'no event after');
  assert.equal(tidePhase(t0, []).phase, null);
});

test('twilight: within an hour of sunrise or sunset', () => {
  const rise = '2026-10-09T14:10:00Z', set = '2026-10-10T01:40:00Z';
  assert.equal(isTwilight(Date.parse('2026-10-09T14:00:00Z'), rise, set), true);
  assert.equal(isTwilight(Date.parse('2026-10-10T01:00:00Z'), rise, set), true);
  assert.equal(isTwilight(Date.parse('2026-10-09T19:00:00Z'), rise, set), false);
  assert.equal(isTwilight(Date.parse('2026-10-09T14:00:00Z'), null, null), false);
});

test('verdict: surf and wind decide, tide and light are mild, long-period swell is never Calmer', () => {
  const s = (band, extra = {}) => ({band, heightFt: 2, periodS: 10, basis: 'nearshore', longPeriodS: null, sneaker: false, sneakerScore: 0, ...extra});
  const w = (band, side = null) => ({band, side, windKnots: 5, gustKnots: 8, directionDeg: null});
  const t = (phase, extra = {}) => ({phase, heightFt: 2, veryLow: false, bonus: phase === 'rising' || phase === 'high', ...extra});
  assert.equal(shoreVerdict(s('Small'), w('Light'), t('falling'), false).verdict, 'Calmer');
  assert.equal(shoreVerdict(s('Moderate'), w('Breezy'), t('falling'), false).verdict, 'Marginal');
  assert.equal(shoreVerdict(s('Moderate'), w('Light'), t('rising'), false).verdict, 'Calmer');
  assert.equal(shoreVerdict(s('Large'), w('Light'), t('high'), true).verdict, 'Rough');
  assert.equal(shoreVerdict(s('Heavy'), w('Light'), t('rising'), true).verdict, 'Rough');
  assert.equal(shoreVerdict(s('Small'), w('Strong'), t('falling'), false).verdict, 'Marginal');
  // Onshore makes a breezy hour worse; a light onshore breeze costs nothing.
  assert.ok(shoreVerdict(s('Small'), w('Breezy', 'onshore'), t(null), false).score > shoreVerdict(s('Small'), w('Breezy', 'offshore'), t(null), false).score);
  assert.equal(shoreVerdict(s('Small'), w('Light', 'onshore'), t(null), false).score, 0);
  assert.equal(shoreVerdict(s('Moderate'), w('Strong', 'onshore'), t(null), false).verdict, 'Rough');
  const sneaky = shoreVerdict(s('Small', {sneaker: true, longPeriodS: 15, sneakerScore: 0}), w('Light'), t('rising'), true);
  assert.equal(sneaky.verdict, 'Marginal');
  assert.match(sneaky.cautions[0], /sneaker waves/);
  assert.ok(sneaky.reasons.includes('long-period swell'));
  assert.equal(shoreVerdict(s('Moderate', {sneaker: true, longPeriodS: 17, sneakerScore: 2.5}), w('Light'), t(null), false).verdict, 'Rough');
  const low = shoreVerdict(s('Small'), w('Light'), t('low', {veryLow: true, heightFt: -0.5}), false);
  assert.match(low.cautions[0], /Very low tide \(-0.5 ft\)/);
  assert.equal(low.verdict, 'Calmer', 'a very low tide is a caution, not a score');
  const unknown = shoreVerdict(s('Unknown', {heightFt: null}), w('Light'), t(null), false);
  assert.deepEqual([unknown.verdict, unknown.score, unknown.reasons], ['Unknown', null, ['Surf height unknown']]);
  assert.deepEqual(shoreVerdict(s('Small'), w('Unknown'), t(null), false).reasons, ['Wind unknown']);
  assert.ok(Math.abs(SHORE.score.tide) + Math.abs(SHORE.score.twilight) < SHORE.score.calmer, 'bonuses stay mild');
});

test('shoreHours and shoreDay: daylight roll-up, best hour, missing direction and tide flags', () => {
  const t0 = Date.parse('2026-10-09T15:00:00Z');
  const hours = [0, 1, 2, 3].map(i => ({at: iso(t0 + i * HOUR), windKnots: i === 3 ? 18 : 5, gustKnots: 8, waveFt: 1.5, wavePeriodS: 10}));
  const out = shoreHours({hours, site: undefined, countyId: 'slo', area, tideEvents: [{at: iso(t0 - 2 * HOUR), heightFt: 1, type: 'L'}, {at: iso(t0 + 2 * HOUR), heightFt: 4, type: 'H'}], tides: [], sunrise: iso(t0 - 30 * 60_000), sunset: iso(t0 + 10 * HOUR)});
  assert.deepEqual(out.map(h => h.tide.phase), ['rising', 'high', 'high', 'high']);
  assert.equal(out[0].twilight, true);
  assert.equal(out[3].verdict, 'Marginal');
  const day = shoreDay(out, iso(t0 - 30 * 60_000), iso(t0 + 10 * HOUR), sea);
  assert.deepEqual(day.surf, {min: 'Small', max: 'Small'});
  assert.equal(day.basis, 'offshore');
  assert.equal(day.best.at, out[0].at, 'dawn and rising tide make the first hour best');
  assert.equal(day.bearingKnown, true);
  assert.equal(day.windSpeedOnly, true, 'no wind direction in these hours');
  assert.equal(shoreDay(out, null, null, null).bearingKnown, false);
  assert.equal(day.tideUnknown, false);
  assert.equal(day.sneakerPeriodS, null);
  assert.equal(surfWindowOk(out[0].surf), undefined, 'offshore surf leaves windows to the generic rule');
  assert.equal(surfWindowOk({...out[0].surf, basis: 'nearshore'}), true);
  assert.equal(surfWindowOk({...out[0].surf, basis: 'nearshore', sneaker: true}), false);
  assert.equal(shoreDay([], null, null).best, null);
});

test('buildDaily shore with a fresh nearshore model: surf windows, verdict headline, tide and wind deck', () => {
  const daily = buildDaily(report({site: true, wave: 4.5}), slo, area, 'shore', date, now);
  assert.ok(daily.shore);
  assert.equal(daily.spear, null);
  assert.equal(daily.shore.basis, 'nearshore');
  assert.match(daily.headline, /^Small surf · calmer at \d{1,2} (AM|PM)$/);
  assert.match(daily.summary, /Surf from the Morro Strand nearshore model: 2 ft at 10 s\./);
  assert.match(daily.summary, /angler rule of thumb, not a guarantee\): high at/);
  assert.match(daily.summary, /Wind offshore\./);
  assert.match(daily.summary, /Calmest daylight hour:/);
  assert.match(daily.summary, /A model point is not your beach/);
  // 4.5 ft offshore fails the generic 3 ft rule; the small nearshore surf opens windows.
  assert.ok(daily.windows.length > 0);
  assert.equal(daily.windows[0].label, 'Lower surf & wind');
  assert.equal(daily.status, 'Mixed');
  assert.ok(daily.missing.includes('Breaking surf, beach access and water quality need a local check'));
  assert.ok(!daily.missing.some(m => /offshore estimate/.test(m)));
  // Long-period nearshore swell: caution status, sneaker headline, no windows.
  const long = buildDaily(report({site: true, nearS: 16}), slo, area, 'shore', date, now);
  assert.match(long.headline, /sneaker-wave risk$/);
  assert.equal(long.status, 'Caution');
  assert.match(long.summary, /Long-period swell \(16 s\) raises the risk of sneaker waves/);
  assert.deepEqual(long.windows, []);
  // Short nearshore period, long offshore swell partition: still the sneaker caution.
  const underneath = buildDaily(report({site: true, nearS: 8, swellPeriod: 15}), slo, area, 'shore', date, now);
  assert.equal(underneath.shore.basis, 'nearshore');
  assert.equal(underneath.shore.sneakerPeriodS, 15);
  assert.equal(underneath.status, 'Caution');
  assert.match(underneath.headline, /sneaker-wave risk$/);
});

test('buildDaily shore: wind side only where the stretch of coast has a vetted bearing', () => {
  const north = slo.areas.find(a => a.id === 'north'), south = slo.areas.find(a => a.id === 'south');
  const forArea = (id, options) => {const r = report(options); r.forecasts = r.forecasts.filter(f => f.id !== id).map(f => f.id === 'central' ? {...f, id} : f); return r;};
  // Cambria with a fresh northwest breeze: cross-shore, never onshore.
  const cambria = buildDaily(forArea('north', {dir: 315, wind: 14, gust: 20}), slo, north, 'shore', date, now);
  assert.ok(cambria.shore.hours.length);
  assert.ok(cambria.shore.hours.every(h => h.wind.side === 'cross-shore'));
  assert.ok(!cambria.summary.includes('onshore'));
  assert.ok(buildDaily(forArea('north', {dir: 225, wind: 14, gust: 20}), slo, north, 'shore', date, now).shore.hours.every(h => h.wind.side === 'onshore'));
  // Avila and Pismo: speed only, and the brief says so.
  const avila = buildDaily(forArea('south', {dir: 270, wind: 14, gust: 20}), slo, south, 'shore', date, now);
  assert.ok(avila.shore.hours.length);
  assert.ok(avila.shore.hours.every(h => h.wind.side === null && h.wind.band === 'Breezy'));
  assert.equal(avila.shore.bearingKnown, false);
  assert.ok(avila.missing.includes('Wind side unknown for this stretch of coast; wind judged on speed only'));
  assert.match(avila.summary, /judged on speed only/);
});

test('buildDaily shore without a nearshore model: offshore estimate labelled, speed-only wind listed', () => {
  const daily = buildDaily(report({dir: null}), slo, area, 'shore', date, now);
  assert.equal(daily.shore.basis, 'offshore');
  assert.match(daily.headline, /^Moderate surf \(offshore estimate\) · /);
  assert.match(daily.summary, /Surf is an offshore estimate: 3 ft offshore seas at 10 s\. Sheltered beaches can see less and exposed beaches more\./);
  assert.match(daily.summary, /Offshore seas do not measure breakers at your beach/);
  assert.match(daily.summary, /judged on speed only/);
  assert.ok(daily.missing.includes('Surf is an offshore estimate where no fresh nearshore model covers the hour'));
  assert.ok(daily.missing.some(m => m.startsWith('Onshore or offshore wind unknown')));
  // Heavy offshore seas: no calmer hour, caution.
  const big = buildDaily(report({wave: 9.5}), slo, area, 'shore', date, now);
  assert.match(big.headline, /Heavy surf \(offshore estimate\) · no calmer hour/);
  assert.equal(big.status, 'Caution');
  // Boat and spear carry no shore reading.
  assert.equal(buildDaily(report(), slo, area, 'boat', date, now).shore, null);
  assert.equal(buildDaily(report(), slo, area, 'spear', date, now).shore, null);
  // No tide events: the phase is listed as unknown.
  const noTide = structuredClone(report());
  noTide.tideEvents = [];
  assert.ok(buildDaily(noTide, slo, area, 'shore', date, now).missing.includes('Tide phase unknown: high and low tide events unavailable'));
});

test('brief rendering for shore: headline, deck, surf in the swell tile, wind side, coast panel', () => {
  const at = iso(start + 18 * HOUR);
  const brief = buildCoastBrief({report: report({site: true, dir: 270, wind: 12, gust: 16}), county: slo, areaId: 'central', profile: 'shore', date, now, at});
  assert.match(brief.headline, /surf · /);
  assert.ok(brief.shore);
  assert.equal(brief.spear, null);
  assert.match(brief.tiles.find(t => t.id === 'swell').detail, /· small surf$/);
  assert.match(brief.tiles.find(t => t.id === 'wind').detail, /from W · onshore$/);
  assert.match(brief.deck, /onshore wind chops the surf/);
  const html = reportPanel(report({site: true}), slo, area, 'shore', date, now);
  assert.match(html, /Smaller surf\. Check your beach\./);
  assert.match(html, /Lower surf &amp; wind\. Local checks required\./);
  assert.match(reportPanel(report({site: true, nearS: 16}), slo, area, 'shore', date, now), /Long-period swell\. Watch for sneaker waves\./);
  // Outside a coast report binding the place has no shoreline bearing: wind side unknown, surf an offshore estimate.
  const place = {id: 'monterey', name: 'Monterey', lat: 36.62, lon: -121.9, timezone: 'America/Los_Angeles', port: 'Monterey'};
  const regional = buildRegionalBrief({daily: montereyDaily, forecast: montereyForecast, place, profile: 'shore', date: '2026-10-08', now});
  assert.ok(regional.shore);
  assert.ok(regional.shore.hours.every(h => h.wind.side === null));
  if (regional.shore.hours.length) assert.ok(regional.missing.includes('Surf is an offshore estimate where no fresh nearshore model covers the hour'));
});

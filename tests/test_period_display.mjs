// SC1722-11: wave periods in Shore, bar, kayak and brief-tile copy read in whole seconds (14.285714 -> "14 s").
// Display only: every rule, threshold and window still reads the exact period. Synthetic inputs, values invented.
import './helpers/spanish-ready.mjs';   // SC1407-09: the Spanish table, before the Spanish renders
import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import report from './fixtures/coast/skippercast-report.json' with {type: 'json'};
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import montereyForecast from './fixtures/brief/monterey-forecast.json' with {type: 'json'};

const {periodSecondsText} = await import('../packages/coast/src/period-display.ts');
const {surf, shoreVerdict, sneakerScore} = await import('../packages/coast/src/shore-conditions.ts');
const {barSwell, barBand} = await import('../packages/coast/src/bar-conditions.ts');
const {kayakSeas, kayakVerdict, kayakWind} = await import('../packages/coast/src/kayak.ts');
const {slo} = await import('../packages/coast/src/counties.ts');
const {PROFILES} = await import('../web/profile.ts');
const {buildCoastBrief, buildRegionalBrief} = await import('../web/brief/model.ts');
const {partText, tileDetailText} = await import('../web/brief/tile-copy.ts');
const {verdictCopy} = await import('../web/brief/verdict-copy.ts');

const P = 14.285714;
const flood = {stage: 'flood', midEbb: false, fraction: 0.5};
const shoreWindLight = {band: 'Light', side: null, windKnots: 4, gustKnots: 6, directionDeg: null};
const tide = {phase: 'falling', heightFt: 2, veryLow: false, bonus: false};
const hourOf = (waveFt, wavePeriodS, extra = {}) => ({at: '2026-10-08T21:00:00Z', waveFt, wavePeriodS, swellFt: 1, swellPeriodS: 8, ...extra});
const shore = hour => { const s = surf(hour); return {s, ...shoreVerdict(s, shoreWindLight, tide, false)}; };
const bar = hour => { const swell = barSwell(hour); return {swell, ...barBand(flood, swell, false)}; };
const kayak = hour => {
  const seas = kayakSeas(hour), launch = surf(hour);
  return {seas, launch, ...kayakVerdict(kayakWind({windKnots: 4, gustKnots: 6, windDirectionDeg: null}, null), seas, launch, true, false)};
};

test('helper: whole seconds, half up, exact integers unchanged', () => {
  for (const [value, text] of [[P, '14'], [14.49, '14'], [14.5, '15'], [16.6, '17'], [14, '14'], [8, '8'], [0.4, '0']]) assert.equal(periodSecondsText(value), text, String(value));
});

test('period_rounding_site_matrix: 14.285714 reads 14 s in every Shore, bar and kayak reason and caution', () => {
  const hour = hourOf(9.6, P);
  const s = shore(hour);
  assert.equal(s.reasons[0], 'Heavy surf (9.6 ft at 14 s, offshore estimate)');
  assert.equal(s.reasons[1], 'long-period swell');
  assert.equal(s.cautions[0], 'Long-period swell (14 s): sneaker waves can run far up the beach without warning; stay off low rocks and keep the ocean in view');
  const b = bar(hour);
  assert.deepEqual(b.reasons.slice(0, 2), ['9.6 ft at 14 s swell (offshore estimate)', 'long-period swell (14 s)']);
  const k = kayak(hour);
  assert.ok(k.reasons.includes('heavy seas (9.6 ft at 14 s)'), k.reasons.join(' | '));
  assert.ok(k.cautions.includes('Long-period swell (14 s): sets can break bigger than the average at the launch'), k.cautions.join(' | '));
  for (const text of [...s.reasons, ...s.cautions, ...b.reasons, ...k.reasons, ...k.cautions]) assert.doesNotMatch(text, /\d\.\d+ s\b|14\.28/, text);
  // Nearshore basis: the nearshore point's period is the one shown.
  const near = surf(hourOf(2, 9), {at: hour.at, waveFt: 6, periodS: P, directionDeg: null, qualityFlag: null, secondaryFlag: null});
  assert.equal(shoreVerdict(near, shoreWindLight, tide, false).reasons[0], 'Large surf (6 ft at 14 s)');
  assert.equal(barBand(flood, barSwell(hourOf(2, 9), {at: hour.at, waveFt: 6, periodS: P, directionDeg: null, qualityFlag: null, secondaryFlag: null}), false).reasons[0], '6 ft at 14 s swell');
});

test('raw_thresholds_not_display_thresholds: verdicts, scores and bands are the same as before on the same inputs', () => {
  const hour = hourOf(9.6, P);
  const s = shore(hour);
  assert.deepEqual([s.verdict, s.score], ['Rough', 7.5]);
  assert.equal(s.s.periodS, P, 'raw period kept in the Surf');
  assert.equal(s.s.longPeriodS, P);
  assert.equal(s.s.sneakerScore, 1.5);
  const b = bar(hour);
  assert.equal(b.band, 'Caution');
  assert.equal(b.swell.periodS, P);
  assert.equal(b.swell.longPeriodS, P);
  const k = kayak(hour);
  assert.deepEqual([k.verdict, k.score], ['Rough', 7.5]);
  assert.equal(k.seas.periodS, P);
  assert.equal(k.launch.longPeriodS, P);
});

test('raw_thresholds_not_display_thresholds: a period that displays across a threshold does not cross it', () => {
  // Shore sneaker steps are 14 s and 17 s on the raw period.
  assert.deepEqual([13.99, 14, 14.01, 16.6, 17, 17.01].map(sneakerScore), [0, 1.5, 1.5, 1.5, 2.5, 2.5]);
  const below = shore(hourOf(4, 13.99, {swellFt: 0}));
  assert.equal(below.s.sneaker, false);
  assert.equal(below.cautions.length, 0, 'displayed 14 s from 13.99 gains no caution');
  assert.equal(below.reasons[0], 'Moderate surf (4 ft at 14 s, offshore estimate)');
  assert.ok(!below.reasons.includes('long-period swell'));
  const below17 = shore(hourOf(4, 16.6, {swellFt: 0}));
  assert.equal(below17.s.sneakerScore, 1.5, 'displayed 17 s from 16.6 keeps the 14 s score');
  assert.match(below17.cautions[0], /^Long-period swell \(17 s\): sneaker waves/);
  assert.equal(shore(hourOf(4, 17, {swellFt: 0})).s.sneakerScore, 2.5);
  // Bar: long-period rule is 14 s on the raw period.
  const barBelow = bar(hourOf(4, 13.99, {swellFt: 0})), barAt = bar(hourOf(4, 14, {swellFt: 0}));
  assert.equal(barBelow.swell.longPeriodS, 13.99);
  assert.ok(!barBelow.reasons.some(r => r.startsWith('long-period swell')), barBelow.reasons.join(' | '));
  assert.equal(barBelow.reasons[0], '4 ft at 14 s swell (offshore estimate)');
  assert.equal(barBelow.band, 'No bar flag');
  assert.deepEqual([barAt.band, barAt.reasons[1]], ['Caution', 'long-period swell (14 s)']);
  // Kayak chop is 8 s or less on the raw period.
  const chopOf = p => kayak(hourOf(3, p, {swellFt: 0})).seas.chop;
  assert.deepEqual([7.99, 8, 8.01].map(chopOf), [true, true, false]);
  assert.equal(kayak(hourOf(3, 8.01, {swellFt: 0})).reasons.find(r => r.includes('seas')), 'large seas (3 ft at 8 s)', 'displayed 8 s from 8.01 is not chop');
});

test('missing_period_and_basis_parity: a missing or unusable period adds no period text', () => {
  for (const p of [null, undefined, 0, -3]) {
    assert.equal(shore(hourOf(4, p, {swellFt: 0})).reasons[0], 'Moderate surf (4 ft, offshore estimate)');
    assert.equal(bar(hourOf(4, p, {swellFt: 0})).reasons[0], '4 ft swell (offshore estimate)');
  }
  for (const p of [null, undefined]) assert.equal(kayak(hourOf(3, p, {swellFt: 0})).reasons.find(r => r.includes('seas')), 'large seas (3 ft)');
  for (const text of [...shore(hourOf(4, NaN, {swellFt: 0})).reasons, ...bar(hourOf(4, Infinity, {swellFt: 0})).reasons]) assert.doesNotMatch(text, /NaN|Infinity/, text);
});

test('tile_dual_representation_and_spanish_reason: tile details and their display parts agree, in both languages', () => {
  const now = new Date(Date.parse(report.generatedAt) + 10 * 60_000), date = '2026-10-08';
  const place = {id: 'monterey', name: 'Monterey', lat: 36.62, lon: -121.9, timezone: 'America/Los_Angeles', port: 'Monterey'};
  const forecast = {...montereyForecast, hours: montereyForecast.hours.map(h => ({...h, wavePeriodS: P, swellPeriodS: P}))};
  const join = (tile, lang) => tile.display.parts.map(p => partText(p, lang)).filter(Boolean).join(' · ');
  const swellOf = brief => brief.tiles.find(t => t.id === 'swell');
  for (const profile of PROFILES) {
    const brief = buildRegionalBrief({daily: montereyDaily, forecast, place, profile, date, now});
    const swell = swellOf(brief);
    if (!/ s · /.test(swell.detail)) continue;
    assert.match(swell.detail, /^14 s · offshore forecast/, `${profile} detail`);
    assert.doesNotMatch(swell.detail, /14\.\d/);
    assert.equal(join(swell, 'en'), swell.detail, `${profile} parts rebuild the English detail`);
    assert.match(tileDetailText(swell, 'es'), /^14 s · pronóstico mar adentro/, `${profile} Spanish`);
    assert.equal(swell.display.parts[0].text, '14 s');
  }
  assert.ok(PROFILES.some(profile => /^14 s · offshore forecast/.test(swellOf(buildRegionalBrief({daily: montereyDaily, forecast, place, profile, date, now})).detail)), 'at least one profile reads the offshore period');
  // Nearshore tile: the nearshore point's period.
  const site = {id: 'mop-1', name: 'Test Point', areaId: 'central', lat: 35.4, lon: -120.9, sourceId: 'cdip', issuedAt: report.generatedAt, fetchedAt: report.generatedAt,
    hours: [{at: report.generatedAt, waveFt: 4, periodS: P, directionDeg: null, qualityFlag: null, secondaryFlag: null}], url: 'https://example.test/mop', kind: 'forecast',
    availability: 'available', freshness: 'current', temporalResolutionMinutes: 60, waterDepthM: 15, depthDatum: 'MLLW', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: null};
  let nearshoreSeen = 0;
  for (const profile of PROFILES) {
    const tile = swellOf(buildCoastBrief({report: {...report, nearshore: [site]}, county: slo, areaId: 'central', profile, date, now}));
    if (!tile.detail.includes('Test Point')) continue;
    nearshoreSeen++;
    assert.match(tile.detail, /^14 s · Test Point/, profile);
    assert.equal(join(tile, 'en'), tile.detail);
    assert.match(tileDetailText(tile, 'es'), /^14 s · Test Point/, profile);
    assert.equal(tile.display.parts[0].text, '14 s');
  }
  assert.ok(nearshoreSeen > 0, 'a nearshore profile reads the site period');
  // The Spanish reason keeps its anchored grammar with the whole-second period.
  const es = verdictCopy('es');
  assert.equal(es.profileReason('Heavy surf (9.6 ft at 14 s, offshore estimate)'), 'oleaje de rompiente muy intenso (9,6 ft a 14 s, estimación mar adentro)');
  assert.equal(es.profileReason('heavy seas (9.6 ft at 14 s)'), 'mar muy intenso (9,6 ft a 14 s)');
});

test('inputs are not mutated by the display change', () => {
  const hour = Object.freeze(hourOf(9.6, P));
  const before = structuredClone(hour);
  shore(hour); bar(hour); kayak(hour);
  assert.ok(isDeepStrictEqual(hour, before), 'hour unchanged');
  assert.equal(hour.wavePeriodS, P);
});

// SC-TIDAL-1: the harbor entrance current (flood, ebb, slack and the turn) and the bar caution that adds swell to the ebb.
// Timing math at slack, ebb and flood; a stale-data case; a missing-data case that says so plainly; the WCOFS cross-check
// (the caution is never calmer than the worst source); and a layout check of the real component at 390 px in headless Chromium.
import assert from 'node:assert/strict';
import test from 'node:test';
import {existsSync} from 'node:fs';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {build} from 'esbuild';
import {chromium} from '@playwright/test';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {BAR_RANK, barHours, entranceFor} from '../packages/coast/src/bar-conditions.ts';
import {CURRENT, entranceReading, entranceTiming, entranceTurns, offshoreFlow} from '../packages/coast/src/entrance-current.ts';
import {entranceCurrentView, offshoreRead} from '../web/brief/entrance-current.ts';

const MIN = 60_000, HOUR = 3_600_000, TZ = 'America/Los_Angeles';
const iso = ms => new Date(ms).toISOString();
const T0 = Date.parse('2026-10-12T12:00:00Z');
// Low 12:00Z, high 18:00Z, low 00:00Z (next day), high 06:00Z: a six-hour semidiurnal sketch.
const EVENTS = [['L', 0], ['H', 6], ['L', 12], ['H', 18]].map(([type, h]) => ({at: iso(T0 + h * HOUR), type, heightFt: type === 'H' ? 5 : 0}));
const at = (h, m = 0) => T0 + h * HOUR + m * MIN;
const MORRO = entranceFor('morro-bay', 'morro-bay'), HUMBOLDT = entranceFor('humboldt-bay-cape-mendocino', 'humboldt-bay-cape-mendocino');
assert.equal(MORRO.seawardDeg, 260);
assert.equal(HUMBOLDT.seawardDeg, null);

// A readable WCOFS sample that says nothing about the entrance (too weak to count): the neutral source state for tests that are not about WCOFS.
const WEAK = {kind: 'weak', speedKn: 0.2, towardDeg: 0, validAt: 0};
const hoursAt = (events, waveFt, {entrance = MORRO, from = 0, count = 14, wavePeriodS = 10, windKnots = 0, windDirectionDeg = 0} = {}) =>
  barHours({entrance, tideEvents: events, hours: Array.from({length: count}, (_, i) => ({at: iso(T0 + (from + i) * HOUR), waveFt, wavePeriodS, windKnots, windDirectionDeg}))});
const hourOf = (hs, ms) => hs.find(h => Date.parse(h.at) <= ms && ms < Date.parse(h.at) + HOUR) ?? null;
const read = (ms, o = {}) => {
  const {events = EVENTS, wave = 2, tideFresh = true, swellFresh = true, offshore = WEAK, entrance = MORRO, wind = {}} = o;
  return entranceReading({at: ms, entrance, tideEvents: events, tideFresh, swellFresh, barHour: hourOf(hoursAt(events, wave, {entrance, ...wind}), ms), offshore});
};

test('timing: flood between a low and the next high, with the turn and its slack window', () => {
  const r = entranceTiming(at(3), EVENTS);
  assert.equal(r.state, 'ok');
  assert.deepEqual([r.phase, r.turnsTo, r.turnType, r.turnAt, r.slackFrom, r.slackUntil], ['flood', 'ebb', 'H', at(6), at(5, 30), at(6, 30)]);
});

test('timing: ebb between a high and the next low turns to flood at the low', () => {
  const r = entranceTiming(at(9), EVENTS);
  assert.deepEqual([r.phase, r.turnsTo, r.turnType, r.turnAt], ['ebb', 'flood', 'L', at(12)]);
});

test('timing: slack within the window either side of a high or a low, and not one minute outside it', () => {
  assert.equal(CURRENT.slackMin, 30);
  for (const [ms, turnsTo, turnType] of [[at(6), 'ebb', 'H'], [at(5, 30), 'ebb', 'H'], [at(6, 30), 'ebb', 'H'], [at(12), 'flood', 'L'], [at(11, 30), 'flood', 'L'], [at(12, 30), 'flood', 'L']]) {
    const r = entranceTiming(ms, EVENTS);
    assert.deepEqual([r.phase, r.turnsTo, r.turnType], ['slack', turnsTo, turnType], iso(ms));
  }
  assert.equal(entranceTiming(at(5, 29), EVENTS).phase, 'flood');
  assert.equal(entranceTiming(at(6, 31), EVENTS).phase, 'ebb');
  assert.equal(entranceTiming(at(11, 29), EVENTS).phase, 'ebb');
  assert.equal(entranceTiming(at(12, 31), EVENTS).phase, 'flood');
});

test('timing: the turns of a window, oldest first, with their flows; unreadable events are skipped', () => {
  const bad = [...EVENTS, {at: '2026-10-12T20:00:00', type: 'H', heightFt: 1}, {at: 'nope', type: 'L', heightFt: 1}, {at: iso(at(7)), type: 'X', heightFt: 1}];
  const turns = entranceTurns(bad, at(1), at(13));
  assert.deepEqual(turns.map(e => [e.at, e.type, e.turnsTo]), [[at(6), 'H', 'ebb'], [at(12), 'L', 'flood']]);
  assert.deepEqual(entranceTurns(EVENTS, at(7), at(8)), []);
  // A turn whose slack window is still open at the start of the window is listed.
  assert.equal(entranceTurns(EVENTS, at(6, 20), at(7))[0].at, at(6));
});

test('timing: no bracketing events, a conflicting pair and an offset-less time are not judged', () => {
  assert.deepEqual([entranceTiming(at(3), []).state, entranceTiming(at(3), []).reason], ['unknown', 'no-tide']);
  assert.equal(entranceTiming(at(3), [EVENTS[0]]).state, 'unknown');
  assert.equal(entranceTiming(at(3), [EVENTS[0], {...EVENTS[1], type: 'L'}]).state, 'unknown');
  assert.equal(entranceTiming(at(3), [{...EVENTS[0], at: '2026-10-12T12:00:00'}, EVENTS[1]]).state, 'unknown');
  assert.equal(entranceTiming(NaN, EVENTS).state, 'unknown');
});

test('offshore flow: out, in, along the coast, too weak, and not comparable without a seaward bearing', () => {
  const s = (toward, kn = 1) => ({speedKn: kn, towardDeg: toward, validAt: 0});
  assert.equal(offshoreFlow(s(260), MORRO).kind, 'out');
  assert.equal(offshoreFlow(s(215), MORRO).kind, 'out');
  assert.equal(offshoreFlow(s(80), MORRO).kind, 'in');
  assert.equal(offshoreFlow(s(170), MORRO).kind, 'across');
  assert.equal(offshoreFlow(s(260, 0.3), MORRO).kind, 'weak');
  assert.equal(offshoreFlow(s(260), HUMBOLDT).kind, 'unjudged');
  for (const bad of [null, undefined, {speedKn: NaN, towardDeg: 0, validAt: 0}, {speedKn: 1, towardDeg: 400, validAt: 0}]) assert.equal(offshoreFlow(bad, MORRO).kind, 'missing');
});

test('caution: ebb with swell is never calmer than flood with the same swell; mid-ebb 6 ft is hazardous', () => {
  const ebb = read(at(9), {wave: 6}), flood = read(at(3), {wave: 6});
  assert.equal(ebb.timing.phase, 'ebb');
  assert.equal(ebb.band, 'Hazardous');
  assert.equal(flood.band, 'Caution');
  assert.ok(BAR_RANK[ebb.band] >= BAR_RANK[flood.band]);
  assert.equal(ebb.flow, 'ebb');
  assert.equal(flood.flow, 'flood');
  assert.deepEqual([ebb.swellFt, ebb.periodS], [6, 10]);
  assert.equal(read(at(3), {wave: 1}).band, 'No bar flag');
});

test('WCOFS running out of the entrance reads the hour as an ebb: the band is the worse of the two sources', () => {
  const out = offshoreFlow({speedKn: 1.2, towardDeg: 255, validAt: at(3)}, MORRO);
  const withOut = read(at(3), {wave: 3, offshore: out}), without = read(at(3), {wave: 3});
  assert.equal(without.band, 'No bar flag');
  assert.deepEqual([withOut.band, withOut.ebbAssumed, withOut.why, withOut.flow], ['Caution', true, ['wcofs-ebb'], 'ebb']);
  // Flowing in, along the coast, weak or not comparable changes nothing.
  for (const toward of [75, 170]) assert.equal(read(at(3), {wave: 3, offshore: offshoreFlow({speedKn: 1.2, towardDeg: toward, validAt: 0}, MORRO)}).band, 'No bar flag');
  assert.equal(read(at(3), {wave: 3, offshore: offshoreFlow({speedKn: 0.2, towardDeg: 255, validAt: 0}, MORRO)}).band, 'No bar flag');
  assert.equal(read(at(3), {wave: 3, entrance: HUMBOLDT, offshore: offshoreFlow({speedKn: 1.2, towardDeg: 255, validAt: 0}, HUMBOLDT)}).ebbAssumed, false);
  // Never calmer than the bar hour's own band, whatever the sources say.
  for (const wave of [0.5, 2, 3, 5, 7, 11]) for (const h of [1, 3, 5, 6, 7, 9, 11, 12]) for (const offshore of [out, {kind: 'missing', reason: 'x'}]) {
    const r = read(at(h), {wave, offshore}), own = hourOf(hoursAt(EVENTS, wave), at(h));
    assert.ok(BAR_RANK[r.band] >= BAR_RANK[own.band], `${wave} ft at +${h} h`);
  }
});

test('stale data never looks calmer: old tide or old swell holds the band at Unknown, and a hazardous hour stays hazardous', () => {
  const calm = read(at(3), {wave: 1});
  assert.equal(calm.band, 'No bar flag');
  const staleTide = read(at(3), {wave: 1, tideFresh: false});
  assert.deepEqual([staleTide.timing.state, staleTide.timing.reason, staleTide.band, staleTide.why], ['unknown', 'stale-tide', 'Unknown', ['tide-stale']]);
  const staleSwell = read(at(3), {wave: 1, swellFresh: false});
  assert.deepEqual([staleSwell.band, staleSwell.why], ['Unknown', ['swell-stale']]);
  assert.equal(read(at(9), {wave: 6, tideFresh: false, swellFresh: false}).band, 'Hazardous');
  for (const r of [staleTide, staleSwell]) assert.ok(BAR_RANK[r.band] > BAR_RANK['Caution']);
});

test('missing data is said plainly: no tide, no swell, no WCOFS', () => {
  assert.deepEqual([read(at(3), {events: []}).timing.reason, read(at(3), {events: []}).why], ['no-tide', ['tide-missing']]);
  const noSwell = entranceReading({at: at(3), entrance: MORRO, tideEvents: EVENTS, tideFresh: true, swellFresh: true, barHour: null, offshore: {kind: 'missing', reason: 'none'}});
  assert.deepEqual([noSwell.band, noSwell.why], ['Unknown', ['swell-missing']]);
});

// ---- the words, over a real brief-shaped input -------------------------------------------------------------------------
const NOW = at(3, 20);
function brief({events = EVENTS, wave = 2, tide = 'fresh', swell = 'fresh', entrance = MORRO, count = 12, from = 0} = {}) {
  const hours = hoursAt(events, wave, {entrance, count, from});
  return {profile: 'boat', bar: {entrance, hours}, tideEvents: events, tides: [], sunrise: null, sunset: null, windows: [], alerts: [], missing: [],
    tiles: [{id: 'tide', state: tide, source: 'NOAA tide predictions, Port San Luis'}, {id: 'swell', state: swell, source: 'GFS-Wave'}]};
}
/** The feed's WCOFS block as /api/forecast carries it: three-hourly frames, [time s, lat, lon, kn, toward, km]. */
function forecast({issuedAgeH = 10, retrievedAgeH = 0.3, toward = 255, kn = 1.2, status = 'ok', region = 'morro-bay'} = {}) {
  const frames = Array.from({length: 24}, (_, k) => T0 / 1000 + k * 3 * 3600 - 6 * 3600);
  const currents = {source: 'wcofs', status, issued_at: iso(NOW - issuedAgeH * HOUR), resolution_km: 4,
    points: status === 'ok' ? [{point_id: 'central', requested: [35.36, -120.94], samples: frames.map(t => [t, 35.37, -120.95, kn, toward, 1.1])}] : []};
  return {region, retrieved: NOW - retrievedAgeH * HOUR, point: {id: 'central', lat: 35.36, lon: -120.94}, models: {}, feed: {region_id: region, retrieved: NOW - retrievedAgeH * HOUR, currents}};
}
const view = (b, f = forecast(), o = {}) => entranceCurrentView({brief: b, forecast: f, region: 'morro-bay', tz: TZ, now: new Date(NOW), lang: 'en', ...o});

test('WCOFS read: a sample inside the forecast gate; old runs, an old feed, a bad status and a missing region are gaps, never filled', () => {
  const ok = offshoreRead(forecast(), 'morro-bay', NOW, NOW);
  assert.deepEqual([ok.gap, ok.sample.speedKn, ok.sample.towardDeg], [null, 1.2, 255]);
  assert.equal(offshoreRead(forecast({issuedAgeH: 40}), 'morro-bay', NOW, NOW).gap, 'old');
  assert.equal(offshoreRead(forecast({retrievedAgeH: 8}), 'morro-bay', NOW, NOW).gap, 'old');
  assert.equal(offshoreRead(forecast({status: 'stale'}), 'morro-bay', NOW, NOW).gap, 'status');
  assert.equal(offshoreRead(null, 'morro-bay', NOW, NOW).gap, 'status');
  assert.equal(offshoreRead(forecast({region: 'cambria'}), 'morro-bay', NOW, NOW).gap, 'status');
  assert.equal(offshoreRead(forecast(), 'morro-bay', NOW + 80 * HOUR, NOW).gap, 'old');
});

test('words: flooding now, the turn with its slack window, the day\'s turns, the caution and the standing estimate wording', () => {
  const v = view(brief({wave: 2}), forecast({toward: 80}));
  assert.match(v.title, /^Morro Bay entrance current \(estimate\)$/);
  assert.match(v.timing, /^Flooding: the water is running in\. It turns to ebb about 11 am \(slack 10:30 am to 11:30 am\)\.$/);
  assert.match(v.turns, /^Turns: 5 am low water, then flood; 11 am high water, then ebb; 5 pm low water, then flood\.$/);
  assert.match(v.caution, /^Flood with 2 ft at 10 s swell: no bar flag \(estimate\)\.$/);
  assert.match(v.wcofs, /NOAA WCOFS forecast, offshore: 1\.2 kn toward 80°, running into the entrance\./);
  assert.match(v.foot, /Estimate from tide predictions and a model forecast/);
  assert.match(v.foot, /Not for navigation/);
  assert.match(v.foot, /VHF 16 or 22A/);
  assert.match(v.basis, /Port San Luis/);
  assert.match(v.basis, /30 minutes/);
  const ebb = view(brief({wave: 6}), forecast({toward: 80}), {now: new Date(at(9, 10))});
  assert.match(ebb.timing, /^Ebbing: the water is running out\. It turns to flood about 5 pm \(slack 4:30 pm to 5:30 pm\)\.$/);
  assert.equal(ebb.band, 'Hazardous');
  assert.match(ebb.caution, /^Ebb with 6 ft at 10 s swell: bar hazardous \(estimate\)\.$/);
  const slack = view(brief({wave: 2}), forecast({toward: 80}), {now: new Date(at(6, 10))});
  assert.match(slack.timing, /^Near slack, turning to ebb about 11 am \(slack 10:30 am to 11:30 am\)\.$/);
  assert.match(slack.caution, /^Near slack with 2 ft at 10 s swell: /);
});

test('words: a WCOFS flow out of the entrance raises the caution and says why', () => {
  const v = view(brief({wave: 3}), forecast({toward: 255, kn: 1.2}));
  assert.equal(v.band, 'Caution');
  assert.match(v.timing, /^Flooding/);
  assert.match(v.caution, /^Ebb with 3 ft at 10 s swell: bar caution \(estimate\)\.$/);
  assert.match(v.wcofs, /running out of the entrance\./);
  assert.match(v.why, /^The tide predictions and the WCOFS forecast disagree: WCOFS runs out of the entrance, so this hour is read as an ebb\.$/);
  assert.equal(view(brief({wave: 3}), forecast({toward: 75})).band, 'No bar flag');
});

test('words: a bar with no vetted bearing shows the WCOFS flow but does not compare it', () => {
  const v = view(brief({wave: 3, entrance: HUMBOLDT}), forecast({toward: 255}));
  assert.match(v.title, /^Humboldt Bay entrance current/);
  assert.match(v.wcofs, /Not compared here: this entrance has no vetted seaward bearing\./);
  assert.equal(v.reading.ebbAssumed, false);
  assert.match(v.timing, /^Flooding/);
});

test('words, stale data: old tide and old swell say so and never read as no bar flag', () => {
  const tide = view(brief({wave: 1, tide: 'stale'}));
  assert.match(tide.timing, /^Flood or ebb not judged: the tide predictions are older than the app allows\.$/);
  assert.equal(tide.turns, '');
  assert.equal(tide.band, 'Unknown');
  assert.match(tide.caution, /bar unknown \(estimate\)/);
  assert.doesNotMatch(tide.caution, /no bar flag/);
  const swell = view(brief({wave: 1, swell: 'stale'}));
  assert.match(swell.caution, /^Bar unknown \(estimate\): the swell forecast is older than the app allows\.$/);
  assert.match(swell.timing, /^Flooding/);
  const old = view(brief({wave: 1}), forecast({issuedAgeH: 40}));
  assert.match(old.wcofs, /unavailable for this hour \(older than the app allows or outside its hours\); the timing uses the tide predictions only\./);
  assert.equal(old.band, 'No bar flag');
});

// ---- review round 1 (PR #1778): the caution is re-read at the real instant, with its wind, and never relaxes as a source ages ----
const SHIFTED = EVENTS.map(e => ({...e, at: iso(Date.parse(e.at) + 5 * MIN)}));
const OUT = {kind: 'out', speedKn: 1.2, towardDeg: 260, validAt: 0};
const MISSING = {kind: 'missing', reason: 'old'};

test('caution is recomputed at the actual instant: a turn inside the hour is not read from the hour before it', () => {
  // Low 12:05, high 18:05 (the floored 18:00 hour is flood), 18:40 is 35 minutes past the high: ebbing, outside the slack window.
  const ms = at(6, 40), r = read(ms, {events: SHIFTED, wave: 3});
  assert.equal(r.timing.phase, 'ebb');
  assert.equal(hourOf(hoursAt(SHIFTED, 3), ms).band, 'No bar flag');
  assert.deepEqual([r.band, r.flow], ['Caution', 'ebb']);
  const v = view(brief({events: SHIFTED, wave: 3}), forecast({toward: 80}), {now: new Date(ms)});
  assert.match(v.timing, /^Ebbing/);
  assert.match(v.caution, /^Ebb with 3 ft at 10 s swell: bar caution \(estimate\)\.$/);
  // The mid-ebb boundary inside an hour: 25% of 18:05 to 00:05 is 19:35; at 19:40 the 19:00 hour is not mid-ebb, the instant is.
  const mid = read(at(7, 40), {events: SHIFTED, wave: 6});
  assert.equal(hourOf(hoursAt(SHIFTED, 6), at(7, 40)).band, 'Caution');
  assert.equal(mid.band, 'Hazardous');
  // And the other way round: never calmer than the hour's own band (a flood instant just after the low, inside an ebb hour).
  const after = read(at(12, 10), {events: SHIFTED, wave: 3});
  assert.equal(hourOf(hoursAt(SHIFTED, 3), at(12, 10)).band, 'Caution');
  assert.equal(after.band, 'Caution');
});

test('stale swell keeps a Hazardous reading in words, with the stale warning beside it, in English and Spanish', () => {
  const now = new Date(at(9, 10));
  for (const lang of ['en', 'es']) {
    const v = view(brief({wave: 6, swell: 'stale'}), forecast({toward: 80}), {now, lang});
    assert.equal(v.band, 'Hazardous');
    assert.ok(v.reading.why.includes('swell-stale'));
    if (lang === 'en') {
      assert.match(v.caution, /^Ebb with 6 ft at 10 s swell: bar hazardous \(estimate\)\. The swell forecast is older than the app allows, so treat this as a minimum\.$/);
      assert.doesNotMatch(v.caution, /bar unknown/);
    } else {
      assert.match(v.caution, /^Vaciante con oleaje de 6 ft a 10 s: condiciones peligrosas en la barra \(estimación\)\. El pronóstico de oleaje es más antiguo de lo que permite la app/);
    }
  }
  // A stale swell without a hazard still reads unknown.
  assert.match(view(brief({wave: 3, swell: 'stale'}), forecast({toward: 80}), {now}).caution, /^Bar unknown \(estimate\): the swell forecast is older than the app allows\.$/);
});

test('an aging WCOFS run never makes the caution calmer: a lost cross-check reads as a possible ebb, not as no hazard', () => {
  const fresh = view(brief({wave: 3}), forecast({toward: 255, kn: 1.2, issuedAgeH: 10})), aged = view(brief({wave: 3}), forecast({toward: 255, kn: 1.2, issuedAgeH: 40}));
  assert.equal(fresh.band, 'Caution');
  assert.deepEqual([aged.band, aged.reading.why], ['Caution', ['wcofs-missing']]);
  assert.match(aged.wcofs, /unavailable for this hour/);
  assert.match(aged.why, /^The WCOFS forecast is unavailable, so an ebb cannot be ruled out and this hour is also read as an ebb\.$/);
  assert.match(aged.caution, /bar caution \(estimate\)/);
  assert.match(view(brief({wave: 3}), forecast({toward: 255, issuedAgeH: 40}), {lang: 'es'}).why, /^El pronóstico WCOFS no está disponible/);
  // No hazard to carry: a small swell stays No bar flag, and no explanation is added.
  const small = view(brief({wave: 1}), forecast({issuedAgeH: 40}));
  assert.deepEqual([small.band, small.reading.why, small.why], ['No bar flag', [], '']);
  // Every source state of the same hour: a missing cross-check is never calmer than any readable one, at an entrance with a bearing.
  const states = [OUT, {kind: 'in', speedKn: 1, towardDeg: 80, validAt: 0}, {kind: 'across', speedKn: 1, towardDeg: 170, validAt: 0}, {kind: 'weak', speedKn: 0.2, towardDeg: 0, validAt: 0}];
  for (const wave of [0.5, 2, 3, 5, 7, 11]) for (const h of [1, 3, 5, 7, 9, 11]) {
    const gone = read(at(h), {wave, offshore: MISSING});
    for (const s of states) assert.ok(BAR_RANK[gone.band] >= BAR_RANK[read(at(h), {wave, offshore: s}).band], `${wave} ft at +${h} h vs ${s.kind}`);
  }
  // An entrance with no vetted bearing is never compared, fresh or old: the same reading either way.
  const fh = view(brief({wave: 3, entrance: HUMBOLDT}), forecast({issuedAgeH: 10})), oh = view(brief({wave: 3, entrance: HUMBOLDT}), forecast({issuedAgeH: 40}));
  assert.deepEqual([oh.band, oh.reading.why], [fh.band, fh.reading.why]);
});

test('an assumed ebb keeps the opposing-wind driver: wind blowing in against the ebb is a caution even with a small swell', () => {
  const wind = {windKnots: 15, windDirectionDeg: 260};
  const flood = read(at(3), {wave: 1, wind, offshore: OUT});
  assert.deepEqual([flood.timing.phase, flood.ebbAssumed, flood.band], ['flood', true, 'Caution']);
  assert.equal(read(at(3), {wave: 1, wind: {windKnots: 15, windDirectionDeg: 80}, offshore: OUT}).band, 'No bar flag');
  assert.equal(read(at(3), {wave: 1, wind: {windKnots: 5, windDirectionDeg: 260}, offshore: OUT}).band, 'No bar flag');
  assert.equal(read(at(3), {wave: 1, wind}).band, 'No bar flag', 'a flood with nothing running out is not an ebb');
  // The same through the view; a lost cross-check also keeps the wind driver.
  const b = brief({wave: 1}), brf = {...b, bar: {...b.bar, hours: hoursAt(EVENTS, 1, {windKnots: 15, windDirectionDeg: 260})}};
  assert.equal(view(brf, forecast({toward: 255})).band, 'Caution');
  assert.equal(view(brf, forecast({toward: 255, issuedAgeH: 40})).band, 'Caution');
  assert.equal(view(brf, forecast({toward: 75})).band, 'No bar flag');
});

test('near slack the hour is also read as an ebb, because the harbor current can turn later than the tide', () => {
  const before = read(at(5, 40), {wave: 3});
  assert.deepEqual([before.timing.phase, before.band, before.why, before.flow], ['slack', 'Caution', ['slack-ebb'], null]);
  assert.deepEqual([read(at(5, 40), {wave: 2}).band, read(at(5, 40), {wave: 2}).why], ['No bar flag', []]);
  const v = view(brief({wave: 3}), forecast({toward: 80}), {now: new Date(at(5, 40))});
  assert.match(v.why, /^Near slack the harbor's current can already be ebbing, so this hour is also read as an ebb\.$/);
  assert.match(v.caution, /^Near slack with 3 ft at 10 s swell: bar caution \(estimate\)\.$/);
  assert.match(view(brief({wave: 3}), forecast({toward: 80}), {now: new Date(at(5, 40)), lang: 'es'}).why, /^Cerca de la marea parada la corriente del puerto/);
});

test('words, missing data: no tide events, no swell, no forecast, no hourly readings', () => {
  const noTide = view(brief({events: [], wave: 1}));
  assert.match(noTide.timing, /^Flood or ebb not judged: the tide predictions have no high and low around this hour\.$/);
  assert.equal(noTide.band, 'Unknown');
  const noSwell = view(brief({wave: null}));
  assert.match(noSwell.caution, /^Bar unknown \(estimate\): no swell reading for this hour\.$/);
  assert.equal(noSwell.band, 'Unknown');
  assert.match(view(brief(), null).wcofs, /unavailable for this hour \(the feed did not publish it\)/);
  const none = view(brief({count: 0}));
  assert.match(none.timing, /Entrance not judged: no hourly readings\./);
  assert.equal(none.band, 'Unknown');
  assert.equal(view({...brief(), bar: null}), null);
});

test('words: a day that is not today names its hour, and no sentence calls the bar safe, open or clear to cross', () => {
  const later = view(brief({wave: 2, from: 2, count: 8}), forecast(), {now: new Date(at(40))});
  assert.match(later.timing, /^For 7 am: Flooding/);
  const all = [];
  for (const wave of [null, 0.5, 3, 6, 11]) for (const [tide, swell] of [['fresh', 'fresh'], ['stale', 'fresh'], ['fresh', 'stale']]) for (const f of [forecast(), null]) for (const lang of ['en', 'es']) {
    const v = view(brief({wave, tide, swell}), f, {lang});
    all.push(v.title, v.timing, v.turns, v.caution, v.why, v.wcofs, v.basis, v.foot);
  }
  for (const s of all) assert.doesNotMatch(s, /\b(?:safe|safely|open|clear to cross|good to go|go\b)/i, s);
});

test('Spanish: every sentence reads in Spanish, with the estimate and not-for-navigation wording', () => {
  const v = view(brief({wave: 6}), forecast(), {lang: 'es', now: new Date(at(9, 10))});
  assert.match(v.title, /^Corriente en Morro Bay entrance \(estimación\)$/);
  assert.match(v.timing, /^Vaciante: el agua sale\./);
  assert.match(v.caution, /^Vaciante con oleaje de 6 ft a 10 s: condiciones peligrosas en la barra \(estimación\)\.$/);
  assert.match(v.foot, /No apto para navegación/);
});

// ---- layout at 390 px, the real component in headless Chromium ------------------------------------------------------------
const needsChromium = {skip: !existsSync(chromium.executablePath()) && 'chromium not installed'};
const ROOT = new URL('..', import.meta.url).pathname;
let bundle, css;
async function load() {
  if (bundle) return;
  const out = join(await mkdtemp(join(tmpdir(), 'entrance-current-')), 'bundle.js');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      import {EntranceCurrent} from './web/brief/EntranceCurrent.tsx';
      import {regionalForecast} from './web/brief/Brief.tsx';
      import {region} from './web/state.ts';
      import {language} from './web/i18n.ts';
      import {h, render} from 'preact';
      window.__t = {EntranceCurrent, regionalForecast, region, language, h, render};`},
    bundle: true, format: 'iife', platform: 'browser', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
    loader: {'.css': 'empty'}});
  bundle = await readFile(out, 'utf8');
  css = (await Promise.all(['web/tokens.css', 'web/ui/ui.css', 'web/app/app.css'].map(f => readFile(join(ROOT, f), 'utf8')))).join('\n');
}

async function layout(width, lang, args) {
  await load();
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await (await browser.newContext({viewport: {width, height: 844}, deviceScaleFactor: 1, isMobile: true, hasTouch: true})).newPage();
    await page.setContent(`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style><style>body{margin:0;padding:0 16px;background:var(--bg,#000);color:var(--text)}</style></head><body><div id="root"></div></body></html>`);
    await page.addScriptTag({content: bundle});
    return await page.evaluate(({brief, forecast, now, lang, tz}) => {
      const m = window.__t;
      m.region.value = 'morro-bay'; m.regionalForecast.value = forecast; m.language.value = lang;
      m.render(m.h(m.EntranceCurrent, {brief, tz, now: new Date(now)}), document.getElementById('root'));
      const box = document.querySelector('.app-entrance');
      const doc = document.documentElement, rect = box.getBoundingClientRect();
      const paragraphs = [...box.querySelectorAll('p')].map(p => ({cls: p.className, right: p.getBoundingClientRect().right, clipped: p.scrollWidth > p.clientWidth + 1, font: parseFloat(getComputedStyle(p).fontSize), text: p.textContent}));
      return {innerWidth, scrollWidth: doc.scrollWidth, right: rect.right, left: rect.left, paragraphs, order: [...box.children].map(c => c.className.split(' ')[0]), detail: box.querySelector('details,button') !== null};
    }, args);
  } finally { await browser.close(); }
}

for (const [width, lang] of [[390, 'en'], [390, 'es'], [320, 'en']]) {
  test(`layout at ${width} px (${lang}): one column, every line wraps inside the screen, nothing scrolls sideways`, needsChromium, async () => {
    const b = brief({wave: 6});
    const r = await layout(width, lang, {brief: JSON.parse(JSON.stringify(b)), forecast: forecast({toward: 80}), now: at(9, 10), lang, tz: TZ});
    assert.equal(r.innerWidth, width);
    assert.ok(r.scrollWidth <= width, `page scrolls sideways: ${r.scrollWidth} > ${width}`);
    assert.ok(r.left >= 0 && r.right <= width, `box ${r.left}..${r.right}`);
    assert.deepEqual(r.order, ['app-entrance-title', 'app-entrance-timing', 'app-entrance-turns', 'app-entrance-caution', 'app-entrance-wcofs', 'app-entrance-foot']);
    for (const p of r.paragraphs) {
      assert.ok(p.right <= width, `${p.cls} runs to ${p.right}`);
      assert.equal(p.clipped, false, `${p.cls} is clipped`);
      assert.ok(p.font >= 11, `${p.cls} font ${p.font}`);
      assert.ok(p.text.length > 0, p.cls);
    }
    assert.equal(r.detail, true);
  });
}

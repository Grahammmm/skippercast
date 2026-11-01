// RF1740-1: a trip window whose departure or return hour has no bar reading, or whose times are not dates or
// reversed, reads as unknown (crossingCheck in packages/coast/src/bar-conditions.ts) and gets the existing
// "bar caution or unknown" reason in the boat brief (daily.ts screen); it is never read as a clear bar.
import test from 'node:test';
import assert from 'node:assert/strict';
import fixture from './fixtures/coast/skippercast-report.json' with {type: 'json'};

const {barHours, barDay, crossingCheck, crossingHours, entranceFor} = await import('../packages/coast/src/bar-conditions.ts');
const {buildDaily} = await import('../packages/coast/src/daily.ts');
const {slo} = await import('../packages/coast/src/counties.ts');

const HOUR = 3_600_000;
const iso = ms => new Date(ms).toISOString();
const at = text => Date.parse(`2026-10-09T${text}:00.000Z`);
const morro = entranceFor('slo', 'central');
const REASON = /bar caution or unknown at departure or return/;

/** A bar day from [hour, band] pairs (UTC hour of 9 October). */
const day = pairs => barDay(morro, pairs.map(([h, band]) => ({at: iso(at(`${h}:00`)), band, tide: {stage: 'flood', midEbb: false, fraction: null},
  swell: {heightFt: 1, periodS: 10, basis: 'nearshore', longPeriodS: null}, windAgainst: false, reasons: []})));
const clear = hs => day(hs.map(h => [h, 'No bar flag']));

test('both ends read No bar flag: known, with the departure and return readings', () => {
  const check = crossingCheck(clear([17, 18, 19, 20, 21, 22, 23]), iso(at('18:00')), iso(at('22:00')));
  assert.equal(check.known, true);
  assert.equal(check.departure.at, iso(at('18:00')));
  assert.equal(check.return.at, iso(at('22:00')));
  assert.deepEqual(check.hours.map(h => h.at), [18, 21, 22].map(h => iso(at(`${h}:00`))));
});

test('a gap at the return or the departure hour reads unknown', () => {
  const noReturn = crossingCheck(clear([17, 18, 19, 20]), iso(at('18:00')), iso(at('23:00')));
  assert.deepEqual([noReturn.known, noReturn.return, noReturn.departure.at], [false, null, iso(at('18:00'))]);
  const noDeparture = crossingCheck(clear([20, 21, 22, 23]), iso(at('18:00')), iso(at('22:00')));
  assert.deepEqual([noDeparture.known, noDeparture.departure, noDeparture.return.at], [false, null, iso(at('22:00'))]);
  // A departure reading half an hour late still counts; one exactly an hour late does not.
  const late = barDay(morro, clear([19, 20, 21]).hours.concat({...clear([18]).hours[0], at: iso(at('18:30'))}));
  assert.equal(crossingCheck(late, iso(at('18:00')), iso(at('21:00'))).known, true);
  assert.equal(crossingCheck(clear([19, 20, 21]), iso(at('18:00')), iso(at('21:00'))).known, false);
  // An empty day (no hours at all) is unknown, never clear.
  assert.deepEqual(crossingCheck(barDay(morro, []), iso(at('18:00')), iso(at('21:00'))), {hours: [], departure: null, return: null, known: false});
});

test('times that are not dates read unknown with no hours', () => {
  const hours = clear([17, 18, 19, 20, 21, 22]);
  for (const [start, end] of [['not a date', iso(at('21:00'))], [iso(at('18:00')), ''], [undefined, iso(at('21:00'))], [iso(at('18:00')), null]]) {
    const check = crossingCheck(hours, start, end);
    assert.equal(check.known, false, `${start} → ${end}`);
    if (Number.isNaN(Date.parse(start))) assert.equal(check.departure, null);
    if (Number.isNaN(Date.parse(end))) assert.equal(check.return, null);
  }
  assert.deepEqual(crossingCheck(hours, 'x', 'y'), {hours: [], departure: null, return: null, known: false});
});

test('a window that does not end after it starts reads unknown, even with readings at both times', () => {
  const hours = clear([17, 18, 19, 20, 21, 22]);
  const reversed = crossingCheck(hours, iso(at('21:00')), iso(at('18:00')));
  assert.ok(reversed.departure && reversed.return, 'readings exist at both times');
  assert.equal(reversed.known, false);
  assert.equal(crossingCheck(hours, iso(at('19:00')), iso(at('19:00'))).known, false, 'zero length');
});

test('a hazardous crossing hour is still seen whether or not the window is known', () => {
  const known = crossingCheck(day([[18, 'Hazardous'], [19, 'No bar flag'], [20, 'No bar flag'], [21, 'No bar flag']]), iso(at('18:00')), iso(at('21:00')));
  assert.equal(known.known, true);
  assert.ok(known.hours.some(h => h.band === 'Hazardous'));
  const unknown = crossingCheck(day([[18, 'Hazardous'], [19, 'No bar flag']]), iso(at('18:00')), iso(at('22:00')));
  assert.equal(unknown.known, false);
  assert.ok(unknown.hours.some(h => h.band === 'Hazardous'), 'the screen drops on this hour even though the return reading is missing');
});

test('crossingHours is unchanged: the hours of crossingCheck, as in the existing day roll-up case', () => {
  const hours = barHours({hours: [17, 18, 19, 20, 21, 22, 23].map(h => ({at: iso(at(`${h}:00`)), windKnots: 5, gustKnots: 8, waveFt: 4, wavePeriodS: 10})), site: undefined, entrance: morro, tideEvents: fixture.tideEvents});
  const d = barDay(morro, hours);
  const expected = [18, 21, 22].map(h => iso(at(`${h}:00`)));
  assert.deepEqual(crossingHours(d, iso(at('18:00')), iso(at('22:00'))).map(h => h.at), expected);
  assert.deepEqual(crossingCheck(d, iso(at('18:00')), iso(at('22:00'))).hours.map(h => h.at), expected);
  assert.deepEqual(crossingHours(d, 'x', iso(at('22:00'))).map(h => h.at), [21, 22].map(h => iso(at(`${h}:00`))), 'one bad time keeps the other end, as before');
});

// The boat brief at Morro Bay, built from the bar test fixture with light wind and a chosen nearshore height.
const now = new Date(Date.parse(fixture.generatedAt) + 10 * 60_000);
const start = Date.parse(fixture.forecasts[1].hours[0].at);
function report(nearFt) {
  const out = structuredClone(fixture);
  out.alerts = [];
  const hours = Array.from({length: 48}, (_, i) => ({at: iso(start + i * HOUR), windKnots: 5, gustKnots: 8, windDirectionDeg: 300, waveFt: 3, wavePeriodS: 10, swellFt: 2.5, swellPeriodS: 10, airTempF: 60, precipPct: 0}));
  out.forecasts = out.forecasts.map(f => f.id === 'central' || f.id === 'north' ? {...f, hours} : f);
  out.nearshore = [{id: 'mop-test', name: 'Morro Bay entrance', areaId: 'central', lat: 35.37, lon: -120.87, sourceId: 'cdip', issuedAt: iso(now.getTime() - 2 * HOUR), fetchedAt: iso(now.getTime() - 20 * 60_000),
    hours: Array.from({length: 16}, (_, i) => ({at: iso(start - 3 * HOUR + i * 3 * HOUR), waveFt: nearFt, periodS: 10, directionDeg: 280, qualityFlag: null, secondaryFlag: null})),
    url: 'https://cdip.ucsd.edu', kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 180, waterDepthM: 15, depthDatum: 'MSL', directionConvention: 'from degrees true', modelInputCycleAt: null, validThrough: iso(start + 42 * HOUR)}];
  return out;
}
const area = id => slo.areas.find(a => a.id === id);

test('buildDaily: a window crossing in No bar flag hours carries no bar reason; every kept window is known at both ends', () => {
  const daily = buildDaily(report(1), slo, area('central'), 'boat', '2026-10-09', now);
  assert.ok(daily.bar && daily.windows.length > 0);
  for (const window of daily.windows) {
    const check = crossingCheck(daily.bar, window.start, window.end);
    assert.equal(check.known, true, window.start);
    assert.equal(window.reasons.some(r => REASON.test(r)), check.hours.some(h => h.band !== 'No bar flag'), window.start);
  }
  assert.ok(daily.windows.some(w => !w.reasons.some(r => REASON.test(r))), 'a clear crossing gets no bar reason');
});

test('buildDaily: a hazardous crossing hour still drops the window; no bar for the area adds no reason', () => {
  const hazardous = buildDaily(report(4), slo, area('central'), 'boat', '2026-10-09', now);
  assert.ok(hazardous.bar.hazardous.length > 0);
  for (const window of hazardous.windows) assert.ok(!crossingHours(hazardous.bar, window.start, window.end).some(h => h.band === 'Hazardous'), window.start);
  const north = buildDaily(report(4), slo, area('north'), 'boat', '2026-10-09', now);
  assert.equal(north.bar, null);
  assert.ok(north.windows.length > 0);
  assert.ok(!north.windows.some(w => w.reasons.some(r => REASON.test(r))));
});

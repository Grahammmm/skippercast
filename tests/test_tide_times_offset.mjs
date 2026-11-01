// RF1740-4: tide-event, tide-curve, sunrise and sunset times without a `Z` or
// `±HH:MM` offset are unknown in the bar and shore readings (Date.parse would
// read them as device-local time), so one report reads the same in any zone.
import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';

const {barTide, barHours, entranceFor} = await import('../packages/coast/src/bar-conditions.ts');
const {tidePhase, isTwilight, shoreHours, shoreDay} = await import('../packages/coast/src/shore-conditions.ts');

const HOUR = 3_600_000;
const z = text => `2026-11-01T${text}:00Z`;
const ms = text => Date.parse(z(text));
/** The same instant written with a -07:00 offset (PDT wall clock). */
const pdt = iso => new Date(Date.parse(iso) - 7 * HOUR).toISOString().slice(0, 19) + '-07:00';
/** The same instant with no offset at all (the form that must read unknown). */
const bare = iso => new Date(Date.parse(iso)).toISOString().slice(0, 19);
// High 16:12, low 22:40, high 04:50 next day (UTC).
const eventsZ = [{at: z('16:12'), type: 'H', heightFt: 4.8}, {at: z('22:40'), type: 'L', heightFt: 0.4}, {at: '2026-11-02T04:50:00Z', type: 'H', heightFt: 5.1}];
const restamp = (events, f) => events.map(e => ({...e, at: f(e.at)}));
const sunriseZ = z('14:20'), sunsetZ = '2026-11-02T01:05:00Z';
const morro = entranceFor('slo', 'central');
const forecast = Array.from({length: 18}, (_, i) => {
  const at = new Date(ms('10:00') + i * HOUR).toISOString();
  // Calm before dawn, rougher in daylight, so the daylight roll-up has a different best hour.
  const waveFt = i < 4 ? 1 : 6;
  return {at, windKnots: 5, gustKnots: 8, windDirectionDeg: 90, waveFt, wavePeriodS: 10, swellFt: waveFt - 0.5, swellPeriodS: 10, airTempF: 60, precipPct: 0};
});
const shore = (tideEvents, sunrise, sunset, tides = []) => shoreHours({hours: forecast, site: undefined, countyId: 'slo', area: {id: 'central'}, tideEvents, tides, sunrise, sunset});
const bar = tideEvents => barHours({hours: forecast, site: undefined, entrance: morro, tideEvents});

test('the same instants as Z and as -07:00 give identical bar and shore readings', () => {
  const eventsPdt = restamp(eventsZ, pdt);
  assert.equal(eventsPdt[0].at, '2026-11-01T09:12:00-07:00');
  for (const t of ['15:00', '16:12', '18:00', '22:40', '23:30']) {
    assert.ok(isDeepStrictEqual(barTide(ms(t), eventsZ), barTide(ms(t), eventsPdt)), `barTide at ${t}`);
    assert.ok(isDeepStrictEqual(tidePhase(ms(t), eventsZ), tidePhase(ms(t), eventsPdt)), `tidePhase at ${t}`);
  }
  assert.equal(barTide(ms('18:00'), eventsPdt).stage, 'ebb');
  assert.equal(tidePhase(ms('18:00'), eventsPdt).phase, 'falling');
  assert.ok(isDeepStrictEqual(bar(eventsZ), bar(eventsPdt)), 'bar hours');
  const hz = shore(eventsZ, sunriseZ, sunsetZ), hp = shore(eventsPdt, pdt(sunriseZ), pdt(sunsetZ));
  assert.ok(isDeepStrictEqual(hz, hp), 'shore hours');
  assert.ok(isDeepStrictEqual(shoreDay(hz, sunriseZ, sunsetZ, 270), shoreDay(hp, pdt(sunriseZ), pdt(sunsetZ), 270)), 'shore day');
  assert.equal(isTwilight(ms('14:00'), pdt(sunriseZ), null), true);
});

test('offset-less tide events read a null phase in bar and shore, without throwing', () => {
  const eventsBare = restamp(eventsZ, bare);
  assert.equal(eventsBare[0].at, '2026-11-01T16:12:00');
  for (const t of ['15:00', '16:12', '18:00', '23:30']) {
    assert.equal(barTide(ms(t), eventsBare).stage, null, `barTide at ${t}`);
    assert.equal(tidePhase(ms(t), eventsBare).phase, null, `tidePhase at ${t}`);
  }
  assert.ok(bar(eventsBare).every(h => h.tide.stage === null));
  assert.ok(shore(eventsBare, null, null).every(h => h.tide.phase === null));
  // One offset-less event among good ones is dropped, not read as local time.
  const mixed = [eventsZ[0], {...eventsZ[1], at: bare(eventsZ[1].at)}];
  assert.equal(barTide(ms('18:00'), mixed).stage, null);
  assert.equal(tidePhase(ms('18:00'), mixed).phase, null);
  // An offset-less tide-curve point gives no height.
  assert.equal(tidePhase(ms('18:00'), [], [{at: z('18:00'), heightFt: 3}]).heightFt, 3);
  assert.equal(tidePhase(ms('18:00'), [], [{at: bare(z('18:00')), heightFt: 3}]).heightFt, null);
});

test('offset-less sunrise and sunset: no twilight, and the day uses all hours as with null', () => {
  assert.equal(isTwilight(ms('14:20'), bare(sunriseZ), bare(sunsetZ)), false);
  assert.equal(isTwilight(Date.parse(sunsetZ), bare(sunriseZ), bare(sunsetZ)), false);
  assert.equal(isTwilight(ms('14:20'), sunriseZ, sunsetZ), true);
  const hours = shore(eventsZ, null, null);
  const unknown = shoreDay(hours, null, null, 270), lit = shoreDay(hours, sunriseZ, sunsetZ, 270);
  assert.ok(isDeepStrictEqual(shoreDay(hours, bare(sunriseZ), bare(sunsetZ), 270), unknown), 'both offset-less');
  assert.ok(isDeepStrictEqual(shoreDay(hours, sunriseZ, bare(sunsetZ), 270), unknown), 'sunset offset-less');
  assert.ok(!isDeepStrictEqual(lit, unknown), 'daylight known changes the roll-up');
  assert.equal(unknown.best?.at, forecast[0].at);
  assert.ok(isDeepStrictEqual(shore(eventsZ, bare(sunriseZ), bare(sunsetZ)), hours), 'shore hours ignore offset-less light');
});

test('date-only and other offset-less forms are ignored', () => {
  const dateOnly = [{at: '2026-11-01', type: 'H', heightFt: 4}, eventsZ[1]];
  assert.equal(barTide(ms('18:00'), dateOnly).stage, null);
  assert.equal(tidePhase(ms('18:00'), dateOnly).phase, null);
  assert.equal(isTwilight(ms('00:30'), '2026-11-01', null), false);
  for (const at of ['2026-11-01T16:12:00+0000', '2026-11-01 16:12:00Z', '2026-11-01T16:12:00.1234Z', 'Sun, 01 Nov 2026 16:12:00 GMT', 1793549520000]) {
    const events = [{...eventsZ[0], at}, eventsZ[1]];
    assert.equal(barTide(ms('18:00'), events).stage, null, String(at));
    assert.equal(tidePhase(ms('18:00'), events).phase, null, String(at));
    assert.equal(isTwilight(ms('16:12'), at, null), false, String(at));
  }
});

test('+05:30 offsets, minute precision and fractional seconds with an offset are accepted', () => {
  const ist = iso => new Date(Date.parse(iso) + 5.5 * HOUR).toISOString().slice(0, 19) + '+05:30';
  const forms = [restamp(eventsZ, ist), [{...eventsZ[0], at: '2026-11-01T16:12Z'}, {...eventsZ[1], at: '2026-11-01T15:40:00.000-07:00'}],
    [{...eventsZ[0], at: '2026-11-01T16:12:00.5Z'}, {...eventsZ[1], at: '2026-11-02T04:10:00.25+05:30'}]];
  assert.equal(forms[0][0].at, '2026-11-01T21:42:00+05:30');
  for (const events of forms) {
    assert.equal(barTide(ms('18:00'), events).stage, 'ebb', events[0].at);
    assert.equal(tidePhase(ms('18:00'), events).phase, 'falling', events[0].at);
  }
  assert.ok(isDeepStrictEqual(barTide(ms('18:00'), forms[0]), barTide(ms('18:00'), eventsZ)));
  assert.equal(isTwilight(ms('14:00'), '2026-11-01T19:50:00.000+05:30', null), true);
});

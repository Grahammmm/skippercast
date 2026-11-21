// RF0708-2: web/units.ts is the one kt/ft source for the landing readout, the habitat
// feed and the brief model. Its exact factors leave every number a visitor sees as it was
// with the old rounded spellings (wind/gust 1.943844, swell 3.28084), by sweep and through
// buoyReadings; a missing wind still reads "No reading".
import assert from 'node:assert/strict';
import test from 'node:test';
import {FT_PER_M, KT_PER_MS, M_PER_FT, M_PER_NMI} from '../web/units.ts';
import {airportReading, buoyReading} from '../dist/live-conditions.js';
import {buoyReadings, loadReadout, tideReading} from '../web/landing/readings.ts';
import {prepareCatalogue, t} from '../web/i18n.ts';
import {units} from '../web/unit-choice.ts';
await prepareCatalogue('es');

test('units: exact definitions', () => {
  assert.equal(M_PER_FT, 0.3048);
  assert.equal(M_PER_NMI, 1852);
  assert.ok(Math.abs(FT_PER_M * M_PER_FT - 1) <= 1e-15);
  assert.ok(Math.abs(KT_PER_MS - 1.9438444924406) <= 1e-12);
});

test('units: wind and gust knots unchanged for 0.0..60.0 m/s by 0.1', () => {
  for (let i = 0; i <= 600; i++) {
    const v = i / 10;
    assert.equal(Math.round(v * KT_PER_MS), Math.round(v * 1.943844), `${v} m/s`);
  }
});

test('units: swell feet unchanged for 0.00..15.00 m by 0.01', () => {
  for (let i = 0; i <= 1500; i++) {
    const v = i / 100;
    assert.equal((v * FT_PER_M).toFixed(1), (v * 3.28084).toFixed(1), `${v} m`);
  }
});

const NOW = Date.parse('2026-10-07T20:00:00Z');
const AT = new Date(NOW - 20 * 60000).toISOString();
const source = (station, units, row) => ({name: 'x', status: 'ok', max_age_hours: 2, data: {station, units, observations: [{time: AT, ...row}]}});
const feed = wspd => ({schema_version: 1, region_id: 'morro-bay', generated_at: AT, sources: {
  offshore: source('46028', {WSPD: 'm/s', GST: 'm/s'}, {WSPD: wspd, GST: 10.3}),
  'diablo-spectrum': source('46215', {SwH: 'm'}, {SwH: 1.52}),
}});
const defaults = {temp: 'F', wind: 'kt', height: 'ft'}, metric = {temp: 'C', wind: 'kmh', height: 'm'}, mph = {...defaults, wind: 'mph'};
const full = feed(7.7), tide = {data: [{t: '2026-10-07 19:00', v: '-0.8'}, {t: '2026-10-07 19:40', v: '-0.47'}]};
full.sources.diablo = source('46215', {WTMP: 'degC'}, {WTMP: 15.44});
const read = (lang, ...u) => [...buoyReadings(full, {}, NOW, lang, ...u), tideReading(tide, '9412110', 'Port', NOW, 'Caveat.', lang, ...u)];

const expected = (lang, [wind, gust, speed, swell, water, temp, level, height] = lang === 'es' ? ['15', 'ráfagas de 20', 'kt', '5', '60', '°F', '-0,5', 'ft'] : ['15', 'gusts 20', 'kt', '5.0', '60', '°F', '-0.5', 'ft']) => {
  const es = lang === 'es', buoy = {station: es ? 'la boya x' : 'the x buoy', rule: t('landing.basis.rule.limit', lang, {h: 2}), same: ''};
  return [
    {id: 'wind', label: es ? 'Viento' : 'Wind', reading: wind, unit: speed, detail: gust, source: 'NDBC 46028 · 20 min', stale: false, basis: t('landing.basis.wind', lang, buoy)},
    {id: 'swell', label: es ? 'Oleaje' : 'Swell', reading: swell, unit: height, detail: undefined, source: 'NDBC 46215 · 20 min', stale: false, basis: t('landing.basis.swell', lang, buoy)},
    {id: 'water', label: es ? 'Agua' : 'Water', reading: water, unit: temp, source: 'NDBC 46215 · 20 min', stale: false, basis: t('landing.basis.water', lang, buoy)},
    {id: 'tide', label: es ? 'Marea' : 'Tide', reading: level, unit: height, detail: es ? 'subiendo' : 'rising', source: 'NOAA 9412110 · 20 min', stale: false, basis: t('landing.basis.tide', lang, {station: 'Port', h: 1, note: ' Caveat.'})},
  ];
};
const metricEN = ['28', 'gusts 37', 'km/h', '1.5', '15.4', '°C', '-0.1', 'm'];
test('C1: one shared preference snapshot per load, even when the choice changes', async ({mock}) => {
  const peek = mock.method(units, 'peek', () => metric), info = {name: 'Port', stations: {tide_name: 'Port', tide_note: 'Caveat.'}};
  const fetch = async url => { if (url.endsWith('/region.json')) { peek.mock.mockImplementation(() => defaults); return Response.json(info); } return Response.json(url.startsWith('/feeds/') ? full : tide); };
  assert.deepEqual(await loadReadout(fetch, 'fixture', () => NOW), {readings: expected('en', metricEN), feed: {age: '20 min', stale: false}, place: 'Port'});
  assert.equal(peek.mock.callCount(), 1);
  peek.mock.mockImplementation(() => metric); assert.deepEqual(read('en'), expected('en', metricEN));
});
test('C2: mph is rounded after conversion and leaves the other tiles as before', () => {
  const f = structuredClone(full); Object.assign(f.sources.offshore.data.observations[0], {WSPD: 7.9, GST: 9.56});
  assert.deepEqual([...buoyReadings(f, {}, NOW, 'en', mph), tideReading(tide, '9412110', 'Port', NOW, 'Caveat.', 'en', mph)], expected('en', ['18', 'gusts 21', 'mph', '5.0', '60', '°F', '-0.5', 'ft']));
});
test('C3: metric readout rounds swell and negative tide in metres', () => assert.deepEqual(read('en', metric), expected('en', metricEN)));
test('C4: Celsius keeps the brief tiles’ precision and the Spanish decimal comma', () =>
  assert.deepEqual(read('es', metric), expected('es', ['28', 'ráfagas de 37', 'km/h', '1,5', '15,4', '°C', '-0,1', 'm'])));
test('C5: absent, explicit default and bad JSON keep the default bytes in both languages', async context => {
  const prior = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  context.after(() => prior ? Object.defineProperty(globalThis, 'localStorage', prior) : delete globalThis.localStorage);
  Object.defineProperty(globalThis, 'localStorage', {configurable: true, value: {getItem: key => key === 'skippercast-units-v1' ? '{bad' : null}});
  const bad = (await import('../web/unit-choice.ts?bad-json')).units.peek();
  for (const lang of ['en', 'es']) for (const args of [[], [defaults], [bad]]) assert.deepEqual(read(lang, ...args), expected(lang));
});
test('C5: missing readings never gain units or lose their unavailable state', () => {
  const empty = feed(null); empty.sources.diablo = source('46215', {WTMP: 'degC'}, {}); empty.sources['diablo-spectrum'].data.observations = [];
  for (const lang of ['en', 'es']) for (const u of [defaults, mph, metric]) {
    const es = lang === 'es', missing = expected(lang).map(({unit, ...r}) => ({...r, reading: es ? 'Sin lectura' : 'No reading', stale: true, source: r.source.replace('20 min', es ? 'no disponible' : 'unavailable'), ...('detail' in r && {detail: undefined})}));
    assert.deepEqual([...buoyReadings(empty, {}, NOW, lang, u), tideReading(null, '9412110', 'Port', NOW, 'Caveat.', lang, u)], missing);
  }
});

// RF1949-1: dist/live-conditions.js and dist/bite-evidence.js take their factors from
// web/units.ts; the strings they show are the ones the old literals showed.
test('units: dist current speed kt (toFixed 2) unchanged for 0.000..5.000 m/s by 0.001', () => {
  for (let i = 0; i <= 5000; i++) {
    const v = i / 1000;
    assert.equal((v * KT_PER_MS).toFixed(2), (v * 1.943844).toFixed(2), `${v} m/s`);
  }
  assert.equal((Math.hypot(0, 0) * KT_PER_MS).toFixed(2), '0.00');
});

test('units: dist airport wind kt (rounded) unchanged for 0..200 km/h by 0.1', () => {
  for (let i = 0; i <= 2000; i++) {
    const v = i / 10;
    assert.equal(Math.round(v * (1000 / M_PER_NMI)), Math.round(v * (1 / 1.852)), `${v} km/h`);
  }
});

const airport = (kmh) => airportReading({properties: {
  timestamp: new Date(NOW).toISOString(),
  windSpeed: {unitCode: 'wmoUnit:km_h-1', value: kmh},
  windGust: {unitCode: 'wmoUnit:km_h-1', value: kmh},
}}, NOW);

test('units: dist airport wind converts km/h to kt through units.ts; 0 stays 0, not -0', () => {
  const r = airport(37.04);
  assert.ok(Math.abs(r.wind - 20) < 1e-9 && Math.abs(r.gust - 20) < 1e-9);
  const calm = airport(0);
  assert.ok(Object.is(calm.wind, 0) && Object.is(calm.gust, 0));
  assert.equal(airport(-1).wind, null);
});

test('units: dist buoy reading converts m and m/s through units.ts; calm wind is 0, not -0', () => {
  const f = feed(0);
  f.sources.offshore.data.units.WVHT = 'm';
  f.sources.offshore.data.observations[0].WVHT = 1;
  const r = buoyReading(f, 'offshore', NOW);
  assert.ok(Math.abs(r.height - FT_PER_M) < 1e-9);
  assert.ok(Object.is(r.wind, 0));
  assert.ok(Math.abs(r.gust - 10.3 * KT_PER_MS) < 1e-9);
});

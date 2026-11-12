// SC1352-05: station readings, kinds, notes and nearshore ring copy in Spanish. The producers keep their English strings and attach
// catalogue parts; the card and legend resolve them in the page's language. Synthetic fixtures, no network.
import './helpers/spanish-ready.mjs';   // SC1407-09: the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import catalog from '../catalog/station-locations.json' with {type: 'json'};
import strings from '../catalog/app/strings.json' with {type: 'json'};
import {resolveMarkCopy} from '../web/mark-copy.ts';
import {stationPins, STATION_BASIS} from '../web/map/station-model.ts';
import {createStations, stationState} from '../web/map/stations.ts';
import {nearshoreRings, ringBasis, ringMark, ringSummary, RING_BASE, RING_MAX_FT, RING_PER_FT} from '../web/map/nearshore.ts';
import {statusText} from '../web/map/status-copy.ts';
import {railNoteCopies, railNotes} from '../web/map/layers.ts';
import {tideSelection} from '../web/tide-selection.ts';
import {configureStore, syncFromURL} from '../web/state.ts';
import {readPalette} from '../web/map/palette.ts';

const NOW = new Date('2026-10-20T18:00:00Z'), HOUR = 3_600_000;
const ago = h => new Date(+NOW - h * HOUR).toISOString();
const region = {id: 'fixture', stations: {tide: '9412553', nearshore_buoy: '46053', offshore_buoy: '46054', roles: {nearshore_buoy: {stations: ['46053', '46054']}}}};
const buoy = (patch = {}) => ({id: 'buoy-primary', kind: 'observation', name: 'Primary role', url: 'https://example.test', checked_at: ago(0), status: 'ok', station: '46054', fallback_for: '46053',
  data: {station: '46054', units: {WTMP: 'degC', WVHT: 'm', DPD: 'sec', WSPD: 'm/s', GST: 'm/s'}, observations: [{time: ago(1), WTMP: 10, WVHT: 1, DPD: 12, WSPD: 2}]}, ...patch});
const tide = (data = {}, patch = {}) => ({id: 'tides', kind: 'prediction', name: 'Tide', url: 'https://example.test', checked_at: ago(1), status: 'ok', station: '9412553',
  data: {station: '9412553', units: 'ft', datum: 'MLLW', note: 'Not entrance current.', coverage_start: ago(5), coverage_end: ago(-5),
    predictions: [{time: ago(5), height_ft: -0.4, type: 'L'}, {time: ago(-0.2), height_ft: 4, type: 'H'}, {time: ago(-5), height_ft: 2, type: 'L'}], ...data}, ...patch});
const pins = (sources, patch = {}) => stationPins({region, catalog, feed: {region_id: 'fixture', sources}, now: NOW, at: NOW, zone: 'America/Los_Angeles', ...patch});
const pin = (all, key) => all.find(p => p.key === key);
const es = mark => resolveMarkCopy(mark, 'es'), en = mark => resolveMarkCopy(mark, 'en');

test('station_es: buoy and tide readings read Spanish; English fields are untouched; names, ids and datums stay as published', () => {
  const all = pins({buoy: buoy(), tides: tide()});
  const b = pin(all, 'ndbc:46054').mark, td = pin(all, 'coops:9412553').mark;
  assert.equal(en(b).reading, b.reading); assert.equal(en(td).reading, td.reading);
  assert.match(b.reading, /^Seas 3\.3 ft · /);
  const r = es(b).reading;
  assert.match(r, /^Oleaje 3,3 ft · \d+ oct, \d\d:\d\d · actual; Período 12,0 s/);
  assert.match(r, /Agua 50,0 °F/); assert.match(r, /Viento 3,9 kt/); assert.match(r, /Ráfaga: no disponible$/);
  assert.ok(!/Seas|Period|fresh|unavailable/.test(r));
  assert.equal(es(b).kind, 'Boya de observación'); assert.equal(es(td).kind, 'Estación de predicción de marea');
  assert.match(es(b).name, /46054 \(respaldo de 46053\)$/); assert.ok(es(b).name.startsWith(b.name.split(' (')[0]));
  const t = es(td).reading;
  assert.match(t, /^Marea evento de pleamar: 4,0 ft MLLW · válida /); assert.match(t, /; obtenido .* · actual · cobertura .* – .*\. Not entrance current\.$/);
  assert.equal(es(td).basis.slice(0, 20), strings.strings['map.station.basis'].es.slice(0, 20)); assert.equal(strings.strings['map.station.basis'].en, STATION_BASIS);
  assert.equal(pin(all, 'coops:9412553').stale, false);
});

test('station_es: a retained or stale reading says last good and desactualizado; the stale decision stays the English one', () => {
  const all = pins({buoy: buoy({status: 'retained', data_retrieved_at: ago(0)}), tides: tide({}, {status: 'retained', data_retrieved_at: ago(40)})});
  assert.equal(pin(all, 'coops:9412553').stale, true);
  assert.match(es(pin(all, 'ndbc:46054').mark).reading, /desactualizado \/ último dato válido; Período/);
  assert.match(es(pin(all, 'coops:9412553').mark).reading, /desactualizado \/ último dato válido/);
});

test('station_es_invalid_and_gap_clocks: the reason is kept, nothing is filled from another station, English decisions stay', () => {
  const none = pin(pins({buoy: buoy(), tides: tide({}, {data_retrieved_at: 'not a time', checked_at: 'bad'})}), 'coops:9412553');
  assert.equal(none.stale, true); assert.equal(es(none.mark).reading, 'Predicción de marea no disponible; no hay un reloj de obtención válido ni datos.');
  const outside = pin(pins({tides: tide({coverage_start: ago(-3), coverage_end: ago(-5)})}), 'coops:9412553');
  assert.match(es(outside.mark).reading, /^Predicción de marea no disponible para la hora seleccionada; obtenido /); assert.equal(outside.stale, true);
  const sparse = pin(pins({tides: tide({predictions: [{time: ago(4), height_ft: 1}, {time: ago(-4), height_ft: 1}]})}), 'coops:9412553');
  assert.match(sparse.mark.reading, /^Tide prediction gap; /); assert.match(es(sparse.mark).reading, /^Vacío en la predicción de marea; /);
  const noCoverage = pin(pins({tides: tide({coverage_start: '', coverage_end: '', predictions: []})}), 'coops:9412553');
  assert.match(es(noCoverage.mark).reading, /cobertura no disponible|^Predicción de marea no disponible/);
  const eventsOnly = pin(pins({tides: tide({predictions: [{time: ago(-0.1), height_ft: 3.14, type: 'L'}]})}), 'coops:9412553');
  assert.match(es(eventsOnly.mark).reading, /^Marea evento de bajamar: 3,1 ft MLLW/);
});

test('station_es_chosen_is_not_default_pin: kinds and the default note follow the language; pins and values do not move', () => {
  const tideChoice = {regionId: 'fixture', defaultStation: '9412553', chosen: '9412110'};
  const all = pins({buoy: buoy(), tides: tide()}, {tideChoice}), plain = pins({buoy: buoy(), tides: tide()});
  const def = pin(all, 'coops:9412553');
  assert.equal(def.mark.kind, 'Region default tide station'); assert.equal(es(def.mark).kind, 'Estación de marea predeterminada de la región');
  assert.match(es(def.mark).reading, /^Estación de marea predeterminada de la región · el Resumen usa la estación que elegiste: 9412110\. Marea /);
  assert.equal(all.some(p => p.key === 'coops:9412110'), false);
  assert.equal(def.mark.reading.replace(/^Region default tide station · the Brief uses your chosen station 9412110\. /, ''), pin(plain, 'coops:9412553').mark.reading);
  const chosenPins = pins({tides: tide()}, {region: {...region, stations: {...region.stations, tide: '9412110'}}, tideChoice: {regionId: 'fixture', defaultStation: '9412553', chosen: '9412110'}});
  assert.equal(es(chosenPins.find(p => p.key === 'coops:9412110').mark).kind, 'Estación de marea elegida');
});

test('station_pending_switch: the layer note carries catalogue parts; Spanish follows the language with no refetch', async t => {
  t.mock.timers.enable({apis: ['setInterval']});
  configureStore({v2: true, storage: null}); syncFromURL('https://example.test/map?region=fixture&layers=stations');
  let fetches = 0; const palette = readPalette(n => /^map-.*-(?:opacity|width)$/.test(n) ? '1' : `token(${n})`), e = {setOverlay() {}, setData() {}};
  const s = createStations({engine: signal(e), zone: () => 'UTC', feed: () => ({region_id: 'fixture', sources: {buoy: buoy(), tides: tide()}}),
    fetchFn: async () => { fetches++; return {ok: true, json: async () => region}; }, palette: () => palette, now: () => NOW});
  t.after(() => { s.destroy(); tideSelection.region.value = null; tideSelection.choice.value = null; });
  assert.equal(stationState.value.note, 'Loading station configuration');
  assert.equal(statusText(stationState.value.note, stationState.value.copy, 'es').text, 'Cargando la configuración de estaciones');
  await new Promise(r => setImmediate(r));
  tideSelection.region.value = {id: 'fixture', bounds: [-125, 34, -119, 36], station: '9412553', name: 'Fixture'}; tideSelection.choice.value = '9412110';
  await new Promise(r => setImmediate(r));
  const {note, copy} = stationState.value;
  assert.match(note, /^3 station locations · latest readings with individual times; Chosen tide station 9412110 is shown in the Brief, not on this layer$/);
  assert.equal(statusText(note, copy, 'es').text, '3 ubicaciones de estaciones · últimas lecturas con sus horas individuales; La estación de marea elegida 9412110 se muestra en el Resumen, no en esta capa');
  assert.equal(statusText(note, copy, 'en').text, note, 'English keeps the producer string');
  assert.equal(railNotes.value.stations, note); assert.ok(railNoteCopies.value.stations?.length);
  assert.equal(fetches, 1, 'reading the note in Spanish asked for nothing more');
});

// ---- nearshore ----
const HOURMS = 3_600_000, NOW2 = new Date('2026-10-09T18:00:00Z'), AT = new Date('2026-10-09T20:00:00Z'), iso = ms => new Date(ms).toISOString();
const site = (patch = {}) => ({id: 'SL345', name: 'Morro Rock', areaId: 'central', lat: 35.36503, lon: -120.87659, sourceId: 'cdip-mop', issuedAt: iso(NOW2 - 6 * HOURMS), fetchedAt: iso(NOW2 - HOURMS),
  url: 'https://example.test/cdip', kind: 'forecast', availability: 'available', freshness: 'current', temporalResolutionMinutes: 60, waterDepthM: 15, depthDatum: 'MSL', directionConvention: 'from degrees true',
  modelInputCycleAt: null, validThrough: null, hours: Array.from({length: 25}, (_, i) => ({at: iso(Date.parse('2026-10-09T12:00:00Z') + i * HOURMS), waveFt: 3 + i * 0.1, periodS: 13, directionDeg: 290, qualityFlag: 0, secondaryFlag: 0})), ...patch});
const label = id => ({id, label: id === 'b' ? 'Other model · x' : 'CDIP MOP · nearshore wave model', url: 'https://example.test', kind: 'forecast', outcome: 'ok', fetchedAt: iso(NOW2 - HOURMS)});
const report = sites => ({schemaVersion: 1, countyId: 'slo', generatedAt: iso(NOW2 - HOURMS), forecasts: [], observations: [], tides: [], tideEvents: [], alerts: [], sources: [label('cdip-mop'), label('b')],
  catches: [], catchStatus: '', habitatStatus: '', visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null}, nearshore: sites});
const ringsOf = sites => nearshoreRings(report(sites), 'central', AT, NOW2);

test('nearshore_es: card, basis and summary read Spanish; the English strings are byte-identical to before', () => {
  const r = ringsOf([site()]), mark = ringMark(r, 'SL345', NOW2, 'America/Los_Angeles');
  assert.equal(mark.kind, 'CDIP MOP model site'); assert.match(mark.basis, /^Model issued .*; retrieved .*\. CDIP MOP nearshore model sites from the bound coast report/);
  const d = es(mark);
  assert.equal(d.kind, 'CDIP MOP: sitio de modelo'); assert.equal(d.name, 'Morro Rock');
  assert.match(d.reading, /^3,8 ft · 13,0 s · desde WNW 290°$/);
  assert.match(d.source, /^CDIP MOP · muestra 9 oct, 13:00 GMT-7 · muestreo del modelo cada 1 h · emitido hace 6 h$/);
  assert.match(d.basis, /^Modelo emitido 9 oct, 05:00; obtenido 9 oct, 10:00\. Sitios del modelo cercano a la costa CDIP MOP del informe costero vinculado/);
  assert.match(d.basis, /Radio del anillo: 4 px más 3 px por pie; los valores de 15 ft o más se dibujan igual\. El sitio está en 15 m de agua \(MSL\)\.$/);
  assert.match(d.basis, /90 minutos.*48 horas.*3 horas.*no una observación de boya ni el oleaje rompiente de una playa/);
  assert.equal(ringBasis('CDIP MOP', 'es').includes('15 ft'), true); assert.equal([RING_BASE, RING_PER_FT, RING_MAX_FT].join(), '4,3,15');
  assert.equal(ringSummary(r, NOW2), '1 nearshore model site · CDIP MOP · issued 6 h ago · ring 4 px + 3 px per ft');
  assert.equal(ringSummary(r, NOW2, 'es'), '1 sitio del modelo cercano a la costa · CDIP MOP · emitido hace 6 h · anillo 4 px + 3 px por pie');
});

test('nearshore_es_model_caveats_and_mixed_products: unknown cadence or depth, under-hour age, mixed products, unknown id', () => {
  const odd = site({id: 'SL1', temporalResolutionMinutes: null, waterDepthM: null, issuedAt: iso(NOW2 - 10 * 60_000)});
  const r = ringsOf([odd, site({id: 'SL2', sourceId: 'b'})]);
  assert.equal(r.product, 'multiple nearshore models');
  assert.equal(ringSummary(r, NOW2, 'es'), '2 sitios del modelo cercano a la costa · varios modelos cercanos a la costa · emitido hace menos de 1 h · anillo 4 px + 3 px por pie');
  const card = es(ringMark(r, 'SL1', NOW2, 'UTC'));
  assert.match(card.source, /intervalo de muestreo del modelo no indicado · emitido hace menos de 1 h$/);
  assert.ok(!card.basis.includes('de agua'), 'no depth sentence without a depth'); assert.equal(card.kind, 'CDIP MOP: sitio de modelo');
  assert.equal(es(ringMark(r, 'SL2', NOW2, 'UTC')).kind, 'Other model: sitio de modelo', 'a supplied product name is never translated');
  assert.equal(ringMark(r, 'nope', NOW2, 'UTC'), null); assert.equal(ringMark(r, null, NOW2, 'UTC'), null);
  assert.match(ringBasis(r.product, 'es'), /^Sitios del modelo cercano a la costa varios modelos cercanos a la costa del informe/);
});

test('catalogue: every new station and nearshore id has matching placeholders in both languages', () => {
  const ids = Object.keys(strings.strings).filter(k => /^map\.(station|nearshore)\./.test(k));
  assert.ok(ids.length >= 40);
  for (const k of ids) {
    const v = strings.strings[k], vars = s => (s.match(/\{\w+\}/g) ?? []).sort().join();
    assert.equal(vars(v.en), vars(v.es), k); assert.ok(v.es.trim(), k);
  }
});

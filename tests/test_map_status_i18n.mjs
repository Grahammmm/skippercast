// SC1352-02/03: water-temperature, contrast, chlorophyll, cloud and offline layer statuses in Spanish. Each producer keeps its
// English string and attaches catalogue parts; the rail and legend resolve them in the page's language at render.
// The bundle is built with esbuild; nothing is fetched.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const ORIGIN = 'https://s.test/map';
const TZ = 'America/Los_Angeles', HOUR = 3_600_000;
const NOW = new Date('2026-10-16T09:00:00Z'), AT = new Date('2026-10-16T09:00:00Z');
const ANALYSED = '2026-10-15T09:00:00Z';
const plain = text => text.replace(/\s/g, ' ');   // ICU puts a no-break space inside "a. m."

let bundle;
async function load() {
  if (bundle) return bundle;
  const out = join(await mkdtemp(join(tmpdir(), 'status-i18n-')), 'bundle.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {LayerRail} from './web/app/LayerRail.tsx';
      export {Legend} from './web/app/Legend.tsx';
      export {railNotes, railNoteCopies, setRailNote} from './web/map/layers.ts';
      export {language, lookup, STRINGS} from './web/i18n.ts';
      export {regionalStatus, analysisStatus, waterTempState} from './web/map/sst.ts';
      export {contrastStatus, contrastState} from './web/map/contrast.ts';
      export {chlorophyllStatus} from './web/map/chlorophyll.ts';
      export {cloudStatus, cloudStatusCopy, frameLabel, frameLabelCopy, NO_FRAMES, OTHER_DAY} from './web/map/clouds.ts';
      export {NOT_SAVED, COAST_NOT_SAVED, TILES_NOT_SAVED, COAST_OFFLINE_COPY, TILES_OFFLINE_COPY} from './web/map/offline.ts';
      export {statusIn, statusText, resolveStatusText, sp} from './web/map/status-copy.ts';
      export {currentsStatus, regionalCurrentsStatus, currentsState} from './web/map/currents.ts';
      export {swellStatus, swellState, nearshoreState} from './web/map/swell.ts';
      export {windStatus, windState} from './web/map/wind.ts';
      export {parseForecast, WAVE_MODEL} from './web/map/forecast-grid.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: preparedRendererPlugins,
  });
  bundle = await import(pathToFileURL(out).href);
  return bundle;
}

const sst = (over = {}) => ({sourceId: 'mur', analysedAt: ANALYSED, fetchedAt: ANALYSED, sampleSpacingDeg: 0, nativeResolutionDeg: 0.01, points: [], ...over});
const ready = (over = {}) => ({state: 'ready', product: 'JPL MUR', maxAgeMs: 72 * HOUR, sst: sst(), ...over});
const listed = (over = {}) => ({state: 'listed', product: 'JPL MUR', maxAgeMs: 72 * HOUR, analysedAt: ANALYSED, layerStatus: 'stale', gradients: true, ...over});

function sstStatuses(m) {
  const at = (feed, hourAt = AT, now = NOW) => m.regionalStatus(true, feed, hourAt, now, TZ);
  return {
    loading: at(null), none: at({state: 'none'}), error: at({state: 'error'}), listedStale: at(listed()), listedNone: at(listed({layerStatus: 'ok', analysedAt: undefined})),
    stale: at(ready({sst: sst({analysedAt: '2026-10-10T09:00:00Z', fetchedAt: '2026-10-10T09:00:00Z'})})),
    afterHour: at(ready(), new Date('2026-10-15T00:00:00Z')), noGrid: at(ready()),
    unbound: m.analysisStatus(true, 'unbound', null, AT, NOW, TZ), reportError: m.analysisStatus(true, 'error', null, AT, NOW, TZ),
    reportExpired: m.analysisStatus(true, 'expired', null, AT, NOW, TZ), reportLoading: m.analysisStatus(true, 'ok', null, AT, NOW, TZ),
    reportNone: m.analysisStatus(true, 'ok', {sources: [], spatial: {}}, AT, NOW, TZ),
    offlineCoast: m.analysisStatus(true, 'error', null, AT, NOW, TZ, true), offlineTiles: m.regionalStatus(true, {state: 'error', network: true}, AT, NOW, TZ, true),
  };
}
function contrastStatuses(m) {
  const at = (feed, hourAt = AT) => m.contrastStatus(true, feed, hourAt, NOW, TZ);
  const cells = {samples: [], spacingDeg: [0.01, 0.01], nativeResolutionDeg: 0.01, sourceId: 'mur', credit: ''};
  return {
    loading: at(null), none: at({state: 'none'}), error: at({state: 'error'}), stale: at(listed()), noFeed: at(listed({layerStatus: 'ok', gradients: true})),
    noGradient: at(listed({layerStatus: 'ok', gradients: false})), afterHour: at({state: 'ready', product: 'JPL MUR', maxAgeMs: 72 * HOUR, analysedAt: ANALYSED, fetchedAt: ANALYSED, ...cells}, new Date('2026-10-15T00:00:00Z')),
    noContrast: at({state: 'ready', product: 'JPL MUR', maxAgeMs: 72 * HOUR, analysedAt: ANALYSED, fetchedAt: ANALYSED, ...cells}),
  };
}

test('every producer branch carries catalogue parts whose English is byte-identical to its own string', async () => {
  const m = await load();
  const all = {...sstStatuses(m), ...Object.fromEntries(Object.entries(contrastStatuses(m)).map(([k, v]) => [`contrast-${k}`, v]))};
  assert.ok(Object.keys(all).length >= 21);
  for (const [name, s] of Object.entries(all)) {
    assert.ok(s.copy?.note && s.copy?.reason, `${name} carries note and reason parts`);
    assert.equal(m.statusIn(s.copy.note, 'en'), s.note, `${name} note`);
    assert.equal(m.statusIn(s.copy.reason, 'en'), s.reason, `${name} reason`);
    assert.equal(m.statusText(s.reason, s.copy.reason, 'en').translated, false, 'English is never re-rendered');
    assert.equal(m.resolveStatusText(s.reason, s.copy.reason, 'en'), s.reason);
  }
  assert.equal(all.offlineCoast.note, m.NOT_SAVED);
  assert.equal(all.offlineCoast.reason, m.COAST_NOT_SAVED);
  assert.equal(all.offlineTiles.reason, m.TILES_NOT_SAVED);
  assert.equal(m.NOT_SAVED, 'not saved for offline');
  assert.equal(m.COAST_NOT_SAVED, 'Coastal readings are not available offline. Save Coastal readings and check the saved pack before leaving coverage.');
  assert.equal(m.TILES_NOT_SAVED, 'These ocean tiles are not available offline. The chart pack does not prefetch them; check the saved pack before leaving coverage.');
  // The off state is the exact object with no copy property.
  assert.equal('copy' in m.regionalStatus(false, null, AT, NOW, TZ), false);
  assert.equal('copy' in m.contrastStatus(false, null, AT, NOW, TZ), false);
});

test('sst_contrast_es_refusal_matrix: each refusal keeps its meaning, its caveat and its numbers in Spanish', async () => {
  const m = await load(), s = sstStatuses(m), c = contrastStatuses(m);
  const es = (status, field = 'reason') => m.resolveStatusText(status[field], status.copy[field], 'es');
  assert.equal(es(s.reportExpired), 'Temperatura del agua no disponible: el informe costero superó su límite de antigüedad.');
  assert.equal(es(s.reportLoading), 'Cargando el informe costero.');
  assert.equal(es(s.loading), 'Cargando el análisis de temperatura superficial de la región.');
  assert.match(es(s.stale), /^Temperatura del agua no disponible: el último análisis de JPL MUR, del 10 oct, superó su límite de antigüedad de 72 horas\.$/);
  assert.match(es(s.afterHour), /es posterior a la hora seleccionada\.$/);
  assert.match(es(s.noGrid), /no es una cuadrícula que se pueda dibujar sin unir vacíos, y no se muestra ningún análisis anterior\.$/);
  assert.equal(es(s.noGrid, 'note'), 'la cuadrícula no se puede dibujar · 15 oct');
  for (const name of ['none', 'error', 'unbound', 'reportError', 'reportNone', 'listedNone']) assert.match(es(s[name]), /^Temperatura del agua no disponible: /, name);
  assert.match(es(c.stale), /^Contraste de temperatura retenido: .*límite de antigüedad de 72 horas\.$/);
  for (const name of ['none', 'error', 'noFeed', 'noGradient', 'afterHour']) assert.match(es(c[name]), /^Contraste de temperatura no disponible: /, name);
  assert.match(es(c.noGradient), /no publica ningún gradiente de temperatura/);
  assert.match(es(c.noContrast), /^No se dibuja nada: .* no supera, en ninguna celda, la suma de sus errores de análisis\.$/);
  // Offline: both sentences keep "check the saved pack before leaving coverage", and the tile sentence does not claim the pack holds them.
  assert.equal(m.resolveStatusText(m.NOT_SAVED, m.COAST_OFFLINE_COPY.note, 'es'), 'no guardado para usar sin conexión');
  assert.equal(es({reason: m.COAST_NOT_SAVED, copy: m.COAST_OFFLINE_COPY}), 'Las lecturas costeras no están disponibles sin conexión. Guarda las lecturas costeras y revisa el paquete guardado antes de salir de la cobertura.');
  assert.equal(es({reason: m.TILES_NOT_SAVED, copy: m.TILES_OFFLINE_COPY}), 'Estas teselas oceánicas no están disponibles sin conexión. El paquete de cartas no las descarga de antemano; revisa el paquete guardado antes de salir de la cobertura.');
  // A refusal draws nothing and carries no stamp.
  for (const status of [...Object.values(s), ...Object.values(c)]) assert.equal(status.drawn, null);
});

test('chlorophyll_and_cloud_status_dates_and_numbers_follow_the_language_and_zone', async () => {
  const m = await load();
  const obs = (sampleAt) => ({state: 'ready', observation: {sampleAt, maxAgeMs: 72 * HOUR, product: 'VIIRS', resolution: [0.0375, 0.0375], cells: []}});
  const fresh = m.chlorophyllStatus(true, obs('2026-10-16T04:00:00Z'), NOW), withheld = m.chlorophyllStatus(true, obs('2026-10-10T04:00:00Z'), NOW);
  assert.equal(fresh.note, 'sample 2026-10-16T04:00:00Z · 5.0 h old');
  assert.equal(m.statusIn(fresh.copy.note, 'en'), fresh.note);
  assert.equal(m.resolveStatusText(fresh.note, fresh.copy.note, 'es'), 'muestra 2026-10-16T04:00:00Z · 5,0 h de antigüedad');
  assert.equal(m.resolveStatusText(withheld.note, withheld.copy.note, 'es'), 'retenido · última muestra 2026-10-10T04:00:00Z');
  for (const [feed, es] of [[null, 'cargando'], [{state: 'error'}, 'no disponible: fallaron las comprobaciones de la fuente'], [{state: 'ready', observation: {...obs('2026-10-10T04:00:00Z').observation, cells: []}, x: 1}, null]]) {
    const st = m.chlorophyllStatus(true, feed, NOW);
    assert.equal(m.statusIn(st.copy.note, 'en'), st.note);
    if (es) assert.equal(m.resolveStatusText(st.note, st.copy.note, 'es'), es);
  }
  assert.equal('copy' in m.chlorophyllStatus(false, null, NOW), false);

  const frame = (offsetMs) => new Date(NOW.getTime() + offsetMs).toISOString();
  for (const offset of [-7 * 60_000, -20_000, 0, 1, 3_600_000]) {
    const at = frame(offset);
    assert.equal(m.statusIn(m.frameLabelCopy(at, NOW, TZ), 'en'), m.frameLabel(at, NOW, TZ), `offset ${offset}`);
  }
  assert.equal(plain(m.statusIn(m.frameLabelCopy(frame(1), NOW, 'UTC'), 'es')), 'observado 9:00 a. m. · antigüedad no disponible (marca de tiempo futura)', 'a future frame is never "0 min ago"');
  assert.equal(plain(m.statusIn(m.frameLabelCopy(frame(-7 * 60_000), NOW, TZ), 'es')), 'observado 1:53 a. m. · hace 7 min');
  assert.equal(plain(m.statusIn(m.frameLabelCopy(frame(-20_000), NOW, TZ), 'es')), 'observado 1:59 a. m. · hace menos de 1 min');
  const cloud = (observedAt) => ({observedAt});
  const cases = [[null, []], [cloud(frame(-HOUR)), []], [cloud(frame(-30 * HOUR)), []], [cloud(frame(-60_000)), [frame(-60_000)]]];
  for (const [image, frames] of cases) {
    assert.equal(m.statusIn(m.cloudStatusCopy(image, frames, NOW, NOW, TZ), 'en'), m.cloudStatus(image, frames, NOW, NOW, TZ));
  }
  assert.equal(m.statusIn(m.cloudStatusCopy(null, [], NOW, NOW, TZ), 'es'), 'sin imágenes para esta zona');
  assert.equal(m.statusIn(m.cloudStatusCopy(cloud(frame(-HOUR)), [], new Date(NOW.getTime() + 30 * HOUR), NOW, TZ), 'es'), 'las imágenes observadas muestran solo hoy');
  assert.equal(plain(m.statusIn(m.cloudStatusCopy(cloud(frame(-HOUR)), [], NOW, NOW, TZ), 'es')), 'sin imagen reciente · última 1:00 a. m.');
  assert.equal(plain(m.statusIn(m.cloudStatusCopy(cloud(frame(-30 * HOUR)), [], NOW, NOW, TZ), 'es')), 'sin imagen reciente · última 2026-10-14 8:00 p. m.');
  assert.equal(plain(m.statusIn(m.frameLabelCopy('2026-11-01T09:30:00Z', new Date('2026-11-01T09:40:00Z'), 'Pacific/Auckland'), 'es')), 'observado 10:30 p. m. · hace 10 min');
});

test('absent, bad or English metadata leaves the producer string whole and never throws', async () => {
  const m = await load(), raw = 'Water temp unavailable: the coast report passed its age limit.';
  assert.equal(m.resolveStatusText(raw, undefined, 'es'), raw);
  assert.equal(m.resolveStatusText(raw, [], 'es'), raw);
  assert.equal(m.resolveStatusText(raw, [m.sp('map.status.sst.reportExpired')], 'en'), raw);
  // The browser's lookup returns an unknown id as text instead of throwing (the Node path throws); the status must not depend on that.
  assert.equal(m.lookup(m.STRINGS, 'no.such.id', 'es', {}, false), 'no.such.id');
  const unchanged = {text: raw, translated: false};
  assert.deepEqual(m.statusText(raw, [{id: 'no.such.id'}], 'es'), unchanged, 'an unknown top-level id keeps the producer string');
  assert.deepEqual(m.statusText(raw, [m.sp('map.status.common.staleNote', {date: {id: 'no.such.id'}})], 'es'), unchanged, 'an unknown nested id keeps the producer string');
  assert.deepEqual(m.statusText(raw, [m.sp('map.status.sst.reportExpired'), {id: 'no.such.id'}], 'es'), unchanged, 'one unknown id among good parts keeps the producer string');
  const badDate = m.statusText(raw, [m.sp('map.status.common.staleNote', {date: {day: 'not a date', tz: TZ}})], 'es');
  assert.deepEqual([badDate.text, badDate.translated], [raw, false], 'an unreadable date falls back to the raw refusal');
  const badZone = m.statusText(raw, [m.sp('map.status.common.staleNote', {date: {day: ANALYSED, tz: 'Not/AZone'}})], 'es');
  assert.deepEqual([badZone.text, badZone.translated], [raw, false]);
});

test('setRailNote keeps the descriptor with the note: an equal note with new parts updates it, clearing removes it, other rails stay', async () => {
  const m = await load(), {setRailNote, railNotes, railNoteCopies, sp} = m;
  const keep = {...railNotes.value}, keepCopies = {...railNoteCopies.value};
  try {
    setRailNote('fleet', '2 charter grounds');
    setRailNote('water-temp', 'no fresh analysis · last Oct 10', [sp('map.status.common.staleNote', {date: {day: '2026-10-10T15:00:00Z', tz: TZ}})]);
    const first = railNoteCopies.value['water-temp'];
    setRailNote('water-temp', 'no fresh analysis · last Oct 10', [sp('map.status.common.staleNote', {date: {day: '2026-10-10T15:00:00Z', tz: TZ}})]);
    assert.equal(railNoteCopies.value['water-temp'], first, 'an identical write changes nothing');
    setRailNote('water-temp', 'no fresh analysis · last Oct 10', [sp('map.status.common.staleNote', {date: {day: '2026-10-10T15:00:00Z', tz: 'Pacific/Kiritimati'}})]);
    assert.notEqual(railNoteCopies.value['water-temp'], first, 'same English, other zone: the descriptor is replaced');
    assert.equal(m.statusIn(railNoteCopies.value['water-temp'], 'es'), 'sin análisis reciente · último 11 oct');
    setRailNote('water-temp', 'loading');
    assert.equal(railNoteCopies.value['water-temp'], undefined, 'a two-argument write clears the descriptor');
    setRailNote('water-temp', '', [sp('map.status.common.loading')]);
    assert.equal(railNoteCopies.value['water-temp'], undefined, 'an empty note holds no descriptor');
    assert.equal(railNotes.value.fleet, '2 charter grounds');
  } finally { railNotes.value = keep; railNoteCopies.value = keepCopies; }
});

test('status_en_es_en_retained_without_refetch: the real rail and legend switch language from the same state', async t => {
  const m = await load(), s = m.state;
  const priorNotes = m.railNotes.value, priorCopies = m.railNoteCopies.value, priorWater = m.waterTempState.value;
  t.after(() => { m.language.value = 'en'; m.railNotes.value = priorNotes; m.railNoteCopies.value = priorCopies; m.waterTempState.value = priorWater; });
  s.configureStore({v2: true, storage: null});
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&layers=water-temp,clouds`);
  const refused = m.regionalStatus(true, listed(), AT, NOW, TZ);
  m.waterTempState.value = refused;
  m.setRailNote('water-temp', refused.note, refused.copy.note);
  m.setRailNote('clouds', 'Frame 13:50 UTC');
  const rail = lang => { m.language.value = lang; return m.render(m.h(m.LayerRail)); }, legend = lang => { m.language.value = lang; return m.render(m.h(m.Legend)); };
  const en = rail('en'), es = rail('es');
  assert.ok(en.includes('no fresh analysis · last Oct 15') && !/Detalles|lang="en"/.test(en), 'English shows the note bare');
  assert.ok(es.includes('sin análisis reciente · último 15 oct'), 'Spanish shows the note in Spanish');
  assert.equal(es.includes('<span lang="en">no fresh analysis'), false, 'a translated note is not labelled English');
  assert.ok(es.includes('Detalles de la fuente (en inglés): <span lang="en">Frame 13:50 UTC</span>'), 'a producer with no descriptor stays whole and labelled English');
  const lEn = legend('en'), lEs = legend('es');
  assert.ok(lEn.includes(refused.reason) && !/lang="en"/.test(lEn.split(refused.reason)[0].slice(-80)), 'English legend reason is the producer string');
  assert.ok(lEs.includes('Temperatura del agua no disponible: el último análisis de JPL MUR, del 15 oct, superó su límite de antigüedad de 72 horas.'));
  assert.equal(lEs.includes(`<span lang="en">${refused.reason}`), false);
  assert.equal(legend('en'), lEn, 'back to English restores the same bytes');
  assert.equal(rail('en'), en);
  // A legend status with no descriptor (a producer that attaches none) keeps the labelled-English path.
  m.waterTempState.value = {...refused, copy: undefined};
  assert.ok(legend('es').includes(`Detalles de la fuente (en inglés): <span lang="en">${refused.reason}</span>`));
});

// SC1352-03: currents, swell and wind. Fixtures are synthetic.
const WCOFS = (over = {}) => ({id: 'wcofs', kind: 'forecast', label: 'NOAA WCOFS surface forecast', url: 'https://example.test/wcofs', fetchedAt: '2026-10-07T11:50:00Z', issuedAt: '2026-10-07T03:00:00Z',
  sampleAt: null, nativeResolutionKm: 1, sampleStride: 1, horizontalDatum: 'NAD83', surfaceOnly: true, attribution: 'NOAA', license: 'public-domain-us-gov', limitations: 'Surface only.',
  frames: [{validAt: '2026-10-07T12:00:00Z', cells: Array.from({length: 64}, (_, k) => ({lat: 35.5 - Math.floor(k / 8) * 0.04, lon: -121 + (k % 8) * 0.04, uMs: 0.3, vMs: 0.1, speedKnots: 0.6, towardDeg: 70}))}], ...over});
const packet = (...currents) => ({schemaVersion: 1, countyId: 'slo', generatedAt: '2026-10-07T11:55:00Z', currents, cloud: null, sources: []});
const CNOW = new Date('2026-10-07T12:20:00Z'), CAT = new Date('2026-10-07T12:00:00Z');
const ISSUED_S = Date.parse('2026-10-09T06:00:00Z'), SNOW = new Date('2026-10-09T18:00:00Z'), SAT = new Date('2026-10-09T20:00:00Z');
const hoursOf = (n, from = ISSUED_S / 1000) => Array.from({length: n}, (_, k) => from + k * 3600);
function wave(m, {retrieved = SNOW.getTime() - HOUR, issued = ISSUED_S / 1000, hours = hoursOf(48), values = (i, j, k) => [2 + i * 0.5 + j * 0.3 + k * 0.5, 11.2 + i * 1.2, 290 + j * 5]} = {}) {
  const lats = [35.05, 35.3, 35.55], lons = [-121.75, -121.5, -121.25], pts = [], series = [];
  const units = Object.fromEntries(['swell_wave_height', 'swell_wave_period', 'swell_wave_direction', 'wind_wave_height', 'wind_wave_period', 'wind_wave_direction', 'secondary_swell_wave_height', 'secondary_swell_wave_period', 'secondary_swell_wave_direction']
    .map(v => [v, v.endsWith('_height') ? 'ft' : v.endsWith('_period') ? 's' : '°']));
  for (let j = 0; j < 3; j++) for (let i = 0; i < 3; i++) {
    pts.push([`offshore-${j}-${i}`, lats[j], lons[i]]);
    const p = hours.map((_, k) => values(i, j, k)), col = f => p.map(v => v[f]);
    series.push({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...units}, hourly: {time: hours, swell_wave_height: col(0), swell_wave_period: col(1), swell_wave_direction: col(2),
      wind_wave_height: col(0), wind_wave_period: col(1), wind_wave_direction: col(2), secondary_swell_wave_height: col(0), secondary_swell_wave_period: col(1), secondary_swell_wave_direction: col(2)}});
  }
  const model = {data: series, meta: {last_run_initialisation_time: issued, data_end_time: hours.at(-1)}};
  return m.parseForecast({region_id: 'morro-bay', requested_points: pts, retrieved, models: {[m.WAVE_MODEL.id]: model, gfs_global: {data: [], meta: {}}}}, 'morro-bay');
}
const swellOf = (m, f, at = SAT, now = SNOW) => m.swellStatus(true, {state: 'ready', region: 'morro-bay', forecast: f, at: now.getTime()}, at, now, TZ);
const WNOW = new Date('2026-10-20T12:00:00Z'), WISSUED = WNOW.getTime() - 12 * HOUR;
function windFeed({retrieved = WNOW.getTime(), issued = WISSUED / 1000, speed = i => i} = {}) {
  const times = Array.from({length: 49}, (_, i) => WISSUED / 1000 + i * 3600);
  return {region_id: 'morro-bay', retrieved, requested_points: [['a', 35, -122], ['b', 35, -121.75], ['c', 35.25, -122], ['d', 35.25, -121.75]],
    models: {gfs_global: {meta: {last_run_initialisation_time: issued, data_end_time: times.at(-1)},
      data: Array.from({length: 4}, () => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', wind_speed_10m: 'kn', wind_direction_10m: '°'}, hourly: {time: times, wind_speed_10m: times.map((_, i) => speed(i)), wind_direction_10m: times.map(() => 0)}}))}}};
}
const windOf = (m, over, at = WNOW, now = WNOW) => m.windStatus(true, m.parseForecast(windFeed(over), 'morro-bay', 'gfs_global'), at, now, 'UTC');
const inEs = (m, st, field = 'reason') => plain(m.resolveStatusText(st[field], st.copy[field], 'es'));
const inEn = (m, st, field = 'reason') => m.statusIn(st.copy[field], 'en');

test('currents_no_fallback_missing_last_and_grid: every branch is byte-identical in English and keeps its no-other-source clause in Spanish', async () => {
  const m = await load(), at = (choice, status, ocean) => m.currentsStatus(choice, status, ocean, CAT, CNOW, TZ);
  const all = {
    unbound: at('wcofs', 'unbound', null), error: at('wcofs', 'error', null), invalid: at('wcofs', 'invalid', null), expired: at('wcofs', 'expired', packet()), loading: at('wcofs', 'ok', null),
    offline: m.currentsStatus('wcofs', 'error', null, CAT, CNOW, TZ, true),
    radarOnly: at('hfr-6', 'ok', packet(WCOFS())), noLast: at('hfr-1', 'ok', packet()),
    last: at('wcofs', 'ok', packet(WCOFS({issuedAt: '2026-10-05T21:00:00Z'}))),
    sparse: at('wcofs', 'ok', packet(WCOFS({nativeResolutionKm: 1, frames: [{validAt: '2026-10-07T12:00:00Z', cells: WCOFS().frames[0].cells.filter((_, k) => k % 2 === 0).map((c, k) => ({...c, lon: c.lon + (k % 3) * 0.013}))}]}))),
    regionalRadar: m.regionalCurrentsStatus('hfr-1', null, CAT, CNOW, TZ), regionalLoading: m.regionalCurrentsStatus('wcofs', null, CAT, CNOW, TZ),
    regionalNone: m.regionalCurrentsStatus('wcofs', {state: 'none'}, CAT, CNOW, TZ), regionalError: m.regionalCurrentsStatus('wcofs', {state: 'error'}, CAT, CNOW, TZ),
    regionalOffline: m.regionalCurrentsStatus('wcofs', {state: 'error', network: true}, CAT, CNOW, TZ, true),
    regionalListed: m.regionalCurrentsStatus('wcofs', {state: 'listed', validAt: ['2026-10-07T09:00:00Z']}, CAT, CNOW, TZ),
    drawn: at('wcofs', 'ok', packet(WCOFS({nativeResolutionKm: 4}))),
  };
  for (const [name, st] of Object.entries(all)) {
    assert.ok(st.copy?.note, `${name} carries note parts`);
    assert.equal(m.statusIn(st.copy.note, 'en'), st.note, `${name} note`);
    if (st.reason) assert.equal(m.statusIn(st.copy.reason, 'en'), st.reason, `${name} reason`);
  }
  assert.ok(all.sparse.reason.includes('not a grid') && all.sparse.drawn === null && all.sparse.note.startsWith('grid cannot be drawn'), 'the sparse frame is the undrawable one');
  assert.equal(all.drawn.copy.reason, undefined, 'a drawn frame has a note and no reason');
  assert.match(inEs(m, all.drawn, 'note'), /^pronóstico \S+ 5 a\. m\.$/);
  const clause = 'y no se muestra ninguna otra fuente.';
  for (const name of ['error', 'invalid', 'expired', 'regionalError']) assert.ok(inEs(m, all[name]).startsWith('Corrientes no disponibles: ') && inEs(m, all[name]).endsWith(clause), name);
  assert.equal(inEs(m, all.expired), 'Corrientes no disponibles: el paquete de corrientes superficiales superó su límite de antigüedad, y no se muestra ninguna otra fuente.');
  assert.equal(inEs(m, all.regionalRadar), 'Corrientes no disponibles: Observed HF radar · 1 km se publica solo donde un paquete local de corrientes superficiales cubre la región; el pronóstico de NOAA WCOFS puede estar disponible.');
  assert.equal(inEs(m, all.noLast), 'Corrientes no disponibles: no hay un fotograma reciente de Observed HF radar · 1 km para esta hora.');
  assert.match(inEs(m, all.last), /^Corrientes no disponibles: no hay un fotograma reciente de NOAA WCOFS forecast para esta hora; el último era válido \S+ \d+ [ap]\. m\.\.$/);
  assert.equal(inEs(m, all.last, 'note').startsWith('sin fotograma reciente · último '), true);
  assert.match(inEs(m, all.sparse), /no es una cuadrícula que se pueda dibujar sin unir vacíos \(demasiado dispersa, demasiado gruesa, irregular o demasiado grande\), y no se muestra ninguna otra fuente\.$/);
  assert.equal(inEs(m, all.offline), 'Las lecturas costeras no están disponibles sin conexión. Guarda las lecturas costeras y revisa el paquete guardado antes de salir de la cobertura.');
  // The chosen source's own words, and the producer's gate, are untouched.
  assert.equal(all.radarOnly.drawn, null);
  assert.equal(m.currentsStatus('off', 'ok', packet(), CAT, CNOW, TZ).copy, undefined);
  assert.equal(m.regionalCurrentsStatus('off', null, CAT, CNOW, TZ).copy, undefined);
});

test('swell_clock_limits_and_missing_corners_es: each limit and each gate order keeps its meaning in Spanish', async () => {
  const m = await load(), A = (f, at, now) => swellOf(m, f, at, now);
  const ok = A(wave(m)), rows = {
    failed: m.swellStatus(true, {state: 'error', region: 'morro-bay', forecast: null, at: 0}, SAT, SNOW, TZ), loading: m.swellStatus(true, {state: 'loading', region: 'morro-bay', forecast: null, at: 0}, SAT, SNOW, TZ),
    runAhead: A(wave(m, {issued: (SNOW.getTime() + 10 * 60_000) / 1000})), runStale: A(wave(m, {issued: (SNOW.getTime() - 37 * HOUR) / 1000})),
    retrievalAhead: A(wave(m, {retrieved: SNOW.getTime() + 10 * 60_000})), retrievalStale: A(wave(m, {retrieved: SNOW.getTime() - 7 * HOUR})),
    outside: A(wave(m), new Date(ISSUED_S + 60 * HOUR)), sparse: A(wave(m, {hours: hoursOf(48).filter((_, k) => k % 6 === 0)})), noCell: A(wave(m, {values: () => [null, 12, 290]})),
  };
  assert.ok(ok.drawn && ok.copy.stamp && ok.copy.note);
  assert.equal(m.statusIn(ok.copy.note, 'en'), ok.note);
  assert.equal(m.statusIn(ok.copy.stamp, 'en'), m.lookup(m.STRINGS, 'legend.swell.stamp', 'en', {name: m.WAVE_MODEL.name, stamp: ok.drawn.stamp}, true), 'the stamp is the legend\'s English');
  for (const [name, st] of Object.entries(rows)) {
    assert.equal(st.drawn, null, name);
    assert.equal(m.statusIn(st.copy.note, 'en'), st.note, `${name} note`);
    assert.equal(m.statusIn(st.copy.reason, 'en'), st.reason, `${name} reason`);
    if (st.reason.startsWith('Swell unavailable:')) assert.equal(m.statusIn(st.copy.fieldReason, 'en'), `Swell field unavailable:${st.reason.slice('Swell unavailable:'.length)} Nearshore rings remain visible.`, `${name} field reason`);
    else assert.equal(st.copy.fieldReason, undefined, `${name} gets no rings suffix`);
  }
  assert.equal(inEs(m, rows.runAhead), 'Oleaje no disponible: la corrida de NOAA GFS-Wave del 9 oct, 11 a. m. está fechada más de 5 minutos por delante del reloj de este dispositivo, por lo que no se puede comprobar su antigüedad.');
  assert.match(inEs(m, rows.runStale), /^Oleaje no disponible: la última corrida de NOAA GFS-Wave, del .*, superó su límite de antigüedad de 36 horas\.$/);
  assert.match(inEs(m, rows.retrievalAhead), /^Oleaje no disponible: .* más de 5 minutos por delante del reloj de este dispositivo, por lo que no se puede comprobar su antigüedad\.$/);
  assert.equal(inEs(m, rows.retrievalStale), 'Oleaje no disponible: el pronóstico regional se obtuvo por última vez hace más de 6 horas.');
  assert.match(inEs(m, rows.outside), /^Oleaje no disponible: la hora seleccionada queda fuera de la corrida de NOAA GFS-Wave del .*, que termina el .*\.$/);
  assert.match(inEs(m, rows.sparse), /no indica ninguna hora a menos de 90 minutos de .*\.$/);
  assert.match(inEs(m, rows.noCell), /tiene altura, período y dirección en las cuatro esquinas para .*; las muestras faltantes quedan en blanco\.$/);
  assert.equal(inEs(m, rows.loading), 'Cargando el pronóstico regional de oleaje.');
  // The limits are the producer's: 36 h and 6 h exactly pass, 5 minutes ahead exactly passes, one more does not (gate order unchanged).
  assert.ok(A(wave(m, {issued: (SNOW.getTime() - 36 * HOUR) / 1000})).drawn && A(wave(m, {retrieved: SNOW.getTime() - 6 * HOUR})).drawn);
  assert.equal(A(wave(m, {issued: (SNOW.getTime() - 36 * HOUR - 1000) / 1000})).drawn, null);
  const both = A(wave(m, {issued: (SNOW.getTime() + 10 * 60_000) / 1000, retrieved: SNOW.getTime() - 7 * HOUR}));
  assert.ok(both.reason.includes('5 minutes ahead'), 'a run ahead of the clock outranks a stale retrieval, in both languages');
  assert.ok(inEs(m, both).includes('5 minutos por delante'));
  assert.equal(m.swellStatus(false, {state: 'idle', region: null, forecast: null, at: 0}, SAT, SNOW, TZ).copy, undefined);
});

test('wind_multi_failure_precedence: the first reason wins in both languages; the stamp and every limit keep their meaning', async () => {
  const m = await load(), W = (o, at, now) => windOf(m, o, at, now);
  const ok = W();
  assert.ok(ok.drawn);
  assert.equal(m.statusIn(ok.copy.stamp, 'en'), m.lookup(m.STRINGS, 'legend.windStamp', 'en', {stamp: ok.drawn.stamp}, true));
  assert.equal(plain(m.statusIn(ok.copy.stamp, 'es')), 'NOAA NCEP · GFS · corrida 20 oct, 12 a. m. · 12 h de antigüedad · válido mar 20 oct, 12 p. m.');
  const future = W({issued: (WNOW.getTime() + 10 * 60_000) / 1000, retrieved: WNOW.getTime() - 7 * HOUR});
  const stale = W({issued: (WNOW.getTime() - 37 * HOUR) / 1000, retrieved: WNOW.getTime() - 7 * HOUR});
  const retrieved = W({retrieved: WNOW.getTime() - 7 * HOUR});
  const noHour = W({}, new Date(WISSUED + 60 * HOUR));
  const samples = W({speed: () => null});
  for (const [name, st] of Object.entries({future, stale, retrieved, noHour, samples})) { assert.equal(st.drawn, null, name); assert.equal(m.statusIn(st.copy.reason, 'en'), st.reason, name); }
  assert.match(inEs(m, future), /una marca de tiempo está por delante del reloj del dispositivo\.$/);
  assert.match(inEs(m, stale), /la corrida superó su límite de antigüedad de 36 horas\.$/);
  assert.match(inEs(m, retrieved), /la obtención superó su límite de antigüedad de 6 horas\.$/);
  assert.match(inEs(m, noHour), /no hay ninguna hora de pronóstico listada a menos de 90 minutos dentro de la corrida\.$/);
  assert.equal(inEs(m, samples), 'Viento no disponible: no hay muestras de viento con unidades comprobadas en esta hora de pronóstico.');
  assert.ok(inEs(m, stale).startsWith('Viento no disponible: corrida 18 oct, 11 p. m. de NOAA GFS; '), 'the run is named in Spanish and the model name stays');
  assert.equal(m.windStatus(true, null, WNOW, WNOW, 'UTC', true).reason, 'Wind unavailable: the regional forecast failed to load.');
  assert.equal(inEs(m, m.windStatus(true, null, WNOW, WNOW, 'UTC', true)), 'Viento no disponible: no se pudo cargar el pronóstico regional.');
  assert.equal(inEs(m, m.windStatus(true, null, WNOW, WNOW, 'UTC')), 'Cargando el pronóstico regional de viento.');
  assert.equal(m.windStatus(false, null, WNOW, WNOW, 'UTC').copy, undefined);
});

test('swell_field_rings_language_switch and currents/wind rows: the legend and rail follow the language from the same retained state', async t => {
  const m = await load(), s = m.state;
  const prior = {sw: m.swellState.value, ns: m.nearshoreState.value, wi: m.windState.value, cu: m.currentsState.value};
  t.after(() => { m.language.value = 'en'; m.swellState.value = prior.sw; m.nearshoreState.value = prior.ns; m.windState.value = prior.wi; m.currentsState.value = prior.cu; });
  s.configureStore({v2: true, storage: null});
  s.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&layers=swell,wind,currents&current=wcofs`);
  const legend = lang => { m.language.value = lang; return m.render(m.h(m.Legend)); }, rail = lang => { m.language.value = lang; return m.render(m.h(m.LayerRail)); };
  const refused = swellOf(m, wave(m, {retrieved: SNOW.getTime() - 7 * HOUR}));
  m.swellState.value = refused;
  m.nearshoreState.value = null;
  m.windState.value = windOf(m, {retrieved: WNOW.getTime() - 7 * HOUR});
  m.currentsState.value = m.currentsStatus('wcofs', 'expired', packet(), CAT, CNOW, TZ);
  const plainLegend = lang => plain(legend(lang));
  const en = legend('en'), es = plainLegend('es');
  assert.ok(en.includes('Swell unavailable: the regional forecast was last retrieved more than 6 hours ago.'));
  assert.ok(es.includes('Oleaje no disponible: el pronóstico regional se obtuvo por última vez hace más de 6 horas.'));
  assert.ok(es.includes('Viento no disponible: corrida 20 oct, 12 a. m. de NOAA GFS; la obtención superó su límite de antigüedad de 6 horas.'));
  assert.ok(es.includes('Corrientes no disponibles: el paquete de corrientes superficiales superó su límite de antigüedad, y no se muestra ninguna otra fuente.'));
  assert.equal(es.includes('<span lang="en">Swell unavailable'), false);
  assert.equal(legend('en'), en, 'back to English restores the same bytes');
  // Rings retained, no field: the field wording and the rings sentence, from the same clause; unknown reasons get no suffix.
  m.nearshoreState.value = {rings: [{site: {id: 'n1'}}], product: 'x', key: 'k', collection: {type: 'FeatureCollection', features: []}};
  assert.ok(legend('en').includes('Swell field unavailable: the regional forecast was last retrieved more than 6 hours ago. Nearshore rings remain visible.'));
  assert.ok(plainLegend('es').includes('Campo de oleaje no disponible: el pronóstico regional se obtuvo por última vez hace más de 6 horas. Los anillos cercanos a la costa siguen visibles.'));
  m.swellState.value = {...refused, copy: undefined};
  assert.ok(plainLegend('es').includes('<span lang="en">Swell field unavailable: the regional forecast was last retrieved'), 'no parts: the whole English field wording stays labelled English');
  m.swellState.value = swellOf(m, wave(m), SAT, SNOW);
  m.nearshoreState.value = {rings: [{site: {id: 'n1'}}], product: 'x', key: 'k', collection: {type: 'FeatureCollection', features: []}};
  assert.equal(plainLegend('es').includes('anillos cercanos'), false, 'a field that draws shows no refusal');
  assert.ok(plainLegend('es').includes('NOAA GFS-Wave: pronóstico del modelo · corrida'), 'the drawn stamp is Spanish');
  // The rail's Currents note follows the matching descriptor: the reason while nothing draws.
  assert.ok(plain(rail('es')).includes('Corrientes no disponibles: el paquete de corrientes superficiales superó su límite de antigüedad, y no se muestra ninguna otra fuente.'), 'the rail shows the Spanish reason, as it shows the English one');
  assert.ok(rail('en').includes('Currents unavailable: the surface-current packet passed its age limit, and no other source is shown.'), 'English rail shows the reason, as before');
});

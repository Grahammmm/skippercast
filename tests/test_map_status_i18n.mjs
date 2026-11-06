// SC1352-02: water-temperature, contrast, chlorophyll, cloud and offline layer statuses in Spanish. Each producer keeps its
// English string and attaches catalogue parts; the rail and legend resolve them in the page's language at render.
// The bundle is built with esbuild; nothing is fetched.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

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
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
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

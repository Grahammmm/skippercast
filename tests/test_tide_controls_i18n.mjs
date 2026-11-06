// SC1137-03: the tide-station control and the tide sparkline read the chosen language.
// Real components are bundled and rendered to HTML; the open panel is forced open by a build-time rewrite of its one
// useState(false) so server rendering can show it. Synthetic stations and a synthetic curve only.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile, mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import fixture from './fixtures/coast/skippercast-report.json' with {type: 'json'};
import {rendererPlugin} from './helpers/esbuild-url.mjs';
import {COVERED, NOT_COVERED} from '../scripts/check_copy.mjs';
import {STRINGS} from '../web/i18n.ts';

const {selectionMessage, noticeText, eventClock, SELECTION_MESSAGE_IDS} = await import('../web/brief/tide-copy.ts');
const {createTideSelection} = await import('../web/tide-selection.ts');
const {slo} = await import('../packages/coast/src/counties.ts');
const {buildCoastBrief} = await import('../web/brief/model.ts');

const ROOT = new URL('..', import.meta.url).pathname;
const MIN = 60_000;
const now = new Date(Date.parse(fixture.generatedAt) + 10 * MIN);
const iso = ms => new Date(ms).toISOString();
const DAY0 = Date.parse('2026-10-08T07:00:00Z');
const synthetic = Array.from({length: 241}, (_, i) => ({at: iso(DAY0 + i * 6 * MIN), heightFt: 3 + 2 * Math.sin(2 * Math.PI * (i * 6 * MIN) / (12.42 * 60 * MIN))}));
const sparkBrief = overrides => buildCoastBrief({report: {...fixture, tides: synthetic, ...overrides}, county: slo, areaId: 'central', profile: 'boat', date: '2026-10-08', now, at: '2026-10-08T21:00:00.000Z'});

const openPanel = {name: 'open-panel', setup: b => b.onLoad({filter: /TideStationControl\.tsx$/}, async args => {
  const source = await readFile(args.path, 'utf8');
  assert.ok(source.includes('[open, setOpen] = useState(false)'), 'the control still starts closed');
  return {contents: source.replace('[open, setOpen] = useState(false)', '[open, setOpen] = useState(true)'), loader: 'tsx', resolveDir: dirname(args.path)};
})};
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'tide-i18n-')), 'bundle.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {TideSpark} from './web/brief/TideSpark.tsx';
      export {TideStationControl} from './web/brief/TideStationControl.tsx';
      export {tideSelection} from './web/tide-selection.ts';
      export {language} from './web/i18n.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: [rendererPlugin, openPanel]});
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const stations = [{id: '9000001', name: 'Fixture <North> & Co', lat: 35.7, lng: -121.1, type: 'S'}, {id: '9000002', name: 'Fixture Port', lat: 35.36, lng: -120.85, type: 'S'}];
const region = {id: 'morro-bay', bounds: [34, -123, 36, -120], station: '9412110', name: 'Morro Bay'};
function seed(m, over = {}) {
  const s = m.tideSelection;
  s.region.value = region; s.stations.value = stations; s.saved.value = ['9000001', '9000002']; s.choice.value = '9000001';
  s.loading.value = false; s.error.value = ''; s.notice.value = '';
  Object.assign(s, {});
  for (const [k, v] of Object.entries(over)) s[k].value = v;
}
const html = (m, lang) => { m.language.value = lang; return m.render(m.h(m.TideStationControl, {})); };

test('chooser_en_es_en_retained_status: every control, aria, option and status follows the language and round-trips', async () => {
  const m = await load();
  seed(m, {error: 'NOAA station directory unavailable. Retry when connected.'});
  const en = html(m, 'en');
  assert.ok(en.includes('Tide station: Fixture &lt;North> &amp; Co'), 'published station name escaped once: ' + en.slice(0, 400));
  assert.ok(en.includes('aria-label="Saved tide stations"') && en.includes('Saved stations (2/3)'));
  assert.ok(en.includes('Use Fixture Port') && en.includes('aria-label="Remove Fixture Port"') && en.includes('>Remove<'));
  assert.ok(en.includes('Prediction station') && en.includes('Region default — Morro Bay') && en.includes('Fixture Port (9000002)'));
  assert.ok(en.includes('Add current station') && en.includes('Use nearest to port'));
  assert.ok(en.includes('Selection changes only the tide tile and chart. Bar and shore checks keep their reviewed reference station. Tide heights do not predict entrance currents.'));
  assert.ok(en.includes('Selected tide display only; bar and shore checks use their configured reference station.'));
  assert.ok(en.includes('NOAA station directory unavailable. Retry when connected.') && en.includes('Retry tide station'));
  const es = html(m, 'es');
  for (const want of ['Estación de marea: Fixture &lt;North> &amp; Co', 'aria-label="Estaciones de marea guardadas"', 'Estaciones guardadas (2/3)', 'Usar Fixture Port', 'aria-label="Eliminar Fixture Port"', '>Eliminar<',
    'Estación de predicción', 'Predeterminada de la región — Morro Bay', 'Fixture Port (9000002)', 'Agregar estación actual', 'Usar la más cercana al puerto',
    'La selección cambia solo el recuadro y el gráfico de marea. Las revisiones de la barra y de la costa mantienen su estación de referencia revisada. Las alturas de marea no predicen las corrientes de entrada.',
    'Solo cambia la visualización de marea elegida; las revisiones de la barra y de la costa usan su estación de referencia configurada.',
    'El directorio de estaciones de NOAA no está disponible. Reintenta cuando tengas conexión.', 'Reintentar estación de marea', 'value="9000002"'])
    assert.ok(es.includes(want), want);
  assert.ok(!/Remove|Retry|Prediction station|Saved stations/.test(es), 'no English control words remain');
  assert.ok(html(m, 'en') === en, 'en -> es -> en is byte-identical');
  // the unavailable option and the loading line
  seed(m, {choice: '9999999', loading: true});
  assert.ok(html(m, 'en').includes('9999999 — unavailable') && html(m, 'en').includes('Loading station predictions…'));
  assert.ok(html(m, 'es').includes('9999999 — no disponible') && html(m, 'es').includes('Cargando predicciones de la estación…'));
});

test('selection_adapter_finite_and_english_compatibility: four statuses translate; anything else stays literal; the model stays English', async () => {
  assert.equal(SELECTION_MESSAGE_IDS.length, 4);
  for (const id of SELECTION_MESSAGE_IDS) {
    const english = STRINGS[id].en;
    assert.equal(selectionMessage(english, 'en'), english);
    assert.equal(selectionMessage(english, 'es'), STRINGS[id].es);
    assert.notEqual(STRINGS[id].es, english);
  }
  for (const odd of ['', 'NOAA station directory unavailable.', 'Station <b>9000001</b> is down', 'Fixture North']) assert.equal(selectionMessage(odd, 'es'), odd);
  const m = await load();
  m.language.value = 'es';
  const sel = createTideSelection(() => Promise.reject(new Error('offline')), {getItem: () => null, setItem() {}, removeItem() {}});
  sel.configure(region);
  await sel.list();
  assert.equal(sel.error.value, 'NOAA station directory unavailable. Retry when connected.', 'model string is English whatever the app language');
  m.language.value = 'en';
});

test('cap_notice_does_not_conceal_failure_es: the cap notice and a data failure show together, each with its own words; Retry stays with the failure', async () => {
  const m = await load();
  seed(m, {notice: 'Up to three tide stations can be saved per region. Remove one before adding another.', error: 'Some chosen-station predictions are unavailable. Missing readings stay blank rather than using the default station.'});
  const es = html(m, 'es');
  assert.ok(es.includes('Puedes guardar hasta tres estaciones de marea por región. Elimina una antes de agregar otra.'));
  assert.ok(es.includes('Algunas predicciones de la estación elegida no están disponibles.') && es.includes('Reintentar estación de marea'));
  seed(m, {notice: 'Up to three tide stations can be saved per region. Remove one before adding another.'});
  assert.ok(!html(m, 'es').includes('Reintentar'), 'a cap notice alone offers no Retry');
  assert.ok(!html(m, 'en').includes('Retry tide station'));
  seed(m, {error: 'Chosen station unavailable in this region. Choose another station or the region default.'});
  assert.ok(html(m, 'es').includes('La estación elegida no está disponible en esta región. Elige otra estación o la predeterminada de la región.'));
  m.language.value = 'en';
});

test('chooser notices are data: nearest, none, port failure, removed and saved follow a language switch', () => {
  const cases = [
    [{id: 'tideStation.nearest', vars: {port: 'Morro Bay', station: 'Fixture Port'}}, 'Nearest listed station to Morro Bay: Fixture Port.', 'Estación listada más cercana a Morro Bay: Fixture Port.'],
    [{id: 'tideStation.noneAvailable', vars: {}}, 'No listed tide station or port is available for this region.', 'No hay una estación de marea listada ni un puerto disponible para esta región.'],
    [{id: 'tideStation.portFail', vars: {}}, 'The port directory could not be read. Retry when connected.', 'No se pudo leer el directorio de puertos. Reintenta cuando tengas conexión.'],
    [{id: 'tideStation.removed', vars: {station: 'Fixture Port'}}, 'Fixture Port removed from saved stations.', 'Fixture Port eliminada de las estaciones guardadas.'],
    [{id: 'tideStation.savedActive', vars: {station: 'Fixture Port'}}, 'Fixture Port saved and active.', 'Fixture Port guardada y activa.'],
  ];
  for (const [notice, en, es] of cases) { assert.equal(noticeText(notice, 'en'), en); assert.equal(noticeText(notice, 'es'), es); }
});

test('spark_locale_and_empty_matrix: label, aria, High/Low and clock follow the language; empty lines reuse the tide ids; English keeps minutes', async () => {
  const m = await load();
  const brief = sparkBrief({});
  assert.ok(brief.tideEvents.length >= 2);
  m.language.value = 'en';
  const en = m.render(m.h(m.TideSpark, {brief, now}));
  assert.match(en, /^<figure class="app-spark" aria-label="Tide curve">/);
  assert.match(en, /<li>(High|Low) <span class="ui-mono">\d{1,2}:\d\d [ap]m · \d+\.\d ft MLLW<\/span><\/li>/);
  m.language.value = 'es';
  const es = m.render(m.h(m.TideSpark, {brief, now}));
  assert.match(es, /^<figure class="app-spark" aria-label="Curva de marea">/);
  assert.match(es, /<li>(Pleamar|Bajamar) <span class="ui-mono">\d{1,2}:\d\d · \d+\.\d ft MLLW<\/span><\/li>/);
  assert.ok(!/>(High|Low) </.test(es));
  const heights = h => [...h.matchAll(/(\d+\.\d) ft MLLW/g)].map(x => x[1]).join();
  assert.equal(heights(es), heights(en), 'same heights and datum');
  // empty states
  const none = sparkBrief({tides: [], tideEvents: []}), noCurve = sparkBrief({tides: []});
  assert.equal(none.tideEvents.length, 0);
  assert.ok(m.render(m.h(m.TideSpark, {brief: none, now})).includes('<span class="app-spark-empty">Serie de mareas no disponible</span>'));
  assert.ok(m.render(m.h(m.TideSpark, {brief: noCurve, now})).includes('<span class="app-spark-empty">No hay curva de marea para este lugar.'));
  assert.ok(m.render(m.h(m.TideSpark, {brief: null, now})).includes('<span class="app-spark-empty">—</span>'));
  m.language.value = 'en';
  assert.ok(m.render(m.h(m.TideSpark, {brief: none, now})).includes('<span class="app-spark-empty">Tide series unavailable</span>'));
  assert.equal(m.render(m.h(m.TideSpark, {brief: null, now})), '<figure class="app-spark" aria-label="Tide curve"><span class="app-spark-empty">—</span></figure>');
});

test('eventClock: the instant and zone are kept; a non-Pacific zone and the repeated DST hour use the original instant', () => {
  assert.equal(eventClock('2026-10-08T21:00:00Z', 'America/Los_Angeles', 'en'), '2:00 pm');
  assert.equal(eventClock('2026-10-08T21:00:00Z', 'America/Los_Angeles'), '2:00 pm');
  assert.equal(eventClock('2026-10-08T21:00:00Z', 'America/Los_Angeles', 'es'), '14:00');
  assert.equal(eventClock('2026-10-08T21:00:00Z', 'Pacific/Honolulu', 'en'), '11:00 am');
  // 2026-11-01 01:30 happens twice in Los Angeles (08:30Z PDT, 09:30Z PST)
  assert.equal(eventClock('2026-11-01T08:30:00Z', 'America/Los_Angeles', 'en'), '1:30 am');
  assert.equal(eventClock('2026-11-01T09:30:00Z', 'America/Los_Angeles', 'en'), '1:30 am');
  assert.equal(eventClock('2026-11-01T09:30:00Z', 'America/Los_Angeles', 'es'), '1:30');
});

test('catalogue and inventory: tideStation.* / tideSpark.* have both languages with the same placeholders; files are COVERED', () => {
  const ids = Object.keys(STRINGS).filter(id => /^tide(Station|Spark)\./.test(id));
  assert.ok(ids.length >= 28);
  const holes = text => [...text.matchAll(/\{(\w+)\}/g)].map(x => x[1]).sort().join();
  for (const id of ids) { assert.ok(STRINGS[id].en.trim() && STRINGS[id].es.trim(), id); assert.equal(holes(STRINGS[id].es), holes(STRINGS[id].en), `${id} placeholders`); }
  for (const f of ['web/brief/TideStationControl.tsx', 'web/brief/TideSpark.tsx', 'web/brief/tide-copy.ts']) { assert.ok(COVERED.includes(f), f); assert.ok(!(f in NOT_COVERED), f); }
});

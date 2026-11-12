// SC0707-10: the Trip dialog's offline pages in Spanish. The ocean lines are tested as pure functions; the page is the real
// web/app/Trip.tsx with the store, buttons and hooks replaced by the SP-15 fixtures (no network, no browser storage).
import './helpers/spanish-ready.mjs';   // SC1407-09: the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedCatalogue} from './helpers/esbuild-url.mjs';
import {oceanLines} from '../web/trip-ocean-lines.ts';

const root = fileURLToPath(new URL('../', import.meta.url));
const fixtures = resolve(root, 'tests/fixtures/sp1502_pack_inventory');
const NOW = new Date('2026-10-20T12:00:00Z');
const layer = (state, extra = {}) => ({state, ...extra});
const meta = layers => ({ocean: {path: 'layers', layers}});
const WATER = 'sst-analysis', CURRENTS = 'wcofs-surface-forecast';

test('trip_es_ocean_all_states: same booleans and time boundary as English, Spanish words, English unchanged', () => {
  assert.equal(oceanLines({}, NOW, 'UTC', 'es'), null, 'a pack saved before the ocean phase has no line');
  assert.deepEqual(oceanLines({ocean: {path: 'none'}}, NOW, 'UTC', 'es'), {water: 'no se publica para esta área', currents: 'no se publica para esta área'});
  assert.deepEqual(oceanLines({ocean: {path: 'none'}}, NOW, 'UTC'), {water: 'not published for this area', currents: 'not published for this area'});
  const savedAt = '2026-10-20T10:00:00Z';
  const coastal = (lang) => oceanLines({ocean: {path: 'coastal-report', coastal: {saved_at: savedAt}}}, NOW, 'UTC', lang);
  assert.match(coastal('en').water, /^from Coastal readings \(saved \w{3} \d+ [ap]m\)$/);
  assert.match(coastal('es').water, /^de Lecturas costeras \(guardadas .+\)$/);
  assert.equal(oceanLines({ocean: {path: 'coastal-report', coastal: null}}, NOW, 'UTC', 'es').currents, 'de Lecturas costeras (no guardadas)');
  assert.equal(oceanLines({ocean: {path: 'coastal-report', coastal: {saved_at: 'not a date'}}}, NOW, 'UTC').water, 'from Coastal readings (not saved)');
  const until = '2026-10-20T12:00:00Z';
  const at = (now, lang) => oceanLines(meta({[WATER]: layer('saved', {drawable_until: until}), [CURRENTS]: layer('saved', {drawable_until: until})}), now, 'UTC', lang);
  assert.match(at(new Date('2026-10-20T11:59:59Z'), 'es').water, /^guardado · no se muestra después de .+ · solo para horas a partir del análisis$/);
  assert.match(at(new Date('2026-10-20T11:59:59Z'), 'es').currents, /· solo para horas de pronóstico$/);
  assert.match(at(new Date('2026-10-20T11:59:59Z'), 'en').water, /^saved · not shown after .+ · only for hours on or after the analysis$/);
  assert.equal(at(new Date(until), 'es').water, 'guardado · superó su límite de antigüedad', 'exactly at the limit is past it, as in English');
  assert.equal(at(new Date(until), 'en').water, 'saved · past its age limit');
  assert.equal(oceanLines(meta({[WATER]: layer('saved', {drawable_until: 'garbage'}), [CURRENTS]: layer('saved')}), NOW, 'UTC', 'es').water, 'guardado');
  const states = [[layer('failed'), 'no guardado: no pasó la revisión', 'not saved: failed check'], [layer('over-cap'), 'no guardado: demasiado grande para este paquete', 'not saved: too large for this pack'],
    [layer('not-current', {why: 'retrieval'}), 'no guardado: pronóstico demasiado antiguo para mostrar sin conexión', 'not saved: forecast too old to show offline'],
    [layer('not-current', {why: 'short-window'}), 'no guardado: pronóstico demasiado antiguo para mostrar sin conexión', 'not saved: forecast too old to show offline'],
    [layer('not-current', {why: 'other'}), 'no guardado: no había datos actuales al guardar', 'not saved: no current data at save time'],
    [layer('absent'), 'no guardado: no se publica para esta área', 'not saved: not published for this area'], [layer('cancelled'), 'no guardado', 'not saved'], [undefined, 'no guardado', 'not saved']];
  for (const [l, es, en] of states) {
    assert.equal(oceanLines(meta({[WATER]: l}), NOW, 'UTC', 'es').water, es);
    assert.equal(oceanLines(meta({[WATER]: l}), NOW, 'UTC').water, en);
  }
  for (const bad of [null, [], 'x', undefined]) assert.equal(oceanLines({ocean: {path: 'layers', layers: bad}}, NOW, 'UTC', 'es').water, 'no guardado', 'malformed layers read as none recorded');
});

async function load(responses) {
  const dir = await mkdtemp(resolve(tmpdir(), 'trip-i18n-'));
  const trip = resolve(root, 'web/app/Trip.tsx');
  await build({
    stdin: {resolveDir: root, loader: 'js', contents: `export {Trip} from './web/app/Trip.tsx'; export {language} from './web/i18n.ts'; export {h} from 'preact'; export {render} from 'preact-render-to-string'; export * from './tests/fixtures/sp1502_pack_inventory/runtime.mjs';`},
    outfile: resolve(dir, 'trip.mjs'), bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent',
    plugins: [preparedCatalogue, {name: 'trip-i18n-boundary', setup(b) {
      b.onResolve({filter: /.*/}, args => {
        if (args.importer.endsWith('web/trip-ocean-lines.ts') && args.path === './map/currents.ts') return {path: resolve(root, 'tests/fixtures/trip_i18n/currents.mjs')};
        if (args.importer !== trip) return;
        if (args.path === 'preact/hooks') return {path: resolve(fixtures, 'runtime.mjs')};
        if (['../ui/Button.tsx', '../landing/PortInput.tsx', '../state.ts', '../trip.ts', '../trip-forecast-end.ts', './App.tsx', './PositionCheck.tsx'].includes(args.path)) return {path: resolve(fixtures, 'boundary.mjs')};
      });
    }}],
  });
  const m = await import(pathToFileURL(resolve(dir, 'trip.mjs')).href);
  m.reset(responses);
  return m;
}
const pack = {cache: 'sc-pack-fixture', meta: {region_name: 'Fixture Harbor', saved_at: '2026-10-20T11:00:00Z', bytes: 2500000, missing: ['a'], forecast_end: null,
  tiles: {saved: 2, planned: 3, min_zoom: 8, max_zoom: 9}, v2: {basemap: {saved: 1, planned: 2}, missing: []},
  ocean: {path: 'layers', layers: {[WATER]: {state: 'saved', drawable_until: '2099-01-01T00:00:00Z'}, [CURRENTS]: {state: 'absent'}}}}};

test('trip_es_inventory_and_async_states: the page, the pack rows and a status follow the language without a second save or delete', async t => {
  const descriptors = new Map();
  for (const [key, value] of Object.entries({navigator: {onLine: true}, caches: {delete: async () => true}}))
    { descriptors.set(key, Object.getOwnPropertyDescriptor(globalThis, key)); Object.defineProperty(globalThis, key, {value, configurable: true, writable: true}); }
  const m = await load([() => Promise.resolve([pack]), () => Promise.resolve([pack]), () => Promise.resolve([pack])]);
  t.after(() => { m.cleanup(); for (const [key, d] of descriptors) { if (d) Object.defineProperty(globalThis, key, d); else delete globalThis[key]; } });
  let deletes = 0;
  globalThis.caches.delete = async () => { deletes++; return true; };
  const render = () => { m.runtime.cursor = 0; m.runtime.actions.clear(); const html = m.render(m.h(m.Trip)); for (const effect of m.runtime.effects.splice(0)) effect(); return html; };
  const settle = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); return render(); };
  render();
  const en = await settle();
  assert.match(en, /<span>Water temp: saved · not shown after .+ · only for hours on or after the analysis<\/span><span>Currents: not saved: not published for this area<\/span>/);
  assert.match(en, /2 of 3 chart tiles · 1 of 2 base map tiles \(zoom 8–9\) · 1 item missing/);
  assert.match(en, /Saved \d+ min ago|Saved \d+ h ago|Saved \d+ days ago/);
  m.language.value = 'es';
  const es = render();
  assert.match(es, /<h3 id="app-offline-pack">Paquete de cartas<\/h3>/);
  assert.match(es, /<span>Temperatura del agua: guardado · no se muestra después de .+ · solo para horas a partir del análisis<\/span><span>Corrientes: no guardado: no se publica para esta área<\/span>/);
  assert.match(es, /2 de 3 teselas de cartas · 1 de 2 teselas del mapa base \(zoom 8–9\) · falta 1 elemento/);
  assert.match(es, /Guardado hace \d+ (min|h|d)/);
  assert.match(es, /aria-label="Eliminar la región guardada Fixture Harbor"/);
  assert.match(es, /<strong>Lecturas costeras<\/strong>|<h3 id="app-offline-coastal">Lecturas costeras<\/h3>/);
  assert.doesNotMatch(es, /Chart pack|Water temp|Currents:|Delete the saved/);
  m.language.value = 'en';
  assert.equal(render().replace(/\d+ (min|h) ago/, 'AGO'), en.replace(/\d+ (min|h) ago/, 'AGO'), 'es then en restores the exact English page');
  // A saved region's status keeps its id and variables: switching language rewrites it, and nothing is saved or deleted again.
  const action = key => { const call = m.runtime.actions.get(key); assert.equal(typeof call, 'function', key); return call; };
  action('Save Fixture Harbor for offline')(); await settle();
  assert.equal(m.runtime.saves, 1);
  assert.match(render(), /<p role="status" aria-live="polite">Saved Fixture Harbor · 128 B\.|<p role="status" aria-live="polite">Saved Fixture Harbor · \d+ KB\./);
  m.language.value = 'es';
  assert.match(render(), /<p role="status" aria-live="polite">Se guardó Fixture Harbor · \d+ KB\./);
  action('Eliminar la región guardada Fixture Harbor')(); await settle();
  assert.equal(deletes, 1);
  assert.match(render(), /<p role="status" aria-live="polite">Se eliminó la región guardada\.<\/p>/);
  m.language.value = 'en';
  assert.match(render(), /<p role="status" aria-live="polite">Saved region deleted\.<\/p>/);
  assert.equal(deletes, 1, 'switching language never deletes again');
  assert.equal(m.runtime.saves, 1, 'switching language never saves again');
  // Offline: the refusal is a status in the chosen language, and no save starts.
  Object.defineProperty(globalThis, 'navigator', {value: {onLine: false}, configurable: true, writable: true});
  action('Save Fixture Harbor for offline')(); render();
  assert.match(render(), /You are offline\. Connect to save this region; saved regions are unchanged\./);
  m.language.value = 'es';
  assert.match(render(), /No tienes conexión\. Conéctate para guardar esta región; las regiones guardadas no cambian\./);
  assert.equal(m.runtime.saves, 1);
});

// SC1722-11: the saved status says "1 item" / "1 elemento" for one missing item, and keeps the plural for three. The count is the
// de-duplicated top-level + v2 missing list; the retained status rewrites its grammar with the language and never saves again.
test('saved_missing_one_three_zero_en_es: one, three and none missing, with overlapping top-level and v2 entries counted once', async t => {
  const descriptors = new Map();
  for (const [key, value] of Object.entries({navigator: {onLine: true}, caches: {delete: async () => true}}))
    { descriptors.set(key, Object.getOwnPropertyDescriptor(globalThis, key)); Object.defineProperty(globalThis, key, {value, configurable: true, writable: true}); }
  const m = await load(Array.from({length: 24}, () => () => Promise.resolve([pack])));
  t.after(() => { m.cleanup(); for (const [key, d] of descriptors) { if (d) Object.defineProperty(globalThis, key, d); else delete globalThis[key]; } });
  const render = () => { m.runtime.cursor = 0; m.runtime.actions.clear(); const html = m.render(m.h(m.Trip)); for (const effect of m.runtime.effects.splice(0)) effect(); return html; };
  const settle = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); return render(); };
  const status = html => /<p role="status" aria-live="polite">([^<]*)<\/p>/.exec(html)?.[1];
  m.language.value = 'en';   // the earlier test ended in Spanish
  render(); await settle();
  const save = async (missing, v2Missing) => {
    m.runtime.saveMeta = {region_name: 'Fixture Harbor', bytes: 128, missing, v2: {basemap: {saved: 1, planned: 2}, missing: v2Missing}};
    const call = m.runtime.actions.get('Save Fixture Harbor for offline'); assert.equal(typeof call, 'function', [...m.runtime.actions.keys()].join(' | '));
    call(); await settle();
  };
  const ONE_EN = 'Saved Fixture Harbor · 1 KB. 1 item could not be saved and will be missing offline.';
  const ONE_ES = 'Se guardó Fixture Harbor · 1 KB. No se pudo guardar 1 elemento y faltará sin conexión.';
  const THREE_EN = 'Saved Fixture Harbor · 1 KB. 3 items could not be saved and will be missing offline.';
  const THREE_ES = 'Se guardó Fixture Harbor · 1 KB. No se pudieron guardar 3 elementos y faltarán sin conexión.';
  await save(['/a.png'], []);
  assert.equal(status(render()), ONE_EN);
  m.language.value = 'es';
  assert.equal(status(render()), ONE_ES, 'the retained one-item status switches to Spanish without a save');
  m.language.value = 'en';
  assert.equal(status(render()), ONE_EN, 'and back to the exact English bytes');
  assert.equal(m.runtime.saves, 1);
  // Three distinct; the same URL in the top-level and the v2 list counts once.
  await save(['/a.png', '/b.png', '/shared.png'], ['/shared.png', '/c.png']);
  assert.equal(status(render()), 'Saved Fixture Harbor · 1 KB. 4 items could not be saved and will be missing offline.');
  await save(['/a.png', '/shared.png'], ['/shared.png', '/b.png']);
  assert.equal(status(render()), THREE_EN);
  m.language.value = 'es';
  assert.equal(status(render()), THREE_ES);
  m.language.value = 'en';
  assert.equal(status(render()), THREE_EN);
  assert.equal(m.runtime.saves, 3, 'switching language never saves again');
  // The same one item listed in both places is still one.
  await save(['/shared.png'], ['/shared.png']);
  assert.equal(status(render()), ONE_EN);
  m.language.value = 'es';
  assert.equal(status(render()), ONE_ES);
  m.language.value = 'en'; render();
  // Nothing missing: no missing sentence.
  await save([], []);
  assert.equal(status(render()), 'Saved Fixture Harbor · 1 KB.');
  m.language.value = 'es';
  assert.equal(status(render()), 'Se guardó Fixture Harbor · 1 KB.');
  assert.equal(m.runtime.saves, 5);
  // The pack inventory line keeps its own wording.
  assert.match(render(), /falta 1 elemento/);
  m.language.value = 'en';
  assert.match(render(), /1 item missing/);
});

// UXFIX-08 review: the saved status keeps the raw byte count, so the GB decimal separator follows the language shown now
// (2.0 GB in English, 2,0 GB in Spanish), without a second save, and the missing-file sentence is kept.
test('saved_gb_status_follows_language: a 2 GB save reads 2.0 GB, 2,0 GB, 2.0 GB across en, es, en', async t => {
  const descriptors = new Map();
  for (const [key, value] of Object.entries({navigator: {onLine: true}, caches: {delete: async () => true}}))
    { descriptors.set(key, Object.getOwnPropertyDescriptor(globalThis, key)); Object.defineProperty(globalThis, key, {value, configurable: true, writable: true}); }
  const m = await load(Array.from({length: 8}, () => () => Promise.resolve([pack])));
  t.after(() => { m.language.value = 'en'; m.cleanup(); for (const [key, d] of descriptors) { if (d) Object.defineProperty(globalThis, key, d); else delete globalThis[key]; } });
  const render = () => { m.runtime.cursor = 0; m.runtime.actions.clear(); const html = m.render(m.h(m.Trip)); for (const effect of m.runtime.effects.splice(0)) effect(); return html; };
  const settle = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); return render(); };
  const status = html => /<p role="status" aria-live="polite">([^<]*)<\/p>/.exec(html)?.[1];
  m.language.value = 'en';
  render(); await settle();
  const save = async (missing) => {
    m.runtime.saveMeta = {region_name: 'Fixture Harbor', bytes: 2e9, missing};
    const call = m.runtime.actions.get('Save Fixture Harbor for offline'); assert.equal(typeof call, 'function');
    call(); await settle();
  };
  await save([]);
  assert.equal(status(render()), 'Saved Fixture Harbor · 2.0 GB.');
  m.language.value = 'es';
  assert.equal(status(render()), 'Se guardó Fixture Harbor · 2,0 GB.', 'the retained status is written in Spanish, with the Spanish decimal separator');
  m.language.value = 'en';
  assert.equal(status(render()), 'Saved Fixture Harbor · 2.0 GB.', 'and back to the exact English text');
  // A missing file is still said, in the language shown, beside the size.
  await save(['/a.png']);
  assert.equal(status(render()), 'Saved Fixture Harbor · 2.0 GB. 1 item could not be saved and will be missing offline.');
  m.language.value = 'es';
  assert.equal(status(render()), 'Se guardó Fixture Harbor · 2,0 GB. No se pudo guardar 1 elemento y faltará sin conexión.');
  m.language.value = 'en';
  assert.equal(status(render()), 'Saved Fixture Harbor · 2.0 GB. 1 item could not be saved and will be missing offline.');
  assert.equal(m.runtime.saves, 2, 'switching language never saves again');
});

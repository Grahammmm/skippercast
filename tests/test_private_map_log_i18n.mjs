// SC1407-12: the private map log's controls follow the page language; stored snapshots are shown exactly as stored, in lang="en".
// Real bundled component rendered to markup; synthetic records in an in-memory store. No account, network or position.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import util from 'node:util';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'private-map-log-i18n-')), 'log.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {PrivateMapLog, LogEntry, noticeText, countText} from './web/app/PrivateMapLog.tsx';
      export {createEntry, readEntries, saveEntry, LOG_KEY} from './web/private-map-log.ts';
      export {readingSource} from './web/brief/mark-forecast.ts';
      export {parseConditionsForecast} from './web/conditions.ts';
      export {language} from './web/i18n.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: preparedRendererPlugins,
  });
  ui = await import(pathToFileURL(out).href);
  return ui;
}

const NOW = Date.parse('2026-11-07T18:00:00Z');
const mark = {name: 'Synthetic reef', position: {latitude: 35, longitude: -121}};
const props = {mark, region: 'fixture', forecast: null, tz: 'UTC'};
const esc = s => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');

function forecast(parse) {
  const sec = NOW / 1000, time = [sec - 3600, sec, sec + 3600];
  return parse({region_id: 'fixture', retrieved: NOW, requested_points: [['regional', 35.1, -121.1]], models: {gfs_global: {
    meta: {last_run_initialisation_time: sec - 3600, data_end_time: sec + 3600},
    data: [{utc_offset_seconds: 0, hourly_units: {time: 'unixtime', wind_speed_10m: 'kn'}, hourly: {time, wind_speed_10m: [11, 12, 13]}}],
  }}}, 'fixture', [35.1, -121.1]);
}
function store(raw) {
  let value = raw, writes = 0;
  return {getItem: () => value, setItem: (_k, v) => { writes++; value = v; }, writes: () => writes};
}

test('es_controls_privacy_and_no_catch: Spanish section, actions, caveats and counts; catch and blank stay distinct; en returns unchanged', async () => {
  const {PrivateMapLog, noticeText, countText, language, render, h} = await components();
  try {
    language.value = 'en';
    const en = render(h(PrivateMapLog, props));
    for (const s of ['aria-label="Private device log"', 'Log catch here', 'Log blank here', 'NOT FOR NAVIGATION.', 'Device log (unavailable)', '>Forecast sources<',
      'blank records no catch']) assert.ok(en.includes(s), `en: ${s}`);
    language.value = 'es';
    const es = render(h(PrivateMapLog, props));
    for (const s of ['aria-label="Registro privado del dispositivo"', 'Registrar captura aquí', 'Registrar sin captura aquí',
      'Solo en este navegador de este dispositivo; nunca se sube ni se añade a tu cuenta.', 'Borrar los datos del sitio elimina estas entradas.',
      'Quien use este dispositivo puede leerlas.', 'NO USAR PARA NAVEGACIÓN.', 'no observaciones en el agua', 'Los huecos siguen sin datos.',
      '>Fuentes del pronóstico<', 'Registro del dispositivo (no disponible)', 'sin captura registra que no hubo ninguna captura', 'No se deduce ninguna especie ni cantidad.',
      'se muestran en inglés, tal como se registraron']) assert.ok(es.includes(s), `es: ${s}`);
    assert.ok(!/Log catch|Log blank|Private device log|Device log|NOT FOR NAVIGATION|Forecast sources/.test(es), 'no English controls in Spanish');
    assert.ok(!es.includes('role="status"'), 'no status before any action');
    // A readable empty log is zero entries; an unreadable one is unavailable, never zero.
    assert.equal(countText([], 'es'), 'Registro del dispositivo (0)');
    assert.equal(countText(Array(3).fill({}), 'es'), 'Registro del dispositivo (3)');
    assert.equal(countText(null, 'es'), 'Registro del dispositivo (no disponible)');
    assert.equal(countText([], 'en'), 'Device log (0)');
    language.value = 'en';
    assert.ok(render(h(PrivateMapLog, props)) === en, 'es then back to en renders the original English');
    // Notices are ids: the same notice reads in whichever language is current.
    assert.equal(noticeText('saved', 'es'), 'Guardado solo en este dispositivo.');
    assert.equal(noticeText('saved', 'en'), 'Saved on this device only.');
    assert.match(noticeText('full', 'es'), /lleno \(500 entradas\)\. Los registros existentes no cambian\./);
    assert.match(noticeText('unavailable', 'es'), /^No se guardó:/);
    assert.match(noticeText('readFailed', 'es'), /no se han modificado/);
    assert.equal(noticeText(null, 'es'), '');
    language.value = 'es';
    assert.equal(render(h(PrivateMapLog, {...props, mark: {...mark, withheld: true}})), '', 'a withheld position still hides both actions');
  } finally { language.value = 'en'; }
});

test('legacy_english_snapshot_is_verbatim_and_tagged: an earlier English entry reads as stored under lang="en", with Spanish app labels', async () => {
  const {LogEntry, createEntry, readEntries, readingSource, parseConditionsForecast, render, h} = await components();
  const old = createEntry({...mark, name: '<b>Reef & "co"</b>'}, 'catch', 'fixture', forecast(parseConditionsForecast), NOW, 'UTC');
  const blank = createEntry(mark, 'blank', 'fixture', null, NOW, 'UTC');
  const raw = JSON.stringify([old, blank]), storage = store(raw);
  const [entry, empty] = readEntries(storage);
  const frozen = JSON.stringify(entry);
  const html = render(h(LogEntry, {entry, tz: 'UTC', lang: 'es'}));
  assert.ok(html.includes('Captura · &lt;b>Reef &amp; &quot;co&quot;&lt;/b> · fixture · <time datetime="2026-11-07T18:00:00.000Z">'), 'name is escaped text');
  assert.ok(!html.includes('<b>'), 'no markup from a stored name');
  assert.ok(html.includes('35.00000, -121.00000 · <span lang="en">Selected map position; not live GPS</span>'));
  assert.ok(html.includes('Datos del pronóstico obtenidos: 2026-11-07T18:00:00.000Z'));
  const readings = [...entry.conditions.forecast.families.flatMap(f => f.rows), entry.conditions.forecast.current];
  const lines = [...html.matchAll(/<li lang="en">([^<]*)<\/li>/g)].map(m => m[1]);
  assert.equal(lines.length, readings.length);
  readings.forEach((r, i) => {
    const expect = `${r.label}: ${r.value ?? `Unavailable: ${r.gap}`} · ${readingSource(r, entry.conditions.at, 'UTC')}`
      + (r.validAt !== null ? ` · Valid ${new Date(r.validAt).toISOString()}` : '') + (r.issuedAt !== null ? ` · Run ${new Date(r.issuedAt).toISOString()}` : '');
    assert.equal(lines[i], esc(expect), `reading ${i} as stored`);
  });
  assert.ok(lines[0].startsWith('Wind: 12 kt · '));
  assert.ok(lines.some(l => l.includes('Unavailable: ')), 'a stored gap keeps its English wrapper');
  assert.ok(!/No disponible|Válido|Corrida|Viento|Oleaje/.test(lines.join('\n')), 'nothing in the snapshot is translated');
  const none = render(h(LogEntry, {entry: empty, tz: 'UTC', lang: 'es'}));
  assert.ok(none.includes('Sin captura (no se registró ninguna captura)'));
  assert.ok(none.includes('Condiciones no disponibles en el momento del registro.'));
  assert.ok(!/Datos del pronóstico|lang="en">[^<]*:/.test(none), 'no invented source or data for null conditions');
  assert.equal(JSON.stringify(entry), frozen, 'rendering does not change the entry');
  assert.equal(storage.getItem(), raw, 'stored bytes unchanged');
  assert.equal(storage.writes(), 0, 'reading and rendering never write');
  assert.ok(util.isDeepStrictEqual(readEntries(storage), JSON.parse(raw)));
});

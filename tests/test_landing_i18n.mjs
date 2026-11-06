// SC0707-05: the landing in Spanish. It resolves the language as the map app does (web/i18n.ts initLanguage), sets the document lang
// before anything is mounted, and its copy (the static hero and footer, the port input, the four profile choices, the readings strip with its
// "out at sea" caveat, the live verdict's word and reason) comes from catalog/app/strings.json. English output stays byte for byte.
// Synthetic fixtures; no network, no provider requests.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {gzipSync} from 'node:zlib';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {catalogueProblems, COVERED} from '../scripts/check_copy.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;
const REGION = JSON.parse(await readFile(join(ROOT, 'dist/regions/morro-bay/region.json'), 'utf8'));
const PAGE = 'https://s.test/', HOUR = 3_600_000, NOW_MS = Date.parse('2026-10-07T20:00:00Z');
const ago = min => new Date(NOW_MS - min * 60000).toISOString();
const source = (name, station, units, rows, extra = {}) => ({name, status: 'ok', max_age_hours: 2, data: {station, units, observations: rows}, ...extra});
const FEED = {schema_version: 1, region_id: 'morro-bay', generated_at: ago(12), sources: {
  offshore: source('Cape San Martin offshore', '46028', {WDIR: 'degT', WSPD: 'm/s', GST: 'm/s'}, [{time: ago(20), WDIR: 320, WSPD: 7, GST: 9}]),
  'diablo-spectrum': source('Diablo Canyon swell and wind waves', '46215', {SwH: 'm', SwP: 'sec', SwD: '-'}, [{time: ago(34), SwH: 0.7, SwP: 10.5, SwD: 'WNW'}]),
  diablo: source('Diablo Canyon', '46215', {WTMP: 'degC', WVHT: 'm'}, [{time: ago(200), WTMP: 14.5, WVHT: 1}])}};
const coops = minutes => minutes.map(([min, v]) => ({t: new Date(NOW_MS - min * 60000).toISOString().slice(0, 16).replace('T', ' '), v, s: '0.01', f: '0,0,0,0', q: 'p'}));
const TIDE = {data: coops([[114, '2.10'], [60, '2.52'], [6, '3.04']])};

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'landing-i18n-')), 'm.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {initLanguage, language, LANGUAGE_KEY, t, STRINGS} from './web/i18n.ts';
      export {applyLandingCopy, portCopy} from './web/landing/copy.ts';
      export {LandingApp, LandingHead, LiveVerdict, NAV} from './web/landing/Landing.tsx';
      export {PortInput, PortDialog} from './web/landing/PortInput.tsx';
      export {ProfileStep, STEP_COPY} from './web/landing/ProfileStep.tsx';
      export {Readout} from './web/landing/Readout.tsx';
      export {buoyReadings, tideReading, loadReadout, fromHarbor, DEFAULT_PLACE} from './web/landing/readings.ts';
      export {loadLandingVerdict, REFERENCE_BOAT_LABEL} from './web/landing/live-verdict.ts';
      export {Verdict, dailyFeed, regionalForecast} from './web/brief/Brief.tsx';
      export {parseConditionsForecast} from './web/conditions.ts';
      export {regionInfo, createRegionReader} from './web/app/App.tsx';
      export {hour, day, profile} from './web/state.ts';
      export {loadLimits, savedLimits} from './web/limits.ts';
      export {COPY} from './web/ports.ts';
      export {PROFILE_NOTES, PROFILE_TABLE} from './web/profile.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  return (mod = await import(pathToFileURL(out).href));
}

/** Run `fn` with the page in `lang`; always back to English. */
async function inLang(m, lang, fn) { m.language.value = lang; try { return await fn(); } finally { m.language.value = 'en'; } }
const port = (id, name, status = 'active') => ({id, name, region: id, status, forecast_point: id, forecast_name: name, match: [35, -120]});
const noop = () => {};

// ---- language: the same resolution as web/i18n.ts, set before anything mounts ----

test('landing_language_precedence_and_blocked_storage: the shared resolver, the document lang, only the explicit-link write, and no crash on a blocked storage', async () => {
  const m = await load();
  const env = (over = {}) => { const writes = [], doc = {documentElement: {lang: 'en'}}, store = new Map(over.stored ? [[m.LANGUAGE_KEY, over.stored]] : []);
    return {writes, doc, store, args: {search: over.search ?? '', languages: over.languages, doc, storage: over.storage ?? {getItem: k => store.get(k) ?? null, setItem: (k, v) => { writes.push([k, v]); store.set(k, v); }}}}; };
  try {
    let e = env({languages: ['es-MX', 'en-US']});
    assert.equal(m.initLanguage(e.args), 'es'); assert.equal(e.doc.documentElement.lang, 'es'); assert.equal(m.language.value, 'es');
    assert.deepEqual(e.writes, [], 'a browser language alone writes nothing');
    e = env({stored: 'en', languages: ['es-MX']});
    assert.equal(m.initLanguage(e.args), 'en', 'a stored choice beats the browser'); assert.equal(e.doc.documentElement.lang, 'en');
    e = env({stored: 'en', languages: ['en'], search: '?lang=es'});
    assert.equal(m.initLanguage(e.args), 'es', '?lang= beats the stored choice'); assert.deepEqual(e.writes, [[m.LANGUAGE_KEY, 'es']], 'the one existing explicit-preference write');
    for (const languages of [['fr-FR'], ['xx-!!bad'], [], undefined]) assert.equal(m.initLanguage(env({languages}).args), 'en', JSON.stringify(languages));
    assert.equal(m.initLanguage(env({search: '?lang=fr', languages: ['es']}).args), 'es', 'an unsupported link value is ignored');
    const refusing = {getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); }};
    e = env({storage: refusing, languages: ['es']});
    assert.equal(m.initLanguage(e.args), 'es', 'storage that throws on read: the browser decides');
    e = env({storage: refusing, search: '?lang=es', languages: ['en']});
    assert.equal(m.initLanguage(e.args), 'es', 'storage that throws on write: the link still holds');
    assert.equal(m.initLanguage({search: '', storage: null, languages: undefined, doc: null}), 'en', 'no storage, no languages, no document');
  } finally { m.language.value = 'en'; }
  // main.tsx: the language is resolved before the first mount and before a saved port can navigate; it adds no key, no header fetch and no location request.
  const main = await readFile(join(ROOT, 'web/landing/main.tsx'), 'utf8');
  const at = text => main.indexOf(text);
  assert.ok(at('initLanguage()') > 0 && at('initLanguage()') < at('savedPortTarget(location.href') && at('initLanguage()') < at("mount('landing-shore'"), 'language first');
  assert.ok(at('applyLandingCopy(document, lang)') > at('initLanguage()') && at('applyLandingCopy(document, lang)') < at("mount('landing-shore'"));
  assert.doesNotMatch(main.replace(/\/\/[^\n]*/g, ''), /geolocation|skippercast-language|Accept-Language|setLanguage/, 'no own key, no header fetch, no location request, no language switch');
});

// ---- the static hosts ----

const fakePage = () => {
  const writes = [], host = (attrs, first = 'English') => { const lead = {nodeType: 3, nodeValue: first + ' '}, el = {attrs: {...attrs}, firstChild: lead, _t: first,
    getAttribute: k => el.attrs[k] ?? null, setAttribute: (k, v) => { writes.push(['attr', k, v]); el.attrs[k] = v; }};
    Object.defineProperty(el, 'textContent', {get: () => el._t, set: v => { writes.push(['text', v]); el._t = v; }}); return el; };
  const hosts = [host({'data-i18n': 'landing.hero.title'}), host({'data-i18n': 'brief.terms'}, 'Terms'), host({'data-i18n-lead': 'brief.planning'}, 'Planning aid · not a navigation chart.'), host({'data-i18n-aria': 'landing.aria.public'}), host({'data-i18n': 'landing.nope.unknown'}), host({'data-i18n': 'brief.disclaimer'}, 'Forecasts, observations and habitat carry separate clocks; check the rules before you fish.')];
  const sel = {'[data-i18n]': 'data-i18n', '[data-i18n-lead]': 'data-i18n-lead', '[data-i18n-aria]': 'data-i18n-aria'};
  return {writes, hosts, doc: {querySelectorAll: s => hosts.filter(h => sel[s] in h.attrs)}};
};

test('static_hosts_catalogue_and_budget: English is a no-op; Spanish writes only the marked hosts; the page keeps its English markup and one module', async () => {
  const m = await load();
  let page = fakePage();
  m.applyLandingCopy(page.doc, 'en');
  assert.deepEqual(page.writes, [], 'English makes no DOM write');
  page = fakePage();
  m.applyLandingCopy(page.doc, 'es');
  const [title, terms, planning, nav, unknown, disclaimer] = page.hosts;
  assert.equal(title._t, 'Conoce el agua antes de salir del muelle.');
  assert.equal(terms._t, 'Términos');
  assert.equal(planning.firstChild.nodeValue, 'Ayuda de planificación · no es una carta náutica. ', 'only the lead text node changes; the Terms link after it is kept');
  assert.equal(nav.attrs['aria-label'], 'Información pública');
  assert.equal(unknown._t, 'English', 'an unknown id leaves its host as it is');
  assert.equal(disclaimer._t, 'Los pronósticos, las observaciones y el hábitat tienen relojes separados; revisa las reglas antes de pescar.', 'the actual first-paint helper translates the footer warning');
  assert.equal(page.writes.length, 4, 'three text hosts and aria-label; the lead text node is the fifth write');
  // dist/landing.html: every marked host names a catalogue id with an es value; English text, links, metadata and scripts are untouched.
  const html = await readFile(join(ROOT, 'dist/landing.html'), 'utf8');
  const ids = [...html.matchAll(/data-i18n(?:-lead)?="([^"]+)"/g)].map(x => x[1]);
  assert.ok(ids.length >= 12, 'the hero and the footer are marked');
  for (const id of ids) assert.ok(m.STRINGS[id]?.es?.trim(), `${id} has an es value`);
  assert.match(html, /<html lang="en">/, 'no-JS stays English');
  assert.deepEqual([...html.matchAll(/<script\b[^>]*>/g)].map(x => x[0]), ['<script type="application/ld+json">', '<script type="module" src="../web/landing/main.tsx">'], 'no new script');
  assert.match(html, /<p class="landing-lede" data-i18n="landing\.hero\.lede">Wind, swell, water temperature and tide from fixed Central Coast buoys/);
  for (const id of ids) assert.equal(html.includes(`>${m.t(id, 'en')}<`) || html.includes(`>${m.t(id, 'en')} <`), true, `${id}: the static English is the catalogue's en`);
  // The hero Spanish is the frozen text.
  assert.equal(m.t('landing.hero.eyebrow', 'es'), 'Costa de California central · lecturas en vivo');
  assert.equal(m.t('landing.hero.lede', 'es'), 'Viento, oleaje, temperatura del agua y marea de boyas fijas de la Costa Central y un mareógrafo, cada lectura con su estación y antigüedad, junto al fondo marino y las corrientes en un solo mapa.');
  // The files are covered, the catalogue and the files are clean, and a bare literal in any of them would fail the lint.
  for (const file of ['main.tsx', 'copy.ts', 'Landing.tsx', 'PortInput.tsx', 'ProfileStep.tsx', 'Readout.tsx', 'readings.ts', 'live-verdict.ts']) assert.ok(COVERED.includes(`web/landing/${file}`), file);
  assert.deepEqual(catalogueProblems(), []);
  const slice = JSON.parse(await readFile(join(ROOT, 'web/landing/strings.generated.json'), 'utf8'));
  for (const [, id] of html.matchAll(/data-i18n(?:-lead|-aria)?="([^"]+)"/g)) {
    assert.ok(Object.hasOwn(slice, id), `${id}: every static translation host is in the first-paint slice`);
    for (const lang of ['en', 'es']) assert.ok(slice[id][lang]?.trim(), `${id}: first-paint ${lang} exists`);
  }
  for (const [id, entry] of Object.entries(slice)) assert.deepEqual(entry, m.STRINGS[id], `${id}: generated first-paint copy matches the shared catalogue`);
  assert.equal(JSON.parse(await readFile(join(ROOT, 'scripts/startup-budget.json'), 'utf8')).precache.install_raw_max, 707311, 'the install ceiling is the SC1352-03 measurement + 10% (the landing page adds nothing to it)');
  for (const file of ['Landing.tsx', 'PortInput.tsx', 'Readout.tsx', 'readings.ts']) {
    const root = await mkdtemp(join(tmpdir(), 'landing-lint-')), {mkdir, writeFile} = await import('node:fs/promises');
    await mkdir(join(root, 'catalog/app'), {recursive: true}); await mkdir(join(root, 'web/landing'), {recursive: true});
    await writeFile(join(root, 'catalog/app/strings.json'), JSON.stringify({strings: {'x.ok': {en: 'One', es: 'Uno'}}}));
    await writeFile(join(root, `web/landing/${file}`), "export const a = () => <p>Not translated yet</p>;\nexport const b = 'Not translated either';\n");
    assert.match(catalogueProblems(root).join('\n'), new RegExp(`web/landing/${file}:\\d bare literal`), `${file}: an untranslated literal fails the lint`);
  }
  // First paint: neither language pulls the live verdict, the brief, the app or the map engine into the entry chunk, and the entry stays inside its budget.
  const result = await build({entryPoints: [join(ROOT, 'web/landing/main.tsx')], bundle: true, splitting: true, format: 'esm', platform: 'browser', minify: true, outdir: join(await mkdtemp(join(tmpdir(), 'landing-budget-')), 'out'),
    write: false, metafile: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins, external: ['*.css']});
  const outputs = Object.values(result.metafile.outputs), entry = outputs.find(o => o.entryPoint?.endsWith('web/landing/main.tsx'));
  for (const mod of ['web/landing/readings.ts', 'catalog/app/strings.json', 'web/landing/live-verdict.ts', 'web/brief/Brief.tsx', 'web/brief/verdict.ts', 'web/app/App.tsx']) assert.ok(!Object.keys(entry.inputs).includes(mod), `${mod} is not in the entry chunk`);
  // The initial JavaScript is the entry and every chunk it imports statically (dynamic imports load after first paint); it carries the hosts' helper and the catalogue.
  const byPath = Object.fromEntries(Object.entries(result.metafile.outputs)), entryPath = Object.keys(byPath).find(k => byPath[k] === entry);
  const initial = new Set(), walk = path => { if (initial.has(path)) return; initial.add(path); for (const i of byPath[path]?.imports ?? []) if (i.kind === 'import-statement') walk(i.path); };
  walk(entryPath);
  const initialInputs = [...initial].flatMap(p => Object.keys(byPath[p].inputs));
  assert.ok(initialInputs.includes('web/landing/copy.ts') && initialInputs.includes('web/landing/strings.generated.json'), 'the static hosts helper and the catalogue are in the initial JS');
  const budget = JSON.parse(await readFile(join(ROOT, 'scripts/startup-budget.json'), 'utf8')).bundles['landing.html'].js_gzip_max;
  const size = [...initial].reduce((sum, p) => sum + gzipSync(result.outputFiles.find(f => f.path.endsWith(`/${p.split('/').pop()}`)).contents).length, 0);
  assert.ok(size < budget, `the initial JS (${size} B gzipped) is inside the landing budget (${budget} B)`);
});

// ---- the funnel ----

test('landing_english_bytes_and_spanish_funnel: English is the old copy word for word; Spanish renders the port, profile and status copy with names escaped', async () => {
  const m = await load();
  const ports = [port('morro-bay', 'Morro Bay'), port('ventura', '<b>Odd</b> & Co {n}', 'preview')];
  // English: the catalogue is web/ports.ts COPY and the profile table, byte for byte.
  const en = m.portCopy('en');
  for (const k of ['question', 'placeholder', 'finding', 'unsupported', 'unavailable', 'none', 'empty', 'privacy', 'forget', 'forgotten']) assert.equal(en[k], m.COPY[k], k);
  for (const p of ports) assert.deepEqual([en.found(p), en.detail(p)], [m.COPY.found(p), m.COPY.detail(p)]);
  for (const p of ['boat', 'shore', 'spear', 'kayak']) assert.deepEqual([m.t(`where.profile.${p}`, 'en'), m.t(`landing.profile.note.${p}`, 'en')], [m.PROFILE_TABLE[p].label, m.PROFILE_NOTES[p]], p);
  assert.deepEqual([m.STEP_COPY.title, m.STEP_COPY.back, m.STEP_COPY.loading('Morro Bay'), m.STEP_COPY.ready('Morro Bay')], ['How do you fish?', 'Change port', 'Loading the Morro Bay map…', 'Morro Bay map files ready.']);
  assert.deepEqual(m.NAV.map(n => n.label), ['Fleet', 'Reports', 'How it’s built']);
  const props = {ports, onChoose: noop, onExplore: noop, storage: null, cookies: null};
  const explicit = await inLang(m, 'en', () => m.render(m.h(m.PortInput, props)));
  assert.equal(m.render(m.h(m.PortInput, props)), explicit, 'default English equals explicit English');
  assert.ok(explicit.includes('placeholder="Try Morro Bay, Ventura, San Diego…"') && explicit.includes('>Go<') && explicit.includes('>See all 2 ports<') && explicit.includes('>Use my location<') && explicit.includes('>Explore the coast<'));
  // Spanish.
  const es = await inLang(m, 'es', () => ({
    port: m.render(m.h(m.PortInput, {...props, ports: [port('morro-bay', 'Morro Bay'), port('ventura', '<b>Odd</b> & Co', 'preview')]})),
    down: m.render(m.h(m.PortInput, {...props, ports: [], onRetry: noop})), wait: m.render(m.h(m.PortInput, {...props, ports: null})),
    step: m.render(m.h(m.ProfileStep, {place: 'Morro Bay', warm: 'loading', onChoose: noop, onBack: noop})),
    ready: m.render(m.h(m.ProfileStep, {place: 'Morro Bay', warm: 'ready', current: 'kayak', onChoose: noop, onBack: noop})),
    failed: m.render(m.h(m.ProfileStep, {place: 'Morro Bay', warm: 'failed', onChoose: noop, onBack: noop})),
    dialog: m.render(m.h(m.PortDialog, {open: false, onClose: noop}, 'inner')), head: m.render(m.h(m.LandingHead, {href: PAGE})),
    app: m.render(m.h(m.LandingApp, {href: PAGE, navigate: noop, load: false})),
  }));
  for (const text of ['¿Desde dónde sales al agua?', 'placeholder="Prueba Morro Bay, Ventura, San Diego…"', '>Ir<', '>Ver los 2 puertos<', '>Usar mi ubicación<', '>Explorar la costa<', 'Área cartografiada · Morro Bay', 'Vista previa regional · &lt;b>Odd&lt;/b> &amp; Co', 'Tu elección se guarda en este navegador.'])
    assert.ok(es.port.includes(text), text);
  assert.ok(!es.port.includes('<b>Odd'), 'a port name with markup is escaped, not rendered');
  assert.ok(es.down.includes('Las opciones de puerto no están disponibles. Explora la costa en su lugar.') && es.down.includes('>Intentar de nuevo<'));
  assert.ok(es.wait.includes('Cargando puertos…'));
  for (const text of ['¿Cómo pescas?', 'Esto define el límite de profundidad', '>Barco<', '>Costa<', '>Pesca submarina<', '>Kayak<', 'Marcas de arrecife y fondo marino hasta 300 ft; fondo marino y corrientes en el mapa.', 'Cargando el mapa de Morro Bay…', '>Cambiar puerto<'])
    assert.ok(es.step.includes(text), text);
  assert.ok(es.ready.includes('Archivos del mapa de Morro Bay listos.') && es.ready.includes('aria-pressed="true"'));
  assert.match(es.failed, /<p class="landing-step-status" role="status" data-warm="failed"><\/p>/, 'a failed warm-up still says nothing');
  assert.ok(es.step.includes('data-profile="boat"') && es.step.includes('data-profile="kayak"'), 'the profile keys stay');
  assert.ok(es.dialog.includes('>Cambiar puerto<') && es.dialog.includes('aria-label="Cerrar"'));
  for (const text of ['aria-label="Sitio"', '>Flota<', '>Informes<', '>Cómo se hizo<', '>Iniciar sesión<', 'href="/map?region=morro-bay&amp;view=fleet"', 'href="/sources"']) assert.ok(es.head.includes(text), text);
  assert.ok(es.app.includes('¿Desde dónde sales al agua?') && es.app.includes('Últimas lecturas · Morro Bay &amp; Avila') && es.app.includes('Cargando las últimas lecturas…') && es.app.includes('Consultando las boyas') && es.app.includes('>Hora por hora en el mapa<'), 'LandingApp in Spanish');
  const pc = m.portCopy('es');
  assert.deepEqual([pc.finding, pc.unsupported, pc.unavailable, pc.none, pc.empty, pc.forget, pc.forgotten, pc.found(ports[0])], ['Buscando un puerto cercano…', 'La ubicación no está disponible. Busca un puerto en su lugar.', 'No se pudo obtener la ubicación. Busca un puerto en su lugar.', 'No hay un puerto de la lista cerca. Busca o explora la costa.', 'Aún no hay un puerto que coincida. Prueba un puerto cercano o explora la costa.', 'Olvidar puerto guardado', 'Se eliminó el puerto guardado. Esta visita mantiene la selección actual.', 'Puerto de la lista más cercano: Morro Bay. Selecciónalo abajo para continuar.']);
  assert.equal(pc.found(ports[1]), 'Puerto de la lista más cercano: <b>Odd</b> & Co {n}. Selecciónalo abajo para continuar.', 'a name is a value: markup and braces are not expanded');
  // Every new id has both languages and the same placeholders.
  for (const [id, e] of Object.entries(m.STRINGS)) if (id.startsWith('landing.')) assert.deepEqual([...(e.en.match(/\{\w+\}/g) ?? [])].sort(), [...(e.es.match(/\{\w+\}/g) ?? [])].sort(), id);
});

// ---- the readings strip ----

test('spanish_readings_missing_stale_backup_and_caveat: the offshore caveat and age rule in Spanish; names, ids and the tide note as published; same numbers as English', async () => {
  const m = await load();
  const [wind, swell, water] = m.buoyReadings(FEED, REGION, NOW_MS, 'es'), [windEn, swellEn, waterEn] = m.buoyReadings(FEED, REGION, NOW_MS);
  assert.deepEqual(m.buoyReadings(FEED, REGION, NOW_MS, 'en'), m.buoyReadings(FEED, REGION, NOW_MS), 'explicit English is the default');
  assert.equal(windEn.basis, 'Observed wind at the Cape San Martin offshore buoy, about 56 nm WNW of Morro Bay harbor, out at sea: not a harbor or launch reading. Averaged over 8 minutes, with the peak gust; stale after 2 h.');
  assert.equal(wind.basis, 'Viento observado en la boya Cape San Martin offshore, a unos 56 nm WNW de Morro Bay, mar adentro: no es una lectura del puerto ni del punto de salida al agua. Promedio de 8 minutos, con la ráfaga máxima; desactualizado después de 2 h.');
  assert.match(swell.basis, /^Altura, período y dirección del mar de fondo del espectro de olas en la boya Diablo Canyon, a unos 10 nm S de Morro Bay; se excluyen las olas de viento; desactualizado después de 2 h\.$/);
  assert.match(water.basis, /^Temperatura superficial del agua medida en la boya Diablo Canyon, a unos 10 nm S de Morro Bay; desactualizado después de 2 h\.$/);
  assert.deepEqual([wind.label, swell.label, water.label], ['Viento', 'Oleaje', 'Agua']);
  assert.deepEqual([wind.reading, wind.unit, wind.detail, wind.source, wind.stale], [windEn.reading, windEn.unit, 'NW · ráfagas de 17', windEn.source, windEn.stale], 'same number, threshold and station');
  assert.deepEqual([swell.reading, swell.detail, water.reading, water.source, water.stale], ['2,3', '11 s · WNW', waterEn.reading, waterEn.source, waterEn.stale]);
  assert.equal(swellEn.reading, '2.3');
  // Missing, malformed units, a future reading, and an absent feed: Unknown states as in English, never filled from another station.
  const missing = m.buoyReadings(null, {}, NOW_MS, 'es');
  assert.deepEqual(missing.map(r => [r.reading, r.stale, r.source.endsWith('· no disponible')]), [['Sin lectura', true, true], ['Sin lectura', true, true], ['Sin lectura', true, true]]);
  const badUnit = structuredClone(FEED); badUnit.sources.offshore.data.units.WSPD = 'knots';
  assert.equal(m.buoyReadings(badUnit, REGION, NOW_MS, 'es')[0].reading, 'Sin lectura');
  const future = structuredClone(FEED); future.sources.diablo.data.observations[0].time = ago(-30);
  assert.equal(m.buoyReadings(future, REGION, NOW_MS, 'es')[2].stale, true, 'a future reading is stale');
  assert.equal(m.buoyReadings(future, REGION, NOW_MS)[2].stale, true);
  // No age limit: the Spanish rule says only the age is shown; no "stale after".
  const unlimited = structuredClone(FEED); delete unlimited.sources.diablo.max_age_hours;
  assert.match(m.buoyReadings(unlimited, REGION, NOW_MS, 'es')[2].basis, /la fuente no indica un límite de antigüedad, así que solo se muestra la antigüedad\.$/);
  // Backup station sharing a role: named as itself, "de respaldo", and the shared-station sentence in Spanish.
  const backup = structuredClone(FEED); backup.sources.diablo.station = '46011'; backup.sources.diablo.fallback_for = '46215'; backup.sources.diablo.data.station = '46011';
  backup.sources['diablo-spectrum'].data.station = '46011'; backup.sources['diablo-spectrum'].station = '46011'; backup.sources['diablo-spectrum'].fallback_for = '46215';
  const b = m.buoyReadings(backup, REGION, NOW_MS, 'es'), bEn = m.buoyReadings(backup, REGION, NOW_MS);
  assert.ok(b[2].basis.includes('boya NDBC 46011') && b[2].basis.includes('de respaldo para 46215'), b[2].basis);
  assert.ok(bEn[2].basis.includes('NDBC buoy 46011') && bEn[2].basis.includes('the backup for 46215'), bEn[2].basis);
  const shared = structuredClone(FEED); Object.assign(shared.sources.offshore, {station: '46215', fallback_for: '46028'}); shared.sources.offshore.data.station = '46215';
  assert.ok(m.buoyReadings(shared, REGION, NOW_MS, 'es')[2].basis.endsWith(' Misma estación que la lectura de viento, no una medición independiente.'));
  assert.ok(m.buoyReadings(shared, REGION, NOW_MS)[2].basis.endsWith(' Same station as the wind reading, not a separate measurement.'));
  // A buoy with no published name uses the area word and invents no station.
  const unnamed = structuredClone(FEED); delete unnamed.sources.offshore.name; delete unnamed.sources.diablo.name;
  assert.match(m.buoyReadings(unnamed, {}, NOW_MS, 'es')[0].basis, /^Viento observado en la boya mar adentro,/);
  assert.match(m.buoyReadings(unnamed, {}, NOW_MS, 'es')[2].basis, /^Temperatura superficial del agua medida en la boya costera;/);
  // Tide: rise, fall, slack, the note and the station name as published; English unchanged.
  const note = 'Measured at the Port San Luis pier.';
  const rise = m.tideReading(TIDE, '9412110', 'Port San Luis', NOW_MS, note, 'es'), riseEn = m.tideReading(TIDE, '9412110', 'Port San Luis', NOW_MS, note);
  assert.equal(rise.basis, `Nivel del agua observado en Port San Luis, en pies sobre la bajamar media inferior, cada 6 minutos; desactualizado después de 1 h. ${note}`);
  assert.equal(riseEn.basis, `Observed water level at Port San Luis, in feet above mean lower low water, every 6 minutes; stale after 1 h. ${note}`);
  assert.deepEqual([rise.label, rise.detail, riseEn.detail, rise.reading, riseEn.reading], ['Marea', 'subiendo', 'rising', '3', '3.0']);
  const fall = m.tideReading({data: coops([[114, '3.50'], [6, '2.00']])}, '9412110', 'X', NOW_MS, undefined, 'es'), slack = m.tideReading({data: coops([[114, '2.00'], [6, '2.01']])}, '9412110', 'X', NOW_MS, undefined, 'es');
  assert.deepEqual([fall.detail, slack.detail, fall.reading], ['bajando', 'sin cambio', '2']);
  assert.match(m.tideReading(null, '9412110', undefined, NOW_MS, undefined, 'es').basis, /^Nivel del agua observado en la estación de mareas,/);
  assert.equal(m.tideReading(null, '9412110', undefined, NOW_MS).basis.startsWith('Observed water level at the tide station,'), true);
  assert.equal(m.tideReading(null, '9412110', 'X', NOW_MS, undefined, 'es').reading, 'Sin lectura');
  // The strip renders it; the title adds no English "area" in Spanish, and the feed line follows the feed's state.
  const data = {readings: [...m.buoyReadings(FEED, REGION, NOW_MS, 'es'), rise], feed: {age: '12 min', stale: false}, place: 'Morro Bay & Avila area'};
  const html = await inLang(m, 'es', () => m.render(m.h(m.Readout, {data, conditions: '/map?x=1'})));
  assert.ok(html.includes('Últimas lecturas · Morro Bay &amp; Avila area</h2>') && html.includes('Fuente de boyas actualizada hace 12 min') && html.includes('>Hora por hora en el mapa<'), html.slice(0, 400));
  assert.ok(html.includes('mar adentro: no es una lectura del puerto'), 'the caveat is on the page');
  const render = (feed, lang) => inLang(m, lang, () => m.render(m.h(m.Readout, {data: {...data, feed}})));
  assert.ok((await render({age: '3 h', stale: true}, 'es')).includes('Fuente de boyas desactualizada, actualizada hace 3 h'));
  assert.ok((await render({age: null, stale: true}, 'es')).includes('Fuente de boyas no disponible'));
  assert.ok((await render({age: '3 h', stale: true}, 'en')).includes('Buoy feed stale, updated 3 h ago'));
  // loadReadout passes the language through and makes only the requests English makes.
  const asked = [], fetchFn = async url => { asked.push(String(url)); return {ok: false, status: 404, json: async () => ({})}; };
  const askedEn = [], fetchEn = async url => { askedEn.push(String(url)); return {ok: false, status: 404, json: async () => ({})}; };
  const loaded = await m.loadReadout(fetchFn, 'morro-bay', () => NOW_MS, 'es'); await m.loadReadout(fetchEn, 'morro-bay', () => NOW_MS);
  assert.deepEqual(asked, askedEn); assert.equal(loaded.readings[3].label, 'Marea'); assert.equal(loaded.place, 'Morro Bay & Avila');
});

// ---- the live verdict ----

const DAILY = {...montereyDaily, region_id: 'morro-bay'};
function forecastFeed(now, ageH = 6) {
  const start = Math.floor(now.getTime() / 86_400_000) * 86400 - 86400, issued = now.getTime() / 1000 - ageH * 3600;
  const time = Array.from({length: 9 * 24}, (_, i) => start + i * 3600), day = t => Math.floor((t - start) / 86400);
  const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(t => typeof v === 'function' ? v(t) : v)]))}});
  const meta = {last_run_initialisation_time: issued, data_end_time: time.at(-1)};
  return {region_id: 'morro-bay', retrieved: now.getTime() - 20 * 60_000, requested_points: [['central', 35.36, -120.94], ['offshore-1-0', 35.3, -121.25]],
    models: {gfs_global: {meta, data: [0, 1].map(() => series({wind_speed_10m: [t => 4 + 3 * day(t), 'kn'], wind_gusts_10m: [t => 8 + 4 * day(t), 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [30, '%']}))},
      ncep_gfswave016: {meta, data: [0, 1].map(() => series({wave_height: [t => 2 + day(t), 'ft'], wave_period: [12, 's']}))}}};
}
const feeds = (now, {missing = [], ageH = 6} = {}) => async url => {
  const path = new URL(String(url), PAGE).pathname;
  const body = missing.some(x => path.includes(x)) ? null : path.endsWith('/region.json') ? REGION : path === '/feeds/data/regions/morro-bay/latest.json' ? DAILY : path === '/api/forecast' ? forecastFeed(now, ageH) : null;
  return body ? {ok: true, status: 200, json: async () => body} : {ok: false, status: 404, json: async () => ({}), body: null};
};
async function onDevice(entries, fn) {
  const store = {getItem: k => entries.get(k) ?? null, setItem: () => {}, removeItem: () => {}, clear: () => {}, key: () => null, length: 0};
  const had = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {value: store, configurable: true, writable: true});
  try { return await fn(); } finally { if (had) Object.defineProperty(globalThis, 'localStorage', had); else delete globalThis.localStorage; }
}
const NOW = new Date('2026-10-08T21:00:00Z');
const boatEntry = boat => new Map([['skippercast-boat-v1', JSON.stringify({schema_version: 1, boat})]]);

/** The app's own Verdict limit sentence in `lang` for the same feeds: what the landing's reason must equal. */
async function appLimit(m, now, lang, opts) {
  const fetchFn = feeds(now, opts), info = await m.createRegionReader(fetchFn)('morro-bay');
  m.regionInfo.value = info; m.dailyFeed.value = DAILY; m.hour.value = null; m.day.value = null; m.profile.value = 'boat';
  const f = await fetchFn('/api/forecast'); m.regionalForecast.value = f.ok ? m.parseConditionsForecast(await f.json(), 'morro-bay', info.center) : null;
  try { return await onDevice(new Map(), () => inLang(m, lang, () => { m.loadLimits(); return /<p class="app-verdict-limit">([^<]*)</.exec(m.render(m.h(m.Verdict, {now})))?.[1] ?? null; })); }
  finally { m.regionInfo.value = null; m.dailyFeed.value = null; m.regionalForecast.value = null; m.savedLimits.value = {}; }
}

test('spanish_live_reason_parity: the verdict word, day, boat and reason in Spanish, the reason the app\'s own; English unchanged; scoring invariant', async () => {
  const m = await load();
  const run = (entries, opts, lang, now = NOW) => onDevice(entries, () => lang === undefined ? m.loadLandingVerdict(feeds(now, opts), now, PAGE) : m.loadLandingVerdict(feeds(now, opts), now, PAGE, lang));
  const cases = {rated: {}, noForecast: {missing: ['/api/forecast']}, stale: {ageH: 30}};
  for (const [name, opts] of Object.entries(cases)) {
    const en = await run(new Map(), opts), explicit = await run(new Map(), opts, 'en'), es = await run(new Map(), opts, 'es');
    assert.deepEqual(explicit, en, `${name}: explicit English is the default`);
    assert.deepEqual([es.verdict, es.date, es.href, es.place], [en.verdict, en.date, en.href, en.place], `${name}: the rating, day and link do not depend on the language`);
    assert.equal(es.word, {comfortable: 'Cómodo', marginal: 'Marginal', rough: 'Agitado', unknown: 'Desconocido'}[en.verdict]);
    assert.equal(es.day, 'Mañana'); assert.equal(en.day, 'Tomorrow');
    assert.equal(es.sentence, await appLimit(m, NOW, 'es', opts), `${name}: the reason is the app's Spanish sentence`);
    assert.equal(en.sentence, await appLimit(m, NOW, 'en', opts));
    assert.notEqual(es.sentence, en.sentence, `${name}: the Spanish reason is not the English one`);
    assert.doesNotMatch(es.sentence, /\b(?:Wind of|Seas|forecast|marine alert)\b/, `${name}: no English reason fragments`);
    assert.equal(es.boatName, 'barco de referencia de 23 ft'); assert.equal(en.boatName, 'reference 23 ft boat'); assert.equal(m.REFERENCE_BOAT_LABEL, 'reference 23 ft boat');
  }
  assert.equal((await run(new Map(), cases.noForecast, 'es')).verdict, 'unknown', 'no forecast reads Unknown, never a calmer word');
  assert.notEqual((await run(new Map(), cases.stale, 'es')).verdict, 'comfortable', 'a stale run holds');
  // Saved boats: a custom name stays literal; the no-name forms and the model caveat follow the language.
  const named = await run(boatEntry({name: 'Wren <b>', loa_ft: 31}), {}, 'es');
  assert.equal(named.boatName, 'Wren <b>'); assert.equal(named.boatNote, 'Las calificaciones son un modelo empírico para casco de planeo ajustado a un barco de 23 ft, no un cálculo de navegabilidad.');
  assert.equal((await run(boatEntry({name: 'Wren', loa_ft: 31}), {})).boatNote, 'Ratings are a planing-hull rule-of-thumb model tuned on a 23 ft boat, not a sea-keeping calculation.');
  for (const name of ['your boat', 'your 19 ft boat', 'your 19.5 ft boat']) {
    for (const lang of ['en', 'es']) assert.equal((await run(boatEntry({name, loa_ft: 19}), {}, lang)).boatName, name, `${lang}: custom name collision stays literal`);
  }
  assert.equal((await run(boatEntry({}), {}, 'es')).boatName, 'tu barco');
  assert.equal((await run(boatEntry({name: '19 ft boat', loa_ft: 19}), {}, 'es')).boatName, 'tu barco de 19 ft');
  assert.equal((await run(boatEntry({loa_ft: 19}), {}, 'es')).boatName, 'tu barco de 19 ft');
  assert.equal((await run(boatEntry({loa_ft: 19}), {})).boatName, 'your 19 ft boat');
  assert.equal((await run(boatEntry({name: 'Wren', loa_ft: 23}), {}, 'es')).boatNote, null, 'inside the reference range: no caveat');
  assert.equal((await run(new Map([['skippercast-boat-v1', '{broken']]), {}, 'es')).boatName, 'barco de referencia de 23 ft', 'an unreadable boat is the reference boat');
  // The wrapper in both languages, live and from saved copies; the word and reason are shown as given.
  const v = {verdict: 'marginal', word: 'Marginal', sentence: 'Una razón.', day: 'Mañana', date: '2026-10-09', place: 'Morro Bay & Avila', href: '/map?x=1', boatName: 'tu barco', boatNote: null};
  const esLive = await inLang(m, 'es', () => m.render(m.h(m.LiveVerdict, {v}))), esSaved = await inLang(m, 'es', () => m.render(m.h(m.LiveVerdict, {v, saved: true})));
  assert.ok(esLive.includes('aria-label="Resumen de mañana"') && esLive.includes('Mañana cerca de Morro Bay &amp; Avila, tu barco: <strong') && esLive.includes('>Abrir el resumen completo<') && esLive.includes('<p class="landing-verdict-limit">Una razón.</p>'), esLive);
  assert.ok(esSaved.includes('aria-label="Resumen de mañana, de copias guardadas"') && esSaved.includes('De copias guardadas, no en vivo: Mañana cerca de'), esSaved);
  const enV = {...v, day: 'Tomorrow', boatName: 'reference 23 ft boat', sentence: 'A reason.'};
  assert.ok(m.render(m.h(m.LiveVerdict, {v: enV})).includes('<p class="landing-verdict-head">Tomorrow near Morro Bay &amp; Avila, reference 23 ft boat: <strong class="landing-verdict-word" data-verdict="marginal">Marginal</strong></p>'));
  assert.ok(m.render(m.h(m.LiveVerdict, {v: enV, saved: true})).includes('aria-label="Tomorrow’s brief, from saved copies"'));
  // A language switch cannot change the verdict a reader already has: the loader's language is the argument, not the page's.
  assert.equal((await inLang(m, 'es', () => run(new Map(), {}, 'en'))).day, 'Tomorrow');
  // No stored value is written and no key is read besides the boat and the limits.
  const reads = []; const spy = new Map(); spy.get = k => { reads.push(k); return null; };
  await onDevice(spy, () => m.loadLandingVerdict(feeds(NOW), NOW, PAGE, 'es'));
  assert.ok(reads.every(k => ['skippercast-boat-v1', 'skippercast-limits-v1'].includes(k)), reads.join());
  assert.ok(HOUR > 0);
});

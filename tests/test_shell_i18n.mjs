// SC0707-07: the app shell (masthead, phone sheet, command bar, account menu) reads its words and aria labels
// from the string catalogue. English stays as it was; Spanish follows the shared language signal at once.
// Synthetic state only: nothing here touches the network.
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
const NOW = new Date('2026-10-05T20:00:00Z');
const none = {getItem: () => null, setItem() {}};

let shell;
async function load() {
  if (shell) return shell;
  const out = join(await mkdtemp(join(tmpdir(), 'shell-i18n-')), 'shell.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {Masthead, ViewNav, Location, FreshnessDot, ChatEntry, VIEW_LABELS, viewLabel, TAB_VIEWS, MASTHEAD_VIEWS} from './web/app/Masthead.tsx';
    export {CommandBar, PortControl, ShareControl, ProfileSwitch, shellTargetText, shellGroupLabel} from './web/app/CommandBar.tsx';
    export {AccountMenu} from './web/app/AccountMenu.tsx';
    export {Mobile, LayersPanel, ReportsLink} from './web/app/Mobile.tsx';
    export {regionInfo, regionLoad, freshness} from './web/app/App.tsx';
    export {session, boat, accountLabel} from './web/account.ts';
    export {tripIds} from './web/trip.ts';
    export {language, setLanguage} from './web/i18n.ts';
    export {optionText} from './web/species.ts';
    export * as state from './web/state.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
  shell = await import(pathToFileURL(out).href);
  return shell;
}
const text = html => html.replace(/<svg[\s\S]*?<\/svg>/g, '').replace(/<[^>]+>/g, '|').replace(/\|+/g, '|');
async function inLanguage(lang, run) {
  const m = await load();
  m.setLanguage(lang, {storage: none, doc: null});
  const was = globalThis.location;
  globalThis.location = {href: `${ORIGIN}?region=morro-bay`, origin: 'https://s.test'};
  m.state.syncFromURL(`${ORIGIN}?region=morro-bay`);
  try { return await run(m); } finally {
    m.setLanguage('en', {storage: none, doc: null});
    m.session.value = {state: 'loading'}; m.boat.value = null; m.tripIds.value = []; m.regionLoad.value = null; m.regionInfo.value = null;
    m.freshness.value = {state: 'unknown', age: null};
    if (was === undefined) delete globalThis.location; else globalThis.location = was;
  }
}
/** Everything the shell draws in one string, for the en -> es -> en comparison. */
const shellHtml = m => {
  const {render, h} = m;
  return [m.Masthead, m.CommandBar, m.AccountMenu, m.LayersPanel, m.ReportsLink, m.Mobile].map(C => render(h(C, {now: NOW, onClose() {}}))).join('\n');
};

test('shell_es_views_sheet_and_aria: names, aria labels and the phone sheet follow the language; links, keys and tabs do not move', async () => {
  const en = await inLanguage('en', m => ({nav: m.render(m.h(m.ViewNav, {})), tabs: m.render(m.h(m.ViewNav, {icons: true})), labels: {...m.VIEW_LABELS}, mobile: m.render(m.h(m.Mobile, {now: NOW}))}));
  assert.deepEqual(en.labels, {coast: 'Coast', conditions: 'Conditions', history: 'History', fleet: 'Fleet', reports: 'Reports', plan: 'Plan'}, 'the public English names are unchanged');
  const es = await inLanguage('es', m => ({nav: m.render(m.h(m.ViewNav, {})), tabs: m.render(m.h(m.ViewNav, {icons: true})), mobile: m.render(m.h(m.Mobile, {now: NOW})), layers: m.render(m.h(m.LayersPanel, {onClose() {}})),
    reports: m.render(m.h(m.ReportsLink, {})), views: ['coast', 'conditions', 'history', 'fleet', 'reports', 'plan'].map(v => m.viewLabel(v, 'es'))}));
  assert.deepEqual(es.views, ['Costa', 'Condiciones', 'Historial', 'Flota', 'Informes', 'Plan']);
  assert.match(es.nav, /<nav aria-label="Vistas">/);
  assert.deepEqual([...es.nav.matchAll(/>([^<>]+)<\/a>/g)].map(x => x[1]), ['Costa', 'Condiciones', 'Historial', 'Flota', 'Informes']);
  assert.deepEqual([...es.tabs.matchAll(/>([^<>]+)<\/a>/g)].map(x => x[1]), ['Costa', 'Condiciones', 'Historial', 'Informes'], 'Fleet stays off the phone tabs');
  const keys = html => [...html.matchAll(/href="([^"]+)"[^>]*data-view="(\w+)"|data-view="(\w+)"/g)].map(x => (x[1] ?? '') + (x[2] ?? x[3]));
  assert.deepEqual(keys(es.nav), keys(en.nav), 'hrefs and data-view keys are the English ones');
  assert.deepEqual(keys(es.tabs), keys(en.tabs));
  assert.match(es.mobile, /aria-label="Capas"/);
  assert.match(es.mobile, /<section class="ui-sheet app-sheet" data-detent="peek" aria-label="Resumen">/);
  assert.match(es.mobile, /role="group" aria-label="Tiempo"/);
  assert.match(es.mobile, /aria-label="Hora"/);
  assert.match(es.mobile, /role="group" aria-label="Área y puerto"/);
  assert.match(es.mobile, /aria-label="Día"/);
  assert.match(es.layers, />Capas<\/span>.*>Listo<\/button>/s);
  assert.match(es.reports, />Informes<\/a>/);
  assert.doesNotMatch(es.mobile, /aria-label="(?:Layers|Brief|Time|Hour|Day|Profile|Area and port)"/, 'no English aria label survives');
});

test('shell_es_views_sheet_and_aria: location states and every freshness state', async () => {
  const info = {id: 'morro-bay', name: 'Morro Bay & Avila', center: [35.34, -120.965], timezone: 'America/Los_Angeles'};
  await inLanguage('es', m => {
    const loc = (load, i) => { m.regionLoad.value = load; m.regionInfo.value = i; return text(m.render(m.h(m.Location, {}))); };
    assert.match(loc({id: 'morro-bay', state: 'loading'}, null), /Morro Bay —\|Cargando región…/);
    assert.match(loc({id: 'morro-bay', state: 'error'}, null), /Los detalles de la región no están disponibles\. \|Reintentar detalles de la región/);
    assert.match(loc({id: 'morro-bay', state: 'missing'}, null), /No hay una región llamada &quot;morro-bay&quot;\. \|Elige un puerto/);
    assert.match(loc({id: 'morro-bay', state: 'ready'}, info), /Morro Bay &amp; Avila \|35\.34N 120\.97W/, 'the published name and the coordinates are not translated');
    m.state.syncFromURL(ORIGIN);
    assert.match(loc(null, null), /Ningún puerto elegido/);
    const states = {ok: 'Todas las lecturas son recientes', stale: 'Hay una lectura desactualizada', offline: 'Sin conexión', unknown: 'Aún no hay lecturas'};
    for (const [state, words] of Object.entries(states)) {
      m.freshness.value = {state, age: '2 min'};
      const html = m.render(m.h(m.FreshnessDot, {}));
      assert.ok(html.includes(`aria-label="Actualidad: ${words}"`), state);
      assert.ok(html.includes('>2 min<'), 'the supplied age is not translated');
    }
  });
});

test('shell_es_chat_session_gate: loading, offline and advisor=false show no Chat in either language; advisor=true shows the translated text and the same link', async () => {
  for (const [lang, words] of [['en', 'Ask SkipperCast'], ['es', 'Pregúntale a SkipperCast']]) await inLanguage(lang, m => {
    for (const s of [{state: 'loading'}, {state: 'offline'}, {state: 'disabled', advisor: false}, {state: 'signed-out', advisor: false}, {state: 'signed-in', name: null, advisor: false}]) {
      m.session.value = s;
      assert.equal(m.render(m.h(m.ChatEntry, {})), '', `${lang} ${s.state}`);
    }
    for (const s of [{state: 'disabled', advisor: true}, {state: 'signed-out', advisor: true}, {state: 'signed-in', name: null, advisor: true}]) {
      m.session.value = s;
      assert.equal(m.render(m.h(m.ChatEntry, {})), `<a class="ui-button ui-button--quiet" href="/chat.html" data-advisor-entry="true">${words}</a>`);
    }
  });
});

test('shell_es_command_values: profile labels change, values and icons do not; target chrome is translated, target names are not', async () => {
  const profiles = html => [...html.matchAll(/<button[^>]*aria-pressed="(\w+)"[^>]*>(?:<svg.*?<\/svg>)?([^<]+)<\/button>/g)].map(x => x[2]);
  const en = await inLanguage('en', m => m.render(m.h(m.ProfileSwitch, {})));
  const es = await inLanguage('es', m => m.render(m.h(m.ProfileSwitch, {})));
  assert.deepEqual(profiles(en), ['Boat', 'Shore', 'Spear', 'Kayak']);
  assert.deepEqual(profiles(es), ['Barco', 'Orilla', 'Pesca submarina', 'Kayak']);
  assert.match(es, /aria-label="Perfil"/);
  const m = await load();
  const option = (state, group) => ({id: 'lingcod', label: 'Lingcod', group, state, unavailable: false});
  for (const s of ['ranked', 'plan', 'unresearched']) assert.equal(m.shellTargetText(option(s), 'en'), m.optionText(option(s)), 'English is the picker own text');
  assert.equal(m.shellTargetText(option('ranked'), 'es'), 'Lingcod · ordenado por hábitat cartografiado');
  assert.equal(m.shellTargetText(option('plan'), 'es'), 'Lingcod · solo plan de búsqueda');
  assert.equal(m.shellTargetText(option('unresearched'), 'es'), 'Lingcod · sin investigar en esta región');
  assert.equal(m.shellTargetText(option(null), 'es'), 'Lingcod', 'no state yet: the name alone');
  const group = (g, label) => ({label, options: [option('ranked', g)]});
  assert.equal(m.shellGroupLabel(group('plan', 'Search plans · Boat'), 'boat', 'en'), 'Search plans · Boat', 'English is verbatim');
  assert.deepEqual(['link', 'profile', 'plan', 'coast', 'other'].map(g => m.shellGroupLabel(group(g, 'x'), 'shore', 'es')),
    ['Del enlace', 'Objetivos de Orilla', 'Planes de búsqueda · Orilla', 'Objetivos de hábitat costero', 'Otros objetivos']);
  assert.equal(m.shellGroupLabel({label: 'x', options: [{...option('ranked'), group: undefined}]}, 'boat', 'es'), 'Objetivos de Barco', 'no group key: the profile group');
  await inLanguage('es', mm => {
    const cmd = mm.render(mm.h(mm.CommandBar, {now: NOW}));
    for (const words of ['aria-label="Barra de comandos"', 'aria-label="Especie objetivo"', 'aria-label="Busca especie" placeholder="Busca especie"', '<label>Objetivo<select', 'aria-label="Ventana de tiempo"', 'role="group" aria-label="Área y puerto"', 'aria-label="Elegir puerto"', '>Puerto</button>', 'aria-label="Usar mi ubicación"', 'aria-label="Compartir esta vista"'])
      assert.ok(cmd.includes(words), words);
    assert.ok(cmd.includes('value="lingcod"') && cmd.includes('Lingcod ·'), 'the target value and published name are unchanged');
    // SC1722-15: the Area picker is drawn only for a link that selects an area.
    for (const words of ['<label>Área<select', 'Toda la región'])
      assert.ok(!cmd.includes(words), `no area selected: ${words} is not drawn`);
    mm.state.syncFromURL(`${ORIGIN}?region=morro-bay&area=estero`);
    const linked = mm.render(mm.h(mm.CommandBar, {now: NOW}));
    for (const words of ['<label>Área<select', '>Toda la región</option>'])
      assert.ok(linked.includes(words), `area selected: ${words}`);
  });
});

test('shell_es_account_states_and_names: all five states, names pass through escaped, presets map by id', async () => {
  const lines = {loading: 'Consultando tu cuenta…', offline: 'Las cuentas necesitan conexión. Inténtalo de nuevo cuando estés en línea.', disabled: 'Las cuentas no están disponibles en este sitio. El mapa y los pronósticos siguen siendo públicos.',
    'signed-out': 'Las cuentas usan una clave de acceso: Face ID, Touch ID o el PIN de tu dispositivo. Sin contraseña.', 'signed-in': 'Tus viajes guardados y tus alertas son privados de esta cuenta.'};
  await inLanguage('es', m => {
    for (const [state, line] of Object.entries(lines)) {
      m.session.value = state === 'signed-in' ? {state, name: null, advisor: false} : state === 'loading' || state === 'offline' ? {state} : {state, advisor: false};
      const html = m.render(m.h(m.AccountMenu, {}));
      assert.ok(html.includes(`<p>${line}</p>`), state);
      assert.ok(html.includes('aria-label="Cuenta, barco y alertas"'));
    }
    m.session.value = {state: 'signed-in', name: '<b>Skipper</b> "Sol"', advisor: false};
    const named = m.render(m.h(m.AccountMenu, {}));
    assert.ok(named.includes('Sesión iniciada como &lt;b>Skipper&lt;/b> &quot;Sol&quot;'), 'the name is escaped, never translated or inserted as HTML');
    assert.ok(!named.includes('<b>Skipper</b>'));
    m.session.value = {state: 'signed-in', name: null, advisor: false};
    assert.ok(m.render(m.h(m.AccountMenu, {})).includes('>Sesión iniciada</h2>'));
    assert.equal(m.accountLabel({state: 'signed-out', advisor: false}, 'es'), 'Iniciar sesión');
    assert.equal(m.accountLabel({state: 'loading'}, 'es'), 'Iniciar sesión');
    assert.equal(m.accountLabel({state: 'offline'}, 'es'), 'Cuenta');
    assert.equal(m.accountLabel({state: 'signed-in', name: null, advisor: false}, 'es'), 'Cuenta');
    assert.equal(m.accountLabel({state: 'signed-in', name: 'Skipper', advisor: false}, 'es'), 'Skipper', 'the account name passes through');
    m.boat.value = {presets: ['skiff', 'console', 'walkaround', 'cabin', 'future'].map(id => ({id, label: `L-${id}`, detail: `${id} ft`})), name: '<i>Mi</i> barco', preset: null};
    m.state.syncFromURL(ORIGIN);
    const boat = m.render(m.h(m.AccountMenu, {}));
    assert.ok(boat.includes('Las calificaciones usan &lt;i>Mi&lt;/i> barco. Se guarda solo en este navegador.'));
    assert.deepEqual([...boat.matchAll(/data-preset="(\w+)"[^>]*><span>([^<]+)<\/span><small>([^<]+)<\/small>/g)].map(x => [x[1], x[2], x[3]]), [
      ['skiff', 'Lancha pequeña o de consola central', 'skiff ft'], ['console', 'Consola central', 'console ft'], ['walkaround', 'Cubierta transitable o cabina pequeña', 'walkaround ft'],
      ['cabin', 'Cabina o barco de pesca deportiva', 'cabin ft'], ['future', 'L-future', 'future ft']], 'an unknown preset keeps its supplied label; ranges are unchanged');
    assert.ok(boat.includes('Alertas de viaje') && boat.includes('Elige un puerto para guardar sus alertas de viaje.') && boat.includes('Llévalo contigo'));
    assert.match(boat, /<button disabled[^>]*>(?:<svg.*?<\/svg>)?Alertas de viajes guardados<\/button>/, 'no port: the alerts action stays disabled');
    m.state.syncFromURL(`${ORIGIN}?region=morro-bay`);
    m.tripIds.value = ['a', 'b'];
    const region = m.render(m.h(m.AccountMenu, {}));
    assert.ok(region.includes('Plan de viaje y GPX · 2 guardados') && region.includes('Guarda una fecha, un área y límites de comodidad; recibe cambios importantes y una evaluación el día anterior.'));
    for (const words of ['Formato de coordenadas', 'Se guarda en este navegador. GPX siempre usa grados decimales.', 'Grados decimales', 'Grados y minutos decimales', 'Grados, minutos y segundos', 'Guardar sin conexión', 'Repetir recorrido de controles', 'Notas de lugares sin conexión (pestaña nueva)', 'Ingresar mi barco exacto', 'Tu barco'])
      assert.ok(region.includes(words), words);
    m.tripIds.value = [];
    assert.ok(m.render(m.h(m.AccountMenu, {})).includes('>Plan de viaje y GPX</button>'), 'no count when no trip is saved');
  });
});

test('shell_language_switch: en -> es -> en restores the exact English markup, the choice buttons stay named in their own language, and the menu keeps its structure', async () => {
  const m = await load();
  const run = async lang => inLanguage(lang, mm => { mm.session.value = {state: 'signed-out', advisor: true}; mm.state.syncFromURL(`${ORIGIN}?region=morro-bay`); return shellHtml(mm); });
  const first = await run('en');
  const es = await run('es');
  const again = await run('en');
  assert.equal(first, again, 'English is restored byte for byte');
  assert.notEqual(first, es);
  assert.ok(es.includes('>English</button>') && es.includes('>Español</button>'), 'each language is still spelled in itself');
  // The English-source label (SC0707-09) wraps producer text in <span lang="en">; that is a words-only disclosure, so unwrap it before comparing shape.
  const shape = html => html.replace(/<span lang="en">([^<]*)<\/span>/g, '$1').replace(/>[^<]*</g, '><').replace(/\s(?:aria-label|aria-valuetext|placeholder|title|label|aria-pressed|data-on)="[^"]*"/g, '').replace(/id="[^"]*"|aria-labelledby="[^"]*"|aria-controls="[^"]*"/g, '');
  assert.equal(shape(first), shape(es), 'switching language changes words only: same elements, order and attributes');
  m.setLanguage('en', {storage: none, doc: null});
});

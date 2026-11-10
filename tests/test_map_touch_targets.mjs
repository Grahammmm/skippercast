// SC1922-03: the small map controls the UX audit measured (S4-26 remainder, S5-REVIEW E36) are the app's Button:
// Cancel waypoint (inside the placing note), Retry region details (Location, shared by the masthead and the phone top
// card) and the Conditions header's model-family options carry the --touch-min floor. Real components, real handlers.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname, ORIGIN = 'https://s.test/map';
const none = {getItem: () => null, setItem() {}};
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))}; };

let shell;
async function load() {
  if (shell) return shell;
  const out = join(await mkdtemp(join(tmpdir(), 'sc192203-')), 'shell.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {loadRegion, regionLoad, retryRegion} from './web/app/App.tsx';
      export {Location} from './web/app/Masthead.tsx';
      export {PresentationToggle} from './web/app/MapStage.tsx';
      export {Button} from './web/ui/Button.tsx';
      export {language, setLanguage} from './web/i18n.ts';
      export {beginWaypointPlacement, cancelWaypointPlacement, waypointPlacement} from './web/waypoint-placement.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: preparedRendererPlugins,
  });
  shell = await import(pathToFileURL(out).href);
  return shell;
}
const status = code => async () => new Response('nope', {status: code});
const at = async (query = 'region=morro-bay&presentation=chart') => {
  const s = await load(); s.state.configureStore({v2: true, storage: memory()}); s.state.syncFromURL(`${ORIGIN}?${query}`); return s;
};

/** Every vnode in a component's output (components are not expanded), so a handler is read off the real element props. */
function* walk(node) {
  if (node == null || typeof node !== 'object') return;
  if (Array.isArray(node)) { for (const child of node) yield* walk(child); return; }
  yield node;
  yield* walk(node.props?.children);
}
const text = node => [...walk(node)].flatMap(n => (typeof n.props?.children === 'string' ? [n.props.children] : [])).join('');
const buttons = (tree, Button, label) => [...walk(tree)].filter(n => n.type === Button && text(n) === label);

test('placing_touch_cancel_en_es: Cancel waypoint is the app Button in the placing note and keeps its action', async () => {
  const s = await at();
  const {PresentationToggle, Button, beginWaypointPlacement, cancelWaypointPlacement, waypointPlacement, render, h, setLanguage} = s;
  try {
    assert.doesNotMatch(render(h(PresentationToggle, {})), /Cancel waypoint/, 'unarmed: no Cancel');
    const picked = [];
    beginWaypointPlacement('morro-bay', at => picked.push(at));
    for (const [lang, words] of [['en', 'Cancel waypoint'], ['es', 'Cancelar punto de ruta']]) {
      setLanguage(lang, {storage: none, doc: null});
      const found = buttons(PresentationToggle(), Button, words);
      assert.equal(found.length, 1, `${lang}: one ${words} Button`);
      assert.equal(found[0].props.onClick, cancelWaypointPlacement, `${lang}: the existing cancel action, not a copy`);
      assert.equal(found[0].props.size, 'sm');
      assert.equal(found[0].props.variant, 'quiet');
      const html = render(h(PresentationToggle, {}));
      assert.match(html, new RegExp(`<button[^>]*type="button"[^>]*class="ui-button ui-button--quiet ui-button--sm"[^>]*>${words}</button>`), `${lang}: native button with the primitive classes`);
      assert.match(html, /<p class="app-stage-note" role="status">[^<]+ <button/, `${lang}: still inside the placing note`);
    }
    buttons(PresentationToggle(), Button, 'Cancelar punto de ruta')[0].props.onClick();
    assert.equal(waypointPlacement.value, null, 'activating it clears the placement');
    assert.equal(picked.length, 0, 'cancelling accepted no waypoint');
    assert.doesNotMatch(render(h(PresentationToggle, {})), /Cancelar punto de ruta/, 'the note is gone after Cancel');
  } finally { cancelWaypointPlacement(); setLanguage('en', {storage: none, doc: null}); }
});

test('placing_touch_cancel: no Cancel when another region is armed or the Chart is not shown', async () => {
  const {PresentationToggle, beginWaypointPlacement, cancelWaypointPlacement, render, h, state} = await at();
  try {
    beginWaypointPlacement('morro-bay', () => {});
    assert.match(render(h(PresentationToggle, {})), /Cancel waypoint/);
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d`);
    assert.doesNotMatch(render(h(PresentationToggle, {})), /Cancel waypoint/, 'not on the Chart');
    state.syncFromURL(`${ORIGIN}?region=another-region&presentation=chart`);
    assert.doesNotMatch(render(h(PresentationToggle, {})), /Cancel waypoint/, 'armed for another region');
  } finally { cancelWaypointPlacement(); }
});

test('region_error_touch_retry_en_es: Retry region details is the app Button in the error status and keeps retryRegion', async () => {
  const s = await at('region=broken');
  const {Location, Button, loadRegion, retryRegion, render, h, setLanguage} = s;
  try {
    assert.equal(await loadRegion('broken', status(503)), null);
    for (const [lang, words, error] of [['en', 'Retry region details', /region details/i], ['es', 'Reintentar detalles de la región', /región/i]]) {
      setLanguage(lang, {storage: none, doc: null});
      const found = buttons(Location(), Button, words);
      assert.equal(found.length, 1, `${lang}: one ${words} Button`);
      assert.equal(found[0].props.onClick, retryRegion, `${lang}: the existing retry handler`);
      const html = render(h(Location, {}));
      assert.match(html, new RegExp(`<span role="status">[^<]*(?:<[^>]*>)?[^<]*<button[^>]*type="button"[^>]*class="ui-button ui-button--quiet ui-button--sm"[^>]*>${words}</button></span>`), `${lang}: inside the status span`);
      assert.match(html, error);
    }
  } finally { setLanguage('en', {storage: none, doc: null}); }
});

test('region_nonerror_has_no_retry: loading, missing and a stale other-region error show no Retry Button', async () => {
  const {Location, Button, loadRegion, regionLoad, state, render, h} = await at('region=nowhere');
  await loadRegion('nowhere', status(404));
  assert.equal(buttons(Location(), Button, 'Retry region details').length, 0, 'missing');
  assert.match(render(h(Location, {})), /Choose a port/, 'the missing-region link stays');
  regionLoad.value = {id: 'nowhere', state: 'loading'};
  assert.equal(buttons(Location(), Button, 'Retry region details').length, 0, 'loading');
  regionLoad.value = {id: 'elsewhere', state: 'error'};
  assert.equal(buttons(Location(), Button, 'Retry region details').length, 0, 'another region\'s stale error');
  state.syncFromURL(`${ORIGIN}?region=elsewhere`);
  regionLoad.value = {id: 'elsewhere', state: 'error'};
  assert.equal(buttons(Location(), Button, 'Retry region details').length, 1, 'the current region\'s error');
});

test('conditions_each_option_touch: the model-family group wraps inside the header and keeps the touch floor on each option', async () => {
  const css = await readFile(join(ROOT, 'web/app/app.css'), 'utf8');
  const rule = selector => css.split('\n').find(line => line.startsWith(`${selector} {`)) ?? '';
  const group = rule('.app-conditions-head > .ui-segmented'), option = rule('.app-conditions-head > .ui-segmented .ui-chip');
  assert.match(group, /flex-wrap: wrap/);
  assert.match(group, /max-width: 100%/);
  assert.match(group, /box-sizing: border-box/);
  assert.match(option, /flex: none/, 'an option is never squeezed');
  assert.match(option, /min-height: var\(--touch-min\)/);
  assert.doesNotMatch(group + option, /(?<![-\w])height:|overflow|font-size|text-overflow/, 'no fixed height, clipping or shrunk text');
  const ui = await readFile(join(ROOT, 'web/ui/ui.css'), 'utf8');
  assert.match(ui, /\.ui-button \{[^}]*min-height: var\(--touch-min\)/, 'the shared Button floor the options inherit');
});

import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const root = new URL('..', import.meta.url).pathname;
let app;
async function load() {
  if (app) return app;
  const outfile = join(await mkdtemp(join(tmpdir(), 'first-run-mobile-')), 'app.mjs');
  await build({stdin: {resolveDir: root, loader: 'ts', contents: `
    export {App, narrow} from './web/app/App.tsx';
    export {showsFirstRun} from './web/app/Mobile.tsx';
    export * as state from './web/state.ts';
    export {h} from 'preact';
    export {render} from 'preact-render-to-string';`},
  outfile, bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins, logLevel: 'silent'});
  app = await import(pathToFileURL(outfile).href);
  return app;
}
const now = new Date('2026-10-05T20:00:00Z');
async function shell(mobile, view = '') {
  const {App, narrow, state, h, render} = await load();
  state.configureStore({v2: true, storage: null});
  state.syncFromURL(`https://s.test/map?region=morro-bay${view ? `&view=${view}` : ''}`);
  narrow.value = mobile;
  return render(h(App, {now}));
}

test('the mobile prompt is inside the sheet scroll body in every sheet view', async () => {
  for (const view of ['', 'conditions', 'history', 'fleet']) {
    const html = await shell(true, view);
    assert.match(html, /class="ui-sheet-body"><section class="app-firstrun"/);
    assert.equal((html.match(/class="app-firstrun"/g) || []).length, 1);
  }
});

test('the layers panel takes the sheet from the first-run prompt, which returns with the brief', async () => {
  const {showsFirstRun} = await load();
  assert.equal(showsFirstRun('brief'), true);
  assert.equal(showsFirstRun('layers'), false);
});

test('mobile Reports keeps the first-run prompt inside its scrollable page', async () => {
  assert.match(await shell(true, 'reports'), /class="app-mobile-page"><section class="app-firstrun"/);
});

test('the desktop keeps its standalone first-run prompt', async () => {
  const html = await shell(false);
  assert.equal((html.match(/class="app-firstrun"/g) || []).length, 1);
  assert.doesNotMatch(html, /class="ui-sheet-body"><section class="app-firstrun"/);
});

// BL-SC-2: the peek row is CSS only. The sheet renders at peek with the whole card's markup,
// and every sheet rule for the card is scoped to peek, so half, full, desktop and Reports are unchanged.
test('the compact peek row keeps the card markup and only peek-scoped rules', async () => {
  const html = await shell(true);
  assert.match(html, /class="ui-sheet[^"]*" data-detent="peek"/);
  const card = html.slice(html.indexOf('<section class="app-firstrun"'));
  for (const part of [/class="ui-eyebrow"/, /<h2 id="first-run-title">/, /<p>The profile sets/, /Keep Boat for now/]) assert.match(card, part);
  assert.equal((card.match(/<small>/g) || []).length, 4);
  const css = readFileSync(join(root, 'web/landing/port-input.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  const rules = [...css.matchAll(/([^{}]+)\{/g)].map(m => m[1].trim()).filter(sel => /\.ui-sheet/.test(sel));
  assert.ok(rules.length >= 5, 'the peek rules exist');
  for (const sel of rules) for (const part of sel.split(',')) assert.match(part.trim(), /^\.ui-sheet\[data-detent="peek"\] \.app-firstrun/, part);
});

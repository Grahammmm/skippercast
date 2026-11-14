// SC1722-20: the skip links' own behaviour. The real bundled web/app/SkipLinks.tsx is rendered (order, hrefs, language) and its
// activation logic (createSkip / focusSkipTarget / needsCoast) runs against a stub document and frame clock, with no browser:
// native Tab order, the 44 px reveal and the phone detent are proved in e2e/v2-skip-links.spec.ts.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'skip-links-')), 'm.mjs');
await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
  export {SkipLinks, createSkip, focusSkipTarget, skipFocusTarget, needsCoast, BRIEF_ID, MAP_ID} from './web/app/SkipLinks.tsx';
  export {language} from './web/i18n.ts';
  export {render} from 'preact-render-to-string';
  export {h} from 'preact';`},
bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
const {SkipLinks, createSkip, focusSkipTarget, skipFocusTarget, needsCoast, BRIEF_ID, MAP_ID, language, render, h} = await import(pathToFileURL(out).href);

/** A stand-in document: elements by selector or id, focus that works unless the element refuses it, [hidden] ancestors by name. */
function page({selectors = {}, ids = {}, refuse = [], hidden = []} = {}) {
  const doc = {activeElement: null, body: {tag: 'body'}};
  doc.activeElement = doc.body;
  const wrap = (name, el) => el && Object.assign(el, {name, attrs: el.attrs ?? {},
    hasAttribute: a => a in el.attrs, setAttribute: (a, v) => { el.attrs[a] = v; },
    closest: q => (q === '[hidden]' && hidden.includes(name) ? el : null),
    focus() { if (!refuse.includes(name) && !hidden.includes(name)) doc.activeElement = el; }});
  const byId = Object.fromEntries(Object.entries(ids).map(([id, v]) => [id, wrap(id, v)]));
  const bySel = Object.fromEntries(Object.entries(selectors).map(([s, v]) => [s, wrap(s, v)]));
  doc.querySelector = s => bySel[s] ?? null;
  doc.getElementById = id => byId[id] ?? null;
  return {doc, byId, bySel};
}
const frames = () => { const queue = []; let next = 1; return {queue, frame: run => { queue.push([next, run]); return next++; }, cancelFrame: id => { const i = queue.findIndex(([n]) => n === id); if (i >= 0) queue.splice(i, 1); }, flush() { for (const [, run] of queue.splice(0)) run(); }}; };

test('the two links are real anchors in order, with catalogue words in both languages and no tabindex', () => {
  for (const [lang, brief, map] of [['en', 'Skip to brief', 'Skip to map'], ['es', 'Saltar al resumen', 'Saltar al mapa']]) {
    language.value = lang;
    try {
      const html = render(h(SkipLinks, {}));
      assert.equal(html, `<a class="app-skip-link" href="#${BRIEF_ID}">${brief}</a><a class="app-skip-link" href="#${MAP_ID}">${map}</a>`, lang);
    } finally { language.value = 'en'; }
  }
});

test('needsCoast: only a view that hides the target is left, and the map is shown from any other view', () => {
  assert.equal(needsCoast('brief', 'coast', false), false);
  assert.equal(needsCoast('map', 'coast', true), false);
  for (const view of ['fleet', 'reports', 'plan']) assert.equal(needsCoast('brief', view, false), true, `desktop ${view} hides the brief`);
  for (const view of ['conditions', 'history']) assert.equal(needsCoast('brief', view, false), false, `desktop ${view} leaves the brief beside it`);
  for (const view of ['conditions', 'fleet', 'history', 'reports', 'plan']) {
    assert.equal(needsCoast('brief', view, true), true, `phone ${view} replaces the brief sheet`);
    assert.equal(needsCoast('map', view, false), true, `desktop ${view} covers the map`);
  }
});

test('map target: the visible Chart canvas, else the terrain canvas or host, else the stage; never a hidden canvas', () => {
  const chart = page({selectors: {'.app-chart canvas': {}, '.app-terrain': {}, '.app-stage': {}}, ids: {[MAP_ID]: {}}, hidden: ['.app-terrain']});
  assert.equal(skipFocusTarget(chart.doc, 'map'), chart.bySel['.app-chart canvas']);
  assert.equal(chart.bySel['.app-chart canvas'].attrs.tabindex, '-1', 'a canvas that cannot take script focus gets tabindex -1, never a positive one');
  const terrain = page({selectors: {'.app-chart canvas': {}, '.app-terrain canvas': {}, '.app-terrain': {}, '.app-stage': {}}, hidden: ['.app-chart canvas']});
  assert.equal(skipFocusTarget(terrain.doc, 'map'), terrain.bySel['.app-terrain canvas']);
  const failed = page({selectors: {'.app-chart canvas': {}, '.app-terrain': {}, '.app-stage': {}}, hidden: ['.app-chart canvas', '.app-terrain']});
  assert.equal(skipFocusTarget(failed.doc, 'map'), failed.bySel['.app-stage']);
});

test('map focus falls back to the stage when the canvas refuses focus; an empty document does nothing, not a throw', () => {
  const refusing = page({selectors: {'.app-chart canvas': {}, '.app-stage': {}}, ids: {[MAP_ID]: {}}, refuse: ['.app-chart canvas']});
  assert.equal(focusSkipTarget(refusing.doc, 'map'), true);
  assert.equal(refusing.doc.activeElement, refusing.byId[MAP_ID]);
  const empty = page();
  assert.equal(focusSkipTarget(empty.doc, 'map'), false);
  assert.equal(focusSkipTarget(empty.doc, 'brief'), false);
  assert.equal(empty.doc.activeElement, empty.doc.body, 'never forced onto the body or anywhere else');
});

test('activation: the view and the phone state are prepared first, then one frame later focus lands on the brief or the map', () => {
  const {doc, byId} = page({ids: {[BRIEF_ID]: {}, [MAP_ID]: {}}, selectors: {'.app-stage': {}}});
  const link = {name: 'link'}; doc.activeElement = link;
  const clock = frames(), calls = [];
  const skip = createSkip({doc, view: () => 'fleet', showCoast: () => calls.push('coast'), ...clock});
  skip.go('brief', true, target => calls.push(`prepare:${target}`));
  assert.deepEqual(calls, ['coast', 'prepare:brief'], 'the view and the sheet are set before focus');
  assert.equal(doc.activeElement, link, 'nothing is focused until the frame');
  clock.flush();
  assert.equal(doc.activeElement, byId[BRIEF_ID]);
  doc.activeElement = link; calls.length = 0;
  createSkip({doc, view: () => 'coast', showCoast: () => calls.push('coast'), ...clock}).go('brief', false);
  assert.deepEqual(calls, [], 'the Coast view is not touched when nothing hides the target');
});

test('stale and duplicate activations: a user who moved on is not pulled back, and a second activation or unmount leaves one or no focus change', () => {
  const {doc, byId, bySel} = page({ids: {[BRIEF_ID]: {}, [MAP_ID]: {}}, selectors: {'.app-stage': {}}});
  const link = {name: 'link'}, other = {name: 'elsewhere'};
  doc.activeElement = link;
  const clock = frames(), skip = createSkip({doc, view: () => 'coast', showCoast() {}, ...clock});
  skip.go('brief', false);
  doc.activeElement = other;   // the user tabbed on while the frame was pending
  clock.flush();
  assert.equal(doc.activeElement, other, 'focus the user chose is kept');
  doc.activeElement = link;
  skip.go('brief', false); skip.go('map', false);
  assert.equal(clock.queue.length, 1, 'the second activation replaced the first frame');
  clock.flush();
  assert.ok(doc.activeElement === bySel['.app-stage'] && doc.activeElement !== byId[BRIEF_ID], 'only the latest target (the map) is focused');
  doc.activeElement = link;
  skip.go('brief', false); skip.cancel();
  assert.equal(clock.queue.length, 0, 'unmount cancels the pending frame');
  clock.flush();
  assert.equal(doc.activeElement, link);
});

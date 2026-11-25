// SC2222-04: closing the mark card returns focus to the map the user is looking at, never <body>.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'map-focus-')), 'map-focus.mjs');
await build({
  stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {MarkCard} from './web/app/MarkCard.tsx';
    export {mapFocusTarget} from './web/app/map-focus.ts';
    export {chartMark} from './web/map/chart.ts';
    export {session} from './web/account.ts';
    export {h, options} from 'preact';
    export {render} from 'preact-render-to-string';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent',
  jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
});
const {MarkCard, mapFocusTarget, chartMark, session, h, options, render} = await import(pathToFileURL(out).href);

const CHART = '.app-chart canvas', TERRAIN_CANVAS = '.app-terrain canvas', TERRAIN = '.app-terrain', STAGE = '.app-stage';

// Ordered selector matches. Attributes are on a wrapper, not the focus target itself.
function page(...matches) {
  const body = {id: 'body'}, focusCalls = [];
  const doc = {body, activeElement: body, defaultView: {getComputedStyle: el => ({visibility: el.visibility})},
    querySelectorAll: selector => nodes.filter(el => el.selector === selector),
    querySelector: selector => doc.querySelectorAll(selector)[0] ?? null};
  const nodes = matches.map(([selector, id, {ancestor, noBox, visibility = 'visible'} = {}]) => ({
    selector, id, ownerDocument: doc, visibility,
    closest: query => ancestor && query.split(/,\s*/).includes(ancestor) ? {attribute: ancestor} : null,
    getClientRects: () => noBox || ancestor === '[hidden]' ? [] : [{}],
    focus() {
      focusCalls.push(id);
      if (!ancestor && !noBox && visibility === 'visible') doc.activeElement = this;
    },
  }));
  return {doc, focusCalls};
}

function escapeFromMark({doc, focusCalls}, expected) {
  const mark = {id: 'depth:fixture', name: 'Synthetic depth mark', kind: 'Depth', reading: '12 ft', source: 'Fixture', basis: 'Fixture'};
  const lastVNode = options.vnode, lastSession = session.value, lastDocument = globalThis.document;
  let keydown;
  options.vnode = node => {
    lastVNode?.(node);
    if (node.type === 'section' && node.props.class === 'app-mark') keydown = node.props.onKeyDown;
  };
  try {
    session.value = {state: 'signed-out'};
    chartMark.value = mark;
    render(h(MarkCard, {}));
    assert.equal(typeof keydown, 'function');
    // Exercise the real MarkCard Escape handler with no surviving returnTo element.
    globalThis.document = doc;
    doc.activeElement = {id: 'mark-heading'};
    const card = Object.assign(new EventTarget(), {querySelector: () => null});
    const event = Object.assign(new Event('keydown', {cancelable: true}), {key: 'Escape'});
    card.addEventListener('keydown', keydown);
    card.dispatchEvent(event);
    assert.ok(event.defaultPrevented);
    assert.equal(chartMark.value, null, 'Escape clears the selected mark');
    assert.equal(doc.activeElement.id, expected, 'focused element after Escape');
    assert.deepEqual(focusCalls, [expected], 'never attempt focus on a blocked target');
  } finally {
    options.vnode = lastVNode;
    chartMark.value = null;
    session.value = lastSession;
    if (lastDocument === undefined) delete globalThis.document; else globalThis.document = lastDocument;
  }
}

test('Escape during a region transition focuses the first usable Chart canvas', () => {
  // If the selector checks only the first match, it skips the whole Chart group and focuses terrain.
  escapeFromMark(page(
    [CHART, 'old-region-chart', {ancestor: '[hidden]'}],
    [CHART, 'inactive-chart', {ancestor: '[inert]'}],
    [CHART, 'unrendered-chart', {noBox: true}],
    [CHART, 'invisible-chart', {visibility: 'hidden'}],
    [CHART, 'visible-chart'], [CHART, 'later-visible-chart'],
    [TERRAIN_CANVAS, 'terrain-canvas'], [TERRAIN, 'terrain-host'], [STAGE, 'stage'],
  ), 'visible-chart');
});
test('Escape with only a hidden Chart focuses the terrain canvas, else its shadow host', () => {
  const hiddenChart = [CHART, 'hidden-chart', {ancestor: '[hidden]'}];
  escapeFromMark(page(hiddenChart, [TERRAIN_CANVAS, 'terrain-canvas'], [TERRAIN, 'terrain-host'], [STAGE, 'stage']), 'terrain-canvas');
  escapeFromMark(page(hiddenChart, [TERRAIN, 'terrain-host'], [STAGE, 'stage']), 'terrain-host');
});
test('Escape focuses the stage when it is the only usable target', () => {
  escapeFromMark(page([STAGE, 'stage']), 'stage');
  escapeFromMark(page([CHART, 'hidden-chart', {ancestor: '[hidden]'}],
    [TERRAIN, 'hidden-terrain', {ancestor: '[hidden]'}], [STAGE, 'stage']), 'stage');
});
test('no usable map or stage: null, not a throw', () => {
  assert.equal(mapFocusTarget(page().doc), null);
  assert.equal(mapFocusTarget(page([CHART, 'hidden-chart', {ancestor: '[hidden]'}]).doc), null);
  assert.equal(mapFocusTarget(page([TERRAIN, 'inert-terrain', {ancestor: '[inert]'}],
    [STAGE, 'inert-stage', {ancestor: '[inert]'}]).doc), null);
});

const MARK_CARD = await readFile(join(ROOT, 'web/app/MarkCard.tsx'), 'utf8');
const MAP_STAGE = await readFile(join(ROOT, 'web/app/MapStage.tsx'), 'utf8');
test('close() prefers a connected returnTo, else the shown map, and tolerates no target', () => {
  assert.match(MARK_CARD, /const back = returnTo\?\.isConnected \? returnTo : mapFocusTarget\(document\);/);
  assert.match(MARK_CARD, /back\?\.focus\(\)/);
  assert.doesNotMatch(MARK_CARD, /querySelector<HTMLElement>\('\.app-chart canvas'\)/);
});
test('the stage and the terrain host take programmatic focus only', () => {
  assert.match(MAP_STAGE, /<section class="app-stage" tabIndex=\{-1\}/);
  assert.match(MAP_STAGE, /<div class="app-terrain"[^>]* tabIndex=\{-1\}/);
  assert.doesNotMatch(MAP_STAGE, /tabIndex=\{[1-9]/);
});

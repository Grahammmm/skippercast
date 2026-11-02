// SC2222-04: closing the mark card returns focus to the map the user is looking at, never <body>.
// mapFocusTarget (web/app/map-focus.ts) is built with esbuild like test_app_shell.mjs and run against
// stub elements that carry only `closest` and `querySelector`.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const ROOT = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'map-focus-')), 'map-focus.mjs');
await build({entryPoints: [join(ROOT, 'web/app/map-focus.ts')], bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent'});
const {mapFocusTarget} = await import(pathToFileURL(out).href);

/** `present` lists the selectors that find an element; `hidden` those whose element sits under a [hidden] ancestor-or-self. */
const page = (present, hidden = []) => {
  const parts = Object.fromEntries(present.map(selector => [selector, {selector, closest: q => (q === '[hidden]' && hidden.includes(selector) ? parts[selector] : null)}]));
  return {parts, doc: {querySelector: selector => parts[selector] ?? null}};
};
const CHART = '.app-chart canvas', TERRAIN_CANVAS = '.app-terrain canvas', TERRAIN = '.app-terrain', STAGE = '.app-stage';

test('Chart shown and not failed: the Chart canvas', () => {
  const {parts, doc: d} = page([CHART, TERRAIN, STAGE], [TERRAIN]);
  assert.equal(mapFocusTarget(d), parts[CHART]);
});
test('2D/3D shown: the terrain canvas, else its host; never the hidden Chart canvas', () => {
  const withCanvas = page([CHART, TERRAIN_CANVAS, TERRAIN, STAGE], [CHART]);
  assert.equal(mapFocusTarget(withCanvas.doc), withCanvas.parts[TERRAIN_CANVAS]);
  const hostOnly = page([CHART, TERRAIN, STAGE], [CHART]);
  assert.equal(mapFocusTarget(hostOnly.doc), hostOnly.parts[TERRAIN]);
});
test('Chart failed (hidden .app-chart): the map stage', () => {
  const {parts, doc: d} = page([CHART, TERRAIN, STAGE], [CHART, TERRAIN]);
  assert.equal(mapFocusTarget(d), parts[STAGE]);
});
test('nothing mounted: null, not a throw', () => {
  assert.equal(mapFocusTarget(page([]).doc), null);
  assert.equal(mapFocusTarget(page([CHART], [CHART]).doc), null);
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

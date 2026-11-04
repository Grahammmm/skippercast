// SC0122-03: the trip planner says a shared evidence confidence once above the list and
// keeps the per-row percent only when the ranked places differ. Display only: the
// helper reads the spots, the rows render from them; no export text is touched.
import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {getRegion} from '../dist/region.js';
import {sharedConfidence} from '../web/planner.ts';
import {rendererPlugin} from './helpers/esbuild-url.mjs';

const ranked = (i, percent) => ({id: `r${i}`, label: `Reef ${i}`, name: `Reef ${i} 90-120ft`, latitude: 35 + i / 100, longitude: -121, habitat_grade: 'A', canonical_habitat: true, neighborhood_depth_ft: [90, 120], trip_rank: i, trip_fit: 3, evidence_confidence: percent === undefined ? undefined : {percent}});
const unranked = i => ({id: `u${i}`, label: `Saved ${i}`, latitude: 35.5, longitude: -121, habitat_grade: 'B', center_depth_ft: 80});

test('three ranked spots at 90 share one value', () => {
  assert.equal(sharedConfidence([ranked(1, 90), ranked(2, 90), ranked(3, 90)]), 90);
});
test('differing percents have no shared value', () => {
  assert.equal(sharedConfidence([ranked(1, 90), ranked(2, 90), ranked(3, 75)]), null);
});
test('one ranked spot has no shared value', () => {
  assert.equal(sharedConfidence([ranked(1, 90)]), null);
});
test('a missing or non-finite percent is never shared', () => {
  assert.equal(sharedConfidence([ranked(1, 90), ranked(2, undefined)]), null);
  assert.equal(sharedConfidence([ranked(1, undefined), ranked(2, undefined)]), null);
  assert.equal(sharedConfidence([ranked(1, NaN), ranked(2, NaN)]), null);
  assert.equal(sharedConfidence([ranked(1, Infinity), ranked(2, Infinity)]), null);
  assert.equal(sharedConfidence([ranked(1, 90), {...ranked(2, 90), evidence_confidence: {}}]), null);
});
test('unranked spots are ignored and an empty list has no shared value', () => {
  assert.equal(sharedConfidence([ranked(1, 80), unranked(1), ranked(2, 80)]), 80);
  assert.equal(sharedConfidence([unranked(1), unranked(2)]), null);
  assert.equal(sharedConfidence([]), null);
});

const bundle = await build({stdin: {contents: `export {Planner} from './web/app/Planner.tsx'; export {createPlanner} from './web/planner.ts'; export {h} from 'preact'; export {default as render} from 'preact-render-to-string';`, resolveDir: new URL('..', import.meta.url).pathname}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', jsxImportSource: 'preact', plugins: [rendererPlugin]});
const ui = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const map = {getSize: () => ({x: 512}), getBounds: () => ({getWest: () => -122, getEast: () => -120, getSouth: () => 34, getNorth: () => 37})};

/** The planner's HTML with `spots` as its list. */
function renderList(spots) {
  const p = ui.createPlanner({atlas: {targets: [], areas: [], drifts: []}, screen: null, region: getRegion(), map, getVisible: () => [], storage: null,
    loadPorts: async () => null, emit() {}, nav: {open() {}, showMap() {}, conditions() {}}});
  try {
    const html = ui.render(ui.h(ui.Planner, {model: {...p, spots: {value: spots}}, open: false}));
    const list = html.slice(html.indexOf('id="export-spot-list"'));
    return {html, list: list.slice(0, list.indexOf('</details>')), above: html.slice(0, html.indexOf('id="export-spot-list"'))};
  } finally { p.dispose(); }
}

test('shared 90: one sentence above the list and rows without a percent', () => {
  const {html, list, above} = renderList([ranked(1, 90), ranked(2, 90), ranked(3, 90)]);
  assert.equal(html.match(/All ranked places: 90% evidence confidence\./g)?.length, 1);
  assert.ok(above.includes('id="export-shared-confidence"'), 'the sentence sits above the spot list');
  assert.match(list, /<strong>#1 · Strong<\/strong>/);
  assert.match(list, /<strong>#3 · Strong<\/strong>/);
  assert.doesNotMatch(list, /% confidence/);
});
test('differing percents: every row keeps its own and no sentence', () => {
  const {html, list} = renderList([ranked(1, 90), ranked(2, 90), ranked(3, 75)]);
  assert.doesNotMatch(html, /export-shared-confidence|All ranked places/);
  assert.match(list, /#1 · Strong · 90% confidence/);
  assert.match(list, /#3 · Strong · 75% confidence/);
});
test('a single ranked row keeps its percent', () => {
  const {html, list} = renderList([ranked(1, 90)]);
  assert.doesNotMatch(html, /export-shared-confidence/);
  assert.match(list, /#1 · Strong · 90% confidence/);
});
test('a missing percent prints no undefined%', () => {
  const {html, list} = renderList([ranked(1, 90), ranked(2, undefined)]);
  assert.doesNotMatch(html, /export-shared-confidence/);
  assert.doesNotMatch(html.slice(html.indexOf('id="export-spot-list"')), /NaN%|Infinity%/);
  assert.match(list, /#1 · Strong · 90% confidence/);
});
test('mixed ranked and unranked: sentence shown and unranked labels unchanged', () => {
  const {html, list} = renderList([ranked(1, 85), ranked(2, 85), unranked(1)]);
  assert.match(html, /All ranked places: 85% evidence confidence\./);
  assert.match(list, /<strong>#2 · Strong<\/strong>/);
  assert.match(list, /<strong>Saved 1<\/strong>/);
});
test('empty list: no sentence and the empty text is unchanged', () => {
  const {html, list} = renderList([]);
  assert.doesNotMatch(html, /export-shared-confidence/);
  assert.match(list, /No matching measured reefs loaded\. Select Best available to load the current screened publication/);
});

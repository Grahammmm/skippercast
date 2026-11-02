// SC1737-07: the export sheet shows the C1 and C4 short-form caveats before Download GPX,
// verbatim from docs/legal/disclaimers.md (placement item 4), whether or not GPX is withheld.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {build} from 'esbuild';
import {getRegion} from '../dist/region.js';
import {initProtectedAreas} from '../dist/protected-areas.js';
import {rendererPlugin} from './helpers/esbuild-url.mjs';

const doc = readFileSync(new URL('../docs/legal/disclaimers.md', import.meta.url), 'utf8');
/** The "Short form (UI)" cell of a caveat row in the doc table. */
function shortForm(id) {
  const row = doc.split('\n').find(line => line.startsWith(`| ${id} |`));
  assert.ok(row, `${id} row in disclaimers.md`);
  return row.split('|').map(cell => cell.trim())[3];
}

const mpas = JSON.parse(readFileSync(new URL('../dist/data/protected-areas.geojson', import.meta.url)));
async function screenFixture() {
  const saved = {fetch: globalThis.fetch, document: globalThis.document};
  globalThis.fetch = async () => ({ok: true, json: async () => ({...mpas, checked_at: new Date().toISOString()})});
  globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}};
  try { return await initProtectedAreas(null, () => {}); }
  finally { Object.assign(globalThis, saved); }
}
const map = {getSize: () => ({x: 512}), getBounds: () => ({getWest: () => -122, getEast: () => -120, getSouth: () => 34, getNorth: () => 37})};
const ui = await (async () => {
  const bundle = await build({stdin: {contents: `export {Planner, EXPORT_CAVEATS} from './web/app/Planner.tsx'; export {createPlanner} from './web/planner.ts'; export {h} from 'preact'; export {default as render} from 'preact-render-to-string';`, resolveDir: new URL('..', import.meta.url).pathname}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', jsxImportSource: 'preact', plugins: [rendererPlugin]});
  return import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
})();

/** Render the planner with one research spot at `point`; returns the HTML and whether GPX is allowed. */
async function renderSheet(point) {
  const target = {id: 'manual-caveat', label: 'Synthetic saved reference', ...point, neighborhood_depth_ft: [0, 0]};
  const p = ui.createPlanner({atlas: {targets: [target], areas: [], drifts: []}, screen: await screenFixture(), region: getRegion(), map, getVisible: () => [], storage: null,
    loadPorts: async () => null, emit() {}, nav: {open() {}, showMap() {}, conditions() {}}});
  try {
    p.add(target.id);
    p.setResearch(true);
    return {html: ui.render(ui.h(ui.Planner, {model: p, open: false})), ok: p.summary.value.ok};
  } finally { p.dispose(); }
}
const count = (html, s) => html.split(s).length - 1;

function assertCaveats(html) {
  const [c1, c4] = ui.EXPORT_CAVEATS;
  const para = html.match(/<p id="export-caveats" class="export-note">([^<]*)<\/p>/);
  assert.ok(para, 'caveat paragraph rendered as plain export-note text');
  assert.equal(para[1], `${c1} ${c4}`, 'C1 then C4');
  const at = html.indexOf('id="export-caveats"');
  assert.ok(html.indexOf('id="export-validation"') < at, 'after export-validation');
  assert.ok(at < html.indexOf('id="export-download"'), 'before Download GPX');
  assert.equal(count(html, c1), 1, 'C1 exactly once');
  assert.equal(count(html, c4), 1, 'C4 exactly once');
  assert.equal(count(html, 'id="export-caveats"'), 1);
}

test('in-app caveats equal the C1 and C4 short forms in docs/legal/disclaimers.md', () => {
  assert.deepEqual([...ui.EXPORT_CAVEATS], [shortForm('C1'), shortForm('C4')]);
  assert.ok(ui.EXPORT_CAVEATS[0].includes('\u00b7'), 'middle dot is U+00B7');
  assert.match(doc, /4\. the Export sheet, before a chartplotter file is downloaded \(C1 and C4 short forms\)/);
});

test('exportable plan: caveats sit after the validation line and before Download GPX', async () => {
  const {html, ok} = await renderSheet({longitude: -121.5, latitude: 35.2});
  assert.equal(ok, true, 'fixture plan is exportable');
  assert.match(html, /id="export-download">Download GPX/);
  assertCaveats(html);
});

test('GPX withheld (spot inside Morro Bay SMR): caveats still render once, before Download GPX', async () => {
  const morro = mpas.features.find(f => f.properties.NAME === 'Morro Bay SMR');
  const {pointInGeometry} = await import('../dist/geo-screen.js');
  const v = morro.geometry.coordinates.flat(Infinity), xs = v.filter((_, i) => i % 2 === 0), ys = v.filter((_, i) => i % 2 === 1);
  let inside;
  for (let x = Math.min(...xs); !inside && x < Math.max(...xs); x += 0.0005) {
    for (let y = Math.min(...ys); y < Math.max(...ys); y += 0.0005) if (pointInGeometry([x, y], morro.geometry)) { inside = {longitude: x, latitude: y}; break; }
  }
  const {html, ok} = await renderSheet(inside);
  assert.equal(ok, false, 'GPX withheld');
  assert.match(html, /id="export-download" disabled/);
  assertCaveats(html);
});

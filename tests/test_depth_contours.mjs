// Shelf depth contours (CI6-13, docs/plans/front-end/design.md § 9): the published
// file's check, the overview/full switch, the overlay, the card and the Chart layer,
// read from the committed Morro Bay publication (offline) with a fake engine.
// web/map/depth-contours.ts runs by type stripping.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {
  DEPTH_EDGE, DEPTH_HIT, DEPTH_LABEL, DEPTH_LABEL_MINOR, DEPTH_LINE, DETAIL_ZOOM, INDEX_FT, INTERVAL_FT, NOTES,
  assessContours, contourMark, contourState, contoursFor, contoursOverlay, createDepthContours, depthContoursOverviewURL, depthContoursURL,
} from '../web/map/depth-contours.ts';
import {ZOOM_OFFSET} from '../web/map/engine.ts';
import {DEPTH_CONTOURS_SOURCE, layerEntry, sourceLayer} from '../web/map/layers.ts';
import {MPA_FILL} from '../web/map/mpa.ts';
import {readPalette} from '../web/map/palette.ts';
import {camera} from '../web/map/stage.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url);
const json = path => JSON.parse(readFileSync(new URL(path, ROOT), 'utf8'));
const FULL = json('dist/regions/morro-bay/depth-contours.geojson');
const OVERVIEW = json('dist/regions/morro-bay/depth-contours-overview.geojson');
const TODAY = '2026-10-20';
const sentinel = readPalette(name => `token(${name})`);
const flush = () => new Promise(resolve => setImmediate(resolve));
const clone = v => structuredClone(v);

test('the committed Morro Bay contours pass the check: feet, a 30 ft interval, a survey, date and datum on every line', () => {
  for (const file of [FULL, OVERVIEW]) {
    const r = assessContours(file, 'morro-bay', TODAY);
    assert.equal(r.status, 'drawn');
    assert.equal(r.data.features.length, file.features.length);
    assert.equal(r.expires, file.provenance.review_expires);
    assert.deepEqual(r.sources.map(s => s.source_id).sort(), ['usgs-morro-bay', 'usgs-point-buchon', 'usgs-point-estero']);
    for (const f of file.features) {
      const p = f.properties;
      assert.ok(r.sources.some(s => s.source_id === p.source_id && s.survey_date === p.survey_date && s.vertical_datum === p.vertical_datum), f.id);
      assert.ok(p.survey_date && p.vertical_datum, `${f.id} carries its survey date and datum`);
      if (p.kind === 'contour') {
        assert.equal(p.depth_ft % INTERVAL_FT, 0);
        assert.ok(p.depth_ft <= 600, 'shelf only');
        assert.equal(p.index, p.depth_ft % INDEX_FT === 0);
      }
    }
    assert.equal(file.provenance.units, 'ft');
    assert.equal(file.provenance.interval_ft, INTERVAL_FT);
    assert.ok(file.features.some(f => f.properties.kind === 'survey-edge'), 'the survey edge is published');
  }
  // The datum is never upgraded: the grids declare none, so every line says so.
  assert.ok(FULL.features.every(f => f.properties.vertical_datum === 'unverified source datum'));
});

test('past review_expires the contours are withheld; any gap in the file fails it whole', () => {
  const expires = FULL.provenance.review_expires;
  assert.equal(assessContours(FULL, 'morro-bay', expires).status, 'drawn', 'drawn on its last day');
  const next = new Date(Date.parse(`${expires}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10);
  const withheld = assessContours(FULL, 'morro-bay', next);
  assert.equal(withheld.status, 'withheld');
  assert.equal(withheld.data, null);
  const broken = [
    ['another region', d => d, 'cambria'],
    ['metres', d => { d.provenance.units = 'm'; }],
    ['another interval', d => { d.provenance.interval_ft = 20; }],
    ['no age limit', d => { delete d.provenance.review_expires; }],
    ['a line without its datum', d => { delete d.features[0].properties.vertical_datum; }],
    ['a line with another survey date', d => { d.features[0].properties.survey_date = '2019'; }],
    ['an unlisted source', d => { d.features[0].properties.source_id = 'gebco-2026'; }],
    ['an off-interval depth', d => { const f = d.features.find(x => x.properties.kind === 'contour'); f.properties.depth_ft = 45; }],
    ['a point instead of a line', d => { d.features[0].geometry = {type: 'Point', coordinates: [-121, 35.3]}; }],
    ['a source without a datum', d => { d.provenance.sources[0].vertical_datum = ''; }],
  ];
  for (const [what, edit, id = 'morro-bay'] of broken) {
    const d = clone(OVERVIEW);
    edit(d);
    assert.equal(assessContours(d, id, TODAY).status, 'failed', what);
  }
  assert.equal(assessContours(null, 'morro-bay', TODAY).status, 'failed');
});

test('the overview draws below the detail zoom; the full contours from it, and for the rest of the visit once loaded', () => {
  const detail = DETAIL_ZOOM + ZOOM_OFFSET;
  assert.equal(contoursFor('morro-bay', detail - 1), depthContoursOverviewURL('morro-bay'));
  assert.equal(contoursFor('morro-bay', detail), depthContoursURL('morro-bay'));
  assert.equal(contoursFor('morro-bay', 9, true), depthContoursURL('morro-bay'));
  assert.equal(depthContoursURL('morro-bay'), 'regions/morro-bay/depth-contours.geojson');
  assert.equal(OVERVIEW.provenance.overview.max_zoom, DETAIL_ZOOM, 'the build and the Chart agree on the switch');
});

test('the overlay: a dashed survey edge, contours heavier at the index, a click target and labels in feet, from the palette', () => {
  const o = contoursOverlay(sentinel, OVERVIEW);
  assert.deepEqual(Object.keys(o.sources), [DEPTH_CONTOURS_SOURCE]);
  assert.equal(sourceLayer(DEPTH_CONTOURS_SOURCE), 'depth-contours');
  assert.deepEqual(o.layers.map(l => l.id), [DEPTH_EDGE, DEPTH_LINE, DEPTH_HIT, DEPTH_LABEL, DEPTH_LABEL_MINOR]);
  const by = id => o.layers.find(l => l.id === id);
  assert.deepEqual(by(DEPTH_EDGE).filter, ['==', ['get', 'kind'], 'survey-edge']);
  assert.deepEqual(by(DEPTH_EDGE).paint['line-dasharray'], [2, 2]);
  assert.equal(by(DEPTH_EDGE).paint['line-color'], 'token(muted)');
  assert.equal(by(DEPTH_LINE).paint['line-color'], 'token(depth-1)');
  assert.deepEqual(by(DEPTH_LINE).paint['line-opacity'], ['case', ['==', ['get', 'index'], true], 0.85, 0.55]);
  assert.equal(by(DEPTH_HIT).paint['line-opacity'], 0);
  assert.equal(by(DEPTH_HIT).filter, undefined, 'contours and edge are both selectable');
  assert.deepEqual(by(DEPTH_LABEL).layout['text-field'], ['concat', ['to-string', ['get', 'depth_ft']], ' ft']);
  assert.equal(by(DEPTH_LABEL).minzoom, undefined, 'index labels at every zoom');
  assert.equal(by(DEPTH_LABEL_MINOR).minzoom, DETAIL_ZOOM);
  for (const l of o.layers) assert.equal(l.maxzoom, undefined, `${l.id} draws at every zoom`);
  assert.ok(o.layers.filter(l => l.type === 'line').every(l => l.minzoom === undefined), 'lines draw at every zoom');
});

test('the card names the depth, interval, survey, date and datum; the edge says no reviewed grid continues', () => {
  const sources = assessContours(FULL, 'morro-bay', TODAY).sources;
  const f150 = FULL.features.find(f => f.properties.kind === 'contour' && f.properties.depth_ft === 150);
  const m = contourMark(f150.properties, sources);
  assert.equal(m.name, '150 ft depth contour');
  assert.equal(m.kind, `Index contour · every ${INDEX_FT} ft`);
  assert.match(m.reading, /150 ft below the survey's unverified source datum/);
  assert.match(m.reading, /not a sounding or a chart depth/);
  assert.match(m.source, /surveyed 2008 · unverified source datum$/);
  assert.equal(m.basis, layerEntry('depth-contours').basis);
  assert.ok(m.terms?.[0].href.startsWith('https://doi.org/'));
  const f60 = FULL.features.find(f => f.properties.kind === 'contour' && f.properties.depth_ft === 60);
  assert.equal(contourMark(f60.properties, sources).kind, `Depth contour · every ${INTERVAL_FT} ft`);
  const edge = contourMark(FULL.features.find(f => f.properties.kind === 'survey-edge').properties, sources);
  assert.equal(edge.name, 'Survey edge');
  assert.match(edge.reading, /No reviewed grid continues past this line/);
  assert.equal(contourMark({...f150.properties, source_id: 'gebco-2026'}, sources), null, 'an unlisted survey opens no card');
  assert.equal(contourMark(null, sources), null);
});

test('the registry entry: always on, Chart only, every zoom; the basis says not for navigation, names the datum and where lines stop', () => {
  const e = layerEntry('depth-contours');
  assert.equal(e.control, 'always');
  assert.deepEqual(e.presentations, ['chart']);
  assert.deepEqual(e.time, ['static']);
  assert.equal(e.gate, undefined, 'no zoom gate');
  assert.equal(e.task, 'CI6-13');
  assert.ok(e.attribution);
  assert.match(e.basis, /not for navigation/);
  assert.match(e.basis, /vertical datum/);
  assert.match(e.basis, /unverified/);
  assert.match(e.basis, /MLLW/);
  assert.match(e.basis, /stop at the dashed survey edge where no reviewed grid continues/);
  assert.match(e.basis, /every 30 ft/);
  assert.match(e.basis, /withheld one year after their source review/, 'the age limit');
  assert.match(e.basis, /2 m grids, surveyed 2008/, 'the product, grid and age');
  assert.doesNotMatch(e.basis + e.legend.map(r => r.label).join(' '), /\b(fish|catch|hotspot|feeding|bite)/i);
  assert.deepEqual(e.legend.map(r => r.swatch), ['depth1', 'muted']);
  // The ENC chart base is left as it was: its own entry, source, zoom gate and basis.
  assert.equal(layerEntry('chart').gate, 'zoom ≥ 10');
});

function setup(t, {files, today = Date.parse(`${TODAY}T18:00:00Z`)} = {}) {
  globalThis.location = {href: 'https://s.test/map?region=morro-bay'};
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  camera.value = {latitude: 35.35, longitude: -120.95, zoom: 11};
  const asked = [], calls = [];
  const fetchFn = async url => {
    const path = new URL(url).pathname.slice(1);
    asked.push(path);
    if (!(path in files)) return {ok: false, status: 404, json: async () => ({})};
    return {ok: true, status: 200, json: async () => clone(files[path])};
  };
  const engine = signal({setOverlay: (layer, o, before) => calls.push(['overlay', layer, o && o.layers.map(l => l.id), before ?? null]),
    setData: (id, data) => calls.push(['data', id, data.features.length])});
  const layer = createDepthContours({engine, fetchFn, page: () => location.href, palette: () => sentinel, now: () => today});
  t.after(() => { layer.destroy(); camera.value = null; });
  return {asked, calls, layer};
}
const FILES = {[depthContoursOverviewURL('morro-bay')]: OVERVIEW, [depthContoursURL('morro-bay')]: FULL};

test('the Chart layer draws the overview under the protected areas, swaps in the full contours at the detail zoom and keeps them', async t => {
  const {asked, calls, layer} = setup(t, {files: FILES});
  await flush(); await flush();
  assert.deepEqual(asked, [depthContoursOverviewURL('morro-bay')]);
  const drawnAt = calls.findIndex(c => c[0] === 'overlay' && c[2]);
  assert.deepEqual(calls[drawnAt], ['overlay', 'depth-contours', [DEPTH_EDGE, DEPTH_LINE, DEPTH_HIT, DEPTH_LABEL, DEPTH_LABEL_MINOR], MPA_FILL]);
  assert.deepEqual(calls[drawnAt + 1], ['data', DEPTH_CONTOURS_SOURCE, OVERVIEW.features.length]);
  assert.equal(contourState.value.status, 'drawn');
  assert.equal(contourState.value.sources.length, 3);
  const edge = OVERVIEW.features.find(f => f.properties.kind === 'survey-edge');
  assert.equal(layer.pick.mark(DEPTH_HIT, edge.properties).name, 'Survey edge');
  assert.ok(layer.pick.ordered);
  camera.value = {...camera.value, zoom: DETAIL_ZOOM + ZOOM_OFFSET};
  await flush(); await flush();
  assert.deepEqual(asked, [depthContoursOverviewURL('morro-bay'), depthContoursURL('morro-bay')]);
  assert.deepEqual(calls.at(-1), ['data', DEPTH_CONTOURS_SOURCE, FULL.features.length]);
  assert.equal(calls.filter(c => c[0] === 'overlay' && c[2]).length, 1, 'the overlay is added once');
  camera.value = {...camera.value, zoom: 9};
  await flush(); await flush();
  assert.equal(asked.length, 2, 'zooming out keeps the full contours: no second request');
});

test('a region without contours draws none and shows no row; expired contours are withheld and say so', async t => {
  const none = setup(t, {files: {}});
  await flush(); await flush();
  assert.equal(none.calls.some(c => c[2]), false);
  assert.equal(contourState.value.status, 'none');
  assert.equal(contourState.value.note, NOTES.none);
  camera.value = {...camera.value, zoom: DETAIL_ZOOM + ZOOM_OFFSET};
  await flush();
  assert.equal(none.asked.length, 1, 'the full form of a region without contours is not asked for');
  none.layer.destroy();
  const after = Date.parse(`${FULL.provenance.review_expires}T00:00:00Z`) + 2 * 86_400_000;
  const old = setup(t, {files: FILES, today: after});
  await flush(); await flush();
  assert.equal(old.calls.some(c => c[2]), false, 'nothing drawn past the age limit');
  assert.equal(contourState.value.status, 'withheld');
  assert.equal(contourState.value.note, NOTES.withheld);
  assert.equal(old.layer.pick.mark(DEPTH_HIT, OVERVIEW.features[0].properties), null);
});

// Shelf depth contours (CI6-13, docs/plans/front-end/design.md § 9): the published
// file's check, the overview/full switch, the overlay, the card and the Chart layer,
// read from the committed Morro Bay publication (offline) with a fake engine.
// web/map/depth-contours.ts runs by type stripping.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {
  DEPTH_BOTTOM, DEPTH_EDGE, DEPTH_HIT, DEPTH_LABEL, DEPTH_LABEL_MINOR, DEPTH_LINE, DEPTH_UNRESOLVED_FILL, DEPTH_UNRESOLVED_LINE, DETAIL_ZOOM, INDEX_FT, INTERVAL_FT, NOTES,
  assessContours, contourMark, contourState, contoursFor, contoursOverlay, createDepthContours, depthContoursOverviewURL, depthContoursURL, omittedNote,
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
  assert.deepEqual(o.layers.map(l => l.id), [DEPTH_UNRESOLVED_FILL, DEPTH_UNRESOLVED_LINE, DEPTH_EDGE, DEPTH_LINE, DEPTH_HIT, DEPTH_LABEL, DEPTH_LABEL_MINOR]);
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
  assert.deepEqual(calls[drawnAt], ['overlay', 'depth-contours', [DEPTH_UNRESOLVED_FILL, DEPTH_UNRESOLVED_LINE, DEPTH_EDGE, DEPTH_LINE, DEPTH_HIT, DEPTH_LABEL, DEPTH_LABEL_MINOR], MPA_FILL]);
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

const NOAA_BAG = [{source_id: 'noaa-bag', review_status: 'candidate'}];
const BAG_NOTE = '1 bound survey not drawn: noaa-bag (not yet reviewed).';
// Morro Bay's committed files now carry noaa-bag as approved (G, 2026-10-30), so the unreviewed wording
// is exercised on copies that state the survey as a candidate, as before.
const withBagCandidate = file => { const d = clone(file); d.provenance.sources_omitted = clone(NOAA_BAG); return d; };
const BAG_FULL = withBagCandidate(FULL);
const BAG_FILES = {[depthContoursOverviewURL('morro-bay')]: withBagCandidate(OVERVIEW), [depthContoursURL('morro-bay')]: BAG_FULL};

test('the committed Morro Bay file names noaa-bag as an approved survey it does not trace, with no unreviewed note', () => {
  const r = assessContours(FULL, 'morro-bay', TODAY);
  assert.deepEqual(r.omitted, [{source_id: 'noaa-bag', review_status: 'approved'}]);
  assert.equal(omittedNote(r.omitted), '');
});

test('the file names the bound surveys it does not draw; the card and the drawn note say so in plain words', async t => {
  const r = assessContours(BAG_FULL, 'morro-bay', TODAY);
  assert.deepEqual(r.omitted, NOAA_BAG);
  const f150 = BAG_FULL.features.find(f => f.properties.kind === 'contour' && f.properties.depth_ft === 150);
  const m = contourMark(f150.properties, r.sources, r.omitted);
  assert.match(m.reading, /1 bound survey not drawn: noaa-bag \(not yet reviewed\)\./);
  assert.match(m.reading, /150 ft below the survey's unverified source datum/);
  assert.equal(m.name, '150 ft depth contour');
  const edge = contourMark(BAG_FULL.features.find(f => f.properties.kind === 'survey-edge').properties, r.sources, r.omitted);
  assert.match(edge.reading, /No reviewed grid continues past this line/);
  assert.ok(edge.reading.endsWith(BAG_NOTE));
  const {layer} = setup(t, {files: BAG_FILES});
  await flush(); await flush();
  assert.equal(contourState.value.status, 'drawn');
  assert.equal(contourState.value.note, BAG_NOTE);
  assert.match(layer.pick.mark(DEPTH_HIT, f150.properties).reading, /not yet reviewed/);
});

test('a file without a well-formed omitted list fails; the note counts only unapproved surveys', () => {
  for (const omitted of [undefined, [{source_id: ''}], [{source_id: 'noaa-bag'}], 'noaa-bag']) {
    const d = clone(FULL);
    if (omitted === undefined) delete d.provenance.sources_omitted; else d.provenance.sources_omitted = omitted;
    assert.equal(assessContours(d, 'morro-bay', TODAY).status, 'failed', JSON.stringify(omitted));
  }
  const none = clone(FULL);
  none.provenance.sources_omitted = [];
  assert.deepEqual(assessContours(none, 'morro-bay', TODAY).omitted, []);
  assert.equal(omittedNote([]), '');
  assert.equal(omittedNote([{source_id: 'usgs-x', review_status: 'approved'}]), '');
  assert.equal(omittedNote([{source_id: 'nos-r', review_status: 'restricted'}]), '1 bound survey not drawn: nos-r (restricted).');
  assert.equal(omittedNote([...NOAA_BAG, {source_id: 'nos-r', review_status: 'restricted'}, {source_id: 'usgs-x', review_status: 'approved'}]),
    '2 bound surveys not drawn: noaa-bag (not yet reviewed), nos-r (restricted). 1 reviewed survey not traced in this file: usgs-x.');
  assert.equal(contourMark(FULL.features[0].properties, assessContours(FULL, 'morro-bay', TODAY).sources).reading.includes('not drawn'), false);
});

// EC6: provenance runs and unresolved areas (docs/seafloor-ec.md), on a copy of the committed full file.
const F60 = FULL.features.find(f => f.properties.kind === 'contour' && f.properties.depth_ft === 60);
const RUN = provenance => ({...clone(F60), id: `run-60ft-${provenance}`, properties: {...clone(F60.properties), provenance}});
const [X, Y] = F60.geometry.type === 'LineString' ? F60.geometry.coordinates[0] : F60.geometry.coordinates[0][0];
const SQUARE = [[X, Y], [X + 0.01, Y], [X + 0.01, Y + 0.01], [X, Y + 0.01], [X, Y]];
const AREA = (props = {reason: 'conflict', shoal_hint_ft: 12}, geometry = {type: 'Polygon', coordinates: [SQUARE]}) => ({type: 'Feature', id: 'area', geometry,
  properties: {kind: 'unresolved-area', source_id: F60.properties.source_id, survey_date: F60.properties.survey_date, vertical_datum: F60.properties.vertical_datum, blocks: 3, ...props}});
const EC = (...extra) => { const d = clone(FULL); d.features.push(RUN('filled'), RUN('verified'), AREA(), ...extra); return d; };
const card = (props, r = assessContours(EC(), 'morro-bay', TODAY)) => contourMark(props, r.sources, r.omitted);

test('EC6: filled and verified runs and a conflict area draw; their cards say how each was made, keeping the basis', () => {
  const r = assessContours(EC(), 'morro-bay', TODAY);
  assert.equal(r.status, 'drawn');
  assert.equal(r.data.features.length, FULL.features.length + 3);
  const filled = card(RUN('filled').properties), verified = card(RUN('verified').properties), area = card(AREA().properties);
  assert.match(filled.reading, /shallowest neighbouring depth; not measured at this spot\.$/);
  assert.match(verified.reading, /Two independent surveys agree here within the published tolerance\.$/);
  for (const m of [filled, verified]) assert.equal(m.name, '60 ft depth contour');
  assert.equal(card(RUN('measured').properties).reading, card(F60.properties).reading, 'measured reads as an unmarked line');
  assert.equal(area.name, 'Unverified / no data');
  assert.equal(area.kind, 'Where the survey could not be verified');
  assert.equal(area.reading, 'Two surveys disagree here; the shallower reading is 12 ft. Treat as a possible shoal.');
  for (const m of [filled, verified, area]) { assert.equal(m.basis, layerEntry('depth-contours').basis); assert.match(m.basis, /not for navigation/); }
  assert.match(area.source, /unverified source datum$/);
  const readings = {hole: /no usable measurement here; the gap is too large to fill safely\.$/, 'ring-range': /^A small gap on a steep or rough bottom; not filled\.$/,
    'datum-suspect': /may use different vertical datums; not compared\.$/, nodata: /^No data\.$/};
  for (const [reason, re] of Object.entries(readings)) assert.match(card(AREA({reason}).properties).reading, re, reason);
  const bag = withBagCandidate(EC()), rb = assessContours(bag, 'morro-bay', TODAY);
  assert.ok(contourMark(AREA({reason: 'hole'}).properties, rb.sources, rb.omitted).reading.endsWith(BAG_NOTE), 'then the omitted note');
  for (const props of [{reason: 'foo'}, {reason: ' conflict', shoal_hint_ft: 12}, {reason: 'conflict'}, {reason: 'conflict', shoal_hint_ft: 0}])
    assert.equal(card(AREA(props).properties), null, JSON.stringify(props));
  assert.equal(card({...F60.properties, kind: ' contour'}), null, 'a padded kind opens no card');
});

test('EC6: any unknown kind, geometry, reason, hint or provenance still fails the whole file', () => {
  const line = {type: 'LineString', coordinates: SQUARE.slice(0, 2)}, open = [...SQUARE.slice(0, 4), [X + 0.02, Y]];
  const broken = [
    ['an area drawn as a line', AREA(undefined, line)],
    ['an unknown reason', AREA({reason: 'foo'})],
    ['a padded reason', AREA({reason: 'hole '})],
    ['no reason', AREA({reason: undefined})],
    ['a shoal hint on a hole', AREA({reason: 'hole', shoal_hint_ft: 12})],
    ['a conflict without its hint', AREA({reason: 'conflict'})],
    ['a fractional hint', AREA({reason: 'conflict', shoal_hint_ft: 12.5})],
    ['a hint as text', AREA({reason: 'conflict', shoal_hint_ft: '12'})],
    ['a zero hint', AREA({reason: 'conflict', shoal_hint_ft: 0})],
    ['an open ring', AREA(undefined, {type: 'Polygon', coordinates: [open]})],
    ['a three-point ring', AREA(undefined, {type: 'Polygon', coordinates: [[SQUARE[0], SQUARE[1], SQUARE[0]]]})],
    ['a ring with a NaN', AREA(undefined, {type: 'Polygon', coordinates: [[...SQUARE.slice(0, 2), [NaN, Y], ...SQUARE.slice(3)]]})],
    ['an empty polygon', AREA(undefined, {type: 'Polygon', coordinates: []})],
    ['a padded area kind', {...AREA(), properties: {...AREA().properties, kind: ' unresolved-area'}}],
    ['a guessed contour', RUN('guessed')],
    ['an empty provenance', RUN('')],
    ['a contour drawn as a polygon', {...RUN('filled'), geometry: {type: 'Polygon', coordinates: [SQUARE]}}],
    ['a survey edge drawn as a polygon', {...AREA(), properties: {...FULL.features.find(f => f.properties.kind === 'survey-edge').properties}}],
  ];
  for (const [what, feature] of broken) assert.equal(assessContours(EC(feature), 'morro-bay', TODAY).status, 'failed', what);
  const multi = AREA({reason: 'nodata'}, {type: 'MultiPolygon', coordinates: [[SQUARE], [SQUARE]]});
  assert.equal(assessContours(EC(multi), 'morro-bay', TODAY).status, 'drawn', 'a MultiPolygon area draws');
});

for (const type of ['Polygon', 'MultiPolygon']) {
  test(`EC6: ${type} requires an exact geometry type or the whole file fails`, () => {
    const coordinates = type === 'Polygon' ? [SQUARE] : [[SQUARE]];
    const canonical = EC(AREA(undefined, {type, coordinates}));
    const drawn = assessContours(canonical, 'morro-bay', TODAY);
    assert.equal(drawn.status, 'drawn', 'canonical geometry still draws');
    assert.deepEqual(drawn.data.features, canonical.features, 'accepted geometry is passed through unchanged');
    for (const padded of [` ${type}`, `${type} `]) {
      const file = EC(AREA(undefined, {type: padded, coordinates}));
      const result = assessContours(file, 'morro-bay', TODAY);
      assert.equal(result.status, 'failed', JSON.stringify(padded));
      assert.equal(result.data, null, 'no partial collection escapes to the renderer');
    }
  });
}

test('EC6: the area draws muted and dashed at the bottom; filled runs dash and verified runs draw heavier; the area is clickable', async t => {
  const o = contoursOverlay(sentinel, EC()), by = id => o.layers.find(l => l.id === id), ids = o.layers.map(l => l.id);
  assert.equal(DEPTH_BOTTOM, DEPTH_UNRESOLVED_FILL);
  assert.ok(ids.indexOf(DEPTH_UNRESOLVED_FILL) < ids.indexOf(DEPTH_UNRESOLVED_LINE) && ids.indexOf(DEPTH_UNRESOLVED_LINE) < ids.indexOf(DEPTH_EDGE));
  const unresolved = ['==', ['get', 'kind'], 'unresolved-area'];
  assert.deepEqual(by(DEPTH_UNRESOLVED_FILL), {id: DEPTH_UNRESOLVED_FILL, type: 'fill', source: DEPTH_CONTOURS_SOURCE, filter: unresolved,
    paint: {'fill-color': 'token(muted)', 'fill-opacity': 0.18}});
  assert.deepEqual(by(DEPTH_UNRESOLVED_LINE).filter, unresolved);
  assert.deepEqual(by(DEPTH_UNRESOLVED_LINE).paint, {'line-color': 'token(muted)', 'line-width': 1, 'line-dasharray': [1, 2]});
  const line = by(DEPTH_LINE).paint, verified = ['case', ['==', ['get', 'provenance'], 'verified'], 1.25, 1], index = ['==', ['get', 'index'], true];
  assert.deepEqual(line['line-dasharray'], ['case', ['==', ['get', 'provenance'], 'filled'], ['literal', [4, 3]], ['literal', [1, 0]]]);
  assert.deepEqual(line['line-width'], ['interpolate', ['linear'], ['zoom'],
    8, ['*', ['case', index, 0.9, 0.4], verified], 14, ['*', ['case', index, 1.6, 0.8], verified]]);
  assert.deepEqual(by(DEPTH_LABEL).filter, ['all', ['==', ['get', 'kind'], 'contour'], index], 'labels still follow every contour');
  const {layer} = setup(t, {files: {[depthContoursOverviewURL('morro-bay')]: EC()}});
  await flush(); await flush();
  assert.equal(contourState.value.status, 'drawn');
  assert.deepEqual(layer.pick.layers, [DEPTH_HIT, DEPTH_UNRESOLVED_FILL]);
  assert.match(layer.pick.mark(DEPTH_UNRESOLVED_FILL, AREA().properties).reading, /shallower reading is 12 ft/);
});

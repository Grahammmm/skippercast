// Walkthrough slice 3 (#620): the rail's terrain grade filter (`?grade=`) narrows reef
// marks and seafloor candidates, and below `?view=` zoom 10 the screened marks draw as a
// density weighted by grade and habitat fit that hands over to the marks. Over the
// committed Morro Bay atlas, offline; the web/*.ts files run by type stripping.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {GRADE_LABELS, GRADE_MEANING, gradeAllows, gradeParam, parseGrade} from '../web/grade.ts';
import {EMPTY, assessScreen, markFeatures, markWeight} from '../web/map/habitat.ts';
import {DENSITY_SOURCE, MARKS_SOURCE, layerEntry, sourceLayer} from '../web/map/layers.ts';
import {DENSITY_BELOW_VIEW_ZOOM, densityLayer, densityShown, markData, markScreen, markSources, markStyle} from '../web/map/marks.ts';
import {readPalette} from '../web/map/palette.ts';
import {gradeFiltered} from '../web/map/seafloor.ts';
import {camera} from '../web/map/stage.ts';
import {configureStore, grade, readURL, syncFromURL, withParams} from '../web/state.ts';

const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const MARKS = read('regions/morro-bay/atlas-marks.json');
const READY = assessScreen({areas: read('data/protected-areas.geojson').features, checkedAt: new Date().toISOString(), live: true}, Date.now());
const STALE = assessScreen({areas: read('data/protected-areas.geojson').features, checkedAt: '2020-01-01T00:00:00Z', live: false}, Date.now());
const gradeOf = id => MARKS.targets.find(t => t.id === id).habitat_grade;
const PROMISE = /\b(?:fish here|hotspot|catch rate|chance|odds|probab\w*|guarantee\w*|bite)\b/i;

test('?grade= parses to a filter, writes back, and anything unknown means all grades', () => {
  assert.deepEqual(['a', 'AB', 'ab', 'c', '', null, 'all'].map(parseGrade), ['a', 'ab', 'ab', 'all', 'all', 'all', 'all']);
  assert.deepEqual(['all', 'ab', 'a'].map(gradeParam), [null, 'ab', 'a']);
  assert.deepEqual(['A', 'B', 'C', undefined].map(g => gradeAllows('all', g)), [true, true, true, true], 'all keeps ungraded features');
  assert.deepEqual(['A', 'b', 'C', undefined].map(g => gradeAllows('ab', g)), [true, true, false, false]);
  assert.deepEqual(['A', 'B', 'C', undefined].map(g => gradeAllows('a', g)), [true, false, false, false], 'an ungraded feature never passes as A');
  configureStore({storage: null});
  const href = withParams('https://s.test/map?region=morro-bay&target=rockfish', {grade: 'a'});
  assert.equal(readURL(href).grade, 'a');
  syncFromURL(href);
  assert.equal(grade.value, 'a');
  syncFromURL('https://s.test/map?region=morro-bay&grade=zzz');
  assert.equal(grade.value, 'all');
});

test('the grade filter hides lower-graded reef marks; all grades leaves the marks as they were', () => {
  const all = markFeatures(MARKS, 'rockfish', 'boat', READY);
  const ab = markFeatures(MARKS, 'rockfish', 'boat', READY, 'ab'), a = markFeatures(MARKS, 'rockfish', 'boat', READY, 'a');
  assert.ok(all.features.some(f => gradeOf(f.properties.id) === 'C'), 'the fixture has C marks to hide');
  assert.ok(a.features.length > 0 && a.features.length < ab.features.length && ab.features.length < all.features.length);
  assert.ok(ab.features.every(f => ['A', 'B'].includes(gradeOf(f.properties.id))));
  assert.ok(a.features.every(f => gradeOf(f.properties.id) === 'A'));
  assert.deepEqual(markFeatures(MARKS, 'rockfish', 'boat', READY, 'all'), all);
});

test('density weights rank grade and fit, change with the target, and draw nothing without marks or a current screen', () => {
  const [strong] = MARKS.targets.filter(t => t.habitat_grade === 'A');
  const weak = MARKS.targets.find(t => t.habitat_grade === 'C');
  assert.ok(markWeight(strong, 'rockfish') > markWeight(weak, 'rockfish'), 'A outweighs C');
  for (const t of MARKS.targets) for (const target of ['lingcod', 'rockfish']) {
    const w = markWeight(t, target);
    assert.ok(w > 0 && w <= 1, `${t.id} ${target} weight ${w}`);
  }
  assert.ok(MARKS.targets.some(t => markWeight(t, 'lingcod') !== markWeight(t, 'rockfish')), 'the target changes the weights');
  const features = markFeatures(MARKS, 'rockfish', 'boat', READY).features;
  assert.ok(features.every(f => typeof f.properties.weight === 'number'));
  assert.deepEqual(markFeatures(MARKS, 'halibut', 'boat', READY), EMPTY, 'a soft-bottom target has no reef density');
  assert.deepEqual(markFeatures({targets: []}, 'rockfish', 'boat', READY), EMPTY, 'a region without marks draws nothing');
  assert.deepEqual(markFeatures(MARKS, 'rockfish', 'boat', STALE).features, [], 'a stale protected-area check withholds the density too');
});

test('the density source belongs to the Marks entry, fades out as the marks come in, and colours from the palette', () => {
  assert.equal(sourceLayer(DENSITY_SOURCE), 'marks');
  assert.equal(sourceLayer(MARKS_SOURCE), 'marks');
  const sentinel = readPalette(name => `token(${name})`);
  const layer = densityLayer(sentinel), style = markStyle(sentinel);
  assert.equal(layer.type, 'heatmap');
  assert.equal(layer.source, DENSITY_SOURCE);
  assert.ok(style.sources[DENSITY_SOURCE], 'the style declares the source');
  assert.equal(style.marks[0].id, layer.id, 'the density sits under the marks');
  const marksFrom = style.marks.find(l => l.id === 'marks-ring').minzoom;
  assert.equal(DENSITY_BELOW_VIEW_ZOOM, marksFrom + 1, 'the density hands over at the view zoom the marks draw from');
  assert.ok(layer.maxzoom > marksFrom && layer.maxzoom <= marksFrom + 1, 'a short cross-fade, not two layers competing');
  const colors = layer.paint['heatmap-color'].filter(v => typeof v === 'string' && v.startsWith('token('));
  assert.deepEqual(colors, [sentinel.depth2, sentinel.depth1, sentinel.depth0], 'the depth ramp, strongest brightest');
  assert.deepEqual(layer.paint['heatmap-weight'], ['coalesce', ['get', 'weight'], 0]);
});

test('the density follows the profile and zoom: none for Shore, a legend count only when zoomed out on the Chart', () => {
  configureStore({storage: null});
  syncFromURL('https://s.test/map?region=morro-bay&profile=boat&target=rockfish');
  markData.value = {region: {id: 'morro-bay'}, atlas: MARKS, survey: null, geology: null};
  const density = markSources[DENSITY_SOURCE];
  assert.equal(density.value.features.length, 0, 'withheld until the screen is ready');
  camera.value = {latitude: 35.3, longitude: -120.9, zoom: 8};
  assert.equal(densityShown.value, null, 'no legend line while the protected-area check is pending');
  markScreen.value = READY;
  const n = markFeatures(MARKS, 'rockfish', 'boat', READY).features.length;
  assert.equal(density.value.features.length, n, 'the screened rockfish marks');
  assert.equal(densityShown.value, n, 'the legend counts what the density draws from');
  camera.value = {latitude: 35.3, longitude: -120.9, zoom: DENSITY_BELOW_VIEW_ZOOM};
  assert.equal(densityShown.value, null, 'from zoom 10 the marks speak for themselves');
  camera.value = {latitude: 35.3, longitude: -120.9, zoom: 8};
  syncFromURL('https://s.test/map?region=morro-bay&profile=boat&target=halibut');
  assert.equal(densityShown.value, 0, 'a target without reef marks says so instead of leaving empty water');
  syncFromURL('https://s.test/map?region=morro-bay&profile=shore&target=rockfish');
  assert.deepEqual(density.value.features, [], 'Shore draws no reef density');
  assert.equal(densityShown.value, null);
  markData.value = null; camera.value = null;
});

test('the density wording names habitat candidates and grades, never fish', () => {
  const entry = layerEntry('marks');
  for (const text of [entry.basis, ...entry.legend.map(l => l.label), GRADE_MEANING, ...Object.values(GRADE_LABELS)]) assert.doesNotMatch(text, PROMISE, text);
  assert.match(entry.legend.map(l => l.label).join(' '), /Habitat candidates, denser here/);
  assert.match(GRADE_MEANING, /not catch/);
});

test('the seafloor grade filter keeps candidates by terrain grade and unranked areas only with all grades', () => {
  const f = (kind, terrain_grade) => ({kind, properties: {terrain_grade}});
  const list = [f('candidate', 'A'), f('candidate', 'B'), f('candidate', 'C'), f('search'), f('interpreted')];
  assert.equal(gradeFiltered(list, 'all').length, 5);
  assert.deepEqual(gradeFiltered(list, 'ab'), list.slice(0, 2));
  assert.deepEqual(gradeFiltered(list, 'a'), list.slice(0, 1));
});

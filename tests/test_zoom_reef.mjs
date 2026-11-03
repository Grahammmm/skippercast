import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {assessScreen, atlasCard, depthBand, markFeatures, markShown, withheld} from '../web/map/habitat.ts';
import {gradeAllows} from '../web/grade.ts';
import {withinDepth, ownSpearDepthFt} from '../web/profile.ts';
import {GEOLOGY_PICK, MARK_PICK, SURVEY_PICK, markStyle} from '../web/map/marks.ts';
import {MARKS_SOURCE, SURVEY_SOURCE} from '../web/map/layers.ts';
import {readPalette} from '../web/map/palette.ts';
import {LABEL_FONT} from '../web/map/style.ts';

const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const region = read('regions/cambria-san-simeon/region.json');
const atlas = read(region.assets.atlas);
const morro = read('data/atlas.json');
const ready = assessScreen({areas: [], checkedAt: '2026-01-01T00:00:00Z', live: true}, Date.parse('2026-01-01T00:00:00Z'));
const stale = assessScreen({areas: [], checkedAt: '2025-12-01T00:00:00Z', live: false}, Date.parse('2026-01-01T00:00:00Z'));
const promise = /\b(?:hotspot|chance|odds|probab\w*|productive|best spot|catch rate|bite|guarantee\w*)\b/i;

test('depth bands require two ordered finite numbers within 0–1000', () => {
  assert.equal(depthBand([45.4, 79.6]), '45–80 ft');
  assert.equal(depthBand([80, 80]), '80–80 ft');
  assert.equal(depthBand([0, 1000]), '0–1000 ft');
  for (const value of [undefined, null, [], [45], [80, 45], [NaN, 10], [-5, 10], [10, 5000], ['45', '80'], [0, Infinity], [1, 2, 3], [, 10]]) {
    assert.equal(depthBand(value), null);
  }
});

test('labels preserve the existing screened, depth-limited features and card text', () => {
  for (const source of [atlas, morro]) {
    const features = markFeatures(source, 'reef', 'boat', ready).features;
    const baseline = source.targets.filter(t => markShown(t, 'reef') && withinDepth('boat', t.neighborhood_depth_ft?.[1]) && gradeAllows('all', t.habitat_grade) && !withheld(t, ready));
    assert.equal(features.length, baseline.length);
    if (source === morro) assert.ok(features.length > 0);
    for (const f of features) {
      const t = baseline.find(t => t.id === f.properties.id), expected = depthBand(t.neighborhood_depth_ft);
      if (expected === null) assert.equal('depth' in f.properties, false);
      else { assert.equal(f.properties.depth, expected); assert.doesNotMatch(f.properties.depth, promise); }
      assert.notEqual(f.properties.depth, '');
    }
    const data = {region, atlas: source, survey: null, geology: null};
    for (const t of source.targets.slice(0, 3)) {
      const d = t.neighborhood_depth_ft;
      const range = d?.length === 2 ? `~${Math.round(d[0])}–${Math.round(d[1])} ft` : '';
      const oldKind = ['Reef mark', t.habitat_grade && `grade ${t.habitat_grade}`, range].filter(x => typeof x === 'string' && x.trim()).join(' · ');
      assert.equal(atlasCard(t, data, 'reef').kind, oldKind);
    }
  }
  assert.ok(morro.targets.length >= 3);
  const template = morro.targets[0];
  const sample = {targets: [{...template, id: 'shallow', neighborhood_depth_ft: [30, 60]}, {...template, id: 'deep', neighborhood_depth_ft: [30, 61]}, {...template, id: 'invalid', neighborhood_depth_ft: [61, 30]}]};
  const prior = ownSpearDepthFt.value;
  try {
    ownSpearDepthFt.value = null;
    const features = markFeatures(sample, 'reef', 'spear', ready).features;
    assert.ok(features.some(f => f.properties.id === 'shallow' && f.properties.depth === '30–60 ft'));
    assert.ok(!features.some(f => f.properties.id === 'deep'));
    assert.ok(features.some(f => f.properties.id === 'invalid' && !('depth' in f.properties)));
    assert.equal(markFeatures(sample, 'reef', 'spear', stale).features.length, 0);
  } finally { ownSpearDepthFt.value = prior; }
});

test('zoom styling adds non-pickable outline and optional label with palette colours', () => {
  const p = readPalette(name => `token(${name})`), style = markStyle(p);
  const habitat = style.habitat, marks = style.marks;
  assert.deepEqual(habitat.map(l => l.id), [SURVEY_PICK, 'survey-habitat-line', GEOLOGY_PICK, 'geology-line']);
  assert.deepEqual(marks.map(l => l.id), ['marks-density', MARK_PICK, 'marks-ring', 'marks-fit', 'marks-depth', 'selection-ring']);
  const fill = habitat[0], line = habitat[1], label = marks[4];
  assert.equal(line.type, 'line'); assert.equal(line.source, SURVEY_SOURCE); assert.equal(line.minzoom, 11);
  assert.deepEqual(line.paint['line-color'], fill.paint['fill-color']);
  assert.deepEqual(line.paint['line-width'], ['interpolate', ['linear'], ['zoom'], 11, 0.6, 15, 1.6]);
  assert.equal(line.paint['line-opacity'], 0.8);
  const opacity = fill.paint['fill-opacity'];
  assert.deepEqual(opacity, ['interpolate', ['linear'], ['zoom'], 9, 0.12, 12, 0.22, 15, 0.3]);
  for (let i = 3; i < opacity.length; i += 2) { assert.ok(opacity[i + 1] > 0 && opacity[i + 1] <= 0.35); if (i > 3) assert.ok(opacity[i] > opacity[i - 2]); }
  assert.equal(label.type, 'symbol'); assert.equal(label.source, MARKS_SOURCE); assert.equal(label.minzoom, 12);
  assert.deepEqual(label.filter, ['has', 'depth']); assert.deepEqual(label.layout['text-field'], ['get', 'depth']);
  assert.deepEqual(label.layout['text-font'], [LABEL_FONT]);
  assert.deepEqual(label.layout['text-size'], ['interpolate', ['linear'], ['zoom'], 12, 10, 15, 12]);
  assert.deepEqual(label.layout['text-offset'], [0, 1.6]); assert.equal(label.layout['text-anchor'], 'top');
  assert.equal(label.layout['text-optional'], true);
  assert.deepEqual(label.paint, {'text-color': p.text, 'text-halo-color': p.bg, 'text-halo-width': 1.2});
  assert.doesNotMatch(JSON.stringify([line.paint['line-color'], label.paint]), /#[0-9a-f]{3,8}|rgba?\(/i);
});

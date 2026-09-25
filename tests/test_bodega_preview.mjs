import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {habitatDetails} from '../dist/survey-habitat.js';

const load = path => JSON.parse(readFileSync(new URL(path, import.meta.url)));

test('Bodega original hard-bottom context stays separate from fishing targets', () => {
  const region = load('../dist/regions/bodega-point-reyes/region.json');
  const atlas = load('../dist/regions/bodega-point-reyes/atlas.json');
  const habitat = load('../dist/regions/bodega-point-reyes/survey-habitat.geojson');
  const plans = load('../dist/regions/bodega-point-reyes/search-plans.json');
  assert.equal(region.status, 'preview');
  assert.equal(atlas.targets.length, 0);
  assert.equal(habitat.features.length, 17);
  assert.equal(plans.features.length, 17);
  assert.match(habitatDetails(habitat.features[0], region), /Original measured cells inside this outline/);
  for (const feature of habitat.features) {
    const p = feature.properties;
    assert.equal(p.fishing_target, false);
    assert.equal(p.fishing_export, false);
    assert.equal(p.depth_qualified, false);
    assert.equal(p.bottom_view, false);
    assert.equal(p.quality_grade, null);
    assert.equal(p.catch_evidence, false);
    assert.ok(p.qualified_original_cells > 0);
    assert.ok(p.sampled_original_depth_ft.minimum >= 25);
    assert.ok(p.sampled_original_depth_ft.maximum <= 200);
  }
  for (const feature of plans.features) {
    assert.equal(feature.properties.exportable, false);
    assert.equal(feature.properties.depth_qualified, false);
  }
});

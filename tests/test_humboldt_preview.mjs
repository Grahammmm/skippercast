import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {habitatDetails} from '../dist/survey-habitat.js';

const load = path => JSON.parse(readFileSync(new URL(path, import.meta.url)));

test('Humboldt original-grid research remains separate from fishing targets', () => {
  const region = load('../dist/regions/humboldt-bay-cape-mendocino/region.json');
  const atlas = load('../dist/regions/humboldt-bay-cape-mendocino/atlas.json');
  const habitat = load('../dist/regions/humboldt-bay-cape-mendocino/survey-habitat.geojson');
  const plans = load('../dist/regions/humboldt-bay-cape-mendocino/search-plans.json');
  assert.equal(region.status, 'preview');
  assert.deepEqual(region.map.region_notice_ids, ['northern-mpas', 'humboldt-mpas']);
  assert.equal(atlas.targets.length, 0);
  assert.equal(habitat.features.length, 121);
  assert.equal(plans.features.length, 121);
  assert.match(habitatDetails(habitat.features[0], region), /Original measured cells inside this outline/);
  for (const feature of habitat.features) {
    const p = feature.properties;
    assert.equal(p.fishing_target, false);
    assert.equal(p.fishing_export, false);
    assert.equal(p.depth_qualified, false);
    assert.equal(p.bottom_view, false);
    assert.equal(p.charter_evidence, false);
    assert.ok(p.qualified_original_cells > 0);
    const depths = p.sampled_original_depth_ft;
    assert.ok(depths.minimum >= 25 && depths.maximum <= 200);
    assert.ok(depths.minimum <= depths.p05 && depths.p05 <= depths.median);
    assert.ok(depths.median <= depths.p95 && depths.p95 <= depths.maximum);
  }
  for (const feature of plans.features) {
    assert.equal(feature.properties.exportable, false);
    assert.equal(feature.properties.depth_qualified, false);
  }
});

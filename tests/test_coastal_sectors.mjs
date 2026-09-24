import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {sectorAt,sectorsForCoast,trustedNoaaLink} from '../dist/coastal-sectors.js';

const packet=JSON.parse(fs.readFileSync(new URL('../dist/data/coastal-sectors.json',import.meta.url)));
test('statewide discovery sectors are complete and cannot be mistaken for mapped grounds',()=>{
  assert.equal(packet.sectors.length,19);
  assert.equal(sectorsForCoast(packet,'northern').length,3);
  assert.equal(packet.sectors.every(s=>s.status==='discovery'),true);
  const north=sectorAt(packet,'northern',{latitude:41.5,longitude:-124.5});
  assert.equal(north.id,'crescent-city-humboldt');
  assert.equal(sectorAt(packet,'northern',{latitude:40.95,longitude:-124.5}).id,'crescent-city-humboldt');
  assert.equal(sectorAt(packet,'northern',{latitude:41.5,longitude:-126}),null);
  assert.equal(sectorAt(packet,'northern',{latitude:NaN,longitude:-124.5}),null);
});
test('survey source links require official HTTPS host and matching survey identity',()=>{
  assert.equal(trustedNoaaLink('https://www.ngdc.noaa.gov/nos/H10001-H12000/H11983.html','H11983','catalog'),true);
  assert.equal(trustedNoaaLink('https://data.ngdc.noaa.gov/nos/H11983/BAG/grid.bag','H11983'),true);
  assert.equal(trustedNoaaLink('javascript:alert(1)','H11983'),false);
  assert.equal(trustedNoaaLink('https://www.ngdc.noaa.gov.evil.example/H11983/BAG/grid.bag','H11983'),false);
  assert.equal(trustedNoaaLink('https://data.ngdc.noaa.gov/nos/H11111/BAG/grid.bag','H11983'),false);
});
test('Eureka jetty class is withheld from natural hard-bottom context',()=>{
  const layer=JSON.parse(fs.readFileSync(new URL('../dist/data/usgs-hard-context-northern.geojson',import.meta.url)));
  const eureka=layer.features.filter(f=>f.properties.release_id==='P9EC35PF');
  assert.equal(eureka.length,0);
  const hold=layer.held_releases.find(r=>r.release_id==='P9EC35PF');
  assert.ok(hold?.reason.includes('North Jetty'));
  assert.ok(hold.evidence_urls.some(url=>url.includes('9418768')));
  const review=JSON.parse(fs.readFileSync(new URL('../dist/data/usgs-eureka-jetty-hold-review.json',import.meta.url)));
  assert.equal(review.fishing_target,false);
  assert.equal(review.exportable,false);
  assert.equal(review.products.length,3);
  assert.deepEqual(review.original_cmecs_geoform_review.candidate_centroid_checks.map(p=>p.nearest_geoform),
    ['Jetty','Jetty']);
  assert.ok(review.original_cmecs_geoform_review.candidate_centroid_checks.every(p=>
    p.nearest_geoform_distance_m<15));
  assert.ok(review.products.every(p=>p.joined_hard_depth_cells>0 &&
    p.largest_components[0].centroid_distance_to_landmark_m<800 &&
    p.usgs_source.archive_sha256==='c3d17d3361c96e80835120a0d9861a87257336ecbe261c1a7f2abd8f01a0dfcf'));
});
test('Cape Mendocino native evidence is a held source review, never a fishing target',()=>{
  const coverage=JSON.parse(fs.readFileSync(new URL('../dist/data/noaa-cape-mendocino-vr-source-coverage.json',import.meta.url)));
  const screen=JSON.parse(fs.readFileSync(new URL('../dist/data/noaa-h11975-cape-mendocino-hard-depth-screen.json',import.meta.url)));
  assert.equal(coverage.scope,'original-vr-bag-usgs-source-footprint-audit');
  assert.equal(coverage.usgs_release_id,'P9U0SUGL');
  assert.equal(coverage.fishing_target,false);
  assert.equal(coverage.exportable,false);
  assert.deepEqual(coverage.surveys.map(s=>s.survey_id),['H11973','H11974','H11975']);
  assert.equal(coverage.surveys[0].overview_bbox_intersects_source,true);
  assert.equal(coverage.surveys[0].supergrid_footprints_intersect_source_bbox,0);
  assert.equal(coverage.surveys[1].supergrid_footprints_intersect_source_bbox,0);
  assert.ok(coverage.surveys[2].fine_supergrid_footprints_intersect_source_bbox>20000);
  assert.equal(screen.scope,'original-vr-noaa-usgs-hard-depth-cell-screen');
  assert.equal(screen.survey_id,'H11975');
  assert.equal(screen.bag_sha256,coverage.surveys[2].bag_sha256);
  assert.equal(screen.usgs_archive_sha256,coverage.usgs_class_sha256);
  assert.equal(screen.fishing_target,false);
  assert.equal(screen.exportable,false);
  assert.equal(screen.historical_hazards_screened,11);
  assert.ok(screen.counts.joined_cells_after_mpa_gea_historical_dton>0);
  assert.ok(screen.counts.joined_cells_after_mpa_gea_historical_dton<screen.counts.joined_hard_depth_cells);
  assert.ok(screen.joined_depth_ft_range[0]>=25 && screen.joined_depth_ft_range[1]<=200);
  const context=JSON.parse(fs.readFileSync(new URL('../dist/data/cape-mendocino-native-hard-context.geojson',import.meta.url)));
  assert.equal(context.scope,'northern-native-noaa-usgs-hard-bottom-context');
  assert.equal(context.coast_id,'northern');
  assert.equal(context.historical_hazards_screened,11);
  assert.deepEqual(context.source_screen_counts,screen.counts);
  assert.ok(context.features.length>100 && context.features.length<500);
  assert.ok(context.features.every(f=>f.properties.survey_id==='H11975' &&
    f.properties.fishing_target===false && f.properties.exportable===false &&
    f.properties.legal_clearance===false && f.properties.fish_confirmed===false &&
    f.properties.depth_qualified_for_target===false &&
    f.properties.depth_range_kind==='screened-policy-not-local-depth-range' &&
    f.properties.depth_screen_ft[1]===200 &&
    Number.isFinite(f.properties.sampled_relief_5_95_m) &&
    f.properties.sampled_relief_5_95_m>=0 &&
    f.properties.display_depth_samples>=20 &&
    f.properties.noaa_bag_sha256===screen.bag_sha256));
});
test('Point Conception original-cell layer cannot become fishing or export coordinates',()=>{
  const layer=JSON.parse(fs.readFileSync(new URL('../dist/data/point-conception-native-hard-context.geojson',import.meta.url)));
  const summary=JSON.parse(fs.readFileSync(new URL('../dist/data/point-conception-native-hard-review-summary.json',import.meta.url)));
  assert.equal(layer.coast_id,'central');
  assert.equal(layer.scope,'central-native-noaa-usgs-hard-bottom-context');
  assert.equal(summary.surveys.length,2);
  assert.equal(summary.surveys[0].survey_id,'H11952');
  assert.equal(summary.surveys[0].counts.retained_components,27);
  assert.equal(summary.surveys[1].survey_id,'H11953');
  assert.equal(summary.surveys[1].counts.retained_components,1);
  assert.equal(layer.features.length,21);
  assert.ok(layer.features.every(f=>['H11952','H11953'].includes(f.properties.survey_id) &&
    f.properties.fishing_target===false && f.properties.exportable===false &&
    f.properties.legal_clearance===false && f.properties.fish_confirmed===false &&
    f.properties.depth_qualified_for_target===false && f.properties.depth_ft_range[1]<=200));
  const southern=JSON.parse(fs.readFileSync(new URL('../dist/data/gaviota-native-hard-context.geojson',import.meta.url)));
  const southernSummary=JSON.parse(fs.readFileSync(new URL('../dist/data/gaviota-native-hard-review-summary.json',import.meta.url)));
  assert.equal(southern.coast_id,'southern');
  assert.equal(southern.scope,'southern-native-noaa-usgs-hard-bottom-context');
  assert.equal(southernSummary.surveys[0].survey_id,'H11951');
  assert.equal(southernSummary.surveys[0].counts.retained_components,23);
  assert.equal(southern.features.length,12);
  assert.ok(southern.features.every(f=>f.properties.survey_id==='H11951' &&
    f.properties.fishing_target===false && f.properties.exportable===false &&
    f.properties.legal_clearance===false && f.properties.fish_confirmed===false &&
    f.properties.depth_qualified_for_target===false && f.properties.depth_ft_range[1]<=200));
});
test('charted-danger review flags only existing historical outlines',()=>{
  for(const [name,expected] of [['cape-mendocino',27],['point-conception',0],['gaviota',6]]){
    const context=JSON.parse(fs.readFileSync(new URL(`../dist/data/${name}-native-hard-context.geojson`,import.meta.url)));
    const review=JSON.parse(fs.readFileSync(new URL(`../dist/data/${name}-enc-context-review.json`,import.meta.url)));
    const ids=new Set(context.features.map(f=>f.properties.id));
    assert.equal(review.status,'research-screen-only');
    assert.equal(review.queried_layers,18);
    assert.equal(Object.values(review.context_outlines_in_scope_by_survey).reduce((a,b)=>a+b,0),ids.size);
    assert.equal(review.outlines_near_charted_dangers.length,expected);
    assert.ok(review.outlines_near_charted_dangers.every(row=>ids.has(row.context_id) && row.charted_dangers_within_buffer>0));
    assert.ok(context.features.every(f=>f.properties.fishing_target===false && f.properties.exportable===false));
  }
});

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
test('Eureka original class remains historical context rather than a fishing target',()=>{
  const layer=JSON.parse(fs.readFileSync(new URL('../dist/data/usgs-hard-context-northern.geojson',import.meta.url)));
  const eureka=layer.features.filter(f=>f.properties.release_id==='P9EC35PF');
  assert.equal(eureka.length,2);
  assert.ok(eureka.every(f=>f.properties.source_file_sha256===
    'c3d17d3361c96e80835120a0d9861a87257336ecbe261c1a7f2abd8f01a0dfcf' &&
    f.properties.fishing_target===false && f.properties.exportable===false &&
    f.properties.depth_qualified===false && f.properties.fish_confirmed===false &&
    f.properties.mpa_screened_at));
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

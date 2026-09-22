import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {geometryIntersects,pointInGeometry,positions} from '../dist/geo-screen.js';

const read=path=>JSON.parse(fs.readFileSync(new URL(path,import.meta.url),'utf8'));
const data=read('../dist/regions/southern-california/survey-habitat.geojson');
const index=read('../dist/regions/southern-california/bottom/index.json');
const closures=['protected-areas.geojson','groundfish-exclusions.geojson'].flatMap(name=>read('../dist/regions/southern-california/'+name).features);

test('island habitat retains real source lineage and never upgrades context to fishing targets',()=>{
  assert.equal(data.region_id,'southern-california');
  assert.ok(data.features.length>30,'A materially useful import exists');
  assert.equal(new Set(data.features.map(f=>f.properties.id)).size,data.features.length);
  for(const feature of data.features){
    const p=feature.properties;
    assert.equal(p.depth_qualified,false);
    assert.equal(p.fishing_target,false);
    assert.equal(p.fishing_export,false);
    assert.equal(p.charter_evidence,false);
    assert.equal(p.catch_evidence,false);
    assert.ok(['rock','sediment','kelp'].includes(p.habitat_kind));
    assert.ok(p.source_id&&p.source_url.startsWith('https://')&&p.source_date);
    assert.ok(pointInGeometry([p.longitude,p.latitude],feature.geometry),'Representative point lies in full feature geometry');
    assert.ok(positions(feature.geometry).every(([lon,lat])=>Number.isFinite(lon)&&Number.isFinite(lat)&&lon>=-121&&lon<=-117.05&&lat>=32.5&&lat<=34.45));
    if(p.habitat_kind!=='kelp')assert.equal(p.depth_screened,true);
    assert.notEqual(p.island,'san-clemente');
  }
  assert.equal(data.summary.fishing_targets,0);
  assert.ok(data.summary.islands.some(i=>i.id==='san-clemente'&&i.coverage_status==='withheld'));
  assert.ok(data.summary.islands.some(i=>i.id==='catalina'&&i.habitat_counts.kelp>0));
});

test('full habitat polygons remain outside every MPA and groundfish exclusion, not just centroids',()=>{
  assert.ok(closures.length>=69);
  for(const feature of data.features){
    for(const closed of closures)assert.equal(geometryIntersects(feature.geometry,closed.geometry),false,feature.properties.id);
  }
});

test('numeric bottom images preserve native cells, blank gaps, unknown datum and source hashes',()=>{
  const available=Object.entries(index.views).filter(([,value])=>value.status==='surveyed');
  assert.ok(available.length>10);
  assert.ok(available.length<=128,'Mobile release has a bounded measured-image budget');
  for(const [id,receipt] of available){
    const bytes=fs.readFileSync(new URL('../dist/'+receipt.path,import.meta.url));
    assert.equal(createHash('sha256').update(bytes).digest('hex'),receipt.sha256);
    const tile=JSON.parse(bytes.toString('utf8'));
    assert.equal(tile.target_id,id);
    assert.equal(tile.region_id,'southern-california');
    assert.equal(tile.depth_qualified,false);
    assert.equal(tile.fishing_target,false);
    assert.equal(tile.producer,'NOAA NCCOS/NCEI');
    assert.match(tile.source_interpolation,/IDW interpolation/);
    assert.equal(tile.vertical_datum,'Unspecified merged hydrographic reference');
    assert.ok([2,4].includes(tile.cell_m));
    assert.equal(tile.cell_m,tile.native_cell_m);
    assert.equal(tile.span_m,tile.cell_m*128);
    const z=Buffer.from(tile.elevations,'base64');
    assert.equal(z.length,129*129*2);
    assert.notEqual(z.readInt16LE((64*129+64)*2),-32768);
    let populated=0;
    for(let i=0;i<z.length;i+=2){const value=z.readInt16LE(i);if(value!==-32768){assert.ok(value<=0);populated++;}}
    assert.ok(Math.abs(populated/(129*129)-tile.coverage_fraction)<.0001);
    const feature=data.features.find(f=>f.properties.id===id);
    assert.equal(feature.properties.bottom_view,true);
    assert.deepEqual(feature.properties.view_depth_range_ft,tile.depth_range_ft);
  }
});

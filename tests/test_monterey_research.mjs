import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateMontereyResearch,montereyResearchPopup} from '../dist/coastal-research-context.js';

const load=path=>JSON.parse(readFileSync(new URL(path,import.meta.url)));

test('original Monterey seabed is visible only as historical research context',()=>{
  const context=load('../dist/data/usgs-offshore-monterey-hard-context.geojson');
  const depth=load('../dist/data/usgs-offshore-monterey-bathy-context-review.json');
  const rows=validateMontereyResearch(context,depth);
  assert.equal(rows.size,88);
  assert.equal(context.features.filter(f=>rows.get(f.properties.id).historical_camera_interior_windows>0).length,5);
  const feature=context.features[0],popup=montereyResearchPopup(feature,rows.get(feature.properties.id));
  assert.match(popup,/below NAVD88/);
  assert.match(popup,/not chart MLLW depth/);
  assert.match(popup,/no fishing rank or export/);
  assert.match(popup,/historical camera windows/);
  assert.throws(()=>validateMontereyResearch({...context,features:context.features.map((f,i)=>i?f:{...f,properties:{...f.properties,fishing_target:true}})},depth));
  assert.throws(()=>validateMontereyResearch(context,{...depth,mllw_conversion_reviewed:true}));
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateMontereyResearch,matchMontereyToStatewide,montereyResearchPopup} from '../dist/coastal-research-context.js';

const load=path=>JSON.parse(readFileSync(new URL(path,import.meta.url)));

test('original Monterey seabed is visible only as historical research context',()=>{
  const context=load('../dist/data/usgs-offshore-monterey-hard-context.geojson');
  const statewide=load('../dist/data/usgs-hard-context-central.geojson');
  const depth=load('../dist/data/usgs-offshore-monterey-bathy-context-review.json');
  const rows=validateMontereyResearch(context,depth);
  const liveRows=matchMontereyToStatewide(statewide,context,depth);
  assert.equal(rows.size,88);
  assert.equal(liveRows.size,88);
  assert.equal(context.features.filter(f=>rows.get(f.properties.id).historical_camera_interior_windows>0).length,5);
  const feature=context.features[0],popup=montereyResearchPopup(feature,rows.get(feature.properties.id));
  assert.match(popup,/below NAVD88/);
  assert.match(popup,/not chart MLLW depth/);
  assert.match(popup,/no fishing rank or export/);
  assert.match(popup,/historical camera windows/);
  assert.throws(()=>validateMontereyResearch({...context,features:context.features.map((f,i)=>i?f:{...f,properties:{...f.properties,fishing_target:true}})},depth));
  assert.throws(()=>validateMontereyResearch(context,{...depth,mllw_conversion_reviewed:true}));
  assert.throws(()=>matchMontereyToStatewide({...statewide,coast_id:'southern'},context,depth));
  const module=readFileSync(new URL('../dist/coastal-discovery-v4.js',import.meta.url),'utf8');
  const boot=readFileSync(new URL('../dist/boot-coastwide-v3.js',import.meta.url),'utf8');
  const html=readFileSync(new URL('../dist/index.html',import.meta.url),'utf8');
  assert.match(module,/matchMontereyToStatewide\(data,/);
  assert.match(boot,/coastal-discovery-v4\.js/);
  assert.match(html,/src="boot-coastwide-v3\.js/);
});

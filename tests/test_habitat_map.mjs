import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {habitatFrame,habitatTileURL,decodeHabitatTile,thermalReference,habitatColor,validHabitatManifest} from '../dist/habitat-data.js';
import {terrainSource,terrainMetricsHTML} from '../dist/terrain-evidence.js';
import {verificationHTML} from '../dist/intelligence.js';
const now=Date.parse('2026-09-22T18:00:00Z'),t=now/1000;
const forecast={status:'ok',kind:'forecast',issued_at:'2026-09-22T03:00:00Z',max_age_hours:36,frames:[{time:t,valid_cells:4},{time:t+10800,valid_cells:4},{time:t+21600,valid_cells:4}]};
test('published manifests preserve their region and reject incomplete rendering contracts',()=>{
  const data=JSON.parse(readFileSync(new URL('../dist/regions/southern-california/habitat-dynamics.json',import.meta.url)));
  assert.ok(validHabitatManifest(data,'southern-california'));
  assert.equal(validHabitatManifest(data,'morro-bay'),false);
  data.layers['sst-analysis'].resolution_degrees=null;assert.equal(validHabitatManifest(data,'southern-california'),false);
});
test('qualified survey cards use their actual native source and ranking method',()=>{
  const atlas=JSON.parse(readFileSync(new URL('../dist/regions/southern-california/atlas.json',import.meta.url)));
  for(const target of atlas.targets){const html=terrainMetricsHTML(target);assert.equal(terrainSource(target).producer,'NOAA/NOS');assert.match(html,/Central 90%/);assert.doesNotMatch(html,/NaN|undefined|0% mapped/);assert.match(html,/not a validated species or catch score/);}
});
test('ocean forecast uses an actual nearby frame, never extrapolates to day seven or fills a missing step',()=>{
  assert.equal(habitatFrame(forecast,t+3600,now).frame.time,t);
  assert.equal(habitatFrame(forecast,t+7*86400,now).frame,null);
  assert.equal(habitatFrame({...forecast,frames:[forecast.frames[0],forecast.frames[2]]},t+10800,now).frame,null);
  assert.equal(habitatFrame(forecast,t,now+37*3600000).frame,null);
});
test('satellite history retains its date for a future trip and does not travel backwards in time',()=>{
  const layer={status:'retained',kind:'analysis',sample_at:new Date(now-48*3600000).toISOString(),max_age_hours:72,frames:[{time:t-48*3600,valid_cells:4}]};
  const out=habitatFrame(layer,t+7*86400,now);assert.equal(out.mode,'observed-context');assert.equal(out.frame.time,t-48*3600);
  assert.equal(habitatFrame(layer,t-72*3600,now).frame,null);assert.equal(habitatFrame(layer,t,now+25*3600000).frame,null);
});
test('tile loading is pinned to region, hash and length; altered samples and path traversal fail',async()=>{
  const tile={schema_version:1,region_id:'morro-bay',layer_id:'sst-analysis',bounds:[-121,35,-120.5,35.5],fields:['latitude','longitude','temperature_c'],resolution_degrees:[.01,.01],frames:[{time:t,cells:[[35.1,-120.7,16]]}]};
  const bytes=new TextEncoder().encode(JSON.stringify(tile)),sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
  const record={path:`habitat-tiles/sst-analysis--242-70-${sha.slice(0,16)}.json`,sha256:sha,bytes:bytes.byteLength,bounds:tile.bounds},base='https://raw.githubusercontent.com/x/y/conditions/regions/morro-bay/habitat-dynamics.json';
  assert.match(habitatTileURL(base,record,'morro-bay'),/regions\/morro-bay\/habitat-tiles/);
  assert.throws(()=>habitatTileURL(base,{...record,path:'../private.json'},'morro-bay'));
  assert.throws(()=>habitatTileURL(base,record,'southern-california'));
  assert.deepEqual(await decodeHabitatTile(bytes,record,'morro-bay','sst-analysis',tile),tile);
  for(const layer of [{...tile,fields:['latitude','longitude','u_mps']},{...tile,resolution_degrees:[.04,.04]},{...tile,frames:[{time:t+10800}]}])await assert.rejects(decodeHabitatTile(bytes,record,'morro-bay','sst-analysis',layer),/parent layer/);
  await assert.rejects(decodeHabitatTile(bytes,{...record,sha256:'0'.repeat(64)},'morro-bay','sst-analysis',tile),/integrity/);
  await assert.rejects(decodeHabitatTile(bytes,record,'southern-california','sst-analysis',tile),/identity/);
});
test('thermal references and missing values never manufacture a catch score',()=>{
  assert.match(thermalReference({temperature_range_c:[12,21]},16),/does not establish fish presence/);
  assert.match(thermalReference({temperature_range_c:[12,21]},24),/Outside/);
  assert.match(thermalReference({},16),/No locally validated/);assert.equal(habitatColor(null,'temperature'),null);
});
test('verification describes a small archive without confusing repeated forecasts with weather hours',()=>{
  const html=verificationHTML({verification:{status:'collecting',archived_forecasts:100,matched_samples:30,summary:{headline:'Collecting local history',matched_valid_times:3,coverage_fraction:.3,next_action:'Collect more days'},groups:[],comparisons:[],limitations:'No automatic correction.'}});
  assert.match(html,/30%/);assert.match(html,/station \/ variable \/ weather hours/);assert.match(html,/Collect more days/);assert.doesNotMatch(html,/NaN|undefined/);
});

test('verification shows provider deferrals without hiding actual collection failures',()=>{
  const html=verificationHTML({verification:{groups:[],collection_deferrals:{'model-gfs_global':{code:'provider_update_settling',reason:'Provider update settling; excluded from archive',retry_at:1790099587}},collection_issues:{'model-example':'<failure>'}}});
  assert.match(html,/Collection gaps & deferred samples/);assert.match(html,/excluded from archive/);assert.match(html,/&lt;failure&gt;/);assert.doesNotMatch(html,/<failure>|\[object Object\]/);
});

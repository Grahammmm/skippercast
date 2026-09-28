import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
import {oceanSearchAreas,nearestSearchForecast,searchWindow} from '../dist/search-plan-data.js';
const region={id:'test',fishing_bounds:[-121,32,-117,35]};
const frame={regionId:'test',layerId:'wcofs-surface-forecast',time:100,step:[.04,.04],fields:['latitude','longitude','temperature_c'],rows:[[33,-120,16],[33,-119.96,17],[33,-119.92,18]]};
test('ocean strips retain contiguous populated cells and never bridge masked water',()=>{
 assert.equal(oceanSearchAreas(frame,{},region).length,1);
 assert.equal(oceanSearchAreas({...frame,rows:[frame.rows[0],frame.rows[2]]},{},region).length,0);
 assert.equal(oceanSearchAreas({...frame,regionId:'wrong'},{},region).length,0);
 const f=oceanSearchAreas(frame,{},region)[0];assert.equal(f.geometry.type,'Polygon');assert.equal(f.properties.exportable,false);
 assert.equal(oceanSearchAreas(frame,{thermal_range_c:[20,25]},region).length,1);
});
test('local forecast matching refuses distant forecasts and missing data stays unrated',()=>{
 assert.equal(nearestSearchForecast({latitude:34,longitude:-120},{kind:'offshore'},[{latitude:35,longitude:-121,offshore:true}]),null);
 assert.equal(searchWindow(null,0,'yellowtail',100).conditions,null);
});
test('every regional target has its own search requirements and explicit unconfirmed fish status',()=>{
 for(const id of ['morro-bay','cambria-san-simeon','southern-california']){
 const r=JSON.parse(fs.readFileSync(`dist/regions/${id}/region.json`)),d=JSON.parse(fs.readFileSync(`dist/regions/${id}/search-plans.json`));
 assert.equal(d.region_id,id);assert.deepEqual(Object.keys(d.profiles).sort(),r.species.slice().sort());
 for(const p of Object.values(d.profiles)){assert.ok(p.presentation.length>40);assert.ok(p.source_links.length);assert.equal(p.numeric_bite_model,false);}
 for(const f of d.features){assert.equal(f.properties.fish_confirmed,false);assert.ok(f.properties.species.every(s=>r.species.includes(s)));}
 }
 const d=JSON.parse(fs.readFileSync('dist/regions/southern-california/search-plans.json'));
 assert.ok(d.features.some(f=>f.properties.species.includes('yellowtail')));
 assert.equal(d.features.some(f=>f.properties.species.includes('spotted-bass')),false);
});
test('offshore envelope, meaningful transitions, uncertainty and clock gates',()=>{
 const offshore={...region,bounds:[-122,32,-117,35],fishing_bounds:[-119,32,-118,35]};
 assert.equal(oceanSearchAreas(frame,{},offshore).length,1);
 assert.equal(oceanSearchAreas({...frame,rows:frame.rows.map(r=>[r[0],r[1],17])},{},region).length,0);
 assert.equal(oceanSearchAreas({...frame,selectedTime:frame.time+7200},{},region).length,0);
 assert.equal(oceanSearchAreas({...frame,step:[0,.04]},{},region).length,0);
 const satellite={...frame,layerId:'sst-analysis',selectedTime:100,fields:[...frame.fields,'analysis_error_c'],rows:frame.rows.map(r=>[...r,.1])};
 assert.equal(oceanSearchAreas(satellite,{},region)[0].properties.search_priority,1);
 assert.equal(oceanSearchAreas({...satellite,selectedTime:100+49*3600},{},region).length,0);
 assert.equal(oceanSearchAreas({...satellite,rows:frame.rows.map(r=>[...r,2])},{},region).length,0);
 assert.equal(oceanSearchAreas({...satellite,rows:frame.rows.map(r=>[...r,null])},{},region).length,0);
});
test('species context and current differences have explicit independent meanings',()=>{
 const flow={...frame,fields:[...frame.fields,'u_mps','v_mps'],rows:frame.rows.map((r,i)=>[...r,i*.1,0])};
 assert.equal(oceanSearchAreas(flow,{},region)[0].properties.search_priority,1);
 assert.equal(oceanSearchAreas(flow,{thermal_range_c:[20,25]},region)[0].properties.search_priority,3);
 assert.equal(oceanSearchAreas(frame,{},region)[0].properties.search_priority,2);
 assert.equal(oceanSearchAreas(flow,{},region)[0].properties.evidence_confidence,'Low');
});

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {setRegion,localContext,pointBundle} from '../dist/region.js?v=8.11';
import {geometryIntersects} from '../dist/geo-screen.js';
import {buildContext} from '../scripts/build_reef_context.mjs';
import {regulationState} from '../dist/regulations.js';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const r=read('regions/southern-california/region.json');
const reef=read('regions/southern-california/reef-records.json');
const mpa=read('dist/'+r.assets.protected_areas),gea=read('dist/'+r.assets.closures);
test('southern contexts isolate San Diego and Santa Barbara tides, buoy and new NWS zones',()=>{
 setRegion(r);assert.equal(localContext('la-jolla').marine_zones.coastal,'PZZ740');
 assert.equal(localContext('santa-barbara').stations.tide,'9411340');
 assert.equal(localContext('la-jolla').stations.tide,'9410170');
 assert.equal(localContext('anacapa').marine_zones.coastal,'PZZ655');
 assert.equal(localContext('san-miguel').marine_zones.coastal,'PZZ673');
 assert.equal(localContext('santa-rosa').marine_zones.offshore,'PZZ673');
 assert.equal(localContext('santa-barbara-island').marine_zones.coastal,'PZZ676');
 for(const focus of r.map.focus_areas)assert.ok(r.forecast_points.some(p=>p.id===focus.forecast_point));
 const b={models:{},contexts:{'san-diego':{tides:[1],alerts:{coastal:['SD alert']}}}};
 assert.deepEqual(pointBundle(b,'santa-barbara').tides,[]);
 assert.deepEqual(pointBundle(b,'santa-barbara').alerts,{});
 assert.deepEqual(pointBundle(b,'la-jolla').tides,[1]);
});
test('historical complex envelopes exclude full MPA/GEA geometry and cannot become ranked or exportable targets',()=>{
 const exclusions={features:[...mpa.features,...gea.features]};const data=buildContext(reef,r,exclusions);
 assert.equal(mpa.features.length,61);assert.equal(gea.features.length,8);assert.equal(data.features.length,16);
 assert.ok(data.withheld.some(x=>x.id==='sca-pacific-beach'));
 for(const f of data.features){assert.equal(f.properties.rank,null);assert.equal(f.properties.exportable,false);assert.equal(f.properties.depth_verified,false);assert.ok(!exclusions.features.some(x=>geometryIntersects(f.geometry,x.geometry)));}
 const atlas=read('dist/'+r.assets.atlas);
 assert.ok(atlas.targets.length>0);
 assert.ok(atlas.targets.every(t=>t.qualification?.full_geometry_screened&&t.rating?.catch_probability===null));
 for(const area of atlas.areas)assert.ok(!exclusions.features.some(x=>geometryIntersects(area.geometry,x.geometry)));
});
test('Southern fall windows never become an unrestricted reef opening even with fresh matching checks',()=>{
 const d=read('dist/'+r.assets.regulations),now=Date.parse('2026-09-22T18:00:00Z');
 for(const [id,s] of Object.entries(d.sources)){s.approved_content_sha256='a'.repeat(64);d.checks[id]={url:s.url,normalization:s.normalization,status:'unchanged',source_status:'ok',content_sha256:s.approved_content_sha256,data_retrieved_at:new Date(now).toISOString()};}
 for(const id of ['lingcod','rockfish','reef']){const state=regulationState(d,id,now,'2026-10-10');assert.equal(state.status,'restricted');assert.match(state.reason,/seaward/);}
 assert.equal(regulationState(d,'halibut',now,'2026-10-10').status,'open');
 d.checks['rules-southern'].status='changed';assert.equal(regulationState(d,'reef',now,'2026-10-10').status,'unknown');
});

test('zero combined-wave period is unavailable rather than a calm sea',async()=>{
 const {readConditions}=await import('../dist/marine-data.js');
 const data={hourly_units:{time:'unixtime',wave_height:'ft',wave_period:'s',wave_direction:'°'},utc_offset_seconds:0,hourly:{time:[1],wave_height:[0],wave_period:[0],wave_direction:[0]}};
 const conditions=readConditions({models:{ncep_gfswave025:{data:[data]}}},0,1);
 assert.equal(conditions.sea.height,null);assert.equal(conditions.sea.period,null);
});

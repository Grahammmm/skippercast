import test from 'node:test';
import assert from 'node:assert/strict';
import {bestSpots as checkedBestSpots,distanceNm,evidenceConfidence,waypointTitle,plotterName} from '../dist/spot-ranking.js';
import {tripGPX} from '../dist/gpx.js';
// These tests cover the other filters: every spot is water here (the land/water check: test_land_water.mjs).
const bestSpots=(atlas,screen,options={})=>checkedBestSpots(atlas,screen,{place:()=>({state:'water'}),...options});
import {loadReefTrip} from '../dist/reef-trip-data.js';
import {buildExport,readDraft,offlineNotes} from '../dist/trip-export.js';
import {gzipSync} from 'node:zlib';
const ring=(x)=>[[x,35],[x+.002,35],[x+.002,35.002],[x,35.002],[x,35]];
const props=id=>({id,region:'morro-bay',tier:2,status:'habitat',exportable:true,screen:{status:'pass'},
  waypoint:{longitude:-120.999,latitude:35.001},source_ids:['survey'],source_year:2008,resolution_m:2,
  metric_support_fraction:.96,interpolation_mask:'unknown',substrate:{known_fraction:1,same_survey_as_depth:true,independent_confirmation:false},
  independent_evidence:[],depth_min_ft:90,depth_max_ft:120,terrain:{score:82,grade:'A',relief_210m_m:12},fit:{lingcod:3,'rockfish-reef':3},area_ha:2});
const screen={ready:()=>true,pointAllowed:()=>true,geometryAllowed:()=>true,exportExclusions:()=>({features:[],checked_at:new Date().toISOString()})};
async function fixture(change=()=>{}){
 const p=props('reef-a'), data={type:'FeatureCollection',region:'morro-bay',expires_at:new Date(Date.now()+86400000).toISOString(),features:[{type:'Feature',properties:p,geometry:{type:'Polygon',coordinates:[ring(-121)]}}]};change(data);
 const bytes=new TextEncoder().encode(JSON.stringify(data));
 const digest=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
 const manifest={region:'morro-bay',status:'ready',archive_sha256:'a'.repeat(64),expires_at:data.expires_at,
  export_file:'habitat-export.geojson',export_sha256:digest,export_bytes:bytes.length};
 const fetchImpl=async url=>String(url).includes('manifest-')?new Response(JSON.stringify(manifest)):new Response(bytes);
 return {data,manifest,fetchImpl};
}
test('evidence index does not reward terrain grade or same-survey duplicates',()=>{
 const p=props('a'),c=evidenceConfidence(p);assert.equal(c.percent,90);
 p.terrain.grade='C';p.terrain.score=1;p.substrate.same_survey_as_depth=false;
 assert.equal(evidenceConfidence(p).percent,90);
 p.independent_evidence=[];p.substrate.independent_confirmation=true;assert.equal(evidenceConfidence(p).percent,90);
 p.metric_support_fraction=null;assert.equal(evidenceConfidence(p),null);
});
test('compressed canonical boundaries retain every coordinate and reject corruption or excessive decoding',async()=>{
 const f=await fixture();f.data.features[0].properties.transport_test_padding='x'.repeat(33*1024*1024);
 const raw=Buffer.from(JSON.stringify(f.data));let compressed=gzipSync(raw);
 const m={...f.manifest,export_file:'habitat-export.geojson.gz',export_bytes:compressed.length,
  export_decoded_bytes:raw.length,export_sha256:Buffer.from(await crypto.subtle.digest('SHA-256',compressed)).toString('hex')};
 const fetchImpl=async url=>String(url).includes('manifest-')?new Response(JSON.stringify(m)):new Response(compressed);
 const atlas=await loadReefTrip('morro-bay',{fetchImpl});
 assert.deepEqual(atlas.areas[0].geometry,f.data.features[0].geometry);
 m.export_decoded_bytes=raw.length-1;await assert.rejects(loadReefTrip('morro-bay',{fetchImpl}),/exceeds/);
 m.export_decoded_bytes=raw.length+1;await assert.rejects(loadReefTrip('morro-bay',{fetchImpl}),/revision changed/);
 m.export_decoded_bytes=129*1024*1024;await assert.rejects(loadReefTrip('morro-bay',{fetchImpl}),/too large/);
 m.export_decoded_bytes=raw.length;m.export_sha256='d'.repeat(64);await assert.rejects(loadReefTrip('morro-bay',{fetchImpl}),/checksum/);
 compressed=compressed.subarray(0,compressed.length-8);m.export_bytes=compressed.length;
 m.export_sha256=Buffer.from(await crypto.subtle.digest('SHA-256',compressed)).toString('hex');
 await assert.rejects(loadReefTrip('morro-bay',{fetchImpl}));
});
test('canonical outlines and interior points load by verified hash; all are re-screened at export',async()=>{
 const f=await fixture(),atlas=await loadReefTrip('morro-bay',f);
 const selected=bestSpots(atlas,screen);assert.equal(selected.length,1);assert.equal(selected[0].trip_fit,3);
 atlas.targets=selected;
 const r=buildExport({atlas,screen,ids:selected.map(t=>t.id),layers:{waypoints:true,outlines:true,alignments:false,exclusions:false},region:{id:'morro-bay',mpa:{bounds:[-122,34,-120,36]}}});
 assert.equal(r.counts.waypoints,1);assert.equal(r.counts.outlines,1);
 assert.match(r.gpx,/<name>01 Reef 90-120ft<\/name>/);
 assert.match(r.gpx,/not a sounding or catch forecast/);assert.doesNotMatch(r.gpx,/<rte>|<name>AVOID|alignment track/);
 assert.deepEqual(r.features.areas[0].geometry,f.data.features[0].geometry);
 assert.throws(()=>buildExport({atlas,screen:{...screen,geometryAllowed:()=>false},ids:['reef-a'],region:{mpa:{bounds:[]}}}),/whole-boundary/);
 atlas.publication.expires_at='2000-01-01';assert.throws(()=>buildExport({atlas,screen,ids:['reef-a'],region:{mpa:{bounds:[]}}}),/expired/);
});
test('producer credits and use restrictions survive canonical loading, GPX and offline notes',async()=>{
 const rights=[{source_id:'survey',attribution:'Original producer <credit>',notice:'Public noncommercial use only; for-profit permission required. Not for navigation.',policy_url:'https://example.org/terms'}];
 const f=await fixture(d=>d.features[0].properties.source_rights=rights);
 f.manifest.source_use_notice='Retain producer terms';
 const atlas=await loadReefTrip('morro-bay',f),region={id:'morro-bay',mpa:{bounds:[-122,34,-120,36]}};
 const r=buildExport({atlas,screen,ids:['reef-a'],layers:{waypoints:true,outlines:true,alignments:false,exclusions:false},region});
 assert.equal(atlas.targets[0].source_rights[0].id,'survey');
 for(const document of [r.gpx,offlineNotes(r,region,{name:'Test day',date:'2026-09-30'})]){
  assert.match(document,/Original producer &lt;credit&gt;/);
  assert.match(document,/for-profit permission required/);
  assert.match(document,/https:\/\/example.org\/terms/);
  assert.doesNotMatch(document,/<credit>/);
 }
 assert.match(atlas.areas[0].extent_note,/for-profit permission required/);
});
test('SCJ-4 ranked waypoint-only GPX (outlines off) keeps producer credits, use terms and policy URL',async()=>{
 const rights=[{source_id:'survey',attribution:'Original producer <credit>',notice:'Public noncommercial use only; for-profit permission required. Not for navigation.',policy_url:'https://example.org/terms'}];
 const f=await fixture(d=>d.features[0].properties.source_rights=rights);
 f.manifest.source_use_notice='Retain producer terms';
 const atlas=await loadReefTrip('morro-bay',f),region={id:'morro-bay',mpa:{bounds:[-122,34,-120,36]}};
 atlas.targets=bestSpots(atlas,screen);assert.equal(atlas.targets[0].trip_rank,1);
 const r=buildExport({atlas,screen,ids:['reef-a'],layers:{waypoints:true,outlines:false,alignments:false,exclusions:false},region});
 assert.equal(r.counts.outlines,0);assert.doesNotMatch(r.gpx,/<trk>/);
 const wpt=r.gpx.match(/<wpt [^>]*>.*?<\/wpt>/)[0];
 assert.match(wpt,/<name>01 Reef 90-120ft<\/name>/);
 assert.match(wpt,/<src>Original producer &lt;credit&gt; Public noncommercial use only; for-profit permission required\. Not for navigation\. https:\/\/example\.org\/terms<\/src>/);
 assert.doesNotMatch(r.gpx,/<credit>/);
 const desc=wpt.match(/<desc>([^<]*)<\/desc>/)[1];
 assert.ok(!desc.includes('\n')&&desc.length<=160&&!desc.includes('producer'),'the waypoint description stays one short line');
});
test('new credited publication rejects absent or partially malformed contributor notices',async()=>{
 for(const value of [undefined,[],[{source_id:'survey',attribution:'Producer'}],
  [{source_id:'survey',attribution:'Producer',notice:'Terms'},{source_id:'other',notice:'Terms'}]]){
  const f=await fixture(d=>d.features[0].properties.source_rights=value);
  f.manifest.source_use_notice='Retain producer terms';
  await assert.rejects(loadReefTrip('morro-bay',f),/credits or use terms/);
 }
});
test('saved canonical selections remain pending for fresh publication restoration',()=>{
 const plan={sha256:'a'.repeat(64),species:'reef',priorities:[{id:'reef-a',rank:1}]};
 const raw=JSON.stringify({ids:['reef-a','unrelated'],rankedPlan:plan});
 const saved=readDraft(raw,{targets:[]},'2026-09-30');
 assert.deepEqual(saved.ids,['reef-a']);assert.deepEqual(saved.rankedPlan,plan);
 assert.deepEqual(readDraft(JSON.stringify({ids:['reef-a'],rankedPlan:{...plan,sha256:'bad'}}),{targets:[]},'2026-09-30').ids,[]);
});
test('wrong region, duplicate, held, exterior point and mismatched bytes cannot enter a plan',async()=>{
 for(const change of [d=>d.region='other',d=>d.features.push(d.features[0]),d=>d.features[0].properties.exportable=false,
  d=>d.features[0].properties.waypoint.longitude=-120]){
   const f=await fixture(change);await assert.rejects(loadReefTrip('morro-bay',f));
 }
 const f=await fixture();f.manifest.export_sha256='b'.repeat(64);await assert.rejects(loadReefTrip('morro-bay',f),/checksum/);
});
test('top set enforces depth, whole boundaries, distinct reefs, count and combined weaker fit',async()=>{
 const f=await fixture(),atlas=await loadReefTrip('morro-bay',f),base=atlas.targets[0];
 atlas.targets=Array.from({length:25},(_,i)=>({...base,id:'r'+i,longitude:-121-i*.01,area_ids:['r'+i],habitat_score:100-i,
  species_fit:{lingcod:3,'rockfish-reef':i===0?2:3}}));
 atlas.areas=atlas.targets.map(t=>({id:t.id,geometry:{type:'Polygon',coordinates:[ring(t.longitude)]}}));
 const ranked=bestSpots(atlas,screen,{count:20});assert.equal(ranked.length,20);assert.equal(ranked[0].id,'r1');
 assert.equal(ranked.at(-1).trip_rank,20);assert.ok(ranked.every(t=>t.name.includes('C90%')));
 atlas.targets[1].neighborhood_depth_ft=[290,310];assert.ok(!bestSpots(atlas,screen).some(t=>t.id==='r1'));
 assert.equal(bestSpots(atlas,{...screen,geometryAllowed:()=>false}).length,0);
 assert.throws(()=>bestSpots(atlas,{...screen,ready:()=>false}),/Refresh/);
 const near={...base,id:'near',area_ids:['r0'],longitude:atlas.targets[0].longitude};atlas.targets.push(near);
 assert.equal(new Set(bestSpots(atlas,screen,{count:50}).flatMap(t=>t.area_ids)).size,bestSpots(atlas,screen,{count:50}).length);
 assert.equal(bestSpots(atlas,screen,{origin:{latitude:35,longitude:-121},maxDistanceNm:.01}).length,0);
});
test('titles retain leading priority and confidence for plotters with shorter labels',()=>{
 assert.equal(waypointTitle({trip_fit:3,trip_species:'lingcod',neighborhood_depth_ft:[100.1,199.9],evidence_confidence:{percent:85}},2),'02 LC H3 C85% 100-200ft');
});
test('SCJ-4 plotter names: target word per species, whole feet, two-digit priority',()=>{
 const t={trip_species:'reef',trip_rank:1,neighborhood_depth_ft:[199.6,278.4]};
 assert.equal(plotterName(t),'01 Reef 200-278ft');
 assert.equal(plotterName({...t,trip_species:'lingcod'},12),'12 Lingcod 200-278ft');
 assert.equal(plotterName({...t,trip_species:'rockfish',neighborhood_depth_ft:[90.49,120.5]}),'01 Rockfish 90-121ft');
 assert.ok(plotterName({...t,trip_species:'reef'},12).length<=20);
});
test('SCJ-4 ranked GPX waypoint: short name, one-line desc, SC26 id kept; other waypoints export as before',async()=>{
 const f=await fixture(d=>d.features[0].properties.id='SC26-test-0001'),atlas=await loadReefTrip('morro-bay',f);
 for(const species of ['reef','lingcod','rockfish']){
  const [t]=bestSpots(atlas,screen,{species});t.neighborhood_depth_ft=[89.62345678901234,120.4999999999999];
  const gpx=tripGPX({...atlas,targets:[t]},[t.id],'x',{outlines:false,alignments:false});
  const name=gpx.match(/<wpt [^>]*><name>([^<]*)<\/name>/)[1],desc=gpx.match(/<wpt [^>]*>.*?<desc>([^<]*)<\/desc>/)[1];
  assert.match(name,/^\d{2} (Lingcod|Rockfish|Reef) \d+-\d+ft$/);assert.equal(name,plotterName(t));
  assert.match(desc,/habitat, about 90–120 ft\./);assert.ok(!desc.includes('\n')&&desc.length<=160,desc);
  assert.doesNotMatch(desc,/\d\.\d{2}|C90%|habitat-evidence|nominal/);
  assert.match(gpx,/<cmt>SC26-test-0001<\/cmt>/);assert.equal(t.name,waypointTitle(t),'the Chart keeps its heading');
 }
 const plain=atlas.targets[0],gpx=tripGPX(atlas,[plain.id],'x',{outlines:false,alignments:false});
 assert.ok(gpx.includes(`<name>${plain.name}</name>`)&&gpx.includes('Trip priority unassigned')&&gpx.includes('nominal'),'a non-ranked target keeps its full notes');
 const user={id:'u1',name:'My spot',latitude:35,longitude:-121,category:'user',user_waypoint:true,trip_rank:1,trip_species:'reef'};
 assert.ok(tripGPX({...atlas,targets:[user]},['u1'],'x',{outlines:false,alignments:false}).includes('<name>My spot</name><cmt>u1</cmt><desc>User waypoint. User-supplied label;'),'a user waypoint is unchanged');
 const odd={...bestSpots(atlas,screen)[0],trip_species:'tuna'};
 assert.ok(tripGPX({...atlas,targets:[odd]},[odd.id],'x',{outlines:false,alignments:false}).includes(`<name>${odd.name}</name>`),'an unknown target word falls back to the full name');
});
// SC2207-04: the optional `distanceFor` decides the range by the caller's own (water) distance. Synthetic reefs due north of ORIGIN.
const ORIGIN={latitude:35,longitude:-121}, north=nm=>ORIGIN.latitude+nm/60;
const reef=(id,nm,area,score,extra={})=>({id,canonical_habitat:true,latitude:north(nm),longitude:-121,habitat_score:score,neighborhood_depth_ft:[90,120],resolution_m:2,
  evidence_confidence:{percent:90},species_fit:{lingcod:3,'rockfish-reef':3},area_ids:[area],...extra});
const synth=(...targets)=>({targets,areas:[...new Set(targets.flatMap(t=>t.area_ids))].map(id=>({id,geometry:{}}))});
const viaTable=(table,calls=[])=>(t,straight)=>{calls.push(t.id);const v=table[t.id];return typeof v==='function'?v(straight):v;};
test('SC2207-04 unused option: the result is the same bytes with and without it, and no origin never asks',()=>{
 const atlas=synth(reef('a',3,'A',90),reef('b',5,'B',89),reef('c',12,'C',88)), plain=bestSpots(atlas,screen,{origin:ORIGIN,maxDistanceNm:10});
 assert.deepEqual(plain.map(t=>t.id),['a','b']);assert.ok(plain.every(t=>!('distance_basis' in t)&&!('distance_why' in t)&&t.distance_nm===distanceNm(ORIGIN,t)));
 const same=bestSpots(atlas,screen,{origin:ORIGIN,maxDistanceNm:10,distanceFor:null});
 assert.ok(JSON.stringify(same)===JSON.stringify(plain),'distanceFor: null leaves the answer byte for byte');
 const calls=[],none=bestSpots(atlas,screen,{distanceFor:viaTable({a:{nm:1,basis:'water'}},calls)});
 assert.ok(calls.length===0&&none.length===3&&none.every(t=>t.distance_nm===null&&!('distance_basis' in t)),'no origin: the callback is never called');
});
test('SC2207-04 a distance rejected by the callback reserves neither its area nor a separation position',()=>{
 // A: 9 nm straight but 13 nm by water (range 10). B shares A's area; C lies 0.1 nm past A, far from B.
 const atlas=synth(reef('A',9,'X',90),reef('B',7,'X',89),reef('C',9.1,'Y',88)), calls=[];
 const got=bestSpots(atlas,screen,{origin:ORIGIN,maxDistanceNm:10,distanceFor:viaTable({A:{nm:13,basis:'water'},B:s=>({nm:s,basis:'water'}),C:s=>({nm:s,basis:'straight'})},calls)});
 assert.deepEqual(got.map(t=>[t.id,t.trip_rank]),[['B',1],['C',2]],'ranks are contiguous over the kept reefs');
 assert.ok(got[0].name.startsWith('01 ')&&got[1].name.startsWith('02 '));
 assert.deepEqual(calls,['A','B','C']);
 // Separation stays straight-line against reefs KEPT: D 0.1 nm past B is excluded; at the exact boundary it is kept.
 const near=synth(reef('B',7,'X',90),reef('D',7.1,'Z',89)), ok=s=>({nm:s,basis:'water'});
 assert.deepEqual(bestSpots(near,screen,{origin:ORIGIN,distanceFor:viaTable({B:ok,D:ok})}).map(t=>t.id),['B']);
 const gap=distanceNm(near.targets[0],near.targets[1]);
 assert.deepEqual(bestSpots(near,screen,{origin:ORIGIN,minSeparationNm:gap,distanceFor:viaTable({B:ok,D:ok})}).map(t=>t.id),['B','D']);
 // The callback is not asked about a spot that fails the area or separation check (nothing to route).
 const asked=[];bestSpots(near,screen,{origin:ORIGIN,distanceFor:viaTable({B:ok,D:ok},asked)});assert.deepEqual(asked,['B']);
});
test('SC2207-04 range is inclusive and cheap filters come before the callback',()=>{
 const water=nm=>({nm,basis:'water'});
 const atlas=synth(reef('exact',4,'A',90),reef('over',5,'B',89),reef('far',11,'C',88),reef('deep',6,'D',87,{neighborhood_depth_ft:[90,400]}),
   reef('outside',7,'E',86,{longitude:-120.5}),reef('land',8,'F',85),reef('held',2,'G',84),reef('later',3,'H',83)), calls=[], stats={};
 const got=bestSpots(atlas,{...screen,pointAllowed:t=>t.id!=='held'},{origin:ORIGIN,maxDistanceNm:10,bounds:[-121.1,34,-120.9,36],stats,place:t=>({state:t.id==='land'?'unknown':'water'}),
   distanceFor:viaTable({exact:water(10),over:water(10.0001),later:water(9.99)},calls)});
 assert.deepEqual(got.map(t=>t.id),['exact','later']);assert.equal(got[0].distance_nm,10,'unrounded, inclusive');
 assert.deepEqual(calls,['exact','over','later'],'out of straight range, too deep, outside the map, non-water and screen-held reefs are never asked');
 assert.equal(stats.withheld,1,'only the land/water withholding is counted');
});
test('SC2207-04 callback answers: null rejects, metadata is kept, invalid answers throw',()=>{
 const atlas=synth(reef('a',3,'A',90),reef('b',4,'B',89)), run=answer=>bestSpots(atlas,screen,{origin:ORIGIN,distanceFor:()=>answer});
 assert.deepEqual(run(null),[]);
 const [kept]=run({nm:3.5,basis:'straight',why:'no-route'});
 assert.deepEqual([kept.distance_nm,kept.distance_basis,kept.distance_why],[3.5,'straight','no-route']);
 const [water]=run({nm:4,basis:'water'});assert.ok(water.distance_nm===4&&water.distance_basis==='water'&&!('distance_why' in water));
 for(const bad of [{nm:NaN,basis:'water'},{nm:Infinity,basis:'water'},{nm:-1,basis:'water'},{nm:'3',basis:'water'},{nm:3,basis:'air'},{nm:3},{basis:'water'},undefined,'water'])
  assert.throws(()=>run(bad),/^Error: Invalid trip distance\.$/,String(JSON.stringify(bad)));
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {bestSpots,evidenceConfidence,waypointTitle} from '../dist/spot-ranking.js';
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
 assert.match(r.gpx,/<name>01 LR H3 C90% 90-120ft<\/name>/);
 assert.match(r.gpx,/not catch odds/);assert.doesNotMatch(r.gpx,/<rte>|<name>AVOID|alignment track/);
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

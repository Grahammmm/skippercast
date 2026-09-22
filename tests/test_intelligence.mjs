import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {memberSummary,currentFrame,nearestCurrent,spectrumSVG,uncertaintyHTML} from '../dist/intelligence.js';
import {getRegion} from '../dist/region.js?v=8.2';
import {tripGPX} from '../dist/gpx.js';
import {exportSelection} from '../dist/inavx.js';
import {bottomSection} from '../dist/bottom-view.js';
import {regulationState} from '../dist/regulations.js';
import {spotEvidence} from '../dist/spot-evidence.js';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
const now=Date.parse('2026-09-22T04:00:00Z');

test('uncertainty requires both stable point ID and requested coordinates after a region edit',()=>{
  const point=getRegion().forecast_points[0],time=Math.floor(Date.now()/1000);
  const identity={point_id:point.id,requested:[point.latitude,point.longitude]};
  const row={...identity,frames:[{time,members:Array.from({length:31},(_,i)=>[i,6,8])}]};
  const waveRow={...identity,percent:75,grid:[point.latitude,point.longitude],distance_km:0};
  const fresh=data=>({status:'ok',max_age_hours:36,data:{issued_at:new Date().toISOString(),...data}});
  const data={sources:{ensemble:fresh({points:[row]}),'wave-ensemble':fresh({frames:[{time,threshold_m:1,points:[waveRow]}]})}};
  assert.match(uncertaintyHTML(data,{point:0,time}),/6\.0–6\.0 kt/);
  assert.match(uncertaintyHTML(data,{point:0,time}),/75%/);
  row.requested=[point.latitude+.1,point.longitude];waveRow.requested=row.requested;
  const moved=uncertaintyHTML(data,{point:0,time});
  assert.match(moved,/Unavailable/);assert.doesNotMatch(moved,/6\.0–6\.0 kt|75%/);
  delete row.requested;delete waveRow.requested;
  assert.doesNotMatch(uncertaintyHTML(data,{point:0,time}),/6\.0–6\.0 kt|75%/);
});

test('ensemble counts exclude missing and inconsistent gusts without claiming confidence from few members',()=>{
  const members=Array.from({length:31},(_,i)=>[i,i===0?0:10,i===0?0:14]);
  members[1][2]=5;members[2][2]=null;
  const s=memberSummary(members);assert.equal(s.n,31);assert.equal(s.gustN,29);assert.equal(s.windPercent,30/31*100);
  assert.equal(memberSummary(members.slice(0,19)).windPercent,null);
  assert.equal(memberSummary([[1,0,0]]).p50,0);
});
test('observed current never turns into a future forecast; distant samples and stale sources are rejected',()=>{
  const source={status:'ok',max_age_hours:6,data:{kind:'observation',sample_at:new Date(now-3600000).toISOString(),resolution_km:1,frames:[{time:now/1000-3600,cells:[[35,-121,0,0]]}]}};
  assert.ok(currentFrame(source,now/1000,now));assert.equal(currentFrame(source,now/1000+7200,now),null);
  assert.equal(nearestCurrent(source,now/1000,{latitude:35.5,longitude:-121},now),null);
  source.status='retained';assert.equal(currentFrame(source,now/1000,now),null);
  source.status='ok';source.data={...source.data,kind:'forecast',valid_from:now/1000,valid_through:now/1000+72*3600};
  assert.equal(currentFrame(source,now/1000+73*3600,now),null);
});
test('wave diagram rejects invalid frequencies, density and directions and labels measured energy',()=>{
  const svg=spectrumSVG({bins:[[.1,2,270],[0,8,100],[.2,-1,30],[.15,2,999]]});
  assert.match(svg,/10\.0 s/);assert.equal((svg.match(/<title>/g)||[]).length,1);assert.doesNotMatch(svg,/NaN|Infinity/);
});
test('trip export deduplicates points and shared geometry, retains holes, and rechecks full MPA geometry',()=>{
  const atlas=read('../dist/data/atlas.json'),ids=atlas.targets.slice(0,3).map(t=>t.id);
  const output=tripGPX(atlas,[...ids,ids[0]]);assert.equal((output.match(/<wpt /g)||[]).length,3);
  const names=[...output.matchAll(/<trk><name>([^<]+)/g)].map(m=>m[1]);assert.equal(new Set(names).size,names.length);
  assert.match(output,/<cmt>SC26-/);assert.doesNotMatch(output,/<rte>/);
  const screen={ready:()=>true,pointAllowed:()=>true,geometryAllowed:()=>false};
  assert.throws(()=>exportSelection(atlas,screen,ids),/full outline/);
  screen.geometryAllowed=()=>true;assert.match(exportSelection(atlas,screen,ids),/<gpx/);
  screen.ready=()=>false;assert.throws(()=>exportSelection(atlas,screen,ids),/protected-area/);
});
test('native bottom cross-sections retain nodata and meter-to-foot scale at cardinal and diagonal headings',()=>{
  const tile=read('../dist/regions/morro-bay/bottom/SC26-001.json');
  const bytes=Buffer.alloc(129*129*2);for(let i=0;i<129*129;i++)bytes.writeInt16LE(-100,i*2);bytes.writeInt16LE(-32768,(64*129+64)*2);
  const data={...tile,elevations:bytes.toString('base64')};
  for(const bearing of [0,90,45,179]){const s=bottomSection(data,bearing);assert.equal(s[64].depth_ft,null);assert.ok(s.every(p=>p.depth_ft===null||Math.abs(p.depth_ft-32.8084)<.001));assert.ok(s.at(-1).distance_ft>=256*3.2808);}
});
test('trip-date rules use the selected season while source freshness stays tied to now',()=>{
  const r=read('../dist/data/regulations.json');r.reviewed_at=new Date(now-3600000).toISOString();
  for(const id of Object.keys(r.sources)){r.sources[id].approved_content_sha256='a'.repeat(64);r.checks[id]={status:'unchanged',source_status:'ok',content_sha256:'a'.repeat(64),data_retrieved_at:new Date(now-3600000).toISOString()};}
  r.species.dungeness.windows=[{start:'2026-10-01',end:'2026-11-30'}];
  assert.equal(regulationState(r,'dungeness',now,'2026-10-15','hoop').status,'open');
  assert.equal(regulationState(r,'dungeness',now,'2026-10-15','trap').status,'scheduled');
  assert.equal(regulationState(r,'dungeness',now,'2026-09-22','hoop').status,'closed');
  assert.equal(regulationState(r,'dungeness',now+40*3600000,'2026-10-15','hoop').status,'unknown');
});
test('spot evidence keeps physical structure separate from fish and AIS proof',()=>{
  const r=read('../regions/morro-bay/region.json'),a=read('../dist/data/atlas.json');
  const e=spotEvidence(a.targets[0],'reef',{habitat:'Reviewed reef hypothesis'},r);
  assert.ok(e.measured.length);assert.ok(e.inferred.some(s=>s.includes('not a species or catch score')));assert.ok(e.unknown.some(s=>s.includes('camera')));
});

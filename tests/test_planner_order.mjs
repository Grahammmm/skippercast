import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {createPlanner, shorterRunOrder} from '../web/planner.ts';
import {distanceNm} from '../dist/spot-ranking.js';
import {draftKey} from '../dist/trip-export.js';
import {tripLegs} from '../web/trip-legs.ts';
import {launchPoints} from '../web/launches.ts';
import {session} from '../web/account.ts';
import {region as activeRegion} from '../web/state.ts';
import {getRegion} from '../dist/region.js';
const eq = (a,b) => assert.ok(isDeepStrictEqual(a,b), `expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
const region = getRegion(), now = new Date('2026-11-09T18:00:00Z');
const screen = {ready:()=>true, pointAllowed:()=>true, geometryAllowed:()=>true, coversGeometry:()=>true, exportExclusions:()=>({features:[],checked_at:now.toISOString()})};
const map = {getSize:()=>({x:512,y:512}),getBounds:()=>({getWest:()=>-125,getEast:()=>-115,getSouth:()=>30,getNorth:()=>40,contains:()=>true})};
const point = (id,n) => ({id,label:id,name:id,latitude:35+n/100,longitude:-121,habitat_grade:'A',canonical_habitat:true,neighborhood_depth_ft:[90,120],species_fit:{lingcod:3,'rockfish-reef':3},habitat_score:90-n,resolution_m:2,evidence_confidence:{percent:90},area_ids:[`area-${id}`]});
const publication = {export_sha256:'a'.repeat(64),status:'ready',expires_at:'2099-12-31T00:00:00Z',region:region.id};
const reefs = {targets:[point('A',1),point('B',3),point('C',4)],areas:['A','B','C'].map((id,i)=>({id:`area-${id}`,target_ids:[id],geometry:{type:'Polygon',coordinates:[[[-121,35+i/100],[-120.999,35+i/100],[-120.999,35.001+i/100],[-121,35+i/100]]]}})),publication};
const wp = {id:'user:W',name:'W',category:'other',latitude:35.02,longitude:-121};
function make({raw,blocked=false,loadReefs=async()=>reefs,water=()=>({state:'water'}),ports=[]}={}) {
  const store=new Map(raw?[[draftKey(region.id),raw]]:[]), calls=[], emitted=[];
  const p=createPlanner({atlas:{targets:[],areas:[]},region,screen,map,getVisible:()=>[],now:()=>now,landWater:async()=>water,loadReefs,loadPorts:async()=>({ports}),emit:d=>emitted.push(d),
    storage:{getItem:k=>store.get(k)??null,setItem:(k,v)=>{if(blocked)throw Error('blocked');store.set(k,v);}},nav:{open(){},showMap(){},conditions(){}},
    alertSettings:()=>({profile:'boat',ownBoatLimits:false,limits:{wind:12,gust:18,seas:4},factors:{wind:1,sea:1,custom:false},boat:null}),
    alertFetch:async(url,init)=>{calls.push(JSON.parse(init.body));return {ok:true,status:201,json:async()=>({id:'trip-1'})};}});
  return {p,store,calls,emitted,raw:()=>store.get(draftKey(region.id))};
}
const select=async h=>{await h.p.selectBest();assert.equal(h.p.ranked.value,true,h.p.scopeStatus.value);};
const stops=p=>p.orderedStops.value.map(t=>({id:t.id,name:t.name||t.label,lat:t.latitude,lon:t.longitude}));
const legs = s=>tripLegs(null,s,12,(a,b)=>({ok:true,nm:Math.round((a.latitude-35)*100)*10+Math.round((b.latitude-35)*100),points:[]}));

test('adjacent swaps, ends, unknown, singleton, pending restore, blocked storage and stale ranking',async()=>{
 const h=make({blocked:true}); const p=h.p;
 try {
  assert.equal(p.moveStop('A','up'),false);
  p.toggleSpot('A',true); assert.equal(p.moveStop('A','down'),false);
  p.toggleSpot('B',true);p.toggleSpot('C',true);
  const before=p.draft.value;
  for(const [id,dir] of [['A','up'],['C','down'],['missing','up'],['user:launch-r','up']])assert.equal(p.moveStop(id,dir),false);
  assert.equal(p.draft.value,before);
  p.restorePending.value=true;assert.equal(p.moveStop('B','up'),false);p.restorePending.value=false;
  assert.equal(p.moveStop('B','up'),true);eq(p.draft.value.ids,['B','A','C']);
  assert.equal(p.moveStop('B','down'),true);eq(p.draft.value.ids,['A','B','C']);
  assert.match(p.storageNote.value,/unavailable/);
 } finally {p.dispose();}
 let release;const slow=make({loadReefs:()=>new Promise(r=>release=r)});
 slow.p.toggleSpot('A',true);slow.p.toggleSpot('B',true);
 const pending=slow.p.selectBest();await new Promise(r=>setTimeout(r,0));
 slow.p.moveStop('B','up');release(reefs);await pending;
 eq(slow.p.draft.value.ids,['B','A']);assert.equal(slow.p.ranked.value,false);slow.p.dispose();
});

test('manual ranked provenance survives two restores without rank claims; legacy and fresh rank; guards retained',async()=>{
 let h=make();await select(h);const legacy=h.raw();
 h.p.moveStop('B','up');eq(h.p.draft.value.ids,['B','A','C']);
 assert.equal(h.p.draft.value.rankedPlan.manualOrder,true);assert.equal(h.p.ranked.value,false);
 eq(h.emitted.at(-1).targets,[]);
 for(let i=0;i<2;i++){
  const raw=h.raw();h.p.dispose();h=make({raw});
  assert.equal(h.p.moveStop('A','up'),false);await h.p.restore();
  eq(h.p.draft.value.ids,['B','A','C']);assert.equal(h.p.ranked.value,false);
  assert.equal(h.p.scopeStatus.value,'Your own stop order.');
  for(const t of h.p.orderedStops.value){assert.equal(t.trip_rank,undefined);assert.equal(t.trip_fit,undefined);assert.equal(t.trip_species,undefined);assert.equal(t.distance_nm,undefined);assert.equal(t.name,t.label);assert.equal(t.canonical_habitat,true);}
  assert.doesNotMatch(await(await h.p.exportFile('gpx')).text(),/priority [123]/i);
 }
 await select(h);assert.equal(h.p.draft.value.rankedPlan.manualOrder,undefined);h.p.dispose();
 const old=make({raw:legacy});await old.p.restore();assert.equal(old.p.ranked.value,true);old.p.dispose();
 for(const opts of [{loadReefs:async()=>({...reefs,publication:{...publication,export_sha256:'b'.repeat(64)}})},{water:()=>({state:'land'})}]){
  const bad=make({raw:legacy,...opts});await bad.p.restore();assert.equal(bad.p.restorePending.value,true);assert.equal(bad.p.moveStop('B','up'),false);await assert.rejects(bad.p.exportFile('gpx'));bad.p.dispose();
 }
});

test('mixed ordered projection drives legs/totals, GPX and ordinary notes with launch last',async()=>{
 const h=make();await select(h);const p=h.p;
 try {
  p.setLayer('outlines',false);p.draft.value={...p.draft.value,ids:['A','user:W','B'],userWaypoints:[wp]};
  launchPoints.value={region:region.id,points:[{id:'r',name:'Ramp',latitude:35.05,longitude:-121}]};p.setLaunch(true);
  eq(p.orderedStops.value.map(t=>t.id),['A','user:W','B','user:launch-r']);
  let r=legs(stops(p));eq(r.legs.map(l=>[l.from,l.to]),[[p.orderedStops.value[0].name,'W'],['W',p.orderedStops.value[2].name],[p.orderedStops.value[2].name,'Launch · Ramp']]);assert.equal(r.totalNm,70);assert.equal(r.totalRunMin,350);
  p.moveStop('user:W','up');eq(p.orderedStops.value.map(t=>t.id),['user:W','A','B','user:launch-r']);
  r=legs(stops(p));assert.equal(r.totalNm,69);assert.equal(r.totalRunMin,345);
  const noSpeed=tripLegs(null,stops(p),null);assert.equal(noSpeed.totalRunMin,null);
  const port=tripLegs({name:'Port',lat:35,lon:-121},stops(p),12);assert.equal(port.legs[0].from,'Port');assert.equal(port.legs.at(-1).to,'Port');
  const gpx=await(await p.exportFile('gpx')).text(),notes=await(await p.exportFile('notes')).text();
  const names=[...gpx.matchAll(/<wpt\b[\s\S]*?<name>(.*?)<\/name>/g)].map(m=>m[1]);
  eq(names,['W','A','B','Launch · Ramp']);
  let last=-1;for(const name of ['W','A · A','B · B','Launch · Ramp']){const at=notes.indexOf(`<h2>${name}`);assert.ok(at>last,`${name} in notes order`);last=at;}
  assert.equal(p.moveStop('user:launch-r','up'),false);
 }finally{p.dispose();launchPoints.value=null;}
});

test('alert preview and explicit snapshots follow moves; no implicit send, duplicate and publication-race refused',async()=>{
 const h=make();activeRegion.value=region.id;session.value={state:'signed-in',name:'Synthetic'};await select(h);const p=h.p;
 try{
  p.setAlertOpen(true);p.moveStop('B','up');assert.equal(h.calls.length,0);
  let preview=p.alertPreview(legs);assert.equal(preview.ok,true,preview.message);eq(preview.preview.legList.map(l=>[l.from,l.to]),[['B','A'],['A','C']]);
  await p.saveAlert(legs);assert.equal(h.calls.length,1);eq(h.calls[0].plan.spots.map(s=>s.name),['B','A','C']);
  await p.saveAlert(legs);assert.equal(h.calls.length,1);
  p.moveStop('C','up');await p.saveAlert(legs);assert.equal(h.calls.length,2);eq(h.calls[0].plan.spots.map(s=>s.name),['B','A','C']);eq(h.calls[1].plan.spots.map(s=>s.name),['B','C','A']);
 }finally{p.dispose();}
 const releases=[];let hold=false;const race=make({loadReefs:()=>hold?new Promise(r=>releases.push(r)):Promise.resolve(reefs)});await select(race);race.p.setAlertOpen(true);await new Promise(r=>setTimeout(r,0));hold=true;
 const saving=race.p.saveAlert(legs);race.p.moveStop('B','up');hold=false;for(const release of releases)release(reefs);await saving;assert.equal(race.calls.length,0);assert.match(race.p.alertStatus.value,/changed/i);race.p.dispose();session.value={state:'loading'};activeRegion.value=null;
});

// SC2052-09. Protects: shorterRunOrder improves a zigzag rank order, keeps the anchors, never adds/drops a stop, leaves ties and optimal orders alone.
// Fails if it reorders on a tie, returns a longer order, drops a stop, or moves the pinned first stop or an anchor.
const S=Object.fromEntries([5,1,4,2,3,0].map((o,i)=>[`S${i+1}`,{id:`S${i+1}`,latitude:35+o/10,longitude:-121}])), rank=Object.values(S);
const total=(order,{start,end}={})=>[start,...order,end].filter(Boolean).reduce((sum,p,i,all)=>i?sum+distanceNm(all[i-1],p):0,0);
const idsOf=r=>r.ids.join(',');
test('shorterRunOrder: six-stop zigzag beats rank order; first stop pinned, launch/return anchors fixed, same stops',()=>{
 const r=shorterRunOrder(rank);
 assert.equal(idsOf(r),'S1,S3,S5,S4,S2,S6');assert.equal(r.changed,true);
 const byId=r.ids.map(id=>S[id]);assert.ok(Math.abs(total(byId)-r.afterNm)<1e-9&&Math.abs(total(rank)-r.beforeNm)<1e-9&&r.afterNm<r.beforeNm/2,'independent sums');
 eq([...r.ids].sort(),rank.map(s=>s.id).sort());
 const port={latitude:35,longitude:-121};
 assert.equal(idsOf(shorterRunOrder(rank,{start:port})),'S6,S2,S4,S5,S3,S1');
 const ramp=shorterRunOrder(rank,{end:port});assert.equal(idsOf(ramp),'S1,S3,S5,S4,S2,S6');assert.ok(total(ramp.ids.map(id=>S[id]),{end:port})<total(rank,{end:port}));
 const loop=shorterRunOrder(rank,{start:port,end:port});assert.equal(loop.changed,true);assert.ok(Math.abs(total(loop.ids.map(id=>S[id]),{start:port,end:port})-loop.afterNm)<1e-9&&loop.afterNm<loop.beforeNm);
});
test('shorterRunOrder: ties and an already-shortest order stay exactly as they are',()=>{
 const A=at('A',35.1),B=at('B',34.9),from={latitude:35,longitude:-121};
 for(const order of [[A,B],[B,A]]){const r=shorterRunOrder(order,{start:from});assert.equal(r.changed,false);eq(r.ids,order.map(s=>s.id));}
 const best=shorterRunOrder(rank),again=shorterRunOrder(best.ids.map(id=>S[id]));
 assert.equal(again.changed,false);eq(again.ids,best.ids);assert.equal(again.afterNm,again.beforeNm);
 for(const few of [[],[S.S1]])assert.equal(shorterRunOrder(few).changed,false);
});
function at(id,latitude){return {id,latitude,longitude:-121};}

// Protects: the planner button only reorders when called, commits through the manual-order path (manualOrder, status, persisted, legs/alert/notes follow),
// and a refusal or a repeat changes nothing. Fails if it runs on its own, drops the rank claim wrongly, loses the order on reload or touches a refused plan.
const lat={A:1,B:9,C:2,D:8,E:3},zig=ids=>({targets:ids.map((id,i)=>({...point(id,i+1),latitude:35+lat[id]/100})),areas:ids.map((id,i)=>({id:`area-${id}`,target_ids:[id],geometry:{type:'Polygon',coordinates:[[[-121,35+i/100],[-120.999,35+i/100],[-120.999,35.001+i/100],[-121,35+i/100]]]}})),publication});
const straight=s=>tripLegs(null,s,12);
test('shortenRun: tap only; persists as manualOrder; legs, alert preview and notes follow; repeat, restore and unknown stop change nothing',async()=>{
 const h=make({loadReefs:async()=>zig(['A','B','C','D','E'])});activeRegion.value=region.id;session.value={state:'signed-in',name:'Synthetic'};await select(h);const p=h.p;
 try{
  eq(p.draft.value.ids,['A','B','C','D','E']);const was=straight(stops(p)).totalNm;
  assert.equal(p.shortenRun(),'moved');eq(p.draft.value.ids,['A','C','E','D','B']);
  assert.equal(p.draft.value.rankedPlan.manualOrder,true);assert.equal(p.ranked.value,false);assert.equal(p.scopeStatus.value,'Your own stop order.');
  assert.ok(straight(stops(p)).totalNm<was);
  const reload=make({raw:h.raw(),loadReefs:async()=>zig(['A','B','C','D','E'])});await reload.p.restore();eq(reload.p.draft.value.ids,['A','C','E','D','B']);assert.equal(reload.p.scopeStatus.value,'Your own stop order.');reload.p.dispose();
  p.setAlertOpen(true);const preview=p.alertPreview(s=>straight(s));assert.equal(preview.ok,true,preview.message);eq(preview.preview.legList.map(l=>[l.from,l.to]),[['A','C'],['C','E'],['E','D'],['D','B']]);
  const notes=await(await p.exportFile('notes')).text();let last=-1;for(const n of ['A','C','E','D','B']){const i=notes.indexOf(`<h2>${n} · ${n}`);assert.ok(i>last,`${n} in notes order`);last=i;}
  const settled=p.draft.value;assert.equal(p.shortenRun(),'same');assert.equal(p.draft.value,settled);
  p.restorePending.value=true;p.draft.value={...settled,ids:['B','A','C','D','E']};const queued=p.draft.value;assert.equal(p.shortenRun(),'refused');assert.equal(p.draft.value,queued);p.restorePending.value=false;
  p.draft.value={...queued,ids:['B','A','ghost']};const unknown=p.draft.value;assert.equal(p.shortenRun(),'refused');assert.equal(p.draft.value,unknown);assert.equal(h.calls.length,0);
 }finally{p.dispose();session.value={state:'loading'};activeRegion.value=null;}
});
test('shortenRun: home port starts the legs and the launch ramp stays last, never reordered',async()=>{
 const h=make({loadReefs:async()=>zig(['A','B','C','D','E']),ports:[{id:'pt',name:'Port',region:region.id,match:[35.1,-121]}]});const p=h.p;
 try{
  await new Promise(r=>setTimeout(r,0));p.setFilter('port','pt');await select(h);
  launchPoints.value={region:region.id,points:[{id:'r',name:'Ramp',latitude:35,longitude:-121}]};p.setLaunch(true);
  assert.equal(p.shortenRun(),'moved');eq(p.draft.value.ids,['B','D','E','C','A']);eq(p.orderedStops.value.map(t=>t.id),['B','D','E','C','A','user:launch-r']);
 }finally{p.dispose();launchPoints.value=null;}
});

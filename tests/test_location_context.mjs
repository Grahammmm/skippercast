import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolveLocation,enrichLocation,targetsForLocation,viewFromURL,locationURL} from '../dist/location-context.js';
import {setRegion} from '../dist/region.js?v=8.7';
import {circleGeometry} from '../dist/geo-screen.js?v=8.7';
import {localizeRuleState,areaNoticesHTML} from '../dist/regulations.js';
const read=p=>JSON.parse(readFileSync(p,'utf8'));
const directory=read('dist/regions/index.json').regions;
const south=read('dist/regions/southern-california/region.json');
const central=read('dist/regions/morro-bay/region.json');
const clear={inspect:()=>({status:'clear',fresh:true,names:[]})};
const point=(latitude,longitude)=>({latitude,longitude});
const context=p=>enrichLocation(resolveLocation(p,directory,south.id),south,clear);

test('map crossing loads the correct region, with deterministic overlap and unsupported gaps',()=>{
 assert.equal(resolveLocation(point(34,-119.4),directory,central.id).regionId,south.id);
 assert.equal(resolveLocation(point(35.3,-120.88),directory,south.id).regionId,central.id);
 for(const active of [central.id,'cambria-san-simeon'])assert.equal(resolveLocation(point(35.545,-121.1),directory,active).regionId,'cambria-san-simeon');
 for(const p of [point(34.6,-120.7),point(32.4,-117.3),point(36,-121.5)])assert.equal(resolveLocation(p,directory,south.id).coverage,'outside');
 assert.equal(resolveLocation(point(34.45,-120.5),directory,south.id).coverage,'edge');
});
test('southern target list excludes Dungeness; island context excludes bay bass without claiming a legal ban',()=>{
 const island=context(point(34,-119.4)), mainland=context(point(32.75,-117.2));
 assert.equal(island.name,'Anacapa');
 assert.ok(!targetsForLocation(south,island).some(t=>['dungeness','spotted-bass'].includes(t.id)));
 assert.ok(targetsForLocation(south,island).some(t=>t.id==='lobster'));
 assert.ok(targetsForLocation(south,mainland).some(t=>t.id==='spotted-bass'));
 assert.match(island.hiddenTargets[0].reason,/not a legal prohibition/);
 assert.deepEqual(targetsForLocation(south,context(point(34.6,-120.7))),[]);
});
test('nearby access notices are selected geographically and regional health advice remains',()=>{
 const d=read('dist/regions/southern-california/regulations.json'), island=context(point(34,-119.4));
 const html=areaNoticesHTML(d,Date.parse(d.reviewed_at),island).split('data-reg-section="other-access"')[0];
 assert.match(html,/Anacapa Island/);assert.match(html,/Health advice/);
 assert.doesNotMatch(html,/Camp Pendleton|San Diego naval|San Clemente: live/);
});
test('whole geometry, stale boundaries, MPAs and missing regional coverage cannot inherit an open badge',()=>{
 setRegion(south);
 const p={...point(34.4,-120),geometry:{type:'Polygon',coordinates:[[[-120.1,34.3],[-119.9,34.3],[-119.9,34.5],[-120.1,34.5],[-120.1,34.3]]]}};
 assert.equal(context(p).coverage,'mixed');
 const base={status:'open',label:'Season open',reason:'Season',issues:[]};
 assert.equal(localizeRuleState(base,context(p)).status,'unknown');
 assert.equal(localizeRuleState(base,{...context(point(34,-119.4)),protection:{status:'unavailable'}}).status,'unknown');
 const excluded=localizeRuleState(base,{...context(point(34,-119.4)),protection:{status:'excluded',names:['Anacapa SMCA'],fresh:true}});
 assert.equal(excluded.status,'excluded');assert.match(excluded.reason,/allow some activities/);
 assert.equal(localizeRuleState(base,{...context(point(34,-119.4)),regionId:central.id}).status,'unknown');
});
test('region handoff keeps map position, zoom and target while dropping a stale focus',()=>{
 const u=locationURL('https://skippercast.com/?region=morro-bay&focus=anacapa#spot',south.id,point(34,-119.4),11,'dungeness');
 assert.equal(u.searchParams.get('target'),'dungeness');assert.equal(u.searchParams.get('focus'),null);assert.equal(u.hash,'#map');
 assert.deepEqual(viewFromURL(u),{latitude:34,longitude:-119.4,zoom:11});
 for(const value of ['NaN,-119,11','34,-119,25','90,-119,11','34,0,11oops'])assert.equal(viewFromURL('https://example.org/?view='+value),null);
});
test('offshore search references keep their data package without borrowing nearshore legal clearance',()=>{
 for(const region of [central,read('dist/regions/cambria-san-simeon/region.json')]){
  setRegion(region);
  for(const p of region.forecast_points.filter(p=>p.offshore)){
   const c=enrichLocation(resolveLocation({...p,geometry:circleGeometry(p.latitude,p.longitude,5500)},directory,region.id),region,clear);
   assert.equal(c.regionId,region.id);assert.equal(c.coverage,'discovery');
   assert.ok(targetsForLocation(region,c).some(t=>t.id==='albacore'));
   assert.ok(targetsForLocation(region,c).every(t=>t.kind==='offshore'));
   assert.equal(localizeRuleState({status:'open'},c).status,'unknown');
  }
 }
 const p={...point(34.43,-120.5),geometry:circleGeometry(34.43,-120.5,5500)};
 assert.equal(resolveLocation(p,directory,south.id).coverage,'mixed');
});

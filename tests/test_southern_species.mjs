import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {getRegion,setRegion} from '../dist/region.js?v=8.8';
import {validRegulations,regulationState,ruleMethods} from '../dist/regulations.js';
import {habitatMatches,habitatDetails} from '../dist/survey-habitat.js';
import {hourScores} from '../dist/morning-outlook.js';
import {assessTrip} from '../server/alert-policy.js';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const source=read('regions/southern-california/region.json'),targets=read('catalog/targets.json').targets;
const region={...source,target_options:source.species.map(id=>({id,...targets[id]}))};
const habitat=(kind,extra={})=>({properties:{id:'sample',name:'Survey patch',habitat_kind:kind,island:'Anacapa',area_km2:.2,source_date:'2006',source_url:'https://coastalscience.noaa.gov/',depth_qualified:false,...extra}});
test('Southern selectors have complete distinct evidence, methods and rules without Northern defaults',()=>{
 const old=getRegion();setRegion(region);
 try{
  assert.ok(!region.species.includes('dungeness'));assert.ok(!region.species.includes('salmon'));
  for(const id of ['reef','lobster','yellowtail','yellowfin','white-seabass','sheephead','whitefish','kelp-bass','sand-bass','spotted-bass'])assert.ok(region.species.includes(id));
  const ecology=read('catalog/ecology/california-southern.json'),rules=read('dist/'+source.assets.regulations);
  assert.ok(validRegulations(rules));
  for(const id of region.species){assert.ok(ecology.profiles[id]?.source_species?.length,id);assert.ok(targets[id].control_mode);}
  assert.deepEqual(ruleMethods(rules,'lobster').map(x=>x[0]).sort(),['hand','hoop']);
  assert.ok(!ruleMethods(rules,'lobster').some(x=>x[0]==='rod'));
  delete rules.species.lobster;assert.equal(validRegulations(rules),false);
 }finally{setRegion(old);}
});
test('habitat associations do not turn bay bass or mobile offshore fish into island reef spots',()=>{
 assert.ok(habitatMatches(habitat('rock'),'sheephead',region));
 assert.ok(habitatMatches(habitat('rock'),'lobster',region));
 for(const id of ['spotted-bass','bluefin','yellowfin','dorado','bonito'])assert.equal(habitatMatches(habitat('rock'),id,region),false,id);
 assert.equal(habitatMatches(habitat('rock',{military_access:'unverified'}),'lobster',region),false);
 assert.equal(habitatMatches(habitat('rock',{species_ids:['reef']}),'lobster',region),false);
 const html=habitatDetails(habitat('mixed'),region);assert.match(html,/Mixed hard and soft/);assert.ok(!html.includes('classifies this as sediment'));
 assert.match(habitatDetails(habitat('rock'),region),/not a depth-qualified/);
});
test('bottom species keep conservative control; lobster cannot inherit a pelagic gear rating',()=>{
 const old=getRegion();setRegion(region);
 try{
  const c={wind:10,gust:12,sea:{height:2},chop:{height:.5,period:7},swell:{from:290},secondary:{height:.2,from:290}};
  const reef=hourScores(c,c,'reef'),whitefish=hourScores(c,c,'whitefish'),lobster=hourScores(c,c,'lobster');
  assert.equal(whitefish.control,reef.control);assert.ok(whitefish.control<hourScores(c,c,'bluefin').control);
  assert.equal(lobster.control,null);assert.equal(lobster.conditions,lobster.comfort);assert.equal(lobster.score_scope,'boat-comfort');
  assert.equal(lobster.bite,null);
 }finally{setRegion(old);}
});
test('lobster opening cannot auto-authorize a morning set or unreviewed gear',()=>{
 const old=getRegion();setRegion(region);
 try{
  const data=read('dist/'+source.assets.regulations),now=Date.parse('2026-09-22T18:00:00Z');
  for(const [id,s] of Object.entries(data.sources)){s.approved_content_sha256='a'.repeat(64);data.checks[id]={url:s.url,normalization:s.normalization,status:'unchanged',source_status:'ok',content_sha256:s.approved_content_sha256,data_retrieved_at:new Date(now).toISOString()};}
  assert.equal(regulationState(data,'lobster',now,'2026-09-22','hoop').status,'closed');
  assert.notEqual(regulationState(data,'lobster',now,'2026-10-02','hoop').status,'open');
 }finally{setRegion(old);}
});
test('a reviewed timed season honors the opening instant and does not treat a date as an all-day opening',()=>{
 const old=getRegion();setRegion(region);
 try{
  const data=read('dist/'+source.assets.regulations),before=Date.parse('2026-10-02T17:59:00-07:00'),opening=Date.parse('2026-10-02T18:00:00-07:00');
  for(const [id,s] of Object.entries(data.sources)){s.approved_content_sha256='a'.repeat(64);data.checks[id]={url:s.url,normalization:s.normalization,status:'unchanged',source_status:'ok',content_sha256:s.approved_content_sha256,data_retrieved_at:new Date(before).toISOString()};}
  // Exercise the future reviewed state too; today the opening-review gate remains in place.
  for(const w of data.species.lobster.windows){delete w.requires_opening_review;delete w.restriction;}
  delete data.species.lobster.methods.hand.requires_clearance;
  assert.equal(regulationState(data,'lobster',before,null,'hand').status,'closed');
  assert.equal(regulationState(data,'lobster',opening,null,'hand').status,'open');
  assert.equal(regulationState(data,'lobster',before,'2026-10-02','hand').status,'restricted');
  assert.equal(regulationState(data,'lobster',before,'2026-10-02','hand',before).status,'closed');
  assert.equal(regulationState(data,'lobster',before,'2026-10-02','hand',opening).status,'open');
  data.species.lobster.windows[0].start_at='2026-10-02T18:00:00';assert.equal(validRegulations(data),false);
 }finally{setRegion(old);}
});
test('saved-trip assessment also rejects fishing hours before a reviewed timed opening',()=>{
 const now=Date.parse('2026-10-02T16:00:00-07:00'),rules=read('dist/'+source.assets.regulations);
 const trip={point:'border',species:'lobster',date:'2026-10-02',start_hour:17,end_hour:18};
 const hours=['2026-10-02T17:00:00-07:00','2026-10-02T18:00:00-07:00'].map(x=>Date.parse(x)/1000);
 for(const [id,s] of Object.entries(rules.sources)){s.approved_content_sha256='a'.repeat(64);rules.checks[id]={url:s.url,normalization:s.normalization,status:'unchanged',source_status:'ok',content_sha256:s.approved_content_sha256,data_retrieved_at:new Date(now).toISOString()};}
 for(const w of rules.species.lobster.windows){delete w.requires_opening_review;delete w.restriction;}
 const intelligence={region_id:region.id,completed_at:new Date(now).toISOString(),forecast:{requested_points:region.forecast_points.map(p=>[p.id,p.latitude,p.longitude]),models:{gfs_global:{data:[{hourly:{time:hours}}]}}}};
 const before=assessTrip(trip,region,intelligence,rules,[],now);
 assert.equal(before.legal,'closed');assert.ok(before.issues.some(s=>s.includes('before the legal season opening')));
 const after=assessTrip({...trip,start_hour:18},region,intelligence,rules,[],now);
 assert.equal(after.legal,'reviewed season');
 intelligence.forecast.requested_points.pop();
 const mismatched=assessTrip(trip,region,intelligence,rules,[],now);
 assert.equal(mismatched.status,'unverified');assert.equal(mismatched.values.wind,null);
 assert.match(mismatched.issues[0],/locations do not match/);
});

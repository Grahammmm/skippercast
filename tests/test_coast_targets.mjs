import {searchSelectionProfile} from '../dist/search-plan-data.js';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {sharedTargetOptions,nativeOnlyTarget} from '../dist/coast-targets.js';
import {setRegion} from '../dist/region.js';
import {targetsForLocation} from '../dist/location-context.js';
import {matchesSpecies,PROFILES} from '../dist/species.js';
import {regulationState} from '../dist/regulations.js';
const read=id=>JSON.parse(readFileSync(`dist/regions/${id}/region.json`,'utf8'));
const central=read('morro-bay');
test('shared targets preserve every chart option and original native species without duplicates',()=>{
 const options=sharedTargetOptions(central),ids=options.map(t=>t.id);
 for(const original of central.target_options)assert.deepEqual(options.find(t=>t.id===original.id),original);
 for(const id of ['lingcod','rockfish-reef','gopher-rockfish','cabezon-shallow-reef','surfperch'])assert.ok(ids.includes(id));
 assert.equal(new Set(ids).size,ids.length);
 for(const id of ['gopher-rockfish','cabezon-shallow-reef','surfperch'])assert.ok(nativeOnlyTarget(id));
 assert.ok(!nativeOnlyTarget('lingcod'));assert.ok(!nativeOnlyTarget('__proto__'));
});
test('reviewed geography retains exclusions and does not add coast targets offshore or outside terrain regions',()=>{
 const south=read('southern-california');assert.deepEqual(sharedTargetOptions(south),south.target_options);
 const context={coverage:'covered',regionId:central.id,hiddenTargets:[{id:'surfperch'}]};
 assert.ok(!targetsForLocation(central,context).some(t=>t.id==='surfperch'));
 assert.ok(targetsForLocation(central,context).some(t=>t.id==='cabezon-shallow-reef'));
 assert.ok(targetsForLocation(central,{...context,coverage:'discovery'}).every(t=>t.kind==='offshore'));
});
test('native-only targets cannot inherit reef atlas matches or generic legal limits',()=>{
 setRegion(central);const target={metrics:{relief_210m_m:10,rugose_or_bedrock_fraction_210m:1}};
 const rules=JSON.parse(readFileSync('dist/'+central.assets.regulations,'utf8'));
 for(const id of ['rockfish-reef','gopher-rockfish','cabezon-shallow-reef','surfperch']){
  assert.equal(matchesSpecies(target,id),false);assert.equal(PROFILES[id].kind,'coast');
  assert.equal(regulationState(rules,id,Date.parse(rules.reviewed_at)).status,'unknown');
 }
 assert.equal(matchesSpecies(target,'lingcod'),true);
});

test('a stale chart search outline cannot inherit a new native target or an unrelated supported method',()=>{
 const data={profiles:{reef:{name:'reef'},halibut:{name:'halibut'}}},entry={target:'reef',feature:{properties:{species:['reef']}}};
 assert.equal(searchSelectionProfile(data,'reef',entry),data.profiles.reef);
 for(const id of ['cabezon-shallow-reef','gopher-rockfish','halibut','constructor'])assert.equal(searchSelectionProfile(data,id,entry),null);
});

test('generated ocean search strips retain current-target actions without asserting fish presence',()=>{
 const data={profiles:{albacore:{kind:'offshore'},bluefin:{kind:'offshore'}}},entry={target:'albacore',feature:{properties:{species:[],habitat_kind:'ocean',search_method:'ocean-transition-v2'}}};
 assert.equal(searchSelectionProfile(data,'albacore',entry),data.profiles.albacore);
 for(const id of ['bluefin','gopher-rockfish','constructor'])assert.equal(searchSelectionProfile(data,id,entry),null);
 assert.deepEqual(entry.feature.properties.species,[]);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {fishEntry,nativePlaceView} from '../web/fish-entry.ts';
import {coastPlaces} from '../packages/coast/src/coast3d/place-data.ts';
import {readFileSync} from 'node:fs';
test('v1 entry normalizes actual aliases before the raw store starts and region locks',()=>{
 const url=fishEntry('https://skippercast.com/?place=avila&mode=shore&species=surfperch&layer=waves&hour=2026-10-07T12:00:00Z');
 assert.equal(url.searchParams.get('region'),'morro-bay');assert.equal(url.searchParams.get('profile'),'shore');assert.equal(url.searchParams.get('target'),'surfperch');assert.equal(url.searchParams.get('layers'),'swell');assert.equal(url.searchParams.get('hour'),'2026-10-07T12:00Z');assert.equal(url.searchParams.get('view'),nativePlaceView('avila'));assert.equal(fishEntry(url.href).href,url.href);
 const boot=readFileSync(new URL('../dist/boot.js',import.meta.url),'utf8');assert.ok(boot.indexOf('fishEntry(location.href)')<boot.indexOf('startURLSync();'));assert.ok(boot.indexOf('history.replaceState')<boot.indexOf('startURLSync();'));assert.ok(boot.indexOf('startURLSync();')<boot.indexOf('lockRegion();'));
});
test('all original native place centers and spans survive entry with no renderer dependency',()=>{
 for(const [id,,longitude,latitude,span] of coastPlaces){const url=fishEntry('https://skippercast.com/?place='+id),view=url.searchParams.get('view').split(',').map(Number);assert.equal(view[0],latitude);assert.equal(view[1],longitude);assert.equal(view[2],Math.max(7,Math.min(18,12-Math.log2(span/7300))));}
 const source=readFileSync(new URL('../packages/coast/src/coast3d/place-data.ts',import.meta.url),'utf8');assert.doesNotMatch(source,/^import /m);
});
test('canonical geography and view win, and bad explicit geography cannot become Morro',()=>{
 for(const query of ['region=','coast=','place=','place=constructor','area=unknown','place=morro&place=avila'])assert.throws(()=>fishEntry('https://s.test/?'+query),query);
 for(const query of ['region=monterey-point-sur&place=morro','coast=central&place=unknown','region=unknown&place=morro']){const url=fishEntry('https://s.test/?'+query);assert.equal(url.searchParams.get('view'),null);}
 const url=fishEntry('https://s.test/?place=morro&view=35.1,-120.8,9&target=&species=lingcod');assert.equal(url.searchParams.get('view'),'35.1,-120.8,9');assert.equal(url.searchParams.get('target'),'');
});
test('initial regional selector preserves explicit empty, unknown and prototype targets before location initialization',async()=>{
 const {initialTargetSelection}=await import('../dist/region.js');const region={id:'morro-bay',species:['reef'],target_options:[{id:'reef',name:'Reef',group:'Targets'}]};
 for(const id of ['','unknown','constructor','toString','__proto__']){const initial=initialTargetSelection(region,id);assert.equal(initial.value,id);assert.ok(initial.options.some(item=>item.id===id&&item.group==='Unavailable selection'));}
 assert.equal(initialTargetSelection(region,null).value,'reef');
});
test('unknown target profiles and inherited ecological names do not borrow reef or prototype methods',async()=>{
 const {speciesProfile,ecologicalProfile}=await import('../dist/species.js');
 for(const id of ['','unknown','constructor','toString','__proto__']){const p=speciesProfile(id);assert.equal(p.kind,'unavailable');assert.match(p.map,/No substitute/);assert.deepEqual(p.sources,[]);assert.equal(ecologicalProfile({profiles:{}},id),null);}
 assert.equal(speciesProfile('reef').kind,'reef');assert.equal(ecologicalProfile({profiles:{reef:{habitat:'own'}}},'reef').habitat,'own');
});
test('actual species guide/draw/fit initialization with unknown and constructor targets is unavailable without borrowed methods',async()=>{
 const {initSpecies}=await import('../dist/species.js');const {setRegion}=await import('../dist/region.js');
 const region=JSON.parse(readFileSync(new URL('../regions/morro-bay/region.json',import.meta.url),'utf8'));setRegion({...region,assets:{...region.assets,habitats:'habitat-fixture',ecology:'ecology-fixture'}});
 const old={document:globalThis.document,fetch:globalThis.fetch,CustomEvent:globalThis.CustomEvent};let evidenceFetches=0;
 const nodes=new Map(),node=()=>({value:'all',dataset:{},innerHTML:'',hidden:false,disabled:false,textContent:'',addEventListener:()=>{},querySelector:()=>null});
 for(const id of ['species-select','species-guide','filter-options','grade','geometry','species-info'])nodes.set(id,node());
 const empty={...node(),querySelector:key=>nodes.get('empty:'+key)};for(const id of ['strong','p'])nodes.set('empty:'+id,node());nodes.set('map-empty',empty);
 globalThis.document={getElementById:id=>nodes.get(id),dispatchEvent:()=>{}};globalThis.CustomEvent=class extends Event{};
 globalThis.fetch=async url=>{if(url==='habitat-fixture')return Response.json({areas:[]});if(url==='ecology-fixture')return Response.json({region_id:region.id,profiles:{}});evidenceFetches++;throw Error('Unknown target must not fetch a strategy or evidence');};
 try{for(const id of ['unknown','constructor','__proto__','']){nodes.get('species-select').value=id;const ui=await initSpecies({closePopup:()=>{}},{areas:{}},{protectedAreas:{pointAllowed:()=>{throw Error('No unknown target geometry');}},onChange:()=>{},onConditions:()=>{},showGuide:()=>{},onSelect:()=>{}});ui.draw();assert.equal(ui.fit(),false);assert.match(nodes.get('species-guide').innerHTML,/Target method unavailable/);assert.equal(nodes.get('empty:strong').textContent,'Target method unavailable');assert.equal(nodes.get('grade').disabled,true);}assert.equal(evidenceFetches,0);}finally{Object.assign(globalThis,old);}
});
test('all supplied legacy species identities survive actual startup including empty, invalid and prototype names',()=>{
 for(const species of ['','toString','constructor','__proto__','not valid','UPPERCASE','<script>']){
  const input=new URL('https://skippercast.com/?place=morro');input.searchParams.set('species',species);const next=fishEntry(input.href);assert.equal(next.searchParams.has('target'),true);assert.equal(next.searchParams.get('target'),species);assert.equal(next.searchParams.has('species'),false);
  input.searchParams.set('target','');assert.equal(fishEntry(input.href).searchParams.get('target'),'');input.searchParams.set('target','halibut');assert.equal(fishEntry(input.href).searchParams.get('target'),'halibut');
 }
 const boot=readFileSync(new URL('../dist/boot.js',import.meta.url),'utf8');assert.ok(boot.indexOf('try {')<boot.indexOf('fishEntry(location.href)'));assert.ok(boot.indexOf('fishEntry(location.href)')<boot.indexOf('} catch(error)'));assert.match(boot,/SkipperCast couldn't load this area/);
});

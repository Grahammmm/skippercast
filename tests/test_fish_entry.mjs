import test from 'node:test';
import assert from 'node:assert/strict';
import {fishEntry,nativePlaceView} from '../web/fish-entry.ts';
import {coastPlaces} from '../packages/coast/src/coast3d/place-data.ts';
import {readFileSync} from 'node:fs';
test('Fish entry normalizes actual aliases',()=>{
 const url=fishEntry('https://skippercast.com/?place=avila&mode=shore&species=surfperch&layer=waves&hour=2026-10-07T12:00:00Z');
 assert.equal(url.searchParams.get('region'),'morro-bay');assert.equal(url.searchParams.get('profile'),'shore');assert.equal(url.searchParams.get('target'),'surfperch');assert.equal(url.searchParams.get('layers'),'swell');assert.equal(url.searchParams.get('hour'),'2026-10-07T12:00Z');assert.equal(url.searchParams.get('view'),nativePlaceView('avila'));assert.equal(fishEntry(url.href).href,url.href);
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
test('all supplied legacy species identities survive entry including empty, invalid and prototype names',()=>{
 for(const species of ['','toString','constructor','__proto__','not valid','UPPERCASE','<script>']){
  const input=new URL('https://skippercast.com/?place=morro');input.searchParams.set('species',species);const next=fishEntry(input.href);assert.equal(next.searchParams.has('target'),true);assert.equal(next.searchParams.get('target'),species);assert.equal(next.searchParams.has('species'),false);
  input.searchParams.set('target','');assert.equal(fishEntry(input.href).searchParams.get('target'),'');input.searchParams.set('target','halibut');assert.equal(fishEntry(input.href).searchParams.get('target'),'halibut');
 }
});

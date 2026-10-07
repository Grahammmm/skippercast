import assert from 'node:assert/strict';
import test from 'node:test';
import {hasAreaLink, portURL, closestPort} from '../dist/home-port.js';

const morro={id:'morro-bay',region:'morro-bay',view:[35.36,-120.94,10],match:[35.3667,-120.868]};
const sanDiego={id:'san-diego',region:'southern-california',view:[32.84,-117.45,10],match:[32.72,-117.22]};

test('only a bare visit opens port choice; shared region and view links stay authoritative',()=>{
  assert.equal(hasAreaLink('https://skippercast.com/'),false);
  assert.equal(hasAreaLink('https://skippercast.com/?utm_source=friend'),false);
  assert.equal(hasAreaLink('https://skippercast.com/?region=southern-california#map'),true);
  assert.equal(hasAreaLink('https://skippercast.com/?coast=central'),true);
  assert.equal(hasAreaLink('https://skippercast.com/?view=35.2,-120.9,10'),true);
  assert.equal(hasAreaLink('https://skippercast.com/#forecast'),true);
});

test('port navigation chooses its forecast map while retaining unrelated link parameters',()=>{
  const url=new URL(portURL('https://skippercast.com/?utm_source=friend&coast=central&target=reef#forecast',sanDiego));
  assert.equal(url.searchParams.get('region'),'southern-california');
  assert.equal(url.searchParams.get('view'),'32.84000,-117.45000,10');
  assert.equal(url.searchParams.get('target'),null);
  assert.equal(url.searchParams.get('utm_source'),'friend');
  assert.equal(url.hash,'#map');
});

test('nearest-port suggestion stays local and refuses a distant match',()=>{
  assert.equal(closestPort([morro,sanDiego],35.36,-120.88)?.id,'morro-bay');
  assert.equal(closestPort([morro,sanDiego],37,-119),null);
  assert.equal(closestPort([morro],NaN,-120.9),null);
});

test('synthetic home migration keeps valid current home ahead of legacy cookie and preserves native sites',async()=>{
 const {resolveHome,nativeHomeURL,HOME_PORT_KEY,HOME_PLACE_KEY}=await import('../dist/home-port.js');
 const {preferenceHeader}=await import('../packages/coast/src/coast3d/preferences.ts');
 const values=new Map([[HOME_PORT_KEY,morro.id]]),storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
 const cookie=preferenceHeader({v:1,place:'cambria',mode:'spear'},true);
 assert.equal(resolveHome([morro,sanDiego],storage,cookie).port,morro);assert.equal(values.has(HOME_PLACE_KEY),false);
 values.set(HOME_PORT_KEY,'missing');const home=resolveHome([morro],storage,cookie);assert.equal(home.native.place,'cambria');assert.equal(values.get('skippercast-profile-v1'),'spear');assert.equal(JSON.parse(values.get(HOME_PLACE_KEY)).place,'cambria');
 const url=new URL(nativeHomeURL('https://skippercast.com/',home.native));assert.equal(url.searchParams.get('region'),'cambria-san-simeon');assert.equal(url.searchParams.get('profile'),'spear');assert.match(url.searchParams.get('view'),/^35.56000,-121.11000,/);
 assert.equal(resolveHome([],null,'skippercast_home=invalid'),null);
});
test('shared Fish selections bypass home and forget removes home stores/cookie without changing visit',async()=>{
 const {forgetHome,HOME_PORT_KEY,HOME_PLACE_KEY,FIRST_RUN_KEY}=await import('../dist/home-port.js');
 for(const key of ['place','area','mode','species','hour','profile','day','habitat'])assert.equal(hasAreaLink('https://s.test/?'+key+'='),true,key);
 const values=new Map([[HOME_PORT_KEY,'morro-bay'],[HOME_PLACE_KEY,'native'],[FIRST_RUN_KEY,'boat'],['skippercast-profile-v1','shore'],['other','kept']]);const jar={cookie:'old'},href='https://s.test/?region=monterey-point-sur&target=surfperch';
 forgetHome({removeItem:k=>values.delete(k)},jar,true);assert.deepEqual([...values],[['other','kept']]);assert.match(jar.cookie,/skippercast_home=;.*Max-Age=0.*Secure/);assert.equal(href,'https://s.test/?region=monterey-point-sur&target=surfperch');
});
test('actual shared startup never reads legacy cookie or changes saved home',async()=>{
 const {initHomePort}=await import('../dist/home-port.js');
 const old={location:globalThis.location,document:globalThis.document,localStorage:globalThis.localStorage,fetch:globalThis.fetch};let writes=0;
 globalThis.location={href:'https://skippercast.com/?place=cambria&mode=shore'};
 globalThis.document={getElementById:()=>({setAttribute:()=>{},addEventListener:()=>{}}),get cookie(){throw Error('Shared startup must not read legacy cookie');}};
 globalThis.localStorage={getItem:()=>morro.id,setItem:()=>writes++,removeItem:()=>writes++};globalThis.fetch=()=>{throw Error('Shared startup must not load home directory');};
 try{assert.equal(await initHomePort(),true);assert.equal(writes,0);}finally{Object.assign(globalThis,old);}
});
test('native save and forget keep root home coherent; validated current profile wins cached and cookie mode',async()=>{
 const {resolveHome,nativeHomeURL,HOME_PLACE_KEY,HOME_PORT_KEY}=await import('../dist/home-port.js');
 const {saveBrowserPreferences,syncPreferences,browserPreferences,preferenceHeader}=await import('../packages/coast/src/coast3d/preferences.ts');
 const old=globalThis.localStorage,values=new Map(),storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)},jar={cookie:''};globalThis.localStorage=storage;
 try{
  assert.equal(saveBrowserPreferences(jar,{v:1,place:'cambria',mode:'spear'},true),true);assert.equal(resolveHome([morro],storage,jar.cookie).native.place,'cambria');
  assert.equal(saveBrowserPreferences(jar,{v:1,place:'carmel',mode:'shore'},true),true);assert.equal(resolveHome([morro],storage,jar.cookie).native.place,'carmel');
  values.set('skippercast-profile-v1','boat');assert.equal(resolveHome([],storage,jar.cookie).native.mode,'boat');assert.equal(browserPreferences(jar).mode,'boat');assert.equal(new URL(nativeHomeURL('https://s.test/',{v:1,place:'carmel',mode:'shore'},storage)).searchParams.get('profile'),'boat');
  values.delete(HOME_PLACE_KEY);assert.equal(resolveHome([],storage,preferenceHeader({v:1,place:'avila',mode:'spear'},true)).native.mode,'boat');
  syncPreferences(null);jar.cookie='';assert.equal(values.has(HOME_PLACE_KEY),false);assert.equal(values.has(HOME_PORT_KEY),false);assert.equal(resolveHome([],storage,jar.cookie),null);
 }finally{globalThis.localStorage=old;}
});
test('explicit new port clears Fish geography and habitat so readable report binds the new point; empty same-region target persists',async()=>{
 const {fishEntry}=await import('../web/fish-entry.ts');const {portChoiceURL}=await import('../dist/home-port.js');
 globalThis.REGIONS={};globalThis.DEPLOYMENT={allowed_origins:['https://skippercast.com']};
 const {readableSelection}=await import('../server/coast-pages.ts');const {readFileSync}=await import('node:fs');
 const regions={'morro-bay':JSON.parse(readFileSync(new URL('../regions/morro-bay/region.json',import.meta.url),'utf8'))};
 const old=fishEntry('https://skippercast.com/?place=avila&area=south&mode=shore&species=surfperch&habitat=123&focus=old&spot=old&hour=2026-10-07T12:00:00Z');
 const next=new URL(portChoiceURL(old.href,morro));
 for(const key of ['place','area','habitat','focus','spot'])assert.equal(next.searchParams.has(key),false,key);
 assert.equal(next.searchParams.get('target'),'surfperch');assert.equal(next.searchParams.get('profile'),'shore');assert.equal(next.searchParams.get('hour'),'2026-10-07T12:00Z');
 const selection=readableSelection(next,regions,new Date('2026-10-07T12:00:00Z'));assert.ok(selection.context);assert.equal(selection.reason,null);assert.equal(selection.context.regionId,'morro-bay');assert.equal(selection.context.point.latitude,morro.view[0]);
 old.searchParams.set('target','');const empty=new URL(portChoiceURL(old.href,morro));assert.equal(empty.searchParams.has('target'),true);assert.equal(empty.searchParams.get('target'),'');
 const other=new URL(portChoiceURL(old.href,sanDiego));assert.equal(other.searchParams.has('target'),false);
});

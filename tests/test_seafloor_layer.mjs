import test from 'node:test';
import assert from 'node:assert/strict';
import { legendHTML, detailsHTML, VIEWS } from '../dist/seafloor-layer.js';

test('search area sheet explains limited evidence without inventing a grade', () => {
  const html = detailsHTML({status: 'search-area', terrain_grade: 'unknown', fit_lingcod: 'unknown',
    search_area: JSON.stringify({target_species: ['lingcod']}), depth_min_ft: 40, depth_max_ft: 50});
  assert.match(html, /Limited confidence · unranked search area/);
  assert.match(html, /surrounding measurements are insufficient/);
  assert.match(html, /Potential habitat for lingcod/);
  assert.doesNotMatch(html, /Terrain grade unknown|of 3/);
  assert.match(legendHTML('terrain'), /Rough-bottom search area · unranked/);
});
import { GRADE_STYLE, FIT_STYLE } from '../dist/seafloor-data.js';

test('producer notices survive tile JSON and unsafe credit text cannot become markup', () => {
  const row={source_id:'original',attribution:'Producer <img src=x>',notice:'Noncommercial; not for navigation.',policy_url:'https://example.org/terms'};
  const html=detailsHTML({source_rights:JSON.stringify([row])});
  assert.match(html,/Producer &lt;img src=x&gt;/);
  assert.match(html,/Noncommercial; not for navigation\./);
  assert.match(html,/href="https:\/\/example.org\/terms"/);
  assert.doesNotMatch(html,/<img src=x>/);
  const unsafe=detailsHTML({source_rights:[{...row,policy_url:'javascript:alert(1)'}]});
  assert.doesNotMatch(unsafe,/javascript:|Publisher terms/);
  assert.match(unsafe,/Noncommercial/);
});

test('terrain and fit legends never share a key, and fit is never called a catch probability', () => {
  const terrain = legendHTML('terrain'), fit = legendHTML('fit_lingcod');
  for (const s of Object.values(GRADE_STYLE)) { assert.ok(terrain.includes(s.color)); assert.ok(!fit.includes(s.color)); }
  for (const s of Object.values(FIT_STYLE)) { assert.ok(fit.includes(s.color)); assert.ok(!terrain.includes(s.color)); }
  assert.match(fit, /not catch probability/);
  assert.deepEqual(VIEWS.map((v) => v.id), ['terrain', 'fit_lingcod', 'fit_rockfish_reef']);
});

test('details carry the required caveats, escape text and keep unknowns unknown', () => {
  const html = detailsHTML({ id: 'x', terrain_grade: 'A', fit_lingcod: 3, fit_rockfish_reef: 'unknown', depth_min_ft: 40, depth_max_ft: 90,
    source_ids: '["<b>src</b>"]', vertical_datum: 'unknown', screen: '{"status":"pass"}' });
  assert.match(html, /Habitat candidate, unverified/);
  assert.match(html, /Nominal depth; verify on your sounder\./);
  assert.match(html, /40–90 ft nominal/);
  assert.match(html, /lingcod: 3 of 3/);
  assert.match(html, /rockfish reef: unknown/);
  assert.match(html, /not a catch probability/);
  assert.match(html, /not a navigation chart/i);
  assert.ok(html.includes('&lt;b&gt;src&lt;/b&gt;'));
  assert.ok(!html.includes('<b>src</b>'));
  assert.match(html, /id="seafloor-weather"/);
});

test('regional screened habitat opens for reef targets, respects off, and skips unrelated species', async t => {
  const {initSeafloor} = await import('../dist/seafloor-layer.js');
  const elements = new Map();
  const element = (id, value='') => {
    const handlers = {};
    const e = {value, checked:false, hidden:false, textContent:'', add(){},
      addEventListener(name, fn){handlers[name]=fn;}, change(){handlers.change?.();}};
    elements.set(id,e); return e;
  };
  const species=element('species-select','reef'), toggle=element('layer-seafloor');
  const cells=element('layer-seafloor-cells'), view=element('seafloor-view','terrain');
  element('seafloor-status');element('seafloor-options');
  const saved={document:globalThis.document,L:globalThis.L,Option:globalThis.Option,pmtiles:globalThis.pmtiles,location:globalThis.location};
  t.after(()=>{for(const [key,val] of Object.entries(saved)){if(val===undefined)delete globalThis[key];else globalThis[key]=val;}});
  globalThis.document={getElementById:id=>elements.get(id)};
  globalThis.Option=class{constructor(label,id){this.value=id;}};
  globalThis.location={href:'https://skippercast.com/'};
  let visible=0;
  const layer=()=>({shown:false,addTo(){if(!this.shown){this.shown=true;visible++;}return this;},remove(){if(this.shown){this.shown=false;visible--;}},clearLayers(){}});
  globalThis.L={canvas:()=>({}),layerGroup:layer,control:()=>({...layer(),getContainer:()=>({})})};
  const map={createPane:()=>({style:{}}),on(){},getZoom:()=>9};
  let opened=0;
  globalThis.pmtiles={PMTiles:class{constructor(){opened++;}async getHeader(){return {};}}};
  const ready={status:'ready',region:'morro-bay',archive_sha256:'a'.repeat(64),expires_at:'2099-01-01T00:00:00Z',layers:{habitat:9},reach_inputs:{r01:'x',r02:'y'}};
  let response=ready;
  const settle=()=>new Promise(resolve=>setImmediate(resolve));
  const reader=initSeafloor(map,()=>{}, {fetchImpl:async()=>({ok:true,status:200,json:async()=>response})});
  await settle();
  assert.equal(toggle.checked,true);assert.equal(cells.checked,false);
  assert.equal(view.value,'fit_rockfish_reef');assert.equal(reader.state(),'ready');
  assert.match(elements.get('seafloor-status').textContent,/2 published reach inputs/);
  species.value='lingcod';species.change();await settle();assert.equal(view.value,'fit_lingcod');
  response={...ready,archive_sha256:'b'.repeat(64)};species.change();await settle();
  assert.equal(opened,2,'a changed publication discards its old reader');
  toggle.checked=false;toggle.change();species.value='rockfish';species.change();await settle();
  assert.equal(toggle.checked,false,'manual off survives a target change');
  toggle.checked=true;response={status:'updating'};toggle.change();await settle();
  assert.equal(reader.state(),'updating');assert.equal(opened,2,'held refresh does not open another archive');
  assert.match(elements.get('seafloor-status').textContent,/updating/);
  species.value='yellowfin';toggle.checked=false;
  initSeafloor(map,()=>{}, {fetchImpl:async()=>({ok:true,status:200,json:async()=>ready})});
  await settle();assert.equal(toggle.checked,false,'pelagic target does not open the reef layer');
});

test('defaults distinguish reef fishing from pelagic targets and count actual publication inputs', async () => {
  const {habitatDefaults,publishedReachCount}=await import('../dist/seafloor-layer.js');
  assert.equal(habitatDefaults('yellowfin').enabled,false);
  assert.equal(habitatDefaults('reef').enabled,true);
  assert.equal(habitatDefaults('lingcod').view,'fit_lingcod');
  assert.equal(publishedReachCount({reach_inputs:{a:'x',b:'y',c:'z',d:'w'}}),4);
  assert.equal(publishedReachCount({}),0);
});

test('transient publication recovers automatically, retries are bounded, and off cancels recovery', async t => {
  const {initSeafloor}=await import('../dist/seafloor-layer.js');
  const elements=new Map();
  for(const id of ['species-select','layer-seafloor','layer-seafloor-cells','seafloor-view','seafloor-status','seafloor-options']){
    const handlers={}; elements.set(id,{value:id==='species-select'?'reef':'terrain',checked:false,hidden:false,textContent:'',add(){},
      addEventListener(name,fn){handlers[name]=fn;},change(){handlers.change?.();}});
  }
  const saved={document:globalThis.document,L:globalThis.L,Option:globalThis.Option,pmtiles:globalThis.pmtiles,location:globalThis.location};
  t.after(()=>{for(const [key,value]of Object.entries(saved)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}});
  globalThis.document={getElementById:id=>elements.get(id)};globalThis.Option=class{};
  globalThis.location={href:'https://skippercast.com/'};
  let visible=0;
  const layer=()=>({shown:false,addTo(){if(!this.shown){this.shown=true;visible++;}return this;},remove(){if(this.shown){this.shown=false;visible--;}},clearLayers(){}});
  globalThis.L={canvas:()=>({}),layerGroup:layer,control:()=>({...layer(),getContainer:()=>({})})};
  let opened=0;globalThis.pmtiles={PMTiles:class{constructor(){opened++;}async getHeader(){return {};}}};
  const map={createPane:()=>({style:{}}),on(){},getZoom:()=>9};
  const ready={status:'ready',region:'morro-bay',archive_sha256:'a'.repeat(64),expires_at:'2099-01-01T00:00:00Z',layers:{habitat:9}};
  let pendingFetch=null;
  let response={status:'updating'}, clock=Date.parse('2030-01-01T00:00:00Z'), next=0;
  const timers=new Map(), settle=()=>new Promise(resolve=>setImmediate(resolve));
  const reader=initSeafloor(map,()=>{}, {fetchImpl:async()=>{if(pendingFetch)await pendingFetch;return {ok:true,status:200,json:async()=>response};},now:()=>clock,
    setTimeoutImpl(fn,delay){const id=++next;timers.set(id,{fn,delay});return id;},clearTimeoutImpl(id){timers.delete(id);}});
  t.after(()=>reader.dispose());await settle();
  assert.equal(reader.state(),'updating');assert.equal(opened,0);
  assert.equal(timers.size,1,'updating publication schedules automatic recovery');
  assert.equal([...timers.values()][0].delay,30000);
  const fire=async()=>{const [id,event]=timers.entries().next().value;timers.delete(id);event.fn();await settle();};
  response=ready;await fire();assert.equal(reader.state(),'ready');assert.equal(opened,1);
  response={status:'updating'};await reader.enable();
  const delays=[];while(timers.size){delays.push([...timers.values()][0].delay);await fire();}
  assert.deepEqual(delays,[30000,60000,120000,240000,300000]);
  assert.match(elements.get('seafloor-status').textContent,/toggle layer to retry/);
  await reader.enable();assert.equal(timers.size,1);
  const toggle=elements.get('layer-seafloor');toggle.checked=false;toggle.change();await settle();assert.equal(timers.size,0);
  toggle.checked=true;response={status:'held'};toggle.change();await settle();
  assert.equal(reader.state(),'held');assert.equal(timers.size,0);assert.equal(opened,1);
  response=ready;await reader.enable();assert.equal(reader.state(),'ready');assert.equal(timers.size,1);
  assert.equal(visible,3);
  let release;pendingFetch=new Promise(resolve=>{release=resolve;});
  clock=Date.parse(ready.expires_at);await fire();
  assert.equal(visible,0,'expiry hides all layers before a pending fetch completes');
  assert.equal(reader.state(),'checking');
  release();await settle();pendingFetch=null;
  assert.equal(reader.state(),'expired');assert.equal(timers.size,0);
  clock=Date.parse('2030-01-01T00:00:00Z');await reader.enable();assert.equal(visible,3);
  pendingFetch=new Promise(resolve=>{release=resolve;});
  const refresh=reader.enable();assert.equal(visible,0,'manual/species refresh hides old layers synchronously');
  reader.dispose();release();await refresh;pendingFetch=null;
  elements.get('species-select').change();toggle.change();elements.get('layer-seafloor-cells').change();
  await reader.enable();await reader.draw();await settle();
  assert.equal(reader.state(),'disposed');assert.equal(visible,0);assert.equal(timers.size,0);
});


test('classified area sheet separates publisher interpretation from terrain and species ranks', () => {
  const html = detailsHTML({status: 'classified-area', terrain_grade: 'A', fit_lingcod: 3,
    depth_min_ft: 25, depth_max_ft: 300, source_ids: '["depth","class"]'});
  assert.match(html, /Publisher interpretation · unranked habitat area/);
  assert.match(html, /original publisher interprets rugose rock and boulders/);
  assert.match(html, /does not establish fish presence or a precise fishing position/);
  assert.match(html, /Terrain grade and species fit are unknown/);
  assert.match(html, /lingcod: unknown/);
  assert.doesNotMatch(html, /surrounding measurements are insufficient|of 3|Terrain grade A/);
  assert.match(legendHTML('terrain'), /Interpreted rugose-rock area · unranked/);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { legendHTML, detailsHTML, VIEWS } from '../dist/seafloor-layer.js';

test('bedrock sheet explains original geology without claiming rugose boulders', () => {
  const html = detailsHTML({status: 'classified-area', classified_area: JSON.stringify({
    profile: 'original-interpreted-bedrock-area-v1',
    interpretation_method: 'original-interpreted-bedrock-v1',
  }), fit_lingcod: 'unknown'});
  assert.match(html, /exposed-bedrock habitat area/);
  assert.match(html, /Rugosity, boulder size, terrain grade and species fit are unknown/);
  assert.match(html, /processed survey window rather than a reef edge/);
  assert.doesNotMatch(html, /interprets rugose rock and boulders/);
  assert.match(legendHTML('terrain'), /Interpreted rock habitat · unranked/);
});

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
  assert.match(legendHTML('terrain'), /Interpreted rock habitat · unranked/);
});
test('map movement during delayed archive initialization or refresh cannot draw before legend/header mount',async t=>{
 const {initSeafloor}=await import('../dist/seafloor-layer.js');
 const elements=new Map();for(const id of ['species-select','layer-seafloor','layer-seafloor-cells','seafloor-view','seafloor-status','seafloor-options']){
  const handlers={};elements.set(id,{value:id==='species-select'?'reef':'terrain',checked:false,hidden:false,textContent:'',add(){},addEventListener(name,fn){handlers[name]=fn;},removeEventListener(){},change(){handlers.change?.();}});
 }
 const saved={document:globalThis.document,L:globalThis.L,Option:globalThis.Option,pmtiles:globalThis.pmtiles,location:globalThis.location};t.after(()=>Object.assign(globalThis,saved));
 globalThis.document={getElementById:id=>elements.get(id)};globalThis.Option=class{constructor(label,id){this.value=id;}};globalThis.location={href:'https://skippercast.com/'};
 let clears=0,mounted=false,legendHost,legendWrites=0,headerReads=0,release;
 const layer=()=>({addTo(){return this;},remove(){},clearLayers(){clears++;}});
 globalThis.L={canvas:()=>({}),layerGroup:layer,control:()=>({addTo(){mounted=true;legendHost={set innerHTML(value){legendWrites++;}};return this;},remove(){mounted=false;},getContainer:()=>legendHost})};
 const handlers={};const map={createPane:()=>({style:{}}),on(name,fn){handlers[name]=fn;},off(){},getZoom:()=>9,invalidateSize(){return handlers.moveend?.();}};
 let headerWait=new Promise(resolve=>{release=resolve;});globalThis.pmtiles={PMTiles:class{async getHeader(){headerReads++;await headerWait;return {};}}};
 const ready={status:'ready',region:'morro-bay',archive_sha256:'a'.repeat(64),expires_at:'2099-01-01T00:00:00Z',layers:{habitat:9}};
 const reader=initSeafloor(map,()=>{}, {fetchImpl:async()=>Response.json(ready),setTimeoutImpl:()=>0,clearTimeoutImpl:()=>{}});t.after(()=>reader.dispose());const settle=()=>new Promise(resolve=>setImmediate(resolve));await settle();
 assert.equal(reader.state(),'ready','publication admission can precede display readiness');assert.equal(mounted,false);assert.equal(headerReads,1);
 await assert.doesNotReject(async()=>map.invalidateSize());assert.equal(clears,0);assert.equal(legendWrites,0);
 release();await settle();assert.equal(mounted,true);assert.equal(legendWrites,1);assert.equal(clears,2);
 // Real Leaflet retains the old control container after removal. A truthy
 // getContainer alone therefore cannot authorize drawing during a refresh.
 headerWait=new Promise(resolve=>{release=resolve;});const refresh=reader.enable();await settle();assert.equal(mounted,false);assert.ok(legendHost);const previous={clears,legendWrites,headerReads};
 await assert.doesNotReject(async()=>map.invalidateSize());assert.deepEqual({clears,legendWrites,headerReads},previous);
 release();await refresh;assert.equal(mounted,true);assert.equal(legendWrites,previous.legendWrites+1);assert.equal(clears,previous.clears+2);
 reader.dispose();await assert.doesNotReject(async()=>reader.draw());assert.equal(mounted,false);
});

// ---- v2 Chart layer (FE-14, web/map/seafloor.ts) over tests/fixtures/seafloor/chart.pmtiles
// (synthetic; built by build-chart.mjs). A fake engine records which MapLibre
// layers turn on and off and what the GeoJSON source holds.
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {PMTiles} from 'pmtiles';
import {decodeTile as decodeV2, dedupeById as dedupeV2, manifestState, tileFeatures as tileFeaturesV2} from '../dist/seafloor-data.js';
import {
  EXPIRED, INCOMPLETE, NO_PUBLICATION, SEAFLOOR_LAYERS, SEAFLOOR_SOURCE, admitCell, admitHabitat, createSeafloor, fitKey, legendKey,
  publicationRights, seafloorLayers, seafloorMark, seafloorState, seafloorView, surveyLine, toneOf, viewBounds,
} from '../web/map/seafloor.ts';
import {readPalette} from '../web/map/palette.ts';
import {camera} from '../web/map/stage.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const FIXTURE = readFileSync(new URL('./fixtures/seafloor/chart.pmtiles', import.meta.url));
/** The fixture archive; `bounds` widens its header (a region larger than the two tiles it holds). */
const fixtureReader = (hold = null, bounds = null) => {
  const archive = new PMTiles({getKey: () => 'fixture', getBytes: async (offset, length) => ({data: FIXTURE.buffer.slice(FIXTURE.byteOffset + offset, FIXTURE.byteOffset + offset + length)})});
  return {async getHeader() { return {...await archive.getHeader(), ...bounds}; }, async getZxy(z, x, y) { if (hold) await hold.promise; return archive.getZxy(z, x, y); }};
};
async function fixtureFeatures() {
  const reader = fixtureReader(), habitat = [], cells = [];
  for (const x of [671, 672]) {
    const decoded = decodeV2(new Uint8Array((await reader.getZxy(12, x, 1617)).data));
    habitat.push(...tileFeaturesV2(decoded, 'habitat', 12, x, 1617));
    cells.push(...tileFeaturesV2(decoded, 'cells', 12, x, 1617));
  }
  return {habitat: dedupeV2(habitat), cells: dedupeV2(cells)};
}
const MANIFEST_BASE = {schema_version: 1, region: 'morro-bay', status: 'ready', archive_sha256: 'a'.repeat(64), expires_at: '2099-01-01T00:00:00Z',
  source_attribution: ['Fixture Survey Lab'], source_use_notice: 'Retain source-specific terms and credits; mixed data do not become public-domain.',
  planning_notice: 'Planning only. Not a navigation chart. Check current CDFW regulations.'};
const LEDGER = JSON.stringify({region: 'morro-bay', reaches: [
  {id: 'morro-bay-fx1', region: 'morro-bay', status: 'habitat-screened'},
  {id: 'morro-bay-fx2', region: 'morro-bay', status: 'habitat-held-for-screen'},
  {id: 'morro-bay-fx3', region: 'morro-bay', status: 'unassessed'}]});
const LEDGER_SHA = createHash('sha256').update(LEDGER).digest('hex');
const PUB = {screened: new Set(['morro-bay-fx1']), rights: publicationRights(MANIFEST_BASE)};
const FORBIDDEN = /hotspot|chance|probabilit(?:y|ies)\b(?<!not catch probability)|bite|catch rate|productive|best spot/i;

test('v2: only screened, unheld, credited features of ledger-screened reaches are admitted, each with its basis and rights', async () => {
  const {habitat, cells} = await fixtureFeatures();
  const admitted = habitat.map(f => admitHabitat(f, PUB)).filter(Boolean);
  assert.deepEqual(admitted.map(f => [f.id, f.kind]), [
    ['fixture-candidate-a', 'candidate'], ['fixture-candidate-deep', 'candidate'], ['fixture-search', 'search'], ['fixture-interpreted', 'interpreted']]);
  assert.equal(admitted[0].geometry.coordinates.length, 2, 'the candidate split across two tiles is one feature');
  for (const f of admitted) {
    assert.match(f.basis, /fish presence is unverified\.$/, `${f.id} basis`);
    assert.doesNotMatch(f.basis, FORBIDDEN);
    assert.deepEqual(f.rights.map(r => r.credit), ['Fixture Survey Lab'], `${f.id} carries its source rights`);
    assert.equal(f.rights[0].policyURL, 'https://example.org/terms');
  }
  assert.match(admitted[0].basis, /^Habitat candidate, unverified\. Nominal depth \(NAVD88\); verify on your sounder\. Terrain screening of survey fixture-survey-2m, 2010, on a 2 m grid;/);
  assert.match(admitted[2].basis, /^Measured rough-bottom search area, unranked: .* Nominal depth \(NAVD88\); search with your sounder\./);
  assert.match(admitted[3].basis, /^Publisher-interpreted rugose-rock habitat area, unranked: .* Within the nominal 25–300 ft band \(vertical datum unknown\); verify on your sounder\./);
  // Each gate on its own: a held reach, a held screen, hold reasons, missing rights, an unpublished status.
  const a = habitat[0].properties, as = properties => admitHabitat({...habitat[0], properties: {...a, ...properties}}, PUB);
  assert.ok(as({}));
  for (const [name, change] of [['held reach', {reach: 'morro-bay-fx2'}], ['unlisted reach', {reach: 'morro-bay-r99'}], ['screen held', {screen: '{"status":"held"}'}],
    ['no screen', {screen: undefined}], ['hold reason', {hold_reasons: '["overlap-cdfw-mpa"]'}], ['no hold list', {hold_reasons: undefined}],
    ['quality hold', {habitat_quality_hold: true}], ['no rights', {source_rights: '[]'}], ['bad rights', {source_rights: '[{"source_id":"x"}]'}],
    ['held status', {status: 'held'}], ['prototype status', {status: 'constructor'}], ['no id', {id: ''}]]) assert.equal(as(change), null, name);
  assert.deepEqual(cells.map(f => admitCell(f, PUB)?.id ?? null), ['cell:3310:fx:1', null, null, null], 'tier-0 water stays blank; held and unscreened reaches\' cells never draw');
  const cell = admitCell(cells[0], PUB);
  assert.deepEqual(cell.rights.map(r => r.credit), ['Fixture Survey Lab']);
  assert.match(cell.basis, /coverage only, with no habitat rank\.$/);
  assert.equal(admitCell(cells[0], {...PUB, rights: publicationRights({source_attribution: ['x']})}), null, 'cells need the publication\'s credits and use notice');
});

test('v2: grade and fit draw on the depth ramp from palette tokens; the key keeps v1\'s words', async () => {
  const {habitat} = await fixtureFeatures();
  const [a, deep, search, , , interpreted] = habitat.map(f => admitHabitat(f, PUB));
  assert.deepEqual([toneOf(a, 'terrain'), toneOf(a, 'fit_lingcod'), toneOf(deep, 'terrain'), toneOf(deep, 'fit_lingcod'), toneOf(a, 'fit_gopher_rockfish')],
    ['strong', 'strong', 'some', 'some', 'unknown']);
  assert.deepEqual([toneOf(search, 'fit_lingcod'), toneOf(interpreted, 'terrain')], ['search', 'interpreted']);
  assert.deepEqual([fitKey('lingcod', 'boat'), fitKey('rockfish', 'boat'), fitKey(null, 'spear'), fitKey('reef', 'boat')],
    ['fit_lingcod', 'fit_rockfish_reef', 'fit_cabezon_shallow_reef', null]);
  const sentinel = readPalette(name => `token(${name})`), layers = seafloorLayers(sentinel);
  assert.deepEqual(layers.map(l => l.id), [...SEAFLOOR_LAYERS]);
  assert.ok(layers.every(l => l.source === SEAFLOOR_SOURCE && l.layout.visibility === 'none'), 'hidden until the publication admits something');
  const color = layers[1].paint['fill-color'], outputs = Object.fromEntries(color.slice(2, -1).reduce((pairs, v, i, all) => i % 2 ? pairs : [...pairs, [v, all[i + 1]]], []));
  assert.deepEqual(outputs, {strong: 'token(depth-0)', moderate: 'token(depth-1)', some: 'token(depth-2)', search: 'token(amber)', interpreted: 'token(blue)'});
  assert.equal(color.at(-1), 'token(muted)');
  assert.equal(layers[0].paint['fill-color'], 'token(depth-3)', 'cells are the deepest step');
  for (const l of layers) for (const [key, value] of Object.entries(l.paint)) if (key.endsWith('color')) {
    for (const v of [value].flat(Infinity)) if (typeof v === 'string' && /^[#(]|rgb|hsl/.test(v)) assert.fail(`${l.id} ${key} has a literal colour ${v}`);
  }
  assert.deepEqual(layers.slice(2).map(l => l.paint['line-dasharray'] ?? null), [null, [3, 2]], 'unranked areas are dashed');
  const terrain = legendKey('terrain'), fit = legendKey('fit');
  assert.deepEqual(terrain.slice(0, 3).map(([, label]) => label), Object.values(GRADE_STYLE).map(s => s.label));
  assert.deepEqual(fit.slice(0, 3).map(([, label]) => label), Object.values(FIT_STYLE).map(s => s.label).reverse());
  for (const [, label] of [...terrain, ...fit]) assert.doesNotMatch(label, FORBIDDEN);
  assert.equal(surveyLine(['a (2010)']), 'Survey a (2010)');
  assert.equal(surveyLine(['a (2010)', 'b (2008)', 'c (2008)', 'd (2006)', 'e (2004)']), 'Surveys a (2010), b (2008), c (2008) and 2 more');
});

test('v2: the mark card names the candidate, its nominal depth, survey and year, and carries basis and credits', async () => {
  const {habitat} = await fixtureFeatures();
  const [a, , search] = habitat.map(f => admitHabitat(f, PUB));
  const mark = seafloorMark(a, 'fit_lingcod');
  assert.deepEqual({...mark, basis: undefined}, {id: 'seafloor:fixture-candidate-a', name: 'Habitat candidate, unverified',
    kind: 'Terrain grade A · fits lingcod habitat 3 of 3', reading: '41–90 ft nominal', source: 'Survey fixture-survey-2m · 2010 · 2 m grid', basis: undefined});
  assert.ok(mark.basis.startsWith(a.basis));
  assert.match(mark.basis, /Fixture Survey Lab Synthetic test credit; never survey data\. Planning only\. Not a navigation chart\. Check current CDFW regulations\.$/);
  assert.equal(seafloorMark(a, 'terrain').kind, 'Terrain grade A');
  assert.equal(seafloorMark(a, 'fit_gopher_rockfish').kind, 'Terrain grade A · gopher rockfish fit unknown');
  assert.equal(seafloorMark(search, 'fit_lingcod').kind, 'Rough-bottom search area · unranked');
  assert.equal(seafloorMark(search, 'fit_lingcod').name, 'Measured rough-bottom search area');
  for (const m of [mark, seafloorMark(search, 'terrain')]) assert.doesNotMatch(Object.values(m).join(' '), FORBIDDEN);
});

test('v2: view bounds follow web-mercator spans for a north-up camera', () => {
  const [w, s, e, n] = viewBounds({latitude: 0, longitude: 0, zoom: 12}, 256, 256);
  assert.ok(Math.abs(e - w - 360 / 4096) < 1e-12 && Math.abs(w + 180 / 4096) < 1e-12);
  assert.ok(Math.abs(n + s) < 1e-12 && n > 0);
  const world = viewBounds({latitude: 0, longitude: 0, zoom: 0}, 256, 256);
  assert.ok(Math.abs(world[3] - 85.0511287798) < 1e-6, 'the whole Mercator world at zoom 0');
});

const PAGE_V2 = 'https://s.test/map';
const settle = () => new Promise(resolve => setTimeout(resolve, 25));
/** A seafloor layer over the fixture with injected feeds, clock and timers. */
function seafloorRig({manifest = {}, ledger = LEDGER, profile = 'boat', layers = 'seafloor', target = '', bounds = null} = {}) {
  configureStore({v2: true, storage: null});
  const url = layers => `${PAGE_V2}?region=morro-bay&profile=${profile}&layers=${layers}${target ? `&target=${target}` : ''}`;
  syncFromURL(url(layers));
  camera.value = {latitude: 35.353, longitude: -120.948, zoom: 13};
  seafloorView.value = 'fit';
  const rig = {
    clock: Date.parse('2030-01-01T00:00:00Z'), timers: new Map(), next: 0, requests: [], opened: [], calls: [], data: null, hold: null, tileHold: null,
    manifest: {...MANIFEST_BASE, ledger_sha256: createHash('sha256').update(ledger).digest('hex'), ...manifest}, ledger,
    layers: value => syncFromURL(url(value)),
    async fire() { const [id, t] = rig.timers.entries().next().value; rig.timers.delete(id); t.fn(); await settle(); },
  };
  rig.layer = createSeafloor({
    engine: {setVisible: (id, on) => rig.calls.push(['visible', id, on]), setData: (id, data) => { rig.calls.push(['data', id, data.features.length]); rig.data = data; }},
    open: url => { rig.opened.push(url); return fixtureReader(rig.tileHold, bounds); }, size: () => ({width: 1000, height: 700}), page: () => PAGE_V2, now: () => rig.clock,
    setTimer: (fn, delay) => { const id = ++rig.next; rig.timers.set(id, {fn, delay}); return id; }, clearTimer: id => rig.timers.delete(id),
    fetchFn: async url => {
      rig.requests.push(url);
      await null;  // the test may change the feeds right after creating the layer
      if (rig.hold) await rig.hold.promise;
      if (url === '/feeds/tiles/seafloor/manifest-morro-bay.json') return rig.manifest === 404 ? new Response('{}', {status: 404}) : Response.json(rig.manifest);
      if (url === '/feeds/tiles/seafloor/regions/morro-bay/ledger.json') return new Response(rig.ledger);
      return new Response('{}', {status: 404});
    },
  });
  return rig;
}
const deferred = () => { let release; const promise = new Promise(resolve => { release = resolve; }); return {promise, release}; };
const drawnIds = rig => rig.data.features.map(f => f.properties.id).sort();

test('v2: toggling Seafloor adds and removes exactly its layers; held reaches and held features never draw', async t => {
  const rig = seafloorRig({layers: 'currents'});
  t.after(() => rig.layer.destroy());
  await settle();
  assert.deepEqual(rig.calls, [], 'off: no layer touched');
  assert.deepEqual(rig.requests, [], 'off: no publication request');
  assert.equal(seafloorState.value.status, 'off');

  rig.layers('seafloor,currents');
  await settle();
  assert.deepEqual(rig.requests, ['/feeds/tiles/seafloor/manifest-morro-bay.json', '/feeds/tiles/seafloor/regions/morro-bay/ledger.json']);
  assert.deepEqual(rig.opened, ['https://s.test/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles']);
  assert.deepEqual(rig.calls.filter(c => c[0] === 'visible'), SEAFLOOR_LAYERS.map(id => ['visible', id, true]), 'exactly the seafloor layers turn on');
  assert.deepEqual(drawnIds(rig), ['cell:3310:fx:1', 'fixture-candidate-a', 'fixture-candidate-deep', 'fixture-interpreted', 'fixture-search']);
  assert.deepEqual(Object.fromEntries(rig.data.features.map(f => [f.properties.id, f.properties.tone])), {
    'cell:3310:fx:1': 'cell', 'fixture-candidate-a': 'strong', 'fixture-candidate-deep': 'some', 'fixture-interpreted': 'interpreted', 'fixture-search': 'search'});
  const state = seafloorState.value;
  assert.deepEqual({...state, note: undefined}, {status: 'ready', note: undefined, view: 'fit', fit: 'lingcod', drawn: 5,
    surveys: ['fixture-survey-2m (2010)', 'fixture-survey-2m (unknown)'], credits: ['Fixture Survey Lab']});
  assert.equal(state.note, '2 candidates · 2 unranked in view');
  assert.equal(rig.layer.mark('fixture-candidate-a').kind, 'Terrain grade A · fits lingcod habitat 3 of 3');
  for (const id of ['fixture-held', 'fixture-held-reach', 'fixture-uncredited', '3310:fx:2']) assert.equal(rig.layer.mark(id), null, id);

  seafloorView.value = 'terrain';
  await settle();
  assert.equal(seafloorState.value.view, 'terrain');
  assert.equal(rig.layer.mark('fixture-candidate-a').kind, 'Terrain grade A');
  assert.equal(rig.opened.length, 1, 'a view change reuses the archive');

  rig.calls.length = 0;
  rig.layers('currents');
  await settle();
  assert.deepEqual(rig.calls, [...SEAFLOOR_LAYERS.map(id => ['visible', id, false]), ['data', SEAFLOOR_SOURCE, 0]], 'exactly the seafloor layers turn off and empty');
  assert.equal(rig.layer.mark('fixture-candidate-a'), null);
  assert.equal(seafloorState.value.status, 'off');
  assert.equal(rig.timers.size, 0, 'off cancels the expiry check');
});

test('v2: a view with cells and no candidates empties the source when it zooms out, leaves the archive or needs too many tiles', async t => {
  const onlyCells = LEDGER.replace('"morro-bay-fx1","region":"morro-bay","status":"habitat-screened"', '"morro-bay-fx1","region":"morro-bay","status":"terrain-pending"')
    .replace('"morro-bay-fx3","region":"morro-bay","status":"unassessed"', '"morro-bay-fx3","region":"morro-bay","status":"habitat-screened"');
  assert.notEqual(onlyCells, LEDGER);
  const rig = seafloorRig({ledger: onlyCells, bounds: {minLon: -122, minLat: 34.5, maxLon: -120, maxLat: 36}});
  t.after(() => rig.layer.destroy());
  await settle();
  assert.deepEqual(drawnIds(rig), ['cell:3310:fx:3'], 'only the screened reach\'s cell');
  assert.equal(seafloorState.value.note, '0 candidates · 0 unranked in view');
  for (const [move, note] of [
    [{latitude: 35.353, longitude: -120.948, zoom: 9}, 'Zoom in to see seafloor candidates'],
    [{latitude: 35.0, longitude: -122.5, zoom: 13}, 'No published seafloor survey in this view; the rest of the coast is unassessed'],
    [{latitude: 35.353, longitude: -120.948, zoom: 10.5}, 'Zoom in to load seafloor candidates'],
  ]) {
    camera.value = {latitude: 35.353, longitude: -120.948, zoom: 13};
    await settle();
    assert.deepEqual(drawnIds(rig), ['cell:3310:fx:3'], 'drawn again');
    rig.calls.length = 0;
    camera.value = move;
    await settle();
    assert.deepEqual(rig.calls, [['data', SEAFLOOR_SOURCE, 0]], `${note}: the cells leave the map`);
    assert.equal(seafloorState.value.note, note);
  }
});

test('v2: Spear leaves out candidates deeper than its limit; a target without published fit draws terrain grade', async t => {
  const rig = seafloorRig({profile: 'spear'});
  t.after(() => rig.layer.destroy());
  await settle();
  assert.deepEqual(drawnIds(rig), ['cell:3310:fx:1', 'fixture-candidate-a', 'fixture-interpreted', 'fixture-search']);
  assert.equal(seafloorState.value.note, '1 candidate · 2 unranked in view · 1 deeper than the Spear limit (60 ft nominal) left out');
  assert.deepEqual([seafloorState.value.view, seafloorState.value.fit], ['terrain', null], 'cabezon fit is not in this publication');
});

test('v2: held, updating, unpublished and ledger-mismatched publications draw nothing, with v1\'s messages', async t => {
  const held = seafloorRig({manifest: {status: 'held'}});
  await settle();
  held.layer.destroy();
  assert.deepEqual([held.calls, held.opened, held.timers.size], [[], [], 0]);
  assert.equal(held.requests.length, 1, 'a held manifest is the end: no ledger, no archive');

  const updating = seafloorRig({manifest: {status: 'updating'}});
  t.after(() => updating.layer.destroy());
  await settle();
  assert.equal(seafloorState.value.status, 'updating');
  assert.equal(seafloorState.value.note, 'Seafloor layer is updating; try again shortly · retrying in 30s');
  assert.deepEqual([...updating.timers.values()].map(v => v.delay), [30000]);
  assert.deepEqual(updating.calls, []);
  updating.manifest = {...updating.manifest, status: 'ready'};
  await updating.fire();
  assert.equal(seafloorState.value.status, 'ready', 'recovers on the retry');
  assert.ok(updating.data.features.length > 0);
  updating.layer.destroy();

  const mismatch = seafloorRig({ledger: LEDGER});
  mismatch.ledger = LEDGER.replace('habitat-held-for-screen', 'habitat-screened');
  t.after(() => mismatch.layer.destroy());
  await settle();
  assert.equal(seafloorState.value.status, 'unavailable');
  assert.equal(seafloorState.value.note, `${INCOMPLETE} · retrying in 30s`, 'a ledger that is not the manifest\'s never unlocks a reach');
  assert.deepEqual([mismatch.calls, mismatch.opened], [[], []]);
  mismatch.layer.destroy();

  const none = seafloorRig({});
  none.manifest = 404;
  t.after(() => none.layer.destroy());
  await settle();
  assert.deepEqual([seafloorState.value.status, seafloorState.value.note, none.timers.size], ['unavailable', NO_PUBLICATION, 0]);
  none.layer.destroy();

  for (const status of ['held', 'expired']) {
    const reason = manifestState(status === 'held' ? {status} : {...MANIFEST_BASE, expires_at: '2000-01-01T00:00:00Z'}, 'morro-bay').reason;
    const rig = seafloorRig({manifest: status === 'held' ? {status} : {expires_at: '2000-01-01T00:00:00Z'}});
    await settle();
    assert.deepEqual([seafloorState.value.status, seafloorState.value.note, rig.calls.length], [status, reason, 0]);
    rig.layer.destroy();
  }
  assert.equal(EXPIRED, manifestState({...MANIFEST_BASE, expires_at: '2000-01-01T00:00:00Z'}, 'morro-bay').reason);
});

test('v2: expiry hides candidates before the refresh answers, and a late tile never draws (the #395 race fix)', async t => {
  const rig = seafloorRig({manifest: {expires_at: '2030-01-01T00:01:00Z'}});
  t.after(() => rig.layer.destroy());
  await settle();
  assert.ok(rig.data.features.length > 0);
  assert.deepEqual([...rig.timers.values()].map(v => v.delay), [60000], 'the expiry check is scheduled');
  rig.hold = deferred();
  rig.clock = Date.parse('2030-01-01T00:01:00Z');
  rig.calls.length = 0;
  const [id, timer] = rig.timers.entries().next().value;
  rig.timers.delete(id);
  timer.fn();
  assert.deepEqual(rig.calls, [...SEAFLOOR_LAYERS.map(l => ['visible', l, false]), ['data', SEAFLOOR_SOURCE, 0]], 'hidden synchronously, before the refresh answers');
  assert.equal(seafloorState.value.status, 'checking');
  rig.hold.release(); rig.hold = null;
  await settle();
  assert.deepEqual([seafloorState.value.status, seafloorState.value.note], ['expired', EXPIRED]);
  assert.equal(rig.calls.length, SEAFLOOR_LAYERS.length + 1, 'nothing drawn after expiry');

  // A clock past expiry with no timer (a sleeping tab) hides on the next draw.
  const asleep = seafloorRig({manifest: {expires_at: '2030-01-01T00:01:00Z'}});
  t.after(() => asleep.layer.destroy());
  await settle();
  asleep.clock = Date.parse('2030-01-01T00:02:00Z');
  asleep.calls.length = 0;
  camera.value = {latitude: 35.35, longitude: -120.95, zoom: 13};
  await settle();
  assert.deepEqual(asleep.calls, [...SEAFLOOR_LAYERS.map(l => ['visible', l, false]), ['data', SEAFLOOR_SOURCE, 0]]);
  assert.deepEqual([seafloorState.value.status, seafloorState.value.note], ['expired', EXPIRED]);
  asleep.layer.destroy();

  // Tiles still loading when the layer turns off never reach the map.
  const late = seafloorRig({});
  t.after(() => late.layer.destroy());
  late.tileHold = deferred();
  await settle();
  assert.equal(late.data, null, 'still loading');
  late.layers('currents');
  await settle();
  late.tileHold.release();
  await settle();
  assert.ok(late.calls.every(c => c[0] !== 'data' || c[2] === 0), 'no features after off');
});

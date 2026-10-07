import test from 'node:test';
import assert from 'node:assert/strict';
import {coastTarget,hasCoastTerrain,presentationFromURL,presentationURL,habitatURL} from '../web/coast-context.ts';

test('coast target aliases are explicit and unknown targets remain unavailable',()=>{
 for(const [a,b] of [['reef','all'],['rockfish','rockfish-reef'],['cabezon','cabezon-shallow-reef'],['surfperch','surfperch']])assert.equal(coastTarget(a),b);
 for(const id of ['salmon','tuna','lobster','constructor','__proto__',''])assert.equal(coastTarget(id),null);
});
test('terrain availability follows reviewed regional identity',()=>{
 for(const id of ['morro-bay','monterey-point-sur','point-arguello-conception','big-sur-coast'])assert.equal(hasCoastTerrain(id),true);
 for(const id of ['san-diego','southern-california','constructor',''])assert.equal(hasCoastTerrain(id),false);
});
test('presentation changes retain geographic, species, time, profile and planning state',()=>{
 const start='https://skippercast.com/?region=monterey-point-sur&target=rockfish&profile=spear&hour=2026-10-12T12:00Z&spot=synthetic-spot&habitat=123#export';
 const next=presentationURL(start,'2d');assert.equal(next.searchParams.get('presentation'),'2d');
 for(const key of ['region','target','profile','hour','spot','habitat'])assert.equal(next.searchParams.get(key),new URL(start).searchParams.get(key));
 assert.equal(next.hash,'#export');assert.deepEqual([...presentationURL(next.href,'chart').searchParams],[...new URL(start).searchParams]);
});
test('presentation parsing uses supported display states only',()=>{
 for(const mode of ['2d','3d'])assert.equal(presentationFromURL('https://example.test/?presentation='+mode),mode);
 for(const mode of ['','chart','constructor','unknown'])assert.equal(presentationFromURL('https://example.test/?presentation='+mode),'chart');
});
test('public habitat selection cannot overwrite atlas selection or geographic context',()=>{
 const start='https://example.test/?region=morro-bay&spot=atlas-1&target=lingcod#map';
 const next=habitatURL(start,'123');assert.equal(next.searchParams.get('habitat'),'123');assert.equal(next.searchParams.get('spot'),'atlas-1');assert.equal(next.searchParams.get('region'),'morro-bay');
 assert.equal(habitatURL(next.href,null).href,start);
 for(const id of ['../private','<script>','x'.repeat(161)])assert.equal(habitatURL(start,id).searchParams.has('habitat'),false);
});

// Execute the actual adapter with inert DOM/renderer dependencies. No network or GPU.
import {readFileSync} from 'node:fs';
const adapter=readFileSync(new URL('../dist/coast-workspace.js',import.meta.url),'utf8')
 .replace(/^import .*;\n/gm,'').replace('export function initCoastWorkspace','function initCoastWorkspace')
 .replace("await import('../packages/coast/src/coast3d/viewer.ts')",'await loadViewer()');
function element(){return {hidden:false,value:'lingcod',options:[{value:'chart'},{value:'2d'},{value:'3d'}],textContent:'',append(){},remove(){},setAttribute(){},listeners:{},addEventListener(k,f){this.listeners[k]=f},removeEventListener(k){delete this.listeners[k]},dataset:{}};}
async function workspace(ready=true,initialView='map'){
 const keys=['document','window','location','DOMParser','MutationObserver'],saved=Object.fromEntries(keys.map(k=>[k,globalThis[k]]));
 const nodes=new Map(),get=id=>nodes.get(id)??(nodes.set(id,element()),nodes.get(id));
 const root={querySelector:()=>element(),getElementById:get,querySelectorAll:()=>[],append(){}};
 get('coast-workspace').attachShadow=()=>root;get('map-presentation').value='chart';
 const doc={getElementById:get,createElement:element,importNode:x=>x,body:{dataset:{view:initialView}},hidden:false,listeners:{},addEventListener(k,f){this.listeners[k]=f},removeEventListener(k){delete this.listeners[k]}};
 const win={listeners:{},addEventListener(k,f){this.listeners[k]=f},removeEventListener(k){delete this.listeners[k]}};
 Object.assign(globalThis,{document:doc,window:win,location:{href:'https://example.test/?region=morro-bay#map'},DOMParser:class{parseFromString(){return {getElementById:get}}},MutationObserver:class{observe(){}disconnect(){}}});
 let viewer;class FakeViewer{constructor(host,options){viewer=this;this.options=options;this.hours=[];this.positions=[];this.visibility=[];this.loads=0;}setSpecies(){}setDepthLimit(){}setLocation(p){this.positions.push(p)}setHour(at){this.hours.push(at)}setPerspective(){}selectHabitat(id){this.selection=id}setVisible(v){this.visibility.push(v)}load(){this.loads++;return Promise.resolve(ready)}destroy(){}}
 const factory=new Function('getRegion','navigate','profile','setParams','effect','coastPath','coastTarget','hasCoastTerrain','presentationFromURL','presentationURL','habitatURL','loadViewer','const template="",viewStyles="/synthetic.css";'+adapter+'\nreturn initCoastWorkspace;');
 const init=factory(()=>({id:'morro-bay'}),url=>location.href=String(url),{value:'boat'},()=>{},fn=>{fn();return()=>{}},x=>x,coastTarget,hasCoastTerrain,presentationFromURL,presentationURL,habitatURL,async()=>({CoastViewer:FakeViewer}));
 let invalidations=0,zoom=12,center={lat:35.43,lng:-120.98};const map={getCenter:()=>center,getZoom:()=>zoom,setView(p,z){center=Array.isArray(p)?{lat:p[0],lng:p[1]}:p;zoom=z},invalidateSize(){invalidations++}};
 const handle=init({map,locationUI:{get:()=>null,select(p){assert.deepEqual(center,{lat:p.latitude,lng:p.longitude},'Move the map before publishing source metadata');},clear(){}},weather:{getHour:()=>1791288000}});
 const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
 return {get,doc,map,flush,invalidations:()=>invalidations,change:async mode=>{get('map-presentation').value=mode;get('map-presentation').listeners.change();await flush();},viewer:()=>viewer,setZoom:z=>zoom=z,cleanup:()=>{handle.destroy();Object.assign(globalThis,saved);}};
}
test('a failed terrain load retains chart fallback on every later selection',async()=>{
 const s=await workspace(false);try{await s.change('2d');assert.equal(s.get('coast-workspace').hidden,true);await s.change('3d');assert.equal(s.get('coast-workspace').hidden,true);assert.equal(s.get('map-presentation').value,'chart');assert.equal(s.get('map-presentation-status').hidden,false);assert.equal(s.viewer().loads,1);}finally{s.cleanup();}
});
test('terrain follows selected UTC time even without a usable forecast model',async()=>{
 const s=await workspace();try{await s.change('2d');assert.equal(s.viewer().hours.at(-1).getTime(),1791288000000);s.doc.listeners['skippercast:time']({detail:{epoch:1791892800,regionId:'morro-bay'}});assert.equal(s.viewer().hours.at(-1).getTime(),1791892800000);s.doc.listeners['skippercast:time']({detail:{epoch:1791896400,regionId:'monterey-point-sur'}});assert.equal(s.viewer().hours.at(-1).getTime(),1791892800000);}finally{s.cleanup();}
});
test('chart scale changes at a fixed center reach terrain and native view does not loop',async()=>{
 const s=await workspace();try{await s.change('3d');await s.change('chart');s.setZoom(14);s.doc.listeners['skippercast:location']({detail:{regionId:'morro-bay',point:{latitude:35.43,longitude:-120.98}}});assert.equal(s.viewer().positions.at(-1).span,1825);const before=s.viewer().positions.length;s.viewer().options.onView({latitude:35.43,longitude:-120.98,span:3650});s.doc.listeners['skippercast:location']({detail:{regionId:'morro-bay',point:{latitude:35.43,longitude:-120.98}}});assert.equal(s.viewer().positions.length,before);assert.equal(s.map.getZoom(),13);}finally{s.cleanup();}
});
test('closing habitat and resetting home remove shared public selection identity',async()=>{
 const s=await workspace();try{await s.change('3d');s.viewer().options.onSelection({latitude:35.43,longitude:-120.98,id:'123',region:'morro-bay'});assert.equal(new URL(location.href).searchParams.get('habitat'),'123');s.get('target-close').onclick();assert.equal(new URL(location.href).searchParams.has('habitat'),false);assert.equal(s.viewer().selection,null);s.viewer().options.onSelection({latitude:35.45,longitude:-120.99,id:'456',region:'morro-bay'});s.get('reset').onclick();assert.equal(new URL(location.href).searchParams.has('habitat'),false);assert.equal(s.viewer().selection,null);assert.equal(s.map.getCenter().lat,35.43);}finally{s.cleanup();}
});

test('finishing a delayed terrain load cannot restart a hidden tab',async()=>{
 let resolve;const loading=new Promise(done=>resolve=done),s=await workspace(loading);
 try{await s.change('3d');s.doc.hidden=true;s.doc.listeners.visibilitychange();resolve(true);await s.flush();assert.equal(s.viewer().visibility.at(-1),false);}finally{s.cleanup();}
});

test('initial chart adapter cannot resize a chart hidden by Conditions or Export',async()=>{for(const initialView of ['forecast','export']){const w=await workspace(true,initialView);try{assert.equal(w.invalidations(),0);}finally{w.cleanup();}}});

test('unsupported scoped UTC hour reaches terrain as a gap instead of retaining the old hour',async()=>{const s=await workspace();try{await s.change('2d');s.doc.listeners['skippercast:time']({detail:{epoch:NaN,regionId:'morro-bay'}});assert.ok(Number.isNaN(s.viewer().hours.at(-1).getTime()));}finally{s.cleanup()}});

test('native feature selection publishes metadata after moving the chart and preserves original shared coordinates',async()=>{const s=await workspace();try{await s.change('2d');const p={id:'original',region:'morro-bay',latitude:35.37866518735354,longitude:-120.8749234607946};s.viewer().options.onSelection(p);const u=new URL(location.href);assert.equal(u.searchParams.get('habitat'),'original');assert.equal(u.searchParams.get('view'),'35.37867,-120.87492,12');}finally{s.cleanup()}});

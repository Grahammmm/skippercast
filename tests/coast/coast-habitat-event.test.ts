// NB-SC-02: onHabitat tells a host-chrome embed what the native habitat rail shows
// (status line + up to 12 ranked reefs), and exploreNext() runs "Explore a ranked reef".
import test from 'node:test';
import assert from 'node:assert/strict';
import * as T from 'three';
import {CoastViewer} from '../../packages/coast/src/coast3d/viewer.ts';
import {mountCoast,type CoastHabitat} from '../../packages/coast/src/embed.ts';

type El={[key:string]:any};
const element=():El=>({children:[] as El[],dataset:{},hidden:false,textContent:'',append(...nodes:El[]){this.children.push(...nodes);},replaceChildren(){this.children=[];},remove(){},setAttribute(key:string,value:string){this[key]=value;},closest(){return element();}});
// The coast-embedded.test.ts harness: real viewer state methods, no WebGL, fetch or timers.
function harness(onHabitat?:(habitat:CoastHabitat)=>void){
 const nodes=new Map<string,El>(),node=(id:string)=>{if(!nodes.has(id))nodes.set(id,{...element(),value:'all',checked:true});return nodes.get(id)!;};
 const v:any=Object.create(CoastViewer.prototype),selections:any[]=[];let moves=0;
 Object.assign(v,{root:{querySelector:(selector:string)=>node(selector.slice(5,-2))},options:{managed:true,onHabitat,onSelection:(s:any)=>selections.push(s)},host:{dataset:{},clientWidth:800,clientHeight:600},alive:true,visible:true,speciesSupported:true,habitat:new T.Group(),currents:new T.Group(),pins:[],labels:[],features:[],allFeatures:[],shoreFeatures:[],reviewed:{manifest:{expiresAt:'2099-01-01T00:00:00Z',regions:[]}},selectedTarget:null,reefIndex:0,readingGeneration:0,depthLimit:300,habitatGeneration:0,currentGeneration:0,controls:{target:new T.Vector3(),update(){}}});
 v.refine=()=>{};v.drawPins=()=>{};v.moveTo=()=>moves++;
 return {v,node,selections,moves:()=>moves};
}
const reef=(i:number)=>({id:'reef-'+i,properties:{exportable:true,screen_status:'pass',screen_expires_at:'2099-01-01T00:00:00Z',terrain_score:90-i/10,terrain_grade:i%2?'B':'A',region:'morro-bay',depth_min_ft:20+i,depth_max_ft:40+i,waypoint_latitude:35.37,waypoint_longitude:-120.87},geometry:{type:'Polygon',coordinates:[[[-120.87,35.37],[-120.86,35.37],[-120.86,35.38],[-120.87,35.37]]]}});
const shore={id:'shore-1',properties:{id:'shore-1',name:'Original shore',areaId:'south',access:[{coordinates:[-120.76,35.16]}]},geometry:{coordinates:[[[-120.76,35.16],[-120.75,35.15]]]}};
function withDom<R>(run:()=>R):R{
 const saved=Object.getOwnPropertyDescriptor(globalThis,'document');Object.defineProperty(globalThis,'document',{configurable:true,value:{createElement:element}});
 try{return run();}finally{if(saved)Object.defineProperty(globalThis,'document',saved);else delete (globalThis as any).document;}
}
const bindNative=(v:any,node:(id:string)=>El)=>{
 node('species').options=[];v.renderer={domElement:{addEventListener(){}}};const saved=Object.getOwnPropertyDescriptor(globalThis,'window');
 Object.defineProperty(globalThis,'window',{configurable:true,value:{addEventListener(){}}});try{v.bind();}finally{if(saved)Object.defineProperty(globalThis,'window',saved);else delete (globalThis as any).window;}
};

test('ranked reefs: one ok event with the rail buttons\' text in order, status equal to the native line',()=>{
 const events:CoastHabitat[]=[],{v,node}=harness(h=>events.push(h));v.allFeatures=[reef(2),reef(0),reef(1)];
 withDom(()=>v.drawHabitat());
 assert.equal(events.length,1);const [h]=events;
 assert.equal(h!.state,'ok');assert.equal(h!.canExplore,true);assert.equal(h!.status,node('habitat-status').textContent);
 assert.match(h!.status,/^3 screened reef footprints · /);
 assert.deepEqual(h!.ranks.map(r=>r.id),['reef-0','reef-1','reef-2']);
 const buttons=node('rank-list').children;assert.equal(buttons.length,3);
 buttons.forEach((button:El,i:number)=>{assert.equal(button.children[0].textContent,h!.ranks[i]!.title);assert.equal(button.children[1].textContent,h!.ranks[i]!.detail);});
 assert.equal(h!.ranks[0]!.title,'1. Morro / Estero reef · grade A');assert.equal(h!.ranks[1]!.detail,'21–41 ft · screened · terrain 89.9/100');
});

test('more than 12 ranked reefs: exactly the 12 the rail lists',()=>{
 const events:CoastHabitat[]=[],{v,node}=harness(h=>events.push(h));v.allFeatures=Array.from({length:15},(_,i)=>reef(i));
 withDom(()=>v.drawHabitat());
 assert.equal(events.length,1);assert.equal(events[0]!.ranks.length,12);assert.equal(node('rank-list').children.length,12);
 assert.equal(events[0]!.ranks.at(-1)!.id,'reef-11');assert.match(events[0]!.status,/^15 screened/);assert.equal(events[0]!.canExplore,true);
});

test('unsupported species: unavailable, no ranks, nothing to explore, the exact native sentence',()=>{
 const events:CoastHabitat[]=[],{v,node}=harness(h=>events.push(h));v.allFeatures=[reef(0)];
 withDom(()=>v.drawHabitat());assert.equal(v.setSpecies('albacore'),false);
 assert.equal(events.length,2);
 assert.deepEqual(events[1],{status:'Terrain habitat unavailable for this target. No substitute species is assumed.',state:'unavailable',ranks:[],canExplore:false});
 assert.equal(node('habitat-status').textContent,events[1]!.status);assert.equal(v.exploreNext(),false);
});

test('load failure and withheld overlays: withheld, each with its own sentence, ranks cleared',async()=>{
 const events:CoastHabitat[]=[],{v,node}=harness(h=>events.push(h));v.reviewed=null;
 const prior=globalThis.fetch;globalThis.fetch=(async()=>new Response('held source',{status:503})) as typeof fetch;
 try{await (CoastViewer.prototype as any).refreshHabitat.call(v);}finally{globalThis.fetch=prior;}
 assert.deepEqual(events,[{status:'Reviewed reefs withheld: source binding or current screening unavailable.',state:'withheld',ranks:[],canExplore:false}]);
 v.reviewed={manifest:{expiresAt:'2099-01-01T00:00:00Z',regions:[]}};v.allFeatures=[reef(0)];withDom(()=>v.drawHabitat());assert.equal(events.at(-1)!.ranks.length,1);
 v.withholdOverlays();
 assert.deepEqual(events.at(-1),{status:'Reviewed habitat withheld until source binding and current screening are rechecked.',state:'withheld',ranks:[],canExplore:false});
 assert.equal(node('habitat-status').textContent,events.at(-1)!.status);assert.equal(events.length,3);assert.equal(v.exploreNext(),false);
});

test('shore species: shore state with no ranked reefs, even while the rail lists shore segments',()=>{
 const events:CoastHabitat[]=[],{v,node}=harness(h=>events.push(h));node('species').value='halibut';v.shoreFeatures=[shore];
 withDom(()=>v.drawHabitat());
 assert.deepEqual(events,[{status:'1 sandy-shore context segments. No ranked offshore California halibut habitat is admitted.',state:'shore',ranks:[],canExplore:false}]);
 assert.equal(node('rank-list').children.length,1,'the native shore list is unchanged');
 withDom(()=>v.drawShore());assert.equal(events.length,1,'a camera redraw of the same shore rail is not re-sent');
});

test('an unchanged rail is sent once; a depth limit that changes the ranks sends again',()=>{
 const events:CoastHabitat[]=[],{v}=harness(h=>events.push(h));v.allFeatures=[reef(0),reef(1),reef(2)];
 withDom(()=>{v.drawHabitat();v.drawHabitat();v.setDepthLimit(300);});
 assert.equal(events.length,1);
 withDom(()=>v.setDepthLimit(41));
 assert.equal(events.length,2);assert.deepEqual(events[1]!.ranks.map(r=>r.id),['reef-0','reef-1']);
 withDom(()=>v.setDepthLimit(41));assert.equal(events.length,2);
 withDom(()=>v.setDepthLimit(10));assert.equal(events.length,3);
 assert.equal(events[2]!.canExplore,false);assert.deepEqual(events[2]!.ranks,[]);assert.match(events[2]!.status,/^0 screened/);
});

test('exploreNext: false and no camera move with nothing to explore; otherwise the button\'s own selection',()=>{
 const empty=harness();bindNative(empty.v,empty.node);
 assert.equal(empty.v.exploreNext(),false,'before any habitat draw');
 withDom(()=>empty.v.drawHabitat());assert.equal(empty.node('next-reef').disabled,true);
 assert.equal(empty.v.exploreNext(),false);assert.deepEqual(empty.selections,[]);assert.equal(empty.moves(),0);
 const viaHandle=harness(),viaButton=harness();
 for(const h of [viaHandle,viaButton]){bindNative(h.v,h.node);h.v.allFeatures=[reef(0),reef(1)];withDom(()=>h.v.drawHabitat());}
 assert.equal(viaHandle.v.exploreNext(),true);viaButton.node('next-reef').onclick();
 assert.deepEqual(viaHandle.selections,viaButton.selections);assert.equal(viaHandle.selections[0].id,'reef-0');assert.equal(viaHandle.moves(),1);
 assert.equal(viaHandle.v.exploreNext(),true);assert.equal(viaHandle.selections[1].id,'reef-1','it steps through the ranks as the button does');
 viaHandle.node('next-reef').disabled=true;assert.equal(viaHandle.v.exploreNext(),false,'a disabled button is not bypassed');assert.equal(viaHandle.selections.length,2);
 viaHandle.node('next-reef').disabled=false;viaHandle.v.alive=false;assert.equal(viaHandle.v.exploreNext(),false,'a destroyed viewer explores nothing');assert.equal(viaHandle.moves(),2);
});

test('without onHabitat nothing throws and the native status line is unchanged',()=>{
 const {v,node}=harness();v.allFeatures=[reef(0)];
 withDom(()=>v.drawHabitat());assert.match(node('habitat-status').textContent,/^1 screened reef footprints · /);
 v.setSpecies('albacore');assert.match(node('habitat-status').textContent,/No substitute species/);v.withholdOverlays();assert.match(node('habitat-status').textContent,/withheld/);
});

test('the embed passes onHabitat to the renderer and exposes exploreNext, inert after destroy',()=>{
 const any=():El=>({...element(),getElementById:(id:string)=>id==='scene'&&!mounted?null:any(),querySelector:()=>any(),querySelectorAll:()=>[]});
 let mounted=false,options:any,explored=0;const root=any(),onHabitat=()=>{};
 const saved={document:globalThis.document,DOMParser:globalThis.DOMParser};
 Object.assign(globalThis,{document:{createElement:element,importNode:(n:El)=>n},DOMParser:class{parseFromString(){return {getElementById:()=>any()};}}});
 try{
  const viewer={exploreNext:()=>(explored++,true),destroy(){}};
  const handle=mountCoast({} as HTMLElement,{root:root as never,onHabitat},(_scene,o)=>{mounted=true;options=o;return viewer as never;});
  assert.equal(options.onHabitat,onHabitat);assert.equal(handle.exploreNext(),true);assert.equal(explored,1);
  handle.destroy();assert.equal(handle.exploreNext(),false);assert.equal(explored,1);
 }finally{Object.assign(globalThis,saved);}
});

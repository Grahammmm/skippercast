import test from 'node:test';
import assert from 'node:assert/strict';
import * as T from 'three';
import {CoastViewer} from '../../packages/coast/src/coast3d/viewer.ts';

// Exercise real state methods without constructing WebGL, fetching or scheduling
// data refreshes. Private TypeScript methods remain callable in this test harness.
function harness(){
 const nodes=new Map<string,any>();
 const node=(id:string)=>{if(!nodes.has(id))nodes.set(id,{value:'all',textContent:'',hidden:false,checked:true,dataset:{},replaceChildren(){this.replaced=true;},setAttribute(key:string,value:string){this[key]=value;}});return nodes.get(id);};
 const v:any=Object.create(CoastViewer.prototype);
 Object.assign(v,{root:{querySelector:(selector:string)=>node(selector.slice(5,-2))},options:{managed:true},host:{dataset:{},clientWidth:800,clientHeight:600},alive:true,visible:true,speciesSupported:true,habitat:new T.Group(),currents:new T.Group(),pins:[],labels:[],features:[],shoreFeatures:[],shoreGeneration:0,reviewed:null,selectedTarget:null,reefIndex:0,readingGeneration:0,depthLimit:300,revision:0,currentGeneration:0,habitatGeneration:0,frame:0,lodTimer:0,perspective:'3d',orbit:new T.Vector3(-100,100,100),orthoHeight:1000,camera:new T.PerspectiveCamera(42,1,2,1000000),scene:new T.Scene(),renderer:{setSize(){},render(){}},controls:{target:new T.Vector3(),update(){},touches:{},mouseButtons:{}},currentAt:null});
 v.camera.position.set(-100,100,100);v.refine=()=>{};v.refreshCurrents=()=>{};v.refreshHabitat=()=>{};
 return {v,node};
}
function forbidAddress<T>(run:()=>T):T{
 const keys=['location','history','document'] as const,previous=keys.map(key=>Object.getOwnPropertyDescriptor(globalThis,key));
 for(const key of keys)Object.defineProperty(globalThis,key,{configurable:true,get(){throw Error('Managed viewer accessed '+key);}});
 try{return run();}finally{keys.forEach((key,i)=>{if(previous[i])Object.defineProperty(globalThis,key,previous[i]!);else delete (globalThis as any)[key];});}
}
test('root lookups never select IDs from another document or viewer',()=>{
 const a=harness(),b=harness();a.v.$('species').value='lingcod';b.v.$('species').value='surfperch';
 forbidAddress(()=>{assert.equal(a.v.$('species').value,'lingcod');assert.equal(b.v.$('species').value,'surfperch');});
});
test('managed place and camera changes preserve the URL and avoid global DOM state',()=>{
 const {v,node}=harness();const places:string[]=[];v.options.onPlace=(id:string)=>places.push(id);
 forbidAddress(()=>{v.setPlace('avila');v.setPerspective('2d');assert.equal(v.host.dataset.perspective,'2d');assert.equal(node('perspective-2d')['aria-pressed'],'true');const target=v.controls.target.clone();v.setPerspective('3d');assert.deepEqual(v.controls.target.toArray(),target.toArray());v.setPlace('unreviewed-place');});
 assert.deepEqual(places,['avila']);assert.equal(v.selectedTarget,null);
});
test('unsupported target clears habitat and selection rather than falling back to reef species',()=>{
 const {v,node}=harness();v.habitat.add(new T.Group());v.features=[{id:'old'}];v.selectedTarget='old';
 assert.equal(v.setSpecies('albacore'),false);assert.equal(node('species').value,'');assert.equal(v.habitat.children.length,0);assert.deepEqual(v.features,[]);assert.equal(v.selectedTarget,null);assert.equal(node('target-detail').hidden,true);assert.equal(node('next-reef').disabled,true);assert.match(node('habitat-status').textContent,/No substitute species/);
 assert.equal(v.setSpecies('lingcod'),true);assert.equal(node('species').value,'lingcod');
});
test('selected reef callbacks keep the original point, identity and published region',()=>{
 const {v}=harness();let point:any;v.options.onSelection=(p:any)=>point=p;
 const reef={id:'source-reef',properties:{waypoint_latitude:35.9,waypoint_longitude:-121.5,region:'cambria-san-simeon',terrain_grade:'B',depth_min_ft:40,depth_max_ft:70,terrain_score:60,resolution_m:2,source_year:2020,metric_support_fraction:.9,screen_expires_at:'2027-01-01T00:00:00Z'}};
 forbidAddress(()=>v.selectFeature(reef,false));assert.deepEqual(point,{latitude:35.9,longitude:-121.5,region:'cambria-san-simeon',id:'source-reef'});
});
test('host hour is copied and invalid input cannot silently change selected time',()=>{
 const {v}=harness(),at=new Date('2026-10-06T15:00:00Z');v.setHour(at);at.setUTCDate(7);assert.equal(v.currentAt.toISOString(),'2026-10-06T15:00:00.000Z');v.setHour(new Date(NaN));assert.ok(Number.isNaN(v.currentAt.getTime()));v.setHour(null);assert.equal(v.currentAt,null);
});
test('hidden rendering stops and zero-size resize leaves camera projection finite',()=>{
 const {v}=harness();let renders=0,frames=0;v.renderer.render=()=>renders++;
 const cancel=globalThis.cancelAnimationFrame,request=globalThis.requestAnimationFrame;
 globalThis.cancelAnimationFrame=()=>{};globalThis.requestAnimationFrame=()=>++frames;
 try{v.setVisible(false);v.animate();assert.equal(frames,0);assert.equal(renders,0);assert.equal(v.revision,1);v.host.clientWidth=0;v.host.clientHeight=0;v.onResize();assert.ok(v.camera.projectionMatrix.elements.every(Number.isFinite));v.setVisible(true);assert.equal(frames,1);assert.equal(renders,1);v.setVisible(true);assert.equal(frames,1);}finally{globalThis.cancelAnimationFrame=cancel;globalThis.requestAnimationFrame=request;}
});

test('public habitat restoration queues exact identity and never emits a host selection',()=>{
 const {v,node}=harness();let calls=0;v.options.onSelection=()=>calls++;v.drawPins=()=>{};
 v.selectHabitat('123');assert.equal(v.selectedTarget,null);assert.equal(v.requestedHabitat,'123');
 const feature={id:123,properties:{waypoint_latitude:35.9,waypoint_longitude:-121.5,region:'cambria-san-simeon',terrain_grade:'B',depth_min_ft:40,depth_max_ft:70,terrain_score:60,resolution_m:2,source_year:2020,metric_support_fraction:.9,screen_expires_at:'2027-01-01T00:00:00Z'}};
 v.features=[feature];v.restoreHabitatSelection();assert.equal(v.selectedTarget,'123');assert.equal(calls,0);assert.equal(node('target-detail').hidden,false);
 v.selectHabitat('0123');assert.equal(v.selectedTarget,null);assert.equal(node('target-detail').hidden,true);assert.equal(calls,0);v.selectHabitat(null);assert.equal(v.requestedHabitat,null);
});

test('managed binding never reads browser geography and native handlers retain root ownership',()=>{
 const {v,node}=harness();node('species').options=[{value:'all'},{value:'lingcod'}];v.renderer.domElement={addEventListener(){}};
 const previous=Object.getOwnPropertyDescriptor(globalThis,'window');Object.defineProperty(globalThis,'window',{configurable:true,value:{addEventListener(){}}});
 try{forbidAddress(()=>{v.bind();assert.equal(node('species').value,'all');assert.equal(v.host.dataset.perspective,'3d');node('species').value='lingcod';node('species').onchange();assert.equal(node('species').value,'lingcod');node('location').value='avila';node('location').onchange();assert.equal(node('place-title').textContent,'Avila / Port San Luis');});}finally{if(previous)Object.defineProperty(globalThis,'window',previous);else delete (globalThis as any).window;}
});

test('shore restoration uses only original admitted identity and reports no inferred region',()=>{
 const {v,node}=harness();let point:any;v.options.onSelection=(p:any)=>point=p;v.drawPins=()=>{};node('species').value='surfperch';
 const shore={properties:{id:'shore-1',areaId:'south',name:'Original shore',access:[{coordinates:[-120.76,35.16]}],shoreClass:'sand',sourceYear:2020,checkedAt:'2026-09-01',legalReviewExpiresAt:'2026-09-30'},geometry:{coordinates:[[[-120.76,35.16],[-120.75,35.15]]]}};
 v.shoreFeatures=[shore];v.selectHabitat('shore-1');assert.equal(v.selectedTarget,'shore-1');assert.equal(point,undefined);assert.equal(node('target-title').textContent,'Original shore');v.selectShoreFeature(shore,false);assert.deepEqual(point,{latitude:35.16,longitude:-120.76,id:'shore-1'});
});

test('native user camera changes report original projection and keep normal refinement',()=>{
 const {v}=harness();const views:any[]=[];let refined=0,pins=0;v.options.onView=(view:any)=>views.push(view);v.refine=()=>refined++;v.drawPins=()=>pins++;
 const previous=Object.getOwnPropertyDescriptor(globalThis,'window');Object.defineProperty(globalThis,'window',{configurable:true,value:{setTimeout(fn:()=>void){fn();return 0;}}});
 try{forbidAddress(()=>{v.setLocation({latitude:35.16,longitude:-120.76,span:4500});assert.equal(views.length,0);refined=0;pins=0;v.userViewChanged();});assert.equal(views.length,1);assert.ok(Math.abs(views[0].latitude-35.16)<1e-10);assert.ok(Math.abs(views[0].longitude+120.76)<1e-10);assert.ok(Math.abs(views[0].span-4500)<1e-8);assert.equal(refined,1);assert.equal(pins,1);v.visible=false;v.userViewChanged();assert.equal(views.length,1);}finally{if(previous)Object.defineProperty(globalThis,'window',previous);else delete (globalThis as any).window;}
});
test('native perspective callback fires once per actual camera change without a view feedback loop',()=>{
 const {v}=harness(),modes:string[]=[],views:any[]=[];v.options.onPerspective=(mode:string)=>{modes.push(mode);v.setPerspective(mode);};v.options.onView=(view:any)=>views.push(view);
 forbidAddress(()=>{v.setPerspective('2d');v.setPerspective('2d');v.setPerspective('3d');});assert.deepEqual(modes,['2d','3d']);assert.equal(views.length,0);
});

test('hide and delayed rejected revalidation cannot reveal cached habitat, details or current vectors',async()=>{
 const {v,node}=harness();let invalidated=0,restored=0;v.options.onSelectionInvalidated=()=>invalidated++;v.options.onRestoredSelection=()=>restored++;v.manifest={};v.requestedHabitat='old';v.reviewed={manifest:{screenExpiresAt:'2000-01-01T00:00:00Z'}};v.allFeatures=[{id:'old'}];v.features=v.allFeatures;v.shoreFeatures=[{properties:{id:'old-shore'}}];v.selectedTarget='old';v.habitat.add(new T.Group());v.currents.add(new T.Group());let removed=0;v.pins=[{el:{remove(){removed++;}}}];node('target-detail').hidden=false;
 const previousFetch=globalThis.fetch,cancel=globalThis.cancelAnimationFrame,request=globalThis.requestAnimationFrame;
 const pending:{path:string;reject:(error:Error)=>void}[]=[];globalThis.fetch=((path:string)=>new Promise((_resolve,reject)=>pending.push({path,reject}))) as typeof fetch;globalThis.cancelAnimationFrame=()=>{};globalThis.requestAnimationFrame=()=>0;
 let task:Promise<void>|undefined;const refresh=(CoastViewer.prototype as any).refreshHabitat;v.refreshHabitat=()=>task=refresh.call(v);v.loadShore=()=>{};
 const empty=()=>{assert.equal(v.habitat.children.length,0);assert.equal(v.currents.children.length,0);assert.equal(v.pins.length,0);assert.equal(node('target-detail').hidden,true);assert.equal(v.reviewed,null);assert.deepEqual(v.features,[]);assert.deepEqual(v.shoreFeatures,[]);};
 try{v.setVisible(false);empty();assert.equal(removed,1);assert.equal(v.requestedHabitat,'old');v.setVisible(true);empty();assert.equal(pending.length,1);assert.match(pending[0].path,/skippercast-manifest/);v.animate();empty();pending[0].reject(Error('Expired source screen'));await task;empty();assert.equal(v.requestedHabitat,'old');assert.match(node('habitat-status').textContent,/withheld/);assert.equal(invalidated,1,'expired hidden selection is withdrawn once before resumed validation');assert.equal(restored,0,'rejected expired source cannot republish binding metadata');}finally{globalThis.fetch=previousFetch;globalThis.cancelAnimationFrame=cancel;globalThis.requestAnimationFrame=request;}
});
test('managed keyboard Home executes the host reset once without an intermediate native view',()=>{
 const {v,node}=harness();node('species').options=[];const events=new Map<string,(e:any)=>void>();v.renderer.domElement={addEventListener(key:string,fn:(e:any)=>void){events.set(key,fn);}};
 const previous=Object.getOwnPropertyDescriptor(globalThis,'window');Object.defineProperty(globalThis,'window',{configurable:true,value:{addEventListener(){}}});let resets=0,views=0;v.options.onView=()=>views++;
 try{v.bind();node('reset').onclick=()=>{resets++;v.setLocation({latitude:36.62,longitude:-121.91,span:24000});};node('reset').click=()=>node('reset').onclick();forbidAddress(()=>events.get('keydown')!({key:'Home',preventDefault(){}}));assert.equal(resets,1);assert.equal(views,0);assert.notEqual(v.controls.target.x,0);}finally{if(previous)Object.defineProperty(globalThis,'window',previous);else delete (globalThis as any).window;}
});

test('a late current response from the hidden admission cannot restore old vectors',async()=>{
 const {v,node}=harness();v.manifest={};v.currents.add(new T.Group());const refresh=(CoastViewer.prototype as any).refreshCurrents;
 const previousFetch=globalThis.fetch,cancel=globalThis.cancelAnimationFrame,request=globalThis.requestAnimationFrame;
 const pending:((response:Response)=>void)[]=[];globalThis.fetch=(()=>new Promise(resolve=>pending.push(resolve))) as typeof fetch;globalThis.cancelAnimationFrame=()=>{};globalThis.requestAnimationFrame=()=>0;v.loadShore=()=>{};
 try{const old=refresh.call(v);assert.equal(pending.length,1);v.setVisible(false);assert.equal(v.currents.children.length,0);v.setVisible(true);assert.equal(v.currents.children.length,0);pending[0](new Response(JSON.stringify({currents:[]}),{headers:{'Content-Type':'application/json'}}));await old;assert.equal(v.currents.children.length,0);assert.match(node('current-status').textContent,/withheld/);const current=refresh.call(v);assert.equal(pending.length,2);pending[1](new Response(JSON.stringify({currents:[]}),{headers:{'Content-Type':'application/json'}}));await current;assert.equal(v.currents.children.length,0);assert.match(node('current-status').textContent,/No reviewed current field/);}finally{globalThis.fetch=previousFetch;globalThis.cancelAnimationFrame=cancel;globalThis.requestAnimationFrame=request;}
});
test('restored reef metadata reports only exact admitted source identity without user callback, address or camera changes',()=>{
 const {v,node}=harness(),restored:any[]=[];let selected=0,moved=0;v.options.onRestoredSelection=(p:any)=>restored.push(p);v.options.onSelection=()=>selected++;v.moveTo=()=>moved++;v.drawPins=()=>{};
 const reef={id:123,properties:{id:'different-property-id',waypoint_latitude:35.9,waypoint_longitude:-121.5,region:'cambria-san-simeon',terrain_grade:'B',depth_min_ft:40,depth_max_ft:70,terrain_score:60,resolution_m:2,source_year:2020,metric_support_fraction:.9,screen_expires_at:'2027-01-01T00:00:00Z'}};
 forbidAddress(()=>{v.selectHabitat('123');assert.deepEqual(restored,[]);v.features=[reef];v.restoreHabitatSelection();});
 assert.deepEqual(restored,[{latitude:35.9,longitude:-121.5,region:'cambria-san-simeon',id:'123'}]);assert.equal(selected,0);assert.equal(moved,0);assert.equal(node('target-detail').hidden,false);
 v.selectHabitat('0123');assert.equal(restored.length,1,'similar numeric ID cannot restore another feature');
 v.withholdOverlays();v.selectHabitat('123');v.restoreHabitatSelection();assert.equal(restored.length,1,'held/rejected source has no admitted feature callback');assert.equal(node('target-detail').hidden,true);
 v.features=[reef];forbidAddress(()=>v.restoreHabitatSelection());assert.equal(restored.length,2,'a newly admitted exact feature restores its source metadata');
 v.selectFeature(reef,false);assert.equal(selected,1);assert.equal(restored.length,2,'user callback remains distinct');
});
test('restored shore callbacks retain original access/vertex coordinates and never infer a region from area',()=>{
 const {v,node}=harness(),restored:any[]=[];let selected=0;v.options.onRestoredSelection=(p:any)=>restored.push(p);v.options.onSelection=()=>selected++;v.drawPins=()=>{};v.moveTo=()=>{throw Error('Restoration must not pan');};node('species').value='surfperch';
 const shore={id:'published-shore',properties:{id:'alternate-id',areaId:'south',name:'Original shore',access:[{coordinates:[-120.76,35.16]}],shoreClass:'sand',sourceYear:2020,checkedAt:'2026-09-01',legalReviewExpiresAt:'2026-09-30'},geometry:{coordinates:[[[-120.75,35.15],[-120.74,35.14]]]}};
 v.shoreFeatures=[shore];forbidAddress(()=>v.selectHabitat('published-shore'));assert.deepEqual(restored,[{latitude:35.16,longitude:-120.76,id:'published-shore'}]);assert.equal(selected,0);
 const vertex={...shore,id:'published-vertex',properties:{...shore.properties,access:[],region:'morro-bay'}};v.shoreFeatures=[vertex];forbidAddress(()=>v.selectHabitat('published-vertex'));assert.deepEqual(restored.at(-1),{latitude:35.15,longitude:-120.75,region:'morro-bay',id:'published-vertex'});
 v.withholdOverlays();v.selectHabitat('published-shore');v.restoreHabitatSelection();assert.equal(restored.length,2,'withheld shore source cannot restore cached publication identity');
});
test('selection invalidation clears restored host proof on expiry, rejection and explicit clear, then exact re-admission restores it',async()=>{
 const {v,node}=harness(),restored:any[]=[];let invalidated=0;v.options.onRestoredSelection=(p:any)=>restored.push(p);v.options.onSelectionInvalidated=()=>invalidated++;v.drawPins=()=>{};
 const reef={id:'verified-id',properties:{waypoint_latitude:35.9,waypoint_longitude:-121.5,region:'cambria-san-simeon',terrain_grade:'B',depth_min_ft:40,depth_max_ft:70,terrain_score:60,resolution_m:2,source_year:2020,metric_support_fraction:.9,screen_expires_at:'2027-01-01T00:00:00Z'}};
 v.features=[reef];v.selectHabitat('verified-id');assert.equal(restored.length,1);assert.equal(invalidated,0);
 v.restoreHabitatSelection();assert.equal(invalidated,0,'valid redraw retains admitted identity');v.selectHabitat('verified-id');assert.equal(invalidated,0,'same exact shared identity does not falsely withdraw admission');
 v.withholdOverlays();assert.equal(invalidated,1);assert.equal(v.requestedHabitat,'verified-id');assert.equal(node('target-detail').hidden,true);v.restoreHabitatSelection();assert.equal(restored.length,3,'expiry cannot restore a cached feature');assert.equal(invalidated,1);
 v.features=[reef];v.restoreHabitatSelection();assert.equal(restored.length,4);
 const previousFetch=globalThis.fetch;globalThis.fetch=async()=>new Response('held source',{status:503});try{await (CoastViewer.prototype as any).refreshHabitat.call(v);}finally{globalThis.fetch=previousFetch;}
 assert.equal(invalidated,2,'actual rejected source refresh withdraws publication selection');assert.equal(v.selectedTarget,null);assert.equal(node('target-detail').hidden,true);v.restoreHabitatSelection();assert.equal(restored.length,4);
 v.features=[reef];v.restoreHabitatSelection();assert.equal(restored.length,5);v.selectHabitat(null);assert.equal(invalidated,3);assert.equal(v.requestedHabitat,null);assert.equal(node('target-detail').hidden,true);
});
test('species changes and admitted-feature disappearance invalidate once; valid reef and shore redraws do not',()=>{
 const {v,node}=harness();let invalidated=0,restored=0;v.options.onSelectionInvalidated=()=>invalidated++;v.options.onRestoredSelection=()=>restored++;v.drawPins=()=>{};
 const reef={id:'reef-current',properties:{waypoint_latitude:35.9,waypoint_longitude:-121.5,region:'cambria-san-simeon',terrain_grade:'B',depth_min_ft:40,depth_max_ft:70,terrain_score:60,resolution_m:2,source_year:2020,metric_support_fraction:.9,screen_expires_at:'2027-01-01T00:00:00Z'}};
 v.features=[reef];v.selectHabitat('reef-current');v.restoreHabitatSelection();assert.equal(invalidated,0);
 v.features=[];v.restoreHabitatSelection();assert.equal(invalidated,1);v.restoreHabitatSelection();assert.equal(invalidated,1);
 v.features=[reef];v.restoreHabitatSelection();v.setSpecies('unknown');assert.equal(invalidated,2);assert.equal(v.selectedTarget,null);
 v.speciesSupported=true;node('species').value='surfperch';const shore={id:'shore-current',properties:{areaId:'south',name:'Original shore',access:[{coordinates:[-120.76,35.16]}],shoreClass:'sand',sourceYear:2020,checkedAt:'2026-09-01',legalReviewExpiresAt:'2026-09-30'},geometry:{coordinates:[[[-120.75,35.15],[-120.74,35.14]]]}};
 v.shoreFeatures=[shore];v.selectHabitat('shore-current');v.restoreHabitatSelection();const before=invalidated;v.restoreHabitatSelection();assert.equal(invalidated,before);
 v.shoreFeatures=[];v.restoreHabitatSelection();assert.equal(invalidated,before+1);assert.equal(node('target-detail').hidden,true);assert.ok(restored>=4);
});

test('temporary hiding retains admitted context only until its original expiry without hidden requests',()=>{
 const {v,node}=harness();let invalidated=0,requests=0;v.options.onSelectionInvalidated=()=>invalidated++;v.refreshHabitat=()=>requests++;v.refreshCurrents=()=>requests++;v.loadShore=()=>requests++;
 const originalNow=Date.now,cancel=globalThis.cancelAnimationFrame;let now=1000;Date.now=()=>now;globalThis.cancelAnimationFrame=()=>{};
 try{v.selectedTarget='published';v.requestedHabitat='published';v.retainSelection('published',2000);v.habitat.add(new T.Group());v.setVisible(false);assert.equal(invalidated,0);assert.equal(v.selectionReceipt.id,'published');assert.equal(v.habitat.children.length,0);assert.equal(node('target-detail').hidden,true);v.selectHabitat('published');assert.equal(invalidated,0);assert.equal(requests,0);now=2000;v.scheduleSelectionExpiry();assert.equal(invalidated,1);assert.equal(v.selectionReceipt,null);assert.equal(requests,0);v.scheduleSelectionExpiry();assert.equal(invalidated,1);}finally{clearTimeout(v.selectionTimer);Date.now=originalNow;globalThis.cancelAnimationFrame=cancel;}
});
test('unsupported selected hour clears vectors, cancels pending admission and periodic refresh remains a gap',async()=>{
 const {v,node}=harness();v.currents.add(new T.Group());let calls=0;const prior=globalThis.fetch;globalThis.fetch=(async()=>{calls++;throw Error('must not fetch');}) as typeof fetch;
 try{const generation=v.currentGeneration;v.setHour(new Date(NaN));assert.ok(v.currentGeneration>generation);assert.equal(v.currents.children.length,0);await (CoastViewer.prototype as any).refreshCurrents.call(v);assert.equal(calls,0);assert.match(node('current-status').textContent,/unsupported selected UTC hour/);v.setHour(null);assert.equal(v.currentAt,null);}finally{globalThis.fetch=prior;}
});

test('hidden current receipt survives pending validation but rejected resumed source withdraws it',async()=>{
 const {v}=harness();v.selectedTarget='published';v.requestedHabitat='published';v.retainSelection('published',Date.now()+60000);v.manifest={};let invalidated=0;v.options.onSelectionInvalidated=()=>invalidated++;
 const previousFetch=globalThis.fetch,cancel=globalThis.cancelAnimationFrame,request=globalThis.requestAnimationFrame;let reject!: (error:Error)=>void;globalThis.fetch=(()=>new Promise((_resolve,no)=>{reject=no;})) as typeof fetch;globalThis.cancelAnimationFrame=()=>{};globalThis.requestAnimationFrame=()=>0;v.loadShore=()=>{};let task:Promise<void>;v.refreshHabitat=()=>task=(CoastViewer.prototype as any).refreshHabitat.call(v);
 try{v.setVisible(false);assert.equal(invalidated,0);v.setVisible(true);assert.equal(invalidated,0);v.restoreHabitatSelection();assert.equal(invalidated,0);assert.equal(v.selectedTarget,null);reject(Error('HEAD/source rejected'));await task!;assert.equal(invalidated,1);assert.equal(v.selectionReceipt,null);assert.equal(v.selectedTarget,null);}finally{clearTimeout(v.selectionTimer);globalThis.fetch=previousFetch;globalThis.cancelAnimationFrame=cancel;globalThis.requestAnimationFrame=request;}
});

test('reef context receipt expires at the earliest original release, regional or feature deadline',()=>{
 const {v}=harness();v.reviewed={manifest:{expiresAt:'2027-03-01T00:00:00Z',regions:[{expiresAt:'2027-02-01T00:00:00Z'}]}};
 const reef={id:'deadline',properties:{waypoint_latitude:35.9,waypoint_longitude:-121.5,region:'cambria-san-simeon',screen_expires_at:'2027-04-01T00:00:00Z'}};
 v.selectFeature(reef,false);assert.equal(v.selectionReceipt.expires,Date.parse('2027-02-01T00:00:00Z'));clearTimeout(v.selectionTimer);
});

test('earlier bound full-context publication expiry withdraws native receipt while hidden',()=>{
 const {v}=harness();let invalidated=0;v.options.onSelectionInvalidated=()=>invalidated++;
 const originalNow=Date.now,cancel=globalThis.cancelAnimationFrame;let now=Date.parse('2026-10-07T00:00:00Z');Date.now=()=>now;globalThis.cancelAnimationFrame=()=>{};
 try{v.reviewed={manifest:{expiresAt:'2027-03-01T00:00:00Z',regions:[{expiresAt:'2027-02-01T00:00:00Z'}]}};v.context={expiresAt:'2026-10-08T00:00:00Z'};
  v.selectFeature({id:'bound',properties:{waypoint_latitude:35.9,waypoint_longitude:-121.5,region:'cambria-san-simeon',screen_expires_at:'2027-04-01T00:00:00Z'}},false);assert.equal(v.selectionReceipt.expires,Date.parse(v.context.expiresAt));v.setVisible(false);assert.equal(invalidated,0);assert.equal(v.selectionReceipt.id,'bound');now=Date.parse('2026-10-08T00:00:00Z');v.scheduleSelectionExpiry();assert.equal(v.selectionReceipt,null);assert.equal(invalidated,1);assert.equal(v.habitat.children.length,0);
 }finally{clearTimeout(v.selectionTimer);Date.now=originalNow;globalThis.cancelAnimationFrame=cancel;}
});

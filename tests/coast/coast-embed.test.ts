// FE-70 (design § 3A.2): one embed mounts the managed terrain for v1's
// workspace and v2's MapStage. A DOM fixture and a fake renderer; no GPU.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {embedPalette,mountCoast,type CoastHandle,type CoastMountOptions} from '../../packages/coast/src/embed.ts';
import {coastEmbedTemplate,coastSceneMarkup,coastSourcesMarkup} from '../../packages/coast/src/embed-template.ts';
import {DEFAULT_COAST_PALETTE} from '../../packages/coast/src/palette.ts';
import {coastPath} from '../../packages/coast/src/transport.ts';

const page=readFileSync(new URL('../../dist/coast.html',import.meta.url),'utf8');
const viewerSource=readFileSync(new URL('../../packages/coast/src/coast3d/viewer.ts',import.meta.url),'utf8');
const slice=(open:string,close:string)=>{const start=page.indexOf(open);assert.ok(start>=0,open);return page.slice(start,page.indexOf(close,start)+close.length);};

test('the embed template is the standalone page\'s scene and sources markup, verbatim',()=>{
 assert.equal(coastSceneMarkup,slice('<main id="scene"','</main>'));
 assert.equal(coastSourcesMarkup,slice('<dialog id="sources">','</dialog>'));
 assert.equal(coastEmbedTemplate,coastSceneMarkup+coastSourcesMarkup);
});

test('every element id CoastViewer binds exists in the template or is added by the embed',()=>{
 const ids=new Set([...viewerSource.matchAll(/this\.\$(?:<\w+>)?\('([^']+)'\)/g)].map(m=>m[1]!));
 assert.ok(ids.size>=40,`expected about forty bound ids, found ${ids.size}`);
 const added=new Set(['perspective-2d','perspective-3d','sources-open']);
 for(const id of ids)assert.ok(added.has(id)||coastEmbedTemplate.includes(`id="${id}"`),id);
 for(const marker of ['class="intro"','<aside class="layers"><div class="eyebrow">','<h2>Find your water.</h2>','for="species"','class="view-controls"','<label><input id="currents"'])assert.ok(coastSceneMarkup.includes(marker),marker);
});

test('embedPalette keeps v1 colours and takes only known string roles',()=>{
 assert.deepEqual(embedPalette(),DEFAULT_COAST_PALETTE);
 const palette=embedPalette({ground:'#07131d',sky:'',current:undefined,bogus:'x'} as never);
 assert.deepEqual(palette,{...DEFAULT_COAST_PALETTE,ground:'#07131d'});
 assert.ok(Object.isFrozen(palette));
});

// A small DOM: each parse yields fresh scene and sources nodes, and the shadow
// root resolves ids and selectors in the first parsed copy it holds, as a real
// root resolves them in document order.
type FakeNode={id?:string;doc?:ParsedDoc;parent:FakeNode|null;hidden:boolean;textContent:string;removed:boolean;attributes:Record<string,string>;dataset:Record<string,string>;children:FakeNode[];href?:string;rel?:string;onclick:null|(()=>void);append(...nodes:FakeNode[]):void;remove():void;setAttribute(key:string,value:string):void;closest(selector:string):FakeNode};
type ParsedDoc={get(id:string):FakeNode;selected:Map<string,FakeNode>;select(selector:string):FakeNode;receipts:FakeNode[];reportLinks:FakeNode[]};
function node(init:Partial<FakeNode>={}):FakeNode{
 const label=init.id==='currents'?node({id:'currents-label'}):null;
 return {parent:null,hidden:false,textContent:'',removed:false,attributes:{},dataset:{},children:[],onclick:null,...init,
  append(...nodes){for(const n of nodes){n.parent?.children.splice(n.parent.children.indexOf(n),1);n.parent=this;this.children.push(n);}},
  remove(){if(this.parent)this.parent.children.splice(this.parent.children.indexOf(this),1);this.parent=null;this.removed=true;},
  setAttribute(key,value){this.attributes[key]=value;},closest(selector){assert.equal(selector,'label');return label!;}};
}
function parse():ParsedDoc{
 const ids=new Map<string,FakeNode>(),selected=new Map<string,FakeNode>();
 const doc:ParsedDoc={get:id=>ids.get(id)??(ids.set(id,node({id,doc})),ids.get(id)!),selected,select:selector=>selected.get(selector)??(selected.set(selector,node()),selected.get(selector)!),
  receipts:[...coastSourcesMarkup.matchAll(/data-coast-receipt="([^"]+)"/g)].map(m=>node({dataset:{coastReceipt:m[1]!}})),
  reportLinks:[...coastEmbedTemplate.matchAll(/href="index\.html#forecast"/g)].map(()=>node({href:'index.html#forecast'}))};
 return doc;
}
function fixture(){
 const parsed:string[]=[],docs:ParsedDoc[]=[];
 const root=node();
 const mounted=()=>root.children.find(n=>n.doc)?.doc;
 Object.assign(root,{getElementById:(id:string)=>mounted()?.get(id)??null,querySelector:(selector:string)=>mounted()?.select(selector)??null,
  querySelectorAll:(selector:string)=>{const d=mounted();return !d?[]:selector==='[data-coast-receipt]'?d.receipts:selector==='a[href="index.html#forecast"]'?d.reportLinks:[];}});
 let attached=0;
 const host={shadowRoot:null as FakeNode|null,attachShadow(init:{mode:string}){assert.equal(init.mode,'open');attached++;this.shadowRoot=root;return root;}};
 const saved={document:globalThis.document,DOMParser:globalThis.DOMParser};
 Object.assign(globalThis,{document:{createElement:(tag:string)=>node({attributes:{tag}}),importNode:(n:FakeNode,deep:boolean)=>{assert.equal(deep,true);return n;}},
  DOMParser:class{parseFromString(text:string,type:string){assert.equal(type,'text/html');parsed.push(text);const d=parse();docs.push(d);return {getElementById:d.get};}}});
 const calls:unknown[][]=[];let viewerArgs:{scene:unknown;options:any}|null=null;
 class FakeViewer{constructor(scene:unknown,options:any){viewerArgs={scene,options};}
  load(){calls.push(['load']);return Promise.resolve(true);}setPerspective(m:unknown){calls.push(['setPerspective',m]);}setLocation(p:unknown){calls.push(['setLocation',p]);}
  setSpecies(id:string){calls.push(['setSpecies',id]);return id!=='tuna';}setHour(at:unknown){calls.push(['setHour',at]);}setDepthLimit(ft:unknown){calls.push(['setDepthLimit',ft]);}
  setCurrentLayer(id:unknown){calls.push(['setCurrentLayer',id]);}selectHabitat(id:unknown){calls.push(['selectHabitat',id]);}setVisible(v:unknown){calls.push(['setVisible',v]);}destroy(){calls.push(['destroy']);}
  setRelief(v:unknown){calls.push(['setRelief',v]);}setWaterOpacity(v:unknown){calls.push(['setWaterOpacity',v]);}setWaterVisible(v:unknown){calls.push(['setWaterVisible',v]);}setContours(v:unknown){calls.push(['setContours',v]);}
  setSourceCoverage(v:unknown){calls.push(['setSourceCoverage',v]);}setHabitatVisible(v:unknown){calls.push(['setHabitatVisible',v]);}zoom(d:unknown){calls.push(['zoom',d]);}resetView(){calls.push(['resetView']);}topView(){calls.push(['topView']);}openSources(){calls.push(['openSources']);}}
 const mount=(options?:CoastMountOptions)=>mountCoast(host as unknown as HTMLElement,options,(scene,viewerOptions)=>new FakeViewer(scene,viewerOptions) as never);
 const last=()=>docs.at(-1)!;
 return {root,host,docs,parsed,calls,mount,byId:(id:string)=>last().get(id),selected:{get:(selector:string)=>last().selected.get(selector)},
  get receipts(){return last().receipts;},get reportLinks(){return last().reportLinks;},
  attached:()=>attached,viewer:()=>viewerArgs!,restore:()=>Object.assign(globalThis,saved)};
}

test('mounting adapts the scene for a managed host as v1 did',()=>{
 const f=fixture();
 try{
  f.mount({styles:['/a.css','/b.css'],forecastHref:'#forecast'});
  assert.equal(f.attached(),1);assert.deepEqual(f.parsed,[coastEmbedTemplate]);
  assert.deepEqual(f.root.children.map(n=>n.href??n.id),['/a.css','/b.css','scene','sources']);
  assert.deepEqual(f.root.children.slice(0,2).map(n=>n.rel),['stylesheet','stylesheet']);
  assert.equal(f.selected.get('.intro')!.hidden,true);
  assert.equal(f.selected.get('.layers h2')!.removed,true);assert.equal(f.selected.get('.layers>.eyebrow')!.removed,true);
  assert.equal(f.selected.get('[for="species"]')!.hidden,true);assert.equal(f.byId('species').hidden,true);
  assert.equal(f.byId('currents').closest('label').hidden,false,'the scene keeps its currents checkbox without a host control');
  assert.equal(f.byId('layers-toggle').textContent,'Terrain layers & evidence');
  assert.ok(coastSceneMarkup.includes('<div id="pins" aria-label="Ranked species habitat pins">'),'the template names the pin list');
  assert.equal(f.byId('pins').attributes.role,'group','a named group, so its aria-label is permitted (axe, FE-71)');
  const added=f.selected.get('.view-controls')!.children;
  assert.deepEqual(added.map(n=>[n.id,n.hidden]),[['perspective-2d',true],['perspective-3d',true],['sources-open',false]]);
  assert.equal(added[2]!.textContent,'ⓘ');assert.equal(added[2]!.attributes['aria-label'],'Terrain sources and assumptions');
  assert.equal(f.receipts.length,3);assert.deepEqual(f.receipts.map(n=>n.href),f.receipts.map(n=>coastPath(n.dataset.coastReceipt!)));
  assert.ok(f.reportLinks.length>0);for(const link of f.reportLinks)assert.equal(link.href,'#forecast');
  const {scene,options}=f.viewer();assert.equal(scene,f.byId('scene'));assert.equal(options.root,f.root);assert.equal(options.managed,true);
  assert.equal('palette' in options,false,'v1 passes no palette, so the renderer keeps DEFAULT_COAST_PALETTE');
  assert.equal('controls' in options,false,'native chrome keeps every control in the root');
  assert.equal(f.selected.get('.layers'),undefined,'native chrome never selects the whole layers panel');
  for(const panel of [f.selected.get('.intro')!,f.byId('target-detail'),f.byId('reading'),f.selected.get('.view-controls')!])assert.equal(panel.parent,null,'native chrome moves no panel');
  for(const id of ['top','target-close','reset'])assert.equal(f.byId(id).onclick,null);
  assert.equal(f.byId('reset').attributes['aria-label'],undefined);
  assert.deepEqual(f.calls,[],'no state is applied without initial values');
 }finally{f.restore();}
});

test('host options hide the scene currents, replace buttons, pass a palette and forward callbacks',()=>{
 const f=fixture(),pressed:string[]=[],events:string[]=[];
 try{
  f.mount({hostCurrents:true,palette:{ground:'#07131d'},onTop:()=>pressed.push('top'),onCloseSelection:()=>pressed.push('close'),onReset:()=>pressed.push('reset'),
   onSelection:()=>events.push('selection'),onRestoredSelection:()=>events.push('restored'),onSelectionInvalidated:()=>events.push('invalidated'),
   onCurrentStatus:text=>events.push('status:'+text),onView:view=>events.push('view:'+view.span),onPerspective:mode=>events.push('perspective:'+mode)});
  assert.equal(f.byId('currents').closest('label').hidden,true);
  assert.equal(f.reportLinks[0]!.href,'index.html#forecast','links stay put without forecastHref');
  for(const id of ['top','target-close','reset'])f.byId(id).onclick!();
  assert.deepEqual(pressed,['top','close','reset']);assert.equal(f.byId('reset').attributes['aria-label'],'Reset map view');
  const o=f.viewer().options;assert.deepEqual(o.palette,{...DEFAULT_COAST_PALETTE,ground:'#07131d'});
  o.onSelection({latitude:35.4,longitude:-120.9});o.onRestoredSelection({latitude:35.4,longitude:-120.9});o.onSelectionInvalidated();
  o.onCurrentStatus('off');o.onView({latitude:35.4,longitude:-120.9,span:7300});o.onPerspective('2d');
  assert.deepEqual(events,['selection','restored','invalidated','status:off','view:7300','perspective:2d']);
 }finally{f.restore();}
});

test('initial state reaches the renderer once, in v1\'s order, before load',()=>{
 const f=fixture(),at=new Date('2026-10-12T12:00:00Z');
 try{
  f.mount({initial:{visible:false,habitat:'synthetic-1',perspective:'2d',hour:at,location:{latitude:35.37,longitude:-120.87,span:3650},depthLimit:60,species:'cabezon-shallow-reef',currentLayer:'wcofs'}});
  assert.deepEqual(f.calls,[['setCurrentLayer','wcofs'],['setSpecies','cabezon-shallow-reef'],['setDepthLimit',60],['setLocation',{latitude:35.37,longitude:-120.87,span:3650}],
   ['setHour',at],['setPerspective','2d'],['selectHabitat','synthetic-1'],['setVisible',false]]);
 }finally{f.restore();}
});

test('every handle method reaches the renderer once and the handle is inert after destroy',async()=>{
 const f=fixture();
 try{
  const handle:CoastHandle=f.mount(),at=new Date('2026-10-12T12:00:00Z');
  assert.equal(await handle.load(),true);handle.setPerspective('2d');handle.setLocation({latitude:35.37,longitude:-120.87,span:3650});
  assert.equal(handle.setSpecies('lingcod'),true);assert.equal(handle.setSpecies('tuna'),false);handle.setHour(at);handle.setDepthLimit(60);handle.setCurrentLayer('wcofs');
  handle.selectHabitat('synthetic-1');handle.setVisible(false);handle.destroy();
  assert.deepEqual(f.calls,[['load'],['setPerspective','2d'],['setLocation',{latitude:35.37,longitude:-120.87,span:3650}],['setSpecies','lingcod'],['setSpecies','tuna'],
   ['setHour',at],['setDepthLimit',60],['setCurrentLayer','wcofs'],['selectHabitat','synthetic-1'],['setVisible',false],['destroy']]);
  const before=f.calls.length;
  assert.equal(await handle.load(),false);handle.setPerspective('3d');handle.setLocation({latitude:0,longitude:0});assert.equal(handle.setSpecies('lingcod'),false);
  handle.setHour(null);handle.setDepthLimit(300);handle.setCurrentLayer('off');handle.selectHabitat(null);handle.setVisible(true);handle.destroy();
  assert.equal(f.calls.length,before);
 }finally{f.restore();}
});

test('a supplied shadow root is reused instead of attaching another',()=>{
 const f=fixture();
 try{f.mount({root:f.root as unknown as ShadowRoot});assert.equal(f.attached(),0);assert.equal(f.viewer().options.root,f.root);}finally{f.restore();}
});

test('destroy removes every inserted node, and the same host mounts again with fresh ids',()=>{
 const f=fixture();
 try{
  const first=f.mount({styles:['/a.css'],onReset:()=>{}});const firstScene=f.viewer().scene as FakeNode;
  assert.throws(()=>f.mount(),/already holds a mounted coast/,'a live mount is never doubled');
  assert.equal(f.root.children.length,3,'a refused mount inserts nothing');
  first.destroy();
  assert.deepEqual(f.root.children,[],'stylesheet, scene and sources are gone');assert.equal(firstScene.removed,true);
  first.destroy();assert.deepEqual(f.calls,[['destroy']],'a second destroy is a no-op');
  const reset=()=>{},second=f.mount({styles:['/a.css'],onReset:reset}),fresh=f.docs[1]!;
  assert.equal(f.attached(),1,'the host\'s shadow root is reused');
  assert.notEqual(f.viewer().scene,firstScene);assert.equal(f.viewer().scene,fresh.get('scene'));
  assert.equal((f.root as unknown as {getElementById(id:string):unknown}).getElementById('reset'),fresh.get('reset'));
  assert.equal(fresh.get('reset').onclick,reset);
  assert.deepEqual(f.root.children.map(n=>n.href??n.id),['/a.css','scene','sources']);
  second.destroy();assert.deepEqual(f.root.children,[]);
 }finally{f.restore();}
});

test('CoastViewer.destroy releases the WebGL context, canvas and pagehide listener once',async()=>{
 const {CoastViewer}=await import('../../packages/coast/src/coast3d/viewer.ts');
 assert.match(viewerSource,/window\.addEventListener\('pagehide',this\.pagehide,\{once:true\}\)/,'bind registers the handler destroy removes');
 const events:string[]=[],removed:[string,unknown][]=[];
 const v:any=Object.create(CoastViewer.prototype);
 Object.assign(v,{alive:true,options:{managed:true},loaded:new Map(),terrain:{children:[]},waters:{children:[]},textureValues:[],habitat:{},currents:{},seams:{},
  resize:{disconnect:()=>events.push('resize')},controls:{dispose:()=>events.push('controls')},clearPins:()=>{},clear:()=>{},
  renderer:{dispose:()=>events.push('dispose'),forceContextLoss:()=>events.push('contextLoss'),domElement:{remove:()=>events.push('canvas')}}});
 v.pagehide=()=>v.destroy();
 const saved={window:(globalThis as any).window,cancelAnimationFrame:(globalThis as any).cancelAnimationFrame};
 Object.assign(globalThis,{window:{removeEventListener:(type:string,fn:unknown)=>removed.push([type,fn])},cancelAnimationFrame:()=>{}});
 try{
  v.destroy();v.destroy();
  assert.deepEqual(removed.filter(([type])=>type==='pagehide'),[['pagehide',v.pagehide]]);
  assert.deepEqual(events,['resize','controls','dispose','contextLoss','canvas']);
 }finally{Object.assign(globalThis,saved);}
});

// FE-79: host chrome. The native panels leave the shadow root; the handle's
// setters and events replace them.
test('host chrome keeps the native panels out of the shadow root but bound to the renderer',()=>{
 const f=fixture(),pressed:string[]=[];
 try{
  const handle=f.mount({chrome:'host',styles:['/a.css'],onTop:()=>pressed.push('top'),onReset:()=>pressed.push('reset')});
  const {scene,options}=f.viewer(),detached=options.controls as FakeNode;
  assert.ok(detached,'the renderer resolves the detached controls');
  assert.deepEqual(f.root.children.map(n=>n.href??n.id),['/a.css','scene','sources'],'the root holds the scene and the closed sources sheet only');
  assert.equal(scene,f.byId('scene'));assert.equal(detached.parent,null,'the detached panels are never inserted');
  const panels=[f.selected.get('.intro')!,f.selected.get('.layers')!,f.byId('target-detail'),f.byId('reading'),f.selected.get('.view-controls')!];
  assert.deepEqual(detached.children,panels);for(const panel of panels)assert.equal(panel.parent,detached);
  assert.ok(f.selected.get('.view-controls')!.children.some(n=>n.id==='sources-open'),'the sources button leaves with the view controls');
  f.byId('top').onclick!();f.byId('reset').onclick!();assert.deepEqual(pressed,['top','reset'],'host button handlers still bind');
  handle.destroy();assert.deepEqual(f.root.children,[],'a host-mode destroy leaves the shadow root empty');
 }finally{f.restore();}
});

test('the terrain-control methods reach the renderer once and go inert after destroy',()=>{
 const f=fixture();
 try{
  const handle=f.mount({chrome:'host'});
  const run=()=>{handle.setRelief(8);handle.setWaterOpacity(.2);handle.setWaterVisible(false);handle.setContours(false);handle.setSourceCoverage(true);handle.setHabitatVisible(false);handle.zoom('in');handle.zoom('out');handle.resetView();handle.topView();handle.openSources();};
  run();
  assert.deepEqual(f.calls,[['setRelief',8],['setWaterOpacity',.2],['setWaterVisible',false],['setContours',false],['setSourceCoverage',true],['setHabitatVisible',false],['zoom','in'],['zoom','out'],['resetView'],['topView'],['openSources']]);
  handle.destroy();const before=f.calls.length;run();assert.equal(f.calls.length,before);
 }finally{f.restore();}
});

test('host-chrome setters change the scene and readings, target detail and sources arrive as data',async()=>{
 const T=await import('three');const {CoastViewer}=await import('../../packages/coast/src/coast3d/viewer.ts');
 // Ids that stay in the shadow root under host chrome; the rest resolve in the detached controls.
 const rootIds=new Set(['labels','pins','loading','mesh-status','habitat-view-note','sources','sources-close','source-list']);
 const nodes=new Map<string,any>(),looked:string[]=[];
 const node=(id:string)=>{if(!nodes.has(id))nodes.set(id,{id,value:'all',textContent:'',hidden:false,checked:true,open:false,shown:0,dataset:{},options:[],children:[],min:'',max:'',step:'',
  replaceChildren(){this.children=[];},append(...n:unknown[]){this.children.push(...n);},setAttribute(key:string,value:string){this[key]=value;},showModal(){this.open=true;this.shown++;},close(){this.open=false;}});return nodes.get(id);};
 const lookup=(inRoot:boolean)=>(selector:string)=>{const id=/^\[id="(.+)"\]$/.exec(selector)?.[1]??selector;if(!inRoot)looked.push(id);return rootIds.has(id)===inRoot?node(id):null;};
 Object.assign(node('relief'),{min:'1',max:'12',step:'1',value:'5'});Object.assign(node('water-opacity'),{min:'0',max:'0.8',step:'0.05',value:'0.5'});node('source-coverage').checked=false;node('reading').hidden=true;node('target-detail').hidden=true;
 node('.coverage-key').textContent='Mint: lidar · blue: survey · amber: chart estimate · purple: regional model';
 const views:any[]=[],readings:any[]=[],details:any[]=[],coverage:any[]=[];let seams=0;
 const v:any=Object.create(CoastViewer.prototype);
 Object.assign(v,{root:{querySelector:lookup(true)},options:{managed:true,controls:{querySelector:lookup(false)},onView:(view:unknown)=>views.push(view),onReading:(r:unknown)=>readings.push(r),onTargetDetail:(d:unknown)=>details.push(d),onSourceCoverage:(c:unknown)=>coverage.push(c)},
  host:{dataset:{},clientWidth:800,clientHeight:600},alive:true,visible:true,speciesSupported:true,habitat:new T.Group(),currents:new T.Group(),waters:new T.Group(),terrain:new T.Group(),pins:[],labels:[],features:[],shoreFeatures:[],shoreGeneration:0,reviewed:null,selectedTarget:null,reefIndex:0,readingGeneration:0,depthLimit:300,revision:0,currentGeneration:0,habitatGeneration:0,frame:0,lodTimer:0,
  perspective:'3d',orbit:new T.Vector3(),orthoHeight:1000,camera:new T.PerspectiveCamera(42,1,2,1000000),scene:new T.Scene(),renderer:{setSize(){},render(){},domElement:{addEventListener(){}}},controls:{target:new T.Vector3(),update(){},touches:{},mouseButtons:{}},currentAt:null,currentLayer:null,
  relief:{value:5},contours:{value:1},sourceColors:{value:0},waterOpacity:{value:.5}});
 v.camera.position.set(-3000,3000,3000);v.refine=()=>{};v.refreshCurrents=()=>{};v.refreshHabitat=()=>{};v.drawPins=()=>{};v.drawCoverageSeams=()=>{seams++;};v.geometry=()=>new T.BufferGeometry();
 const mesh=new T.Mesh(new T.BufferGeometry());mesh.userData.grid={};v.terrain.add(mesh);const water=new T.Mesh(mesh.geometry);v.waters.add(water);
 const saved={window:(globalThis as any).window,document:(globalThis as any).document};
 Object.assign(globalThis,{window:{addEventListener(){},removeEventListener(){}},document:{createElement:(tag:string)=>({tag})}});
 try{
  v.bind();
  const old=mesh.geometry;v.setRelief(7.4);
  assert.equal(v.relief.value,7);assert.equal(node('relief-label').textContent,'×7');assert.notEqual(mesh.geometry,old,'terrain is rebuilt at the new relief');assert.equal(water.geometry,mesh.geometry);assert.equal(seams,1);
  v.setRelief(40);assert.equal(v.relief.value,12);v.setRelief(Number.NaN);assert.equal(v.relief.value,12);
  v.setWaterOpacity(.33);assert.equal(v.waterOpacity.value,.35);v.setWaterOpacity(2);assert.equal(v.waterOpacity.value,.8);
  v.setWaterVisible(false);assert.equal(v.waters.visible,false);v.setWaterVisible(true);assert.equal(v.waters.visible,true);
  v.setContours(false);assert.equal(v.contours.value,0);v.setContours(true);assert.equal(v.contours.value,1);
  v.setSourceCoverage(true);assert.equal(v.sourceColors.value,1);v.setSourceCoverage(false);assert.equal(v.sourceColors.value,0);
  v.setHabitatVisible(false);assert.equal(v.habitat.visible,false);
  const distance=()=>v.camera.position.distanceTo(v.controls.target),far=distance();
  v.zoom('in');assert.ok(Math.abs(distance()-far*.7)<1e-6);v.zoom('out');assert.ok(Math.abs(distance()-far*.7*1.4)<1e-6);assert.equal(views.length,2,'each zoom reports the camera');
  v.topView();assert.equal(v.perspective,'2d');assert.ok(v.camera instanceof T.OrthographicCamera);assert.equal(node('perspective-2d')['aria-pressed'],'true');
  v.zoom('in');assert.ok(Math.abs(v.camera.zoom-1/.7)<1e-9,'the top view zooms its orthographic camera');
  node('reset').dataset.homePlace='avila';v.resetView();
  assert.equal(node('place-title').textContent,'Avila / Port San Luis');const home=views.at(-1);assert.ok(Math.abs(home.latitude-35.16)<.01&&Math.abs(home.longitude+120.76)<.01,'the home view reaches the host');
  v.openSources();v.openSources();assert.equal(node('sources').shown,1,'an open sheet is not reopened');
  // Synthetic sources; the labels below are the native panel's own strings.
  v.manifest={sources:[{id:1,label:'Synthetic lidar',kind:'lidar',resolutionM:1,datum:'Synthetic datum',sourceDate:'2022-06-14',url:'https://example.test/lidar'},{id:2,label:'Synthetic model',kind:'model',resolutionM:30,datum:'Model sea level',sourceDate:'2013-01-01',url:'https://example.test/model'}]};
  v.listSources();
  assert.deepEqual(coverage,[{sources:v.manifest.sources,key:node('.coverage-key').textContent}]);assert.ok(Object.isFrozen(coverage[0].sources[0]));assert.equal(node('source-list').children.length,2);
  v.showReading(0,0,{height:-6,source:1,spacing:2});v.showReading(0,0,{height:-40,source:2,spacing:30});
  assert.deepEqual(readings.map(r=>[r.label,r.source.sourceDate,r.value,r.heightM]),[['MEASURED LIDAR · NAVD88','2022-06-14','20 ft depth',-6],['REGIONAL MODEL','2013-01-01','131 ft depth',-40]]);
  assert.ok(readings[0].detail.startsWith('Synthetic lidar · 2022-06-14 · 2 m display spacing. Synthetic datum.'));assert.ok(Number.isFinite(readings[0].latitude)&&Number.isFinite(readings[0].longitude));
  v.setLocation({latitude:35.3,longitude:-120.9});v.setLocation({latitude:35.31,longitude:-120.9});assert.deepEqual(readings.slice(2),[null],'a cleared reading is reported once');
  const reef={id:'synthetic-reef',properties:{waypoint_latitude:35.9,waypoint_longitude:-121.5,region:'cambria-san-simeon',terrain_grade:'B',depth_min_ft:40,depth_max_ft:70,terrain_score:60,resolution_m:2,source_year:2020,metric_support_fraction:.9,screen_expires_at:'2027-01-01T00:00:00Z'}};
  v.selectFeature(reef,false);
  assert.equal(details.length,1);const detail=details[0];
  assert.deepEqual([detail.id,detail.kind,detail.title],['synthetic-reef','reef','Reviewed reef · grade B']);assert.match(detail.facts,/^Nominal 40–70 ft · physical score 60\/100/);assert.match(detail.evidence,/Fish presence unverified\./);
  assert.equal(node('target-detail').hidden,false);v.selectHabitat(null);assert.deepEqual(details.slice(1),[null]);assert.equal(node('target-detail').hidden,true);
  for(const id of ['relief','water-opacity','water','contours','source-coverage','habitat','zoom-in','reset','reading','target-detail','.coverage-key'])assert.ok(looked.includes(id),id+' resolves outside the root');
 }finally{Object.assign(globalThis,saved);}
});

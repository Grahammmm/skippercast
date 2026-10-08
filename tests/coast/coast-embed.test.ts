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

// Nodes by id and by selector, recording what the embed changes.
type FakeNode={id?:string;hidden:boolean;textContent:string;removed:boolean;attributes:Record<string,string>;dataset:Record<string,string>;children:FakeNode[];href?:string;rel?:string;onclick:null|(()=>void);append(...nodes:FakeNode[]):void;remove():void;setAttribute(key:string,value:string):void;closest(selector:string):FakeNode};
function node(init:Partial<FakeNode>={}):FakeNode{
 const label=init.id==='currents'?node({id:'currents-label'}):null;
 return {hidden:false,textContent:'',removed:false,attributes:{},dataset:{},children:[],onclick:null,...init,
  append(...nodes){this.children.push(...nodes);},remove(){this.removed=true;},setAttribute(key,value){this.attributes[key]=value;},
  closest(selector){assert.equal(selector,'label');return label!;}};
}
function fixture(){
 const ids=new Map<string,FakeNode>(),selected=new Map<string,FakeNode>(),parsed:string[]=[];
 const byId=(id:string)=>ids.get(id)??(ids.set(id,node({id})),ids.get(id)!);
 const receipts=[...coastSourcesMarkup.matchAll(/data-coast-receipt="([^"]+)"/g)].map(m=>node({dataset:{coastReceipt:m[1]!}}));
 const reportLinks=[...coastEmbedTemplate.matchAll(/href="index\.html#forecast"/g)].map(()=>node({href:'index.html#forecast'}));
 const root=node();
 Object.assign(root,{getElementById:byId,querySelector:(selector:string)=>selected.get(selector)??(selected.set(selector,node()),selected.get(selector)!),
  querySelectorAll:(selector:string)=>selector==='[data-coast-receipt]'?receipts:selector==='a[href="index.html#forecast"]'?reportLinks:[]});
 let attached=0;
 const host={attachShadow:(init:{mode:string})=>{assert.equal(init.mode,'open');attached++;return root;}};
 const saved={document:globalThis.document,DOMParser:globalThis.DOMParser};
 Object.assign(globalThis,{document:{createElement:(tag:string)=>node({attributes:{tag}}),importNode:(n:FakeNode,deep:boolean)=>{assert.equal(deep,true);return n;}},
  DOMParser:class{parseFromString(text:string,type:string){assert.equal(type,'text/html');parsed.push(text);return {getElementById:byId};}}});
 const calls:unknown[][]=[];let viewerArgs:{scene:unknown;options:any}|null=null;
 class FakeViewer{constructor(scene:unknown,options:any){viewerArgs={scene,options};}
  load(){calls.push(['load']);return Promise.resolve(true);}setPerspective(m:unknown){calls.push(['setPerspective',m]);}setLocation(p:unknown){calls.push(['setLocation',p]);}
  setSpecies(id:string){calls.push(['setSpecies',id]);return id!=='tuna';}setHour(at:unknown){calls.push(['setHour',at]);}setDepthLimit(ft:unknown){calls.push(['setDepthLimit',ft]);}
  setCurrentLayer(id:unknown){calls.push(['setCurrentLayer',id]);}selectHabitat(id:unknown){calls.push(['selectHabitat',id]);}setVisible(v:unknown){calls.push(['setVisible',v]);}destroy(){calls.push(['destroy']);}}
 const mount=(options?:CoastMountOptions)=>mountCoast(host as unknown as HTMLElement,options,(scene,viewerOptions)=>new FakeViewer(scene,viewerOptions) as never);
 return {root,byId,selected,receipts,reportLinks,parsed,calls,mount,attached:()=>attached,viewer:()=>viewerArgs!,restore:()=>Object.assign(globalThis,saved)};
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
  const added=f.selected.get('.view-controls')!.children;
  assert.deepEqual(added.map(n=>[n.id,n.hidden]),[['perspective-2d',true],['perspective-3d',true],['sources-open',false]]);
  assert.equal(added[2]!.textContent,'ⓘ');assert.equal(added[2]!.attributes['aria-label'],'Terrain sources and assumptions');
  assert.equal(f.receipts.length,3);assert.deepEqual(f.receipts.map(n=>n.href),f.receipts.map(n=>coastPath(n.dataset.coastReceipt!)));
  assert.ok(f.reportLinks.length>0);for(const link of f.reportLinks)assert.equal(link.href,'#forecast');
  const {scene,options}=f.viewer();assert.equal(scene,f.byId('scene'));assert.equal(options.root,f.root);assert.equal(options.managed,true);
  assert.equal('palette' in options,false,'v1 passes no palette, so the renderer keeps DEFAULT_COAST_PALETTE');
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

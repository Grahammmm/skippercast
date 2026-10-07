import test from 'node:test';
import assert from 'node:assert/strict';
import * as T from 'three';
import type {Grid} from '../../packages/coast/src/coast3d/grid.ts';

// Exercise the actual rendering method without constructing a WebGL renderer.
// The browser module has its own DOM-only typecheck; load it at runtime so this
// server test does not combine its globals with the Workers type environment.
const {CoastViewer}=await import(new URL('../../packages/coast/src/coast3d/viewer.ts',import.meta.url).href);
const prototype=CoastViewer.prototype as unknown as {
 drawCoverageSeams(this:unknown):void;
 readingAt(this:unknown,x:number,z:number):{height:number;source:number;spacing:number}|null;
 geometry(this:unknown,grid:Grid,skirts?:boolean):T.BufferGeometry;
 addSurface(this:unknown,grid:Grid,kind:number,child:boolean):{mesh:T.Mesh;water:T.Mesh};
 bind(this:unknown):void;
};
function grid(x:number,z:number,size:number,dx:number,value:(x:number,z:number)=>number,source=4):Grid{
 return {x,z,size,dx,dz:dx,values:Float32Array.from({length:size*size},(_,i)=>value(x+i%size*dx,z+Math.floor(i/size)*dx)),sources:new Uint8Array(size*size).fill(source)};
}
function mesh(g:Grid,skirts=false):T.Mesh{
 const count=g.size*g.size,positions=new Float32Array((count+(skirts?16*(g.size-1):0))*3);
 for(let i=0;i<count;i++)positions.set([g.x+i%g.size*g.dx,g.values[i],g.z+Math.floor(i/g.size)*g.dz],i*3);
 const geometry=new T.BufferGeometry();geometry.setAttribute('position',new T.BufferAttribute(positions,3));
 geometry.setAttribute('sourceHeight',new T.BufferAttribute(g.values.slice(),1));
 return new T.Mesh(geometry);
}

test('streaming bands keep all exterior corners pinned to the parent and preserve original readings',()=>{
 const parent=grid(-4096,-4096,5,4096,(x,z)=>.1*x+.2*z),parentMesh=mesh(parent);
 parentMesh.userData.kind=0;
 const child=grid(0,0,33,128,()=>100),childMesh=mesh(child,true),terrain=new T.Group();terrain.add(parentMesh);
 const viewer={overview:parent,background:null,terrain,seams:new T.Group(),relief:{value:1},manifest:{waterReferenceM:0},
  loaded:new Map([['t0:0',{grid:child,tile:{x:0,z:0,width:4096},mesh:childMesh,child:false}]]),
  clear(group:T.Group){group.clear();}};
 const originalValues=child.values.slice(),originalSources=child.sources!.slice(),sourceHeights=(childMesh.geometry.getAttribute('sourceHeight') as T.BufferAttribute).array.slice();
 prototype.drawCoverageSeams.call(viewer);
 const positions=childMesh.geometry.getAttribute('position') as T.BufferAttribute;
 for(let row=0;row<33;row++)for(let col=0;col<33;col++)if(row===0||row===32||col===0||col===32){
  assert.ok(Math.abs(positions.getY(row*33+col)-(.1*col*128+.2*row*128))<.001,`Unmatched boundary at ${col},${row}`);
 }
 assert.equal(positions.getY(16*33+16),100);
 assert.deepEqual(child.values,originalValues);assert.deepEqual(child.sources,originalSources);
 assert.deepEqual((childMesh.geometry.getAttribute('sourceHeight') as T.BufferAttribute).array,sourceHeights);
 assert.equal(prototype.readingAt.call(viewer,0,128)?.height,100);
 const firstPositions=positions.array.slice();prototype.drawCoverageSeams.call(viewer);
 assert.deepEqual(positions.array,firstPositions,'Repeated refresh must not accumulate morphing');
 // First skirt follows both matched top vertices and its original depth.
 assert.equal(positions.getY(1089),positions.getY(0));
 assert.equal(positions.getY(1090),positions.getY(1));
 assert.equal(positions.getY(1091),positions.getY(0)-512);
});

test('regional overview readings retain actual land/model identities and fall back to wide ETOPO',()=>{
 const parent=grid(0,0,3,100,()=>15,19);parent.sources![1]=20;
 const viewer={loaded:new Map(),overview:parent,background:grid(-1000,-1000,3,1000,()=>-1200,1)};
 assert.deepEqual(prototype.readingAt.call(viewer,0,0),{height:15,source:19,spacing:100});
 assert.deepEqual(prototype.readingAt.call(viewer,100,0),{height:15,source:20,spacing:100});
 assert.deepEqual(prototype.readingAt.call(viewer,-1000,0),{height:-1200,source:1,spacing:1000});
});

test('mixed-detail neighbors meet the same rendered boundary in either loading order without exposed skirts',()=>{
 const run=(reverse:boolean)=>{
  const parent=grid(-1024,-1024,5,1024,()=>0,1),parentMesh=mesh(parent);parentMesh.userData.kind=0;
  const terrain=new T.Group();terrain.add(parentMesh);
  const viewer={overview:parent,background:null,terrain,seams:new T.Group(),relief:{value:5},manifest:{waterReferenceM:0},loaded:new Map<string,any>(),visualSource:(id:number)=>id,clear(group:T.Group){group.clear();}};
  const grids=[grid(0,0,9,128,()=>-5,2),grid(1024,0,65,16,()=>-9,7)];
  const items=grids.map(g=>({grid:g,tile:{x:g.x,z:g.z,width:1024},mesh:new T.Mesh(prototype.geometry.call(viewer,g,true)),child:true}));
  for(const item of reverse?[...items].reverse():items)viewer.loaded.set('h'+item.tile.x+':'+item.tile.z,item);
  const originals=grids.map(g=>({values:g.values.slice(),sources:g.sources!.slice()}));prototype.drawCoverageSeams.call(viewer);
  const coarse=items[0].mesh.geometry.getAttribute('position'),fine=items[1].mesh.geometry.getAttribute('position');
  for(let row=0;row<65;row++){const fraction=row/8,base=Math.min(7,Math.floor(fraction)),t=fraction-base,expected=coarse.getY(base*9+8)*(1-t)+coarse.getY((base+1)*9+8)*t;assert.ok(Math.abs(fine.getY(row*65)-expected)<.00001,'A shared fine edge must match the coarser surface');}
  assert.equal(fine.getY(32*65+32),-45,'Supported interior relief remains intact');
  for(let k=0;k<items.length;k++){const g=items[k].mesh.geometry;assert.equal(g.drawRange.count,g.userData.surfaceTriangleCount*3,'Closed edges do not draw skirts');assert.deepEqual(grids[k].values,originals[k].values);assert.deepEqual(grids[k].sources,originals[k].sources);assert.deepEqual(Array.from(g.getAttribute('sourceHeight').array.slice(0,grids[k].values.length)),Array.from(originals[k].values));}
  assert.equal(prototype.readingAt.call(viewer,1024,512)?.height,-9);
  const positions=items.map(item=>Array.from(item.mesh.geometry.getAttribute('position').array));prototype.drawCoverageSeams.call(viewer);assert.deepEqual(items.map(item=>Array.from(item.mesh.geometry.getAttribute('position').array)),positions);
  assert.equal(items[1].mesh.geometry.getAttribute('displayHeight').getX(32*65),fine.getY(32*65)/5,'Visual water mask follows the seam surface, not an inconsistent raw sample');
  return positions;
 };
 assert.deepEqual(run(false),run(true));
});

test('all map surfaces exclude curtain skirts during loading and relief changes',()=>{
 const nodes=new Map<string,{options:unknown[];value:string;oninput?:()=>void}>();
 const node=(id:string)=>{if(!nodes.has(id))nodes.set(id,{options:[],value:'2'});return nodes.get(id)!;};
 const globals=globalThis as unknown as Record<string,unknown>,saved=new Map<string,PropertyDescriptor|undefined>();
 for(const [name,value] of Object.entries({document:{getElementById:node},location:{search:''},window:{addEventListener(){}}})){
  saved.set(name,Object.getOwnPropertyDescriptor(globalThis,name));Object.defineProperty(globalThis,name,{value,writable:true,configurable:true});
 }
 try{
  const viewer={terrain:new T.Group(),waters:new T.Group(),relief:{value:1},manifest:{waterReferenceM:0},
   renderer:{domElement:{addEventListener(){}}},visualSource:(id:number)=>id,
   geometry(g:Grid,skirts?:boolean){return prototype.geometry.call(this,g,skirts);},material(){return new T.MeshBasicMaterial();},drawCoverageSeams(){},goPlace(){}};
  const g=grid(0,0,3,100,()=>-10),surfaces=[0,4,1,2].map(kind=>({kind,...prototype.addSurface.call(viewer,g,kind,kind===2)}));
  const verify=()=>{for(const {kind,mesh,water} of surfaces){
   assert.equal(mesh.geometry,water.geometry,'Water must share the same limited geometry');
   const expected=mesh.geometry.userData.surfaceTriangleCount*3;
   assert.equal(mesh.geometry.drawRange.count,expected,`Curtain skirts returned for kind ${kind}`);
   assert.ok(mesh.geometry.getIndex()!.count>expected,'Fixture must contain real skirt indices');
  }};
  verify();prototype.bind.call(viewer);node('relief').oninput!();verify();
 }finally{for(const [name,descriptor] of saved){if(descriptor)Object.defineProperty(globalThis,name,descriptor);else delete globals[name];}}
});

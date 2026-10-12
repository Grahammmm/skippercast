// FE-81 (design § 3A.2 "Layers"): host overlays draped on the coast terrain.
// Synthetic terrain and features in scene metres around the projection origin;
// no GPU: drape, depth and picking are checked on the geometry and the
// cameras CoastViewer builds for 3D and 2D.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as T from 'three';
import {coastLonLat,coastPoint,type Grid} from '../../packages/coast/src/coast3d/grid.ts';
import {CoastOverlays,DRAPE_M,MAX_OVERLAY_SEGMENTS,MAX_OVERLAY_TRIANGLES,OVERLAY_DEPTH_BIAS,OVERLAY_LIFT,OVERLAY_RENDER_BASE,cutFill,drapeTriangles,lineStep,terrainSampler,type CoastOverlay,type CoastOverlayFeature} from '../../packages/coast/src/coast3d/overlays.ts';
import {COAST_OVERLAY_COLORS,type CoastOverlayPalette} from '../../packages/coast/src/palette.ts';

// Values in the shape of web/map/palette.ts readPalette(); any valid colours do.
const palette:CoastOverlayPalette=Object.freeze({bg:'#07131d',line:'#223849',text:'#e6eff4',muted:'#8ba5b7',mint:'#69e0bc',blue:'#73bfff',coral:'#ff9c86',amber:'#eabd76',mpaFill:'#e8a877',mpaLine:'#e8b584'});
const WATER=0;
type XZ=[number,number];
const lonLat=([x,z]:XZ)=>coastLonLat(x,z);

// A 50 m grid with a hill rising out of the sea, over a coarse 200 m sea floor.
function surface(size:number,spacing:number,x0:number,z0:number,height:(x:number,z:number)=>number){
 const values=new Float32Array(size*size),position=new Float32Array(size*size*3);
 for(let row=0;row<size;row++)for(let col=0;col<size;col++){const i=row*size+col,x=x0+col*spacing,z=z0+row*spacing,y=height(x,z);values[i]=y;position.set([x,y,z],i*3);}
 const geometry=new T.BufferGeometry();geometry.setAttribute('position',new T.BufferAttribute(position,3));
 const mesh=new T.Mesh(geometry);mesh.userData.grid={x:x0,z:z0,size,dx:spacing,dz:spacing,values} satisfies Grid;return mesh;
}
const hill=(x:number,z:number)=>140*Math.exp(-((x-150)**2+(z+50)**2)/350**2)-40;
function terrain(){const group=new T.Group();group.add(surface(41,200,-4000,-4000,()=>-60),surface(41,50,-1000,-1000,hill));return group;}

// An irregular area with a hole, its edges crossing the hill at angles.
const outer:XZ[]=[[-650,-500],[500,-640],[700,300],[-100,650],[-700,200]],hole:XZ[]=[[-150,-100],[150,-120],[0,160]];
const ring=(points:XZ[])=>[...points,points[0]!].map(lonLat);
const zones:CoastOverlay={kind:'fill',order:0,style:{color:'mpaFill',outline:'mpaLine'},features:[{id:'zone-1',geometry:{type:'Polygon',coordinates:[ring(outer),ring(hole)]}}]};
const tracks:CoastOverlay={kind:'line',order:1,style:{color:'amber'},features:[{id:7,geometry:{type:'LineString',coordinates:[lonLat([-600,-300]),lonLat([600,-250])]}}]};
const marks:CoastOverlay={kind:'point',order:2,style:{color:'mint',outline:'bg',size:10},features:[{id:'mark-a',geometry:{type:'Point',coordinates:lonLat([300,200])}},{id:'mark-b',geometry:{type:'Point',coordinates:lonLat([-400,350])}}]};

function overlays(){const o=new CoastOverlays(palette),scene=terrain();o.drape(terrainSampler(scene,WATER));return {o,scene,sample:terrainSampler(scene,WATER)};}
const parts=(o:CoastOverlays,id:string)=>o.group.children.filter(c=>c.name==='overlay:'+id) as (T.Mesh|T.LineSegments|T.Points)[];
const positions=(object:T.Object3D)=>(object as T.Mesh).geometry.getAttribute('position') as T.BufferAttribute;
const area=(p:XZ[])=>Math.abs(p.reduce((s,a,i)=>{const b=p[(i+1)%p.length]!;return s+a[0]*b[1]-b[0]*a[1];},0))/2;
// Millimetre keys; `+0` folds -0 into 0 so a cut that lands a hair below a grid line matches its twin.
const key=(x:number,z:number)=>[x,z].map(v=>(Math.round(v*1000)/1000+0).toFixed(3)).join(',');
function onSegment(x:number,z:number,a:XZ,b:XZ){const dx=b[0]-a[0],dz=b[1]-a[1],t=Math.max(0,Math.min(1,((x-a[0])*dx+(z-a[1])*dz)/(dx*dx+dz*dz)));return Math.hypot(a[0]+dx*t-x,a[1]+dz*t-z)<1e-3;}

test('the sampler reads the finest displayed mesh and never goes below the water reference',()=>{
 const {sample}=overlays();
 assert.ok(Math.abs(sample(150,-50)-100)<1e-3,'hill top from the 50 m grid');
 assert.equal(sample(-900,900),0,'sea floor below the water reads as the water surface');
 assert.equal(sample(9000,9000),0,'outside every grid the water surface carries the overlay');
});

test('a fill is cut on the drape grid, sits on the surface and closes without cracks',()=>{
 const {o,sample}=overlays();o.set('zones',zones);
 const [fill,outline]=parts(o,'zones') as [T.Mesh,T.LineSegments];
 assert.ok(fill instanceof T.Mesh&&outline instanceof T.LineSegments);
 const p=positions(fill),triangles:XZ[][]=[];
 for(let i=0;i<p.count;i++){const x=p.getX(i),z=p.getZ(i);assert.ok(Math.abs(p.getY(i)-(sample(x,z)+OVERLAY_LIFT.fill))<1e-3,`fill vertex ${i} on the surface`);}
 for(let i=0;i<p.count;i+=3){const t:XZ[]=[0,1,2].map(k=>[p.getX(i+k),p.getZ(i+k)] as XZ);triangles.push(t);
  const xs=t.map(v=>v[0]),zs=t.map(v=>v[1]);
  assert.ok(Math.max(...xs)-Math.min(...xs)<=DRAPE_M+1e-6&&Math.max(...zs)-Math.min(...zs)<=DRAPE_M+1e-6,'every triangle fits one drape cell, so it follows the relief');}
 const covered=triangles.reduce((s,t)=>s+area(t),0),expected=area(outer.map(v=>coastPoint(...lonLat(v))))-area(hole.map(v=>coastPoint(...lonLat(v))));
 assert.ok(Math.abs(covered-expected)/expected<1e-6,`the cut covers the polygon minus its hole (${covered} vs ${expected})`);
 // Watertight: every triangle edge is shared by two triangles, except edges on a ring.
 const edges=new Map<string,number>();
 for(const t of triangles)for(let k=0;k<3;k++){const a=t[k]!,b=t[(k+1)%3]!,id=[key(...a),key(...b)].sort().join('|');edges.set(id,(edges.get(id)??0)+1);}
 const rings=[outer,hole].map(r=>r.map(v=>coastPoint(...lonLat(v)) as XZ));
 for(const [id,count] of edges){
  assert.ok(count<=2,id);
  if(count===1){const [a,b]=id.split('|').map(s=>s.split(',').map(Number) as XZ);
   assert.ok(rings.some(r=>r.some((v,i)=>{const w=r[(i+1)%r.length]!;return onSegment(a![0],a![1],v,w)&&onSegment(b![0],b![1],v,w);})),`open edge ${id} lies on a ring`);}
 }
 const l=positions(outline);
 for(let i=0;i<l.count;i++)assert.ok(Math.abs(l.getY(i)-(sample(l.getX(i),l.getZ(i))+OVERLAY_LIFT.line))<1e-3,'outline on the surface');
 for(let i=0;i<l.count;i+=2)assert.ok(Math.hypot(l.getX(i+1)-l.getX(i),l.getZ(i+1)-l.getZ(i))<=DRAPE_M+1e-6,'outline segments follow the relief');
});

test('drapeTriangles keeps area and splits only along grid lines',()=>{
 const flat=drapeTriangles([10,10],[260,40],[90,330],100)!;
 let sum=0;for(let i=0;i<flat.length;i+=6)sum+=area([[flat[i]!,flat[i+1]!],[flat[i+2]!,flat[i+3]!],[flat[i+4]!,flat[i+5]!]]);
 assert.ok(Math.abs(sum-area([[10,10],[260,40],[90,330]]))<1e-6);
 assert.deepEqual(drapeTriangles([0,0],[100,0],[200,0],100),[],'a degenerate triangle yields nothing');
 assert.equal(drapeTriangles([10,10],[260,40],[90,330],100,[],flat.length/6-1),null,'the cut stops once it passes its limit');
});

test('cell and step growth: the finest DRAPE_M doubling that fits the cap',()=>{
 const square=[0,0,1000,0,1000,1000,0,0,1000,1000,0,1000];
 const fine=cutFill(square,Infinity)!;assert.equal(fine.cell,DRAPE_M);
 const coarse=cutFill(square,20)!;
 assert.ok(coarse.xz.length/6<=20&&coarse.cell>DRAPE_M&&Number.isInteger(Math.log2(coarse.cell/DRAPE_M)),`cell ${coarse.cell}, ${coarse.xz.length/6} triangles`);
 assert.ok(cutFill(square,20-1)===null||cutFill(square,20-1)!.cell>=coarse.cell,'a tighter cap never picks a finer cell');
 assert.equal(coarse.source.length,coarse.xz.length/6,'every piece keeps its source triangle');
 assert.equal(cutFill(square,1),null,'two source triangles cannot fit one');
 const line=[{xz:[[0,0],[1000,0]] as XZ[],closed:false}];
 assert.equal(lineStep(line,Infinity),DRAPE_M);assert.equal(lineStep(line,3),400,'100 m and 200 m need 10 and 5 segments; 400 m needs 3');
 assert.equal(lineStep([{xz:[[0,0],[10,0],[20,0],[30,0]] as XZ[],closed:false}],2),null,'unsplit paths over the cap are refused');
});

test('a pathological comb stays under the hard caps by coarsening the drape',()=>{
 // 4,000 vertices: 2,000 slivers 20 km long and 10 m wide.
 const teeth:XZ[]=[];for(let i=0;i<2000;i++)teeth.push([i*10,20000],[i*10+5,0]);
 const comb:CoastOverlay={kind:'fill',style:{color:'mpaFill',outline:'mpaLine'},features:[{id:'comb',geometry:{type:'Polygon',coordinates:[ring([...teeth,[20000,-100],[0,-100]])]}}]};
 const o=new CoastOverlays(palette),started=performance.now();o.set('comb',comb);const ms=performance.now()-started;
 const [fill,outline]=parts(o,'comb') as [T.Mesh,T.LineSegments],spacing=o.spacing('comb')!;
 const triangles=positions(fill).count/3,segments=positions(outline).count/2;
 assert.ok(triangles<=MAX_OVERLAY_TRIANGLES,`${triangles} triangles`);assert.ok(segments<=MAX_OVERLAY_SEGMENTS,`${segments} segments`);
 assert.ok(spacing.cell>DRAPE_M&&spacing.step>DRAPE_M,`coarsened to a ${spacing.cell} m cell and ${spacing.step} m step`);
 const p=positions(fill);for(let i=0;i<p.count;i+=3){const xs=[p.getX(i),p.getX(i+1),p.getX(i+2)];assert.ok(Math.max(...xs)-Math.min(...xs)<=spacing.cell+1e-3);}
 assert.ok(ms<5000,`built in ${Math.round(ms)} ms`);
 assert.deepEqual(o.spacing('zones'),null);o.set('zones',zones);assert.deepEqual(o.spacing('zones'),{cell:DRAPE_M,step:DRAPE_M},'a normal overlay keeps the full drape');
});

test('an overlay that cannot fit the caps is refused with a clear error and changes nothing',()=>{
 const o=new CoastOverlays(palette,{triangles:4,segments:6});o.drape(terrainSampler(terrain(),WATER));
 o.set('tracks',tracks);assert.equal(o.spacing('tracks')!.step>DRAPE_M,true,'a 1.2 km line coarsens to fit six segments');
 const before=[...o.group.children];
 assert.throws(()=>o.set('zones',{...zones,style:{color:'mpaFill'}}),/too detailed to drape: more than 4 fill triangles at any cell size/);
 assert.throws(()=>o.set('tracks',{...tracks,features:[{id:1,geometry:{type:'LineString',coordinates:[0,1,2,3,4,5,6,7].map(i=>lonLat([i*10,0]))}}]}),/too detailed to drape: more than 6 line segments/);
 assert.deepEqual(o.group.children,before,'the existing overlay is untouched');
});

// The cameras CoastViewer builds: the 3D orbit (fov 42, near 2) and the 2D top view.
function cameras(span:number,width=900,height=600){
 const target=new T.Vector3(0,0,0);
 const perspective=new T.PerspectiveCamera(42,width/height,2,1000000);perspective.position.copy(target).add(new T.Vector3(-.56,.46,.6).normalize().multiplyScalar(span));
 const ortho=new T.OrthographicCamera(-1,1,1,-1,2,1000000),orthoHeight=span*2*Math.tan(T.MathUtils.degToRad(21)),half=orthoHeight/2;
 Object.assign(ortho,{left:-half*width/height,right:half*width/height,top:half,bottom:-half});ortho.position.copy(target).add(new T.Vector3(0,Math.max(25000,span),.01));
 const views=[{name:'3d',camera:perspective as T.Camera,perPixel:span*2*Math.tan(T.MathUtils.degToRad(21))/height},{name:'2d',camera:ortho as T.Camera,perPixel:orthoHeight/height}];
 for(const {camera} of views){camera.lookAt(target);camera.updateMatrixWorld();(camera as T.PerspectiveCamera).updateProjectionMatrix();}
 return views;
}

test('overlays never share depth with the surface in 3D or 2D',()=>{
 const {o,sample}=overlays();o.set('zones',zones);o.set('tracks',tracks);o.set('marks',marks);
 // One step of a 24-bit depth buffer in normalised device coordinates.
 const step=2/2**24;
 for(const span of [1500,6000,20000])for(const {name,camera} of cameras(span)){
  const forward=camera.getWorldDirection(new T.Vector3());
  let worst=Infinity;
  for(const object of o.group.children){const p=positions(object);for(let i=0;i<p.count;i+=7){
   const v=new T.Vector3(p.getX(i),p.getY(i),p.getZ(i)),direction=camera instanceof T.OrthographicCamera?forward:v.clone().sub(camera.position).normalize();
   // The surface the same view ray meets behind the overlay vertex.
   let t=0;while(t<5000&&v.y+direction.y*t>sample(v.x+direction.x*t,v.z+direction.z*t))t+=.25;
   assert.ok(t<5000,`${name}: the ray meets the surface`);
   const hit=v.clone().addScaledVector(direction,t),drawn=v.clone().project(camera).z-OVERLAY_DEPTH_BIAS,ground=hit.project(camera).z;
   worst=Math.min(worst,(ground-drawn)/step);
  }}
  assert.ok(worst>=8,`${name} at ${span} m: overlays lead the surface by ${worst.toFixed(1)} depth steps`);
 }
});

test('every overlay material carries the depth bias, and points are round',()=>{
 const {o}=overlays();o.set('zones',zones);o.set('marks',marks);
 for(const object of o.group.children){
  const material=(object as T.Mesh).material as T.Material,shader={vertexShader:'a\n#include <project_vertex>\nb',fragmentShader:'#include <clipping_planes_fragment>'} as unknown as T.WebGLProgramParametersWithUniforms;
  material.onBeforeCompile(shader,{} as T.WebGLRenderer);
  assert.match(shader.vertexShader,/#include <project_vertex>\ngl_Position\.z-=0\.0000010\*gl_Position\.w;/);
  assert.equal(shader.fragmentShader.includes('discard'),object instanceof T.Points);
  assert.equal(material.depthWrite,false);assert.equal(material.transparent,true);
 }
});

test('styles take palette roles only, and colours come from the host palette',()=>{
 const {o}=overlays();o.set('zones',zones);o.set('marks',marks);
 const [fill,outline]=parts(o,'zones') as [T.Mesh,T.LineSegments],[ring,dot]=parts(o,'marks') as [T.Points,T.Points];
 assert.equal((fill.material as T.MeshBasicMaterial).color.getHexString(),palette.mpaFill.slice(1));assert.equal((fill.material as T.MeshBasicMaterial).opacity,.25);
 assert.equal((outline.material as T.LineBasicMaterial).color.getHexString(),palette.mpaLine.slice(1));
 assert.equal((ring.material as T.PointsMaterial).color.getHexString(),palette.bg.slice(1));assert.equal((ring.material as T.PointsMaterial).size,13);
 assert.equal((dot.material as T.PointsMaterial).color.getHexString(),palette.mint.slice(1));assert.equal((dot.material as T.PointsMaterial).sizeAttenuation,false);
 assert.deepEqual([...COAST_OVERLAY_COLORS].sort(),Object.keys(palette).sort());
 const before=o.group.children.length;
 for(const color of ['#ff0000','red','var(--mint)'])assert.throws(()=>o.set('bad',{...marks,style:{color:color as never}}),/unknown colour role/);
 assert.throws(()=>new CoastOverlays().set('zones',zones),/overlayPalette/);
 assert.throws(()=>new CoastOverlays({...palette,mpaFill:'var(--mpa-fill)'}).set('zones',zones),/must be a hex, RGB or HSL colour/);
 assert.equal(o.group.children.length,before,'a refused overlay adds nothing');
});

test('invalid features are refused before anything changes',()=>{
 const {o}=overlays();o.set('zones',zones);const before=[...o.group.children];
 const point={type:'Point',coordinates:lonLat([0,0])} as const;
 const cases:[CoastOverlay,RegExp][]=[
  [{...zones,kind:'label' as never},/unknown kind/],
  [{...zones,features:[{id:'p',geometry:point}]},/fill overlay takes Polygon or MultiPolygon/],
  [{...marks,features:[{geometry:point} as unknown as CoastOverlayFeature]},/needs a string or number id/],
  [{...marks,features:[{id:'x',geometry:{type:'Point',coordinates:[Number.NaN,35]}}]},/finite WGS84/],
  [{...tracks,features:[{id:1,geometry:{type:'LineString',coordinates:[lonLat([0,0])]}}]},/two positions/],
  [{...zones,features:[{id:1,geometry:{type:'Polygon',coordinates:[[lonLat([0,0]),lonLat([1,1]),lonLat([0,0])]]}}]},/three distinct positions/],
  [{...marks,style:{color:'mint',opacity:2}},/opacity must be between 0 and 1/],
  [{...marks,order:Number.NaN},/order must be a finite number/],
 ];
 for(const [overlay,why] of cases)assert.throws(()=>o.set('zones',overlay),why);
 assert.deepEqual(o.group.children,before,'the existing overlay is untouched');
 assert.throws(()=>o.set('',zones),/non-empty string/);
});

test('removing an overlay frees its geometry and materials',()=>{
 const {o}=overlays();o.set('zones',zones);o.set('marks',marks);
 const freed:string[]=[],watch=(id:string)=>{for(const object of parts(o,id)){object.geometry.addEventListener('dispose',()=>freed.push(id+':geometry'));((object as T.Mesh).material as T.Material).addEventListener('dispose',()=>freed.push(id+':material'));}};
 watch('zones');watch('marks');
 assert.equal(o.remove('zones'),true);
 assert.deepEqual(freed.sort(),['zones:geometry','zones:geometry','zones:material','zones:material']);
 assert.equal(parts(o,'zones').length,0);assert.equal(o.remove('zones'),false,'an unknown id is false');
 // Replacing frees the old parts too.
 freed.length=0;o.set('marks',{...marks,features:marks.features.slice(0,1)});
 assert.deepEqual(freed.sort(),['marks:geometry','marks:geometry','marks:material','marks:material']);
 // dispose frees the rest and later calls do nothing.
 const scene=new T.Scene();scene.add(o.group);freed.length=0;watch('marks');o.dispose();
 assert.equal(freed.length,4);assert.equal(o.group.children.length,0);assert.equal(o.group.parent,null);
 o.set('zones',zones);assert.equal(o.group.children.length,0);
});

test('overlays stack in draw order, and a replacement keeps its place',()=>{
 const {o}=overlays();o.set('marks',marks);o.set('zones',zones);o.set('tracks',tracks);o.set('more-zones',{...zones,order:0});
 const rank=(id:string)=>Math.min(...parts(o,id).map(p=>p.renderOrder));
 assert.ok(rank('zones')>=OVERLAY_RENDER_BASE);
 assert.ok(rank('zones')<rank('more-zones')&&rank('more-zones')<rank('tracks')&&rank('tracks')<rank('marks'),'order, then the order first set');
 const [fill,outline]=parts(o,'zones');assert.ok(fill!.renderOrder<outline!.renderOrder,'a fill draws under its outline');
 const [ring,dot]=parts(o,'marks');assert.ok(ring!.renderOrder<dot!.renderOrder,'a point draws over its ring');
 o.set('zones',{...zones,style:{color:'coral'}});assert.ok(rank('zones')<rank('more-zones'),'a replacement keeps its stacking place');
 o.set('zones',{...zones,order:5});assert.ok(rank('zones')>rank('marks'));
});

test('a pick returns the overlay id and feature id under the pointer in 3D and 2D',()=>{
 const {o,sample}=overlays();o.set('zones',zones);o.set('tracks',tracks);o.set('marks',marks);
 const at=([x,z]:XZ,lift:number)=>new T.Vector3(x,sample(x,z)+lift,z);
 for(const {name,camera,perPixel} of cameras(3000)){
  const caster=new T.Raycaster(),pick=(point:T.Vector3)=>{const p=point.clone().project(camera);caster.setFromCamera(new T.Vector2(p.x,p.y),camera);return o.pick(caster.ray,perPixel);};
  const fill=pick(at([-450,0],OVERLAY_LIFT.fill));
  assert.deepEqual(fill&&{overlay:fill.overlay,feature:fill.feature,kind:fill.kind},{overlay:'zones',feature:'zone-1',kind:'fill'},name);
  const [lon,lat]=coastLonLat(-450,0);assert.ok(Math.abs(fill!.longitude-lon)<1e-5&&Math.abs(fill!.latitude-lat)<1e-5,`${name}: the picked place`);
  const line=pick(at([0,-275],OVERLAY_LIFT.line));assert.deepEqual(line&&[line.overlay,line.feature],['tracks',7],name);
  const mark=pick(at([300,200],OVERLAY_LIFT.point));assert.deepEqual(mark&&[mark.overlay,mark.feature,mark.kind],['marks','mark-a','point'],`${name}: the topmost overlay wins over the fill below`);
  assert.equal(pick(at([0,20],0)),null,`${name}: the hole picks nothing`);
  assert.equal(pick(at([2000,2000],0)),null,`${name}: open water picks nothing`);
 }
});

test('CoastViewer drapes after seams, forwards overlays and reports picks instead of a reading',async()=>{
 const {CoastViewer}=await import('../../packages/coast/src/coast3d/viewer.ts');
 const scene=terrain(),picks:unknown[]=[],v:any=Object.create(CoastViewer.prototype);
 Object.assign(v,{alive:true,overlays:new CoastOverlays(palette),terrain:scene,seams:new T.Group(),loaded:new Map(),overview:{},manifest:{waterReferenceM:WATER,sources:[]},
  options:{onOverlayPick:(pick:unknown)=>picks.push(pick)},host:{clientHeight:600},ray:new T.Raycaster(),controls:{target:new T.Vector3()}});
 v.setOverlay('marks',marks);
 const dot=parts(v.overlays,'marks').at(-1)!;assert.equal(positions(dot).getY(0),OVERLAY_LIFT.point,'before terrain the overlay waits at the default height');
 v.drawCoverageSeams();
 const sample=terrainSampler(scene,WATER),[x,z]=[positions(dot).getX(0),positions(dot).getZ(0)];
 assert.ok(Math.abs(positions(dot).getY(0)-(sample(x,z)+OVERLAY_LIFT.point))<1e-3,'drawCoverageSeams re-drapes host overlays');
 const camera=cameras(3000)[1]!;v.camera=camera.camera;v.span=()=>camera.perPixel*600;
 const p=new T.Vector3(x,sample(x,z)+OVERLAY_LIFT.point,z).project(v.camera);v.ray.setFromCamera(new T.Vector2(p.x,p.y),v.camera);
 assert.equal(v.pickOverlay(),true);assert.deepEqual(picks.map((p:any)=>[p.overlay,p.feature]),[['marks','mark-a']]);
 v.options={};assert.equal(v.pickOverlay(),false,'without onOverlayPick the click stays a terrain reading');
 assert.equal(v.removeOverlay('marks'),true);assert.equal(v.removeOverlay('marks'),false);
 v.alive=false;v.setOverlay('marks',marks);assert.equal(v.overlays.group.children.length,0,'a destroyed viewer ignores overlays');
});

test('the embed handle forwards overlays and the pick callback, and is inert after destroy',async()=>{
 const {mountCoast}=await import('../../packages/coast/src/embed.ts');
 const node=():any=>({hidden:false,textContent:'',dataset:{},append(){},remove(){},setAttribute(){},closest:()=>node()});
 const root={append(){},getElementById:()=>node(),querySelector:()=>node(),querySelectorAll:()=>[]},host={shadowRoot:null,attachShadow:()=>root};
 const saved={document:globalThis.document,DOMParser:globalThis.DOMParser};
 Object.assign(globalThis,{document:{createElement:()=>node(),importNode:(n:unknown)=>n},DOMParser:class{parseFromString(){return {getElementById:()=>node()};}}});
 try{
  const calls:unknown[][]=[];let options:any;const onOverlayPick=()=>{};
  const handle=mountCoast(host as never,{overlayPalette:palette,onOverlayPick},(_scene,o)=>{options=o;return {setOverlay:(...a:unknown[])=>calls.push(['set',...a]),removeOverlay:(id:string)=>{calls.push(['remove',id]);return true;},destroy:()=>calls.push(['destroy'])} as never;});
  assert.equal(options.overlayPalette,palette);assert.equal(options.onOverlayPick,onOverlayPick);
  handle.setOverlay('zones',zones);assert.equal(handle.removeOverlay('zones'),true);handle.destroy();
  assert.deepEqual(calls,[['set','zones',zones],['remove','zones'],['destroy']]);
  handle.setOverlay('zones',zones);assert.equal(handle.removeOverlay('zones'),false);assert.equal(calls.length,3);
 }finally{Object.assign(globalThis,saved);}
});

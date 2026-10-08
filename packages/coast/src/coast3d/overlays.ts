// Host overlays draped on the coast terrain (FE-81; design § 3A.2 "Layers").
// v2's layer registry (FE-82: MPAs, reef marks, charter grounds) hands GeoJSON
// features in WGS84 to CoastHandle.setOverlay; CoastViewer owns one
// CoastOverlays. Each overlay is draped on the displayed surface (land where it
// stands above the water reference, the water surface elsewhere). 2D and 3D are
// one scene, so a drape serves both perspectives.
// - Fills are cut on a square grid (DRAPE_M) so every triangle follows the
//   surface; lines are split every DRAPE_M metres. An overlay never builds
//   more than MAX_OVERLAY_TRIANGLES or MAX_OVERLAY_SEGMENTS: the cell or step
//   doubles until it fits, and an overlay that cannot fit is refused.
// - Every vertex sits OVERLAY_LIFT metres above the surface, and the shaders
//   pull overlays OVERLAY_DEPTH_BIAS toward the camera in clip space, so they
//   never share depth with the terrain under either camera.
// - Overlays stack in draw order above the renderer's own layers; a pick
//   reports the overlay and feature ids; removing an overlay (or destroying the
//   viewer) disposes every geometry and material it made.
// Colours are palette roles (src/palette.ts) resolved from the host's overlay
// palette; a style never carries a colour value.
import * as T from 'three';
import {coastLonLat,coastPoint,type Grid} from './grid.ts';
import {COAST_OVERLAY_COLORS,type CoastOverlayColor,type CoastOverlayPalette} from '../palette.ts';
import type {CoastOverlay,CoastOverlayFeature,CoastOverlayKind,CoastOverlayPick} from '../embed-types.ts';
type Position=readonly number[];
type Ring=readonly Position[];

// The public overlay types live in ../embed-types.ts (no renderer imports, FE-71).
export type {CoastOverlay,CoastOverlayFeature,CoastOverlayGeometry,CoastOverlayKind,CoastOverlayPick,CoastOverlayStyle} from '../embed-types.ts';
/** Displayed surface height in scene metres at scene x, z. */
export type SurfaceSampler=(x:number,z:number)=>number;

/** Overlays draw after the water (renderOrder 2) and the native habitat (3). */
export const OVERLAY_RENDER_BASE=10;
/** Metres above the displayed surface, by part. */
export const OVERLAY_LIFT={fill:1,line:2,point:3} as const;
/** Clip-space depth pull toward the camera: about eight steps of a 24-bit depth buffer at any distance. */
export const OVERLAY_DEPTH_BIAS=1e-6;
/** Drape spacing in metres: fill grid cell and the longest line segment. */
export const DRAPE_M=100;
/** Hard caps per overlay on draped fill triangles and on line plus outline segments. */
export const MAX_OVERLAY_TRIANGLES=100000;
export const MAX_OVERLAY_SEGMENTS=50000;
const PICK_PX=6;
const GEOMETRY:Record<CoastOverlayKind,readonly string[]>={fill:['Polygon','MultiPolygon'],line:['LineString','MultiLineString'],point:['Point','MultiPoint']};
const COLOR=/^(?:#[0-9a-f]{3}|#[0-9a-f]{6}|(?:rgb|hsl)a?\([^()]*\))$/i;
// Parts of one overlay stack fill < outline and line < point ring < point.
const STEPS=4;

type XZ=[number,number];
type Part={object:T.Mesh|T.LineSegments|T.Points;xz:Float32Array;feature:Uint32Array;lift:number;step:number};
type Entry={id:string;kind:CoastOverlayKind;ids:(string|number)[];order:number;seq:number;parts:Part[];spacing:{cell:number;step:number}};
/** Per-overlay caps; tests lower them, the viewer uses the defaults. */
export type OverlayLimits={triangles?:number;segments?:number};

function meshHeight(mesh:T.Mesh,grid:Grid,x:number,z:number):number|null{
 const n=grid.size,gx=(x-grid.x)/grid.dx,gz=(z-grid.z)/grid.dz;
 if(!(gx>=0&&gz>=0&&gx<=n-1&&gz<=n-1))return null;
 // The triangle split of regional.ts continuousTriangles, as the viewer's seam blending samples it.
 const col=Math.min(n-2,Math.floor(gx)),row=Math.min(n-2,Math.floor(gz)),fx=gx-col,fz=gz-row,a=row*n+col,b=a+1,c=a+n,d=c+1,p=mesh.geometry.getAttribute('position');
 const y=fx+fz<=1?p.getY(a)*(1-fx-fz)+p.getY(b)*fx+p.getY(c)*fz:p.getY(b)*(1-fz)+p.getY(c)*(1-fx)+p.getY(d)*(fx+fz-1);
 return Number.isFinite(y)?y:null;
}
/** The displayed surface: the finest terrain mesh covering x, z, never below the water reference. */
export function terrainSampler(terrain:T.Object3D,waterReference:number):SurfaceSampler{
 const meshes=(terrain.children as T.Mesh[]).filter(m=>m.isMesh&&m.userData.grid).sort((a,b)=>Math.abs(a.userData.grid.dx)-Math.abs(b.userData.grid.dx));
 return (x,z)=>{for(const mesh of meshes){const y=meshHeight(mesh,mesh.userData.grid,x,z);if(y!==null)return Math.max(y,waterReference);}return waterReference;};
}

function densify(path:readonly XZ[],closed:boolean,step:number):XZ[]{
 const out:XZ[]=[],n=path.length;
 for(let i=0;i<(closed?n:n-1);i++){
  const a=path[i]!,b=path[(i+1)%n]!,steps=Math.max(1,Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])/step));
  for(let s=0;s<steps;s++)out.push([a[0]+(b[0]-a[0])*s/steps,a[1]+(b[1]-a[1])*s/steps]);
 }
 if(!closed&&n)out.push(path[n-1]!);
 return out;
}
// Sutherland–Hodgman against one grid line. The cut is computed from the
// edge's endpoints in a fixed order, so two triangles sharing an edge cut it at
// the same point and the drape has no cracks.
function clip(poly:XZ[],axis:0|1,at:number,below:boolean):XZ[]{
 const out:XZ[]=[],inside=(p:XZ)=>below?p[axis]<=at:p[axis]>=at;
 for(let i=0;i<poly.length;i++){
  const a=poly[i]!,b=poly[(i+1)%poly.length]!;
  if(inside(a))out.push(a);
  if(inside(a)!==inside(b)){const [p,q]=a[0]<b[0]||(a[0]===b[0]&&a[1]<b[1])?[a,b]:[b,a],other=axis?0:1,t=(at-p[axis])/(q[axis]-p[axis]),cut:XZ=[0,0];cut[axis]=at;cut[other]=p[other]+(q[other]-p[other])*t;out.push(cut);}
 }
 return out.filter((p,i)=>{const q=out[(i+1)%out.length]!;return p[0]!==q[0]||p[1]!==q[1];});
}
/**
 * Splits a triangle along the grid of `cell` metres and appends the pieces to
 * `out` as triangles (x, z flat). Returns `out`, or null as soon as `out`
 * holds more than `limit` triangles.
 */
export function drapeTriangles(a:XZ,b:XZ,c:XZ,cell:number,out:number[]=[],limit=Infinity):number[]|null{
 const tri=[a,b,c];
 const span=(poly:XZ[],axis:0|1)=>{const v=poly.map(p=>p[axis]);return [Math.floor(Math.min(...v)/cell),Math.max(...v)] as const;};
 const [i0,xMax]=span(tri,0);
 for(let i=i0;i*cell<xMax;i++){
  const strip=clip(clip(tri,0,i*cell,false),0,(i+1)*cell,true);if(strip.length<3)continue;
  const [j0,zMax]=span(strip,1);
  for(let j=j0;j*cell<zMax;j++){
   const piece=clip(clip(strip,1,j*cell,false),1,(j+1)*cell,true);
   for(let k=1;k+1<piece.length;k++){
    const p=piece[0]!,q=piece[k]!,r=piece[k+1]!;
    if(Math.abs((q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0]))>1e-6&&out.push(p[0],p[1],q[0],q[1],r[0],r[1])>limit*6)return null;
   }
  }
 }
 return out;
}
/** The pieces of a triangulated fill (x, z flat) on the finest cell, from DRAPE_M doubling, that keeps them within `limit`; null when none does. */
export function cutFill(triangles:readonly number[],limit:number):{xz:number[];source:number[];cell:number}|null{
 let area=0,edges=0,minX=Infinity,minZ=Infinity,maxX=-Infinity,maxZ=-Infinity;
 for(let i=0;i<triangles.length;i+=6){
  const x=[triangles[i]!,triangles[i+2]!,triangles[i+4]!],z=[triangles[i+1]!,triangles[i+3]!,triangles[i+5]!];
  area+=Math.abs((x[1]!-x[0]!)*(z[2]!-z[0]!)-(z[1]!-z[0]!)*(x[2]!-x[0]!))/2;edges+=Math.max(...x)-Math.min(...x)+Math.max(...z)-Math.min(...z);
  minX=Math.min(minX,...x);maxX=Math.max(maxX,...x);minZ=Math.min(minZ,...z);maxZ=Math.max(maxZ,...z);
 }
 const count=triangles.length/6,extent=Math.max(maxX-minX,maxZ-minZ,DRAPE_M);
 // Start where a rough estimate (two triangles per cell crossed) fits, then double until the cut fits.
 let cell=DRAPE_M;while(cell<extent&&2*(area/cell**2+edges/cell+count)>limit)cell*=2;
 for(;cell<=2*extent;cell*=2){
  const xz:number[]=[],source:number[]=[];let ok=true;
  for(let i=0;i<triangles.length&&ok;i+=6){
   const before=xz.length;
   ok=drapeTriangles([triangles[i]!,triangles[i+1]!],[triangles[i+2]!,triangles[i+3]!],[triangles[i+4]!,triangles[i+5]!],cell,xz,limit)!==null;
   for(let k=before;k<xz.length;k+=6)source.push(i/6);
  }
  if(ok)return {xz,source,cell};
 }
 return null;
}
/** The line step, from DRAPE_M doubling, that splits these paths into at most `limit` segments; null when even unsplit paths exceed it. */
export function lineStep(paths:readonly {xz:readonly XZ[];closed:boolean}[],limit:number):number|null{
 const lengths:number[]=[];
 for(const {xz,closed} of paths)for(let i=0;i<(closed?xz.length:xz.length-1);i++){const a=xz[i]!,b=xz[(i+1)%xz.length]!;lengths.push(Math.hypot(b[0]-a[0],b[1]-a[1]));}
 if(lengths.length>limit)return null;
 const longest=Math.max(DRAPE_M,...lengths);
 for(let step=DRAPE_M;;step*=2){let n=0;for(const l of lengths)n+=Math.max(1,Math.ceil(l/step));if(n<=limit||step>=longest)return n<=limit?step:null;}
}
function overlayMaterial<M extends T.Material>(material:M,round=false):M{
 material.onBeforeCompile=shader=>{
  shader.vertexShader=shader.vertexShader.replace('#include <project_vertex>',`#include <project_vertex>\ngl_Position.z-=${OVERLAY_DEPTH_BIAS.toFixed(7)}*gl_Position.w;`);
  if(round)shader.fragmentShader=shader.fragmentShader.replace('#include <clipping_planes_fragment>','#include <clipping_planes_fragment>\nif(length(gl_PointCoord-vec2(.5))>.5)discard;');
 };
 material.customProgramCacheKey=()=>round?'coast-overlay-point':'coast-overlay';
 return material;
}

export class CoastOverlays{
 readonly group=new T.Group();
 private entries=new Map<string,Entry>();private seq=0;private sampler:SurfaceSampler=()=>0;private disposed=false;
 private palette:CoastOverlayPalette|undefined;private limits:Required<OverlayLimits>;
 /** Without a palette every `set` throws: overlays draw only in colours the host read from its tokens. */
 constructor(palette?:CoastOverlayPalette,limits:OverlayLimits={}){this.palette=palette;this.limits={triangles:limits.triangles??MAX_OVERLAY_TRIANGLES,segments:limits.segments??MAX_OVERLAY_SEGMENTS};this.group.name='coast-overlays';}
 /** The fill cell and line step an overlay was draped with, in metres; null when the id is unknown. */
 spacing(id:string):{cell:number;step:number}|null{const entry=this.entries.get(id);return entry?{...entry.spacing}:null;}

 /** Adds the overlay, or replaces one with the same id in its stacking place. Invalid input throws and changes nothing. */
 set(id:string,overlay:CoastOverlay):void{
  if(this.disposed)return;
  if(typeof id!=='string'||!id)throw new TypeError('setOverlay: the overlay id must be a non-empty string');
  const entry=this.build(id,overlay),old=this.entries.get(id);
  entry.seq=old?old.seq:this.seq++;if(old)this.release(old);
  this.entries.set(id,entry);
  for(const part of entry.parts)this.group.add(part.object);
  this.drapeEntry(entry);this.restack();
 }
 /** Removes the overlay and frees its geometry and materials; false when the id is unknown. */
 remove(id:string):boolean{const entry=this.entries.get(id);if(!entry)return false;this.release(entry);this.entries.delete(id);return true;}
 /** Re-drapes every overlay, after the terrain loads, its relief changes or a level of detail streams in. */
 drape(sampler:SurfaceSampler):void{this.sampler=sampler;for(const entry of this.entries.values())this.drapeEntry(entry);}
 /** The topmost overlay feature under `ray`; `worldPerPixel` converts the pick tolerance to scene metres. */
 pick(ray:T.Ray,worldPerPixel:number):CoastOverlayPick|null{
  const caster=new T.Raycaster();caster.ray.copy(ray);caster.params.Line.threshold=PICK_PX*worldPerPixel;
  let best:{rank:number;distance:number;pick:CoastOverlayPick}|null=null;
  for(const entry of this.entries.values())for(const part of entry.parts){
   const object=part.object;if(object instanceof T.Points)caster.params.Points.threshold=((object.material as T.PointsMaterial).size+PICK_PX)/2*worldPerPixel;
   for(const hit of caster.intersectObject(object,false)){
    const rank=object.renderOrder;if(best&&(rank<best.rank||(rank===best.rank&&hit.distance>=best.distance)))continue;
    const vertex=object instanceof T.Mesh?(hit.faceIndex??0)*3:hit.index??0,feature=entry.ids[part.feature[vertex]!]!;
    const [longitude,latitude]=object instanceof T.Points?coastLonLat(part.xz[vertex*2]!,part.xz[vertex*2+1]!):coastLonLat(hit.point.x,hit.point.z);
    best={rank,distance:hit.distance,pick:{overlay:entry.id,feature,kind:entry.kind,latitude,longitude}};
   }
  }
  return best?.pick??null;
 }
 /** Frees every overlay; later calls do nothing. */
 dispose():void{for(const entry of this.entries.values())this.release(entry);this.entries.clear();this.disposed=true;this.group.removeFromParent();}

 private release(entry:Entry){for(const {object} of entry.parts){this.group.remove(object);object.geometry.dispose();(object.material as T.Material).dispose();}}
 private drapeEntry(entry:Entry){
  for(const part of entry.parts){
   const p=part.object.geometry.getAttribute('position') as T.BufferAttribute;
   for(let i=0;i<p.count;i++){const x=part.xz[2*i]!,z=part.xz[2*i+1]!;p.setXYZ(i,x,this.sampler(x,z)+part.lift,z);}
   p.needsUpdate=true;part.object.geometry.computeBoundingSphere();
  }
 }
 private restack(){
  [...this.entries.values()].sort((a,b)=>a.order-b.order||a.seq-b.seq).forEach((entry,rank)=>{for(const part of entry.parts)part.object.renderOrder=OVERLAY_RENDER_BASE+rank*STEPS+part.step;});
 }
 private build(id:string,overlay:CoastOverlay):Entry{
  const fail=(why:string):never=>{throw new TypeError(`setOverlay("${id}"): ${why}`);};
  const {kind,features,style}=overlay??{} as CoastOverlay;
  if(!Object.hasOwn(GEOMETRY,kind))fail(`unknown kind ${String(kind)}`);
  if(!Array.isArray(features))fail('features must be an array');
  if(!style||typeof style!=='object')fail('a style is required');
  const order=overlay.order??0;if(!Number.isFinite(order))fail('order must be a finite number');
  const unit=(value:number|undefined,fallback:number,name:string)=>{if(value===undefined)return fallback;if(!(Number.isFinite(value)&&value>=0&&value<=1))fail(`${name} must be between 0 and 1`);return value;};
  const color=(role:CoastOverlayColor)=>{
   if(!(COAST_OVERLAY_COLORS as readonly string[]).includes(role))fail(`unknown colour role ${String(role)}`);
   if(!this.palette)fail('mount the coast with an overlayPalette to draw overlays');
   const value=this.palette![role];if(typeof value!=='string'||!COLOR.test(value.trim()))fail(`the overlay palette's ${role} must be a hex, RGB or HSL colour`);
   return new T.Color(value.trim());
  };
  const size=style.size??8;if(!(Number.isFinite(size)&&size>0&&size<=64))fail('size must be between 0 and 64 px');
  const opacity=unit(style.opacity,kind==='fill'?.25:1,'opacity'),outlineOpacity=unit(style.outlineOpacity,1,'outlineOpacity');
  const main=color(style.color),outline=style.outline===undefined?null:color(style.outline);
  const point=(c:Position):XZ=>{const lon=c[0]!,lat=c[1]!;if(c.length<2||!Number.isFinite(lon)||!Number.isFinite(lat)||Math.abs(lon)>180||Math.abs(lat)>85)fail('coordinates must be finite WGS84 longitude, latitude');return coastPoint(lon,lat);};
  const path=(coordinates:readonly Position[],closed:boolean)=>{
   const xz=coordinates.map(point);
   if(closed&&xz.length>1&&xz[0]![0]===xz.at(-1)![0]&&xz[0]![1]===xz.at(-1)![1])xz.pop();
   if(xz.length<(closed?3:2))fail(closed?'a polygon ring needs three distinct positions':'a line needs two positions');
   return xz;
  };
  const triangles:number[]=[],triangleFeature:number[]=[],paths:{xz:XZ[];closed:boolean;fi:number}[]=[],points:number[]=[],pointFeature:number[]=[],ids:(string|number)[]=[];
  features.forEach((f,fi)=>{
   if(!f||typeof f!=='object'||!((typeof f.id==='string'&&f.id)||(typeof f.id==='number'&&Number.isFinite(f.id))))fail(`feature ${fi} needs a string or number id`);
   ids.push(f.id);
   const g=f.geometry;if(!g||!GEOMETRY[kind].includes(g.type))fail(`a ${kind} overlay takes ${GEOMETRY[kind].join(' or ')} features (feature ${String(f.id)})`);
   if(g.type==='Polygon'||g.type==='MultiPolygon'){
    const polygons:readonly (readonly Ring[])[]=g.type==='Polygon'?[g.coordinates]:g.coordinates;
    for(const polygon of polygons){
     if(!polygon.length)fail('a polygon needs an outer ring');
     const rings=polygon.map(r=>path(r,true)),all=rings.flat();
     for(const face of T.ShapeUtils.triangulateShape(rings[0]!.map(([x,z])=>new T.Vector2(x,z)),rings.slice(1).map(r=>r.map(([x,z])=>new T.Vector2(x,z))))){for(const i of face)triangles.push(all[i]![0],all[i]![1]);triangleFeature.push(fi);}
     if(outline)for(const ring of rings)paths.push({xz:ring,closed:true,fi});
    }
   }else if(g.type==='LineString'||g.type==='MultiLineString'){
    for(const line of g.type==='LineString'?[g.coordinates]:g.coordinates)paths.push({xz:path(line,false),closed:false,fi});
   }else for(const c of g.type==='Point'?[g.coordinates]:g.coordinates){const [x,z]=point(c);points.push(x,z);pointFeature.push(fi);}
  });
  // One drape cell and one line step per overlay, coarsened only to stay under the caps.
  const {triangles:maxTriangles,segments:maxSegments}=this.limits;
  const cut=triangles.length?cutFill(triangles,maxTriangles):{xz:[],source:[],cell:DRAPE_M};
  if(!cut)fail(`too detailed to drape: more than ${maxTriangles} fill triangles at any cell size; simplify the features or split the overlay`);
  const step=paths.length?lineStep(paths,maxSegments):DRAPE_M;
  if(step===null)fail(`too detailed to drape: more than ${maxSegments} line segments; simplify the features or split the overlay`);
  const fill=cut!.xz,fillFeature:number[]=[];for(const t of cut!.source){const fi=triangleFeature[t]!;fillFeature.push(fi,fi,fi);}
  const lines:number[]=[],lineFeature:number[]=[];
  for(const {xz,closed,fi} of paths){const line=densify(xz,closed,step!);for(let i=0;i<(closed?line.length:line.length-1);i++){const a=line[i]!,b=line[(i+1)%line.length]!;lines.push(a[0],a[1],b[0],b[1]);lineFeature.push(fi,fi);}}
  const parts:Part[]=[],common={transparent:true,depthWrite:false,toneMapped:false};
  const add=(object:T.Mesh|T.LineSegments|T.Points,xz:number[],feature:number[],lift:number,step:number)=>{
   if(!xz.length){object.geometry.dispose();(object.material as T.Material).dispose();return;}
   object.geometry.setAttribute('position',new T.BufferAttribute(new Float32Array(xz.length/2*3),3));object.name=`overlay:${id}`;
   parts.push({object,xz:Float32Array.from(xz),feature:Uint32Array.from(feature),lift,step});
  };
  if(kind==='fill'){
   add(new T.Mesh(new T.BufferGeometry(),overlayMaterial(new T.MeshBasicMaterial({...common,color:main,opacity,side:T.DoubleSide}))),fill,fillFeature,OVERLAY_LIFT.fill,0);
   if(outline)add(new T.LineSegments(new T.BufferGeometry(),overlayMaterial(new T.LineBasicMaterial({...common,color:outline,opacity:outlineOpacity}))),lines,lineFeature,OVERLAY_LIFT.line,1);
  }else if(kind==='line')add(new T.LineSegments(new T.BufferGeometry(),overlayMaterial(new T.LineBasicMaterial({...common,color:main,opacity}))),lines,lineFeature,OVERLAY_LIFT.line,1);
  else{
   if(outline)add(new T.Points(new T.BufferGeometry(),overlayMaterial(new T.PointsMaterial({...common,color:outline,opacity:outlineOpacity,size:size+3,sizeAttenuation:false}),true)),[...points],[...pointFeature],OVERLAY_LIFT.point,2);
   add(new T.Points(new T.BufferGeometry(),overlayMaterial(new T.PointsMaterial({...common,color:main,opacity,size,sizeAttenuation:false}),true)),points,pointFeature,OVERLAY_LIFT.point,3);
  }
  return {id,kind,ids,order,seq:0,parts,spacing:{cell:cut!.cell,step:step!}};
 }
}

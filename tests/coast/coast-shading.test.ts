// Auto exposure, adaptive contours and sun direction (packages/coast/src/coast3d/shading.ts).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {coastLook,KIT_RAMP_CAPACITY,depthWindow,contourInterval,sunDirection,shadingReadout,reliefChip,sourceContourFloor,MIN_WINDOW_M,SOURCE_CONTOUR_FLOOR_M} from '../../packages/coast/src/coast3d/shading.ts';
import * as T from 'three';
import {CoastViewer} from '../../packages/coast/src/coast3d/viewer.ts';
import {resolveRelief} from '../../web/map/relief-data.ts';
import {coastPoint} from '../../packages/coast/src/coast3d/grid.ts';

const near=(a:number,b:number,eps=1e-9)=>assert.ok(Math.abs(a-b)<=eps,`${a} ≉ ${b}`);
test('depth window spans the 2nd to 98th percentile of submerged depths only',()=>{
 const heights=Array.from({length:101},(_,i)=>0.8-i);// depths 0..100 m below a +0.8 m water reference
 const w=depthWindow([...heights,50,120,NaN,Infinity],0.8)!;
 assert.ok(w.min>=1&&w.min<=3,`min ${w.min}`);assert.ok(w.max>=97&&w.max<=99,`max ${w.max}`);
});
test('outliers and missing samples do not stretch the window',()=>{
 const heights=new Float32Array(200).fill(-20);heights[0]=-3000;heights[1]=NaN;heights[2]=-21;
 const w=depthWindow(heights,0)!;assert.ok(w.max<30,`max ${w.max}`);
});
test('a flat view keeps a minimum window width instead of exploding contrast',()=>{
 const w=depthWindow(new Float32Array(64).fill(-10),0)!;
 near(w.max-w.min,MIN_WINDOW_M);near((w.min+w.max)/2,10);
 const shallow=depthWindow(new Float32Array(64).fill(-.5),0)!;assert.equal(shallow.min,0);near(shallow.max,MIN_WINDOW_M);
});
test('too few submerged samples leave the ramp unchanged',()=>{
 assert.equal(depthWindow([5,6,7,-1],0),null);
 assert.equal(depthWindow(new Float32Array(100).fill(10),0.8),null,'land only');
});
test('contour spacing draws about eight to twenty minor lines and indexes every fifth',()=>{
 for(const window of [6,10,25,40,80,150,300,600,1200]){
  const {minor,index}=contourInterval(window,0);
  const lines=window/minor;near(index,minor*5);
  assert.ok(lines<=20||minor===500*.3048,`${window} m: ${lines} lines at ${minor} m`);
  assert.ok(lines>=8||minor===10*.3048,`${window} m: ${lines} lines at ${minor} m`);
 }
 near(contourInterval(25,0).minor,10*.3048);// 25 m / 3.048 = 8.2 lines; 5 ft is never offered since lidar's floor is 10 ft
 near(contourInterval(80,0).minor,20*.3048);
});
test('contour spacing never goes finer than the finest grid spacing allows',()=>{
 near(contourInterval(10,2).minor,10*.3048);// 2 m display mesh: 3 m floor, 10 ft
 near(contourInterval(4,0).minor,10*.3048);// a very narrow window still gets the finest step offered, 10 ft
 near(contourInterval(10,30).minor,250*.3048);// 30 m model grid: 45 m floor
 near(contourInterval(10,1000).minor,Math.ceil(1500/.3048)*.3048,1e-9);// coarser than every step: floor rounded up to a whole foot
 near(contourInterval(NaN,NaN).minor,10*.3048);
});
test('sun direction is a unit vector in the coastPoint frame (x east, y up, z south)',()=>{
 const [nx,nz]=coastPoint(-120.98,35.6);assert.ok(nz<0&&Math.abs(nx)<1e-6,'north is -z');
 const north=sunDirection(0,0);near(north[0],0);near(north[1],0);near(north[2],-1);
 const east=sunDirection(90,0);near(east[0],1);near(east[2],0,1e-12);
 const up=sunDirection(123,90);near(up[1],1);
 for(const [az,alt] of [[305,54],[200,20],[45,70]]){const v=sunDirection(az,alt);near(Math.hypot(...v),1,1e-12);}
 const nw=sunDirection(315,45);assert.ok(nw[0]<0&&nw[2]<0&&nw[1]>0,'north-west sun is west, north and up');
});
test('each source keeps the contour floor the fixed intervals drew, and the shader carries the same literals',()=>{
 assert.deepEqual(SOURCE_CONTOUR_FLOOR_M,{lidar:3.048,survey:9.144,estimate:9.144,model:152.4});
 assert.equal(sourceContourFloor(7),3.048,'lidar 10 ft');assert.equal(sourceContourFloor(5),9.144,'survey 30 ft');assert.equal(sourceContourFloor(2),9.144,'chart estimate 30 ft');assert.equal(sourceContourFloor(1),152.4,'regional model 500 ft');
 const shader=readFileSync(new URL('../../packages/coast/src/coast3d/viewer.ts',import.meta.url),'utf8');
 assert.ok(shader.includes('float sourceFloor=coastSource>6.5?3.048:coastSource<1.5?152.4:9.144;float minorStep=max(contourMinor,sourceFloor)'),'the fragment shader floors the adaptive minor step per source');
});
test('readout names the ramp in view and the contour spacing; the chip discloses exaggeration',()=>{
 assert.equal(shadingReadout({min:18.6,max:43.3},false,{minor:3.048,index:15.24}),'Ramp 61–142 ft in view · contours 10 ft where the source allows, index 50 ft');
 assert.equal(shadingReadout(null,true,{minor:3.048,index:15.24}),'Fixed ramp 0–5,900 ft · contours 10 ft where the source allows, index 50 ft');
 assert.equal(shadingReadout({min:18.6,max:43.3},false,null),'Ramp 61–142 ft in view · contours off');
 assert.equal(reliefChip(5),'Seabed ×5 · land true scale');
 assert.equal(reliefChip(1),'Seabed true scale · land true scale');
});


// Use the actual viewer's shader uniforms: a missing or rescaled stop, stale
// contour ink or wrong default would not be caught by the pointer reader alone.
test('regional look binds the kit stops, ink, no-data and fixed default to the viewer',()=>{
 const read=(name:string)=>JSON.parse(readFileSync(new URL(`../fixtures/relief/pointer-style/${name}.json`,import.meta.url),'utf8'));
 const key=(name:string)=>{
  const p=read(name),r=resolveRelief(p.region,p);assert.equal(r.status,'ready');return r.archive.look;
 };
 const look=coastLook(key('v1'))!;
 const table=read('looks').coast;
 const other=coastLook(key('v1-no-contours'),table)!;
 const rolling=coastLook(key('v1_1-prev-v1'),table)!;
 assert.notEqual(other.depthStopsFt[0]?.[1],rolling.depthStopsFt[0]?.[1]);
 assert.equal(coastLook(key('v1'),table),other,'rollback reads the v1 file again; the other view remains v1');
 const input={checked:false,onchange(){viewer.fixedRamp.value=Number(this.checked);viewer.updateShading();}};
 let shading:any;
 const viewer=Object.assign(Object.create(CoastViewer.prototype),{
  alive:true,options:{onShading:(s:unknown)=>{shading=s;}},
  root:{querySelector:(s:string)=>s==='[id="fixed-ramp"]'?input:null},
  kitCount:{value:0},kitStops:{value:Array.from({length:KIT_RAMP_CAPACITY},()=>new T.Vector4())},contourInk:{value:new T.Color()},
  fixedRamp:{value:0},contours:{value:0},contourMinor:{value:0},contourIndex:{value:0},relief:{value:2},
  manifest:{waterReferenceM:0,bounds:[0,0,4096,4096]},controls:{target:{x:0,z:0}},loaded:new Map(),span:()=>1000,rampWindow:{min:18.6,max:43.3},
 });
 assert.equal(viewer.setReliefLook(key('v1')),'known');
 assert.equal(shading.fixedRamp,true);
 assert.equal(shading.readout,'Fixed ramp 0–900 ft · contours off');
 assert.equal(shading.noData,look.noData);
 const shader={uniforms:{},vertexShader:'',fragmentShader:''};
 viewer.material(null,0,false).onBeforeCompile(shader);
 const u=shader.uniforms as Record<string,{value:any}>;
 for(const ft of [0,100,300]){
  const stop=u.kitStops!.value.find((v:T.Vector4)=>Math.abs(v.w-ft*.3048)<1e-6);
  const hex=stop.toArray().slice(0,3).map((c:number)=>Math.round(c*255).toString(16).padStart(2,'0')).join('');
  assert.equal(hex,look.depthStopsFt.find(s=>s[0]===ft)?.[1].slice(1).toLowerCase());
 }
 assert.equal(u.contourColor!.value.getHexString(),look.contour.slice(1).toLowerCase());
 viewer.setFixedRamp(false);assert.match(shading.readout,/Ramp 61–142 ft in view/);
 assert.equal(viewer.setReliefLook(key('v1_1-prev-v1')),'unknown');
 viewer.setFixedRamp(true);assert.equal(shading.fixedRamp,false);assert.equal(shading.unmatched,true);assert.equal(u.kitCount!.value,0);
 assert.equal(viewer.setReliefLook(null),'unknown');
 assert.equal(viewer.setReliefLook(key('legacy')),'legacy');
 viewer.setFixedRamp(true);assert.match(shading.readout,/0–5,900 ft/);assert.equal(shading.unmatched,undefined);
});

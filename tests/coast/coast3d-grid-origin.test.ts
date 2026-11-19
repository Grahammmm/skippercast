import {test} from 'node:test';
import assert from 'node:assert/strict';
import {coastPoint,coastLonLat,projectionFor,ORIGIN} from '../../packages/coast/src/coast3d/grid.ts';
// CI-ARTICLE-1: each test names the contract it protects and the bug that makes it fail.
const R=6378137,rad=Math.PI/180;
const ORIGINS:Array<[string,number,number]>=[['Oregon border',42.0,-124.2],['San Diego',32.7,-117.2],['island',33.4,-118.4]];

// Contract: the legacy exports keep their exact numbers (viewer.ts and saved scenes depend on them).
// Bug caught: a refactor that reorders the floating-point operations or rebinds the default origin.
test('legacy coastPoint/coastLonLat are bit-identical to the frozen pre-seam formulas at the default origin',()=>{
 const s=Math.cos(ORIGIN[1]*Math.PI/180),bx=R*ORIGIN[0]*Math.PI/180,by=R*Math.asinh(Math.tan(ORIGIN[1]*Math.PI/180));
 for(const [lon,lat] of [[-121.09,35.49],[-120.85,35.374],[-120.98,35.43],[-122.5,37.8]]){
  const [x,z]=coastPoint(lon,lat);
  assert.deepEqual([x,z],[(R*lon*Math.PI/180-bx)*s,-(R*Math.asinh(Math.tan(lat*Math.PI/180))-by)*s]);
  assert.deepEqual(coastLonLat(x,z),[(x/s+bx)/R*180/Math.PI,Math.atan(Math.sinh((-z/s+by)/R))*180/Math.PI]);
 }
 assert.deepEqual(coastPoint(ORIGIN[0],ORIGIN[1]),[0,-0]);
 assert.deepEqual(projectionFor({lat:ORIGIN[1],lon:ORIGIN[0]}).forward(-121.09,35.49),coastPoint(-121.09,35.49));
});

// Contract: a projection bound to any valid origin puts that origin at scene (0,0) and inverts exactly.
// Bug caught: a factory still closed over the Central Coast origin (non-central regions land hundreds of km off).
test('non-central origins map to scene zero and round-trip within 1 cm at 50 km in every direction',()=>{
 for(const [name,lat0,lon0] of ORIGINS){
  const p=projectionFor({lat:lat0,lon:lon0}),[ox,oz]=p.forward(lon0,lat0);
  assert.ok(Math.abs(ox)<1e-6&&Math.abs(oz)<1e-6,`${name} origin is scene zero`);
  for(const [ex,nz] of [[50000,0],[-50000,0],[0,50000],[0,-50000],[35000,-35000],[-35000,35000]]){
   // scene point -> lon/lat -> scene point (metres), and lon/lat -> scene -> lon/lat (degrees; 1e-8 deg is ~1 mm)
   const [lon,lat]=p.inverse(ex,nz),[x,z]=p.forward(lon,lat);
   assert.ok(Math.hypot(x-ex,z-nz)<0.01,`${name} scene round trip at (${ex},${nz}) off by ${Math.hypot(x-ex,z-nz)} m`);
   const [lon2,lat2]=p.inverse(...p.forward(lon,lat));
   assert.ok(Math.abs(lon2-lon)<1e-8&&Math.abs(lat2-lat)<1e-8,`${name} degree round trip`);
  }
 }
});

// Contract: scene units are local metres, so the scale is cos(origin latitude) and is origin-specific.
// Bug caught: scale taken from the default latitude (35.43) or left as 1 (Mercator stretch at 42 N is ~35%).
test('metre scale is cos(origin lat) and 1 km east/north of each origin is ~1000 scene units',()=>{
 const scales=new Set<number>();
 for(const [name,lat0,lon0] of ORIGINS){
  const p=projectionFor({lat:lat0,lon:lon0});
  assert.equal(p.scale,Math.cos(lat0*rad));scales.add(p.scale);
  const [ex]=p.forward(lon0+1000/(R*Math.cos(lat0*rad))/rad,lat0),[,nz]=p.forward(lon0,lat0+1000/R/rad);
  assert.ok(Math.abs(ex-1000)<0.01,`${name} east 1 km -> ${ex}`);
  assert.ok(Math.abs(-nz-1000)<0.5,`${name} north 1 km -> ${-nz}`);// z grows southward; Mercator second-order term < 0.5 m per km
 }
 assert.equal(scales.size,ORIGINS.length);
});

// Contract: a bad origin fails loudly instead of yielding NaN scene coordinates.
// Bug caught: validation written as `!(|lat|<=85)` omitted or as `lat>85` only, which lets NaN/Infinity/strings through.
test('an invalid origin is rejected',()=>{
 const bad:unknown[]=[{lat:NaN,lon:-120},{lat:35,lon:NaN},{lat:Infinity,lon:-120},{lat:35,lon:-Infinity},{lat:85.01,lon:-120},{lat:-85.01,lon:-120},{lat:35,lon:180.01},{lat:35,lon:-180.01},{lat:'35',lon:-120},{lat:35},{},null,undefined];
 for(const o of bad)assert.throws(()=>projectionFor(o as {lat:number;lon:number}),RangeError,JSON.stringify(o));
 assert.doesNotThrow(()=>projectionFor({lat:85,lon:180}));
 assert.doesNotThrow(()=>projectionFor({lat:-85,lon:-180}));
});

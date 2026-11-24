import test from 'node:test';
import assert from 'node:assert/strict';
import {surfaceField,vectorReading,fieldContours,fieldColor,temperatureColors} from '../../packages/coast/src/map/surface-field.ts';
const points=[{lon:0,lat:0,values:[0,1]},{lon:1,lat:0,values:[2,1]},{lon:1,lat:1,values:[2,3]},{lon:0,lat:1,values:[0,3]}];
test('bilinear components preserve uniform and linear fields without angle-wrap artifacts',()=>{
 const f=surfaceField(points)!;assert.deepEqual(f.sample(.5,.25),[1,1.5]);assert.deepEqual(f.sample(1,1),[2,3]);assert.equal(f.sample(1.001,.5),null);
 const vector=vectorReading([0,1]);assert.equal(vector.towardDeg,0);assert.ok(Math.abs(vector.speedKnots-1.943844492)<1e-8);
 const opposed=points.map((p,i)=>({...p,values:[i===0||i===3?-1:1,1]}));assert.equal(vectorReading(surfaceField(opposed)!.sample(.5,.5)!).towardDeg,0);
});
test('missing coastal cells and entire missing columns remain blank',()=>{
 assert.equal(surfaceField(points.slice(1)),null);
 const wide=[...points,...points.map(p=>({...p,lon:p.lon+3}))];const f=surfaceField(wide,{step:[1,1]})!;
 assert.equal(f.quads.length,2);assert.equal(f.sample(2,.5),null);assert.equal(f.sample(1.5,.5),null);
 assert.equal(surfaceField(points,{maxStep:[.5,.5]}),null);
});
test('complete quads support their shared edges and corners without filling neighboring gaps',()=>{
 const far={lon:2,lat:0,values:[10,9]};
 const f=surfaceField([...points,far])!;
 assert.deepEqual(f.quads,[{west:0,east:1,south:0,north:1,corners:points}]);
 assert.deepEqual(f.sample(.5,.25),[1,1.5]);
 assert.equal(f.sample(1.25,.5),null,'a represented far column with a missing corner does not support its interior');
 assert.equal(f.sample(1+1e-6,.5),null,'a point off the seam is not snapped back onto it');
 assert.equal(f.sample(1,1.001),null,'seam fallback does not extend the domain');

 const full=surfaceField([...points,far,{lon:2,lat:1,values:[14,11]}])!;
 assert.equal(full.quads.length,2);
 assert.deepEqual(full.sample(1,.5),[2,2]);
 assert.deepEqual(full.sample(1.5,.5),[7,6]);
 const roundoff=2**-30;
 assert.deepEqual(full.sample(1+roundoff,.5),[2+10*roundoff,2+8*roundoff],'a complete ordinary owner keeps its original weights');

 // Flooring to the east quad used to hide the painted west quad's edge.
 assert.deepEqual(f.sample(1,.5),[2,2]);
 assert.deepEqual(f.sample(1+roundoff,.5),[2,2]);
 assert.deepEqual(f.sample(1,0),[2,1]);
 assert.deepEqual(f.sample(1,1),[2,3]);

 const diagonal=surfaceField([...points,far,{lon:0,lat:2,values:[20,20]},{lon:2,lat:2,values:[30,30]}])!;
 assert.deepEqual(diagonal.quads,f.quads);
 assert.deepEqual(diagonal.sample(.5,1),[1,3]);
 assert.deepEqual(diagonal.sample(1,1),[2,3],'at an internal corner the only complete quad can be diagonal to the owner');
 assert.equal(diagonal.sample(1,1.25),null,'a line between two incomplete quads remains blank');
});
test('rejects duplicate, nonfinite and irregular source grids',()=>{
 assert.equal(surfaceField([...points,points[0]]),null);
 assert.equal(surfaceField(points.map((p,i)=>i===0?{...p,values:[NaN,1]}:p)),null);
 assert.equal(surfaceField(points.map((p,i)=>i===0?{...p,lon:.25}:p),{step:[1,1]}),null);
});
test('contours never cross a missing quad and show linear gradients at their true value',()=>{
 const f=surfaceField([...points,...points.map(p=>({...p,lon:p.lon+3}))],{step:[1,1]})!;
 const lines=fieldContours(f,[1]);assert.ok(lines.features.length);
 for(const feature of lines.features)for(const [x]of feature.geometry.coordinates)assert.ok(Math.abs(x-.5)<1e-8||Math.abs(x-3.5)<1e-8);
 assert.deepEqual(fieldColor(-20,0,1,temperatureColors),[36,79,157]);assert.deepEqual(fieldColor(20,0,1,temperatureColors),[241,138,101]);
});

test('reviewed historical MUR and all current products retain complete-cell display support',async()=>{
 const {readFile}=await import('node:fs/promises');
 // A dated launch refresh may correctly withdraw expired fields. Renderer checks
 // use fixed real source grids, independently of live provider availability.
 const reference=JSON.parse(await readFile(new URL('./fixtures/surface-reference.json',import.meta.url),'utf8'));
 const sst=reference.surfaceTemperature;
 const temperature=surfaceField(sst.points.map((p:any)=>({lon:p.lon,lat:p.lat,values:[p.tempF,p.errorF]})),{step:[sst.sampleSpacingDeg,sst.sampleSpacingDeg]})!;
 assert.ok(temperature?.quads.length);const q=temperature.quads[0],v=temperature.sample((q.west+q.east)/2,(q.south+q.north)/2)!;
 assert.ok(Math.abs(v[0]-q.corners.reduce((n,p)=>n+p.values[0],0)/4)<1e-6);
 assert.deepEqual(reference.currents.map((field:any)=>field.id),['wcofs','hfr-1','hfr-6']);
 for(const field of reference.currents){const cells=field.frames[0].cells,lat=cells.reduce((n:number,p:any)=>n+p.lat,0)/cells.length,km=field.nativeResolutionKm*field.sampleStride;
  const grid=surfaceField(cells.map((p:any)=>({lon:p.lon,lat:p.lat,values:[p.uMs,p.vMs]})),{maxStep:[km/111/Math.cos(lat*Math.PI/180)*1.6,km/111*1.6]});assert.ok(grid?.quads.length,field.id);
 }
});

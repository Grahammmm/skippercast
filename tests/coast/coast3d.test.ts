import {test} from 'node:test';
import assert from 'node:assert/strict';
import {gridTriangles,nearestDepth,coastPoint,coastLonLat,type Grid} from '../../packages/coast/src/coast3d/grid.ts';
const grid=(values:number[],sources?:number[]):Grid=>({x:100,z:200,size:2,dx:8,dz:8,values:new Float32Array(values),sources:sources?new Uint8Array(sources):undefined});
test('3D mesh leaves missing survey vertices unconnected',()=>{
 assert.deepEqual([...gridTriangles(grid([10,20,30,NaN]))],[0,2,1]);
 assert.equal(gridTriangles(grid([10,NaN,30,NaN])).length,0);
});
test('3D mesh never bridges different survey identities',()=>{
 assert.equal(gridTriangles(grid([10,20,30,40],[1,1,2,2])).length,0);
 assert.deepEqual([...gridTriangles(grid([10,20,30,40],[1,1,1,2]))],[0,2,1]);
 assert.equal(gridTriangles(grid([10,20,30,40],[0,0,0,0])).length,0);
});
test('depth inspection returns a nearest display sample, never an invented gap depth',()=>{
 const g=grid([10,20,30,NaN]);assert.equal(nearestDepth(g,108,208),null);assert.equal(nearestDepth(g,100,200),10);assert.equal(nearestDepth(g,109,208),null);
});
test('local metre projection round trips marine coordinates',()=>{
 for(const [lon,lat] of [[-121.09,35.49],[-120.85,35.374]]){const [x,z]=coastPoint(lon,lat),[l,p]=coastLonLat(x,z);assert.ok(Math.abs(l-lon)<1e-9&&Math.abs(p-lat)<1e-9);}
});

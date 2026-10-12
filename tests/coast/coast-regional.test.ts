import test from 'node:test';
import assert from 'node:assert/strict';
import {decodeTerrain,displayElevations,roundEven,continuousTriangles,chooseTiles,reefBindingMatches,rankedHabitat,boundedBytes} from '../../packages/coast/src/coast3d/regional.ts';
import {nearestDepth} from '../../packages/coast/src/coast3d/grid.ts';
test('regional display keeps source values and fills triangles across source boundaries',()=>{const bytes=new ArrayBuffer(20);new Float32Array(bytes,0,4).set([-2,1,-8,-10]);new Uint8Array(bytes,16).set([7,2,1,4]);const g=decodeTerrain(bytes,2,0,0,4);assert.equal(nearestDepth(g,0,0),-2);assert.deepEqual([...g.sources!],[7,2,1,4]);assert.equal(continuousTriangles(2).length,6);assert.throws(()=>decodeTerrain(bytes,3,0,0,4));});
test('regional terrain rejects missing samples and unknown sources',()=>{const data=new ArrayBuffer(20);new Float32Array(data,0,4).set([0,1,NaN,2]);new Uint8Array(data,16).fill(1);assert.throws(()=>decodeTerrain(data,2,0,0,1));new Float32Array(data,0,4)[2]=2;new Uint8Array(data,16)[0]=8;assert.throws(()=>decodeTerrain(data,2,0,0,1));});
test('stream selection is bounded and gives nearest tiles first',()=>{const tiles=Array.from({length:200},(_,i)=>({x:i*1024,z:0,width:1024,lods:[]}));const picked=chooseTiles(tiles,0,0,100000,10);assert.equal(picked.length,10);assert.equal(picked[0].x,0);assert.equal(new Set(picked).size,10);});
test('derived outlines require all original source bindings and unexpired screening',()=>{const r={regionId:'morro',archiveSha256:'a',exportSha256:'b'},now=1000,c={regions:[r],expiresAt:new Date(2000).toISOString()},m={regions:[r]};assert.equal(reefBindingMatches(c,m,now),true);assert.equal(reefBindingMatches(c,{regions:[{...r,exportSha256:'changed'}]},now),false);assert.equal(reefBindingMatches(c,{regions:[r,{...r,regionId:'cambria'}]},now),false);assert.equal(reefBindingMatches(c,m,2001),false);});
test('rankings use original species fit then terrain score and reject stale or unscreened evidence',()=>{const f=(id:string,fit:number,score:number,extra={})=>({id,geometry:{type:'Polygon'},properties:{exportable:true,screen_status:'pass',screen_expires_at:new Date(3000).toISOString(),fit_lingcod:fit,terrain_score:score,...extra}});const ranked=rankedHabitat([f('low',2,99),f('high',3,60),f('best',3,80),f('weak',1,100),f('stale',3,100,{screen_expires_at:new Date(500).toISOString()}),f('held',3,100,{exportable:false})],'fit_lingcod',1000);assert.deepEqual(ranked.map(f=>f.id),['best','high','low']);});
test('byte readers cancel oversized compressed or decoded bodies',async()=>{const stream=new ReadableStream<Uint8Array>({start(c){c.enqueue(new Uint8Array(10));c.close();}});await assert.rejects(boundedBytes(stream,9));});

test('source seam blending never alters inspection values or erases large elevation differences',()=>{const values=new Float32Array([0,0,0,0,2,4,0,2,0]),sources=new Uint8Array([1,1,1,1,7,3,1,7,1]),grid={x:0,z:0,size:3,dx:1,dz:1,values,sources};const before=[...values],display=displayElevations(grid);assert.deepEqual([...values],before);assert.equal(display[4],2);sources[4]=3;assert.notEqual(displayElevations(grid)[4],values[4]);assert.equal(nearestDepth(grid,1,1),2);});

test('chart evidence uses the same halfway rounding as its Python compiler',()=>{assert.deepEqual([.5,1.5,2.5,3.5,-.5,-1.5,4.4,4.6].map(roundEven),[0,2,2,4,0,-2,4,5]);assert.equal(roundEven(32.5),32);});


test('new terrain sources must be explicitly admitted by the scene manifest',()=>{
 const data=new ArrayBuffer(20);new Float32Array(data,0,4).set([-10,-20,-30,-40]);new Uint8Array(data,16).fill(8);
 assert.throws(()=>decodeTerrain(data,2,0,0,8));
 assert.equal(decodeTerrain(data,2,0,0,8,8,new Set([1,8])).sources![0],8);
 new Uint8Array(data,16)[0]=19;assert.throws(()=>decodeTerrain(data,2,0,0,8,8,new Set([1,8])));
});

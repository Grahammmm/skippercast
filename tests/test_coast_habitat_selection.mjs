import test from 'node:test';
import assert from 'node:assert/strict';
import {resolveHabitatSelection} from '../packages/coast/src/state/habitat-selection.ts';
const expires='2027-02-01T00:00:00Z',region={regionId:'cambria-san-simeon',ready:true,commercialArchivePermitted:true,license:'public-domain-us-gov',expiresAt:expires,archiveSha256:'a'.repeat(64),archiveETag:'"original"',archiveBytes:100};
const manifest={ready:true,expiresAt:'2027-03-01T00:00:00Z',regions:[region]};
const reef={id:123,geometry:{type:'Polygon',coordinates:[]},properties:{id:'different-id',region:'cambria-san-simeon',waypoint_latitude:35.9,waypoint_longitude:-121.5,depth_max_ft:90,exportable:true,screen_status:'pass',screen_expires_at:'2027-04-01T00:00:00Z',fit_lingcod:2,fit_gopher_rockfish:1,terrain_score:50}};
function mock(features=[reef],headOK=true){return async (path,init)=>{assert.equal(init.credentials,'omit');if(path.includes('skippercast-manifest'))return Response.json(manifest);if(path.includes('skippercast-habitat'))return Response.json({features});if(init.method==='HEAD')return headOK?new Response(null,{headers:{ETag:region.archiveETag,'Content-Length':'100'}}):new Response(null,{status:503});return new Response(null,{status:404});};}
async function using(fetcher,run){const previous=globalThis.fetch;globalThis.fetch=fetcher;try{await run();}finally{globalThis.fetch=previous;}}
test('exact reef restoration preserves original identity, point, published region and earliest publication expiry',async()=>using(mock(),async()=>{
 assert.deepEqual(await resolveHabitatSelection({id:'123',species:'lingcod'}),{id:'123',latitude:35.9,longitude:-121.5,region:'cambria-san-simeon',expiresAt:new Date(expires).toISOString(),kind:'reef'});
 for(const request of [{id:'0123',species:'lingcod'},{id:'different-id',species:'lingcod'},{id:'123',species:'gopher-rockfish'},{id:'123',species:'lingcod',depthLimitFt:89},{id:'123',species:'constructor'},{id:'',species:'all'}])assert.equal(await resolveHabitatSelection(request),null);
}));
test('rejected publication, expired feature and duplicate exact identity cannot supply context',async()=>{
 await using(mock([reef],false),async()=>assert.equal(await resolveHabitatSelection({id:'123',species:'lingcod'}),null));
 await using(mock([{...reef,properties:{...reef.properties,screen_expires_at:'2000-01-01Z'}}]),async()=>assert.equal(await resolveHabitatSelection({id:'123',species:'lingcod'}),null));
 await using(mock([reef,reef]),async()=>assert.equal(await resolveHabitatSelection({id:'123',species:'lingcod'}),null));
});
test('late source replies never restore superseded or aborted host context',async()=>{
 let resolve,active=true;const hold=new Promise(yes=>resolve=yes),base=mock();await using(async(...args)=>{await hold;return base(...args);},async()=>{
  const task=resolveHabitatSelection({id:'123',species:'lingcod'},{isCurrent:()=>active});active=false;resolve();assert.equal(await task,null);
 });const controller=new AbortController();controller.abort();await using(()=>{throw Error('aborted request must not fetch');},async()=>assert.equal(await resolveHabitatSelection({id:'123',species:'lingcod'},{signal:controller.signal}),null));
});
test('shore restoration uses hash-verified original access point and does not infer region from area',async()=>{
 const shore={id:'shore',properties:{areaId:'south',reviewExpiresAt:expires,access:[{coordinates:[-120.76,35.16]}]},geometry:{type:'MultiLineString',coordinates:[[[-120.8,35.2],[-120.7,35.1]]]}};
 const bytes=new TextEncoder().encode(JSON.stringify({features:[shore]})),sha256=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex'),asset={url:'/data/shore.json',bytes:bytes.length,sha256};
 await using(async path=>path.includes('manifest')?Response.json({schemaVersion:1,origin:[-120.98,35.43],shoreAsset:asset}):new Response(bytes),async()=>{
  assert.deepEqual(await resolveHabitatSelection({id:'shore',species:'surfperch'}),{id:'shore',latitude:35.16,longitude:-120.76,expiresAt:new Date(expires).toISOString(),kind:'shore'});
  assert.equal(await resolveHabitatSelection({id:'other',species:'halibut'}),null);
 });
 await using(async path=>path.includes('manifest')?Response.json({schemaVersion:1,origin:[-120.98,35.43],shoreAsset:{...asset,sha256:'b'.repeat(64)}}):new Response(bytes),async()=>assert.equal(await resolveHabitatSelection({id:'shore',species:'surfperch'}),null));
});

test('wide reef context requires original archive bindings and verified bytes; curated evidence wins',async()=>{
 const additional={...reef,id:'wide',properties:{...reef.properties,waypoint_latitude:35.85}},bytes=new TextEncoder().encode(JSON.stringify({features:[additional,reef]})),sha256=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
 const context={regions:[{regionId:region.regionId,archiveSha256:region.archiveSha256}],expiresAt:'2027-01-01T00:00:00Z',featureCount:2,asset:{url:'/data/wide.json',bytes:bytes.length,sha256}};
 const base=mock();let binding=context;
 await using(async(path,init)=>path.includes('reef-context')?Response.json(binding):path.includes('wide.json')?new Response(bytes):base(path,init),async()=>{
  const result=await resolveHabitatSelection({id:'wide',species:'lingcod'});assert.equal(result.latitude,35.85);assert.equal(result.expiresAt,'2027-01-01T00:00:00.000Z');
  binding={...context,regions:[{regionId:region.regionId,archiveSha256:'b'.repeat(64)}]};assert.equal(await resolveHabitatSelection({id:'wide',species:'lingcod'}),null);
  binding={...context,asset:{...context.asset,sha256:'b'.repeat(64)}};assert.equal(await resolveHabitatSelection({id:'wide',species:'lingcod'}),null);assert.equal((await resolveHabitatSelection({id:'123',species:'lingcod'})).latitude,35.9);
 });
});

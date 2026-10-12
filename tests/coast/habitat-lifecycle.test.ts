import test from 'node:test';
import assert from 'node:assert/strict';
import type {HabitatManifest,HabitatRegion} from '../../packages/coast/src/habitat-types.ts';
import {HabitatRetryGate,habitatReleaseFresh,readReviewedHabitat,validateHabitatHeads} from '../../packages/coast/src/map/habitat-lifecycle.ts';

const start=Date.parse('2026-10-02T05:39:00Z');
const region=(regionId:string,index:number):HabitatRegion=>({
 regionId,ready:true,sourceManifestUrl:'https://source.example/manifest-'+regionId+'.json',
 builtAt:'2026-10-02T03:00:00Z',expiresAt:'2026-11-04T00:00:00Z',
 archiveUrl:'https://source.example/'+regionId+'.pmtiles',archiveETag:'"archive-'+index+'"',
 archiveBytes:1000+index,archiveSha256:String(index).repeat(64),featureCount:10,coverageCount:20,
 layerNames:['cells','habitat'],bounds:[-121,35,-120,36],license:'public-domain-us-gov',commercialArchivePermitted:true
});
const manifest=():HabitatManifest=>({ready:true,builtAt:'2026-10-02T03:00:00Z',expiresAt:'2026-11-04T00:00:00Z',
 regions:[region('morro-bay',1),region('cambria-san-simeon',2)],featureCount:20,coverageCount:40,allowedSpeciesScores:{}});
const curated={features:[
 {properties:{id:'reviewed',exportable:true,screen_status:'pass',screen_expires_at:'2026-11-04T00:00:00Z'}},
 {properties:{id:'expired',exportable:true,screen_status:'pass',screen_expires_at:'2026-10-01T00:00:00Z'}},
 {properties:{id:'noncommercial',exportable:false,screen_status:'pass',screen_expires_at:'2026-11-04T00:00:00Z'}}
]};
const receipt=(r:HabitatRegion)=>new Response(null,{headers:{ETag:r.archiveETag,'Content-Length':String(r.archiveBytes)}});
const deferred=<T>()=>{let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes;});return {promise,resolve};};
const assets=(m:HabitatManifest,head:(r:HabitatRegion)=>Promise<Response>)=>async(url:string,init?:RequestInit)=>{
 assert.equal(init?.cache,'no-store');assert.ok(init?.signal instanceof AbortSignal);
 if(url==='/manifest.json')return Response.json(m);
 if(url==='/details.geojson')return Response.json(curated);
 assert.equal(init?.method,'HEAD');const id=new URL(url,'https://fish.example').searchParams.get('region');
 const r=m.regions.find(r=>r.regionId===id);assert.ok(r);return head(r);
};

test('an upstream updating outage recovers without reload, with bounded retries and original reviewed clocks',async()=>{
 const m=manifest();let now=start,updating=true,headRequests=0,publications=0,visible=false;
 const gate=new HabitatRetryGate(()=>now),fetcher=assets(m,async r=>{headRequests++;return updating?new Response(null,{status:503}):receipt(r);});
 const attempt=()=>gate.run(async current=>{
  const candidate=await readReviewedHabitat('/manifest.json','/details.geojson',fetcher,()=>now);
  if(!current())return;visible=true;publications++;
  assert.equal(candidate.manifest.builtAt,m.builtAt);assert.equal(candidate.manifest.expiresAt,m.expiresAt);
  assert.deepEqual(candidate.details.map(f=>f.properties.id),['reviewed']);
 },()=>{visible=false;gate.invalidate();});
 await attempt();assert.equal(visible,false);assert.equal(headRequests,2);
 updating=false;now+=59999;await attempt();assert.equal(headRequests,2);assert.equal(publications,0);
 now++;await attempt();assert.equal(visible,true);assert.equal(publications,1);assert.equal(headRequests,4);
 await attempt();assert.equal(publications,1);
});

test('one working region cannot publish while another required region is pending or unavailable',async()=>{
 const m=manifest(),last=deferred<Response>();let published=false,headRequests=0;
 const promise=readReviewedHabitat('/manifest.json','/details.geojson',assets(m,async r=>{
  headRequests++;return r.regionId==='morro-bay'?receipt(r):last.promise;
 }),()=>start).then(()=>{published=true;});
 while(headRequests<2)await new Promise(resolve=>setImmediate(resolve));
 assert.equal(published,false);last.resolve(new Response(null,{status:503}));
 await assert.rejects(promise,/publication changed/);assert.equal(published,false);
});

test('a previously visible release is withdrawn on a HEAD failure and can recover on a later reviewed check',async()=>{
 const m=manifest();let now=start,available=true,visible=true,withdrawals=0;
 const gate=new HabitatRetryGate(()=>now),fetcher=assets(m,async r=>available?receipt(r):new Response(null,{status:503}));
 const check=()=>gate.run(async current=>{
  if(visible)await validateHabitatHeads(m,fetcher,()=>now);
  else {await readReviewedHabitat('/manifest.json','/details.geojson',fetcher,()=>now);if(current())visible=true;}
 },()=>{visible=false;withdrawals++;gate.invalidate();});
 available=false;await check();assert.equal(visible,false);assert.equal(withdrawals,1);
 available=true;now+=60000;await check();assert.equal(visible,true);assert.equal(withdrawals,1);
});

test('overlapping ticks do not start another request and withdrawal invalidates an in-flight publication',async()=>{
 let now=start,attempts=0,published=0;const gate=new HabitatRetryGate(()=>now),pending=deferred<void>();
 const first=gate.run(async current=>{attempts++;await pending.promise;if(current())published++;},()=>assert.fail('Unexpected failure'));
 now+=120000;await gate.run(async()=>{attempts++;},()=>assert.fail('Unexpected failure'));
 assert.equal(attempts,1);gate.invalidate();pending.resolve();await first;assert.equal(published,0);
 await gate.run(async()=>{attempts++;},()=>assert.fail('Unexpected failure'));assert.equal(attempts,1);
 now+=60000;await gate.run(async current=>{attempts++;if(current())published++;},()=>assert.fail('Unexpected failure'));
 assert.equal(attempts,2);assert.equal(published,1);
});

test('HEAD success cannot substitute another archive pin, length or weak ETag',async()=>{
 const badReceipts:Record<string,string>[]=[{ETag:'"different"','Content-Length':'1001'},{ETag:'"archive-1"','Content-Length':'999'},
  {ETag:'W/"archive-1"','Content-Length':'1001'},{}];
 for(const headers of badReceipts){
  const m=manifest();await assert.rejects(validateHabitatHeads(m,async()=>new Response(null,{headers}),()=>start),/publication changed/);
 }
});

test('rights, expiry, unique regions and archive identities remain mandatory on every recovery',async()=>{
 const mutations:Array<(m:HabitatManifest)=>void>=[
  m=>m.ready=false,m=>m.expiresAt=new Date(start).toISOString(),m=>m.regions[0].ready=false,
  m=>m.regions[0].commercialArchivePermitted=false,m=>m.regions[0].license='noncommercial',
  m=>m.regions[0].expiresAt=new Date(start).toISOString(),m=>m.regions[0].archiveETag='W/"weak"',
  m=>m.regions[0].archiveSha256='unreviewed',m=>m.regions[0].archiveBytes=0,
  m=>m.regions[1].regionId=m.regions[0].regionId,m=>m.regions=[]
 ];
 for(const mutate of mutations){const m=manifest();mutate(m);assert.equal(habitatReleaseFresh(m,start),false);
  await assert.rejects(validateHabitatHeads(m,async()=>assert.fail('No HEAD for unusable release'),()=>start),/Unusable/);
 }
});

test('a screen expiring while regional checks are in flight never becomes publishable',async()=>{
 const m=manifest();let now=start,requests=0;const pending=deferred<Response>();
 m.regions[1].expiresAt=new Date(start+1000).toISOString();
 const checking=validateHabitatHeads(m,async url=>{requests++;const r=m.regions.find(r=>url.endsWith(r.regionId))!;
  return r.regionId==='morro-bay'?receipt(r):pending.promise;
 },()=>now);
 while(requests<2)await new Promise(resolve=>setImmediate(resolve));now+=1000;pending.resolve(receipt(m.regions[1]));
 await assert.rejects(checking,/publication changed/);
});

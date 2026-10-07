import test from 'node:test';import assert from 'node:assert/strict';
import {COASTAL_INDEX,COASTAL_META,COASTAL_PREFIX,COASTAL_PRODUCTS,canMutateCoastalSnapshot,saveCoastalSnapshot,readCoastalSnapshot,deleteCoastalSnapshot} from '../dist/coastal-offline-core.js';
const origin='https://skipper.test',now=()=>new Date('2026-10-07T12:00Z');
class Storage{constructor(){this.items=new Map();this.fail=null;}async open(name){if(this.fail?.(name))throw Error('Quota denied');if(!this.items.has(name))this.items.set(name,new Map());const entries=this.items.get(name);return {match:async k=>entries.get(String(k))?.clone(),put:async(k,response)=>{if(this.fail?.(name,String(k)))throw Error('Quota denied');entries.set(String(k),response.clone());},delete:async k=>entries.delete(String(k))};}async keys(){return [...this.items.keys()];}async has(name){return this.items.has(name);}async delete(name){return this.items.delete(name);}}
const packet={schemaVersion:1,countyId:'slo',generatedAt:'2026-10-07T10:00:00Z',sources:[{observedAt:'2026-10-06T11:00:00Z'}],forecasts:[],observations:[],tides:[],tideEvents:[],alerts:[],catches:[],visibility:{},currents:[],stations:[],recentWindowDays:14};
function fetcher(transform=()=>packet,requests=[]){return async(url,init)=>{requests.push({url,init});assert.equal(new URL(url).origin,origin);assert.equal(new URL(url).search,'');assert.ok(COASTAL_PRODUCTS.some(p=>origin+p.path===url));assert.equal(init.method,'GET');assert.equal(init.credentials,'omit');assert.equal(init.redirect,'error');assert.deepEqual(init.headers,{'X-SC-Offline-Save':'1'});assert.ok(init.signal instanceof AbortSignal);return new Response(JSON.stringify(transform(url)),{headers:{'Content-Type':'application/json',ETag:'"original"','X-Fish-Habitat-Release':'original-public-header'}});};}
const options=caches=>({origin,caches,now,fetcher:fetcher()});
test('explicit complete save commits three exact public products and preserves original bytes, clocks and headers',async()=>{
 const caches=new Storage(),requests=[],o={...options(caches),fetcher:fetcher(undefined,requests)};assert.equal(await readCoastalSnapshot(o),null);assert.equal(requests.length,0);
 const saved=await saveCoastalSnapshot(o);assert.equal(requests.length,3);assert.deepEqual(await readCoastalSnapshot(o),saved);assert.equal(saved.saved_at,now().toISOString());assert.equal(saved.products.length,3);
 const cache=await caches.open(saved.cache);for(const {path} of COASTAL_PRODUCTS){const response=await cache.match(origin+path);assert.equal(await response.text(),JSON.stringify(packet));assert.equal(response.headers.get('ETag'),'"original"');assert.equal(response.headers.get('X-SC-Saved-At'),saved.saved_at);}
 assert.equal(await deleteCoastalSnapshot(o),true);assert.equal(await readCoastalSnapshot(o),null);assert.equal(caches.items.has(saved.cache),false);assert.equal(await deleteCoastalSnapshot(o),false);
});
test('failed HTTP/binding/clock/JSON save retains prior committed snapshot and removes candidate',async()=>{
 const caches=new Storage(),o=options(caches),old=await saveCoastalSnapshot(o);
 for(const response of [new Response('{}',{status:503}),Response.json(null),Response.json({...packet,countyId:'monterey'}),Response.json({...packet,schemaVersion:2}),Response.json({...packet,generatedAt:'2026-10-07T13:00Z'}),Response.json({...packet,generatedAt:'bad'}),new Response('not json')]){
  await assert.rejects(saveCoastalSnapshot({...o,fetcher:async()=>response.clone()}));assert.equal((await readCoastalSnapshot(o)).cache,old.cache);assert.deepEqual([...caches.items.keys()].filter(k=>k.startsWith(COASTAL_PREFIX)),[old.cache]);
 }
});
test('streaming byte limit rejects absent or misleading lengths and cancels the reader',async()=>{
 for(const length of [undefined,'1']){let cancelled=false;const stream=new ReadableStream({start(controller){controller.enqueue(new Uint8Array(8*1024*1024+1));},cancel(){cancelled=true;}}),caches=new Storage();await assert.rejects(saveCoastalSnapshot({...options(caches),fetcher:async()=>new Response(stream,{headers:{'Content-Type':'application/json',...(length?{'Content-Length':length}:{})}})}),/byte budget/);assert.equal(cancelled,true);assert.equal([...caches.items.keys()].some(k=>k.startsWith(COASTAL_PREFIX)),false);}
 const caches=new Storage();await assert.rejects(saveCoastalSnapshot({...options(caches),fetcher:async()=>new Response('{}',{headers:{'Content-Type':'application/json','Content-Length':String(9*1024*1024)}})}),/byte budget/);
});
test('abort and quota failure preserve pointer; incomplete unreferenced candidates are never read',async()=>{
 const caches=new Storage(),o=options(caches),old=await saveCoastalSnapshot(o),controller=new AbortController();controller.abort();await assert.rejects(saveCoastalSnapshot({...o,signal:controller.signal}));assert.equal((await readCoastalSnapshot(o)).cache,old.cache);
 caches.fail=(name,k)=>name!==old.cache&&name!==COASTAL_INDEX&&!!k;await assert.rejects(saveCoastalSnapshot(o),/Quota/);caches.fail=null;assert.equal((await readCoastalSnapshot(o)).cache,old.cache);
 caches.fail=(name,k)=>name===COASTAL_INDEX&&!!k;await assert.rejects(saveCoastalSnapshot(o),/Quota/);caches.fail=null;assert.equal((await readCoastalSnapshot(o)).cache,old.cache);
 await caches.open(COASTAL_PREFIX+'incomplete');assert.equal((await readCoastalSnapshot(o)).cache,old.cache);const denied={has:async()=>true,open:async()=>{throw Error('Storage denied');}};await assert.rejects(readCoastalSnapshot({origin,caches:denied}),/Storage denied/);
});
test('save/delete and overlapping saves serialize without publishing partial products',async()=>{
 const caches=new Storage(),o=options(caches);let release;const held=new Promise(resolve=>release=resolve),base=fetcher();let calls=0;
 const pending=saveCoastalSnapshot({...o,fetcher:async(...args)=>{calls++;await held;return base(...args);}}),deleted=deleteCoastalSnapshot(o);await new Promise(resolve=>setImmediate(resolve));assert.equal(calls,1);const index=await caches.open(COASTAL_INDEX);assert.equal(await index.match(origin+COASTAL_META),undefined);release();await pending;assert.equal(await deleted,true);assert.equal(await readCoastalSnapshot(o),null);
 const [first,last]=await Promise.all([saveCoastalSnapshot(o),saveCoastalSnapshot(o)]);assert.notEqual(first.cache,last.cache);assert.equal((await readCoastalSnapshot(o)).cache,last.cache);assert.equal(caches.items.has(first.cache),false);
});
test('origin must be a plain origin; snapshot paths cannot be supplied by caller',async()=>{
 for(const invalid of ['https://skipper.test/private','https://skipper.test/?region=other'])await assert.rejects(saveCoastalSnapshot({...options(new Storage()),origin:invalid}));
 const caches=new Storage(),requests=[];await saveCoastalSnapshot({...options(caches),paths:['/api/account'],fetcher:fetcher(undefined,requests)});assert.equal(requests.length,3);assert.ok(requests.every(r=>r.url.startsWith(origin+'/api/coast/')));
});

test('abort during a streamed body cancels consumption and preserves committed snapshot',async()=>{
 const caches=new Storage(),o=options(caches),old=await saveCoastalSnapshot(o),controller=new AbortController();let cancel=false,started;const reading=new Promise(resolve=>started=resolve);
 const task=saveCoastalSnapshot({...o,signal:controller.signal,fetcher:async()=>new Response(new ReadableStream({start(stream){stream.enqueue(new TextEncoder().encode('{'));started();},cancel(){cancel=true;}}),{headers:{'Content-Type':'application/json'}})});await reading;controller.abort();await assert.rejects(task);assert.equal(cancel,true);assert.equal((await readCoastalSnapshot(o)).cache,old.cache);
});
test('browser origin-scoped lock coordinates mutations while invalid UTF-8 cannot be stored',async()=>{
 const caches=new Storage(),names=[],o={...options(caches),locks:{request:async(name,work)=>{names.push(name);return work();}}};await saveCoastalSnapshot(o);await readCoastalSnapshot(o);await deleteCoastalSnapshot(o);assert.deepEqual(names,Array(3).fill('skippercast-coastal-snapshot:'+origin));
 await assert.rejects(saveCoastalSnapshot({...o,fetcher:async()=>new Response(new Uint8Array([123,34,120,34,58,34,255,34,125]),{headers:{'Content-Type':'application/json'}})}));assert.equal(await readCoastalSnapshot(o),null);
});

test('offline responses cannot be re-saved with a fresh saved time; malformed index metadata is unavailable',async()=>{
 const caches=new Storage(),o=options(caches),old=await saveCoastalSnapshot(o);await assert.rejects(saveCoastalSnapshot({...o,fetcher:async()=>new Response(JSON.stringify(packet),{headers:{'Content-Type':'application/json','X-SC-Offline':old.saved_at}})}),/cannot create a fresh snapshot/);assert.equal((await readCoastalSnapshot(o)).cache,old.cache);
 const index=await caches.open(COASTAL_INDEX);await index.put(origin+COASTAL_META,new Response('bad JSON'));assert.equal(await readCoastalSnapshot(o),null);await index.put(origin+COASTAL_META,Response.json({...old,products:[null,null,null]}));assert.equal(await readCoastalSnapshot(o),null);
});
test('cross-tab shared Web Lock serializes separate storage facades and preserves the final replacement',async()=>{
 const storage=new Storage(),facade=()=>({open:storage.open.bind(storage),delete:storage.delete.bind(storage),has:storage.has.bind(storage),keys:storage.keys.bind(storage)});let queue=Promise.resolve();const locks={request(_name,work){const task=queue.catch(()=>{}).then(work);queue=task;return task;}};
 const a={...options(facade()),locks},b={...options(facade()),locks};const [first,second]=await Promise.all([saveCoastalSnapshot(a),saveCoastalSnapshot(b)]);assert.equal((await readCoastalSnapshot(a)).cache,second.cache);assert.equal(storage.items.has(first.cache),false);
 const deletion=deleteCoastalSnapshot(a),replacement=saveCoastalSnapshot(b);await deletion;const latest=await replacement;assert.equal((await readCoastalSnapshot(a)).cache,latest.cache);assert.equal(storage.items.has(latest.cache),true);
});
test('browser mutations fail closed without cross-tab locking while reads remain available',async()=>{
 const previous=globalThis.window;globalThis.window={};try{const o={...options(new Storage()),locks:{}};assert.equal(canMutateCoastalSnapshot(o),false);await assert.rejects(saveCoastalSnapshot(o),/Web Locks/);await assert.rejects(deleteCoastalSnapshot(o),/Web Locks/);assert.equal(await readCoastalSnapshot(o),null);}finally{if(previous===undefined)delete globalThis.window;else globalThis.window=previous;}
});
test('original JSON MIME is mandatory and all stored products must retain complete status and saved stamp',async()=>{
 for(const type of ['text/plain','text/html','application/problem+json',''])await assert.rejects(saveCoastalSnapshot({...options(new Storage()),fetcher:async()=>new Response(JSON.stringify(packet),{headers:{'Content-Type':type}})}),/application\/json MIME/);
 for(const change of ['missing','status','stamp']){const caches=new Storage(),o=options(caches),saved=await saveCoastalSnapshot(o),cache=await caches.open(saved.cache),path=origin+'/api/coast/ocean';if(change==='missing')await cache.delete(path);else await cache.put(path,new Response(JSON.stringify(packet),{status:change==='status'?503:200,headers:{'Content-Type':'application/json','X-SC-Saved-At':change==='stamp'?'2000-01-01Z':saved.saved_at}}));assert.equal(await readCoastalSnapshot(o),null);}
});
test('missing candidates are not created by reads and invalid/future descriptors remain gaps',async()=>{
 const caches=new Storage(),o=options(caches);assert.equal(await readCoastalSnapshot(o),null);assert.equal(caches.items.size,0);const saved=await saveCoastalSnapshot(o);await caches.delete(saved.cache);assert.equal(await readCoastalSnapshot(o),null);assert.equal(caches.items.has(saved.cache),false);
 const index=await caches.open(COASTAL_INDEX);for(const change of [{cache:COASTAL_PREFIX+'UPPER'},{cache:COASTAL_PREFIX+'a'.repeat(160)},{saved_at:'2026-10-08T00:00:00Z'}]){const descriptor={...saved,...change};await index.put(origin+COASTAL_META,new Response(JSON.stringify(descriptor),{headers:{'X-SC-Saved-At':descriptor.saved_at}}));assert.equal(await readCoastalSnapshot(o),null);assert.equal(caches.items.has(descriptor.cache),false);}
});
test('each request/body receives a 20-second deadline combined with explicit cancellation',async()=>{
 const previous=AbortSignal.timeout,deadline=new AbortController(),explicit=new AbortController(),durations=[];AbortSignal.timeout=ms=>{durations.push(ms);return deadline.signal;};let started,cancelled=false;const reading=new Promise(resolve=>started=resolve);
 try{const task=saveCoastalSnapshot({...options(new Storage()),signal:explicit.signal,fetcher:async(_url,init)=>{assert.notEqual(init.signal,explicit.signal);return new Response(new ReadableStream({start(stream){stream.enqueue(new TextEncoder().encode('{'));started();},cancel(){cancelled=true;}}),{headers:{'Content-Type':'application/json'}});}});await reading;deadline.abort(new DOMException('Deadline expired','TimeoutError'));await assert.rejects(task,/Deadline expired/);assert.deepEqual(durations,[20000]);assert.equal(cancelled,true);}finally{AbortSignal.timeout=previous;}
});

test('wrong-product and malformed product-specific 200 responses cannot replace prior pack',async()=>{
 const caches=new Storage(),o=options(caches),old=await saveCoastalSnapshot(o);
 for(const [path,change] of [['report',{visibility:[]}],['report',{forecasts:null}],['ocean',{currents:null}],['ocean',{sources:{}}],['history',{stations:null}],['history',{recentWindowDays:0}],['history',{recentWindowDays:'14'}]]){
  await assert.rejects(saveCoastalSnapshot({...o,fetcher:fetcher(url=>url.endsWith('/'+path)?{...packet,...change}:packet)}),/product shape/);assert.equal((await readCoastalSnapshot(o)).cache,old.cache);
 }
 const reportOnly={schemaVersion:1,countyId:'slo',generatedAt:packet.generatedAt,forecasts:[],observations:[],tides:[],tideEvents:[],alerts:[],sources:[],catches:[],visibility:{}};await assert.rejects(saveCoastalSnapshot({...o,fetcher:fetcher(()=>reportOnly)}),/product shape/);assert.equal((await readCoastalSnapshot(o)).cache,old.cache);
 const cache=await caches.open(old.cache);await cache.put(origin+'/api/coast/ocean',new Response(JSON.stringify({...packet,currents:null}),{headers:{'Content-Type':'application/json','X-SC-Saved-At':old.saved_at}}));assert.equal(await readCoastalSnapshot(o),null,'tampered stored shape is a gap');
});

test('saving sweeps orphan candidates while retaining prior pack until commit; deletion removes malformed-pointer family only',async()=>{
 const caches=new Storage(),o=options(caches),old=await saveCoastalSnapshot(o);await caches.open(COASTAL_PREFIX+'orphan');for(const name of ['sc-data','sc-pack-morro','sc-shell-build','sc-coastal-snapshots-unrelated'])await caches.open(name);
 await assert.rejects(saveCoastalSnapshot({...o,fetcher:async()=>new Response('{}',{status:503,headers:{'Content-Type':'application/json'}})}));assert.equal(caches.items.has(old.cache),true);assert.equal(caches.items.has(COASTAL_PREFIX+'orphan'),false);
 const latest=await saveCoastalSnapshot(o);assert.equal(caches.items.has(old.cache),false);await caches.open(COASTAL_PREFIX+'unfinished');const index=await caches.open(COASTAL_INDEX);await index.put(origin+COASTAL_META,new Response('malformed pointer'));assert.equal(await deleteCoastalSnapshot(o),true);assert.equal(caches.items.has(latest.cache),false);assert.equal(caches.items.has(COASTAL_PREFIX+'unfinished'),false);assert.equal(caches.items.has(COASTAL_INDEX),false);assert.deepEqual([...caches.items.keys()].sort(),['sc-coastal-snapshots-unrelated','sc-data','sc-pack-morro','sc-shell-build'].sort());
});
test('cleanup failures reject deletion and distinguish a committed new save from retained prior state',async()=>{
 const caches=new Storage(),o=options(caches),old=await saveCoastalSnapshot(o),original=caches.delete.bind(caches);let blocked=old.cache;caches.delete=async name=>{if(name===blocked)throw Error('Deletion denied');return original(name);};
 let failure;try{await saveCoastalSnapshot(o);}catch(error){failure=error;}assert.equal(failure.committed,true);assert.match(failure.message,/New coastal snapshot saved/);const latest=await readCoastalSnapshot(o);assert.equal(latest.cache,failure.descriptor.cache);assert.notEqual(latest.cache,old.cache);assert.equal(caches.items.has(old.cache),true);
 await assert.rejects(deleteCoastalSnapshot(o),/cleanup failed/);assert.equal(caches.items.has(COASTAL_INDEX),false);assert.equal(caches.items.has(old.cache),true);assert.equal(caches.items.has(latest.cache),false);blocked=null;assert.equal(await deleteCoastalSnapshot(o),true);assert.equal(caches.items.size,0);
 const another=await saveCoastalSnapshot(o);blocked=COASTAL_INDEX;await assert.rejects(deleteCoastalSnapshot(o),/Deletion denied/);assert.equal(caches.items.has(another.cache),true);
});

// Synthetic, process-local guards precede the complete target module import.
import test, {after} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {syncBuiltinESMExports} from 'node:module';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dgram from 'node:dgram';
import childProcess from 'node:child_process';

const attempts=[];
const refuse=kind=>(..._args)=>{attempts.push(kind);throw Error('SP82 forbidden external effect: '+kind);};
globalThis.fetch=refuse('fetch/model');
for(const [api,names] of [[http,['request','get']],[https,['request','get']],
  [net,['connect','createConnection']],[tls,['connect']],[dgram,['createSocket']],
  [childProcess,['exec','execFile','spawn','fork','execSync','execFileSync','spawnSync']]]) {
  for(const name of names)api[name]=refuse(name);
}
net.Socket.prototype.connect=refuse('socket.connect');
syncBuiltinESMExports();

class Storage {
  items=new Map(); opened=[]; deleted=[];
  async open(name) {
    this.opened.push(name);
    if(!this.items.has(name))this.items.set(name,new Map());
    const entries=this.items.get(name);
    return {
      match:async key=>entries.get(String(key))?.clone(),
      put:async(key,response)=>entries.set(String(key),response.clone()),
      delete:async key=>entries.delete(String(key)),
    };
  }
  async keys(){return [...this.items.keys()];}
  async has(name){return this.items.has(name);}
  async delete(name){this.deleted.push(name);return this.items.delete(name);}
  async image(){
    const rows=[];
    for(const [name,entries] of this.items){
      const values=[];
      for(const [key,response] of entries)values.push([key,response.status,[...response.headers],Array.from(new Uint8Array(await response.clone().arrayBuffer()))]);
      rows.push([name,values]);
    }
    return rows;
  }
}
const locks={request:async(_name,work)=>work()};
globalThis.caches=new Storage();
Object.defineProperty(globalThis,'navigator',{value:{locks},configurable:true});
// Run original literal selectors in this guarded process, without copying tests.
const mode=process.argv[2]??'focused';
if(!['baseline','focused','regression'].includes(mode))throw Error('Unknown SP82 test mode');
if(mode!=='regression'){
  const {COASTAL_INDEX,COASTAL_META,COASTAL_PREFIX,COASTAL_PRODUCTS,COASTAL_REQUEST_TIMEOUT,
    COASTAL_TOTAL_LIMIT,saveCoastalSnapshot,readCoastalSnapshot}=await import('../dist/coastal-offline-core.js');
  const products=JSON.parse(await readFile(new URL('./fixtures/sp82_snapshot_length/products.json',import.meta.url),'utf8'));
  const origin='https://sp82.invalid',now=()=>new Date('2026-10-07T12:00:00Z');
  const body=path=>JSON.stringify(products[path]);
  const size=path=>new TextEncoder().encode(body(path)).byteLength;
  const paths=COASTAL_PRODUCTS.map(p=>p.path);
  const response=(path,{encoding,length='matching',mime='application/json',offline=false}={})=>{
    const headers=new Headers({'Content-Type':mime});
    if(encoding!==undefined)headers.set('Content-Encoding',encoding);
    if(length!==null)headers.set('Content-Length',length==='matching'?String(size(path)):String(length));
    if(offline)headers.set('X-SC-Offline','synthetic');
    return new Response(body(path),{headers});
  };
  function options(caches,transform=path=>response(path)){
    return {origin,caches,locks,now,fetcher:async(url,init)=>{
      assert.equal(new URL(url).origin,origin);
      const path=new URL(url).pathname;assert.ok(paths.includes(path));
      assert.equal(init.method,'GET');assert.equal(init.credentials,'omit');assert.equal(init.redirect,'error');
      assert.deepEqual(init.headers,{'X-SC-Offline-Save':'1'});assert.ok(init.signal instanceof AbortSignal);
      return transform(path,init);
    }};
  }
  async function accepted(config){
    const caches=new Storage(),o=options(caches,path=>response(path,config)),saved=await saveCoastalSnapshot(o);
    assert.deepEqual(await readCoastalSnapshot(o),saved);
    assert.equal(saved.products.length,3);
    for(const path of paths){
      const stored=await (await caches.open(saved.cache)).match(origin+path);
      assert.equal(await stored.text(),body(path));
      assert.equal(saved.products.find(p=>p.path===path).bytes,size(path));
    }
    return saved;
  }
  async function rejected(transform,pattern){
    const caches=new Storage();
    await assert.rejects(saveCoastalSnapshot(options(caches,transform)),pattern);
    assert.deepEqual(await caches.keys(),[],'failed fresh candidate must be removed without creating index');
  }
  test('A4 primary: declared-one identity must reject valid complete products',async()=>{
    const caches=new Storage();let outcome;
    try{outcome={kind:'returned',value:await saveCoastalSnapshot(options(caches,path=>response(path,{encoding:'identity',length:1}))) };}
    catch(error){outcome={kind:'rejected',error};}
    // Capture before asserting so a product exception is data, not a harness error.
    assert.equal(outcome.kind,'rejected','SP82_PRIMARY_IDENTITY_MISMATCH: saver must reject rather than commit');
    assert.match(outcome.error.message,/declared byte length/);
    assert.deepEqual(await caches.keys(),[]);
  });
  test('A4 healthy: matching-length complete products remain accepted',async()=>{await accepted({encoding:'identity'});});

  if(mode==='focused'){
    test('A1 fixture proves UTF-8 byte count differs from JavaScript character count',()=>{
      for(const path of paths)assert.ok(size(path)>body(path).length);
      assert.equal(COASTAL_REQUEST_TIMEOUT,20000);assert.equal(COASTAL_TOTAL_LIMIT,32*1024*1024);
      assert.deepEqual(COASTAL_PRODUCTS.map(p=>p.limit),[8*1024*1024,8*1024*1024,16*1024*1024]);
    });
    for(const encoding of [undefined,'identity','IDENTITY',' Identity ']){
      for(const delta of [-1,1])test(`A1 ${encoding??'absent'} declared length ${delta<0?'shorter':'longer'} rejects`,async()=>{
        await rejected(path=>response(path,{encoding,length:size(path)+delta}),/declared byte length/);
      });
      test(`A1 ${encoding??'absent'} matching length accepts`,async()=>{await accepted({encoding});});
      test(`A1 ${encoding??'absent'} no length accepts`,async()=>{await accepted({encoding,length:null});});
    }
    test('A1 character count is not an acceptable declared byte length',async()=>{
      await rejected(path=>response(path,{length:body(path).length}),/declared byte length/);
    });
    for(const encoding of ['gzip','br'])test(`A2 ${encoding} encoded length may differ from decoded bytes`,async()=>{
      await accepted({encoding,length:1});
    });
    for(const length of ['-1','1.5','1e2','invalid','9007199254740992',String(8*1024*1024+1)]){
      test(`A2 malformed or over-budget declared length ${length} refuses`,async()=>{
        await rejected(path=>response(path,{encoding:'gzip',length}),/byte budget/);
      });
    }
    test('A2 zero declaration disagrees with a nonempty valid product',async()=>{
      await rejected(path=>response(path,{length:0}),/declared byte length/);
    });
    for(const encoding of [undefined,'gzip','br'])test(`A2 ${encoding??'absent'} streaming over budget still cancels`,async()=>{
      let cancelled=false;
      await rejected(()=>new Response(new ReadableStream({
        start(controller){controller.enqueue(new Uint8Array(8*1024*1024+1));},
        cancel(){cancelled=true;},
      }),{headers:{'Content-Type':'application/json','Content-Length':'1',...(encoding?{'Content-Encoding':encoding}:{})}}),/byte budget/);
      assert.equal(cancelled,true);
    });
    test('A2 wrong MIME refuses independently of matching byte length',async()=>{
      await rejected(path=>response(path,{mime:'text/plain'}),/application\/json MIME/);
    });
    test('A2 offline-origin response refuses independently of matching byte length',async()=>{
      await rejected(path=>response(path,{offline:true}),/cannot create a fresh snapshot/);
    });
    test('A2 read failure retains its actual refusal and removes candidate',async()=>{
      await rejected(()=>new Response(new ReadableStream({start(c){c.error(Error('synthetic read failure'));}}),
        {headers:{'Content-Type':'application/json'}}),/synthetic read failure/);
    });
    test('A2 abort during bounded consumption cancels without committing',async()=>{
      const caches=new Storage(),controller=new AbortController();let ready,cancelled=false;
      const started=new Promise(resolve=>ready=resolve);
      const task=saveCoastalSnapshot({...options(caches,()=>new Response(new ReadableStream({
        start(c){c.enqueue(new TextEncoder().encode('{'));ready();},cancel(){cancelled=true;},
      }),{headers:{'Content-Type':'application/json'}})),signal:controller.signal});
      await started;controller.abort(new Error('synthetic abort'));
      await assert.rejects(task,/synthetic abort/);assert.equal(cancelled,true);assert.deepEqual(await caches.keys(),[]);
    });
    for(const [position,badPath] of paths.entries())test(`A3 mismatch in product ${position+1} preserves exact prior index and bytes`,async()=>{
      const caches=new Storage(),o=options(caches),old=await saveCoastalSnapshot(o);
      const unrelated=await caches.open('synthetic-unrelated');await unrelated.put(origin+'/unrelated',new Response('untouched'));
      const before=await caches.image(),deletedAt=caches.deleted.length,openedAt=caches.opened.length;
      const requested=[];
      await assert.rejects(saveCoastalSnapshot(options(caches,path=>{
        requested.push(path);return response(path,{length:path===badPath?1:'matching'});
      })),/declared byte length/);
      assert.deepEqual(requested,paths.slice(0,position+1));
      assert.deepEqual(await caches.image(),before,'prior pointer, metadata, products and unrelated cache unchanged');
      const candidateNames=[...new Set(caches.opened.slice(openedAt))].filter(n=>n.startsWith(COASTAL_PREFIX)&&n!==old.cache);
      assert.equal(candidateNames.length,1);assert.deepEqual(caches.deleted.slice(deletedAt),candidateNames);
      assert.deepEqual(await readCoastalSnapshot(o),old);
      assert.ok(await caches.has(COASTAL_INDEX));
    });
    for(const encoding of [undefined,'identity'])test(`A3 reader returns null for tampered ${encoding??'absent'} length`,async()=>{
      const caches=new Storage(),o=options(caches),old=await saveCoastalSnapshot(o);
      const cache=await caches.open(old.cache),path=paths[1],stored=await cache.match(origin+path),headers=new Headers(stored.headers);
      headers.set('Content-Length','1');
      if(encoding===undefined)headers.delete('Content-Encoding');else headers.set('Content-Encoding',encoding);
      await cache.put(origin+path,new Response(await stored.arrayBuffer(),{headers}));
      assert.equal(await readCoastalSnapshot(o),null);
    });
  }
  after(()=>{assert.deepEqual(attempts,[],'no network, external model or child-process attempts');console.log('SP82_OFFLINE_ATTEMPTS=0');});
}else{
  assert.equal(process.argv[3],'tests/test_coastal_offline.mjs','literal original regression selector required');
  await import('./test_coastal_offline.mjs');
  after(()=>{assert.deepEqual(attempts,[]);console.log('SP82_OFFLINE_ATTEMPTS=0');});
}

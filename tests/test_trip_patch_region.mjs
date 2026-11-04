// PATCH /api/trips for a saved trip whose region is no longer configured answers a
// named 409 and writes nothing (it used to be a TypeError the error net called a 503).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
globalThis.REGIONS={'morro-bay':read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT=read('../deployments/production.json');
import {withSessions} from './fixtures/test-sessions.mjs';
const {default:deployed}=await import('../server/index.ts');
const {RETIRED_AREA}=await import('../server/routes/trips.ts');
const worker=withSessions(deployed);
const TEXT="This trip's area is no longer offered; its plan cannot be changed. Save a new trip.";

function database(){
  const sql=new DatabaseSync(':memory:'),journal=read('../drizzle/meta/_journal.json');
  for(const {tag} of [...journal.entries].sort((a,b)=>a.idx-b.idx))sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`,import.meta.url),'utf8'));
  const writes=[];
  const adapter={prepare(query){let args=[];const statement=sql.prepare(query);return {bind(...a){args=a;return this;},async first(){return statement.get(...args)||null;},async all(){return {results:statement.all(...args)};},async run(){if(/^\s*(UPDATE|INSERT|DELETE)/i.test(query)&&/\btrips\b/.test(query))writes.push(query.slice(0,24));const info=statement.run(...args);return {meta:{changes:Number(info.changes)}};}};},async batch(queries){sql.exec('BEGIN');try{const result=[];for(const q of queries)result.push(await q.run());sql.exec('COMMIT');return result;}catch(e){sql.exec('ROLLBACK');throw e;}}};
  return {sql,adapter,writes};
}
const origin='https://skippercast.com';
function request(path,{owner,method='GET',body}={}){
  const headers={'Content-Type':'application/json'};if(owner)headers['x-test-owner']=owner;if(method!=='GET')headers.Origin=origin;
  return new Request(origin+'/api/'+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});
}
const day=24*60*60*1000;
const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles'}).format(new Date(Date.now()+day));
const alert={region:'morro-bay',point:'north',species:'reef',date,start_hour:7,end_hour:13,wind_limit:8,gust_limit:12,sea_limit:3};
const spot=(id,order)=>({id,name:'Spot '+id,lat:35.4,lon:-121.0,order,notes:'',depth_ft:120});
const plan={spots:[spot('a',0),spot('b',1)],legs:[{from:'Morro Bay',to:'a',nm:6.2,minutes:25}],window:{depart:'06:30',return_by:'13:00',hours:[7,8,9]},exports:[]};

async function save(env,owner){
  const r=await worker.fetch(request('trips',{owner,method:'POST',body:{...alert,plan}}),env);assert.equal(r.status,201);return (await r.json()).id;
}
const snapshot=(sql,id)=>JSON.stringify(sql.prepare('SELECT region,plan,status,updated_at,launch_point,targets FROM trips WHERE id=?').get(id));

test('a retired-region trip: PATCH is a named 409 that writes nothing and logs no dependency failure; GET and DELETE still work',async()=>{
  const {sql,adapter,writes}=database(),env={DB:adapter},logged=[],original=console.error;
  console.error=(...a)=>{logged.push(a);};
  try{
    assert.equal(RETIRED_AREA,TEXT);
    const id=await save(env,'alice');
    sql.prepare('UPDATE trips SET region=? WHERE id=?').run('retired-region',id);
    const before=snapshot(sql,id);writes.length=0;
    const r=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,status:'done'}}),env);
    assert.equal(r.status,409);assert.equal((await r.json()).error,TEXT);
    assert.equal(snapshot(sql,id),before,'plan, status and updated_at are unchanged');
    assert.deepEqual(writes,[],'no D1 write happens on the 409');
    assert.ok(!logged.some(a=>JSON.stringify(a).includes('dependency')),'not logged as a dependency failure');
    const listed=await (await worker.fetch(request('trips',{owner:'alice'}),env)).json();
    assert.ok(listed.trips.some(t=>t.id===id),'GET still lists the trip');
    const del=await worker.fetch(request('trips',{owner:'alice',method:'DELETE',body:{id}}),env);
    assert.deepEqual(await del.json(),{deleted:true});assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM trips WHERE id=?').get(id).n,0);
  }finally{console.error=original;sql.close();}
});

test('a configured region still patches as before; unknown ids and another owner stay 404 (no 409 leak)',async()=>{
  const {sql,adapter}=database(),env={DB:adapter},original=console.error;
  console.error=()=>{};
  try{
    const id=await save(env,'alice'),other=await save(env,'bob');
    const ok=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,status:'done',plan:{...plan,spots:[spot('a',0)]}}}),env);
    assert.equal(ok.status,200);const out=await ok.json();assert.equal(out.status,'done');assert.equal(out.plan.spots.length,1);
    assert.equal(sql.prepare('SELECT status FROM trips WHERE id=?').get(id).status,'done');
    assert.equal((await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id:'missing'}}),env)).status,404);
    sql.prepare('UPDATE trips SET region=? WHERE id=?').run('retired-region',other);
    const foreign=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id:other,status:'done'}}),env);
    assert.equal(foreign.status,404,"another owner's retired trip is a plain 404");assert.equal((await foreign.json()).error,'Not found');
  }finally{console.error=original;sql.close();}
});

test('prototype-chain region names are a 409, not a TypeError',async()=>{
  const {sql,adapter,writes}=database(),env={DB:adapter},logged=[],original=console.error;
  console.error=(...a)=>{logged.push(a);};
  try{
    const id=await save(env,'alice');
    for(const bad of ['__proto__','constructor','toString']){
      sql.prepare('UPDATE trips SET region=? WHERE id=?').run(bad,id);const before=snapshot(sql,id);writes.length=0;
      const r=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,status:'done'}}),env);
      assert.equal(r.status,409,bad);assert.equal((await r.json()).error,TEXT,bad);
      assert.equal(snapshot(sql,id),before,bad);assert.deepEqual(writes,[],bad);
    }
    assert.deepEqual(logged,[],'no error log line at all');
  }finally{console.error=original;sql.close();}
});

// F04-14 / SCA-215: PATCH /api/trips refuses an edit that changes no supported field.
// Contract protected: same as PATCH /api/spots/:id - unknown, immutable (alert threshold, date, region...)
// and empty edits answer 400 and write nothing, so updated_at does not move; a supported edit still
// answers the stored plan fields and never touches the alert thresholds.
// Believable bug that fails this: filtering unknown keys out and still running the UPDATE, which
// answers 200 "saved" (and bumps updated_at) while the alert keeps judging the old threshold.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
globalThis.REGIONS={'morro-bay':read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT=read('../deployments/production.json');
import {withSessions} from './fixtures/test-sessions.mjs';
const {default:deployed}=await import('../server/index.ts');
const worker=withSessions(deployed);
const origin='https://skippercast.com';

function database(){
  const sql=new DatabaseSync(':memory:'),journal=read('../drizzle/meta/_journal.json');
  for(const {tag} of [...journal.entries].sort((a,b)=>a.idx-b.idx))sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`,import.meta.url),'utf8'));
  const writes=[];
  const adapter={prepare(query){let args=[];const statement=sql.prepare(query);return {bind(...a){args=a;return this;},async first(){return statement.get(...args)||null;},async all(){return {results:statement.all(...args)};},async run(){if(/^\s*UPDATE\s+trips\b/i.test(query))writes.push(query.slice(0,24));const info=statement.run(...args);return {meta:{changes:Number(info.changes)}};}};},async batch(queries){const result=[];for(const q of queries)result.push(await q.run());return result;}};
  return {sql,adapter,writes};
}
function request(owner,body,raw){
  return new Request(origin+'/api/trips',{method:'PATCH',headers:{'Content-Type':'application/json',Origin:origin,'x-test-owner':owner},body:raw??JSON.stringify(body)});
}
const day=24*60*60*1000;
const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles'}).format(new Date(Date.now()+day));
const alert={region:'morro-bay',point:'north',species:'reef',date,start_hour:7,end_hour:13,wind_limit:8,gust_limit:12,sea_limit:3};
const spot=(id,order)=>({id,name:'Spot '+id,lat:35.4,lon:-121.0,order,notes:'',depth_ft:120});
const plan={spots:[spot('a',0),spot('b',1)],legs:[{from:'Morro Bay',to:'a',nm:6.2,minutes:25}],window:{depart:'06:30',return_by:'13:00',hours:[7,8,9]},exports:[]};
const OLD='2026-01-01T00:00:00.000Z';

async function save(env,sql){
  const r=await worker.fetch(new Request(origin+'/api/trips',{method:'POST',headers:{'Content-Type':'application/json',Origin:origin,'x-test-owner':'alice'},body:JSON.stringify({...alert,plan})}),env);
  assert.equal(r.status,201);const {id}=await r.json();
  sql.prepare('UPDATE trips SET updated_at=? WHERE id=?').run(OLD,id);return id;
}
const snapshot=(sql,id)=>JSON.stringify(sql.prepare('SELECT * FROM trips WHERE id=?').get(id));

test('negative control: unknown, immutable, mixed and empty PATCH bodies are 400 and leave the row (updated_at included) untouched',async()=>{
  const {sql,adapter,writes}=database(),env={DB:adapter},original=console.error;
  console.error=()=>{};
  try{
    const id=await save(env,sql),before=snapshot(sql,id);writes.length=0;
    const bodies={
      'immutable wind_limit':{id,wind_limit:99},
      'immutable gust_limit':{id,gust_limit:99},
      'immutable sea_limit':{id,sea_limit:9},
      'immutable date':{id,date:'2030-01-01'},
      'immutable region':{id,region:'other'},
      'immutable species':{id,species:'halibut'},
      'unknown property':{id,bogus:true},
      'supported plus immutable (whole edit refused)':{id,status:'done',wind_limit:1},
      'empty edit (id only)':{id},
    };
    for(const [name,body] of Object.entries(bodies)){
      const r=await worker.fetch(request('alice',body),env);
      assert.equal(r.status,400,name);assert.ok(typeof (await r.json()).error==='string',name);
      assert.equal(snapshot(sql,id),before,name+': row unchanged, updated_at not bumped');
    }
    const proto=await worker.fetch(request('alice',null,`{"id":"${id}","__proto__":{"status":"done"}}`),env);
    assert.equal(proto.status,400,'__proto__ key is an unknown property');
    assert.equal(snapshot(sql,id),before);
    assert.deepEqual(writes,[],'no UPDATE trips ever ran');
  }finally{console.error=original;sql.close();}
});

test('positive control: a supported edit answers the stored plan fields, bumps updated_at and never changes the alert thresholds',async()=>{
  const {sql,adapter}=database(),env={DB:adapter};
  const id=await save(env,sql),alertColumns='wind_limit,gust_limit,sea_limit,date,start_hour,end_hour,region,species,point',alertBefore=JSON.stringify(sql.prepare(`SELECT ${alertColumns} FROM trips WHERE id=?`).get(id));
  const r=await worker.fetch(request('alice',{id,status:'done',plan:{...plan,spots:[spot('a',0)]}}),env);
  assert.equal(r.status,200);const out=await r.json(),stored=sql.prepare('SELECT * FROM trips WHERE id=?').get(id);
  assert.deepEqual(Object.keys(out).sort(),['id','launch_point','plan','status','targets']);
  assert.equal(out.status,'done');assert.equal(out.plan.spots.length,1);assert.equal(JSON.stringify(out.plan),stored.plan,'answer is the stored plan');
  assert.notEqual(stored.updated_at,OLD,'a real edit still bumps updated_at');
  assert.equal(JSON.stringify(sql.prepare(`SELECT ${alertColumns} FROM trips WHERE id=?`).get(id)),alertBefore,'alert thresholds unchanged');
  sql.close();
});

test('ownership and the retired-area answer come before body validation (no existence or area leak through the new 400)',async()=>{
  const {sql,adapter}=database(),env={DB:adapter},original=console.error;
  console.error=()=>{};
  try{
    const id=await save(env,sql);
    const foreign=await worker.fetch(request('bob',{id,wind_limit:99}),env);
    assert.equal(foreign.status,404);assert.equal((await foreign.json()).error,'Not found');
    assert.equal((await worker.fetch(request('alice',{id:'missing'}),env)).status,404);
    sql.prepare('UPDATE trips SET region=? WHERE id=?').run('retired-region',id);const before=snapshot(sql,id);
    const retired=await worker.fetch(request('alice',{id,wind_limit:99}),env);
    assert.equal(retired.status,409);assert.equal(snapshot(sql,id),before);
  }finally{console.error=original;sql.close();}
});

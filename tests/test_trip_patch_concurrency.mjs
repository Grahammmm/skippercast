// PATCH /api/trips persists only the planner fields the request sent, so a partial update
// cannot undo a concurrent update to another field, and the answer is the stored row.
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
const origin='https://skippercast.com',KEYS=['id','launch_point','plan','status','targets'];

function database(){
  const sql=new DatabaseSync(':memory:'),journal=read('../drizzle/meta/_journal.json'),writes=[],hooks=[];
  for(const {tag} of [...journal.entries].sort((a,b)=>a.idx-b.idx))sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`,import.meta.url),'utf8'));
  const adapter={prepare(query){let args=[];const statement=sql.prepare(query);return {bind(...a){args=a;return this;},
    async first(){const row=statement.get(...args)||null;if(/^SELECT \* FROM trips WHERE id=\? AND owner=\?/.test(query)&&hooks.length)await hooks.shift()();return row;},
    async all(){return {results:statement.all(...args)};},
    async run(){if(/^\s*UPDATE trips SET/i.test(query))writes.push(query);return {meta:{changes:Number(statement.run(...args).changes)}};}};},
    async batch(queries){const out=[];for(const q of queries)out.push(await q.run());return out;}};
  return {sql,adapter,writes,hooks};
}
const request=(owner,method,body)=>{const headers={'Content-Type':'application/json',Origin:origin};if(owner)headers['x-test-owner']=owner;
  return new Request(origin+'/api/trips',{method,headers,body:JSON.stringify(body)});};
const day=24*60*60*1000;
const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles'}).format(new Date(Date.now()+day));
const alert={region:'morro-bay',point:'north',species:'reef',date,start_hour:7,end_hour:13,wind_limit:8,gust_limit:12,sea_limit:3};
const spot=(id,order)=>({id,name:'Spot '+id,lat:35.4,lon:-121.0,order,notes:'',depth_ft:120});
const plan={spots:[spot('a',0),spot('b',1)],legs:[{from:'Morro Bay',to:'a',nm:6.2,minutes:25}],window:{depart:'06:30',return_by:'13:00',hours:[7,8,9]},exports:[]};
const other={...plan,spots:[spot('z',0)],legs:[]};

async function run(fn){
  const ctx=database(),env={DB:ctx.adapter},originalError=console.error,originalFetch=globalThis.fetch;
  console.error=()=>{};globalThis.fetch=()=>{throw new Error('network blocked');};
  const patch=(owner,body)=>worker.fetch(request(owner,'PATCH',body),env);
  const save=async(owner='alice',extra={})=>{const r=await worker.fetch(request(owner,'POST',{...alert,...extra}),env);assert.equal(r.status,201);return (await r.json()).id;};
  const row=id=>ctx.sql.prepare('SELECT * FROM trips WHERE id=?').get(id);
  try{await fn({...ctx,env,patch,save,row});}finally{console.error=originalError;globalThis.fetch=originalFetch;ctx.sql.close();}
}

test('a launch-only PATCH keeps a concurrent status change, and answers with the stored status',()=>run(async({hooks,patch,save,row})=>{
  const id=await save('alice',{launch_point:'south',targets:['reef'],plan});
  hooks.push(async()=>assert.equal((await patch('alice',{id,status:'done'})).status,200));
  const r=await patch('alice',{id,launch_point:'north'});
  assert.equal(r.status,200);const out=await r.json();
  assert.deepEqual(Object.keys(out).sort(),KEYS);assert.equal(out.launch_point,'north');assert.equal(out.status,'done');assert.deepEqual(out.plan,plan);
  const saved=row(id);assert.equal(saved.launch_point,'north');assert.equal(saved.status,'done');assert.deepEqual(JSON.parse(saved.plan),plan);
}));

test('a status-only PATCH keeps a concurrent launch point and the old plan and targets',()=>run(async({hooks,patch,save,row})=>{
  const id=await save('alice',{launch_point:'south',targets:['reef'],plan});
  hooks.push(async()=>assert.equal((await patch('alice',{id,launch_point:'north'})).status,200));
  const out=await (await patch('alice',{id,status:'cancelled'})).json();
  assert.equal(out.launch_point,'north');assert.equal(out.status,'cancelled');assert.deepEqual(out.plan,plan);assert.deepEqual(out.targets,['reef']);
  const saved=row(id);assert.equal(saved.launch_point,'north');assert.equal(saved.status,'cancelled');assert.deepEqual(JSON.parse(saved.plan),plan);
}));

test('targets-only and plan-only PATCHes do not erase each other, in either order',()=>run(async({hooks,patch,save,row})=>{
  const id=await save('alice',{targets:['reef'],plan});
  hooks.push(async()=>assert.equal((await patch('alice',{id,plan:other})).status,200));
  const first=await (await patch('alice',{id,targets:['reef']})).json();
  assert.deepEqual(first.plan,other);assert.deepEqual(first.targets,['reef']);
  hooks.push(async()=>assert.equal((await patch('alice',{id,targets:['reef']})).status,200));
  const second=await (await patch('alice',{id,plan})).json();
  assert.deepEqual(second.plan,plan);assert.deepEqual(JSON.parse(row(id).plan),plan);assert.deepEqual(JSON.parse(row(id).targets),['reef']);
}));

test('same-column concurrent writes stay last-writer-wins',()=>run(async({hooks,patch,save,row})=>{
  const id=await save();
  hooks.push(async()=>assert.equal((await patch('alice',{id,status:'done'})).status,200));
  assert.equal((await (await patch('alice',{id,status:'draft'})).json()).status,'draft');
  assert.equal(row(id).status,'draft');
}));

test('explicit null clears launch and plan; null targets and status take their defaults; a supplied plan replaces the whole plan',()=>run(async({patch,save,row})=>{
  const id=await save('alice',{launch_point:'south',targets:['reef'],plan,status:'done'});
  const replaced=await (await patch('alice',{id,plan:other})).json();
  assert.deepEqual(replaced.plan,other);assert.equal(replaced.launch_point,'south');assert.equal(replaced.status,'done');
  const out=await (await patch('alice',{id,launch_point:null,plan:null,targets:null,status:null})).json();
  assert.equal(out.launch_point,null);assert.equal(out.plan,null);assert.deepEqual(out.targets,['reef']);assert.equal(out.status,'planned');
  const saved=row(id);assert.equal(saved.launch_point,null);assert.equal(saved.plan,null);assert.equal(saved.status,'planned');
}));

test('an id-only or ignored-field PATCH leaves every planner and alert column alone, even a concurrent change',()=>run(async({hooks,patch,save,row})=>{
  const id=await save('alice',{launch_point:'south',plan});
  const before=row(id);
  hooks.push(async()=>assert.equal((await patch('alice',{id,status:'done'})).status,200));
  const out=await (await patch('alice',{id,date:'2000-01-01',region:'x',owner:'bob',species:'lingcod',boat_name:'x',wind_limit:99})).json();
  assert.equal(out.status,'done');assert.equal(out.launch_point,'south');assert.deepEqual(Object.keys(out).sort(),KEYS);
  const after=row(id);
  for(const k of ['owner','region','point','species','date','start_hour','end_hour','wind_limit','gust_limit','sea_limit','boat_name','plan','launch_point','targets'])assert.equal(after[k],before[k],k);
  assert.equal(after.status,'done');
  assert.equal((await patch('alice',{id})).status,200);assert.equal(row(id).status,'done');
}));

test('a malformed supplied field is a 400 before any trip UPDATE; bad ids, missing, foreign rows and anonymous callers are refused',()=>run(async({patch,save,writes,row,env})=>{
  const id=await save(),before=row(id);
  for(const bad of [{status:'nope'},{launch_point:'Bad Slug'},{targets:['not-a-species']},{plan:{spots:'x'}}])assert.equal((await patch('alice',{id,...bad})).status,400,JSON.stringify(bad));
  for(const bad of ['',null,5,'x'.repeat(65)])assert.equal((await patch('alice',{id:bad})).status,400);
  assert.equal((await patch('alice',{id:'missing',status:'done'})).status,404);
  assert.equal((await patch('bob',{id,status:'done'})).status,404);
  assert.equal((await worker.fetch(request(null,'PATCH',{id,status:'done'}),env)).status,401);
  assert.deepEqual(writes,[]);assert.deepEqual(row(id),before);
}));

test('a retired region is still a 409 and a trip deleted between read and write is a 404, not a success',()=>run(async({hooks,sql,patch,save,row,writes})=>{
  const id=await save(),gone=await save();
  sql.prepare('UPDATE trips SET region=? WHERE id=?').run('retired-region',id);
  assert.equal((await patch('alice',{id,status:'done'})).status,409);assert.deepEqual(writes,[]);
  hooks.push(async()=>sql.prepare('DELETE FROM trips WHERE id=?').run(gone));
  const r=await patch('alice',{id:gone,status:'done'});
  assert.equal(r.status,404);assert.equal((await r.json()).error,'Not found');assert.equal(row(gone),undefined);
}));

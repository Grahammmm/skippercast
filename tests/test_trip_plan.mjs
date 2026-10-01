// The planned trip (migration 0005): launch point, targets, spots, legs, window,
// exports and status ride on the saved trip, validated server-side, patched
// without touching the alert fields, and returned parsed.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
globalThis.REGIONS={'morro-bay':read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT=read('../deployments/production.json');
import {withSessions} from './fixtures/test-sessions.mjs';
const {default:deployed,validateTripPlan,PLAN_LIMITS}=await import('../server/index.ts');
const worker=withSessions(deployed);
const region=globalThis.REGIONS['morro-bay'];

function database(){
  const sql=new DatabaseSync(':memory:'),journal=read('../drizzle/meta/_journal.json');
  for(const {tag} of [...journal.entries].sort((a,b)=>a.idx-b.idx))sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`,import.meta.url),'utf8'));
  const adapter={prepare(query){let args=[];const statement=sql.prepare(query);return {bind(...a){args=a;return this;},async first(){return statement.get(...args)||null;},async all(){return {results:statement.all(...args)};},async run(){const info=statement.run(...args);return {meta:{changes:Number(info.changes)}};}};},async batch(queries){sql.exec('BEGIN');try{const result=[];for(const q of queries)result.push(await q.run());sql.exec('COMMIT');return result;}catch(e){sql.exec('ROLLBACK');throw e;}}};return {sql,adapter};
}
const origin='https://skippercast.com';
function request(path,{owner,method='GET',body}={}){
  const headers={'Content-Type':'application/json'};if(owner)headers['x-test-owner']=owner;if(method!=='GET')headers.Origin=origin;
  return new Request(origin+'/api/'+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});
}
const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles'}).format(new Date(Date.now()+86400000));
const alert={region:'morro-bay',point:'north',species:'reef',date,start_hour:7,end_hour:13,wind_limit:8,gust_limit:12,sea_limit:3};
const spot=(id,order)=>({id,name:'Spot '+id,lat:35.4,lon:-121.0,order,notes:'',depth_ft:120});
const plan={spots:[spot('a',0),spot('b',1)],legs:[{from:'Morro Bay',to:'a',nm:6.2,minutes:25},{from:'a',to:'b',nm:2,minutes:9}],window:{depart:'06:30',return_by:'13:00',hours:[7,8,9,10,11,12]},exports:[{format:'gpx',sha256:'a'.repeat(64),exported_at:'2026-09-30T14:00:00Z'}]};

const maximalBody=()=>({targets:['reef','halibut','salmon'],plan:{spots:Array.from({length:PLAN_LIMITS.spots},(_,i)=>({...spot('s'+i,i),name:'n'.repeat(80),notes:'m'.repeat(280)})),legs:Array.from({length:PLAN_LIMITS.legs},()=>({from:'f'.repeat(80),to:'t'.repeat(80),nm:123.45678,minutes:1234})),window:{depart:'06:00',return_by:'15:00',hours:Array.from({length:24},(_,i)=>i)},exports:Array.from({length:PLAN_LIMITS.exports},()=>({format:'navionics',sha256:'f'.repeat(64),exported_at:'2026-09-30T14:00:00Z'}))}});
test('validateTripPlan: defaults, the primary target first, limits and rejections',()=>{
  assert.deepEqual(validateTripPlan({},region,'reef'),{launch_point:null,targets:['reef'],plan:null,status:'planned'});
  const full=validateTripPlan({launch_point:'morro-bay-launch-ramp',targets:['halibut','reef'],plan,status:'draft'},region,'reef');
  assert.deepEqual(full.targets,['reef','halibut'],'the alert species stays the primary target');
  assert.equal(full.plan.spots.length,2);assert.equal(full.plan.window.depart,'06:30');assert.equal(full.plan.exports[0].exported_at,'2026-09-30T14:00:00.000Z');
  for(const bad of [
    {launch_point:'Morro Bay'},{launch_point:'x'.repeat(65)},
    {targets:[]},{targets:['reef','halibut','salmon','albacore']},{targets:['marlin']},{targets:'reef'},
    {targets:['halibut','halibut']},{targets:['halibut','salmon','albacore']},
    {plan:{spots:[{...spot('a',0),order:-1}]}},{plan:{spots:[{...spot('a',0),order:1.5}]}},
    {status:'wishful'},
    {plan:{spots:Array.from({length:PLAN_LIMITS.spots+1},(_,i)=>spot('s'+i,i))}},
    {plan:{spots:[{...spot('a',0),lat:91}]}},{plan:{spots:[{...spot('a',0),id:'A B'}]}},
    {plan:{legs:[{from:'x',to:'y',nm:-1,minutes:5}]}},
    {plan:{window:{depart:'6:30'}}},{plan:{window:{hours:[24]}}},
    {plan:{exports:[{format:'kml',sha256:'a'.repeat(64),exported_at:'2026-09-30T14:00:00Z'}]}},
    {plan:{exports:[{format:'gpx',sha256:'nope',exported_at:'2026-09-30T14:00:00Z'}]}},
    {plan:[]},
  ])assert.throws(()=>validateTripPlan(bad,region,'reef'),new RegExp('.'),JSON.stringify(bad).slice(0,80));
  assert.deepEqual(validateTripPlan({targets:['halibut','salmon']},region,'reef').targets,['reef','halibut','salmon'],'two others plus the alert species fit');
  // The joint maxima fit under the body cap, so the documented limits are reachable.
  const maximal={launch_point:'x',...maximalBody()};
  assert.ok(JSON.stringify({...alert,...maximal}).length<PLAN_LIMITS.body,'a maximal plan fits the request cap');
  assert.ok(JSON.stringify(validateTripPlan(maximal,region,'reef').plan).length<=PLAN_LIMITS.bytes);
  const long=validateTripPlan({plan:{spots:[{...spot('a',0),notes:'n'.repeat(400),name:'m'.repeat(400)}]}},region,'reef');
  assert.equal(long.plan.spots[0].notes.length,280);assert.equal(long.plan.spots[0].name.length,80);
});

test('POST saves the plan, PATCH changes it without touching the alert, GET returns it parsed',async()=>{
  const {sql,adapter}=database(),env={DB:adapter};
  try{
    const created=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:{...alert,launch_point:'morro-bay-launch-ramp',targets:['reef','halibut'],plan}}),env);
    assert.equal(created.status,201);const {id}=await created.json();
    const row=sql.prepare('SELECT launch_point,targets,plan,status,updated_at FROM trips WHERE id=?').get(id);
    assert.equal(row.launch_point,'morro-bay-launch-ramp');assert.deepEqual(JSON.parse(row.targets),['reef','halibut']);assert.equal(row.status,'planned');assert.ok(row.updated_at);
    const listed=(await (await worker.fetch(request('trips',{owner:'alice'}),env)).json()).trips[0];
    assert.deepEqual(listed.targets,['reef','halibut']);assert.equal(listed.plan.legs.length,2,'plan comes back parsed');
    // A one-tap save from the Tomorrow card carries no plan at all.
    const bare=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:alert}),env);assert.equal(bare.status,201);const bareId=(await bare.json()).id;
    const bareRow=(await (await worker.fetch(request('trips',{owner:'alice'}),env)).json()).trips.find(t=>t.id===bareId);
    assert.deepEqual([bareRow.launch_point,bareRow.targets,bareRow.plan,bareRow.status],[null,['reef'],null,'planned']);
    // PATCH: only the given fields change; the alert fields are untouched.
    const patched=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,status:'done',plan:{...plan,spots:[spot('a',0)]}}}),env);
    assert.equal(patched.status,200);const out=await patched.json();
    assert.equal(out.status,'done');assert.equal(out.plan.spots.length,1);assert.deepEqual(out.targets,['reef','halibut'],'targets kept');assert.equal(out.launch_point,'morro-bay-launch-ramp');
    const after=sql.prepare('SELECT wind_limit,start_hour,status FROM trips WHERE id=?').get(id);assert.deepEqual([after.wind_limit,after.start_hour,after.status],[8,7,'done']);
    assert.equal((await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,targets:['marlin']}}),env)).status,400);
    const big=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,...maximalBody()}}),env);assert.equal(big.status,200,'the documented maxima are accepted over the wire: '+JSON.stringify(await big.clone().json()).slice(0,100));
    assert.equal((await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,plan:{spots:[{...spot('a',0),notes:'n'.repeat(40000)}]}}}),env)).status,400,'an oversized body is refused');
    assert.equal((await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id:'missing'}}),env)).status,404);
    assert.equal((await worker.fetch(request('trips',{owner:'bob',method:'PATCH',body:{id,status:'cancelled'}}),env)).status,404,'another owner cannot touch it');
    assert.equal(sql.prepare('SELECT status FROM trips WHERE id=?').get(id).status,'done');
    const exported=await(await worker.fetch(request('privacy',{owner:'alice'}),env)).json();
    assert.ok(exported.trips.some(t=>t.launch_point==='morro-bay-launch-ramp'),'the account export carries the plan');
    await worker.fetch(request('trips',{owner:'alice',method:'DELETE',body:{id}}),env);assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM trips').get().n,1);
  }finally{sql.close();}
});

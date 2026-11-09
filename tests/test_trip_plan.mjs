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

const BAD_IDS=[123,0,true,false,null,['reef-a'],[['reef-a']],[],{},{toString:null}];
const badPlans=()=>[...BAD_IDS.map(id=>({...spot('x',0),id})),(()=>{const s=spot('x',0);delete s.id;return s;})()];

test('trip_spot_id_requires_string',()=>{
  for(const bad of badPlans())assert.throws(()=>validateTripPlan({plan:{spots:[bad]}},region,'reef'),e=>e.message==='invalid spot id'&&e.constructor.name==='ClientError',JSON.stringify(bad.id));
});

test('trip_spot_id_string_boundaries_unchanged',()=>{
  for(const id of ['a','0','123','true','null','undefined','a'.repeat(64)])assert.equal(validateTripPlan({plan:{spots:[spot(id,0)]}},region,'reef').plan.spots[0].id,id);
  for(const id of ['','a'.repeat(65),'Reef','a b','a_b','a/b'])assert.throws(()=>validateTripPlan({plan:{spots:[spot(id,0)]}},region,'reef'),/invalid spot id/,id);
});

test('trip_post_and_patch_nonstring_spot_id_never_write',async()=>{
  const {sql,adapter}=database(),env={DB:adapter};
  const snap=id=>JSON.stringify(sql.prepare('SELECT * FROM trips WHERE id=?').get(id));
  const count=()=>sql.prepare('SELECT COUNT(*) AS n FROM trips').get().n;
  try{
    const created=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:{...alert,plan}}),env);
    assert.equal(created.status,201);const {id}=await created.json();
    const before=snap(id);
    for(const bad of badPlans()){
      const post=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:{...alert,plan:{spots:[spot('ok',0),bad]}}}),env);
      assert.equal(post.status,400,'POST '+JSON.stringify(bad.id));assert.equal((await post.json()).error,'invalid spot id');
      const patch=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,status:'done',plan:{spots:[bad]}}}),env);
      assert.equal(patch.status,400,'PATCH '+JSON.stringify(bad.id));assert.equal((await patch.json()).error,'invalid spot id');
    }
    assert.equal(count(),1,'no trip row was inserted');
    assert.equal(snap(id),before,'the stored trip row is byte-identical');
  }finally{sql.close();}
});

test('trip_spot_string_roundtrip_and_owner_boundary',async()=>{
  const {sql,adapter}=database(),env={DB:adapter};
  try{
    const created=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:{...alert,plan:{spots:[spot('123',0)]}}}),env);
    assert.equal(created.status,201);const {id}=await created.json();
    const patched=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,plan:{spots:[spot('true',0)]}}}),env);
    assert.equal(patched.status,200);assert.equal((await patched.json()).plan.spots[0].id,'true');
    const listed=(await (await worker.fetch(request('trips',{owner:'alice'}),env)).json()).trips[0];assert.equal(listed.plan.spots[0].id,'true');
    const bad={plan:{spots:[{...spot('x',0),id:123}]}};
    assert.equal((await worker.fetch(request('trips',{owner:'bob',method:'PATCH',body:{id,...bad}}),env)).status,404,'foreign id is 404 before plan validation');
    assert.equal((await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id:'missing',...bad}}),env)).status,404);
    assert.notEqual((await worker.fetch(request('trips',{method:'POST',body:{...alert,plan}}),env)).status,201,'anonymous writes are refused');
    assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM trips').get().n,1);
  }finally{sql.close();}
});

const HEX='b'.repeat(64);
const exp=sha256=>({format:'gpx',sha256,exported_at:'2026-09-30T14:00:00Z'});
const BAD_HASHES=[undefined,null,123,0,true,false,[],[HEX],[[HEX]],{},{toString:null}];
const withExport=e=>({exports:[e]});

test('trip_export_hash_requires_string',()=>{
  const missing=exp(HEX);delete missing.sha256;
  for(const e of [missing,...BAD_HASHES.map(exp)])assert.throws(()=>validateTripPlan({plan:withExport(e)},region,'reef'),x=>x.message==='invalid export'&&x.constructor.name==='ClientError',JSON.stringify(e.sha256));
});

test('trip_export_hash_string_grammar_unchanged',()=>{
  for(const h of [HEX,'0'.repeat(64)])assert.equal(validateTripPlan({plan:withExport(exp(h))},region,'reef').plan.exports[0].sha256,h);
  for(const h of ['','b'.repeat(63),'b'.repeat(65),'B'.repeat(64),' '+HEX,HEX+' ',HEX+'\n','z'.repeat(64)])assert.throws(()=>validateTripPlan({plan:withExport(exp(h))},region,'reef'),/invalid export/,JSON.stringify(h));
});

test('trip_post_and_patch_bad_export_hash_never_write',async()=>{
  const {sql,adapter}=database(),env={DB:adapter};
  const snap=id=>JSON.stringify(sql.prepare('SELECT * FROM trips WHERE id=?').get(id));
  const count=()=>sql.prepare('SELECT COUNT(*) AS n FROM trips').get().n;
  try{
    const created=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:{...alert,plan}}),env);
    assert.equal(created.status,201);const {id}=await created.json();
    const before=snap(id);
    for(const h of BAD_HASHES){
      const later={...plan,exports:[exp(HEX),exp(h)]};
      const post=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:{...alert,plan:later}}),env);
      assert.equal(post.status,400,'POST '+JSON.stringify(h));const pb=await post.json();assert.equal(pb.error,'invalid export');
      const patch=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,status:'done',plan:later}}),env);
      assert.equal(patch.status,400,'PATCH '+JSON.stringify(h));assert.equal((await patch.json()).error,'invalid export');
    }
    assert.equal(count(),1,'no trip row was inserted');
    assert.equal(snap(id),before,'the stored trip row is byte-identical');
    const bad={plan:withExport(exp([HEX]))};
    assert.equal((await worker.fetch(request('trips',{owner:'bob',method:'PATCH',body:{id,...bad}}),env)).status,404,'foreign id is 404 before export validation');
    assert.equal((await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id:'missing',...bad}}),env)).status,404);
    assert.equal(snap(id),before);
  }finally{sql.close();}
});

test('trip_export_hash_string_roundtrip_and_repair',async()=>{
  const {sql,adapter}=database(),env={DB:adapter};
  try{
    const created=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:{...alert,plan:{...plan,exports:[exp('0'.repeat(64))]}}}),env);
    assert.equal(created.status,201);const {id}=await created.json();
    const patched=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,plan:{...plan,exports:[exp(HEX)]}}}),env);
    assert.equal(patched.status,200);assert.equal((await patched.json()).plan.exports[0].sha256,HEX);
    assert.equal((await (await worker.fetch(request('trips',{owner:'alice'}),env)).json()).trips[0].plan.exports[0].sha256,HEX);
    assert.equal(JSON.parse(sql.prepare('SELECT plan FROM trips WHERE id=?').get(id).plan).exports[0].sha256,HEX);
    sql.prepare('UPDATE trips SET plan=? WHERE id=?').run(JSON.stringify({...plan,exports:[exp([HEX])]}),id);
    const repaired=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,plan:{...plan,exports:[exp(HEX)]}}}),env);
    assert.equal(repaired.status,200);assert.equal(JSON.parse(sql.prepare('SELECT plan FROM trips WHERE id=?').get(id).plan).exports[0].sha256,HEX);
    sql.prepare('UPDATE trips SET plan=? WHERE id=?').run(JSON.stringify({...plan,exports:[exp([HEX])]}),id);
    assert.equal((await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,plan:null}}),env)).status,200);
    assert.equal(sql.prepare('SELECT plan FROM trips WHERE id=?').get(id).plan,null);
  }finally{sql.close();}
});

// RF0824-5: the 16,384-byte plan cap is measured in UTF-8 bytes of the normalized JSON.
const planBytes=p=>Buffer.byteLength(JSON.stringify(p));
const cjkPlan=()=>({spots:Array.from({length:PLAN_LIMITS.spots},(_,i)=>({...spot('s'+i,i),name:'海'.repeat(80),notes:'海'.repeat(280)})),legs:Array.from({length:PLAN_LIMITS.legs},()=>({from:'海'.repeat(80),to:'海'.repeat(80),nm:1,minutes:1})),window:{depart:null,return_by:null,hours:[]},exports:[]});
// A legal plan whose normalized JSON is exactly `target` bytes, with quotes, backslashes and multibyte text.
function planOfBytes(target){
  const p=cjkPlan();p.spots[0].notes='"\\'+'é'.repeat(20)+p.spots[0].notes.slice(0,200);
  while(planBytes(p)>target){const s=p.spots.reduce((a,b)=>b.notes.length>a.notes.length?b:a);s.notes=s.notes.slice(0,-1);}
  while(planBytes(p)<target){const s=p.spots.find(x=>x.notes.length<280);s.notes+='a';}
  assert.equal(planBytes(p),target,'fixture is exactly the target size');return p;
}
const bigRequest=plan=>({...alert,plan});
test('trip_plan_utf8_not_utf16',()=>{
  const cjk=cjkPlan();assert.ok(planBytes(cjk)>PLAN_LIMITS.bytes&&JSON.stringify(cjk).length<=PLAN_LIMITS.bytes,'fixture exceeds in bytes only');
  assert.ok(Buffer.byteLength(JSON.stringify(bigRequest(cjk)))<PLAN_LIMITS.body);
  assert.throws(()=>validateTripPlan({plan:cjk},region,'reef'),{message:'plan too large'});
  const twin=JSON.parse(JSON.stringify(cjk).replaceAll('海','a'));
  assert.ok(planBytes(twin)<=PLAN_LIMITS.bytes);assert.ok(validateTripPlan({plan:twin},region,'reef').plan);
  const small=validateTripPlan({plan:{...plan,spots:[{...spot('a',0),name:'Café 🎣',notes:'海 é'}]}},region,'reef').plan.spots[0];
  assert.equal(small.name,'Café 🎣');assert.equal(small.notes,'海 é');
});
test('trip_plan_exact_normalized_byte_boundary',()=>{
  for(const [delta,ok] of [[-1,true],[0,true],[1,false]]){
    const p=planOfBytes(PLAN_LIMITS.bytes+delta);
    if(ok)assert.equal(planBytes(validateTripPlan({plan:p},region,'reef').plan),PLAN_LIMITS.bytes+delta);
    else assert.throws(()=>validateTripPlan({plan:p},region,'reef'),{message:'plan too large'});
  }
});
test('trip_plan_size_after_normalization',()=>{
  const raw={spots:[{...spot('a',0),notes:'海'.repeat(5000),name:'  x  '}]};
  assert.ok(Buffer.byteLength(JSON.stringify(bigRequest(raw)))<PLAN_LIMITS.body);
  const got=validateTripPlan({plan:raw},region,'reef').plan;assert.equal(got.spots[0].notes.length,280);assert.equal(got.spots[0].name,'x');
  assert.equal(validateTripPlan({},region,'reef').plan,null);assert.equal(validateTripPlan({plan:null},region,'reef').plan,null);
});
test('trip_post_patch_utf8_overflow_never_write',async()=>{
  const {sql,adapter}=database(),env={DB:adapter};
  const snap=id=>JSON.stringify(sql.prepare('SELECT * FROM trips WHERE id=?').get(id));
  const count=()=>sql.prepare('SELECT COUNT(*) AS n FROM trips').get().n;
  try{
    const created=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:{...alert,plan}}),env);
    assert.equal(created.status,201);const {id}=await created.json();
    sql.prepare('UPDATE trips SET updated_at=? WHERE id=?').run('2020-01-01T00:00:00.000Z',id);
    const before=snap(id),cjk=cjkPlan();
    assert.ok(Buffer.byteLength(JSON.stringify(bigRequest(cjk)))<PLAN_LIMITS.body);
    const post=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:bigRequest(cjk)}),env);
    assert.equal(post.status,400);assert.equal((await post.json()).error,'plan too large');
    const patch=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,status:'done',plan:cjk}}),env);
    assert.equal(patch.status,400);assert.equal((await patch.json()).error,'plan too large');
    assert.equal(count(),1,'no trip row was inserted');assert.equal(snap(id),before,'the stored row, updated_at included, is unchanged');
    const ok=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,plan:planOfBytes(PLAN_LIMITS.bytes)}}),env);assert.equal(ok.status,200);
    const again=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:bigRequest(plan)}),env);assert.equal(again.status,201);
  }finally{sql.close();}
});
test('trip_utf8_cap_preserves_owner_and_body_limits',async()=>{
  const {sql,adapter}=database(),env={DB:adapter};
  try{
    const cjk=cjkPlan();
    for(const id of ['missing-id','00000000-0000-4000-8000-000000000000']){
      const r=await worker.fetch(request('trips',{owner:'alice',method:'PATCH',body:{id,plan:cjk}}),env);assert.equal(r.status,404);
    }
    const anon=await worker.fetch(request('trips',{method:'POST',body:bigRequest(plan)}),env);assert.ok(anon.status===401||anon.status===403,'anonymous cannot save: '+anon.status);
    const huge=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:{...bigRequest(plan),pad:'海'.repeat(9000)}}),env);
    assert.ok(huge.status===413||huge.status===400,'over-body request refused: '+huge.status);assert.notEqual((await huge.json()).error,'plan too large');
    assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM trips').get().n,0);
  }finally{sql.close();}
});

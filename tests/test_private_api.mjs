import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {assessTrip,alertDecision} from '../server/alert-policy.js';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
globalThis.REGIONS={'morro-bay':read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT=read('../deployments/production.json');
const {default:worker,validateSubscription,checkTrips}=await import('../server/worker.js');

function database(){
  const sql=new DatabaseSync(':memory:');sql.exec(readFileSync(new URL('../drizzle/0000_spicy_kinsey_walden.sql',import.meta.url),'utf8'));
  const adapter={prepare(query){let args=[];const statement=sql.prepare(query);return {bind(...a){args=a;return this;},async first(){return statement.get(...args)||null;},async all(){return {results:statement.all(...args)};},async run(){const info=statement.run(...args);return {meta:{changes:Number(info.changes)}};}};},async batch(queries){sql.exec('BEGIN');try{const result=[];for(const q of queries)result.push(await q.run());sql.exec('COMMIT');return result;}catch(e){sql.exec('ROLLBACK');throw e;}}};return {sql,adapter};
}
const origin='https://skippercast.com';
function request(path,{owner,method='GET',body,requestOrigin=origin}={}){
  const headers={'Content-Type':'application/json'};if(owner){headers['oai-authenticated-user-id']=owner;headers['oai-authenticated-user-email']=owner+'@example.test';}if(method!=='GET')headers.Origin=requestOrigin;
  return new Request(origin+'/api/'+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});
}
test('private API denies anonymous access, enforces owner isolation and supports complete deletion',async()=>{
  const {sql,adapter}=database(),env={DB:adapter};
  assert.equal((await worker.fetch(request('trips'),env)).status,401);
  const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles'}).format(new Date(Date.now()+86400000));
  const trip={region:'morro-bay',point:'north',species:'reef',date,start_hour:7,end_hour:13,wind_limit:8,gust_limit:12,sea_limit:3};
  assert.equal((await worker.fetch(request('trips',{owner:'alice',method:'POST',body:trip,requestOrigin:'https://attacker.test'}),env)).status,400);
  const response=await worker.fetch(request('trips',{owner:'alice',method:'POST',body:trip}),env);assert.equal(response.status,201);const {id}=await response.json();
  assert.equal((await (await worker.fetch(request('trips',{owner:'bob'}),env)).json()).trips.length,0);
  await worker.fetch(request('trips',{owner:'bob',method:'DELETE',body:{id}}),env);assert.ok(sql.prepare('SELECT id FROM trips').get());
  await worker.fetch(request('comfort',{owner:'alice',method:'POST',body:{region:'morro-bay',rating:8,phase:'fishing',point:'north',wind:4,sea:2}}),env);
  const exported=await(await worker.fetch(request('privacy',{owner:'alice'}),env)).json();assert.equal(exported.trips.length,1);assert.equal(exported.feedback.length,1);
  await worker.fetch(request('privacy',{owner:'alice',method:'DELETE',body:{}}),env);assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM trips').get().n,0);assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM comfort_feedback').get().n,0);
  assert.equal((await worker.fetch(request('jobs/check',{method:'POST',body:{}}),env)).status,401);
  sql.close();
});
test('push subscriptions cannot turn the sender into an arbitrary URL fetcher',()=>{
  const keys={p256dh:'a'.repeat(87),auth:'b'.repeat(22)};
  assert.ok(validateSubscription({endpoint:'https://web.push.apple.com/test-endpoint',keys}));
  for(const endpoint of ['http://fcm.googleapis.com/path','https://127.0.0.1/','https://fcm.googleapis.com.attacker.test/','https://web.push.apple.com:444/','https://user:password@web.push.apple.com/'])assert.throws(()=>validateSubscription({endpoint,keys}));
});
test('public feed requests use edge-compatible redirect handling and reject redirected data',async()=>{
  const originalFetch=globalThis.fetch,originalCaches=globalThis.caches;let calls=0;
  try{
    globalThis.caches={get default(){throw Error('default cache forbidden');},async open(name){assert.equal(name,'skippercast-public-feeds-v1');throw Error('optional cache unavailable');}};
    globalThis.fetch=async(url,options)=>{calls++;assert.equal(options.redirect,'manual');return Response.json({region_id:'morro-bay',sources:{},forecast:{points:{north:{}}}});};
    const result=await worker.fetch(request('forecast?region=morro-bay'),{});
    assert.equal(result.status,200);assert.deepEqual(await result.json(),{points:{north:{}}});
    globalThis.fetch=async(url,options)=>{calls++;assert.equal(options.redirect,'manual');return new Response(null,{status:302,headers:{Location:'https://untrusted.example/feed'}});};
    assert.equal((await worker.fetch(request('intelligence?region=morro-bay'),{})).status,503);
    assert.equal(calls,2,'a redirect must not cause another fetch');
  }finally{globalThis.fetch=originalFetch;globalThis.caches=originalCaches;}
});
test('public habitat endpoint is region-pinned and rejects a cross-region product',async()=>{
  const original=globalThis.fetch;let calls=0;
  try{
    globalThis.fetch=async url=>{calls++;assert.equal(url,REGIONS['morro-bay'].habitat_feed);return Response.json({schema_version:1,region_id:'morro-bay',layers:{}});};
    assert.equal((await worker.fetch(request('habitat?region=morro-bay'),{})).status,200);
    assert.equal((await worker.fetch(request('habitat?region=https://attacker.test'),{})).status,404);assert.equal(calls,1);
    globalThis.fetch=async()=>Response.json({schema_version:1,region_id:'southern-california',layers:{}});
    assert.equal((await worker.fetch(request('habitat?region=morro-bay'),{})).status,503);
  }finally{globalThis.fetch=original;}
});
test('outbox produces one in-app event for repeated checks and does not silently skip a missed final',async()=>{
  const {sql,adapter}=database(),env={DB:adapter};const originalFetch=globalThis.fetch;
  const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles'}).format(new Date(Date.now()+2*86400000));
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)').run('trip-1','alice','morro-bay','north','reef',date,7,13,8,12,3,new Date().toISOString());
  globalThis.fetch=async()=>Response.json({}, {status:503});
  try{
    const first=await checkTrips(env);assert.equal(first.changes,1);assert.equal(first.in_app,1);
    const second=await checkTrips(env);assert.equal(second.changes,0);assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM alert_events').get().n,1);
    sql.prepare('UPDATE trips SET date=?').run('2026-01-01');const missed=await checkTrips(env);assert.equal(missed.changes,1);
    assert.equal(sql.prepare("SELECT kind FROM alert_events WHERE kind='missed-final'").get().kind,'missed-final');
  }finally{globalThis.fetch=originalFetch;sql.close();}
});
test('alert changes and source loss retract prior threshold fit; final is mandatory even when unchanged',()=>{
  const a={status:'within limits',issues:[],values:{wind:4,gust:6,sea:2,chop:.5}};
  assert.equal(alertDecision(a,a),null);assert.equal(alertDecision(a,a,{final:true}),'final');
  assert.equal(alertDecision(a,{...a,status:'unverified',issues:['source stale']}),'retraction');
  const result=assessTrip({point:'north'},REGIONS['morro-bay'],null,null,null);
  assert.notEqual(result.status,'within limits');
});

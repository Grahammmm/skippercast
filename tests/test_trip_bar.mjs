// SC0922-02: the production checkTrip/checkOwnerTrips path with a memory database, injected fetch and a fixed clock:
// a harbour-bar hazard note appears, changes, clears and degrades to "not judged" as one update each, from the feeds the checker already reads.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {feedBucket} from './fixtures/feed-bucket.mjs';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
const region=read('../regions/morro-bay/region.json');
globalThis.REGIONS={'morro-bay':region};
globalThis.DEPLOYMENT=read('../deployments/production.json');
const {checkOwnerTrips}=await import('../server/trips.ts');
const {useBucket}=await import('../server/feeds.ts');
const {windowInstants}=await import('../server/alert-policy.ts');
const {hash}=await import('../server/http.ts');
const {BAR_CHECK}=await import('../packages/coast/src/bar-conditions.ts');

function database(){
  const sql=new DatabaseSync(':memory:'),journal=read('../drizzle/meta/_journal.json');
  for(const {tag} of [...journal.entries].sort((a,b)=>a.idx-b.idx))sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`,import.meta.url),'utf8'));
  const adapter={prepare(query){let args=[];const statement=sql.prepare(query);return {bind(...a){args=a;return this;},async first(){return statement.get(...args)||null;},async all(){return {results:statement.all(...args)};},async run(){const info=statement.run(...args);return {meta:{changes:Number(info.changes)}};}};},async batch(queries){sql.exec('BEGIN');try{const result=[];for(const q of queries)result.push(await q.run());sql.exec('COMMIT');return result;}catch(e){sql.exec('ROLLBACK');throw e;}}};
  return {sql,adapter};
}
const b64url=bytes=>Buffer.from(bytes).toString('base64url');
async function pushKeys(){
  const client=await crypto.subtle.generateKey({name:'ECDH',namedCurve:'P-256'},true,['deriveBits']);
  return {p256dh:b64url(new Uint8Array(await crypto.subtle.exportKey('raw',client.publicKey))),auth:b64url(crypto.getRandomValues(new Uint8Array(16)))};
}
async function vapid(){
  const pair=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
  return {VAPID_PUBLIC_KEY:b64url(new Uint8Array(await crypto.subtle.exportKey('raw',pair.publicKey))),VAPID_PRIVATE_KEY:(await crypto.subtle.exportKey('jwk',pair.privateKey)).d};
}
const ZONE=region.timezone,DAY='2026-11-12',PUSH='https://fcm.googleapis.com/fcm/send/sub-',HOUR=3600000;
// 2026-11-11 12:00 PST: the trip is tomorrow and the day-before final (18:00) is not yet due.
const T0=Date.parse('2026-11-11T20:00:00Z');
const rules={valid_from:'2026-01-01',valid_through:'2026-12-31',species:Object.fromEntries(['lingcod','rockfish'].map(id=>[id,{source_ids:[],windows:[{start:'2026-01-01',end:'2026-12-31'}]}]))};
// High 06:00 and low 14:00 PST on the trip day: mid-ebb is 08:00 to 12:00.
const TIDES=[['2026-11-11T22:00:00-08:00','L'],[DAY+'T06:00:00-08:00','H'],[DAY+'T14:00:00-08:00','L'],[DAY+'T22:00:00-08:00','H']].map(([time,type])=>({time,type,height_ft:type==='H'?5:.5}));
// `sea` maps a local hour to a GFS-Wave [height ft, period s] (other hours stay calm at 2 ft / 10 s).
function intelligence(nowMs,sea={}){
  const time=windowInstants(DAY,ZONE,0,23),models={},sources={};
  const local=new Map(time.map(e=>[e,Number(new Intl.DateTimeFormat('en-US',{timeZone:ZONE,hour:'2-digit',hourCycle:'h23'}).format(new Date(e*1000)))]));
  for(const id of ['gfs_global','ecmwf_ifs025','ncep_gfswave016','ecmwf_wam']){
    const s=e=>id==='ncep_gfswave016'?sea[local.get(e)]:null;
    models[id]={meta:{last_run_initialisation_time:nowMs/1000,data_end_time:time.at(-1)},data:region.forecast_points.map(()=>({
      hourly_units:{time:'unixtime',wind_speed_10m:'kn',wind_direction_10m:'°',wind_gusts_10m:'kn',visibility:'m',weather_code:'wmo code',wave_height:'ft',wave_period:'s',wind_wave_height:'ft'},
      hourly:{time,wind_speed_10m:time.map(()=>4),wind_direction_10m:time.map(()=>90),wind_gusts_10m:time.map(()=>6),visibility:time.map(()=>10000),weather_code:time.map(()=>0),
        wave_height:time.map(e=>s(e)?.[0]??2),wave_period:time.map(e=>s(e)?.[1]??10),wind_wave_height:time.map(()=>.5)}}))};
    sources['model-'+id]={status:'ok'};
  }
  return {region_id:region.id,completed_at:new Date(nowMs).toISOString(),forecast:{requested_points:region.forecast_points.map(p=>[p.id,p.latitude,p.longitude]),models},sources};
}

// `state.sea`, `state.tides` (null: the daily feed carries no tide source) and `state.push` (HTTP status of the push service) are read by the injected fetch on every call.
async function scenario(run,{owners=['alice'],subscribe=true}={}){
  const {sql,adapter}=database(),original=globalThis.fetch,env={DB:adapter,...await vapid()};
  const state={sea:{},tides:TIDES,push:201,now:T0,fetched:[],pushes:0};
  for(const owner of owners){
    sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)').run('trip-'+owner,owner,'morro-bay',region.forecast_points[0].id,'reef',DAY,7,13,30,40,20,'2026-11-10T20:00:00.000Z');
    if(subscribe){const k=await pushKeys();sql.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)').run('sub-'+owner,owner,PUSH+owner,k.p256dh,k.auth,'2026-11-10T20:00:00.000Z');}
  }
  globalThis.fetch=async url=>{
    const u=String(url);state.fetched.push(u);
    if(u===region.intelligence_feed)return Response.json(intelligence(state.now,state.sea));
    if(u===region.daily_feed)return Response.json({regulations:rules,...(state.tides?{sources:{tides:{status:'ok',data:{predictions:state.tides}}}}:{})});
    if(u.startsWith('https://api.weather.gov/alerts/active?zone='))return Response.json({features:[]});
    if(u.startsWith(PUSH)){state.pushes++;return new Response(null,{status:state.push});}
    throw Error('unexpected network request '+u);
  };
  useBucket({FEEDS:feedBucket()});   // published feeds come only from R2
  const ctx={sql,state,
    check:(owner='alice')=>checkOwnerTrips(env,owner,state.now,new Map()),
    advance:(hours=.25)=>{state.now+=hours*HOUR;},
    events:(owner='alice')=>sql.prepare('SELECT id,kind,message,status,created_at FROM alert_events WHERE owner=? ORDER BY created_at,rowid').all(owner).map(r=>({...r})),
    stored:(owner='alice')=>JSON.parse(sql.prepare('SELECT last_assessment FROM trips WHERE id=?').get('trip-'+owner).last_assessment)};
  try{await run(ctx);}finally{globalThis.fetch=original;useBucket({});sql.close();}
}
const HAZARD=hour=>`Regional Morro Bay entrance: the offshore bar estimate reads hazardous at ${hour}; this does not establish the trip's launch or crossing. ${BAR_CHECK}`;
const NOT_JUDGED=`Regional Morro Bay entrance: bar not judged for the complete saved window; this does not establish the trip's launch or crossing. ${BAR_CHECK}`;
const range=(from,to,sample)=>Object.fromEntries(Array.from({length:to-from+1},(_,i)=>[from+i,sample]));

test('bar_check_trip_delivery_and_cache: appearance, repeat, changed hour, clearance and missing tide send one update each',()=>scenario(async({check,advance,events,stored,state,sql})=>{
  assert.equal((await check()).changes,1);
  assert.deepEqual(events().map(e=>e.kind),['initial']);
  assert.equal(events()[0].message.includes('Hazard note'),false,'a complete calm window says nothing about the bar');
  assert.equal('hazards' in stored(),false);
  advance();assert.equal((await check()).changes,0,'calm repeat');
  // 6 ft at 10 s from 07:00 to 13:00 is mid-ebb from 08:00; the numerical status stays within limits
  state.sea=range(7,13,[6,10]);advance();
  const before=stored().checked_at;
  assert.equal((await check()).changes,1);
  const e1=events();assert.deepEqual(e1.map(x=>x.kind),['initial','update']);
  assert.ok(e1[1].message.includes('\nHazard note: '+HAZARD('8 am')+'\n'),e1[1].message);
  assert.ok(e1[1].message.includes('\nwithin limits.'),'status is not changed by the bar');
  assert.deepEqual(stored().hazards,[HAZARD('8 am')]);assert.equal(stored().status,'within limits');assert.deepEqual(stored().issues,[]);
  // the event identity is derived from the persisted material, hazards included
  const s=stored(),material={status:s.status,issues:s.issues,values:Object.fromEntries(Object.entries(s.values).map(([k,v])=>[k,v===null?null:Math.round(v*10)/10])),hazards:s.hazards};
  assert.equal(e1[1].id,await hash('trip-alice:update:'+before+':'+JSON.stringify(material)));
  advance();assert.equal((await check()).changes,0,'the identical note does not repeat');
  state.sea=range(9,13,[6,10]);advance();
  assert.equal((await check()).changes,1,'a different earliest hour is a change');assert.ok(events().at(-1).message.includes(HAZARD('9 am')));
  state.sea={};advance();
  assert.equal((await check()).changes,1,'clearance sends one update');
  assert.equal(events().at(-1).message.includes('Hazard note'),false);assert.equal('hazards' in stored(),false);
  advance();assert.equal((await check()).changes,0,'cleared stays quiet');
  // the daily feed loses its tide source: the bar is not judged, as a note, not as missing data
  state.tides=null;advance();
  assert.equal((await check()).changes,1);
  const last=events().at(-1);
  assert.ok(last.message.includes('\nHazard note: '+NOT_JUDGED+'\n'),last.message);
  assert.ok(last.message.includes('\nwithin limits.'));assert.deepEqual(stored().issues,[]);assert.equal(stored().status,'within limits');
  assert.equal(/\b(open|closed|safe)\b/i.test(last.message.split('Hazard note:')[1].split('\n')[0]),false);
  advance();assert.equal((await check()).changes,0,'the same missing tide repeats quietly');
  assert.equal(events().length,5);assert.equal(new Set(events().map(e=>e.id)).size,5);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM alert_events').get().n,5);
}));

test('bar_check_trip_delivery_and_cache: no new request is made for the bar, and the daily feed reaches the policy whole',()=>scenario(async({check,advance,state})=>{
  await check();
  const allowed=u=>u===region.intelligence_feed||u===region.daily_feed||u.startsWith('https://api.weather.gov/alerts/active?zone=');
  const reads=state.fetched.filter(u=>!u.startsWith(PUSH));
  assert.equal(reads.length,4,'intelligence, daily and the two advisory zones, once per check');
  assert.ok(reads.every(allowed));assert.equal(new Set(reads).size,4);
  state.sea=range(7,13,[6,10]);advance();state.fetched.length=0;
  await check();
  assert.equal(state.fetched.filter(u=>!u.startsWith(PUSH)).length,4,'a hazard adds no request');
  assert.ok(state.fetched.every(u=>allowed(u)||u.startsWith(PUSH)));
}));

test('bar_check_trip_delivery_and_cache: an in-app owner stores and reads the note',()=>scenario(async({check,advance,events,stored,state})=>{
  assert.equal((await check()).in_app,1);
  state.sea=range(7,13,[6,10]);advance();
  const r=await check();assert.equal(r.in_app,1);assert.equal(r.delivered,0);
  assert.equal(events().at(-1).status,'in-app');assert.ok(events().at(-1).message.includes(HAZARD('8 am')));
  assert.deepEqual(stored().hazards,[HAZARD('8 am')]);
  advance();assert.equal((await check()).changes,0);
},{subscribe:false}));

test('bar_check_trip_delivery_and_cache: a push that keeps failing gives distinct keys to distinct notes, reuses the key for the same input and delivers once',()=>scenario(async({check,advance,events,stored,state,sql})=>{
  await check();const base=sql.prepare('SELECT last_assessment FROM trips').get().last_assessment;
  state.push=503;state.sea=range(7,13,[6,10]);advance();
  const first=await check();assert.equal(first.changes,1);assert.equal(first.held,1);
  const key=()=>events().filter(e=>e.kind==='update').map(e=>e.id);
  assert.equal(key().length,1);assert.equal(sql.prepare('SELECT last_assessment FROM trips').get().last_assessment,base,'held delivery keeps the previous assessment');
  advance();assert.equal((await check()).changes,0,'same input, same key: no second event');assert.equal(key().length,1);
  state.sea=range(9,13,[6,10]);advance();
  assert.equal((await check()).changes,1,'a different earliest hour is a different key');assert.equal(new Set(key()).size,2);
  state.push=201;advance();assert.equal((await check()).delivered,1);
  assert.deepEqual(stored().hazards,[HAZARD('9 am')],'the delivered assessment carries the note');
  assert.equal(events().filter(e=>e.kind==='update'&&e.message.includes(HAZARD('9 am'))).length,1);
  advance();assert.equal((await check()).changes,0,'delivered once, quiet afterwards');
}));

test('bar_check_trip_delivery_and_cache: owners are isolated',()=>scenario(async({check,advance,events,state})=>{
  await check('alice');await check('bob');
  state.sea=range(7,13,[6,10]);advance();
  assert.equal((await check('alice')).changes,1);
  assert.equal(events('bob').length,1,'bob has not been checked since');
  assert.deepEqual(events('alice').map(e=>e.kind),['initial','update']);
  assert.equal((await check('bob')).changes,1);
  const a=events('alice').at(-1),b=events('bob').at(-1);
  assert.notEqual(a.id,b.id);assert.ok(a.message.includes(HAZARD('8 am'))&&b.message.includes(HAZARD('8 am')));
},{owners:['alice','bob']}));

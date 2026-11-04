// Production checkTrip/checkOwnerTrips with a memory database, injected fetch and a fixed clock:
// a long-period swell hazard note appears, repeats, changes and clears as one update each, never as missing data.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
const region=read('../regions/morro-bay/region.json');
globalThis.REGIONS={'morro-bay':region};
globalThis.DEPLOYMENT=read('../deployments/production.json');
const {checkOwnerTrips}=await import('../server/trips.ts');
const {windowInstants}=await import('../server/alert-policy.ts');
const {hash}=await import('../server/http.ts');

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
// Synthetic L/H brackets around the whole 7-13 PST window, so the bar estimate is complete (calm GFS-Wave data reads no hazard).
const TIDES=[['03','L'],['09','H'],['15','L'],['21','H']].map(([h,type])=>({time:`${DAY}T${h}:00:00-08:00`,height_ft:type==='H'?5:0.5,type}));
const rules={valid_from:'2026-01-01',valid_through:'2026-12-31',species:Object.fromEntries(['lingcod','rockfish'].map(id=>[id,{source_ids:[],windows:[{start:'2026-01-01',end:'2026-12-31'}]}]))};
// Feed for check time `nowMs`; `swell` maps a local hour to a long-period sample on the wave model (others stay calm).
function intelligence(nowMs,swell={}){
  const time=windowInstants(DAY,ZONE,0,23),models={},sources={};
  const local=new Map(time.map(e=>[e,Number(new Intl.DateTimeFormat('en-US',{timeZone:ZONE,hour:'2-digit',hourCycle:'h23'}).format(new Date(e*1000)))]));
  for(const id of ['gfs_global','ecmwf_ifs025','ncep_gfswave016','ecmwf_wam']){
    const hit=e=>id==='ecmwf_wam'&&swell[local.get(e)];
    models[id]={meta:{last_run_initialisation_time:nowMs/1000,data_end_time:time.at(-1)},data:[{
      hourly_units:{time:'unixtime',wind_speed_10m:'kn',wind_direction_10m:'°',wind_gusts_10m:'kn',visibility:'m',weather_code:'wmo code',wave_height:'ft',wave_period:'s',wind_wave_height:'ft'},
      hourly:{time,wind_speed_10m:time.map(()=>4),wind_direction_10m:time.map(()=>90),wind_gusts_10m:time.map(()=>6),visibility:time.map(()=>10000),weather_code:time.map(()=>0),
        wave_height:time.map(e=>hit(e)?.height??2),wave_period:time.map(e=>hit(e)?.period??10),wind_wave_height:time.map(()=>.5)}}]};
    sources['model-'+id]={status:'ok'};
  }
  return {region_id:region.id,completed_at:new Date(nowMs).toISOString(),forecast:{requested_points:region.forecast_points.map(p=>[p.id,p.latitude,p.longitude]),models},sources};
}

// `state.swell` and `state.push` (HTTP status of the push service) are read by the injected fetch on every call.
async function scenario(run,{owners=['alice']}={}){
  const {sql,adapter}=database(),original=globalThis.fetch,env={DB:adapter,...await vapid()};
  const state={swell:{},push:201,now:T0,fetched:[],pushes:0};
  for(const owner of owners){
    sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)').run('trip-'+owner,owner,'morro-bay','north','reef',DAY,7,13,30,40,20,'2026-11-10T20:00:00.000Z');
    const k=await pushKeys();
    sql.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)').run('sub-'+owner,owner,PUSH+owner,k.p256dh,k.auth,'2026-11-10T20:00:00.000Z');
  }
  globalThis.fetch=async url=>{
    const u=String(url);state.fetched.push(u);
    if(u===region.intelligence_feed)return Response.json(intelligence(state.now,state.swell));
    if(u===region.daily_feed)return Response.json({regulations:rules,sources:{tides:{status:'ok',data:{predictions:TIDES}}}});
    if(u.startsWith('https://api.weather.gov/alerts/active?zone='))return Response.json({features:[]});
    if(u.startsWith(PUSH)){state.pushes++;return new Response(null,{status:state.push});}
    throw Error('unexpected network request '+u);
  };
  const ctx={sql,state,
    check:(owner='alice')=>checkOwnerTrips(env,owner,state.now,new Map()),
    advance:(hours=.25)=>{state.now+=hours*HOUR;},
    events:(owner='alice')=>sql.prepare('SELECT id,kind,message,status,created_at FROM alert_events WHERE owner=? ORDER BY created_at,rowid').all(owner).map(r=>({...r})),
    stored:(owner='alice')=>JSON.parse(sql.prepare('SELECT last_assessment FROM trips WHERE id=?').get('trip-'+owner).last_assessment)};
  try{await run(ctx);}finally{globalThis.fetch=original;sql.close();}
}
const NOTE=(h,height='2.5',period='15')=>`Hazard note: Long-period swell (${height} ft at ${period} s) at ${h}; surge and entrance conditions need a separate check.`;

test('long_period_check_trip_events: appearance, repeat, change and clearance send one update each',()=>scenario(async({check,advance,events,stored,state})=>{
  assert.equal((await check()).changes,1);
  assert.deepEqual(events().map(e=>e.kind),['initial']);
  assert.equal(events()[0].message.includes('Hazard note'),false);
  assert.equal('hazards' in stored(),false,'quiet assessment persists the old shape');
  advance();assert.equal((await check()).changes,0,'calm repeat');
  // 2.5 ft at 15 s fits wind 30 / gust 40 / seas 20 and is still "within limits"
  state.swell={9:{height:2.5,period:15}};advance();
  const appeared=await check();assert.equal(appeared.changes,1);assert.equal(appeared.delivered,1);
  const events2=events();assert.deepEqual(events2.map(e=>e.kind),['initial','update']);
  assert.ok(events2[1].message.includes('\n'+NOTE('9 am')+'\n'),events2[1].message);
  assert.ok(events2[1].message.startsWith('Trip update'));assert.ok(events2[1].message.includes('\nwithin limits.'));
  assert.equal(/unverified|unavailable/i.test(events2[1].message.split('\nRules:')[0].replace('Wind','')),false);
  assert.deepEqual(stored().hazards,[NOTE('9 am').slice('Hazard note: '.length)]);
  assert.equal(stored().status,'within limits');
  advance();assert.equal((await check()).changes,0,'identical note does not repeat');
  state.swell={8:{height:2.5,period:15}};advance();
  assert.equal((await check()).changes,1,'an earlier hour is a change');assert.ok(events().at(-1).message.includes(NOTE('8 am')));
  state.swell={8:{height:3.2,period:15}};advance();
  assert.equal((await check()).changes,1,'a stronger swell is a change');assert.ok(events().at(-1).message.includes(NOTE('8 am','3.2')));
  state.swell={};advance();
  assert.equal((await check()).changes,1,'clearance sends one update');
  const last=events().at(-1);assert.equal(last.kind,'update');assert.equal(last.message.includes('Hazard note'),false);
  assert.equal('hazards' in stored(),false,'the persisted assessment drops the note');
  advance();assert.equal((await check()).changes,0,'cleared stays quiet');
  assert.equal(events().length,5);assert.equal(new Set(events().map(e=>e.id)).size,5);
  assert.ok(state.fetched.every(u=>u===region.intelligence_feed||u===region.daily_feed||u.startsWith('https://api.weather.gov/alerts/active?zone=')||u.startsWith(PUSH)));
}));

test('long_period_check_trip_events: a pending previous assessment gives distinct keys to distinct notes and reuses the key for the same input',()=>scenario(async({check,advance,events,stored,state,sql})=>{
  await check();const base=sql.prepare('SELECT last_assessment FROM trips').get().last_assessment;
  // the push service keeps failing (503), so last_assessment never advances and checked_at stays identical
  state.push=503;
  state.swell={9:{height:2.5,period:15}};advance();
  const first=await check();assert.equal(first.changes,1);assert.equal(first.held,1);
  const key=()=>events().filter(e=>e.kind==='update').map(e=>e.id);
  assert.equal(key().length,1);assert.equal(sql.prepare('SELECT last_assessment FROM trips').get().last_assessment,base,'held delivery keeps the previous assessment');
  advance();const again=await check();assert.equal(again.changes,0,'same input, same key: no second event');assert.deepEqual(key().length,1);
  state.swell={10:{height:2.5,period:15}};advance();
  assert.equal((await check()).changes,1,'a different note is a different key');
  assert.equal(new Set(key()).size,2);
  // the push service recovers: the pending event for the current input is delivered and the assessment advances
  state.push=201;advance();assert.equal((await check()).delivered,1);
  assert.deepEqual(stored().hazards,[NOTE('10 am').slice('Hazard note: '.length)],'delivered assessment now carries the note');
  assert.equal(events().filter(e=>e.kind==='update'&&e.message.includes(NOTE('10 am'))).length,1);
  advance();assert.equal((await check()).changes,0,'delivered once, quiet afterwards');
}));

test('long_period_check_trip_events: owners are isolated',()=>scenario(async({check,advance,events,state})=>{
  await check('alice');await check('bob');
  state.swell={9:{height:2.5,period:15}};advance();
  assert.equal((await check('alice')).changes,1);
  assert.equal(events('bob').length,1,'bob has not been checked since');
  assert.deepEqual(events('alice').map(e=>e.kind),['initial','update']);
  assert.equal((await check('bob')).changes,1);
  const a=events('alice').at(-1),b=events('bob').at(-1);
  assert.notEqual(a.id,b.id);assert.ok(a.message.includes(NOTE('9 am'))&&b.message.includes(NOTE('9 am')));
},{owners:['alice','bob']}));

test('long_period_check_trip_events: quiet event identity is unchanged by the note rule',async()=>{
  // the id of an initial/update event is hash(trip.id:kind:checked_at:material); calm material has no hazards key
  await scenario(async({check,events})=>{
    await check();
    const material={status:'within limits',issues:[],values:{wind:4,gust:6,sea:2,chop:.5}};
    assert.equal(events()[0].id,await hash('trip-alice:initial:first:'+JSON.stringify(material)));
  });
});

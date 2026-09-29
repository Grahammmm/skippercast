import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {assessTrip,alertDecision,alertMessage,tripChopLimit} from '../server/alert-policy.js';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
globalThis.REGIONS={'morro-bay':read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT=read('../deployments/production.json');
import {withSessions} from './fixtures/test-sessions.mjs';
const {default:deployed,validateSubscription,checkTrips,validateTripBoat}=await import('../server/worker.js');
// Owner-isolation tests sign in through real session cookies (fixtures/test-sessions.mjs);
// deployed.fetch is the Worker exactly as deployed.
const worker=withSessions(deployed);

function database(){
  // Apply every migration in journal order, as `wrangler d1 migrations apply` does.
  const sql=new DatabaseSync(':memory:'),journal=read('../drizzle/meta/_journal.json');
  for(const {tag} of [...journal.entries].sort((a,b)=>a.idx-b.idx))sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`,import.meta.url),'utf8'));
  const adapter={prepare(query){let args=[];const statement=sql.prepare(query);return {bind(...a){args=a;return this;},async first(){return statement.get(...args)||null;},async all(){return {results:statement.all(...args)};},async run(){const info=statement.run(...args);return {meta:{changes:Number(info.changes)}};}};},async batch(queries){sql.exec('BEGIN');try{const result=[];for(const q of queries)result.push(await q.run());sql.exec('COMMIT');return result;}catch(e){sql.exec('ROLLBACK');throw e;}}};return {sql,adapter};
}
const origin='https://skippercast.com';
function request(path,{owner,method='GET',body,requestOrigin=origin}={}){
  const headers={'Content-Type':'application/json'};if(owner)headers['x-test-owner']=owner;if(method!=='GET')headers.Origin=requestOrigin;
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
const forgedHeaders=(owner)=>({'oai-authenticated-user-id':owner,'oai-authenticated-user-email':owner+'@example.test','x-test-owner':owner});
test('no request header ever authenticates, whatever IDENTITY_PROVIDER says',async()=>{
  const {sql,adapter}=database();
  for(const provider of [undefined,'none','','skippercast','chatgpt-sites','cloudflare','constructor','__proto__','toString']){
    const env={DB:adapter,ANTHROPIC_API_KEY:'k'};if(provider!==undefined)env.IDENTITY_PROVIDER=provider;
    const label=`provider ${JSON.stringify(provider)}`;
    const denied=await deployed.fetch(new Request(origin+'/api/trips',{headers:forgedHeaders('alice')}),env);
    assert.equal(denied.status,401,label+' must not trust forged headers');
    assert.equal((await denied.json()).signIn,provider==='skippercast'?'/#account':null);
    const session=await(await deployed.fetch(new Request(origin+'/api/session',{headers:forgedHeaders('alice')}),env)).json();
    assert.equal(session.signedIn,false,label);assert.equal(session.signIn,provider==='skippercast'?'/#account':null,label);
    const post=await deployed.fetch(new Request(origin+'/api/boat/lookup',{method:'POST',headers:{...forgedHeaders('alice'),'Content-Type':'application/json',Origin:origin},body:JSON.stringify({query:'Parker 2320'})}),env);
    assert.equal(post.status,401,label);
  }
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM trips').get().n,0);
  sql.close();
});
test('the Cloudflare deployment config names the identity provider explicitly',()=>{
  const text=readFileSync(new URL('../wrangler.jsonc',import.meta.url),'utf8').replace(/^\s*\/\/.*$/mg,'');
  assert.equal(JSON.parse(text).vars?.IDENTITY_PROVIDER,'skippercast');
});
test('www redirects to the apex host with a 301 that keeps path and query',async()=>{
  for(const [from,to] of [['https://www.skippercast.com/','https://skippercast.com/'],['https://www.skippercast.com/sources.html?region=morro-bay&x=1#map','https://skippercast.com/sources.html?region=morro-bay&x=1'],['https://www.skippercast.com/api/session','https://skippercast.com/api/session']]){
    const response=await deployed.fetch(new Request(from),{});
    assert.equal(response.status,301,from);assert.equal(response.headers.get('Location'),to);
    assert.ok(response.headers.get('Strict-Transport-Security'),'redirects carry the security headers');
  }
  const apex=await deployed.fetch(new Request('https://skippercast.com/api/session'),{});assert.equal(apex.status,200);
  const staging=await deployed.fetch(new Request('https://skippercast.g4651.workers.dev/api/session'),{});assert.equal(staging.status,200,'workers.dev is not redirected');
});
test('the stable service worker is served with no-cache',async()=>{
  const ASSETS={fetch:async req=>new Response('self.x=1',{headers:{'Content-Type':'text/javascript','Cache-Control':'public,max-age=14400'}})};
  const response=await worker.fetch(new Request(origin+'/sw.js'),{ASSETS});
  assert.equal(response.status,200);assert.equal(response.headers.get('Cache-Control'),'no-cache');
  assert.equal(await response.text(),'self.x=1');
});
test('the cron trigger prunes expired records without any job call',async()=>{
  const {sql,adapter}=database(),originalFetch=globalThis.fetch,now=Date.now(),sec=Math.floor(now/1000);
  assert.ok(sql.prepare("SELECT name FROM sqlite_master WHERE type='index' AND name='limit_expires'").get(),'request_limits.expires_at is indexed');
  const old=new Date(now-100*86400000).toISOString(),recent=new Date(now-86400000).toISOString(),soon=new Date(now+86400000).toISOString().slice(0,10);
  sql.prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,?,?),(?,?,?)').run('stale',1,sec-10,'live',1,sec+600);
  const trip='INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)';
  sql.prepare(trip).run('old-trip','alice','morro-bay','north','reef',old.slice(0,10),7,13,8,12,3,old);
  sql.prepare(trip).run('new-trip','alice','morro-bay','north','reef',soon,7,13,8,12,3,recent);
  const event='INSERT INTO alert_events(id,trip_id,owner,kind,message,created_at) VALUES(?,?,?,?,?,?)';
  sql.prepare(event).run('old-event','old-trip','alice','change','m',old);sql.prepare(event).run('new-event','new-trip','alice','change','m',recent);
  sql.prepare('INSERT INTO delivery_receipts(id,event_id,subscription_id,status,attempt_at) VALUES(?,?,?,?,?),(?,?,?,?,?)').run('r-old','old-event','s','accepted',old,'r-new','new-event','s','accepted',recent);
  const feedback='INSERT INTO comfort_feedback(id,owner,region,observed_at,rating,context) VALUES(?,?,?,?,?,?)';
  sql.prepare(feedback).run('f-old','alice','morro-bay',new Date(now-400*86400000).toISOString(),5,'{}');sql.prepare(feedback).run('f-new','alice','morro-bay',old,5,'{}');
  let jobCalls=0;
  // The watchdog sees a fresh live feed, so the cron makes no GitHub or job call.
  globalThis.fetch=async url=>{if(String(url).includes('/api/jobs/'))jobCalls++;return Response.json({completed_at:new Date().toISOString()});};
  try{
    const pending=[];await worker.scheduled({cron:'*/15 * * * *',scheduledTime:now},{DB:adapter},{waitUntil:p=>pending.push(p)});
    await Promise.all(pending);
    const ids=table=>sql.prepare(`SELECT id FROM ${table} ORDER BY id`).all().map(r=>r.id);
    assert.deepEqual(ids('request_limits'),['live']);assert.deepEqual(ids('trips'),['new-trip']);
    assert.deepEqual(ids('alert_events'),['new-event']);assert.deepEqual(ids('delivery_receipts'),['r-new']);
    assert.deepEqual(ids('comfort_feedback'),['f-new']);assert.equal(jobCalls,0);
    // Without D1 bound (a static-only deploy) the cron still runs the watchdog and does not throw.
    const without=[];await worker.scheduled({},{},{waitUntil:p=>without.push(p)});await Promise.all(without);
  }finally{globalThis.fetch=originalFetch;sql.close();}
});
test('boat lookup settings: kill switch, global cap and model id come from Worker vars',async()=>{
  const {lookupSettings,DEFAULT_MODEL,DEFAULT_GLOBAL_DAILY_LIMIT}=await import('../server/boat-lookup.js');
  assert.deepEqual(lookupSettings({}),{enabled:true,model:DEFAULT_MODEL,globalDailyLimit:DEFAULT_GLOBAL_DAILY_LIMIT});
  assert.equal(DEFAULT_GLOBAL_DAILY_LIMIT,500);
  for(const off of ['false','FALSE',' false '])assert.equal(lookupSettings({BOAT_LOOKUP_ENABLED:off}).enabled,false);
  for(const on of ['true','1',''])assert.equal(lookupSettings({BOAT_LOOKUP_ENABLED:on}).enabled,true);
  assert.equal(lookupSettings({BOAT_LOOKUP_GLOBAL_DAILY_LIMIT:'0'}).globalDailyLimit,0);
  assert.equal(lookupSettings({BOAT_LOOKUP_GLOBAL_DAILY_LIMIT:'40'}).globalDailyLimit,40);
  for(const bad of ['','-1','1.5','lots'])assert.equal(lookupSettings({BOAT_LOOKUP_GLOBAL_DAILY_LIMIT:bad}).globalDailyLimit,500);
  assert.equal(lookupSettings({BOAT_AI_MODEL:'claude-haiku-5'}).model,'claude-haiku-5');
  assert.equal(lookupSettings({BOAT_AI_MODEL:'bad model"id'}).model,DEFAULT_MODEL);
  const text=readFileSync(new URL('../wrangler.jsonc',import.meta.url),'utf8').replace(/^\s*\/\/.*$/mg,''),vars=JSON.parse(text).vars;
  assert.equal(vars.BOAT_LOOKUP_ENABLED,'true');assert.equal(vars.BOAT_LOOKUP_GLOBAL_DAILY_LIMIT,'500');
});
test('boat lookup kill switch and global daily cap stop spend before the model is called',async()=>{
  const {sql,adapter}=database(),originalFetch=globalThis.fetch,originalLog=console.log;let calls=0;const logged=[],points=[];
  const answer={content:[{type:'text',text:JSON.stringify({name:'Parker 2320',loa_ft:23,beam_ft:8.5,hull:'deep-v',deadrise_deg:20,confidence:'high'})}],stop_reason:'end_turn',
    usage:{input_tokens:1200,output_tokens:300,cache_read_input_tokens:100,server_tool_use:{web_search_requests:2}}};
  globalThis.fetch=async url=>{calls++;assert.equal(url,'https://api.anthropic.com/v1/messages');return Response.json(answer);};
  console.log=line=>logged.push(line);
  const lookup=(owner,env,query='Parker 2320 '+owner)=>worker.fetch(request('boat/lookup',{owner,method:'POST',body:{query}}),{DB:adapter,ANTHROPIC_API_KEY:'k',...env});
  try{
    const off=await lookup('alice',{BOAT_LOOKUP_ENABLED:'false'});
    assert.equal(off.status,503);assert.match((await off.json()).error,/switched off/);assert.equal(calls,0);
    const env={BOAT_LOOKUP_GLOBAL_DAILY_LIMIT:'2',BOAT_AI_MODEL:'claude-test-model',ANALYTICS:{writeDataPoint:p=>points.push(p)}};
    assert.equal((await lookup('alice',env)).status,200);assert.equal((await lookup('bob',env)).status,200);
    const capped=await lookup('carol',env);assert.equal(capped.status,429);assert.match((await capped.json()).error,/busy today/);
    assert.equal(calls,2,'the global cap refuses before calling the model');
    const day=Math.floor(Date.now()/86400000);assert.equal(sql.prepare('SELECT count FROM request_limits WHERE id=?').get('global:boat:'+day).count,3);
    const lines=logged.map(l=>{try{return JSON.parse(l);}catch{return null;}}).filter(l=>l?.event==='boat_lookup');
    assert.equal(lines.length,2);
    assert.deepEqual(lines[0],{event:'boat_lookup',outcome:'ok',model:'claude-test-model',turns:1,input_tokens:1300,output_tokens:300,web_search_requests:2});
    assert.ok(!logged.some(l=>String(l).includes('Parker')),'usage logs never carry the query');
    assert.equal(points.length,2);assert.deepEqual(points[0].doubles,[1300,300,2,1]);assert.deepEqual(points[0].blobs,['boat_lookup','ok','claude-test-model']);
    // A failed model call is still logged with its billed turns.
    globalThis.fetch=async()=>new Response('overloaded',{status:529});
    assert.equal((await lookup('dave',{BOAT_LOOKUP_GLOBAL_DAILY_LIMIT:'10'})).status,502);
    assert.equal(logged.map(l=>{try{return JSON.parse(l);}catch{return null;}}).filter(l=>l?.event==='boat_lookup').at(-1).outcome,'error');
  }finally{globalThis.fetch=originalFetch;console.log=originalLog;sql.close();}
});

test('a trip saves the boat it was planned for; invalid boats are rejected and no boat stays null',async()=>{
  const {sql,adapter}=database(),env={DB:adapter};
  try{
    const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles'}).format(new Date(Date.now()+86400000));
    const trip={region:'morro-bay',point:'north',species:'reef',date,start_hour:7,end_hour:13,wind_limit:6,gust_limit:10,sea_limit:2};
    const boat={name:'Skiff\u0007 18',sea:.6,wind:.8,chop_period:5};
    assert.equal((await worker.fetch(request('trips',{owner:'alice',method:'POST',body:{...trip,boat}}),env)).status,201);
    assert.equal((await worker.fetch(request('trips',{owner:'alice',method:'POST',body:trip}),env)).status,201);
    for(const bad of [{...boat,sea:3},{...boat,wind:'1'},{...boat,chop_period:null},[1],'boat'])
      assert.equal((await worker.fetch(request('trips',{owner:'alice',method:'POST',body:{...trip,boat:bad}}),env)).status,400,JSON.stringify(bad));
    const rows=sql.prepare('SELECT boat_name,boat_sea,boat_wind,boat_chop_period FROM trips ORDER BY boat_sea IS NULL').all().map(r=>({...r}));
    assert.deepEqual(rows,[{boat_name:'Skiff 18',boat_sea:.6,boat_wind:.8,boat_chop_period:5},{boat_name:null,boat_sea:null,boat_wind:null,boat_chop_period:null}]);
    const listed=(await (await worker.fetch(request('trips',{owner:'alice'}),env)).json()).trips;
    assert.ok(listed.some(t=>t.boat_name==='Skiff 18'));
  }finally{sql.close();}
  assert.equal(validateTripBoat(undefined),null);
  assert.equal(validateTripBoat({sea:1,wind:1,chop_period:6,name:'x'.repeat(200)}).name.length,80);
});

test('wind chop is judged for the saved boat and the alert says which boat',()=>{
  assert.equal(tripChopLimit({}),1);
  assert.equal(tripChopLimit({boat_sea:.6}),.6);
  assert.equal(tripChopLimit({boat_sea:1.8}),1.8);
  assert.equal(tripChopLimit({boat_sea:40}),1,'out-of-range stored values fall back to the reference boat');
  const region=REGIONS['morro-bay'];
  const assessment={status:'above limits',legal:'reviewed season',values:{wind:5,gust:7,sea:2,chop:.8},chop_limit:.6,issues:[],checked_at:'2026-09-29T00:00:00Z',runs:{}};
  const trip={date:'2026-09-30',point:region.forecast_points[0].id,start_hour:7,end_hour:13,boat_name:'Skiff 18',boat_sea:.6};
  assert.match(alertMessage(trip,region,assessment,'final'),/Boat: Skiff 18 · chop limit 0\.6 ft for this boat\./);
  assert.doesNotMatch(alertMessage({...trip,boat_name:null,boat_sea:null},region,assessment,'final'),/Boat:/);
});


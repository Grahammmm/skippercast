import {buildPushPayload} from '@block65/webcrypto-web-push';
import {assessTrip,alertDecision,alertMessage,dateInZone} from './alert-policy.js';
import {verifyJobToken} from './job-auth.js';
import {lookupBoat,lookupSettings,validQuery} from './boat-lookup.js';
import {useBucket,readBucketJSON,serveFeed} from './feeds.js';
import {watchdog} from './watchdog.js';
import {secure} from './security-headers.js';
import {cached,cacheKey,overLimit,clientIP,tooManyRequests} from './edge-cache.js';
import {answer as modelAnswer,meta as modelMeta,MODELS as FORECAST_MODELS,QueryError} from './model-api.js';

// Injected from reviewed region manifests by the build; never visitor-supplied URLs.
const regions=REGIONS;
const deployment=DEPLOYMENT;
const origins=new Set(deployment.allowed_origins);
let extraOrigins=new Set();
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'strict-origin-when-cross-origin'}});
const hash=async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),b=>b.toString(16).padStart(2,'0')).join('');
const db=env=>{if(!env.DB)throw Error('storage unavailable');return env.DB;};
// Errors caused by the request itself: answered 400 with their (fixed, safe)
// message. Anything else is a dependency failure and answers a generic 503.
export class ClientError extends Error {}
export class RateLimited extends Error {}
const regionById=id=>typeof id==='string'&&Object.hasOwn(regions,id)?regions[id]:null;
// Identity comes from the host platform. ChatGPT Sites injects the OpenAI identity
// headers after authenticating the visitor and strips any the visitor sends. Any
// other host (our own Cloudflare Worker) must never trust them: a visitor could
// forge them and act as any owner. wrangler.jsonc sets IDENTITY_PROVIDER to
// "none"; the Sites package carries no wrangler config, so the var is absent there.
let identityProvider='chatgpt-sites';
const SIGN_IN={'chatgpt-sites':'/signin-with-chatgpt?return_to=%2F%23forecast'};
function user(request){
  if(identityProvider!=='chatgpt-sites')return null;
  const id=request.headers.get('oai-authenticated-user-id'),email=request.headers.get('oai-authenticated-user-email');return id&&email?id:null;
}
async function body(request){
  if(Number(request.headers.get('content-length'))>8192)throw new ClientError('body too large');
  const reader=request.body?.getReader();if(!reader)throw new ClientError('invalid empty body');
  const chunks=[];let size=0;
  for(;;){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>8192){await reader.cancel();throw new ClientError('body too large');}chunks.push(value);}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  try{const value=JSON.parse(new TextDecoder().decode(bytes));if(!value||typeof value!=='object'||Array.isArray(value))throw Error();return value;}catch{throw new ClientError('invalid JSON body');}
}
function requireOrigin(request){const origin=request.headers.get('Origin');if(!origin||!(origins.has(origin)||extraOrigins.has(origin)))throw new ClientError('origin rejected');}
async function budget(env,owner){const minute=Math.floor(Date.now()/60000),id=await hash(owner+':'+minute);const row=await db(env).prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,1,?) ON CONFLICT(id) DO UPDATE SET count=count+1 RETURNING count').bind(id,minute*60+120).first();if(row.count>30)throw new RateLimited('rate limited');}
async function readFeed(url){
  let stage='r2';
  try{
    // Published feeds come from R2 when the bucket is bound; GitHub otherwise.
    const stored=await readBucketJSON(url);if(stored!==undefined)return stored;
    stage='cache';
    const key=new Request(url);let cache,cached;
    // Sites isolates named caches. Its shared default cache is intentionally
    // unavailable; an optional cache failure must never disable public feeds.
    try{cache=await globalThis.caches?.open('skippercast-public-feeds-v1');cached=await cache?.match(key);}catch{cache=null;}
    if(cached)return cached.json();
    // Workers supports manual redirects; response.ok rejects every 3xx below.
    stage='fetch';const response=await fetch(url,{signal:AbortSignal.timeout(18000),redirect:'manual'});
    if(!response.ok)throw Error('feed HTTP '+response.status);stage='decode';const text=await response.text();if(text.length>15000000)throw Error('feed too large');const value=JSON.parse(text);
    stage='cache-write';if(cache)try{await cache.put(key,new Response(text,{headers:{'Content-Type':'application/json','Cache-Control':'public,max-age=300'}}));}catch{console.warn('Public feed cache write unavailable');}return value;
  }catch(error){
    // Only reviewed, public feed URLs reach here. Never include request headers.
    console.error('Regional feed unavailable',{stage,host:new URL(url).host,reason:String(error.message).slice(0,200)});throw error;
  }
}
export function validateSubscription(s){
  if(typeof s?.endpoint!=='string'||!s.keys||typeof s.keys!=='object')throw new ClientError('subscription missing');
  let u;try{u=new URL(s.endpoint);}catch{throw new ClientError('push endpoint rejected');}
  const allowed=u.hostname==='fcm.googleapis.com'||u.hostname==='updates.push.services.mozilla.com'||u.hostname==='web.push.apple.com'||u.hostname.endsWith('.notify.windows.com');
  if(u.protocol!=='https:'||u.port||u.username||u.password||!allowed||u.href.length>2000)throw new ClientError('push endpoint rejected');
  if(!/^[\w-]{87}$/.test(s.keys.p256dh)||!/^[\w-]{22}$/.test(s.keys.auth))throw new ClientError('push keys invalid');return s;
}
export function validateTrip(input,now=Date.now()){
  const r=regionById(input.region);if(!r||!r.forecast_points.some(p=>p.id===input.point)||!r.species.includes(input.species))throw new ClientError('unknown area or species');
  const today=dateInZone(now,r.timezone),last=dateInZone(now+7*86400000,r.timezone);
  if(!/^\d{4}-\d{2}-\d{2}$/.test(input.date)||!Number.isFinite(Date.parse(input.date))||new Date(input.date).toISOString().slice(0,10)!==input.date||input.date<today||input.date>last)throw new ClientError('date must be within the next seven days');
  for(const [key,min,max] of [['start_hour',0,22],['end_hour',1,23],['wind_limit',1,30],['gust_limit',1,40],['sea_limit',.5,10]])if(typeof input[key]!=='number'||!Number.isFinite(input[key])||input[key]<min||input[key]>max)throw new ClientError('invalid '+key);
  if(!Number.isInteger(input.start_hour)||!Number.isInteger(input.end_hour)||input.end_hour<=input.start_hour||input.gust_limit<input.wind_limit)throw new ClientError('invalid window or thresholds');return input;
}
async function deliver(env,event){
  const subscriptions=(await db(env).prepare('SELECT * FROM subscriptions WHERE owner=?').bind(event.owner).all()).results;
  let delivered=false;
  for(const s of subscriptions){
    const id=await hash(event.id+':'+s.id);
    const prior=await db(env).prepare('SELECT status FROM delivery_receipts WHERE id=?').bind(id).first();
    if(prior){if(prior.status==='accepted')delivered=true;continue;}
    const claim=await db(env).prepare('INSERT OR IGNORE INTO delivery_receipts(id,event_id,subscription_id,status,attempt_at) VALUES(?,?,?,?,?)').bind(id,event.id,s.id,'sending',new Date().toISOString()).run();
    if(!claim.meta.changes)continue;
    let status='uncertain',httpStatus=null;
    try{
      const payload=await buildPushPayload({data:JSON.stringify({title:'SkipperCast trip update',body:event.message.slice(0,1600),eventId:event.id,url:'/#forecast'}),options:{ttl:3600}},
        {endpoint:s.endpoint,keys:{p256dh:s.p256dh,auth:s.auth}},{subject:deployment.public_origin,publicKey:env.VAPID_PUBLIC_KEY,privateKey:env.VAPID_PRIVATE_KEY});
      const response=await fetch(s.endpoint,{...payload,redirect:'manual',signal:AbortSignal.timeout(12000)});httpStatus=response.status;
      status=response.ok?'accepted':response.status===404||response.status===410?'expired':'failed';
      if(status==='expired')await db(env).prepare('DELETE FROM subscriptions WHERE id=?').bind(s.id).run();
    }catch{status='uncertain';}
    await db(env).prepare('UPDATE delivery_receipts SET status=?,http_status=? WHERE id=?').bind(status,httpStatus,id).run();
    if(status==='accepted')delivered=true;
  }
  if(delivered)await db(env).prepare('UPDATE alert_events SET status=?,delivered_at=? WHERE id=?').bind('delivered',new Date().toISOString(),event.id).run();
  else await db(env).prepare('UPDATE alert_events SET status=? WHERE id=?').bind(subscriptions.length?'held':'in-app',event.id).run();
  return delivered;
}
// Retention: expired rate-limit rows, 90-day trips/events/receipts, 365-day feedback.
// Runs from the Cloudflare cron (scheduled) and after each job page, so it never
// depends on the GitHub Actions chain alone (the Sites host has no cron trigger).
export async function prune(env,now=Date.now()){
  const cutoff=new Date(now-90*86400000).toISOString();
  await db(env).batch([db(env).prepare('DELETE FROM request_limits WHERE expires_at<?').bind(Math.floor(now/1000)),db(env).prepare('DELETE FROM comfort_feedback WHERE observed_at<?').bind(new Date(now-365*86400000).toISOString()),
    db(env).prepare('DELETE FROM delivery_receipts WHERE event_id IN (SELECT id FROM alert_events WHERE created_at<?)').bind(cutoff),db(env).prepare('DELETE FROM alert_events WHERE created_at<?').bind(cutoff),db(env).prepare('DELETE FROM trips WHERE date<?').bind(cutoff.slice(0,10))]);
}
async function scheduledPrune(env){
  if(!env?.DB)return;
  try{await prune(env);}catch(error){console.error('Retention prune failed',{reason:String(error.message).slice(0,200)});}
}
export async function checkTrips(env,cursor=''){
  const now=Date.now(),trips=(await db(env).prepare('SELECT * FROM trips WHERE enabled=1 AND final_delivered_at IS NULL AND id>? ORDER BY id LIMIT 25').bind(cursor).all()).results;
  const feeds=new Map();let changes=0,delivered=0,held=0,inApp=0;
  for(const trip of trips){
    const region=regions[trip.region];if(!region)continue;
    const today=dateInZone(now,region.timezone),tomorrow=dateInZone(now+86400000,region.timezone);
    const hour=Number(new Intl.DateTimeFormat('en-US',{timeZone:region.timezone,hour:'2-digit',hourCycle:'h23'}).format(new Date(now)));
    let intel,rules,alerts;
    const pointConfig=region.forecast_points.find(p=>p.id===trip.point), zones=region.contexts?.[pointConfig?.context]?.marine_zones||region.marine_zones;
    const feedKey=trip.region+':'+(pointConfig?.context||'default');
    if(!feeds.has(feedKey)){
      const loaded=await Promise.allSettled([readFeed(region.intelligence_feed),readFeed(region.daily_feed),...['coastal','offshore'].map(k=>readFeed('https://api.weather.gov/alerts/active?zone='+zones[k]))]);
      feeds.set(feedKey,loaded.map(x=>x.status==='fulfilled'?x.value:null));
    }
    const inputs=feeds.get(feedKey);intel=inputs[0];rules=inputs[1]?.regulations;
    const offshore=region.forecast_points.find(p=>p.id===trip.point)?.offshore;alerts=inputs[offshore?3:2]?.features?.map(f=>f.properties);
    const assessment=assessTrip(trip,region,intel,rules,alerts,now);let previous=null;try{previous=JSON.parse(trip.last_assessment);}catch{}
    const final=trip.date===tomorrow&&hour>=18,missed=trip.date<=today&&!trip.final_delivered_at;
    const kind=alertDecision(previous,assessment,{final,missed});if(!kind)continue;
    const material={status:assessment.status,issues:assessment.issues,values:Object.fromEntries(Object.entries(assessment.values).map(([k,v])=>[k,v===null?null:Math.round(v*10)/10]))};
    const id=await hash(trip.id+':'+(missed?'missed-final':final?'final':kind+':'+(previous?.checked_at||'first')+':'+JSON.stringify(material)));
    const message=alertMessage(trip,region,assessment,kind);
    const insert=await db(env).prepare('INSERT OR IGNORE INTO alert_events(id,trip_id,owner,kind,message,created_at) VALUES(?,?,?,?,?,?)').bind(id,trip.id,trip.owner,kind,message,new Date(now).toISOString()).run();
    if(insert.meta.changes)changes++;
    const event=await db(env).prepare('SELECT * FROM alert_events WHERE id=?').bind(id).first();
    const accepted=['delivered','read'].includes(event.status)||event.status==='pending'&&await deliver(env,event);
    if(accepted){delivered++;await db(env).prepare('UPDATE trips SET last_assessment=?,final_delivered_at=? WHERE id=?').bind(JSON.stringify(assessment),final||missed?new Date(now).toISOString():null,trip.id).run();}
    else {
      const receipt=await db(env).prepare('SELECT status FROM alert_events WHERE id=?').bind(id).first();
      if(receipt.status==='in-app'){inApp++;await db(env).prepare('UPDATE trips SET last_assessment=? WHERE id=?').bind(JSON.stringify(assessment),trip.id).run();}
      else held++;
    }
  }
  await prune(env,now);
  return {checked:trips.length,changes,delivered,held,in_app:inApp,next_cursor:trips.length===25?trips.at(-1).id:null};
}

// One structured line per boat lookup (billed tokens and searches, never the
// query or owner), mirrored to Workers Analytics Engine when ANALYTICS is bound.
function recordLookupUsage(env,usage,outcome){
  const line={event:'boat_lookup',outcome,model:usage.model||null,turns:usage.turns||0,input_tokens:usage.input_tokens||0,output_tokens:usage.output_tokens||0,web_search_requests:usage.web_search_requests||0};
  console.log(JSON.stringify(line));
  try{env.ANALYTICS?.writeDataPoint({indexes:['boat_lookup'],blobs:[line.event,line.outcome,line.model||''],doubles:[line.input_tokens,line.output_tokens,line.web_search_requests,line.turns]});}catch{}
}
function bind(env){
  useBucket(env);
  identityProvider=env?.IDENTITY_PROVIDER??'chatgpt-sites';
  // Extra origins (e.g. a workers.dev staging copy) may post; production origins come from the deployment policy.
  extraOrigins=new Set(String(env?.EXTRA_ORIGINS||'').split(',').map(s=>s.trim()).filter(s=>/^https:\/\/[a-z0-9.-]+$/.test(s)));
}
export default {async scheduled(controller,env,ctx){bind(env);ctx.waitUntil(Promise.all([watchdog(env),scheduledPrune(env)]));},
// Every response, including shells, assets, feeds and errors, carries the security headers.
async fetch(request,env,ctx){return secure(await route(request,env,ctx));}};
const build=()=>typeof BUILD_ID==='undefined'?'dev':BUILD_ID;
const PUBLIC_TTL='public, max-age=300, s-maxage=300';
async function route(request,env,ctx){
  bind(env);
  const url=new URL(request.url),path=url.pathname;
  if(request.method==='GET'&&path.startsWith('/feeds/')){
    // Per-IP limits apply only where the Rate Limiting binding exists (not on Sites).
    if(await overLimit(env.FEED_LIMITER,'feeds:'+clientIP(request)))return tooManyRequests();
    const served=await serveFeed(request,path,env.ASSETS,{ctx,build:build()});if(served)return served;
    return new Response('Not found',{status:404});
  }
  if(!path.startsWith('/api/')){
    if(!env.ASSETS)return new Response('Not found',{status:404});
    // The Sites edge can retain a previously deployed asset at a stable URL, so
    // scripts, styles and pages are published under content-hashed names
    // (scripts/fingerprint.mjs). Stable page paths resolve here, uncached.
    if(path==='/sw.js'){
      // Stable service-worker URL (see scripts/fingerprint.mjs STABLE): revalidate on every check.
      const response=await env.ASSETS.fetch(request),fresh=new Response(response.body,response);
      fresh.headers.set('Cache-Control','no-cache');return fresh;
    }
    const current=SHELLS[path];
    if(!current)return env.ASSETS.fetch(request);
    const assetUrl=new URL(request.url);assetUrl.pathname=current.replace(/\.html$/,'');assetUrl.search=''; // hosts serve pages without .html
    const response=await env.ASSETS.fetch(new Request(assetUrl,request));
    const fresh=new Response(response.body,response);
    fresh.headers.set('Cache-Control','no-store');
    return fresh;
  }
  try{
    // SkipperCast's own NOAA/ECMWF forecast service, answering Open-Meteo-style queries.
    const om=path.match(/^\/api\/om\/(?:v1\/(forecast|marine)|data\/([a-z0-9_]+)\/static\/meta\.json)$/);
    if(request.method==='GET'&&om){
      if(await overLimit(env.PUBLIC_LIMITER,'om:'+clientIP(request)))return tooManyRequests();
      const base=deployment.forecast_feed,store={
        manifest:model=>FORECAST_MODELS[model]?readFeed(`${base}/${model}/manifest.json`):null,
        tile:(model,key)=>FORECAST_MODELS[model]&&/^-?\d{1,3}_-?\d{1,3}$/.test(key)?readFeed(`${base}/${model}/tiles/${key}.json`):null};
      // Keyed on the normalised query (parameter order does not split the cache).
      return await cached(cacheKey(url,{build:build()}),ctx,async()=>{
        try{
          const data=om[1]?await modelAnswer(om[1],url.searchParams,store):await modelMeta(om[2],store);
          const response=json(data);response.headers.set('Cache-Control',PUBLIC_TTL);return {response};
        }catch(error){if(error instanceof QueryError)return {response:json({error:true,reason:error.message},400)};throw error;}
      });
    }
    // Public liveness only: which bindings and secrets exist is not published.
    // Feed storage shows per response in X-Feed-Source on /feeds/.
    if(path==='/api/health')return json({service:'SkipperCast',version:'0.3.0',build:BUILD_ID});
    if(path==='/api/jobs/check'&&request.method==='POST'){
      const token=request.headers.get('Authorization')?.replace(/^Bearer /,'');
      const claims=await verifyJobToken(token,deployment);if(!claims)return json({error:'Unauthorized'},401);
      const input=await body(request),cursor=input.cursor||'';if(typeof cursor!=='string'||cursor.length>50)throw new ClientError('invalid cursor');
      await budget(env,'job:'+claims.jti);
      return json(await checkTrips(env,cursor));
    }
    if(request.method==='GET'&&path==='/api/habitat'){
      const region=regionById(url.searchParams.get('region'));if(!region?.habitat_feed)return json({error:'Unknown region'},404);
      return await cached(cacheKey(url,{params:['region'],build:build()}),ctx,async()=>{
        const feed=await readFeed(region.habitat_feed);if(feed.region_id!==region.id||feed.schema_version!==1)throw Error('region mismatch');
        const response=json(feed);response.headers.set('Cache-Control',PUBLIC_TTL);return {response};
      });
    }
    if(request.method==='GET'&&['/api/intelligence','/api/forecast'].includes(path)){
      const region=regionById(url.searchParams.get('region'));if(!region)return json({error:'Unknown region'},404);
      const key=p=>cacheKey(new URL(p+'?region='+encodeURIComponent(region.id),url),{params:['region'],build:build()});
      return await cached(key(path),ctx,async()=>{
        // One read and parse of the regional feed answers both endpoints; the
        // sibling response is cached too, so the feed is decoded once per TTL.
        const feed=await readFeed(region.intelligence_feed);if(feed.region_id!==region.id)throw Error('region mismatch');
        const forecast=json(feed.forecast);forecast.headers.set('Cache-Control',PUBLIC_TTL);
        const intelligence=json({...feed,forecast:undefined,sources:Object.fromEntries(Object.entries(feed.sources).map(([k,v])=>[k,k.startsWith('model-')||k.startsWith('verify-')?{name:v.name,status:v.status,issue:v.issue,url:v.url,checked_at:v.checked_at}:v]))});
        // Live conditions refresh often: one minute, matching intelligence.json on /feeds/.
        intelligence.headers.set('Cache-Control','public, max-age=60, s-maxage=60');
        return path==='/api/forecast'?{response:forecast,extra:[[key('/api/intelligence'),intelligence]]}:{response:intelligence,extra:[[key('/api/forecast'),forecast]]};
      });
    }
    const owner=user(request);
    if(path==='/api/session'&&request.method==='GET')return json({signedIn:!!owner,publicKey:env.VAPID_PUBLIC_KEY||null,signIn:SIGN_IN[identityProvider]||null});
    if(!owner)return json({error:SIGN_IN[identityProvider]?'Sign in to save private trips or feedback':'Accounts are not available on this site yet',signIn:SIGN_IN[identityProvider]||null},401);
    if(request.method!=='GET'){requireOrigin(request);await budget(env,owner);}
    if(path==='/api/boat/lookup'&&request.method==='POST'){
      // AI spec lookup for the boat profile: signed-in only, 20 per person per day,
      // a global daily ceiling, a kill switch, cached by query.
      const settings=lookupSettings(env);
      if(!settings.enabled)return json({error:'AI boat lookup is switched off for now; enter your boat details by hand.'},503);
      if(!env.ANTHROPIC_API_KEY)return json({error:'AI boat lookup is not configured yet; enter your boat details by hand.'},503);
      const query=validQuery((await body(request)).query);if(!query)throw new ClientError('invalid boat name');
      const key=new Request('https://skippercast.com/boat-lookup/'+await hash(query.toLowerCase()));
      let cache=null;try{cache=await globalThis.caches?.open('skippercast-boat-lookups-v1');const hit=await cache?.match(key);if(hit)return json({...await hit.json(),cached:true});}catch{cache=null;}
      const day=Math.floor(Date.now()/86400000),id=await hash(owner+':boat:'+day);
      const count=async id=>(await db(env).prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,1,?) ON CONFLICT(id) DO UPDATE SET count=count+1 RETURNING count').bind(id,(day+2)*86400).first()).count;
      if(await count(id)>20)return json({error:'Daily boat lookup limit reached; try again tomorrow or enter details by hand.'},429);
      if(await count('global:boat:'+day)>settings.globalDailyLimit){
        console.warn(JSON.stringify({event:'boat_lookup_global_cap',day,limit:settings.globalDailyLimit}));
        return json({error:'AI boat lookup is busy today; try again tomorrow or enter details by hand.'},429);
      }
      let result,outcome='ok';const usage={};
      try{result=await lookupBoat(query,{apiKey:env.ANTHROPIC_API_KEY,model:settings.model,usage});}
      catch(error){outcome='error';console.error('Boat lookup failed',{reason:String(error.message).slice(0,200)});}
      finally{recordLookupUsage(env,usage,outcome);}
      if(outcome!=='ok')return json({error:'Could not look up that boat. Check the name or enter details by hand.'},502);
      const payload={query,...result,looked_up_at:new Date().toISOString()};
      if(cache)try{await cache.put(key,new Response(JSON.stringify(payload),{headers:{'Content-Type':'application/json','Cache-Control':'public,max-age=2592000'}}));}catch{}
      return json(payload);
    }
    if(path==='/api/trips'&&request.method==='GET')return json({trips:(await db(env).prepare('SELECT * FROM trips WHERE owner=? ORDER BY date DESC LIMIT 50').bind(owner).all()).results,events:(await db(env).prepare('SELECT id,trip_id,kind,message,status,created_at FROM alert_events WHERE owner=? ORDER BY created_at DESC LIMIT 30').bind(owner).all()).results});
    if(path==='/api/trips'&&request.method==='POST'){
      const t=validateTrip(await body(request));const count=await db(env).prepare('SELECT COUNT(*) AS n FROM trips WHERE owner=? AND enabled=1 AND final_delivered_at IS NULL AND date>=?').bind(owner,dateInZone(Date.now(),regions[t.region].timezone)).first();if(count.n>=20)return json({error:'Limit of 20 active trips'},409);
      const id=crypto.randomUUID();await db(env).prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,enabled,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,1,?)').bind(id,owner,t.region,t.point,t.species,t.date,t.start_hour,t.end_hour,t.wind_limit,t.gust_limit,t.sea_limit,new Date().toISOString()).run();return json({id},201);
    }
    if(path==='/api/trips'&&request.method==='DELETE'){
      const {id}=await body(request);if(typeof id!=='string'||!id||id.length>64)throw new ClientError('trip id required');
      await db(env).batch([db(env).prepare('DELETE FROM delivery_receipts WHERE event_id IN (SELECT id FROM alert_events WHERE trip_id=? AND owner=?)').bind(id,owner),db(env).prepare('DELETE FROM alert_events WHERE trip_id=? AND owner=?').bind(id,owner),db(env).prepare('DELETE FROM trips WHERE id=? AND owner=?').bind(id,owner)]);return json({deleted:true});
    }
    if(path==='/api/events/ack'&&request.method==='POST'){
      // Event ids are SHA-256 hex digests; never bind an unchecked value.
      const {id}=await body(request);if(typeof id!=='string'||!/^[0-9a-f]{64}$/.test(id))throw new ClientError('event id required');
      const event=await db(env).prepare('SELECT * FROM alert_events WHERE id=? AND owner=?').bind(id,owner).first();
      if(!event)return json({error:'Not found'},404);
      await db(env).prepare('UPDATE alert_events SET status=?,delivered_at=? WHERE id=? AND owner=?').bind('read',new Date().toISOString(),id,owner).run();
      if(['final','missed-final'].includes(event.kind))await db(env).prepare('UPDATE trips SET final_delivered_at=? WHERE id=? AND owner=?').bind(new Date().toISOString(),event.trip_id,owner).run();
      return json({read:true});
    }
    if(path==='/api/subscription'&&request.method==='POST'){
      const s=validateSubscription(await body(request)),id=await hash(s.endpoint);const existing=await db(env).prepare('SELECT owner FROM subscriptions WHERE id=?').bind(id).first();if(existing&&existing.owner!==owner)return json({error:'Subscription belongs to another signed-in user'},409);
      const count=await db(env).prepare('SELECT COUNT(*) AS n FROM subscriptions WHERE owner=?').bind(owner).first();if(!existing&&count.n>=5)return json({error:'Limit of five notification devices'},409);
      await db(env).prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET p256dh=excluded.p256dh,auth=excluded.auth').bind(id,owner,s.endpoint,s.keys.p256dh,s.keys.auth,new Date().toISOString()).run();return json({enabled:true});
    }
    if(path==='/api/subscription'&&request.method==='DELETE'){await db(env).prepare('DELETE FROM subscriptions WHERE owner=?').bind(owner).run();return json({enabled:false});}
    if(path==='/api/comfort'&&request.method==='POST'){
      const b=await body(request);if(!regionById(b.region)||!Number.isInteger(b.rating)||b.rating<1||b.rating>10||!['outbound','fishing','return'].includes(b.phase))throw new ClientError('invalid feedback');
      for(const [key,max] of [['wind',200],['sea',100],['period',60],['heading',360]])if(b[key]!=null&&(typeof b[key]!=='number'||!Number.isFinite(b[key])||b[key]<0||b[key]>max))throw new ClientError('invalid feedback context');
      if(b.point!=null&&!regions[b.region].forecast_points.some(p=>p.id===b.point))throw new ClientError('invalid feedback point');
      await db(env).prepare('INSERT INTO comfort_feedback(id,owner,region,observed_at,rating,context) VALUES(?,?,?,?,?,?)').bind(crypto.randomUUID(),owner,b.region,new Date().toISOString(),b.rating,JSON.stringify({phase:b.phase,wind:b.wind??null,sea:b.sea??null,period:b.period??null,heading:b.heading??null,point:b.point??null})).run();return json({saved:true},201);
    }
    if(path==='/api/comfort'&&request.method==='GET')return json({feedback:(await db(env).prepare('SELECT * FROM comfort_feedback WHERE owner=? ORDER BY observed_at DESC LIMIT 100').bind(owner).all()).results});
    if(path==='/api/privacy'&&request.method==='GET')return json({trips:(await db(env).prepare('SELECT * FROM trips WHERE owner=?').bind(owner).all()).results,feedback:(await db(env).prepare('SELECT * FROM comfort_feedback WHERE owner=?').bind(owner).all()).results,events:(await db(env).prepare('SELECT message,created_at,status FROM alert_events WHERE owner=?').bind(owner).all()).results});
    if(path==='/api/privacy'&&request.method==='DELETE'){
      await db(env).batch([db(env).prepare('DELETE FROM delivery_receipts WHERE event_id IN (SELECT id FROM alert_events WHERE owner=?)').bind(owner),...['trips','subscriptions','alert_events','comfort_feedback'].map(t=>db(env).prepare(`DELETE FROM ${t} WHERE owner=?`).bind(owner))]);return json({deleted:true});
    }
    return json({error:'Not found'},404);
  }catch(error){const client=error instanceof ClientError,limited=error instanceof RateLimited,message=error.message||'';console.error('SkipperCast request failed',{path,type:client?'validation':limited?'rate':'dependency'});return json({error:limited?'Please try again shortly':client?message:'This service is temporarily unavailable. Your existing records are preserved.'},limited?429:client?400:503);}
}

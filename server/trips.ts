// Saved trips, push subscriptions and alert delivery: validation, the trip
// check (per trip, per owner for the queue, paged for the manual job), and retention.
import {buildPushPayload} from '@block65/webcrypto-web-push';
import {assessTrip,alertDecision,alertMessage,dateInZone} from './alert-policy.ts';
import type {Assessment} from './alert-policy.ts';
import {readFeed} from './feeds.ts';
import {regions,deployment,regionById} from './config.ts';
import {db,hash} from './http.ts';
import {ClientError} from './errors.ts';
import type {Env} from './env.ts';
import type {TripRow,AlertEventRow,SubscriptionRow,ExternalJSON,Region,MarineZones} from './types.ts';

export interface PushSubscriptionInput {endpoint:string;keys:{p256dh:string;auth:string}}
export function validateSubscription(s:ExternalJSON):PushSubscriptionInput{
  if(typeof s?.endpoint!=='string'||!s.keys||typeof s.keys!=='object')throw new ClientError('subscription missing');
  let u:URL;try{u=new URL(s.endpoint);}catch{throw new ClientError('push endpoint rejected');}
  const allowed=u.hostname==='fcm.googleapis.com'||u.hostname==='updates.push.services.mozilla.com'||u.hostname==='web.push.apple.com'||u.hostname.endsWith('.notify.windows.com');
  if(u.protocol!=='https:'||u.port||u.username||u.password||!allowed||u.href.length>2000)throw new ClientError('push endpoint rejected');
  if(!/^[\w-]{87}$/.test(s.keys.p256dh)||!/^[\w-]{22}$/.test(s.keys.auth))throw new ClientError('push keys invalid');return s;
}
export interface TripBoat {sea:number;wind:number;chop_period:number;name:string}
export interface TripInput {region:string;point:string;species:string;date:string;start_hour:number;end_hour:number;wind_limit:number;gust_limit:number;sea_limit:number;boat:TripBoat|null}
export function validateTrip(input:ExternalJSON,now=Date.now()):TripInput{
  const r=regionById(input.region);if(!r||!r.forecast_points.some(p=>p.id===input.point)||!r.species.includes(input.species))throw new ClientError('unknown area or species');
  const today=dateInZone(now,r.timezone),last=dateInZone(now+7*86400000,r.timezone);
  if(!/^\d{4}-\d{2}-\d{2}$/.test(input.date)||!Number.isFinite(Date.parse(input.date))||new Date(input.date).toISOString().slice(0,10)!==input.date||input.date<today||input.date>last)throw new ClientError('date must be within the next seven days');
  for(const [key,min,max] of [['start_hour',0,22],['end_hour',1,23],['wind_limit',1,30],['gust_limit',1,40],['sea_limit',.5,10]] as const)if(typeof input[key]!=='number'||!Number.isFinite(input[key])||input[key]<min||input[key]>max)throw new ClientError('invalid '+key);
  if(!Number.isInteger(input.start_hour)||!Number.isInteger(input.end_hour)||input.end_hour<=input.start_hour||input.gust_limit<input.wind_limit)throw new ClientError('invalid window or thresholds');
  return {...input,boat:validateTripBoat(input.boat)};
}
// The saved boat travels with the trip (profiles live in the browser). Ranges match
// boatFactors() in dist/boat-handling.js; null means the reference boat.
export function validateTripBoat(boat:ExternalJSON):TripBoat|null{
  if(boat===undefined||boat===null)return null;
  if(typeof boat!=='object'||Array.isArray(boat))throw new ClientError('invalid boat');
  const out={} as TripBoat;
  for(const [key,min,max] of [['sea',.45,2.6],['wind',.6,1.8],['chop_period',2,15]] as const)if(typeof boat[key]!=='number'||!Number.isFinite(boat[key])||boat[key]<min||boat[key]>max)throw new ClientError('invalid boat '+key);else out[key]=Math.round(boat[key]*1000)/1000;
  out.name=typeof boat.name==='string'?boat.name.replace(/[\u0000-\u001f\u007f]/g,'').trim().slice(0,80):'';
  return out;
}
export function pushConfigured(env:Env):boolean{return Boolean(env.VAPID_PUBLIC_KEY&&env.VAPID_PRIVATE_KEY);}
async function deliver(env:Env,event:AlertEventRow):Promise<boolean>{
  const subscriptions=(await db(env).prepare('SELECT * FROM subscriptions WHERE owner=?').bind(event.owner).all<SubscriptionRow>()).results;
  if(subscriptions.length&&!pushConfigured(env)){
    // No VAPID pair on this deployment: hold the event without claiming receipts, so the
    // next check after the keys are set delivers it instead of leaving it 'uncertain' forever.
    console.error(JSON.stringify({event:'push_unconfigured',alert:event.id}));
    await db(env).prepare('UPDATE alert_events SET status=? WHERE id=?').bind('held',event.id).run();
    return false;
  }
  let delivered=false;
  for(const s of subscriptions){
    const id=await hash(event.id+':'+s.id);
    const prior=await db(env).prepare('SELECT status FROM delivery_receipts WHERE id=?').bind(id).first<{status:string}>();
    if(prior){if(prior.status==='accepted')delivered=true;continue;}
    const claim=await db(env).prepare('INSERT OR IGNORE INTO delivery_receipts(id,event_id,subscription_id,status,attempt_at) VALUES(?,?,?,?,?)').bind(id,event.id,s.id,'sending',new Date().toISOString()).run();
    if(!claim.meta.changes)continue;
    let status='uncertain',httpStatus:number|null=null;
    try{
      const payload=await buildPushPayload({data:JSON.stringify({title:'SkipperCast trip update',body:event.message.slice(0,1600),eventId:event.id,url:'/#forecast'}),options:{ttl:3600}},
        {endpoint:s.endpoint,expirationTime:null,keys:{p256dh:s.p256dh,auth:s.auth}},{subject:deployment.public_origin,publicKey:env.VAPID_PUBLIC_KEY as string,privateKey:env.VAPID_PRIVATE_KEY as string});
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
// Retention: expired rate-limit rows, sessions and sign-in challenges, 90-day
// trips/events/receipts, 365-day feedback.
// Runs from the Cloudflare cron (scheduled) and after each job page, so it never
// depends on the GitHub Actions chain alone.
export async function prune(env:Env,now=Date.now()):Promise<void>{
  const cutoff=new Date(now-90*86400000).toISOString();
  await db(env).batch([db(env).prepare('DELETE FROM request_limits WHERE expires_at<?').bind(Math.floor(now/1000)),
    db(env).prepare('DELETE FROM sessions WHERE expires_at<?').bind(Math.floor(now/1000)),db(env).prepare('DELETE FROM auth_challenges WHERE expires_at<?').bind(Math.floor(now/1000)),db(env).prepare('DELETE FROM comfort_feedback WHERE observed_at<?').bind(new Date(now-365*86400000).toISOString()),
    db(env).prepare('DELETE FROM delivery_receipts WHERE event_id IN (SELECT id FROM alert_events WHERE created_at<?)').bind(cutoff),db(env).prepare('DELETE FROM alert_events WHERE created_at<?').bind(cutoff),db(env).prepare('DELETE FROM trips WHERE date<?').bind(cutoff.slice(0,10))]);
}
export async function scheduledPrune(env:Env):Promise<'ok'|'failed'|'no-db'>{
  if(!env?.DB)return 'no-db';
  try{await prune(env);return 'ok';}catch(error){console.error('Retention prune failed',{reason:String((error as Error).message).slice(0,200)});return 'failed';}
}
export interface CheckResult {checked:number;changes:number;delivered:number;held:number;in_app:number;next_cursor:string|null}
export type TripOutcome = 'unchanged'|'skipped'|'delivered'|'held'|'in_app';
/** Parsed public inputs, shared by the trips of one check run (or queue batch). */
export type FeedCache = Map<string,Promise<ExternalJSON[]>>;
// Trips still due a check: enabled, and not past their final alert.
const DUE='enabled=1 AND final_delivered_at IS NULL';

async function tripInputs(feeds:FeedCache,feedKey:string,region:Region,zones:MarineZones):Promise<ExternalJSON[]>{
  if(!feeds.has(feedKey))feeds.set(feedKey,Promise.allSettled([readFeed(region.intelligence_feed),readFeed(region.daily_feed),...['coastal','offshore'].map(k=>readFeed('https://api.weather.gov/alerts/active?zone='+zones[k]))])
    .then(loaded=>loaded.map(x=>x.status==='fulfilled'?x.value:null)));
  return feeds.get(feedKey)!;
}

/**
 * Assess one saved trip and deliver its alert when the decision changed. Safe
 * to run more than once for the same inputs (a retried queue message, the
 * manual job and the queue together): the event id is stable for a given
 * decision and both the event and each delivery are claimed with INSERT OR IGNORE.
 */
export async function checkTrip(env:Env,trip:TripRow,now:number,feeds:FeedCache):Promise<{outcome:TripOutcome;created:boolean}>{
  const region=regions[trip.region];if(!region)return {outcome:'skipped',created:false};
  const today=dateInZone(now,region.timezone),tomorrow=dateInZone(now+86400000,region.timezone);
  const hour=Number(new Intl.DateTimeFormat('en-US',{timeZone:region.timezone,hour:'2-digit',hourCycle:'h23'}).format(new Date(now)));
  const pointConfig=region.forecast_points.find(p=>p.id===trip.point), zones=region.contexts?.[pointConfig?.context??'']?.marine_zones||region.marine_zones;
  const inputs=await tripInputs(feeds,trip.region+':'+(pointConfig?.context||'default'),region,zones);
  const intel=inputs[0],rules=inputs[1]?.regulations;
  const offshore=pointConfig?.offshore,alerts=inputs[offshore?3:2]?.features?.map((f:ExternalJSON)=>f.properties);
  const assessment=assessTrip(trip,region,intel,rules,alerts,now);let previous:Assessment|null=null;try{previous=JSON.parse(trip.last_assessment as string);}catch{}
  const final=trip.date===tomorrow&&hour>=18,missed=trip.date<=today&&!trip.final_delivered_at;
  const kind=alertDecision(previous,assessment,{final,missed});if(!kind)return {outcome:'unchanged',created:false};
  const material={status:assessment.status,issues:assessment.issues,values:Object.fromEntries(Object.entries(assessment.values).map(([k,v])=>[k,v===null?null:Math.round(v*10)/10]))};
  const id=await hash(trip.id+':'+(missed?'missed-final':final?'final':kind+':'+(previous?.checked_at||'first')+':'+JSON.stringify(material)));
  const message=alertMessage(trip,region,assessment,kind);
  const insert=await db(env).prepare('INSERT OR IGNORE INTO alert_events(id,trip_id,owner,kind,message,created_at) VALUES(?,?,?,?,?,?)').bind(id,trip.id,trip.owner,kind,message,new Date(now).toISOString()).run();
  const created=Boolean(insert.meta.changes);
  const event=(await db(env).prepare('SELECT * FROM alert_events WHERE id=?').bind(id).first<AlertEventRow>())!;
  const accepted=['delivered','read'].includes(event.status)||event.status==='pending'&&await deliver(env,event);
  if(accepted){await db(env).prepare('UPDATE trips SET last_assessment=?,final_delivered_at=? WHERE id=?').bind(JSON.stringify(assessment),final||missed?new Date(now).toISOString():null,trip.id).run();return {outcome:'delivered',created};}
  const receipt=(await db(env).prepare('SELECT status FROM alert_events WHERE id=?').bind(id).first<{status:string}>())!;
  if(receipt.status==='in-app'){await db(env).prepare('UPDATE trips SET last_assessment=? WHERE id=?').bind(JSON.stringify(assessment),trip.id).run();return {outcome:'in_app',created};}
  return {outcome:'held',created};
}

function tally(trips:TripRow[],results:{outcome:TripOutcome;created:boolean}[]):Omit<CheckResult,'next_cursor'>{
  const count=(o:TripOutcome)=>results.filter(r=>r.outcome===o).length;
  return {checked:trips.length,changes:results.filter(r=>r.created).length,delivered:count('delivered'),held:count('held'),in_app:count('in_app')};
}

/** One page of 25 due trips after `cursor` (the manual and fallback path: POST /api/jobs/check). */
export async function checkTrips(env:Env,cursor=''):Promise<CheckResult>{
  const now=Date.now(),trips=(await db(env).prepare(`SELECT * FROM trips WHERE ${DUE} AND id>? ORDER BY id LIMIT 25`).bind(cursor).all<TripRow>()).results;
  const feeds:FeedCache=new Map(),results=[];
  for(const trip of trips)results.push(await checkTrip(env,trip,now,feeds));
  await prune(env,now);
  return {...tally(trips,results),next_cursor:trips.length===25?trips.at(-1)!.id:null};
}

/** Every due trip of one owner (the queue consumer's unit of work). */
export async function checkOwnerTrips(env:Env,owner:string,now=Date.now(),feeds:FeedCache=new Map()):Promise<Omit<CheckResult,'next_cursor'>>{
  const trips=(await db(env).prepare(`SELECT * FROM trips WHERE owner=? AND ${DUE} ORDER BY id`).bind(owner).all<TripRow>()).results;
  const results=[];
  for(const trip of trips)results.push(await checkTrip(env,trip,now,feeds));
  return tally(trips,results);
}

/** Owners with due trips, in pages (the cron producer). */
export async function ownersWithDueTrips(env:Env,after='',limit=500):Promise<string[]>{
  return (await db(env).prepare(`SELECT DISTINCT owner FROM trips WHERE ${DUE} AND owner>? ORDER BY owner LIMIT ?`).bind(after,limit).all<{owner:string}>()).results.map(r=>r.owner);
}

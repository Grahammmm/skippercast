// Saved trips, push subscriptions and alert delivery: validation, the trip
// check the scheduler pages through, and retention.
import {buildPushPayload} from '@block65/webcrypto-web-push';
import {assessTrip,alertDecision,alertMessage,dateInZone} from './alert-policy.ts';
import type {Assessment} from './alert-policy.ts';
import {readFeed} from './feeds.ts';
import {regions,deployment,regionById} from './config.ts';
import {db,hash} from './http.ts';
import {ClientError} from './errors.ts';
import type {Env} from './env.ts';
import type {TripRow,AlertEventRow,SubscriptionRow,ExternalJSON} from './types.ts';

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
async function deliver(env:Env,event:AlertEventRow):Promise<boolean>{
  const subscriptions=(await db(env).prepare('SELECT * FROM subscriptions WHERE owner=?').bind(event.owner).all<SubscriptionRow>()).results;
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
        {endpoint:s.endpoint,expirationTime:null,keys:{p256dh:s.p256dh,auth:s.auth}},{subject:deployment.public_origin,publicKey:env.VAPID_PUBLIC_KEY!,privateKey:env.VAPID_PRIVATE_KEY!});
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
export async function scheduledPrune(env:Env):Promise<void>{
  if(!env?.DB)return;
  try{await prune(env);}catch(error){console.error('Retention prune failed',{reason:String((error as Error).message).slice(0,200)});}
}
export interface CheckResult {checked:number;changes:number;delivered:number;held:number;in_app:number;next_cursor:string|null}
export async function checkTrips(env:Env,cursor=''):Promise<CheckResult>{
  const now=Date.now(),trips=(await db(env).prepare('SELECT * FROM trips WHERE enabled=1 AND final_delivered_at IS NULL AND id>? ORDER BY id LIMIT 25').bind(cursor).all<TripRow>()).results;
  const feeds=new Map<string,ExternalJSON[]>();let changes=0,delivered=0,held=0,inApp=0;
  for(const trip of trips){
    const region=regions[trip.region];if(!region)continue;
    const today=dateInZone(now,region.timezone),tomorrow=dateInZone(now+86400000,region.timezone);
    const hour=Number(new Intl.DateTimeFormat('en-US',{timeZone:region.timezone,hour:'2-digit',hourCycle:'h23'}).format(new Date(now)));
    let intel,rules,alerts;
    const pointConfig=region.forecast_points.find(p=>p.id===trip.point), zones=region.contexts?.[pointConfig?.context??'']?.marine_zones||region.marine_zones;
    const feedKey=trip.region+':'+(pointConfig?.context||'default');
    if(!feeds.has(feedKey)){
      const loaded=await Promise.allSettled([readFeed(region.intelligence_feed),readFeed(region.daily_feed),...['coastal','offshore'].map(k=>readFeed('https://api.weather.gov/alerts/active?zone='+zones[k]))]);
      feeds.set(feedKey,loaded.map(x=>x.status==='fulfilled'?x.value:null));
    }
    const inputs=feeds.get(feedKey)!;intel=inputs[0];rules=inputs[1]?.regulations;
    const offshore=region.forecast_points.find(p=>p.id===trip.point)?.offshore;alerts=inputs[offshore?3:2]?.features?.map((f:ExternalJSON)=>f.properties);
    const assessment=assessTrip(trip,region,intel,rules,alerts,now);let previous:Assessment|null=null;try{previous=JSON.parse(trip.last_assessment as string);}catch{}
    const final=trip.date===tomorrow&&hour>=18,missed=trip.date<=today&&!trip.final_delivered_at;
    const kind=alertDecision(previous,assessment,{final,missed});if(!kind)continue;
    const material={status:assessment.status,issues:assessment.issues,values:Object.fromEntries(Object.entries(assessment.values).map(([k,v])=>[k,v===null?null:Math.round(v*10)/10]))};
    const id=await hash(trip.id+':'+(missed?'missed-final':final?'final':kind+':'+(previous?.checked_at||'first')+':'+JSON.stringify(material)));
    const message=alertMessage(trip,region,assessment,kind);
    const insert=await db(env).prepare('INSERT OR IGNORE INTO alert_events(id,trip_id,owner,kind,message,created_at) VALUES(?,?,?,?,?,?)').bind(id,trip.id,trip.owner,kind,message,new Date(now).toISOString()).run();
    if(insert.meta.changes)changes++;
    const event=(await db(env).prepare('SELECT * FROM alert_events WHERE id=?').bind(id).first<AlertEventRow>())!;
    const accepted=['delivered','read'].includes(event.status)||event.status==='pending'&&await deliver(env,event);
    if(accepted){delivered++;await db(env).prepare('UPDATE trips SET last_assessment=?,final_delivered_at=? WHERE id=?').bind(JSON.stringify(assessment),final||missed?new Date(now).toISOString():null,trip.id).run();}
    else {
      const receipt=(await db(env).prepare('SELECT status FROM alert_events WHERE id=?').bind(id).first<{status:string}>())!;
      if(receipt.status==='in-app'){inApp++;await db(env).prepare('UPDATE trips SET last_assessment=? WHERE id=?').bind(JSON.stringify(assessment),trip.id).run();}
      else held++;
    }
  }
  await prune(env,now);
  return {checked:trips.length,changes,delivered,held,in_app:inApp,next_cursor:trips.length===25?trips.at(-1)!.id:null};
}

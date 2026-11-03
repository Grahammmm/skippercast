// A day-before final still 'pending' when the trip date arrives (server/trips.ts checkTrip, missedFinal):
// it is sent once more within its 3 tries; accepted marks the trip delivered, anything else raises
// one missed-final. A trip saved on its own date is still skipped after that date.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
globalThis.REGIONS={'morro-bay':read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT=read('../deployments/production.json');
const {checkOwnerTrips,missedFinal}=await import('../server/trips.ts');
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
// Trip day 2026-11-12 (PST, UTC-8); 17:00Z and 20:00Z are 09:00 and 12:00 on the trip date.
const DAY='2026-11-12',BEFORE='2026-11-10T20:00:00.000Z',PUSH='https://fcm.googleapis.com/fcm/send/sub-1';
const MORNING=Date.parse('2026-11-12T17:00:00Z'),NOON=Date.parse('2026-11-12T20:00:00Z'),NEXT_DAY=Date.parse('2026-11-13T17:00:00Z');

// `replies` lists the push service's answers in order (a status number); feeds are unavailable (503).
// `failed` pre-records that many 'failed' receipts (http `failedStatus`) for the pending final.
async function scenario(run,{replies=[],failed=1,failedStatus=429,keys=true,final='pending',created_at=BEFORE}={}){
  const {sql,adapter}=database(),original=globalThis.fetch,env={DB:adapter,...(keys?await vapid():{})};let pushes=0;
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)').run('trip-1','alice','morro-bay','north','reef',DAY,7,13,8,12,3,created_at);
  const k=await pushKeys();
  sql.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)').run('sub-1','alice',PUSH,k.p256dh,k.auth,BEFORE);
  const finalId=await hash('trip-1:final'),receiptId=n=>hash(finalId+':sub-1'+(n>1?':'+n:''));
  if(final){
    sql.prepare('INSERT INTO alert_events(id,trip_id,owner,kind,message,status,created_at) VALUES(?,?,?,?,?,?,?)').run(finalId,'trip-1','alice','final','m',final,'2026-11-12T03:00:00.000Z');
    for(let n=1;n<=failed;n++)sql.prepare('INSERT INTO delivery_receipts(id,event_id,subscription_id,status,http_status,attempt_at) VALUES(?,?,?,?,?,?)').run(await receiptId(n),finalId,'sub-1','failed',failedStatus,'2026-11-12T03:00:00.000Z');
  }
  globalThis.fetch=async url=>{
    if(String(url)!==PUSH)return new Response('{}',{status:503});
    const reply=replies[pushes++];assert.ok(reply!==undefined,'unexpected push '+pushes);
    return new Response(null,{status:reply});
  };
  const ctx={sql,
    check:now=>checkOwnerTrips(env,'alice',now,new Map()),
    kinds:()=>sql.prepare('SELECT kind FROM alert_events ORDER BY created_at,kind').all().map(r=>r.kind),
    pushes:()=>pushes,
    finalReceipts:()=>sql.prepare('SELECT status,http_status FROM delivery_receipts WHERE event_id=? ORDER BY attempt_at,rowid').all(finalId).map(r=>r.status+':'+r.http_status),
    receipt:async n=>{const r=sql.prepare('SELECT status,http_status FROM delivery_receipts WHERE id=?').get(await receiptId(n));return r?{...r}:null;},
    finalStatus:()=>sql.prepare('SELECT status FROM alert_events WHERE id=?').get(finalId)?.status,
    finalAt:()=>sql.prepare('SELECT final_delivered_at FROM trips').get().final_delivered_at};
  try{await run(ctx);}finally{globalThis.fetch=original;sql.close();}
}

test('missedFinal: pending counts as missed only when the caller says its retry failed',()=>{
  const trip={date:DAY,created_at:BEFORE,final_delivered_at:null};
  assert.equal(missedFinal(trip,DAY,'America/Los_Angeles','pending'),false,'default: not missed');
  assert.equal(missedFinal(trip,DAY,'America/Los_Angeles','pending',true),true,'retry failed');
  assert.equal(missedFinal(trip,'2026-11-11','America/Los_Angeles','pending',true),false,'before the trip date');
  assert.equal(missedFinal({...trip,final_delivered_at:'2026-11-12T03:00:00.000Z'},DAY,'America/Los_Angeles','pending',true),false,'already delivered');
  for(const status of ['in-app','read','delivered'])assert.equal(missedFinal(trip,DAY,'America/Los_Angeles',status,true),false,status);
});

test('pending final, retry accepted on the trip date: one delivery, final_delivered_at set, no missed-final',()=>scenario(async({check,kinds,pushes,receipt,finalStatus,finalAt})=>{
  const day=await check(MORNING);
  assert.equal(day.delivered,1);assert.equal(day.changes,0,'no new event');assert.equal(pushes(),1,'exactly one push');
  assert.deepEqual(await receipt(2),{status:'accepted',http_status:201},'second attempt of the original final');
  assert.equal(finalStatus(),'delivered');assert.equal(finalAt(),new Date(MORNING).toISOString());
  assert.deepEqual(kinds(),['final']);
  const again=await check(NOON);
  assert.equal(again.checked,0,'trip no longer due');assert.equal(pushes(),1,'never sent twice');assert.deepEqual(kinds(),['final']);
},{replies:[201]}));

test('pending final, retry 429 again: missed-final raised once; a second check the same day raises nothing new',()=>scenario(async({check,kinds,pushes,receipt,finalStatus,finalAt})=>{
  const day=await check(MORNING);
  assert.equal(day.changes,1);assert.deepEqual(kinds(),['final','missed-final']);
  assert.deepEqual(await receipt(2),{status:'failed',http_status:429});assert.equal(finalAt(),null);
  // Second check: the final's third and last try (429 again, now held) and the missed-final's retry; no new event.
  const again=await check(NOON);
  assert.equal(again.changes,0,'missed-final not duplicated');assert.deepEqual(kinds(),['final','missed-final']);
  assert.deepEqual(await receipt(3),{status:'failed',http_status:429});assert.equal(finalStatus(),'held');
  assert.equal(pushes(),4);
  const third=await check(NEXT_DAY);
  assert.equal(third.changes,0);assert.deepEqual(kinds(),['final','missed-final']);assert.equal(await receipt(4),null,'never a fourth try');
},{replies:[429,429,429,429,429]}));

test('pending final with all 3 attempts used: no new push for the final, missed-final raised',()=>scenario(async({check,kinds,finalReceipts,finalStatus,pushes})=>{
  const day=await check(MORNING);
  assert.equal(day.changes,1);assert.deepEqual(kinds(),['final','missed-final']);
  assert.deepEqual(finalReceipts(),['failed:503','failed:503','failed:503'],'no fourth receipt claimed');
  assert.equal(finalStatus(),'held');assert.equal(pushes(),1,'only the missed-final was pushed');
},{failed:3,failedStatus:503,replies:[503]}));

test('pending final whose last receipt is not retryable (400) is not re-sent; missed-final raised',()=>scenario(async({check,kinds,finalReceipts,pushes})=>{
  await check(MORNING);
  assert.deepEqual(kinds(),['final','missed-final']);assert.deepEqual(finalReceipts(),['failed:400']);assert.equal(pushes(),1);
},{failedStatus:400,replies:[503]}));

test('no VAPID pair (pending forever): missed-final shows in-app; no push claimed',()=>scenario(async({sql,check,kinds,pushes,finalStatus})=>{
  const day=await check(MORNING);
  assert.equal(day.changes,1);assert.deepEqual(kinds(),['final','missed-final']);
  assert.equal(pushes(),0);assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM delivery_receipts').get().n,0,'no receipt claimed');
  assert.equal(finalStatus(),'pending');
  const again=await check(NOON);assert.equal(again.changes,0);assert.deepEqual(kinds(),['final','missed-final']);
},{keys:false,failed:0}));

test('a trip saved on its own date is skipped the next day without a push, as today',()=>scenario(async({check,kinds,pushes})=>{
  const next=await check(NEXT_DAY);
  assert.equal(next.checked,1);assert.equal(next.changes,0);assert.equal(next.delivered+next.held+next.in_app,0,'skipped');
  assert.equal(pushes(),0);assert.deepEqual(kinds(),[]);
},{final:null,created_at:'2026-11-12T16:00:00.000Z'}));

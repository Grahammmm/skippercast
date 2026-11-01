// "Missed day-before assessment" (server/trips.ts missedFinal): raised only when the trip
// was saved before its date and its day-before final does not exist or is 'held'.
// A same-day trip gets ordinary assessments; a recorded in-app final is never followed by a missed-final.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
globalThis.REGIONS={'morro-bay':read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT=read('../deployments/production.json');
const {checkOwnerTrips,missedFinal,hadFinalSlot}=await import('../server/trips.ts');
const {hash}=await import('../server/http.ts');
const ZONE='America/Los_Angeles';
assert.equal(REGIONS['morro-bay'].timezone,ZONE);

function database(){
  const sql=new DatabaseSync(':memory:'),journal=read('../drizzle/meta/_journal.json');
  for(const {tag} of [...journal.entries].sort((a,b)=>a.idx-b.idx))sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`,import.meta.url),'utf8'));
  const adapter={prepare(query){let args=[];const statement=sql.prepare(query);return {bind(...a){args=a;return this;},async first(){return statement.get(...args)||null;},async all(){return {results:statement.all(...args)};},async run(){const info=statement.run(...args);return {meta:{changes:Number(info.changes)}};}};},async batch(queries){sql.exec('BEGIN');try{const result=[];for(const q of queries)result.push(await q.run());sql.exec('COMMIT');return result;}catch(e){sql.exec('ROLLBACK');throw e;}}};
  return {sql,adapter};
}
// Trip day 2026-11-12 (PST, UTC-8).
const DAY='2026-11-12',BEFORE='2026-11-10T20:00:00.000Z';
const at=iso=>Date.parse(iso);
const EVENING_BEFORE=at('2026-11-12T03:00:00Z'),MORNING=at('2026-11-12T17:00:00Z'),NOON=at('2026-11-12T20:00:00Z'),NEXT_DAY=at('2026-11-13T17:00:00Z');

async function scenario(run,{date=DAY,created_at=BEFORE,subscribed=false}={}){
  const {sql,adapter}=database(),originalFetch=globalThis.fetch;let fetches=0;
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)').run('trip-1','alice','morro-bay','north','reef',date,7,13,8,12,3,created_at);
  if(subscribed)sql.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)').run('sub-1','alice','https://fcm.googleapis.com/fcm/send/x','p','a',BEFORE);
  globalThis.fetch=async()=>{fetches++;return Response.json({},{status:503});};
  const check=now=>checkOwnerTrips({DB:adapter},'alice',now,new Map());
  const kinds=()=>sql.prepare('SELECT kind FROM alert_events ORDER BY created_at,kind').all().map(r=>r.kind);
  try{await run({sql,check,kinds,fetches:()=>fetches});}finally{globalThis.fetch=originalFetch;sql.close();}
}

test('missedFinal and hadFinalSlot: every argument combination, without D1',()=>{
  const trip={date:DAY,created_at:BEFORE,final_delivered_at:null};
  assert.equal(missedFinal(trip,DAY,ZONE,null),true,'no final event on the trip date');
  assert.equal(missedFinal(trip,'2026-11-13',ZONE,null),true,'still missed after the date');
  assert.equal(missedFinal(trip,'2026-11-11',ZONE,null),false,'before the trip date');
  assert.equal(missedFinal(trip,DAY,ZONE,'held'),true,'push failed: still warned');
  for(const status of ['in-app','read','delivered','pending'])assert.equal(missedFinal(trip,DAY,ZONE,status),false,status);
  assert.equal(missedFinal({...trip,final_delivered_at:'2026-11-12T03:00:00.000Z'},DAY,ZONE,null),false,'final already delivered');
  assert.equal(missedFinal({...trip,created_at:'2026-11-12T16:00:00.000Z'},DAY,ZONE,null),false,'saved on the trip date (08:00 PST)');
  assert.equal(missedFinal({...trip,created_at:'2026-11-12T16:00:00.000Z'},DAY,ZONE,'held'),false,'same-day trip never had a slot');
  for(const created_at of ['garbage','',null])assert.equal(missedFinal({...trip,created_at},DAY,ZONE,null),true,`unparsable created_at ${JSON.stringify(created_at)} counts as saved before`);
  // Zone edge: 06:30Z is 23:30 PDT the evening before; 07:30Z is 00:30 on the trip date.
  assert.equal(hadFinalSlot({date:'2026-11-01',created_at:'2026-11-01T06:30:00Z'},ZONE),true);
  assert.equal(hadFinalSlot({date:'2026-11-01',created_at:'2026-11-01T07:30:00Z'},ZONE),false);
  assert.equal(missedFinal({date:'2026-11-01',created_at:'2026-11-01T06:30:00Z',final_delivered_at:null},'2026-11-01',ZONE,null),true);
  assert.equal(missedFinal({date:'2026-11-01',created_at:'2026-11-01T07:30:00Z',final_delivered_at:null},'2026-11-01',ZONE,null),false);
});

test('a trip saved two days before with no final gets one missed-final on its date',()=>scenario(async({check,kinds})=>{
  const first=await check(MORNING);assert.equal(first.changes,1);assert.deepEqual(kinds(),['missed-final']);
  const again=await check(NOON);assert.equal(again.changes,0,'the missed-final is not duplicated');assert.deepEqual(kinds(),['missed-final']);
}));

test('a same-day trip gets initial then update, never missed-final, and is skipped without a fetch the next day',()=>scenario(async({sql,check,kinds,fetches})=>{
  const first=await check(MORNING);assert.equal(first.changes,1);assert.equal(first.in_app,1);assert.deepEqual(kinds(),['initial']);
  // A changed assessment later the same day is an ordinary update.
  const previous=JSON.parse(sql.prepare('SELECT last_assessment FROM trips').get().last_assessment);
  sql.prepare('UPDATE trips SET last_assessment=?').run(JSON.stringify({...previous,status:'above limits',checked_at:'2026-11-12T18:00:00.000Z'}));
  const later=await check(NOON);assert.equal(later.changes,1);assert.deepEqual(kinds(),['initial','update']);
  const before=fetches();
  const next=await check(NEXT_DAY);
  assert.equal(next.checked,1);assert.equal(next.changes,0);assert.equal(next.delivered+next.held+next.in_app,0,'skipped, not assessed');
  assert.equal(fetches(),before,'no feed read for a skipped trip');assert.deepEqual(kinds(),['initial','update']);
},{created_at:'2026-11-12T16:00:00.000Z'}));

test('an unread in-app final recorded the evening before is not followed by a missed-final',()=>scenario(async({sql,check,kinds})=>{
  const evening=await check(EVENING_BEFORE);assert.equal(evening.in_app,1);assert.deepEqual(kinds(),['final']);
  assert.equal(sql.prepare('SELECT status FROM alert_events').get().status,'in-app');
  assert.equal(sql.prepare('SELECT final_delivered_at FROM trips').get().final_delivered_at,null,'unread, so the trip stays due');
  await check(MORNING);await check(NOON);
  assert.ok(!kinds().includes('missed-final'),kinds().join(','));
}));

test('a held push final still raises missed-final on the trip date',()=>scenario(async({sql,check,kinds})=>{
  sql.prepare('INSERT INTO alert_events(id,trip_id,owner,kind,message,status,created_at) VALUES(?,?,?,?,?,?,?)').run(await hash('trip-1:final'),'trip-1','alice','final','m','held','2026-11-12T03:00:00.000Z');
  const day=await check(MORNING);assert.equal(day.changes,1);assert.deepEqual(kinds(),['final','missed-final']);
},{subscribed:true}));

test('garbage created_at counts as saved before: missed-final on the trip date',()=>scenario(async({check,kinds})=>{
  await check(MORNING);assert.deepEqual(kinds(),['missed-final']);
},{created_at:'garbage'}));

test('zone edge: saved 23:30 PDT the evening before (06:30Z on the trip date) had a slot',()=>scenario(async({check,kinds})=>{
  await check(at('2026-11-01T17:00:00Z'));assert.deepEqual(kinds(),['missed-final']);
},{date:'2026-11-01',created_at:'2026-11-01T06:30:00.000Z'}));

test('zone edge: saved 00:30 PDT on the trip date had no slot',()=>scenario(async({check,kinds})=>{
  await check(at('2026-11-01T17:00:00Z'));assert.deepEqual(kinds(),['initial']);
},{date:'2026-11-01',created_at:'2026-11-01T07:30:00.000Z'}));

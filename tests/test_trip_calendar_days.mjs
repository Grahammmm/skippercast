// RF1650-6: the saved-trip window ("next seven days") and checkTrip's "tomorrow" are counted in
// calendar days of the region zone, not 24-hour steps, so DST weeks neither lose nor gain a day.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
globalThis.REGIONS={'morro-bay':read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT=read('../deployments/production.json');
const {validateTrip,checkTrip}=await import('../server/trips.ts');
assert.equal(REGIONS['morro-bay'].timezone,'America/Los_Angeles');

const base={region:'morro-bay',point:'north',species:'reef',start_hour:7,end_hour:13,wind_limit:8,gust_limit:12,sea_limit:3};
const ok=(date,now)=>assert.equal(validateTrip({...base,date},Date.parse(now)).date,date,`${date} accepted at ${now}`);
const refused=(date,now)=>assert.throws(()=>validateTrip({...base,date},Date.parse(now)),/date must be within the next seven days/,`${date} refused at ${now}`);

test('fall-back week: a save at 00:30 PDT still reaches today+7, not one day past it',()=>{
  const now='2026-10-28T07:30:00Z';// 2026-10-28 00:30 PDT; clocks fall back 2026-11-01
  ok('2026-10-28',now);ok('2026-11-04',now);
  refused('2026-11-05',now);refused('2026-10-27',now);
});

test('spring-forward week: a save at 23:30 PST stops at today+7, never today+8',()=>{
  const now='2027-03-08T07:30:00Z';// 2027-03-07 23:30 PST; clocks spring forward 2027-03-14
  ok('2027-03-07',now);ok('2027-03-14',now);
  refused('2027-03-15',now);refused('2027-03-06',now);
});

test('ordinary day: today and today+7 accepted, yesterday and today+8 refused (unchanged)',()=>{
  const now='2026-10-15T19:00:00Z';// 2026-10-15 12:00 PDT
  ok('2026-10-15',now);ok('2026-10-22',now);
  refused('2026-10-14',now);refused('2026-10-23',now);
});

test('month and year roll-over count calendar days',()=>{
  const now='2026-12-28T18:00:00Z';// 2026-12-28 10:00 PST
  ok('2027-01-04',now);refused('2027-01-05',now);
  ok('2026-12-31',now);refused('2026-12-27',now);
});

test('malformed dates are still refused with the same words',()=>{
  for(const date of ['2026-02-30','2026-10-1','tomorrow','',null])refused(date,'2026-10-15T19:00:00Z');
});

function database(){
  const sql=new DatabaseSync(':memory:'),journal=read('../drizzle/meta/_journal.json');
  for(const {tag} of [...journal.entries].sort((a,b)=>a.idx-b.idx))sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`,import.meta.url),'utf8'));
  const adapter={prepare(query){let args=[];const statement=sql.prepare(query);return {bind(...a){args=a;return this;},async first(){return statement.get(...args)||null;},async all(){return {results:statement.all(...args)};},async run(){const info=statement.run(...args);return {meta:{changes:Number(info.changes)}};}};},async batch(queries){for(const q of queries)await q.run();}};
  return {sql,adapter};
}
// One check of a 2027-03-14 trip (saved days before) at `now`; feeds are stubbed (503), no network.
async function checkAt(now){
  const {sql,adapter}=database(),originalFetch=globalThis.fetch;
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)').run('trip-1','alice','morro-bay','north','reef','2027-03-14',7,13,8,12,3,'2027-03-10T20:00:00.000Z');
  globalThis.fetch=async()=>Response.json({},{status:503});
  try{
    const trip=sql.prepare('SELECT * FROM trips WHERE id=?').get('trip-1');
    const result=await checkTrip({DB:adapter},trip,Date.parse(now),new Map());
    return {result,kinds:sql.prepare('SELECT kind FROM alert_events').all().map(r=>r.kind)};
  }finally{globalThis.fetch=originalFetch;sql.close();}
}

test('checkTrip: 23:30 PST the night before spring-forward is the trip-eve final, as at 18:00',async()=>{
  for(const now of ['2027-03-14T07:30:00Z','2027-03-14T02:00:00Z']){// 03-13 23:30 PST, 03-13 18:00 PST
    const {result,kinds}=await checkAt(now);
    assert.deepEqual(kinds,['final'],now);assert.equal(result.outcome,'in_app',now);
  }
});

test('checkTrip: not final before 18:00 on the eve, nor two evenings before',async()=>{
  for(const now of ['2027-03-14T01:00:00Z','2027-03-13T07:30:00Z']){// 03-13 17:00 PST, 03-12 23:30 PST
    const {kinds}=await checkAt(now);
    assert.deepEqual(kinds,['initial'],now);
  }
});

import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';
import {mkdtemp, readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {pathToFileURL} from 'node:url';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import dailyFixture from './fixtures/brief/monterey-daily.json' with {type:'json'};
import reportFixture from './fixtures/coast/skippercast-report.json' with {type:'json'};
const ROOT = new URL('..', import.meta.url).pathname;
const NOW = new Date('2026-10-08T21:00:00Z'), ID = 'morro-bay';
const INFO = {id:ID,name:'Morro Bay',center:[35.34,-120.965],timezone:'America/Los_Angeles',localAreas:[{id:'estero-bay',name:'Estero Bay',bounds:[-121.05,35.32,-120.78,35.47]}]};
const daily = {...dailyFixture,region_id:ID,part:'brief',catch_probability:null,bite_score:null};
const conditions = {schema_version:1,region_id:ID,sources:{}};
function forecast() {
  const time = Array.from({length:192},(_,i)=>Date.parse('2026-10-08T07:00Z')/1000+i*3600);
  const series = values => ({utc_offset_seconds:0,hourly_units:{time:'unixtime',...Object.fromEntries(Object.entries(values).map(([k,[,u]])=>[k,u]))},hourly:{time,...Object.fromEntries(Object.entries(values).map(([k,[v]])=>[k,time.map(()=>v)]))}});
  const meta={last_run_initialisation_time:NOW.getTime()/1000-6*3600,data_end_time:time.at(-1)};
  return {region_id:ID,retrieved:NOW.getTime()-1200000,requested_points:[['estero',35.34,-120.965]],models:{gfs_global:{meta,data:[series({wind_speed_10m:[9,'kn'],wind_gusts_10m:[14,'kn'],wind_direction_10m:[300,'°'],temperature_2m:[60,'°F'],cloud_cover:[30,'%']})]},ncep_gfswave016:{meta,data:[series({wave_height:[5.1,'ft'],wave_period:[12,'s']})]}}};
}
let href, serial=0;
async function load() {
  if (!href) {
    const out=join(await mkdtemp(join(tmpdir(),'settled-verdict-')),'m.mjs');
    await build({stdin:{resolveDir:ROOT,loader:'ts',contents:`
      export * from './web/brief/Brief.tsx';
      export {createVerdictLoad} from './web/brief/verdict-load.ts';
      export * from './web/brief/saved-brief.ts';
      export {parseConditionsForecast} from './web/conditions.ts';
      export {createCoastData} from './web/coast-data.ts';
      export {regionPlace} from './web/map/currents.ts';
      export {regionInfo} from './web/app/region-info.ts';
      export {FirstAnswerLine} from './web/app/FirstAnswerLine.tsx';
      export {dayVerdicts,withVerdicts} from './web/app/day-verdicts.ts';
      export {dockPending} from './web/dock-selection.ts';
      export {region,hour,profile} from './web/state.ts';
      export {render} from 'preact-render-to-string'; export {h} from 'preact';`},bundle:true,platform:'node',format:'esm',outfile:out,jsx:'automatic',jsxImportSource:'preact',plugins:rendererPlugins,logLevel:'silent'});
    href=pathToFileURL(out).href;
  }
  delete globalThis.document;
  return import(`${href}?${++serial}`);
}
const flush = () => new Promise(resolve=>setImmediate(resolve));
const response = data => new Response(JSON.stringify(data));
const permutations = xs => xs.length ? xs.flatMap((x,i)=>permutations(xs.filter((_,j)=>i!==j)).map(rest=>[x,...rest])) : [[]];
const memory = () => { const map=new Map(); return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v)}; };
function render(m) {
  return [m.render(m.h(m.Verdict,{now:NOW})),m.render(m.h(m.FirstAnswerLine,{now:NOW}))];
}
function assertPresentation(m, final, label) {
  const view=m.verdictPresentation(NOW), htmls=render(m);
  const chips=m.dayVerdicts(NOW,INFO.timezone).value;
  if (!m.verdictEpoch.value?.sealed) assert.equal(chips.size,0,label+' no unlabelled chip verdict');
  for (const html of htmls) {
    if (view.state==='pending') {
      assert.match(html,/aria-busy="true"/); assert.match(html,/Updating/);
      assert.doesNotMatch(html,/app-verdict-word|data-fishable="|data-verdict="|app-verdict-limit|app-verdict-rules/);
    } else if (view.state==='saved') {
      assert.ok(view.saved,label+' saved clocks'); assert.match(html,/data-saved="/);
    } else if (view.state==='live') assert.equal(view.verdict?.verdict,final,label+' only final word');
    else { assert.match(html,/Couldn&#39;t load the forecast|Couldn't load the forecast/); assert.doesNotMatch(html,/app-verdict-word|data-fishable="/); }
  }
}
async function scenario(m,{saved=false,failure=null,fallback=false}={}) {
  m.region.value=ID; m.beginVerdictRegion(ID); m.regionInfo.value=INFO; m.noteRegionInfo(ID);
  const pending=new Map(), calls=[];
  globalThis.fetch = path => {
    path=String(path);calls.push(path);
    const source=path.includes('forecast')?'forecast':path.includes('/api/coast/')?'coast':path.includes('/feeds/conditions/')?'conditions':'daily';
    if (fallback && path.startsWith('/api/daily')) return Promise.resolve(new Response('',{status:404}));
    return new Promise(resolve=>pending.set(source,resolve));
  };
  const data=m.createCoastData({clockEvents:null});
  const stop=m.bindBriefReport(()=>m.regionPlace(INFO,'boat',''),data);
  const feeds=m.loadDailyFeed(ID), fc=m.ensureRegionalForecast(ID,INFO.center,globalThis.fetch,'https://skippercast.test/map');
  const report={...reportFixture,generatedAt:NOW.toISOString()};
  const parsed=m.parseConditionsForecast(forecast(),ID,INFO.center);
  const reportSnapshot={data:report,expiresAt:new Date(NOW.getTime()+3*3600000).toISOString()};
  const binding=data.coastBinding.value;
  const expected=m.briefFrom({info:INFO,feed:m.mergeFeeds(daily,conditions),forecast:parsed,coast:binding?{report,areaId:binding.areaId}:null,profile:'boat',hour:m.leadHour(null,null,NOW,INFO.timezone)},NOW);
  // Independent engine result from the complete fixture set, not the controller's output.
  const final=m.currentVerdict; // raw engine accessor uses the same forecast once loaded below
  const store=memory();m.enableSavedBrief(store);
  m.writeSaved(store,ID,{at:NOW.getTime()-3600000,data:daily},{at:NOW.getTime()-3600000,data:parsed},m.displayedRegion(INFO));
  const outcomes={daily,conditions,forecast:forecast(),coast:report};
  return {pending,calls,expected,parsed,reportSnapshot,async event(source) {
    if(source==='saved'){if(saved)m.showSavedBrief(ID,NOW.getTime());}
    else {const resolve=pending.get(source);assert.ok(resolve,'request exists for '+source);resolve(source===failure?new Response('',{status:503}):response(outcomes[source]));}
    await flush();
  }, async done(){await Promise.all([feeds,fc]);stop();data.destroy();m.verdictLoad.reset();}, final};
}

test('every_arrival_order_only_final_word: real producers, both rendered answers and date-only chips, with or without saved restoration',async()=>{
  const oldNow=Date.now;Date.now=()=>NOW.getTime();
  try {
    for(const saved of [false,true]) for(const order of permutations(saved?['daily','conditions','forecast','coast','saved']:['daily','conditions','forecast','coast'])) {
      const m=await load(), s=await scenario(m,{saved});
      // Compute final from the same pure assessor with complete fixtures.
      const at=m.leadHour(null,null,NOW,INFO.timezone);
      const token=m.verdictLoad.peek().generation;
      assertPresentation(m,null,order.join(','));
      for(const source of order) {
        await s.event(source);
        const epoch=m.verdictEpoch.value;
        assert.equal(epoch.generation,token);
        const final=m.currentVerdict(s.expected,NOW)?.verdict;
        assertPresentation(m,final,order.join(',')+' after '+source);
      }
      assert.equal(m.verdictEpoch.value.sealed,true);
      assert.equal(m.verdictPresentation(NOW).state,'live');
      assert.ok(m.dayVerdicts(NOW,INFO.timezone).value.size>0);
      assert.equal(s.calls.length,4,'no duplicate reads');
      await s.done();
    }
  } finally {Date.now=oldNow;delete globalThis.fetch;}
});

test('each_input_failure_terminates: each real producer error and daily part/full fallback',async()=>{
  const oldNow=Date.now;Date.now=()=>NOW.getTime();
  try {
    for(const failure of ['daily','conditions','forecast','coast',null]) {
      const m=await load(),s=await scenario(m,{failure,fallback:true});
      for(const source of ['forecast','conditions','coast','daily'])await s.event(source);
      assert.equal(m.verdictEpoch.value.sealed,true,failure);
      assert.notEqual(m.verdictPresentation(NOW).state,'pending',failure);
      if(failure==='forecast'){assert.equal(m.verdictPresentation(NOW).state,'failed');assertPresentation(m,null,failure);}
      assert.equal(s.calls.filter(p=>p.startsWith('/api/daily')).length,1);
      assert.equal(s.calls.filter(p=>p.startsWith('/feeds/data')).length,1);
      await s.done();
    }
  } finally {Date.now=oldNow;delete globalThis.fetch;}
});

test('deadline_19999_20000_and_older_generation: bounded controller ignores duplicate, late, cancelled and A-B-A results; releases timers',async()=>{
  const m=await load();let now=0,timer=null,latest=null;
  const c=m.createVerdictLoad(v=>latest=v,{set:(fn,ms)=>(timer={fn,at:now+ms}),clear:()=>{timer=null;}});
  const a=c.start('A'),b=c.start('B'),a2=c.start('A');
  c.settle(a,'metadata',{state:'loaded',data:INFO});c.settle(b,'forecast',{state:'failed'});
  assert.equal(latest.generation,a2);assert.equal(latest.inputs.metadata.state,'pending');
  now=19999;assert.ok(timer.at>now);assert.equal(latest.sealed,false);
  now=20000;const fire=timer.fn;timer=null;fire();assert.equal(latest.sealed,true);
  assert.ok(Object.values(latest.inputs).every(s=>s.state==='timedout'));
  const sealed=latest;c.settle(a2,'forecast',{state:'loaded',data:{forecast:{},savedAt:null}});assert.equal(latest,sealed);
  c.reset();assert.equal(latest,null);assert.equal(timer,null);
  c.settle(a2,'daily',{state:'failed'});assert.equal(latest,null);
  const d=c.start('D');for(const k of ['metadata','daily','conditions','forecast','coast'])c.settle(d,k,{state:'failed'});
  assert.equal(timer,null);assert.equal(latest.sealed,true);
});

test('coast_context_change_supersedes: a completion captured for an earlier coast binding cannot settle the new binding',async()=>{
  const m=await load();
  m.region.value=ID; m.beginVerdictRegion(ID); m.regionInfo.value=INFO; m.noteRegionInfo(ID);
  const loads=[]; let report=null;
  // The real bindBriefReport over a scripted coast client: the place's local area decides the binding; each load is settled by hand.
  const data={setPlace:p=>p.localId?{areaId:p.localId}:null,load:()=>new Promise(resolve=>loads.push(resolve)),coastReport:{peek:()=>report}};
  const stop=m.bindBriefReport(()=>({regionId:ID,localId:m.hour.value?'area-b':'area-a'}),data);
  const first=m.verdictEpoch.value, tickets=first.tickets;
  for(const source of ['daily','conditions']) m.verdictLoad.settle(tickets[source],source,{state:'loaded',data:{feed:daily,savedAt:null}});
  m.verdictLoad.settle(tickets.forecast,'forecast',{state:'loaded',data:{forecast:m.parseConditionsForecast(forecast(),ID,INFO.center),savedAt:null}});
  assert.equal(m.verdictEpoch.value.inputs.coast.state,'pending','area-a is still loading');
  m.hour.value='2026-10-09T16:00Z';   // the binding moves to area-b while area-a's read is outstanding
  const second=m.verdictEpoch.value;
  assert.ok(second.generation>first.generation,'a new binding is a new generation');
  assert.notEqual(second.tickets.coast,tickets.coast,'with its own coast ticket');
  assert.equal(second.inputs.daily.state,'loaded','the other sources carry over: no second set of reads');
  report={data:{...reportFixture,generatedAt:NOW.toISOString()},expiresAt:new Date(NOW.getTime()+3600000).toISOString()};
  loads[0](); await flush();
  assert.equal(m.verdictEpoch.value.sealed,false,'area-a finishing never settles area-b');
  assert.equal(m.verdictEpoch.value.inputs.coast.state,'pending');
  assert.equal(m.verdictPresentation(NOW).state,'pending');
  m.hour.value='2026-10-09T17:00Z';   // same binding again: no new ask, no new generation
  assert.equal(m.verdictEpoch.value.generation,second.generation);
  loads[1](); await flush();
  const sealed=m.verdictEpoch.value;
  assert.equal(sealed.sealed,true); assert.equal(sealed.inputs.coast.data.areaId,'area-b');
  stop(); m.verdictLoad.reset(); m.hour.value=null;
});

test('same_context_refresh_keeps_the_published_answer: a visible-page refresh never flashes Updating; one that reads nothing keeps its feeds',async()=>{
  const oldNow=Date.now;Date.now=()=>NOW.getTime();
  try {
    const m=await load(), s=await scenario(m);
    for(const source of ['daily','conditions','forecast','coast']) await s.event(source);
    const live=m.verdictPresentation(NOW), sealed=m.verdictEpoch.value;
    assert.equal(live.state,'live');
    const refresh=m.refreshDailyIfStale(NOW.getTime()+31*60000);
    assert.ok(refresh,'the 30-minute rule reads both feeds again');
    assert.ok(m.verdictEpoch.value.generation>sealed.generation && !m.verdictEpoch.value.sealed,'a new generation is under way');
    const during=m.verdictPresentation(NOW);
    assert.equal(during.state,'live'); assert.equal(during.verdict.verdict,live.verdict.verdict,'the published answer stands');
    for(const html of render(m)) assert.doesNotMatch(html,/Updating|aria-busy/);
    s.pending.get('daily')(new Response('',{status:503})); await flush();
    s.pending.get('daily')(new Response('',{status:503}));   // the whole-feed fallback after the part
    s.pending.get('conditions')(new Response('',{status:503}));
    await refresh; await flush();
    const after=m.verdictEpoch.value;
    assert.equal(after.sealed,true);
    assert.equal(after.inputs.daily.state,'failed'); assert.ok(after.inputs.daily.data,'a refresh that read neither keeps the admitted feeds');
    assert.equal(m.verdictPresentation(NOW).verdict.verdict,live.verdict.verdict);
    await s.done();
  } finally {Date.now=oldNow;delete globalThis.fetch;}
});

test('metadata_failure_and_fast_load: failed context ends unavailable; all sources in one turn go Updating to the final word',async()=>{
  const oldNow=Date.now;Date.now=()=>NOW.getTime();
  try {
    const m=await load();m.region.value=ID;m.beginVerdictRegion(ID);m.failVerdictMetadata(ID);
    await m.loadDailyFeed(ID,async()=>new Response('',{status:503}));
    assert.equal(m.verdictEpoch.value.sealed,true,'a failed metadata read ends the load, no permanent Updating');
    assert.equal(m.verdictPresentation(NOW).verdict,null);
    const failed=m.render(m.h(m.Verdict,{now:NOW}));
    assert.match(failed,/<h1>Readings unavailable\.<\/h1>/); assert.doesNotMatch(failed,/Updating|app-verdict-word/);
    const f=await load(), s=await scenario(f);
    const before=render(f);
    for(const html of before){assert.match(html,/Updating/);assert.doesNotMatch(html,/Unknown|app-verdict-word|data-fishable="/);}
    for(const source of ['daily','conditions','forecast','coast']) s.pending.get(source)(response({daily,conditions,forecast:forecast(),coast:{...reportFixture,generatedAt:NOW.toISOString()}}[source]));
    await flush();
    const final=f.verdictPresentation(NOW);
    assert.equal(final.state,'live'); assert.notEqual(final.verdict.verdict,'unknown','the fixture rates the day');
    for(const html of render(f)) assert.doesNotMatch(html,/Updating|aria-busy/);
    await s.done();
  }finally{Date.now=oldNow;delete globalThis.fetch;}
});

test('deadline_through_the_real_loader: a forecast still unread at 20 s ends as a timed-out failure with Try again, never Unknown',async t=>{
  const oldNow=Date.now;Date.now=()=>NOW.getTime();
  t.mock.timers.enable({apis:['setTimeout']});
  try {
    const m=await load(), s=await scenario(m);
    for(const source of ['daily','conditions','coast']) await s.event(source);
    t.mock.timers.tick(19_999); await flush();
    assert.equal(m.verdictEpoch.value.sealed,false,'19,999 ms: still loading');
    assert.equal(m.verdictPresentation(NOW).state,'pending');
    t.mock.timers.tick(1); await flush();
    const epoch=m.verdictEpoch.value, view=m.verdictPresentation(NOW);
    assert.equal(epoch.sealed,true,'20,000 ms: settled');
    assert.equal(epoch.inputs.forecast.state,'timedout');
    assert.equal(view.state,'failed'); assert.equal(view.reason,'timeout');
    for(const html of render(m)) { assert.match(html,/Try again/); assert.doesNotMatch(html,/Unknown|app-verdict-word|data-fishable="/); }
    s.pending.get('forecast')(response(forecast())); await flush();
    assert.equal(m.verdictEpoch.value,epoch,'a late completion cannot reopen or rewrite the sealed snapshot');
    await s.done();
  }finally{Date.now=oldNow;delete globalThis.fetch;}
});

test('a_b_a_reuses_the_forecast_read_under_the_current_epoch: the restarted epoch is answered by the reused read, in flight or cached, never by the older ticket',async()=>{
  const oldNow=Date.now;Date.now=()=>NOW.getTime();
  try {
    for(const cached of [false,true]) {
      const m=await load(), calls=[];let resolve;
      m.region.value=ID;m.beginVerdictRegion(ID);
      const fetchFn=path=>{calls.push(String(path));return new Promise(r=>{resolve=r;});};
      const first=m.verdictEpoch.value.tickets.forecast;
      const read=m.ensureRegionalForecast(ID,INFO.center,fetchFn,'https://skippercast.test/map');
      if(cached){resolve(response(forecast()));await read;}
      m.beginVerdictRegion('other-region'); m.beginVerdictRegion(ID);   // A -> B -> A before B's metadata resolves
      const restarted=m.verdictEpoch.value;
      assert.equal(restarted.inputs.forecast.state,'pending','the restarted epoch has not been answered yet');
      const reused=m.ensureRegionalForecast(ID,INFO.center,fetchFn,'https://skippercast.test/map');
      const current=m.verdictEpoch.value;
      assert.equal(current.generation,restarted.generation,'the reused read joins the current epoch, no new generation');
      assert.notEqual(current.tickets.forecast,first,'under its own ticket, not the older epoch\'s');
      m.verdictLoad.settle(first,'forecast',{state:'failed'});
      if(!cached) assert.equal(m.verdictEpoch.value.inputs.forecast.state,'pending','an older ticket can never settle it');
      if(!cached){resolve(response(forecast()));await reused;await flush();}
      assert.equal(m.verdictEpoch.value.inputs.forecast.state,'loaded','the reused result answers the current epoch, no false timeout');
      assert.equal(m.verdictEpoch.value.tickets.forecast,current.tickets.forecast);
      assert.equal(calls.length,1,'one forecast read for the region and point');
      m.verdictLoad.reset();
    }
  } finally {Date.now=oldNow;delete globalThis.fetch;}
});

test('offline_pack_snapshot_gives_date_only_chips: parts the saved pack answered are saved, so no chip carries a verdict word',async()=>{
  const oldNow=Date.now;Date.now=()=>NOW.getTime();
  try {
    const settleAll=(m,savedAt)=>{
      m.region.value=ID;m.beginVerdictRegion(ID);
      const t=m.verdictEpoch.value.tickets, parsed=m.parseConditionsForecast(forecast(),ID,INFO.center);
      m.verdictLoad.settle(t.metadata,'metadata',{state:'loaded',data:INFO});
      m.verdictLoad.settle(t.daily,'daily',{state:'loaded',data:{feed:daily,savedAt}});
      m.verdictLoad.settle(t.conditions,'conditions',{state:'loaded',data:{feed:conditions,savedAt:null}});
      m.verdictLoad.settle(t.forecast,'forecast',{state:'loaded',data:{forecast:parsed,savedAt:null}});
      m.verdictLoad.settle(t.coast,'coast',{state:'absent'});
    };
    const pack=await load();settleAll(pack,NOW.getTime()-3600000);
    assert.equal(pack.verdictEpoch.value.sealed,true);
    assert.equal(pack.verdictPresentation(NOW).state,'saved'); assert.equal(pack.verdictPresentation(NOW).saved.state,'offline');
    assert.equal(pack.chipsAdmitted(),false,'an offline-pack snapshot admits no chip verdicts');
    const chips=pack.dayVerdicts(NOW,INFO.timezone).value;
    assert.equal(chips.size,0);
    const labels=pack.withVerdicts([{value:'d',label:'Sat'}],chips,'en');
    assert.deepEqual(labels,[{value:'d',label:'Sat'}],'date-only label');
    const fresh=await load();settleAll(fresh,null);
    assert.equal(fresh.verdictPresentation(NOW).state,'live');
    assert.equal(fresh.chipsAdmitted(),true); assert.ok(fresh.dayVerdicts(NOW,INFO.timezone).value.size>0);
  } finally {Date.now=oldNow;delete globalThis.fetch;}
});

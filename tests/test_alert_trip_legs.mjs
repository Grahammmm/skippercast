import test from 'node:test';
import assert from 'node:assert/strict';
import {assessTrip, alertDecision, alertMessage, tripHours, windowInstants} from '../server/alert-policy.ts';

const date='2026-11-02', now=Date.parse('2026-11-01T20:00Z');
const region={id:'r',timezone:'America/Los_Angeles',forecast_points:[{id:'p',name:'Test point',latitude:1,longitude:2}],marine_zones:{coastal:'TEST'},harbor:{information_url:'https://example.test/harbor'}};
const trip={point:'p',date,species:'rockfish',start_hour:7,end_hour:11,wind_limit:15,gust_limit:20,sea_limit:6};
const planned=(window,base=trip)=>({...base,plan:JSON.stringify({window})});
const rules={valid_from:'2026-01-01',valid_through:'2026-12-31',species:{rockfish:{source_ids:[],windows:[{start:'2026-01-01',end:'2026-12-31'}]}}};
function intelligence(t=trip, rough=()=>false, metric='wind', modelOnly=null){
  const time=windowInstants(t.date,region.timezone,0,23);
  const models={}, sources={};
  for(const id of ['gfs_global','ecmwf_ifs025','ncep_gfswave016','ecmwf_wam']){
    const bad=time.map(epoch=>rough(epoch)&&(!modelOnly||modelOnly===id));
    models[id]={meta:{last_run_initialisation_time:now/1000,data_end_time:time.at(-1)},data:[{
      hourly_units:{time:'unixtime',wind_speed_10m:'kn',wind_gusts_10m:'kn',visibility:'m',weather_code:'wmo code',wave_height:'ft',wave_period:'s',wind_wave_height:'ft'},
      hourly:{time,wind_speed_10m:bad.map(b=>b&&metric==='wind'?18:4),wind_gusts_10m:bad.map(b=>b&&metric==='gust'?25:19),visibility:time.map(()=>10000),weather_code:time.map(()=>0),wave_height:bad.map(b=>b&&metric==='sea'?8:2),wave_period:time.map(()=>10),wind_wave_height:bad.map(b=>b&&metric==='chop'?2:.5)}
    }]};
    sources['model-'+id]={status:'ok'};
  }
  return {region_id:'r',completed_at:new Date(now).toISOString(),forecast:{requested_points:[['p',1,2]],models},sources};
}
const at=(h,t=trip)=>new Set(windowInstants(t.date,region.timezone,h,h));
const check=(t,intel=intelligence(t),r=rules,advisories=[])=>assessTrip(t,region,intel,r,advisories,now);
const message=(t,a)=>alertMessage(t,region,a,'update');

test('rough return retracts fishing-only fit, names the return, and never repeats unchanged',()=>{
  const t=planned({return_by:'14:00'}), rough=new Set(windowInstants(date,region.timezone,12,14));
  const intel=intelligence(t,e=>rough.has(e)), before=check(trip,intel), after=check(t,intel);
  assert.equal(before.status,'within limits');assert.equal(after.status,'above limits');
  assert.deepEqual(after.legs,{depart:false,return:true});
  assert.ok(message(t,after).endsWith('\nReturn by 14:00: above saved limits'));
  assert.equal(alertDecision(before,after),'retraction');assert.equal(alertDecision(after,check(t,intel)),null);
  assert.equal(alertDecision(after,{...after,legs:{depart:true,return:false}}),null,'leg labels are not a new event');
});

test('calm extension preserves message and only adds false leg flags',()=>{
  const t=planned({depart:'05:00',return_by:'14:00'}), a=check(t), plain=check(trip);
  assert.equal(a.status,'within limits');assert.deepEqual(a.legs,{depart:false,return:false});
  assert.equal(message(t,a),message(trip,plain));
  const {legs,...rest}=a;assert.equal(JSON.stringify(rest),JSON.stringify(plain));
});

test('partial return hour includes 13, excludes 14; clocks inside fishing hours do not extend',()=>{
  const t=planned({return_by:'13:30'});
  assert.equal(tripHours(t).end,13);
  assert.equal(check(t,intelligence(t,e=>at(13).has(e))).legs.return,true);
  assert.equal(check(t,intelligence(t,e=>at(14).has(e))).status,'within limits');
  const inner=planned({depart:'08:00',return_by:'10:00'});
  assert.equal(JSON.stringify(check(inner)),JSON.stringify(check(trip)));
});

test('each saved metric in either model is judged on each extension, not fishing hours',()=>{
  for(const [metric,model] of [['wind','gfs_global'],['gust','ecmwf_ifs025'],['sea','ecmwf_wam'],['chop','ncep_gfswave016']]){
    for(const [leg,hour] of [['depart',5],['return',14]]){
      const t=planned({depart:'05:00',return_by:'14:00'}), a=check(t,intelligence(t,e=>at(hour).has(e),metric,model));
      assert.equal(a.status,'above limits',metric);assert.equal(a.legs[leg],true,metric);
      assert.equal(a.legs[leg==='depart'?'return':'depart'],false);
      assert.ok(message(t,a).includes(leg==='depart'?'Departure at 05:00: above saved limits':'Return by 14:00: above saved limits'));
    }
    const t=planned({depart:'05:00',return_by:'14:00'}), a=check(t,intelligence(t,e=>at(9).has(e),metric,model));
    assert.equal(a.status,'above limits');assert.deepEqual(a.legs,{depart:false,return:false});
  }
});

test('horizon, missing samples, stale feeds and advisories in the extension remain fail closed',()=>{
  const t=planned({return_by:'14:00'}), intel=intelligence(t);
  intel.forecast.models.ecmwf_ifs025.meta.data_end_time=[...at(11)][0];
  const a=check(t,intel);assert.equal(a.status,'unverified');
  assert.ok(a.issues.includes('ecmwf_ifs025 published horizon does not cover the full window'));
  const missing=intelligence(t);missing.forecast.models.gfs_global.data[0].hourly.time=missing.forecast.models.gfs_global.data[0].hourly.time.filter(e=>!at(14).has(e));
  assert.equal(check(t,missing).status,'unverified');
  const stale=intelligence(t);stale.completed_at='2026-10-30T00:00Z';assert.equal(check(t,stale).status,'unverified');
  const onset=new Date([...at(14)][0]*1000).toISOString();assert.ok(check(t,intelligence(t),rules,[{onset,ends:onset}]).issues.includes('Applicable marine advisory'));
});

test('malformed, absent and overnight plans retain byte-identical assessments',()=>{
  const baseline=JSON.stringify(check(trip));
  for(const plan of [null,'{','null','{}',JSON.stringify({window:{depart:'05:00',return_by:'01:00'}}),JSON.stringify({window:{return_by:'25:00'}}),JSON.stringify({window:{depart:'bad',return_by:'14:00'}}),JSON.stringify({window:{return_by:'13:60'}}),JSON.stringify({window:{return_by:14}})]){
    const t={...trip,plan};assert.equal(JSON.stringify(check(t)),baseline,String(plan));
    assert.deepEqual(tripHours(t),{start:7,end:11,depart:null,ret:null});
  }
});

test('fall-back return extension assesses both real 01:00 hours on the trip date',()=>{
  const base={...trip,date:'2026-11-01',start_hour:0,end_hour:0},t=planned({return_by:'02:00'},base);
  const repeated=[Date.parse('2026-11-01T08:00Z')/1000,Date.parse('2026-11-01T09:00Z')/1000];
  assert.equal(windowInstants(t.date,region.timezone,tripHours(t).start,tripHours(t).end).length,4);
  for(const epoch of repeated){
    const a=check(t,intelligence(t,e=>e===epoch));assert.equal(a.status,'above limits');assert.equal(a.legs.return,true);
    const intel=intelligence(t);intel.forecast.models.gfs_global.data[0].hourly.time=intel.forecast.models.gfs_global.data[0].hourly.time.filter(e=>e!==epoch);
    assert.equal(check(t,intel).status,'unverified');
  }
});

test('season closure remains a legal issue regardless of calm planned legs',()=>{
  const t=planned({return_by:'14:00'}),closed=structuredClone(rules);closed.species.rockfish.windows=[];
  const a=check(t,intelligence(t),closed);assert.equal(a.legal,'closed');assert.equal(a.status,'unverified');
  assert.ok(a.issues.includes('Outside the reviewed species season'));
});

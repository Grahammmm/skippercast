import test from 'node:test';
import assert from 'node:assert/strict';
import {browserPreferences,saveBrowserPreferences,readPreferences,preferenceHeader,forgetPreferenceHeader,homeURL,type HomePreferences} from '../../packages/coast/src/coast3d/preferences.ts';
import {methodMetrics} from '../../packages/coast/src/coast3d/report.ts';
import {createState} from '../../packages/coast/src/state/experience.ts';
import {slo} from '../../packages/coast/src/counties.ts';
import type {Report} from '../../packages/coast/src/types.ts';
const home:HomePreferences={v:1,place:'avila',mode:'spear'};
test('preference cookie is bounded to known sites and methods; malformed and obsolete cookies restart setup',()=>{
 assert.equal(readPreferences(''),null);
 const header=preferenceHeader(home,true);assert.deepEqual(readPreferences('other=keep; '+header),home);
 assert.match(header,/Path=\/; Max-Age=31536000; SameSite=Lax; Secure$/);
 assert.doesNotMatch(preferenceHeader(home,false),/Secure/);
 for(const value of [null,{...home,v:2},{...home,place:'unknown'},{...home,mode:'commercial'},{...home,place:'<script>'}])assert.equal(readPreferences('skippercast_home='+encodeURIComponent(JSON.stringify(value))),null);
 assert.equal(readPreferences('skippercast_home=%FF'),null);assert.match(forgetPreferenceHeader(true),/Max-Age=0/);
 assert.throws(()=>preferenceHeader({...home,place:'unknown'},true));
 const extra={...home,email:'not-kept',location:'not-kept'};assert.deepEqual(readPreferences('skippercast_home='+encodeURIComponent(JSON.stringify(extra))),home);assert.doesNotMatch(preferenceHeader(extra,true),/email|location/);
});
test('bare return visits use saved home; shared links override this visit without mutating saved preferences',()=>{
 const url=homeURL(new URL('https://example.com/'),home);assert.equal(url.search,'?place=avila&profile=spear');assert.deepEqual(home,{v:1,place:'avila',mode:'spear'});
 const shared=homeURL(new URL('https://example.com/?place=carmel&profile=boat&species=lingcod&perspective=2d'),home);assert.equal(shared.search,'?place=carmel&profile=boat&species=lingcod&perspective=2d');
 assert.equal(homeURL(new URL('https://example.com/?area=north'),home).search,'?area=north&profile=spear');
 const reset=homeURL(new URL('https://example.com/?day=2020-01-01&hour=old&species=lingcod#old'),home,true);assert.equal(reset.search,'?place=avila&profile=spear');assert.equal(reset.hash,'');
});
test('blocked or throwing browser cookie storage permits session use and never falsely claims persistence',()=>{
 const blocked={get cookie(){return '';},set cookie(_:string){}};assert.equal(saveBrowserPreferences(blocked,home,true),false);assert.equal(browserPreferences(blocked),null);
 const denied={get cookie():string{throw Error('blocked');},set cookie(_:string){throw Error('blocked');}};assert.equal(saveBrowserPreferences(denied,home,true),false);assert.equal(browserPreferences(denied),null);
 const available={cookie:''};assert.equal(saveBrowserPreferences(available,home,true),true);assert.deepEqual(browserPreferences(available),home);
});
test('method summaries prioritize relevant facts and preserve missing, stale and future-day observation limits',()=>{
 const now=new Date('2026-10-06T18:00:00Z');
 const report:Report={schemaVersion:1,countyId:'slo',generatedAt:now.toISOString(),forecasts:[{id:'central',sourceId:'nws-central',hours:Array.from({length:48},(_,i)=>({at:new Date(+now+i*3600000).toISOString(),windKnots:5,gustKnots:8,waveFt:2,wavePeriodS:10,airTempF:60,precipPct:0}))}],sources:[{id:'nws-central',label:'NWS',url:'https://api.weather.gov',kind:'forecast',outcome:'ok',fetchedAt:now.toISOString(),issuedAt:now.toISOString()},{id:'nws-alerts',label:'Alerts',url:'https://api.weather.gov',kind:'forecast',outcome:'ok',fetchedAt:now.toISOString()}],observations:[{stationId:slo.temperatureStationId,observedAt:now.toISOString(),url:'https://www.ndbc.noaa.gov',waterTempF:58,windKnots:null,gustKnots:null,waveFt:2,wavePeriodS:10}],tides:[],tideEvents:[],alerts:[],catches:[],catchStatus:'Pending',visibility:{status:'unknown',feet:null,observedAt:null,sourceUrl:null},habitatStatus:'Pending'};
 const before=JSON.stringify(report),boat=createState(report,slo,'boat','central',undefined,undefined,now),shore={...boat,mode:'shore' as const},spear={...boat,mode:'spear' as const};
 assert.ok(methodMetrics(boat).indexOf('Wind / gust')<methodMetrics(boat).indexOf('Tide'));
 assert.ok(methodMetrics(shore).indexOf('Tide')<methodMetrics(shore).indexOf('Wind / gust'));assert.match(methodMetrics(shore),/No local model/);
 assert.ok(methodMetrics(spear).indexOf('In-water visibility')<methodMetrics(spear).indexOf('Latest buoy'));assert.match(methodMetrics(spear),/Unknown/);assert.match(methodMetrics(spear),/58.0/);assert.equal(JSON.stringify(report),before);
 report.visibility={status:'observed',feet:15,observedAt:'2026-10-06T10:00:00Z',sourceUrl:'https://example.com'};assert.match(methodMetrics(spear),/Unknown/);
 report.visibility.observedAt=now.toISOString();assert.match(methodMetrics(spear),/15 <small>ft/);
 const future={...spear,date:'2026-10-07'};assert.doesNotMatch(methodMetrics(future),/58.0/);
});

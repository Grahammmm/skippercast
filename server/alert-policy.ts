// Pure, region-independent alert assessment. Threshold fit is not trip clearance.
import type {Region, ExternalJSON} from './types.ts';
import {LONG_PERIOD_SWELL} from '../web/score.ts';
import {BAR_CHECK, barHours, entranceFor} from '../packages/coast/src/bar-conditions.ts';
import type {ForecastHour, TideEvent} from '../packages/coast/src/types.ts';

/** The trip fields an assessment reads (a TripRow, or a trip under test). */
export interface AlertTrip {point: string; date: string; species: string; start_hour: number; end_hour: number; wind_limit: number; gust_limit: number; sea_limit: number; boat_sea?: number | null; boat_name?: string | null; plan?: string | null}
export type Values = {wind: number | null; gust: number | null; sea: number | null; chop: number | null};
export interface Assessment {status: string; legal: string; values: Values; chop_limit?: number; issues: string[]; checked_at: string; runs: Record<string, number | null>; legs?: {depart: boolean; return: boolean}; hazards?: string[]}
export const finite=(n:unknown):n is number=>typeof n==='number'&&Number.isFinite(n);
export function dateInZone(epoch:number,zone:string):string{return new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(epoch));}
const localHour=(t:number,zone:string)=>Number(new Intl.DateTimeFormat('en-US',{timeZone:zone,hour:'2-digit',hourCycle:'h23'}).format(new Date(t*1000)));
const hourWords=(h:number)=>h===0?'midnight':h===12?'noon':h<12?h+' am':(h-12)+' pm';
/** Unix seconds of every real whole UTC hour on `date` (local) with local hour in [start,end]: 01:00 twice on fall-back day, no 02:00 on spring-forward day. */
export function windowInstants(date:string,zone:string,start:number,end:number):number[]{
  const out:number[]=[],day=Date.parse(date+'T00:00Z')/1000;
  if(!finite(day))return out;
  for(let t=day-14*3600;t<=day+(24+14)*3600;t+=3600)if(dateInZone(t*1000,zone)===date&&localHour(t,zone)>=start&&localHour(t,zone)<=end)out.push(t);
  return out;
}
export function samplePoint(data:ExternalJSON,key:string,time:number,unit:string):number|null{
  const h=data?.hourly, i=h?.time?.indexOf(time);
  if(data?.hourly_units?.[key]!==unit||data?.hourly_units?.time!=='unixtime'||i<0||!finite(h?.[key]?.[i]))return null;
  return h[key][i];
}
// Wind chop is judged against 1 ft for the reference 23 ft boat, scaled by the
// saved boat's sea factor (dist/boat-handling.js) when the trip carries one.
export const REFERENCE_CHOP_FT=1;
export function tripChopLimit(trip:Partial<AlertTrip>|null|undefined):number{
  const s=trip?.boat_sea,sea=finite(s)&&s>=.45&&s<=2.6?s:1;
  return Math.round(REFERENCE_CHOP_FT*sea*10)/10;
}
// Advisory time: undefined when absent, null when present but unreadable, else epoch ms.
const advisoryTime=(v:unknown):number|null|undefined=>v===undefined||v===null||v===''?undefined:typeof v==='string'&&finite(Date.parse(v))?Date.parse(v):null;
/** Fail closed: a non-object advisory, or one with a present but unreadable onset/ends/expires, applies. */
export function advisoryApplies(a:unknown,startMs:number|null,endMs:number|null):boolean{
  if(typeof a!=='object'||a===null||Array.isArray(a)||startMs===null||endMs===null)return true;
  const r=a as Record<string,unknown>,onset=advisoryTime(r.onset),ends=advisoryTime(r.ends),end=ends===undefined?advisoryTime(r.expires):ends;
  if(onset===null||end===null)return true;
  return (onset===undefined||onset<=endMs)&&(end===undefined||end>=startMs);
}
const planWindow=(trip:AlertTrip):{depart?:string;return_by?:string}=>{
  try{
    const w=JSON.parse(trip.plan||'null')?.window;
    if(!w||[w.depart,w.return_by].some(v=>v!=null&&(typeof v!=='string'||!/^([01]\d|2[0-3]):[0-5]\d$/.test(v)))||w.depart&&w.return_by&&w.return_by<w.depart)return {};
    return w;
  }catch{return {};}
};
export function tripHours(trip:AlertTrip):{start:number;end:number;depart:number|null;ret:number|null}{
  const w=planWindow(trip),depart=w.depart==null?null:Number(w.depart.slice(0,2)),ret=w.return_by==null?null:Number(w.return_by.slice(0,2));
  return {start:Math.min(trip.start_hour,depart??trip.start_hour),end:Math.max(trip.end_hour,ret??trip.end_hour),depart,ret};
}
/** The feed's own completed_at: finite, at most 3 h old and at most 1 h ahead. */
const feedTimeOk=(intelligence:ExternalJSON,now:number):boolean=>{const t=Date.parse(intelligence?.completed_at);return finite(t)&&now-t<=3*3600000&&t<=now+3600000;};
/** A forecast model the policy reads: source ok, no error, run time finite, at most 36 h old and at most 1 h ahead. */
const modelUsable=(intelligence:ExternalJSON,model:string,now:number):boolean=>{
  const m=intelligence?.forecast?.models?.[model],source=intelligence?.sources?.['model-'+model],run=m?.meta?.last_run_initialisation_time;
  return !(source?.status!=='ok'||m?.error||!finite(run)||now/1000-run>36*3600||run>now/1000+3600);
};
/** Saved-trip bar notes (SC0922-02). The same shared estimate as the brief and the advisor, offshore basis, at the saved forecast point; an estimate, never a status. */
function tripBarNotes(trip:AlertTrip,region:Region,intelligence:ExternalJSON,daily:ExternalJSON,now:number):string[]{
  const entrance=entranceFor(region.id,region.id);
  if(!entrance)return [];
  const lead=(hit:number|null)=>hit===null?`Regional ${entrance.name}: bar not judged for the complete saved window; this does not establish the trip's launch or crossing.`:`Regional ${entrance.name}: the offshore bar estimate reads hazardous at ${hourWords(localHour(hit,region.timezone))}; this does not establish the trip's launch or crossing.`;
  const note=(hit:number|null,partial:boolean,windUnknown:boolean)=>`${lead(hit)} ${BAR_CHECK}${hit!==null&&partial?' The bar was not judged for the complete saved window.':''}${windUnknown?' Wind against the ebb was not judged.':''}`;
  try{
    const hours=tripHours(trip),want=windowInstants(trip.date,region.timezone,hours.start,hours.end);
    const point=region.forecast_points.findIndex(p=>p.id===trip.point);
    const expectedPoints=region.forecast_points.map(p=>[p.id,p.latitude,p.longitude]);
    const identity=point>=0&&intelligence?.region_id===region.id&&JSON.stringify(intelligence?.forecast?.requested_points)===JSON.stringify(expectedPoints)&&feedTimeOk(intelligence,now);
    const models=intelligence?.forecast?.models||{};
    // A sample is read only from a usable model whose published horizon covers that instant.
    const read=(model:string,key:string,t:number,unit:string):number|null=>{
      const m=models[model];
      return identity&&modelUsable(intelligence,model,now)&&finite(m?.meta?.data_end_time)&&t<=m.meta.data_end_time?samplePoint(m?.data?.[point],key,t,unit):null;
    };
    const pair=(h:number|null,p:number|null):[number|null,number|null]=>finite(h)&&h>=0&&finite(p)&&p>0?[h,p]:[null,null];
    const forecast:ForecastHour[]=want.map(t=>{
      const [waveFt,wavePeriodS]=pair(read('ncep_gfswave016','wave_height',t,'ft'),read('ncep_gfswave016','wave_period',t,'s'));
      const [swellFt,swellPeriodS]=pair(read('ncep_gfswave016','swell_wave_height',t,'ft'),read('ncep_gfswave016','swell_wave_period',t,'s'));
      return {at:new Date(t*1000).toISOString(),windKnots:read('gfs_global','wind_speed_10m',t,'kn'),gustKnots:null,windDirectionDeg:read('gfs_global','wind_direction_10m',t,'°'),waveFt,wavePeriodS,swellFt,swellPeriodS};
    });
    const tides=daily?.sources?.tides,tideEvents:TideEvent[]=[];
    if(tides?.status==='ok'&&Array.isArray(tides.data?.predictions))for(const row of tides.data.predictions)if(row&&typeof row==='object'&&finite(row.height_ft)&&typeof row.time==='string'&&(row.type==='H'||row.type==='L'))tideEvents.push({at:row.time,heightFt:row.height_ft,type:row.type});
    const bar=barHours({hours:forecast,site:undefined,entrance,tideEvents});
    const hit=bar.filter(h=>h.band==='Hazardous').map(h=>Date.parse(h.at)/1000).sort((a,b)=>a-b)[0]??null;
    const partial=!bar.length||bar.some(h=>h.swell.heightFt===null||h.swell.periodS===null||h.tide.stage===null||h.band==='Unknown');
    const windUnknown=entrance.seawardDeg===null||!forecast.length||forecast.some(h=>h.windKnots===null||h.windDirectionDeg==null);
    return hit!==null||partial||windUnknown?[note(hit,partial,windUnknown)]:[];
  }catch{return [note(null,true,true)];}
}
export function assessTrip(trip:AlertTrip,region:Region,intelligence:ExternalJSON,rules:ExternalJSON,advisories:ExternalJSON[]|null|undefined,now=Date.now(),daily:ExternalJSON|null=null):Assessment{
  const point=region.forecast_points.findIndex(p=>p.id===trip.point);
  const issues:string[]=[],values:Values={wind:null,gust:null,sea:null,chop:null};
  // Only the four regulated harbours have a bar note; any other region keeps its old assessment shape.
  const early=(message:string):Assessment=>{const bar=tripBarNotes(trip,region,intelligence,daily,now);return {status:'unverified',legal:'unverified',issues:[message],values,checked_at:new Date(now).toISOString(),runs:{},...(bar.length?{hazards:bar}:{})};};
  if(point<0||intelligence?.region_id!==region.id)return early('Regional forecast unavailable');
  const expectedPoints=region.forecast_points.map(p=>[p.id,p.latitude,p.longitude]);
  if(JSON.stringify(intelligence.forecast?.requested_points)!==JSON.stringify(expectedPoints))return early('Forecast locations do not match this regional release');
  if(!feedTimeOk(intelligence,now))issues.push('Forecast feed time is missing, stale or invalid');
  const models=intelligence.forecast?.models||{};
  const base=models.gfs_global?.data?.[point];
  const hours=tripHours(trip),want=windowInstants(trip.date,region.timezone,hours.start,hours.end),have=new Set(base?.hourly?.time||[]);
  const times:number[]=want.filter(t=>have.has(t));
  if(times.length!==want.length||!want.length)issues.push('The complete saved window is not populated');
  const legs=hours.start<trip.start_hour||hours.end>trip.end_hour?{depart:false,return:false}:undefined;
  let leg:'depart'|'return'|null=null;
  const limits:Values={wind:trip.wind_limit,gust:trip.gust_limit,sea:trip.sea_limit,chop:tripChopLimit(trip)};
  // Long-period swell: height and period from the same wave model, point and hour, read only from a usable model. A hazard note, never an issue.
  const swell:{t:number;model:string;height:number;period:number}[]=[];
  const max=(key:keyof Values,value:number|null)=>{if(finite(value)){const v=values[key];values[key]=v===null?value:Math.max(v,value);if(legs&&leg&&value>limits[key]!)legs[leg]=true;}else issues.push('Required '+key+' sample missing');};
  for(const model of ['gfs_global','ecmwf_ifs025','ncep_gfswave016','ecmwf_wam']){
    const m=models[model];
    const usable=modelUsable(intelligence,model,now);
    if(!usable)issues.push(model+' is unavailable or stale');
    for(const t of times){
      const h=localHour(t,region.timezone);leg=h<trip.start_hour?'depart':h>trip.end_hour?'return':null;
      const d=m?.data?.[point];
      if(!finite(m?.meta?.data_end_time)||t>m.meta.data_end_time)issues.push(model+' published horizon does not cover the full window');
      if(model==='gfs_global'||model==='ecmwf_ifs025'){
        const w=samplePoint(d,'wind_speed_10m',t,'kn'),g=samplePoint(d,'wind_gusts_10m',t,'kn');max('wind',w);max('gust',g);
        if(finite(g)&&finite(w)&&g<w)issues.push('Inconsistent gust sample');
        const visibility=samplePoint(d,'visibility',t,'m'),code=samplePoint(d,'weather_code',t,'wmo code');
        if(visibility===null||code===null)issues.push('Visibility or weather hazard check missing');
        if(visibility!==null&&visibility<1609.344||code!==null&&code>=95)issues.push('Fog or thunderstorm signal');
      }else{const period=samplePoint(d,'wave_period',t,'s'),height=samplePoint(d,'wave_height',t,'ft');if(period===null||period<=0)issues.push('Combined wave period unavailable or invalid');max('sea',height);
        if(usable&&finite(m?.meta?.data_end_time)&&t<=m.meta.data_end_time&&finite(height)&&finite(period)&&height>=LONG_PERIOD_SWELL.height&&period>0&&period>=LONG_PERIOD_SWELL.period)swell.push({t,model,height,period});
        if(model==='ncep_gfswave016')max('chop',samplePoint(d,'wind_wave_height',t,'ft'));}
    }
  }
  const species=trip.species==='reef'?['lingcod','rockfish']:[trip.species];
  let legal='reviewed season';
  for(const id of species){
    const p=rules?.species?.[id];
    if(!p||trip.date<rules.valid_from||trip.date>rules.valid_through){issues.push('Trip-date rules unavailable');legal='unverified';continue;}
    const window=p.windows.find((w:ExternalJSON)=>trip.date>=w.start&&trip.date<=w.end);
    if(!window){legal='closed';issues.push('Outside the reviewed species season');}
    else if(window.restriction){legal='restricted';issues.push(window.restriction);}
    else if(window.requires_opening_review){legal='unverified';issues.push('Scheduled opening needs review');}
    if(window?.start_at){
      const opening=Date.parse(window.start_at);
      if(!/T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$/.test(window.start_at)||!finite(opening)||dateInZone(opening,region.timezone)!==window.start){legal='unverified';issues.push('Season opening time is invalid or unavailable');}
      else if(times.some(t=>t*1000<opening)){legal='closed';issues.push('The saved fishing window starts before the legal season opening time');}
    }
    if(p.source_ids.some((s:string)=>{const c=rules.checks?.[s];return c?.status!=='unchanged'||c.source_status!=='ok'||c.content_sha256!==rules.sources?.[s]?.approved_content_sha256||!finite(Date.parse(c.data_retrieved_at))||now-Date.parse(c.data_retrieved_at)>36*3600000;})){
      legal='unverified';issues.push('Rules changed or need a fresh source check');
    }
  }
  if(!Array.isArray(advisories))issues.push('Marine advisories unavailable');
  else if(advisories.some((a:unknown)=>advisoryApplies(a,times.length?times[0]!*1000:null,times.length?times.at(-1)!*1000:null)))issues.push('Applicable marine advisory');
  const chopLimit=tripChopLimit(trip);
  const within=finite(values.wind)&&finite(values.gust)&&finite(values.sea)&&values.wind<=trip.wind_limit&&values.gust<=trip.gust_limit&&values.sea<=trip.sea_limit&&(values.chop as number)<=chopLimit;
  const status=issues.length?'unverified':within?'within limits':'above limits';
  // Earliest real hour wins; ties take the greater height, then period, then model id. Raw values decide, rounded values only display.
  const first=[...swell].sort((a,b)=>a.t-b.t||b.height-a.height||b.period-a.period||(a.model<b.model?-1:a.model>b.model?1:0))[0];
  const hazards=[...first?[`Long-period swell (${Number(first.height.toFixed(1))} ft at ${Math.round(first.period)} s) at ${hourWords(localHour(first.t,region.timezone))}; surge and entrance conditions need a separate check.`]:[],...tripBarNotes(trip,region,intelligence,daily,now)];
  return {status,legal,values,chop_limit:chopLimit,...(legs?{legs}:{}),issues:[...new Set(issues)],checked_at:new Date(now).toISOString(),
    runs:Object.fromEntries(Object.entries(models).map(([id,m]:[string,ExternalJSON])=>[id,m.meta?.last_run_initialisation_time??null])),...(hazards.length?{hazards}:{})};
}

export function alertDecision(previous:Assessment|null,current:Assessment,{final=false,missed=false}={}):string|null{
  if(missed)return 'missed-final';
  if(final)return 'final';
  if(!previous)return 'initial';
  if(previous.status==='within limits'&&current.status!=='within limits')return 'retraction';
  if(previous.status!==current.status||JSON.stringify(previous.issues)!==JSON.stringify(current.issues))return 'update';
  if(JSON.stringify(previous.hazards??[])!==JSON.stringify(current.hazards??[]))return 'update';
  const limits:Record<keyof Values,number>={wind:2,gust:3,sea:.5,chop:.5};
  return (Object.keys(limits) as (keyof Values)[]).some(k=>{const a=previous.values?.[k],b=current.values[k];return finite(a)!==finite(b)||finite(b)&&Math.abs(b-(a as number))>=limits[k];})?'update':null;
}

export function alertMessage(trip:AlertTrip,region:Region,assessment:Assessment,kind:string):string{
  const value=(v:number|null,u:string)=>finite(v)?v.toFixed(1)+' '+u:'unavailable';
  const name=region.forecast_points.find(p=>p.id===trip.point)?.name||trip.point;
  const w=planWindow(trip),legText=(assessment.legs?.depart&&w.depart?`\nDeparture at ${w.depart}: above saved limits`:'')+(assessment.legs?.return&&w.return_by?`\nReturn by ${w.return_by}: above saved limits`:'');
  return `${kind==='retraction'?'No longer within saved limits':kind==='final'?'Day-before assessment':kind==='missed-final'?'Missed day-before assessment':kind==='initial'?'Saved-trip assessment':'Trip update'} · ${trip.date} · ${name}\n${assessment.status}. Window ${trip.start_hour}:00–${trip.end_hour}:00 ${region.timezone}.\nWind ${value(assessment.values.wind,'kt')}; gust ${value(assessment.values.gust,'kt')}; seas ${value(assessment.values.sea,'ft')}; chop ${value(assessment.values.chop,'ft')}.\n${(assessment.hazards??[]).map(note=>`Hazard note: ${note}\n`).join('')}${finite(trip.boat_sea)?`Boat: ${trip.boat_name||'saved boat'} · chop limit ${(assessment.chop_limit??tripChopLimit(trip)).toFixed(1)} ft for this boat.\n`:''}${assessment.issues.join('; ')||'Within your numerical preferences; this does not evaluate route, entrance or catch success.'}\nRules: ${assessment.legal}. Recheck current marine, species and entrance conditions before departure.\nChecked ${assessment.checked_at}. NOAA/ECMWF run times: ${Object.entries(assessment.runs||{}).map(([k,v])=>k+' '+(v?new Date(v*1000).toISOString():'unavailable')).join('; ')}\nhttps://forecast.weather.gov/MapClick.php?TextType=2&zoneid=${(region.contexts?.[region.forecast_points.find(p=>p.id===trip.point)?.context??'']?.marine_zones||region.marine_zones)[region.forecast_points.find(p=>p.id===trip.point)?.offshore?'offshore':'coastal']}\n${region.harbor.information_url}${legText}`;
}

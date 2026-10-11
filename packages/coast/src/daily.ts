import {getMoonIllumination, getTimes} from 'suncalc';
import {assess, freshForecast, freshObservation} from './assessment.ts';
import type {Alert, Area, County, ForecastHour, Mode, Observation, Report, TideEvent, TidePoint, Window} from './types.ts';
import {freshNearshore, nearshoreAt} from './nearshore.ts';
import {SPEAR, SURGE_RANK, clarityText, spearDay, spearHours, surge, surgeText, type SpearDay} from './spear.ts';

export type DailyDay = {date:string;label:string;weekday:string;dayNumber:number;provisional:boolean};
export type DailyBrief = {
 date:string;label:string;headline:string;summary:string;status:'Caution'|'Mixed'|'Unknown';confidence:string;
 hours:ForecastHour[];wind:{min:number|null;max:number|null;gust:number|null};seas:{min:number|null;max:number|null;period:number|null};
 air:{min:number|null;max:number|null};rainPct:number|null;tempObservation:Observation|null;
 tides:TidePoint[];tideEvents:TideEvent[];tideRange:{min:number|null;max:number|null};windows:Window[];
 sunrise:string|null;sunset:string|null;moon:{fraction:number|null;label:string};alerts:Alert[];missing:string[];issuedAt:string|null;
 /** The spear reading (spear.ts); null for the other profiles. */
 spear:SpearDay|null;
};
const HOUR=3_600_000;
const finite=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value);

/** Calendar identity always uses the county's zone, independently of the execution host. */
export function dateKey(at:string|Date,tz:string):string {
 const value=at instanceof Date?at:new Date(at);
 if(!Number.isFinite(value.getTime()))throw new RangeError('Invalid date');
 const parts=new Intl.DateTimeFormat('en-US',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(value);
 const get=(type:string)=>parts.find(part=>part.type===type)!.value;
 return `${get('year')}-${get('month')}-${get('day')}`;
}
function calendarDate(date:string):Date {
 const value=new Date(`${date}T00:00:00Z`);
 if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||!Number.isFinite(value.getTime())||value.toISOString().slice(0,10)!==date)throw new RangeError('Invalid local calendar date');
 return value;
}
function addDay(date:string,days:number):string {
 const value=calendarDate(date);value.setUTCDate(value.getUTCDate()+days);return value.toISOString().slice(0,10);
}
function offsetMinutes(at:Date,tz:string):number {
 const parts=new Intl.DateTimeFormat('en-US',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(at);
 const number=(type:string)=>Number(parts.find(part=>part.type===type)!.value);
 const wall=Date.UTC(number('year'),number('month')-1,number('day'),number('hour'),number('minute'),number('second'));
 return (wall-at.getTime())/60_000;
}
/** Resolve local wall time against the offset at that instant, rather than assuming a 24h day. */
function localInstant(date:string,tz:string,hour=0):Date {
 const base=calendarDate(date).getTime()+hour*HOUR;
 let instant=new Date(base);
 for(let i=0;i<4;i++){
  const next=new Date(base-offsetMinutes(instant,tz)*60_000);
  if(next.getTime()===instant.getTime())return next;
  instant=next;
 }
 return instant;
}
function dayInfo(date:string,county:County,now:Date):DailyDay {
 const today=dateKey(now,county.timezone),day=localInstant(date,county.timezone,12);
 const weekday=new Intl.DateTimeFormat('en-US',{timeZone:county.timezone,weekday:'long'}).format(day);
 return {date,label:date===today?'Today':date===addDay(today,1)?'Tomorrow':weekday,weekday,dayNumber:Number(date.slice(8)),provisional:date>=addDay(today,2)};
}

/** Today remains selectable for a useful outage state; later days require valid forecast bins. */
export function availableDays(report:Report,county:County,area:Area,now=new Date()):DailyDay[] {
 const today=dateKey(now,county.timezone),forecast=freshForecast(report,area,now);
 return [0,1,2].map(index=>addDay(today,index)).filter((date,index)=>index===0||forecast?.hours.some(hour=>{
  const at=Date.parse(hour.at);return Number.isFinite(at)&&at>=now.getTime()-HOUR&&at<now.getTime()+72*HOUR&&dateKey(hour.at,county.timezone)===date;
 })).map(date=>dayInfo(date,county,now));
}
function range(values:(number|null|undefined)[]):{min:number|null;max:number|null} {
 const numbers=values.filter(finite);return numbers.length?{min:Math.min(...numbers),max:Math.max(...numbers)}:{min:null,max:null};
}
function maximum(values:(number|null|undefined)[]):number|null{return range(values).max;}
function textRange(value:{min:number|null;max:number|null},unit:string):string|null {
 if(value.min===null||value.max===null)return null;
 const format=(n:number)=>Number(n.toFixed(1)).toString();
 return `${value.min===value.max?format(value.min):`${format(value.min)}–${format(value.max)}`} ${unit}`;
}
function relevantAlerts(report:Report,area:Area,start:number,end:number,now:Date):Alert[] {
 return report.alerts.filter(alert=>{
  if(alert.areaIds&&!alert.areaIds.includes(area.id))return false;
  const effective=alert.effective?Date.parse(alert.effective):-Infinity;
  const expires=alert.expires?Date.parse(alert.expires):Infinity;
  // Invalid warning clocks are treated conservatively rather than disappearing.
  return (Number.isNaN(effective)||effective<end)&&(Number.isNaN(expires)||expires>Math.max(start,now.getTime()));
 });
}
function astro(date:string,county:County,area:Area) {
 const noon=localInstant(date,county.timezone,12);
 const times=getTimes(noon,area.lat,area.lon,0,offsetMinutes(noon,county.timezone));
 const iso=(value:Date|null)=>value&&Number.isFinite(value.getTime())&&dateKey(value,county.timezone)===date?value.toISOString():null;
 const lunar=getMoonIllumination(noon);
 const names=['New moon','Waxing crescent','First quarter','Waxing gibbous','Full moon','Waning gibbous','Last quarter','Waning crescent'];
 return {sunrise:iso(times.sunrise),sunset:iso(times.sunset),moon:{fraction:finite(lunar.fraction)?lunar.fraction:null,label:finite(lunar.phase)?names[Math.round(lunar.phase*8)%8]!:'Unknown'}};
}

export function buildDaily(report:Report,county:County,area:Area,mode:Mode,date:string,now=new Date()):DailyBrief {
 const day=dayInfo(date,county,now),start=localInstant(date,county.timezone).getTime(),end=localInstant(addDay(date,1),county.timezone).getTime();
 const today=dateKey(now,county.timezone),isToday=date===today;
 const forecast=freshForecast(report,area,now);
 const source=report.sources.find(item=>item.id===forecast?.sourceId);
 const alerts=relevantAlerts(report,area,start,end,now);
 // Spear windows judge surge from a fresh nearshore model where one covers the hour, not the generic 3 ft rule.
 const site=mode==='spear'?freshNearshore(report,area.id,now)[0]:undefined;
 const surgeJudged=(hour:ForecastHour)=>!!site&&!!nearshoreAt(site,hour.at)&&surge(hour,nearshoreAt(site,hour.at)).basis==='nearshore';
 const waveOk=site?(hour:ForecastHour)=>surgeJudged(hour)?SURGE_RANK[surge(hour,nearshoreAt(site,hour.at)).band]<=SURGE_RANK[SPEAR.windowMaxSurge]:undefined:undefined;
 // Assess with the real clock, not tomorrow's timestamp. Limit warnings to this day's interval.
 const assessment=assess({...report,alerts},area,mode,now,county.timezone,waveOk?{waveOk,label:'Lower surge & wind'}:{});
 const hours=(forecast?.hours??[]).filter(hour=>{
  const at=Date.parse(hour.at);
  return Number.isFinite(at)&&at>=Math.max(start,now.getTime()-HOUR)&&at<Math.min(end,now.getTime()+72*HOUR);
 }).sort((a,b)=>Date.parse(a.at)-Date.parse(b.at));
 const wind={...range(hours.map(hour=>hour.windKnots)),gust:maximum(hours.map(hour=>hour.gustKnots))};
 const seas={...range(hours.map(hour=>hour.waveFt)),period:maximum(hours.flatMap(hour=>[hour.wavePeriodS,hour.swellPeriodS]))};
 const air=range(hours.map(hour=>hour.airTempF)),rainPct=maximum(hours.map(hour=>hour.precipPct));
 const inDay=(point:{at:string})=>{const at=Date.parse(point.at);return Number.isFinite(at)&&at>=start&&at<end;};
 const tides=report.tides.filter(point=>inDay(point)&&finite(point.heightFt)).sort((a,b)=>Date.parse(a.at)-Date.parse(b.at));
 const tideEvents=report.tideEvents.filter(point=>inDay(point)&&finite(point.heightFt)).sort((a,b)=>Date.parse(a.at)-Date.parse(b.at));
 const tideRange=range([...tides,...tideEvents].map(point=>point.heightFt));
 const tempObservation=isToday?report.observations.filter(observation=>observation.stationId===county.temperatureStationId&&finite(observation.waterTempF)&&freshObservation(observation.observedAt,now)).sort((a,b)=>Date.parse(b.observedAt)-Date.parse(a.observedAt))[0]??null:null;
 const missing:string[]=[];
 if(!forecast)missing.push('Fresh local forecast unavailable');
 else if(!hours.length)missing.push('No forecast hours available for this date');
 const alertSource=report.sources.find(item=>item.id==='nws-alerts');
 const alertAge=alertSource?now.getTime()-Date.parse(alertSource.fetchedAt):NaN;
 const alertCheckFresh=alertSource?.outcome==='ok'&&Number.isFinite(alertAge)&&alertAge>=-HOUR&&alertAge<=2*HOUR;
 if(!alertCheckFresh)missing.push('Current marine alert check unavailable');
 for(const [label,field] of [['Wind','windKnots'],['Gusts','gustKnots'],['Offshore seas','waveFt'],['Wave period','wavePeriodS'],['Air temperature','airTempF'],['Rain probability','precipPct']] as const){
  if(hours.some(hour=>!finite(hour[field])))missing.push(`${label} missing for some forecast hours`);
 }
 if(!tides.length)missing.push('Tide curve unavailable for this date');
 else if(Date.parse(tides[0]!.at)>start+HOUR||Date.parse(tides[tides.length-1]!.at)<end-HOUR||tides.some((point,index)=>index>0&&Date.parse(point.at)-Date.parse(tides[index-1]!.at)>HOUR))missing.push('Tide curve covers only part of this date');
 if(!tideEvents.length)missing.push('High and low tide events unavailable');
 if(isToday&&!tempObservation)missing.push('Fresh sea temperature observation unavailable');
 if(!isToday)missing.push('Sea temperature forecast unavailable');
 if(mode==='boat')missing.push('Harbor entrance and full return route need a separate check');
 if(mode==='shore')missing.push('Breaking surf, beach access and water quality need a local check');
 const astronomy=astro(date,county,area);
 const spear=mode==='spear'?spearDay(spearHours({hours,forecastHours:forecast?.hours??[],site,observations:report.observations.filter(observation=>observation.stationId===county.temperatureStationId),tideEvents:report.tideEvents,chlorophyll:report.chlorophyll??null}),astronomy.sunrise,astronomy.sunset):null;
 if(spear){
  missing.push('Underwater visibility is estimated, not measured; entry, exit and currents need a local check');
  if(spear.clarity.missing.length)missing.push(`Clarity estimate needs ${spear.clarity.missing.join(' and ')}`);
  missing.push(...spear.clarity.gaps);
  if(spear.basis!=='nearshore'&&hours.length)missing.push('Surge judged from offshore swell where no fresh nearshore model covers the hour');
 }
 const complete=hours.length>0&&hours.every(hour=>finite(hour.windKnots)&&finite(hour.gustKnots)&&finite(hour.waveFt)&&finite(hour.wavePeriodS));
 const windows=assessment.status==='Unknown'||alerts.length||!alertCheckFresh||!complete?[]:assessment.windows.filter(window=>{
  const from=Date.parse(window.start),to=Date.parse(window.end);
  return from>=start&&to<=end&&!hours.some(hour=>Date.parse(hour.at)>=from&&Date.parse(hour.at)<to&&!surgeJudged(hour)&&finite(hour.waveFt)&&hour.waveFt>=2.5&&finite(hour.swellPeriodS)&&hour.swellPeriodS>=15);
 });
 const status:DailyBrief['status']=alerts.length?'Caution':!forecast||!hours.length||!alertCheckFresh||!complete?'Unknown':mode==='shore'||windows.length?'Mixed':'Caution';
 const conditions=[textRange(wind,'kt winds'),textRange(seas,'ft offshore seas')].filter((item):item is string=>item!==null);
 const spearHeadline=spear?.surge?`${surgeText(spear.surge)} surge · ${clarityText(spear.clarity)}`:null;
 const headline=alerts.length?alerts[0]!.event:spearHeadline??(conditions.length?conditions.join(' · '):'Local forecast unavailable');
 const summaryParts:string[]=[];
 if(conditions.length)summaryParts.push(`${conditions.join('; ')}${wind.gust!==null?`, gusting to ${Number(wind.gust.toFixed(1))} kt`:''}.`);
 if(spear)summaryParts.push(...spearSummary(spear,site?.name??null,county.timezone));
 else if(seas.period!==null)summaryParts.push(seas.period>=15?`Long-period waves reach ${seas.period} seconds; check local surge and breaking surf.`:`Wave periods reach ${seas.period} seconds.`);
 if(alerts.length)summaryParts.push(alerts[0]!.headline);
 if(!alertCheckFresh)summaryParts.push('The current marine alert check is unavailable; conditions windows are withheld.');
 if(!forecast||!hours.length)summaryParts.push('A fresh forecast covering this date is needed.');
 if(mode==='boat')summaryParts.push('Check your harbor entrance, route and return conditions separately.');
 if(mode==='shore')summaryParts.push('Offshore seas do not measure breakers at your beach; verify surf, access and water quality.');
 if(mode==='spear')summaryParts.push('Check entry, exit, currents and water quality locally.');
 if(day.provisional)summaryParts.push('This outlook is provisional; check again closer to departure.');
 return {date,label:day.label,headline,summary:summaryParts.join(' '),status,confidence:day.provisional?'Low · provisional':status==='Unknown'?'Limited · missing local data':'Low · local checks required',hours,wind,seas,air,rainPct,tempObservation,tides,tideEvents,tideRange,windows,...astronomy,alerts,missing,issuedAt:source?.issuedAt??null,spear};
}

const lower=(text:string)=>text.charAt(0).toLowerCase()+text.slice(1);
/** The spear deck: what sets the surge, the clarity estimate and its drivers, and the calmest daylight hour. */
function spearSummary(spear:SpearDay,siteName:string|null,tz:string):string[] {
 const parts:string[]=[];
 const heights=spear.hours.filter(hour=>hour.surge.basis!==null);
 const scale=(values:(number|null)[])=>{const v=values.filter(finite);return v.length?{min:Math.min(...v),max:Math.max(...v)}:{min:null,max:null};};
 const feet=textRange(scale(heights.map(hour=>hour.surge.heightFt)),'ft'),secs=textRange(scale(heights.map(hour=>hour.surge.periodS)),'s');
 if(spear.surge&&feet)parts.push(`Surge from ${spear.basis==='nearshore'&&siteName?`the ${siteName} nearshore model`:spear.basis==='mixed'&&siteName?`the ${siteName} nearshore model and offshore swell`:'offshore swell, so sheltered coves may be calmer'}: ${feet}${secs?` at ${secs}`:''}.`);
 const k=spear.clarity;
 if(k.band==='Unknown')parts.push(`Clarity unknown: ${k.missing.length?`needs ${k.missing.join(' and ')}`:'no inputs'}.`);
 else parts.push(`Clarity is an estimate, not a measurement: ${lower(k.band)}${k.drivers.length?` (${k.drivers.join('; ')})`:''}.`);
 if(spear.best)parts.push(`Calmest daylight hour: ${new Intl.DateTimeFormat('en-US',{timeZone:tz,hour:'numeric'}).format(new Date(spear.best.at))} (${spear.best.verdict.toLowerCase()}).`);
 else if(spear.hours.length)parts.push('No daylight hour reads calmer or marginal.');
 return parts;
}

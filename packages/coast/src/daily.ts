import {getMoonIllumination, getTimes} from 'suncalc';
import {assess, freshForecast, freshObservation} from './assessment.ts';
import type {Alert, Area, County, ForecastHour, Mode, Observation, Report, TideEvent, TidePoint, Window} from './types.ts';

export type DailyDay = {date:string;label:string;weekday:string;dayNumber:number;provisional:boolean};
export type DailyBrief = {
 date:string;label:string;headline:string;summary:string;status:'Caution'|'Mixed'|'Unknown';confidence:string;
 hours:ForecastHour[];wind:{min:number|null;max:number|null;gust:number|null};seas:{min:number|null;max:number|null;period:number|null};
 air:{min:number|null;max:number|null};rainPct:number|null;tempObservation:Observation|null;
 tides:TidePoint[];tideEvents:TideEvent[];tideRange:{min:number|null;max:number|null};windows:Window[];
 sunrise:string|null;sunset:string|null;moon:{fraction:number|null;label:string};alerts:Alert[];missing:string[];issuedAt:string|null;
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
 return {sunrise:iso(times.sunrise),sunset:iso(times.sunset),moon:{fraction:finite(lunar.fraction)?lunar.fraction:null,label:finite(lunar.phase)?names[Math.round(lunar.phase*8)%8]:'Unknown'}};
}

export function buildDaily(report:Report,county:County,area:Area,mode:Mode,date:string,now=new Date()):DailyBrief {
 const day=dayInfo(date,county,now),start=localInstant(date,county.timezone).getTime(),end=localInstant(addDay(date,1),county.timezone).getTime();
 const today=dateKey(now,county.timezone),isToday=date===today;
 const forecast=freshForecast(report,area,now);
 const source=report.sources.find(item=>item.id===forecast?.sourceId);
 const alerts=relevantAlerts(report,area,start,end,now);
 // Assess with the real clock, not tomorrow's timestamp. Limit warnings to this day's interval.
 const assessment=assess({...report,alerts},area,mode,now,county.timezone);
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
 else if(Date.parse(tides[0].at)>start+HOUR||Date.parse(tides[tides.length-1].at)<end-HOUR||tides.some((point,index)=>index>0&&Date.parse(point.at)-Date.parse(tides[index-1].at)>HOUR))missing.push('Tide curve covers only part of this date');
 if(!tideEvents.length)missing.push('High and low tide events unavailable');
 if(isToday&&!tempObservation)missing.push('Fresh sea temperature observation unavailable');
 if(!isToday)missing.push('Sea temperature forecast unavailable');
 if(mode==='boat')missing.push('Harbor entrance and full return route need a separate check');
 if(mode==='shore')missing.push('Breaking surf, beach access and water quality need a local check');
 if(mode==='spear')missing.push('Underwater visibility, entry, exit and currents need a local check');
 const complete=hours.length>0&&hours.every(hour=>finite(hour.windKnots)&&finite(hour.gustKnots)&&finite(hour.waveFt)&&finite(hour.wavePeriodS));
 const windows=assessment.status==='Unknown'||alerts.length||!alertCheckFresh||!complete?[]:assessment.windows.filter(window=>{
  const from=Date.parse(window.start),to=Date.parse(window.end);
  return from>=start&&to<=end&&!hours.some(hour=>Date.parse(hour.at)>=from&&Date.parse(hour.at)<to&&finite(hour.waveFt)&&hour.waveFt>=2.5&&finite(hour.swellPeriodS)&&hour.swellPeriodS>=15);
 });
 const status:DailyBrief['status']=alerts.length?'Caution':!forecast||!hours.length||!alertCheckFresh||!complete||mode==='spear'?'Unknown':mode==='shore'||windows.length?'Mixed':'Caution';
 const conditions=[textRange(wind,'kt winds'),textRange(seas,'ft offshore seas')].filter((item):item is string=>item!==null);
 const headline=alerts.length?alerts[0].event:conditions.length?conditions.join(' · '):'Local forecast unavailable';
 const summaryParts:string[]=[];
 if(conditions.length)summaryParts.push(`${conditions.join('; ')}${wind.gust!==null?`, gusting to ${Number(wind.gust.toFixed(1))} kt`:''}.`);
 if(seas.period!==null)summaryParts.push(seas.period>=15?`Long-period waves reach ${seas.period} seconds; check local surge and breaking surf.`:`Wave periods reach ${seas.period} seconds.`);
 if(alerts.length)summaryParts.push(alerts[0].headline);
 if(!alertCheckFresh)summaryParts.push('The current marine alert check is unavailable; conditions windows are withheld.');
 if(!forecast||!hours.length)summaryParts.push('A fresh forecast covering this date is needed.');
 if(mode==='boat')summaryParts.push('Check your harbor entrance, route and return conditions separately.');
 if(mode==='shore')summaryParts.push('Offshore seas do not measure breakers at your beach; verify surf, access and water quality.');
 if(mode==='spear')summaryParts.push('Underwater visibility is unverified; check entry, exit, currents and water quality locally.');
 if(day.provisional)summaryParts.push('This outlook is provisional; check again closer to departure.');
 return {date,label:day.label,headline,summary:summaryParts.join(' '),status,confidence:day.provisional?'Low · provisional':status==='Unknown'?'Limited · missing local data':'Low · local checks required',hours,wind,seas,air,rainPct,tempObservation,tides,tideEvents,tideRange,windows,...astro(date,county,area),alerts,missing,issuedAt:source?.issuedAt??null};
}

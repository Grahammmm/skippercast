import {getMoonIllumination, getTimes} from 'suncalc';
import {assess, freshForecast, freshObservation} from './assessment.ts';
import type {Alert, Area, Assessment, BriefMode, County, ForecastHour, Observation, Report, TideEvent, TidePoint, Window} from './types.ts';
import {freshNearshore, nearshoreAt} from './nearshore.ts';
import {SPEAR, SURGE_RANK, clarityText, spearDay, spearHours, surge, surgeText, type SpearDay, type SurgeBand} from './spear.ts';
import {KAYAK_WIND_RANK, kayakDay, kayakHours, kayakWindText, kayakWindowOk, type KayakDay} from './kayak.ts';
import {seaward, shoreDay, shoreHours, surf, surfText, surfWindowOk, type ShoreDay} from './shore-conditions.ts';
import {BAR_CHECK, barDay, barHours, crossingHours, entranceFor, type BarDay, type BarHour} from './bar-conditions.ts';
import {clampLimits, defaultLimits, limitsText, looserFields, sameLimits, stricterFields, type ComfortLimits} from './limits.ts';

export type DailyDay = {date:string;label:string;weekday:string;dayNumber:number;provisional:boolean};
export type DailyBrief = {
 date:string;label:string;headline:string;summary:string;status:'Caution'|'Mixed'|'Unknown';confidence:string;
 hours:ForecastHour[];wind:{min:number|null;max:number|null;gust:number|null};seas:{min:number|null;max:number|null;period:number|null};
 air:{min:number|null;max:number|null};rainPct:number|null;tempObservation:Observation|null;
 tides:TidePoint[];tideEvents:TideEvent[];tideRange:{min:number|null;max:number|null};windows:Window[];
 sunrise:string|null;sunset:string|null;moon:{fraction:number|null;label:string};alerts:Alert[];missing:string[];issuedAt:string|null;
 /** The spear reading (spear.ts); null for the other profiles. */
 spear:SpearDay|null;
 /** The shore reading (shore-conditions.ts); null for the other profiles. */
 shore:ShoreDay|null;
 /** The harbour bar reading (bar-conditions.ts) for a boat brief at a regulated bar; null otherwise. */
 bar:BarDay|null;
 /** The kayak reading (kayak.ts); null for the other profiles. */
 kayak:KayakDay|null;
 /**
  * The comfort limits the windows used (limits.ts): the profile's defaults unless the user set their own.
  * `text` says so when they are the user's (null otherwise); `loosened` is true when one is above its default.
  */
 limits:{values:ComfortLimits;custom:boolean;loosened:boolean;text:string|null};
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

/**
 * The daily brief. `limits` are the user's own comfort limits (limits.ts); they are clamped to the profile's
 * bounds and change only the window rule's wind, gust, seas and surge limits. A stricter limit also caps a
 * Calmer hour at Marginal. Alerts, long-period swell, the bar, offshore wind, launch surf and daylight never move.
 */
export function buildDaily(report:Report,county:County,area:Area,mode:BriefMode,date:string,now=new Date(),limits?:Partial<ComfortLimits>|null):DailyBrief {
 const defaults=defaultLimits(mode),mine=limits?clampLimits(mode,limits):defaults,custom=!sameLimits(mode,mine,defaults);
 const strict=stricterFields(mode,mine),loose=looserFields(mode,mine),loosened=custom&&(loose.fields.length>0||loose.surge);
 const day=dayInfo(date,county,now),start=localInstant(date,county.timezone).getTime(),end=localInstant(addDay(date,1),county.timezone).getTime();
 const today=dateKey(now,county.timezone),isToday=date===today;
 const forecast=freshForecast(report,area,now);
 const source=report.sources.find(item=>item.id===forecast?.sourceId);
 const alerts=relevantAlerts(report,area,start,end,now);
 // Spear and shore windows judge surge or surf from a fresh nearshore model where one covers the hour, not the generic 3 ft rule.
 // Kayak reads the launch beach's surf from the same model.
 const site=mode==='spear'||mode==='shore'||mode==='kayak'?freshNearshore(report,area.id,now)[0]:undefined;
 const nearJudged=(hour:ForecastHour)=>{const near=site?nearshoreAt(site,hour.at):undefined;return !!near&&(mode==='spear'?surge(hour,near).basis==='nearshore':surf(hour,near).basis==='nearshore');};
 const astronomy=astro(date,county,area);
 const hours=(forecast?.hours??[]).filter(hour=>{
  const at=Date.parse(hour.at);
  return Number.isFinite(at)&&at>=Math.max(start,now.getTime()-HOUR)&&at<Math.min(end,now.getTime()+72*HOUR);
 }).sort((a,b)=>Date.parse(a.at)-Date.parse(b.at));
 // A stricter user limit caps a Calmer hour at Marginal and says which limit did it; a looser one never lifts a verdict.
 const byAt=new Map(hours.map(hour=>[hour.at,hour]));
 const overLimit=(at:string,seasFt:number|null|undefined,surgeBand?:SurgeBand):string|null=>{
  if(!custom)return null;
  const hour=byAt.get(at),over:string[]=[];
  if(strict.fields.includes('wind')&&finite(hour?.windKnots)&&hour.windKnots>mine.wind)over.push(`wind over your ${mine.wind} kt`);
  if(strict.fields.includes('gust')&&finite(hour?.gustKnots)&&hour.gustKnots>mine.gust)over.push(`gusts over your ${mine.gust} kt`);
  if(strict.fields.includes('seas')&&finite(seasFt)&&seasFt>mine.seas)over.push(`${mode==='shore'?'surf':'seas'} over your ${mine.seas} ft`);
  if(strict.surge&&mine.surge&&surgeBand&&surgeBand!=='Unknown'&&SURGE_RANK[surgeBand]>SURGE_RANK[mine.surge])over.push(`surge over your ${mine.surge.toLowerCase()} limit`);
  return over.length?`${over.join(', ')} (your limits)`:null;
 };
 const cap=<T extends {verdict:string;reasons:string[]}>(hour:T,over:string|null):T=>over&&hour.verdict==='Calmer'?{...hour,verdict:'Marginal',reasons:[...hour.reasons,over]} as T:hour;
 const kayak=mode==='kayak'?kayakDay(kayakHours({hours,site,seawardDeg:seaward(county.id,area.id),alerts,sunrise:astronomy.sunrise,sunset:astronomy.sunset}).map(hour=>cap(hour,overLimit(hour.at,hour.seas.heightFt))),seaward(county.id,area.id)):null;
 const kayakAt=new Map((kayak?.hours??[]).map(hour=>[hour.at,hour]));
 // Kayak windows take the kayak verdict instead of the wave rule: not Rough, no offshore wind, no launch surf caution.
 // A stricter seas or surf limit adds a cap on the judged height; spear's surge limit replaces SPEAR.windowMaxSurge (never Heavy).
 const waveOkFor=(lim:ComfortLimits):((hour:ForecastHour)=>boolean|undefined)|undefined=>{
  const tight=stricterFields(mode,lim).fields.includes('seas'),over=(ft:number|null|undefined)=>tight&&finite(ft)&&ft>lim.seas;
  const surgeMax=lim.surge??SPEAR.windowMaxSurge;
  if(kayak)return hour=>{const ok=kayakWindowOk(kayakAt.get(hour.at));return ok&&over(hour.waveFt)?false:ok;};
  if(!site)return undefined;
  if(mode==='spear')return hour=>{if(!nearJudged(hour))return undefined;const s=surge(hour,nearshoreAt(site,hour.at));return SURGE_RANK[s.band]<=SURGE_RANK[surgeMax]&&!over(s.heightFt);};
  return hour=>{const s=surf(hour,nearshoreAt(site,hour.at)),ok=surfWindowOk(s);return ok&&over(s.heightFt)?false:ok;};
 };
 const label=mode==='spear'?'Lower surge & wind':mode==='kayak'?'Lower wind & seas':'Lower surf & wind';
 // Assess with the real clock, not tomorrow's timestamp. Limit warnings to this day's interval.
 const assessWith=(lim:ComfortLimits)=>{const waveOk=waveOkFor(lim);return assess({...report,alerts},area,mode,now,county.timezone,{...(waveOk?{waveOk,label}:{}),limits:{wind:lim.wind,gust:lim.gust,wave:lim.seas}});};
 const assessment=assessWith(mine);
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
 if(mode==='kayak')missing.push('Launch and landing surf, drift and the paddle back need a local check');
 if(kayak&&hours.length){
  if(!kayak.bearingKnown)missing.push('Offshore wind cannot be told apart for this stretch of coast; wind judged on speed only');
  else if(kayak.windSpeedOnly)missing.push('Offshore wind unknown for some hours (no wind direction); wind judged on speed only');
  if(kayak.launchBasis!=='nearshore')missing.push('Launch surf is an offshore estimate where no fresh nearshore model covers the hour');
  missing.push('Fog and visibility are read only from marine alerts; check the marine forecast');
  if(kayak.daylightUnknown)missing.push('Sunrise or sunset unknown; daylight not checked');
 }
 const shore=mode==='shore'?shoreDay(shoreHours({hours,site,countyId:county.id,area,tideEvents:report.tideEvents,tides:report.tides,sunrise:astronomy.sunrise,sunset:astronomy.sunset}).map(hour=>cap(hour,overLimit(hour.at,hour.surf.heightFt))),astronomy.sunrise,astronomy.sunset,seaward(county.id,area.id)):null;
 if(shore&&hours.length){
  if(shore.basis!=='nearshore')missing.push('Surf is an offshore estimate where no fresh nearshore model covers the hour');
  if(!shore.bearingKnown)missing.push('Wind side unknown for this stretch of coast; wind judged on speed only');
  else if(shore.windSpeedOnly)missing.push('Onshore or offshore wind unknown for some hours (no wind direction); wind judged on speed only');
  if(shore.tideUnknown)missing.push('Tide phase unknown: high and low tide events unavailable');
 }
 // Boat at a regulated bar (33 CFR 165.1196): the bar check per hour, from the fresh nearshore model where one covers the hour.
 const entrance=mode==='boat'?entranceFor(county.id,area.id):null;
 const bar=entrance?barDay(entrance,barHours({hours,site:freshNearshore(report,area.id,now)[0],entrance,tideEvents:report.tideEvents})):null;
 if(bar&&hours.length){
  if(bar.basis!=='nearshore')missing.push('Bar swell is an offshore estimate where no fresh nearshore model covers the hour');
  if(bar.tideUnknown)missing.push('Tide phase unknown: the bar check cannot time the ebb');
 }
 const spear=mode==='spear'?spearDay(spearHours({hours,forecastHours:forecast?.hours??[],site,observations:report.observations.filter(observation=>observation.stationId===county.temperatureStationId),tideEvents:report.tideEvents,chlorophyll:report.chlorophyll??null}).map(hour=>cap(hour,overLimit(hour.at,hour.surge.heightFt,hour.surge.band))),astronomy.sunrise,astronomy.sunset):null;
 if(spear){
  missing.push('Underwater visibility is estimated, not measured; entry, exit and currents need a local check');
  if(spear.clarity.missing.length)missing.push(`Clarity estimate needs ${spear.clarity.missing.join(' and ')}`);
  missing.push(...spear.clarity.gaps);
  if(spear.basis!=='nearshore'&&hours.length)missing.push('Surge judged from offshore swell where no fresh nearshore model covers the hour');
 }
 const complete=hours.length>0&&hours.every(hour=>finite(hour.windKnots)&&finite(hour.gustKnots)&&finite(hour.waveFt)&&finite(hour.wavePeriodS));
 const screen=(assessed:Assessment):Window[]=>assessed.status==='Unknown'||alerts.length||!alertCheckFresh||!complete?[]:assessed.windows.filter(window=>{
  const from=Date.parse(window.start),to=Date.parse(window.end);
  return from>=start&&to<=end&&!hours.some(hour=>Date.parse(hour.at)>=from&&Date.parse(hour.at)<to&&!nearJudged(hour)&&finite(hour.waveFt)&&hour.waveFt>=2.5&&finite(hour.swellPeriodS)&&hour.swellPeriodS>=15)
   // A window that leaves or returns in a hazardous bar hour is not suggested.
   &&!(bar&&crossingHours(bar,window.start,window.end).some(hour=>hour.band==='Hazardous'));
 }).map(window=>{
  const crossing=bar?crossingHours(bar,window.start,window.end):[];
  return bar&&crossing.some(hour=>hour.band!=='No bar flag')?{...window,reasons:[...window.reasons,`${bar.entrance.name}: bar caution or unknown at departure or return (estimate); check the bar status`]}:window;
 });
 // With the user's limits, screen once more with the defaults: a window the defaults would not suggest in full
 // says the user's looser limit decided it, and hours the defaults would suggest but the user's limits leave out are counted.
 const defaultWindows=custom?screen(assessWith(defaults)):[];
 const inside=(window:Window)=>defaultWindows.some(base=>Date.parse(base.start)<=Date.parse(window.start)&&Date.parse(base.end)>=Date.parse(window.end));
 const windows=screen(assessment).map(window=>loosened&&!inside(window)?{...window,reasons:[`Using your limits (${limitsText(mode,mine)}); the default limits would not suggest all of it`,...window.reasons]}:window);
 const covered=(at:number,list:Window[])=>list.some(window=>at>=Date.parse(window.start)&&at<Date.parse(window.end));
 const left=custom?hours.filter(hour=>{const at=Date.parse(hour.at);return covered(at,defaultWindows)&&!covered(at,windows);}).length:0;
 const limitsLine=!custom?null:[loosened?`Using your limits: ${limitsText(mode,mine)}, looser than the defaults (${limitsText(mode,defaults)}).`:`Using your limits: ${limitsText(mode,mine)}.`,
  left?`Your limits leave out ${left} hour${left===1?'':'s'} the default limits would suggest.`:null].filter(Boolean).join(' ');
 // Shore reads Caution when long-period swell is running or no daylight hour reads calmer or marginal.
 const shoreCaution=!!shore&&(shore.sneakerPeriodS!==null||(shore.hours.length>0&&!shore.best));
 // Kayak reads Caution with offshore wind, surf at the launch, a fog alert or no calmer or marginal daylight hour.
 const kayakCaution=!!kayak&&(kayak.offshore.length>0||kayak.launch.length>0||kayak.fog||(kayak.hours.length>0&&!kayak.best));
 const status:DailyBrief['status']=alerts.length?'Caution':!forecast||!hours.length||!alertCheckFresh||!complete?'Unknown':shoreCaution||kayakCaution||!!bar?.hazardous.length?'Caution':mode==='shore'||mode==='kayak'||windows.length?'Mixed':'Caution';
 const conditions=[textRange(wind,'kt winds'),textRange(seas,'ft offshore seas')].filter((item):item is string=>item!==null);
 const spearHeadline=spear?.surge?`${surgeText(spear.surge)} surge · ${clarityText(spear.clarity)}`:null;
 const shoreHeadline=shore?.surf?`${surfText(shore.surf)} surf${shore.basis==='nearshore'?'':' (offshore estimate)'} · ${shore.sneakerPeriodS!==null?'sneaker-wave risk':shore.best?`${shore.best.verdict.toLowerCase()} at ${hourText(shore.best.at,county.timezone)}`:'no calmer hour'}`:null;
 const kayakHeadline=kayak?.wind?`${kayakWindText(kayak.wind)} wind · ${kayak.offshore.length?'offshore wind at times':kayak.best?`${kayak.best.verdict.toLowerCase()} at ${hourText(kayak.best.at,county.timezone)}`:'no calmer hour'}`:null;
 const barHeadline=bar?.hazardous.length?`Bar hazardous ${spans(bar.hazardous,county.timezone)} (estimate)`:null;
 const headline=alerts.length?alerts[0]!.event:spearHeadline??shoreHeadline??kayakHeadline??(barHeadline?[barHeadline,...conditions].join(' · '):null)??(conditions.length?conditions.join(' · '):'Local forecast unavailable');
 const summaryParts:string[]=[];
 if(conditions.length)summaryParts.push(`${conditions.join('; ')}${wind.gust!==null?`, gusting to ${Number(wind.gust.toFixed(1))} kt`:''}.`);
 if(spear)summaryParts.push(...spearSummary(spear,site?.name??null,county.timezone));
 else if(shore&&shore.hours.length)summaryParts.push(...shoreSummary(shore,site?.name??null,county.timezone,tideEvents));
 else if(kayak&&kayak.hours.length)summaryParts.push(...kayakSummary(kayak,site?.name??null,county.timezone));
 else if(seas.period!==null)summaryParts.push(seas.period>=15?`Long-period waves reach ${seas.period} seconds; check local surge and breaking surf.`:`Wave periods reach ${seas.period} seconds.`);
 if(alerts.length)summaryParts.push(alerts[0]!.headline);
 if(!alertCheckFresh)summaryParts.push('The current marine alert check is unavailable; conditions windows are withheld.');
 if(!forecast||!hours.length)summaryParts.push('A fresh forecast covering this date is needed.');
 if(bar&&bar.hours.length)summaryParts.push(...barSummary(bar,county.tideStation.name,county.timezone));
 if(mode==='boat')summaryParts.push('Check your harbor entrance, route and return conditions separately.');
 if(mode==='shore')summaryParts.push(shore?.basis==='nearshore'?'A model point is not your beach; verify surf, access and water quality.':'Offshore seas do not measure breakers at your beach; verify surf, access and water quality.');
 if(mode==='spear')summaryParts.push('Check entry, exit, currents and water quality locally.');
 // Kayak at a regulated bar: the bar is not scored for a kayak, so point paddlers who cross it at the bar check.
 const kayakEntrance=mode==='kayak'?entranceFor(county.id,area.id):null;
 if(kayakEntrance)summaryParts.push(`Crossing the ${kayakEntrance.name} bar by kayak is not scored here. ${BAR_CHECK}`);
 if(mode==='kayak')summaryParts.push('Check your launch, landing, drift and the paddle back locally, and leave your plan with someone ashore.');
 if(limitsLine)summaryParts.push(limitsLine);
 if(day.provisional)summaryParts.push('This outlook is provisional; check again closer to departure.');
 return {date,label:day.label,headline,summary:summaryParts.join(' '),status,confidence:day.provisional?'Low · provisional':status==='Unknown'?'Limited · missing local data':'Low · local checks required',hours,wind,seas,air,rainPct,tempObservation,tides,tideEvents,tideRange,windows,...astronomy,alerts,missing,issuedAt:source?.issuedAt??null,spear,shore,bar,kayak,limits:{values:mine,custom,loosened,text:limitsLine}};
}

const lower=(text:string)=>text.charAt(0).toLowerCase()+text.slice(1);
const hourText=(at:string,tz:string)=>new Intl.DateTimeFormat('en-US',{timeZone:tz,hour:'numeric'}).format(new Date(at));
const clockText=(at:string,tz:string)=>new Intl.DateTimeFormat('en-US',{timeZone:tz,hour:'numeric',minute:'2-digit'}).format(new Date(at));
/** Consecutive hours as spans: "6 AM–9 AM, 1 PM–2 PM and 6 PM–7 PM" (each span ends an hour after its last hour). */
function spans(hours:BarHour[],tz:string):string {
 const groups:BarHour[][]=[];
 for(const hour of hours){const last=groups.at(-1);if(last&&Date.parse(hour.at)-Date.parse(last.at(-1)!.at)<=HOUR)last.push(hour);else groups.push([hour]);}
 const texts=groups.map(group=>`${hourText(group[0]!.at,tz)}–${hourText(new Date(Date.parse(group.at(-1)!.at)+HOUR).toISOString(),tz)}`);
 return texts.length>1?`${texts.slice(0,-1).join(', ')} and ${texts.at(-1)}`:texts[0]??'';
}
/** The bar deck: the worst hours and why, the tide basis, what is not judged, and the standing check line. Never says the bar is safe. */
function barSummary(bar:BarDay,station:string,tz:string):string[] {
 const parts:string[]=[],name=bar.entrance.name;
 if(bar.hazardous.length)parts.push(`${name} bar (estimate): hazardous ${spans(bar.hazardous,tz)} (${bar.hazardous[0]!.reasons.join(', ')}). Windows that leave or return then are not suggested.`);
 else if(bar.caution.length)parts.push(`${name} bar (estimate): caution ${spans(bar.caution,tz)} (${bar.caution[0]!.reasons.join(', ')}).`);
 else if(bar.worst==='No bar flag')parts.push(`${name} bar (estimate): no hour reads hazardous or caution on this rough check, which does not mean the bar is safe.`);
 else parts.push(`${name} bar: not judged (${(bar.hours.find(hour=>hour.band==='Unknown')??bar.hours[0]!).reasons.join(', ')}).`);
 if(bar.hazardous.length||bar.caution.length){const unknown=bar.hours.filter(hour=>hour.band==='Unknown');if(unknown.length)parts.push(`Bar not judged ${spans(unknown,tz)}.`);}
 if(!bar.tideUnknown)parts.push(`Ebb timing is from ${station} tide predictions; the current at the entrance can turn earlier or later.`);
 if(bar.entrance.seawardDeg===null)parts.push('This entrance has no bearing, so wind against the ebb is left out.');
 parts.push(BAR_CHECK);
 return parts;
}
/** The shore deck: what sets the surf, the long-period caution, tide phase, wind side and the calmest daylight hour. */
function shoreSummary(shore:ShoreDay,siteName:string|null,tz:string,tideEvents:TideEvent[]):string[] {
 const parts:string[]=[];
 const scale=(values:(number|null)[])=>{const v=values.filter(finite);return v.length?{min:Math.min(...v),max:Math.max(...v)}:{min:null,max:null};};
 const judged=shore.hours.filter(hour=>hour.surf.basis!==null);
 const feet=textRange(scale(judged.map(hour=>hour.surf.heightFt)),'ft'),secs=textRange(scale(judged.map(hour=>hour.surf.periodS)),'s');
 if(shore.surf&&feet)parts.push(shore.basis==='nearshore'&&siteName?`Surf from the ${siteName} nearshore model: ${feet}${secs?` at ${secs}`:''}.`
  :shore.basis==='mixed'&&siteName?`Surf from the ${siteName} nearshore model and, where it does not cover the hour, an offshore estimate: ${feet}${secs?` at ${secs}`:''}.`
  :`Surf is an offshore estimate: ${feet} offshore seas${secs?` at ${secs}`:''}. Sheltered beaches can see less and exposed beaches more.`);
 if(shore.sneakerPeriodS!==null)parts.push(`Long-period swell (${shore.sneakerPeriodS} s) raises the risk of sneaker waves: sets can run far up the beach without warning. Stay off low rocks and keep the ocean in view.`);
 const highs=tideEvents.filter(event=>event.type==='H');
 if(highs.length)parts.push(`The rising tide and the two hours around high often fish better from the beach (an angler rule of thumb, not a guarantee): high at ${highs.map(event=>clockText(event.at,tz)).join(' and ')}.`);
 if(shore.veryLow.length)parts.push(`Very low tide near ${clockText(shore.veryLow[0]!.at,tz)}: take care on exposed rock and watch the incoming water.`);
 const sides=new Set(shore.hours.map(hour=>hour.wind.side).filter(side=>side!==null));
 if(sides.size)parts.push(`Wind ${[...sides].join(' or ')}${sides.has('onshore')?'; onshore wind chops the surf and blows line back':''}.`);
 else if(shore.hours.some(hour=>hour.wind.band!=='Unknown'))parts.push('Wind direction relative to the beach is unknown; wind is judged on speed only.');
 if(shore.best)parts.push(`Calmest daylight hour: ${hourText(shore.best.at,tz)} (${shore.best.verdict.toLowerCase()}: ${shore.best.reasons.join(', ')}).`);
 else parts.push('No daylight hour reads calmer or marginal.');
 return parts;
}
/** The kayak deck: wind and its side, seas and chop, surf at the launch, fog and the calmest daylight hour. */
function kayakSummary(kayak:KayakDay,siteName:string|null,tz:string):string[] {
 const parts:string[]=[];
 if(kayak.offshore.length)parts.push(`Offshore wind from ${hourText(kayak.offshore[0]!.at,tz)}: it carries a kayak away from shore and makes the paddle back upwind. Stay close in, or wait for it to turn.`);
 else if(!kayak.bearingKnown&&kayak.wind)parts.push('Whether the wind blows offshore here is unknown; wind is judged on speed only.');
 if(kayak.wind&&KAYAK_WIND_RANK[kayak.wind.max]>=KAYAK_WIND_RANK.Fresh)parts.push('Fresh or strong wind tires a paddler quickly and pushes the drift; plan the return into it.');
 if(kayak.chop)parts.push('Short-period seas make steep chop for a kayak.');
 if(kayak.launch.length){
  const peak=Math.max(...kayak.launch.map(hour=>hour.launch.heightFt as number));
  parts.push(`Surf at the launch reaches about ${Number(peak.toFixed(1))} ft${kayak.launchBasis==='nearshore'&&siteName?` (${siteName} nearshore model)`:' (offshore estimate)'}: launching and landing through breaking waves can capsize a kayak; choose a sheltered launch.`);
 }
 if(kayak.fog)parts.push('A fog or visibility alert is in force: a kayak is hard to see and the way back is hard to find.');
 if(kayak.best)parts.push(`Calmest daylight hour: ${hourText(kayak.best.at,tz)} (${kayak.best.verdict.toLowerCase()}: ${kayak.best.reasons.join(', ')}).`);
 else parts.push(kayak.offshore.length?'No daylight hour without offshore wind reads calmer or marginal.':'No daylight hour reads calmer or marginal.');
 return parts;
}
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

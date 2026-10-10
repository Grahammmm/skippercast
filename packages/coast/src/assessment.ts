import type {Report,Mode,Area,Assessment,ForecastHour,Window} from './types.ts';
import {getTimes} from 'suncalc';
export const MODEL_VERSION='conditions-v1';
const age=(at:string,now:Date)=>now.getTime()-Date.parse(at);
export function freshForecast(report:Report,area:Area,now=new Date()){
 const forecast=report.forecasts.find(x=>x.id===area.id);
 const source=report.sources.find(x=>x.id===forecast?.sourceId);
 if(!forecast||!source||source.outcome!=='ok'||!source.issuedAt)return undefined;
 const issueAge=age(source.issuedAt,now),fetchAge=age(source.fetchedAt,now);
 if(!Number.isFinite(issueAge)||!Number.isFinite(fetchAge)||issueAge>18*3600000||issueAge<-3600000||fetchAge>2*3600000||fetchAge<-3600000)return undefined;
 return forecast;
}
export function assess(report:Report,area:Area,mode:Mode,now=new Date(),timezone='America/Los_Angeles'):Assessment{
 const forecast=freshForecast(report,area,now);
 const hours=(forecast?.hours??[]).filter(x=>Date.parse(x.at)>=now.getTime()-3600000 && Date.parse(x.at)<now.getTime()+72*3600000);
 const source=report.sources.find(x=>x.id===forecast?.sourceId);
 const empty={status:'Unknown' as const,headline:'More local data needed',summary:'Conditions could not be evaluated from a fresh, complete forecast.',windows:[],reasons:['Missing or stale forecast'],hours};
 if(!forecast)return empty;
 const alerts=report.alerts.filter(x=>(!x.areaIds||x.areaIds.includes(area.id))&&(!x.expires||Date.parse(x.expires)>now.getTime()));
 const criticalSource=report.sources.find(x=>x.id==='nws-alerts');
 const alertAge=criticalSource?age(criticalSource.fetchedAt,now):NaN;
 if(!criticalSource||criticalSource.outcome!=='ok'||!Number.isFinite(alertAge)||alertAge>2*3600000||alertAge<-3600000)return {...empty,reasons:['Current marine alerts unavailable'],summary:'The current marine alert check is unavailable. Review the official forecast before planning.'};
 const limits=mode==='boat'?{wind:10,gust:15,wave:4}:{wind:8,gust:12,wave:3};
 const pass=(h:ForecastHour)=>{
  if(h.windKnots===null||h.gustKnots===null||h.waveFt===null||h.wavePeriodS===null)return false;
  const localDate=new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(h.at));
  const sun=getTimes(new Date(localDate+'T20:00:00Z'),area.lat,area.lon);
  const at=Date.parse(h.at);
  if(!sun.sunrise||!sun.sunset)return false;
  return at>=sun.sunrise.getTime()&&at+3600000<=sun.sunset.getTime()&&h.windKnots<=limits.wind&&h.gustKnots<=limits.gust&&h.waveFt<=limits.wave && !(h.waveFt>=2.5&&h.wavePeriodS>=15);
 };
 const groups:ForecastHour[][]=[];
 for(const h of hours){if(!pass(h))continue;const g=groups.at(-1);if(g&&Date.parse(h.at)-Date.parse(g.at(-1)!.at)===3600000)g.push(h);else groups.push([h]);}
 const windows:Window[]=groups.filter(g=>g.length>=3).map(g=>({start:g[0]!.at,end:new Date(Date.parse(g.at(-1)!.at)+3600000).toISOString(),label:mode==='boat'?'Lower wind & offshore seas':'Lower offshore exposure',confidence:'Low',reasons:[mode==='boat'?'Harbor entrance and full return route need a separate check':'Breaking surf and exact entry conditions are not measured',...(mode==='spear'?['Underwater visibility is unknown']:[])],wind:Math.max(...g.map(x=>x.windKnots!)),gust:Math.max(...g.map(x=>x.gustKnots!)),wave:Math.max(...g.map(x=>x.waveFt!)),period:Math.max(...g.map(x=>x.wavePeriodS!))}));
 const caution=alerts.length>0;
 const status=caution?'Caution':mode==='spear'?'Unknown':mode==='shore'?'Mixed':windows.length?'Mixed':'Caution';
 return {status,headline:caution?'Marine alert in effect':mode==='spear'?'Visibility still needs a local check':windows.length?'A lower-exposure window to investigate':'Conditions need a closer look',summary:caution?alerts[0]!.headline:mode==='boat'?'Compare the lower-wind periods below with your route, harbor entrance, and return. Offshore forecasts alone cannot clear a trip.':mode==='shore'?'Use the coastal outlook to narrow your timing, then check breaking surf, beach access, and water quality at the exact shore.':'Wind, swell, water quality, entry and exit matter. No current in-water visibility observation is available for these areas.',windows:caution?[]:windows,reasons:[...alerts.map(x=>x.event),area.accessNote],hours};
}
export function freshObservation(at:string,now=new Date()){const delta=age(at,now);return delta>=-3600000&&delta<3*3600000;}

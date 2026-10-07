import type {County,Report,Mode,ForecastHour,Area} from '../types.ts';
import type {SpeciesId} from '../habitat-types.ts';
import {availableDays,buildDaily,dateKey,type DailyBrief} from '../daily.ts';
import {freshNearshore,nearshoreAt} from '../presentation.ts';
export type View='coast'|'conditions'|'history';
export type ThemeLayer='opportunity'|'temperature'|'currents'|'waves'|'clouds';
export type AppState={report:Report;county:County;mode:Mode;areaId:string;species:SpeciesId;date:string;at:string;view:View;layer:ThemeLayer;base:'ocean'|'imagery';maxDepth:number;playing:boolean;motion:boolean;now:Date;selectedSite:string|null};
export const methodLabel:Record<Mode,string>={boat:'Boat',shore:'Shore',spear:'Spear'};
export function defaultSpecies(mode:Mode):SpeciesId{return mode==='shore'?'surfperch':mode==='spear'?'cabezon-shallow-reef':'lingcod';}
export function selectedArea(s:AppState):Area{return s.county.areas.find(a=>a.id===s.areaId)??s.county.areas[0];}
export function daily(s:AppState):DailyBrief{return buildDaily(s.report,s.county,selectedArea(s),s.mode,s.date,s.now);}
export function forecastHour(s:AppState):ForecastHour|undefined{return daily(s).hours.find(h=>h.at===s.at)??daily(s).hours[0];}
export function localWave(s:AppState){const site=freshNearshore(s.report,s.areaId,s.now)[0];return site?{site,hour:nearshoreAt(site,s.at)}:undefined;}
export function createState(report:Report,county:County,mode:Mode,areaId:string,date?:string,species?:SpeciesId,now=new Date()):AppState{
 const area=county.areas.find(a=>a.id===areaId)??county.areas.find(a=>a.id===county.defaultAreaId)??county.areas[0];
 const days=availableDays(report,county,area,now),selected=days.some(d=>d.date===date)?date!:days[0].date;
 const b=buildDaily(report,county,area,mode,selected,now);
 const state:AppState={report,county,mode,areaId:area.id,date:selected,species:species&&species!=='all'?species:defaultSpecies(mode),at:b.hours[0]?.at??now.toISOString(),view:'coast',layer:'opportunity',base:'ocean',maxDepth:mode==='spear'?60:300,playing:false,motion:true,now,selectedSite:null};
 state.at=initialForecastAt(state);return state;
}
/** Compare supported daylight forecast hours. This ranking describes relative exposure, not bite success. */
export function quietestHours(s:AppState):{start:string;end:string;qualified:boolean}|null{
 const b=daily(s);if(b.windows.length)return {...b.windows[0],qualified:true};
 if(b.alerts.length||b.missing.includes('Current marine alert check unavailable')||!b.sunrise||!b.sunset)return null;
 const hours=b.hours.filter(h=>Date.parse(h.at)>=Date.parse(b.sunrise!)&&Date.parse(h.at)+3600000<=Date.parse(b.sunset!)&&h.windKnots!==null&&h.gustKnots!==null&&h.waveFt!==null&&h.wavePeriodS!==null);
 const pairs=hours.flatMap((h,i)=>{const next=hours[i+1];return next&&Date.parse(next.at)-Date.parse(h.at)===3600000?[{start:h.at,end:new Date(Date.parse(next.at)+3600000).toISOString(),score:Math.max(h.windKnots!,next.windKnots!)+Math.max(h.waveFt!,next.waveFt!)*3,qualified:false}]:[];});
 return pairs.sort((a,b)=>a.score-b.score)[0]??null;
}
export const isToday=(s:AppState)=>s.date===dateKey(s.now,s.county.timezone);

export function initialForecastAt(s:AppState):string{const b=daily(s);if(isToday(s))return b.hours[0]?.at??s.now.toISOString();const window=quietestHours(s);return (window?b.hours.find(h=>h.at===window.start):undefined)?.at??b.hours.find(h=>b.sunrise&&Date.parse(h.at)>=Date.parse(b.sunrise))?.at??b.hours[0]?.at??s.now.toISOString();}

/** Playback requires at least two supported hours; a single observation cannot animate. */
export function canPlayForecast(s:AppState):boolean{return daily(s).hours.length>1;}

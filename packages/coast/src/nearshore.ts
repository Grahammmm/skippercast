import type {Report} from './types.ts';
import type {NearshoreSite} from './enrichment-types.ts';

/** Nearshore model sites for an area whose issue and fetch clocks are current. */
export function freshNearshore(report:Report,areaId:string,now:Date){return (report.nearshore??[]).filter(s=>{const issue=s.issuedAt?now.getTime()-Date.parse(s.issuedAt):NaN,fetchAge=now.getTime()-Date.parse(s.fetchedAt);return s.areaId===areaId&&s.availability==='available'&&s.freshness==='current'&&issue>=-300000&&issue<48*3600000&&fetchAge>=-300000&&fetchAge<3*3600000;});}
/** The site sample within 90 minutes of `at`, inside the site's valid span. */
export function nearshoreAt(site:NearshoreSite,at:string){
 const time=Date.parse(at),hours=site.hours.filter(h=>Number.isFinite(Date.parse(h.at))).sort((a,b)=>Date.parse(a.at)-Date.parse(b.at));
 if(!Number.isFinite(time)||!hours.length)return undefined;
 const first=Date.parse(hours[0]!.at),last=Date.parse(hours.at(-1)!.at),declared=site.validThrough?Date.parse(site.validThrough):NaN;
 if(time<first||time>last||(Number.isFinite(declared)&&time>declared))return undefined;
 return hours.filter(h=>Math.abs(Date.parse(h.at)-time)<=1.5*3600000).sort((a,b)=>Math.abs(Date.parse(a.at)-time)-Math.abs(Date.parse(b.at)-time))[0];
}

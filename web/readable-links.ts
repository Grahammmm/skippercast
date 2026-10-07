import {resolveReportBinding,type CoastReportContext} from '../packages/coast/src/state/report-binding.ts';
const PUBLIC_STATE=['region','coast','view','target','hour','profile','day','layers','area','base','spot','focus','presentation','habitat','ui','place','mode','species'] as const;
/** Preserve public selection only; optional account or arbitrary query fields stay out. */
export function readableReportURL(href:string,context:CoastReportContext|null=null):URL {
 const input=new URL(href),output=new URL('/report',input.origin);
 for(const key of PUBLIC_STATE)for(const value of input.searchParams.getAll(key))output.searchParams.append(key,value);
 if(context&&resolveReportBinding(context)){
  output.searchParams.set('region',context.regionId);
  output.searchParams.delete('area');output.searchParams.delete('place');
  const view=input.searchParams.get('view')?.split(',');
  output.searchParams.set('view',`${context.point.latitude},${context.point.longitude},${view?.length===3?view[2]:'12'}`);
  output.searchParams.set('profile',context.profile);output.searchParams.set('target',context.target);
 }
 return output;
}

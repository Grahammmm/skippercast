import {slo} from '../counties.ts';
import {dateKey} from '../daily.ts';
import type {Report,Mode} from '../types.ts';
import type {AppState} from './experience.ts';

import {resolveReportBinding,type CoastReportContext} from './report-binding.ts';
export {resolveReportBinding} from './report-binding.ts';
export type {ReportLocalArea,CoastReportContext,ManagedReportContext,ReportBinding} from './report-binding.ts';

export function managedReportState(report:Report,context:CoastReportContext,now=new Date()):AppState|null{
 const binding=resolveReportBinding(context),epoch=context.at.getTime();
 if(!binding||report.countyId!==slo.id||report.schemaVersion!==1||!Number.isFinite(epoch)||epoch%3600000!==0||!['boat','shore','spear'].includes(context.profile))return null;
 const aliases:Readonly<Record<string,string>>={reef:'all',rockfish:'rockfish-reef',cabezon:'cabezon-shallow-reef'};
 const target=Object.hasOwn(aliases,context.target)?aliases[context.target]:context.target;
 return {report,county:slo,mode:context.profile,areaId:binding.areaId,species:target,date:dateKey(context.at,slo.timezone),at:context.at.toISOString(),view:'conditions',layer:'opportunity',base:'ocean',maxDepth:context.profile==='spear'?60:300,playing:false,motion:false,now:new Date(now.getTime()),selectedSite:null};
}

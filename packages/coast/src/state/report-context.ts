import {slo} from '../counties.ts';
import {dateKey} from '../daily.ts';
import type {Report,Mode} from '../types.ts';
import type {AppState} from './experience.ts';

export type ReportLocalArea={id:string;bounds:readonly number[]};
export type CoastReportContext={regionId:string;point:{latitude:number;longitude:number};localAreas:readonly ReportLocalArea[];localId?:string|null;profile:Mode;target:string;at:Date};
export type ManagedReportContext=CoastReportContext;
export type ReportBinding={areaId:'north'|'central'|'south';localAreaId:string};
// These identities translate reviewed package/local-area metadata. Bounds are
// provided by the package; proximity never creates a report binding.
const bindings:Readonly<Record<string,Readonly<Record<string,ReportBinding['areaId']>>>>={
 'morro-bay':{'san-simeon':'north','estero-bay':'central',cayucos:'central',buchon:'central',avila:'south'},
 'cambria-san-simeon':{'san-simeon':'north'},
};
export function resolveReportBinding(context:CoastReportContext):ReportBinding|null{
 const {regionId,point,localAreas,localId}=context;
 if(!Object.hasOwn(bindings,regionId)||![point.latitude,point.longitude].every(Number.isFinite)||Math.abs(point.latitude)>90||Math.abs(point.longitude)>180)return null;
 const named=bindings[regionId];
 const matches=localAreas.filter(area=>{const b=area.bounds;return Object.hasOwn(named,area.id)&&b.length===4&&b.every(Number.isFinite)&&b[0]>=-180&&b[2]<=180&&b[1]>=-90&&b[3]<=90&&b[0]<b[2]&&b[1]<b[3]&&point.longitude>=b[0]&&point.longitude<=b[2]&&point.latitude>=b[1]&&point.latitude<=b[3];});
 // A supplied identity must agree with its original bounds. Do not repair it
 // by silently choosing another area.
 const selected=localId!==undefined&&localId!==null?matches.find(area=>area.id===localId):matches.sort((a,b)=>(a.bounds[2]-a.bounds[0])*(a.bounds[3]-a.bounds[1])-(b.bounds[2]-b.bounds[0])*(b.bounds[3]-b.bounds[1])||a.id.localeCompare(b.id))[0];
 return selected?{areaId:named[selected.id],localAreaId:selected.id}:null;
}
export function managedReportState(report:Report,context:CoastReportContext,now=new Date()):AppState|null{
 const binding=resolveReportBinding(context),epoch=context.at.getTime();
 if(!binding||report.countyId!==slo.id||report.schemaVersion!==1||!Number.isFinite(epoch)||epoch%3600000!==0||!['boat','shore','spear'].includes(context.profile))return null;
 const aliases:Readonly<Record<string,string>>={reef:'all',rockfish:'rockfish-reef',cabezon:'cabezon-shallow-reef'};
 const target=Object.hasOwn(aliases,context.target)?aliases[context.target]:context.target;
 return {report,county:slo,mode:context.profile,areaId:binding.areaId,species:target,date:dateKey(context.at,slo.timezone),at:context.at.toISOString(),view:'conditions',layer:'opportunity',base:'ocean',maxDepth:context.profile==='spear'?60:300,playing:false,motion:false,now:new Date(now.getTime()),selectedSite:null};
}

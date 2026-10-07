import type {Mode} from '../types.ts';

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
 const named=bindings[regionId];if(!named)return null;
 const matches=localAreas.filter(area=>{const b=area.bounds;if(!Object.hasOwn(named,area.id)||b.length!==4)return false;const [west,south,east,north]=b;if(typeof west!=='number'||typeof south!=='number'||typeof east!=='number'||typeof north!=='number'||![west,south,east,north].every(Number.isFinite))return false;return west>=-180&&east<=180&&south>=-90&&north<=90&&west<east&&south<north&&point.longitude>=west&&point.longitude<=east&&point.latitude>=south&&point.latitude<=north;});
 // A supplied identity must agree with its original bounds. Do not repair it
 // by silently choosing another area.
 const selected=localId!==undefined&&localId!==null?matches.find(area=>area.id===localId):matches.sort((a,b)=>(a.bounds[2]!-a.bounds[0]!)*(a.bounds[3]!-a.bounds[1]!)-(b.bounds[2]!-b.bounds[0]!)*(b.bounds[3]!-b.bounds[1]!)||a.id.localeCompare(b.id))[0];
 if(!selected)return null;const areaId=named[selected.id];return areaId?{areaId,localAreaId:selected.id}:null;
}

import type {CoastReportContext,ReportLocalArea} from '../packages/coast/src/state/report-binding.ts';
import {resolveReportBinding} from '../packages/coast/src/state/report-binding.ts';
import type {Mode} from '../packages/coast/src/types.ts';
export type OverviewSelection={latitude:number;longitude:number;region?:string;id?:string};
export type OverviewRegion={id:string;fishing_bounds:readonly number[];map?:{local_areas?:readonly ReportLocalArea[]}};
/** Publication identity and exact reviewed bounds must agree. No nearest package. */
export function overviewReportContext(point:{latitude:number;longitude:number},selection:OverviewSelection|null,regions:readonly OverviewRegion[],profile:Mode,target:string,at:Date):CoastReportContext{
 const gap:CoastReportContext={regionId:'',point,localAreas:[],profile,target,at};
 if(!selection?.id||!selection.region||!Number.isFinite(selection.latitude)||!Number.isFinite(selection.longitude)||!Number.isFinite(point.latitude)||!Number.isFinite(point.longitude)||Math.abs(point.latitude-selection.latitude)>.00001||Math.abs(point.longitude-selection.longitude)>.00001)return gap;
 const region=regions.find(r=>r.id===selection.region);if(!region)return gap;
 const b=region.fishing_bounds;if(!Array.isArray(b)||b.length!==4||!b.every(Number.isFinite)||b[0]!>=b[2]!||b[1]!>=b[3]!||point.longitude<b[0]!||point.longitude>b[2]!||point.latitude<b[1]!||point.latitude>b[3]!)return gap;
 const context={...gap,regionId:region.id,localAreas:Array.isArray(region.map?.local_areas)?region.map.local_areas.filter(a=>a&&Array.isArray(a.bounds)):[]};return resolveReportBinding(context)?context:gap;
}

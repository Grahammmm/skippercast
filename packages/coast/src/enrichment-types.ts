import type {SourceStatus} from './types.ts';

export type NearshoreHour = {
 at:string;
 waveFt:number|null;
 periodS:number|null;
 directionDeg:number|null;
 qualityFlag:number|null;
 secondaryFlag:number|null;
};
export type NearshoreSite = {
 id:string;name:string;areaId:string;lat:number;lon:number;sourceId:string;
 issuedAt:string|null;fetchedAt:string;hours:NearshoreHour[];url:string;
 kind:'forecast';availability:'available'|'error';freshness:'current'|'stale'|'unknown';
 temporalResolutionMinutes:number|null;waterDepthM:number|null;
 depthDatum:string;directionConvention:'from degrees true';
 modelInputCycleAt:null;validThrough:string|null;error?:string;
};
export type BeachWaterQuality = {
 id:string;name:string;lat:number;lon:number;status:string;advisory:string|null;
 sampledAt:string|null;fetchedAt:string;sourceId:string;url:string;
 areaId?:string;stationCode:string|null;sampleDateAvailable:boolean;
};
export type Enrichment = {nearshore:NearshoreSite[];waterQuality:BeachWaterQuality[];sources:SourceStatus[]};
export type NearshoreBinding={id:string;name:string;areaId:string;lat:number;lon:number};
export type WaterQualityBinding={id:string;serviceUrl:string;pageUrl:string};
export type EnrichmentBindings={nearshore:NearshoreBinding[];waterQuality?:WaterQualityBinding};

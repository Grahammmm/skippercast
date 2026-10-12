/** Surface fields retain their native footprints and populated times. */
export type CurrentCell = {
 lat:number;lon:number;uMs:number;vMs:number;speedKnots:number;towardDeg:number;
 hdop?:number;radarCount?:number;
};
export type CurrentFrame = {validAt:string;cells:CurrentCell[];sourceFile?:string};
export type CurrentField = {
 id:'wcofs'|'hfr-1'|'hfr-6';kind:'forecast'|'observation';label:string;url:string;
 fetchedAt:string;issuedAt:string|null;sampleAt:string|null;nativeResolutionKm:number;
 sampleStride:number;horizontalDatum:string;surfaceOnly:true;frames:CurrentFrame[];
 attribution:string;license:'public-domain-us-gov';limitations:string;
};
export type CloudImage = {
 id:'goes-longwave';kind:'observation';observedAt:string;fetchedAt:string;
 availableTimes:string[];layer:'goes_longwave_imagery';url:string;
 attribution:string;license:'public-domain-us-gov';limitations:string;
};
export type OceanSource = {
 id:string;status:'ok'|'error';fetchedAt:string;url:string;error?:string;
};
export type OceanData = {
 schemaVersion:1;countyId:string;generatedAt:string;
 currents:CurrentField[];cloud:CloudImage|null;sources:OceanSource[];
};

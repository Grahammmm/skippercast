export type SSTPoint={lon:number;lat:number;tempF:number;errorF:number};
export type SurfaceTemperature={sourceId:string;analysedAt:string;fetchedAt:string;nativeResolutionDeg:number;sampleSpacingDeg:number;points:SSTPoint[];url:string;kind:'analysis'};
export type ProtectionLayer={sourceId:string;fetchedAt:string;url:string;license:string;attribution:string;featureCollection:{type:'FeatureCollection';features:any[]}};
export type SpatialData={surfaceTemperature?:SurfaceTemperature;protectedAreas?:ProtectionLayer};

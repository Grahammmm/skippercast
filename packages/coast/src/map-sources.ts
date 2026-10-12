import type {CloudImage,CurrentField,CurrentFrame} from './ocean-types.ts';

// Sources are fixed publisher endpoints, never URLs supplied by query parameters.
export const mapSourceHosts = ['https://imagery.nationalmap.gov','https://nowcoast.noaa.gov'] as const;
export const shorelineAttribution = 'NOAA National Geodetic Survey · CUSP shoreline';
export const shorelineSource = {type:'geojson' as const,data:'/data/slo-shoreline.geojson',attribution:shorelineAttribution};

/** Natural-color NAIP aerial mosaic: dated shoreline context, not live satellite or bottom imagery. */
export function naipSource() {
 const rule=encodeURIComponent(JSON.stringify({rasterFunction:'NaturalColor'}));
 return {type:'raster' as const,tileSize:256,minzoom:7,maxzoom:19,
  tiles:[`https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?f=image&bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857&size=256,256&format=png32&transparent=true&renderingRule=${rule}`],
  attribution:'USGS / USDA · NAIP aerial imagery (dated mosaic)'};
}

/** Never use `current`/`latest` in tile URLs: every frame is pinned to a published acquisition time. */
export function cloudSource(cloud:CloudImage,now:Date=new Date()) {
 const sample=Date.parse(cloud.observedAt),age=now.getTime()-sample;
 if(!Number.isFinite(sample)||age < -300000||age>90*60000||!cloud.availableTimes.includes(cloud.observedAt))return null;
 return {type:'raster' as const,tileSize:512,minzoom:0,maxzoom:9,
  tiles:[`https://nowcoast.noaa.gov/geoserver/observations/satellite/ows?service=WMS&version=1.1.1&request=GetMap&layers=goes_longwave_imagery&styles=&interpolations=bilinear&format=image/png&transparent=true&width=512&height=512&srs=EPSG:3857&bbox={bbox-epsg-3857}&time=${encodeURIComponent(cloud.observedAt)}`],
  attribution:cloud.attribution};
}

/** Returns a native frame; no interpolated forecast times or projected observations. */
export function selectCurrentFrame(field:CurrentField,selectedAt:string|Date,now:Date=new Date()):CurrentFrame|null {
 const selected=new Date(selectedAt).getTime(),clock=now.getTime();
 const fetched=Date.parse(field.fetchedAt);
 if(!Number.isFinite(selected)||!Number.isFinite(fetched)||fetched>clock+300000||clock-fetched>6*3600000)return null;
 if(field.kind==='observation'){
  // Observations represent now or a historical instant, never a future timeline hour.
  if(selected>clock+300000)return null;
  return [...field.frames].reverse().find(f=>{const at=Date.parse(f.validAt);return at<=selected&&selected-at<=6*3600000&&clock-at<=6*3600000&&f.cells.length>0;})??null;
 }
 const issued=field.issuedAt?Date.parse(field.issuedAt):NaN;
 if(!Number.isFinite(issued)||issued>clock+300000||clock-issued>36*3600000||!field.frames.length)return null;
 const first=Date.parse(field.frames[0]!.validAt),last=Date.parse(field.frames.at(-1)!.validAt);
 if(selected<first||selected>last)return null;
 const nearest=field.frames.reduce((a,b)=>Math.abs(Date.parse(a.validAt)-selected)<=Math.abs(Date.parse(b.validAt)-selected)?a:b);
 return Math.abs(Date.parse(nearest.validAt)-selected)<=90*60000&&nearest.cells.length?nearest:null;
}

/** Sample points at returned wet cells: leave missing cells blank. Animation may illustrate direction only. */
export function currentFeatures(frame:CurrentFrame) {
 return {type:'FeatureCollection' as const,features:frame.cells.map(c=>({type:'Feature' as const,
  geometry:{type:'Point' as const,coordinates:[c.lon,c.lat]},
  properties:{speedKnots:c.speedKnots,towardDeg:c.towardDeg,uMs:c.uMs,vMs:c.vMs,validAt:frame.validAt,
   ...(c.hdop!==undefined?{hdop:c.hdop,radarCount:c.radarCount}:{}),surfaceOnly:true}}))};
}

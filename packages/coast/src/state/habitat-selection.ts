import {coastFetch} from '../transport.ts';
import {speciesOptions} from '../habitat-types.ts';
import {readReviewedHabitat,validateHabitatHeads} from '../map/habitat-lifecycle.ts';
import {boundedBytes,reefBindingMatches,rankedHabitat,verifiedAsset,type Asset} from '../coast3d/regional.ts';

/** Context only: no export permission, catch prediction or geographic inference. */
export type HabitatSelectionReceipt={id:string;latitude:number;longitude:number;region?:string;expiresAt:string;kind:'reef'|'shore'};
export type HabitatSelectionRequest={id:string;species:string;depthLimitFt?:number};
export type HabitatSelectionOptions={signal?:AbortSignal;isCurrent?:()=>boolean};
async function metadata(path:string,options:HabitatSelectionOptions){
 const response=await coastFetch(path,{cache:'no-store',signal:options.signal?AbortSignal.any([options.signal,AbortSignal.timeout(15000)]):AbortSignal.timeout(15000)});
 if(!response.ok||!response.body)throw Error('Habitat metadata unavailable');
 return JSON.parse(new TextDecoder().decode(await boundedBytes(response.body,512*1024)));
}
function exact(features:any[],id:string){const matches=features.filter(f=>String(f.id??f.properties?.id)===id);return matches.length===1?matches[0]:null;}
function receipt(feature:any,kind:'reef'|'shore',expires:number):HabitatSelectionReceipt|null{
 const p=feature.properties,c=kind==='shore'?(p.access?.[0]?.coordinates??feature.geometry.coordinates[0]?.[0]):[p.waypoint_longitude,p.waypoint_latitude];
 if(!Array.isArray(c)||!Number.isFinite(c[0])||!Number.isFinite(c[1])||Math.abs(c[0])>180||Math.abs(c[1])>90||!Number.isFinite(expires)||expires<=Date.now())return null;
 return {id:String(feature.id??p.id),latitude:c[1],longitude:c[0],...(typeof p.region==='string'?{region:p.region}:{}),expiresAt:new Date(expires).toISOString(),kind};
}
/** Resolve only an exact original identity admitted by the viewer's existing
 * publication gates. Caller owns visibility, generation and receipt expiry.
 * Cancellation prevents publication; existing asset readers retain their bounded
 * timeouts and may finish an already-started read after caller cancellation. */
export async function resolveHabitatSelection(request:HabitatSelectionRequest,options:HabitatSelectionOptions={}):Promise<HabitatSelectionReceipt|null>{
 const current=()=>!options.signal?.aborted&&(options.isCurrent?.()??true);
 const species=speciesOptions.find(s=>s.id===request.species),depth=request.depthLimitFt??300;
 if(!current()||!species||typeof request.id!=='string'||!request.id||!Number.isFinite(depth)||depth<0)return null;
 try{
  if(['halibut','surfperch'].includes(species.id)){
   const manifest=await metadata('/data/coast-wide/manifest.json',options);if(!current()||manifest.schemaVersion!==1||manifest.origin?.[0]!==-120.98||manifest.origin?.[1]!==35.43)return null;
   const data=JSON.parse(new TextDecoder().decode(await verifiedAsset(manifest.shoreAsset as Asset)));if(!current()||!Array.isArray(data.features))return null;
   const feature=exact(data.features.filter((f:any)=>f.geometry?.type==='MultiLineString'&&Date.parse(f.properties?.reviewExpiresAt)>Date.now()),request.id);
   return feature&&current()?receipt(feature,'shore',Date.parse(feature.properties.reviewExpiresAt)):null;
  }
  const reviewed=await readReviewedHabitat('/data/skippercast-manifest.json','/data/skippercast-habitat.geojson');if(!current())return null;
  let full=reviewed.details,contextExpires=Infinity;
  try{
   const context=await metadata('/data/coast-wide/reef-context.json',options);if(!current())return null;
   if(reefBindingMatches(context,reviewed.manifest)){
    const data=JSON.parse(new TextDecoder().decode(await verifiedAsset(context.asset,64*1024*1024)));if(!current())return null;
    if(!Array.isArray(data.features)||data.features.length!==context.featureCount)throw Error('Reef context shape changed');
    const detailed=new Map(reviewed.details.map(f=>[String(f.id??f.properties.id),f]));full=data.features.map((f:any)=>detailed.get(String(f.id??f.properties.id))??f);contextExpires=Date.parse(context.expiresAt);
   }
  }catch{full=reviewed.details;contextExpires=Infinity;}
  if(!current())return null;
  await validateHabitatHeads(reviewed.manifest);if(!current())return null;
  const feature=exact(rankedHabitat(full,species.field).filter(f=>f.properties.depth_max_ft<=depth),request.id);if(!feature)return null;
  return receipt(feature,'reef',Math.min(Date.parse(feature.properties.screen_expires_at),Date.parse(reviewed.manifest.expiresAt),...reviewed.manifest.regions.map(r=>Date.parse(r.expiresAt)),contextExpires));
 }catch{return null;}
}

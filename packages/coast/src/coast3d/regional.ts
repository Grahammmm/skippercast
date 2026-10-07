import {coastFetch} from '../transport.ts';
import type {Grid} from './grid.ts';
export type Asset={url:string;sha256:string;bytes:number;encoding?:'gzip';decodedBytes?:number};
export type LOD=Asset&{size:number;spacing:number};
export type RegionTile={x:number;z:number;width:number;lods:LOD[];lidarFraction?:number};
export type TerrainSource={id:number;label:string;kind:string;resolutionM:number|null;datum:string;sourceDate:string;url:string};
export type RegionalManifest={schemaVersion:number;origin:number[];bounds:number[];overview:Asset&{size:number;x:number;z:number;dx:number;dz:number};background?:Asset&{size:number;x:number;z:number;dx:number;dz:number};tiles:RegionTile[];harborTiles:RegionTile[];imagery:(Asset&{bounds:number[];kind:string})[];overviewImagery?:Asset&{bounds:number[]};sources:TerrainSource[];waterReferenceM:number};
export async function boundedBytes(stream:ReadableStream<Uint8Array>,maximum:number):Promise<Uint8Array<ArrayBuffer>>{
 const reader=stream.getReader(),parts:Uint8Array[]=[];let length=0;
 try{for(;;){const item=await reader.read();if(item.done)break;length+=item.value.length;if(length>maximum){await reader.cancel();throw Error('Asset exceeds byte budget');}parts.push(item.value);}}finally{reader.releaseLock();}
 const out=new Uint8Array(length);let at=0;for(const part of parts){out.set(part,at);at+=part.length;}return out;
}
export async function verifiedAsset(asset:Asset,maxDecodedBytes=20*1024*1024):Promise<ArrayBuffer>{
 if(!Number.isSafeInteger(asset.bytes)||asset.bytes<1||asset.bytes>20*1024*1024||!/^\/data\//.test(asset.url)||!/^[a-f0-9]{64}$/.test(asset.sha256))throw Error('Invalid asset contract');
 const r=await coastFetch(asset.url,{signal:AbortSignal.timeout(30000)});if(!r.ok||!r.body)throw Error('Asset unavailable');
 const data=await boundedBytes(r.body,asset.bytes);if(data.length!==asset.bytes)throw Error('Asset length changed');
 const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),n=>n.toString(16).padStart(2,'0')).join('');if(hash!==asset.sha256)throw Error('Asset identity changed');
 if(asset.encoding==='gzip'){
  if(!asset.decodedBytes||asset.decodedBytes>maxDecodedBytes||maxDecodedBytes>64*1024*1024)throw Error('Invalid decoded byte budget');
  const decoded=await boundedBytes(new Blob([data]).stream().pipeThrough(new DecompressionStream('gzip')),asset.decodedBytes);
  if(decoded.length!==asset.decodedBytes)throw Error('Decoded asset length changed');return decoded.buffer;
 }return data.buffer;
}
export function decodeTerrain(data:ArrayBuffer,size:number,x:number,z:number,dx:number,dz=dx,allowedSources:ReadonlySet<number>=new Set([1,2,3,4,5,6,7])):Grid{
 if(!Number.isInteger(size)||size<2||size>1025||data.byteLength!==size*size*5||![x,z,dx,dz].every(Number.isFinite)||dx<=0||dz<=0)throw Error('Invalid terrain shape');
 const values=new Float32Array(data,0,size*size),sources=new Uint8Array(data,size*size*4,size*size);
 if(values.some(v=>!Number.isFinite(v))||sources.some(s=>!allowedSources.has(s)))throw Error('Invalid terrain sample');
 return {x,z,size,dx,dz,values,sources};
}
// Continuous display triangles are separate from the measured-only export mesh.
// Every vertex still carries its original source class and unblended reading.
export function continuousTriangles(n:number):Uint32Array{
 const out=new Uint32Array((n-1)**2*6);let i=0;for(let z=0;z<n-1;z++)for(let x=0;x<n-1;x++){const a=z*n+x;out.set([a,a+n,a+1,a+1,a+n,a+n+1],i);i+=6;}return out;
}
export function chooseTiles(tiles:RegionTile[],x:number,z:number,span:number,limit=100):RegionTile[]{
 const radius=Math.max(6500,Math.min(45000,span*.85));return tiles.filter(t=>Math.hypot(t.x+t.width/2-x,t.z+t.width/2-z)<radius).sort((a,b)=>Math.hypot(a.x+a.width/2-x,a.z+a.width/2-z)-Math.hypot(b.x+b.width/2-x,b.z+b.width/2-z)).slice(0,limit);
}
export function reefBindingMatches(context:{regions:{regionId:string;archiveSha256:string;exportSha256:string}[];expiresAt:string},manifest:{regions:{regionId:string;archiveSha256:string;exportSha256?:string}[]},now=Date.now()):boolean{
 return Date.parse(context.expiresAt)>now&&context.regions.length===manifest.regions.length&&context.regions.every(r=>manifest.regions.some(m=>m.regionId===r.regionId&&m.archiveSha256===r.archiveSha256&&m.exportSha256===r.exportSha256));
}
export function rankedHabitat(features:any[],field:string|null,now=Date.now()):any[]{
 return features.filter(f=>f?.properties?.exportable===true&&f.properties.screen_status==='pass'&&Date.parse(f.properties.screen_expires_at)>now&&(!field||f.properties[field]>=2)&&f.geometry?.type==='Polygon').sort((a,b)=>(field?b.properties[field]-a.properties[field]:0)||b.properties.terrain_score-a.properties.terrain_score||String(a.id??a.properties.id).localeCompare(String(b.id??b.properties.id)));
}
type DisplaySource=Pick<TerrainSource,'id'|'kind'|'resolutionM'>;
const legacyDisplaySources:readonly DisplaySource[]=[{id:1,kind:'model',resolutionM:463},{id:2,kind:'land',resolutionM:null},{id:3,kind:'estimate',resolutionM:null},...[4,5,6].map(id=>({id,kind:'survey',resolutionM:2})),{id:7,kind:'lidar',resolutionM:1}];
/**
 * Presentation transitions only; values, source masks and inspection stay raw.
 * Fine survey/lidar vertices are never softened. A same-source tent filter
 * removes nearest-sampled fallback stairs with <=32 m Manhattan support. A
 * transition band can then meet original fine support within that same radius.
 * This is a display surface, not an additional measured/interpolated survey.
 * Unsupported interiors retain their source and coarse context; no coverage is added.
 */
export function displayElevations(grid:Grid,sources:readonly DisplaySource[]=legacyDisplaySources):Float32Array{
 const out=grid.values.slice(),n=grid.size,ids=grid.sources;if(!ids)return out;
 const fallback=new Uint8Array(256),fine=new Uint8Array(256);
 for(const source of sources){fallback[source.id]=Number(['model','land','estimate'].includes(source.kind));fine[source.id]=Number(['survey','lidar'].includes(source.kind)&&source.resolutionM!==null&&source.resolutionM<=8&&source.resolutionM>0);}
 // Filter only original values of the same fallback source. A measured cliff,
 // different source reference, or source mask is never averaged into this pass.
 const radius=32,kernel:{x:number;z:number;weight:number}[]=[];
 for(let z=-Math.ceil(radius/grid.dz)+1;z<Math.ceil(radius/grid.dz);z++)for(let x=-Math.ceil(radius/grid.dx)+1;x<Math.ceil(radius/grid.dx);x++){const distance=Math.abs(x)*grid.dx+Math.abs(z)*grid.dz;if(distance<radius)kernel.push({x,z,weight:1-distance/radius});}
 if(kernel.length>1)for(let z=0;z<n;z++)for(let x=0;x<n;x++){const i=z*n+x;if(!fallback[ids[i]])continue;let sum=0,weight=0;
  for(const point of kernel){const cx=x+point.x,cz=z+point.z;if(cx<0||cz<0||cx>=n||cz>=n)continue;const j=cz*n+cx;if(ids[j]===ids[i]){sum+=grid.values[j]*point.weight;weight+=point.weight;}}
  out[i]=sum/weight;
 }
 const step=grid.dx;if(step!==grid.dz||step>radius/2)return out;
 // Multi-source breadth-first propagation is linear in grid size. Only coarse
 // fallback cells carry support onward; another native survey is never crossed.
 // Manhattan distance bounds the spatial influence to <=32 m in every direction.
 const count=n*n,targets=new Float32Array(count),distance=new Uint16Array(count),queue=new Int32Array(count);let head=0,tail=0;
 const neighbors=(i:number)=>{const x=i%n,z=Math.floor(i/n);return [x>0?i-1:-1,x<n-1?i+1:-1,z>0?i-n:-1,z<n-1?i+n:-1];};
 for(let i=0;i<count;i++)if(fallback[ids[i]]){let low=Infinity,high=-Infinity;for(const j of neighbors(i))if(j>=0&&fine[ids[j]]){low=Math.min(low,grid.values[j]);high=Math.max(high,grid.values[j]);}
  // The midrange minimizes the largest join to adjacent original fine samples.
  // It cannot increase the largest native/fallback step at this boundary cell.
  if(Number.isFinite(low)){if(Math.max(Math.abs(low-grid.values[i]),Math.abs(high-grid.values[i]))>8){targets[i]=(low+high)/2;distance[i]=1;queue[tail++]=i;}
   else {distance[i]=65535;out[i]=Math.max(high-8,Math.min(low+8,out[i]));} // Preserve the <=8m gentle join after context filtering; block another band.
  }
 }
 while(head<tail){const i=queue[head++],nextDistance=distance[i]+1;if(nextDistance*step>=radius)continue;const x=i%n,z=Math.floor(i/n);
  for(const j of [x>0?i-1:-1,x<n-1?i+1:-1,z>0?i-n:-1,z<n-1?i+n:-1])if(j>=0&&fallback[ids[j]]&&distance[j]===0){targets[j]=targets[i];distance[j]=nextDistance;queue[tail++]=j;}
 }
 for(let i=0;i<count;i++)if(fallback[ids[i]]&&distance[i]>0&&distance[i]<65535){const t=Math.max(0,(distance[i]*step-step)/(radius-step)),weight=1-t*t*(3-2*t);out[i]+=weight*(targets[i]-out[i]);}
 return out;
}
/** Match numpy.rint used by the chart compiler, including halfway cell ties. */
export function roundEven(value:number):number{const lo=Math.floor(value);return value-lo===.5?(lo%2===0?lo:lo+1):Math.round(value);}

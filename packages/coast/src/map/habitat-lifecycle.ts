import {coastFetch} from '../transport.ts';
import type {HabitatManifest,HabitatRegion} from '../habitat-types.ts';

const REQUEST_TIMEOUT_MS=15000;
const RETRY_INTERVAL_MS=60000;
type Fetcher=(input:string,init?:RequestInit)=>Promise<Response>;
export type ReviewedHabitat={manifest:HabitatManifest;details:any[]};
async function bytes(response:Response,max:number):Promise<Uint8Array<ArrayBuffer>>{
 const declared=response.headers.get('Content-Length');
 if(declared!==null&&(!/^\d+$/.test(declared)||Number(declared)>max)){await response.body?.cancel();throw Error('Habitat asset exceeds byte budget');}
 if(!response.body)throw Error('Missing habitat body');
 const reader=response.body.getReader(),parts:Uint8Array[]=[];let length=0;
 try{for(;;){const part=await reader.read();if(part.done)break;length+=part.value.byteLength;
  if(length>max){await reader.cancel();throw Error('Habitat asset exceeds byte budget');}parts.push(part.value);}}
 finally{reader.releaseLock();}
 const result=new Uint8Array(length);let offset=0;for(const part of parts){result.set(part,offset);offset+=part.byteLength;}return result;
}

export function habitatReleaseFresh(manifest:HabitatManifest,now=Date.now()):boolean{
 const expires=(at:string)=>Number.isFinite(Date.parse(at))&&Date.parse(at)>now;
 return manifest.ready===true&&expires(manifest.expiresAt)&&Array.isArray(manifest.regions)&&manifest.regions.length>0&&
  new Set(manifest.regions.map(r=>r.regionId)).size===manifest.regions.length&&manifest.regions.every(r=>
   /^[a-z0-9-]+$/.test(r.regionId)&&r.ready===true&&r.commercialArchivePermitted===true&&
   r.license==='public-domain-us-gov'&&expires(r.expiresAt)&&/^[a-f0-9]{64}$/.test(r.archiveSha256)&&
   /^"[^"\r\n]+"$/.test(r.archiveETag)&&Number.isSafeInteger(r.archiveBytes)&&r.archiveBytes>0);
}

export function habitatEndpoint(region:HabitatRegion,manifest?:HabitatManifest):string{
 return '/api/habitat/tiles?region='+encodeURIComponent(region.regionId)+
  (typeof manifest?.releaseId==='string'&&/^[a-f0-9]{64}$/.test(manifest.releaseId)?'&release='+manifest.releaseId:'');
}

// The proxy independently checks the live producer publication, rights, hash and expiry.
// Matching its HEAD receipt also prevents mixing a newer Worker pin with an older page asset.
export async function validateHabitatHeads(manifest:HabitatManifest,fetcher:Fetcher=coastFetch,now=Date.now):Promise<void>{
 if(!habitatReleaseFresh(manifest,now()))throw Error('Unusable reviewed habitat release');
 const receipts=await Promise.all(manifest.regions.map(r=>fetcher(habitatEndpoint(r,manifest),{
  method:'HEAD',cache:'no-store',signal:AbortSignal.timeout(REQUEST_TIMEOUT_MS)
 })));
 if(receipts.some((receipt,i)=>!receipt.ok||receipt.headers.get('ETag')!==manifest.regions[i].archiveETag||
  receipt.headers.get('Content-Length')!==String(manifest.regions[i].archiveBytes)||
  (manifest.consumerContract==='fish-habitat-v1'&&receipt.headers.get('X-Fish-Habitat-Release')!==manifest.releaseId))||!habitatReleaseFresh(manifest,now()))
  throw Error('Reviewed habitat publication changed');
}

export async function readReviewedHabitat(manifestUrl:string,detailsUrl:string,fetcher:Fetcher=coastFetch,now=Date.now):Promise<ReviewedHabitat>{
 const get=(url:string)=>fetcher(url,{cache:'no-store',signal:AbortSignal.timeout(REQUEST_TIMEOUT_MS)});
 const r=await get(manifestUrl);if(!r.ok)throw Error('Missing reviewed habitat assets');
 const manifest=JSON.parse(new TextDecoder().decode(await bytes(r,512*1024))) as HabitatManifest;
 const live=manifest.consumerContract==='fish-habitat-v1';
 const d=await get(detailsUrl+(live?'?release='+encodeURIComponent(String(manifest.releaseId)):''));
 if(!d.ok)throw Error('Missing reviewed habitat assets');
 const detailBytes=await bytes(d,2*1024*1024);
 if(typeof manifest.geojsonSha256==='string'){
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',detailBytes)),n=>n.toString(16).padStart(2,'0')).join('');
  if(digest!==manifest.geojsonSha256||detailBytes.byteLength!==manifest.geojsonBytes)throw Error('Habitat detail publication changed');
 }
 if(live&&d.headers.get('X-Fish-Habitat-Release')!==manifest.releaseId)throw Error('Habitat detail publication changed');
 const curated=JSON.parse(new TextDecoder().decode(detailBytes)) as {features:any[]};
 if(!Array.isArray(curated.features))throw Error('Missing reviewed habitat details');
 await validateHabitatHeads(manifest,fetcher,now);
 const details=curated.features.filter(f=>f?.properties?.exportable===true&&f.properties.screen_status==='pass'&&
  Number.isFinite(Date.parse(f.properties.screen_expires_at))&&Date.parse(f.properties.screen_expires_at)>now());
 return {manifest,details};
}

// One lock covers initial load, health checks and recovery. Withdrawal cancels the
// current publication token; even a successful late response cannot reveal it.
export class HabitatRetryGate{
 private running=false;private revision=0;private retryAt=0;
 private now:()=>number;
 constructor(now:()=>number=Date.now){this.now=now;}
 invalidate(){this.revision++;this.retryAt=this.now()+RETRY_INTERVAL_MS;}
 async run(work:(current:()=>boolean)=>Promise<void>,failed:()=>void):Promise<void>{
  if(this.running||this.now()<this.retryAt)return;
  this.running=true;const revision=this.revision;
  try{await work(()=>revision===this.revision);}catch{failed();}
  finally{this.running=false;this.retryAt=Math.max(this.retryAt,this.now()+RETRY_INTERVAL_MS);}
 }
}

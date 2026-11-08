// A region-sized canonical export, only while its exact publication is current.
import {loadManifest,FEED_ROOT,manifestState,sourceRightsDetails} from './seafloor-data.js';
import {evidenceConfidence} from './spot-ranking.js';
import {pointInGeometry} from './geo-screen.js';
import {geometryTrack} from './gpx.js';
const MAX_TRANSFER=32*1024*1024,MAX_DECODED=128*1024*1024;
async function boundedBytes(stream,limit,expected){
  const reader=stream.getReader(),chunks=[];let length=0;
  try{
    for(;;){const {value,done}=await reader.read();if(done)break;length+=value.length;
      if(length>limit)throw Error('Reef export exceeds its published size.');chunks.push(value);}
  }catch(e){await reader.cancel().catch(()=>{});throw e;}finally{reader.releaseLock();}
  if(length!==expected)throw Error('Reef export revision changed. Reload the plan.');
  const bytes=new Uint8Array(length);let offset=0;
  for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}return bytes;
}
// SC-PERF-PROTCHECK-1: the publisher's protected-area verdict for a reef (geo-screen.js `screenPlace`'s answer, computed once at publish time).
// Anything of another shape is dropped, so the browser runs the screen itself.
const validVerdict=v=>!!v&&typeof v.inside==='boolean'&&typeof v.screened==='boolean'&&(v.name===null||typeof v.name==='string')&&(v.distanceM===null||Number.isFinite(v.distanceM));
// SC-PERF-REEFDIET-1: `slim` reads the publisher's attribute-only file (habitat-slim-<sha16>.geojson.gz, named by its own hash: no outlines, every reef with its verdict) instead of the
// full export, for the brief and its ranking. It throws when the manifest names no slim file or the file is not usable; `loadReefTripBrief` then loads the full export.
// The planner, map and GPX export call `loadReefTrip` without it and keep the outlines.
export async function loadReefTrip(region,{fetchImpl=globalThis.fetch,now=Date.now(),slim=false}={}) {
  const gate=await loadManifest(region,fetchImpl,now);
  if(gate.state!=='ready')throw Error(gate.reason);
  const m=gate.manifest;
  if(!['habitat-export.geojson','habitat-export.geojson.gz'].includes(m.export_file)||!/^[a-f0-9]{64}$/.test(m.export_sha256||''))throw Error('Ranked reef export is awaiting the next seafloor publication.');
  const file=slim?m.slim_file:m.export_file,sha=slim?m.slim_sha256:m.export_sha256,size=slim?m.slim_bytes:m.export_bytes,decodedSize=slim?m.slim_decoded_bytes:m.export_decoded_bytes;
  if(slim&&(!/^[a-f0-9]{64}$/.test(sha||'')||file!==`habitat-slim-${sha.slice(0,16)}.geojson.gz`))throw Error('Slim reef file is not published.');
  const compressed=file.endsWith('.gz');
  if(!Number.isInteger(size)||size<=0||size>MAX_TRANSFER
      ||(compressed&&(!Number.isInteger(decodedSize)||decodedSize<=0||decodedSize>MAX_DECODED)))throw Error('Reef export size is unavailable or too large.');
  const response=await fetchImpl(`${FEED_ROOT}regions/${region}/${file}`,{cache:'no-store',signal:AbortSignal.timeout(60000)});
  if(!response.ok)throw Error('Ranked reef boundaries could not load. Try again.');
  if(!response.body)throw Error('Reef export body is unavailable.');
  let bytes=await boundedBytes(response.body,size,size);
  const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(n=>n.toString(16).padStart(2,'0')).join('');
  if(hash!==sha)throw Error('Reef export checksum changed. Reload the plan.');
  if(compressed){
    if(typeof DecompressionStream!=='function')throw Error('Update your browser to load compressed reef boundaries.');
    const decoded=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    bytes=await boundedBytes(decoded,decodedSize,decodedSize);
  }
  const latest=await loadManifest(region,fetchImpl);
  if(latest.state!=='ready'||latest.manifest.export_sha256!==m.export_sha256||(slim&&latest.manifest.slim_sha256!==sha))throw Error('Reef publication changed while loading. Select Best available again.');
  const data=JSON.parse(new TextDecoder().decode(bytes));
  if(data.region!==region||data.type!=='FeatureCollection'||!Array.isArray(data.features)||data.expires_at!==m.expires_at
      ||manifestState(m,region,Date.now()).state!=='ready')throw Error('Reef export is expired or belongs to another region.');
  if(slim&&(data.slim_of!==m.export_sha256||typeof data.protected_screen?.fingerprint!=='string'))throw Error('Slim reef file does not match its export.');
  const seen=new Set(),targets=[],areas=[];
  for(const f of data.features){
    const p=f.properties,w=p?.waypoint;
    if(!p||p.region!==region||p.tier!==2||p.status!=='habitat'||p.exportable!==true||p.screen?.status!=='pass'
      ||typeof p.id!=='string'||seen.has(p.id)||!Number.isFinite(w?.longitude)||!Number.isFinite(w?.latitude))throw Error('Reef export contains an unqualified or duplicate area.');
    if(!slim)geometryTrack(p.id,'',f.geometry);
    if((!slim&&!pointInGeometry([w.longitude,w.latitude],f.geometry))||!['A','B','C'].includes(p.terrain?.grade)||!Number.isFinite(p.terrain?.score))throw Error('Reef reference point or terrain score is invalid.');
    if(slim&&!validVerdict(p.protected_place))throw Error('Slim reef file lacks a protected-area verdict.');
    seen.add(p.id);
    const rights=sourceRightsDetails(p.source_rights);
    if(m.source_use_notice&&!rights.length)throw Error('Reef source credits or use terms are incomplete.');
    const sourceNote=rights.map(r=>`${r.credit} ${r.notice}${r.policyURL?' '+r.policyURL:''}`).join(' ');
    const c=evidenceConfidence(p);
    const t={id:p.id,canonical_habitat:true,name:p.id,label:'Surveyed reef habitat',latitude:w.latitude,longitude:w.longitude,
      center_depth_ft:null,neighborhood_depth_ft:[p.depth_min_ft,p.depth_max_ft],vertical_datum:p.vertical_datum,
      habitat_grade:p.terrain?.grade,habitat_score:p.terrain?.score,metrics:p.terrain,
      species_fit:p.fit,resolution_m:p.resolution_m,evidence_confidence:c,
      area_ids:[p.id],drift_id:null,source_url:p.source_urls?.[0]||'',survey_year:p.source_year,
      terrain_interpretation:`${p.terrain?.relief_210m_m?.toFixed(1)??'Unknown'} m local relief; ${p.area_ha?.toFixed(1)??'unknown'} ha reef footprint.`,
      special_note:'Interior reef reference point, not a sampled point depth. Search the reef on your sounder and test your drift.'+(sourceNote?' '+sourceNote:''),
      source_rights:rights,
      evidence_status:c?`${c.percent}% habitat evidence index (${c.version}); not catch probability.`:'Evidence confidence unavailable.',
      ais_status:'No charter AIS confirmation implied.'};
    if(validVerdict(p.protected_place))t.protected_place=p.protected_place;
    targets.push(t);
    if(!slim)areas.push({id:p.id,geometry:f.geometry,target_ids:[p.id],area_ha:p.area_ha,
      extent_note:`Canonical screened reef boundary; nominal ${Math.round(p.depth_min_ft)}-${Math.round(p.depth_max_ft)} ft. ${t.evidence_status}${sourceNote?' '+sourceNote:''}`});
  }
  const print=data.protected_screen?.fingerprint;
  return {targets,areas,drifts:[],...(slim?{slim:true}:{}),...(typeof print==='string'?{protected_fingerprint:print}:{}),publication:{...m,verified_at:new Date().toISOString()},source_validation_date:m.built_at};
}
// SC-PERF-REEFDIET-1: the brief's load: the slim file when the publication has a usable one, else (any failure) the full export, as before.
export async function loadReefTripBrief(region,opts={}){
  try{return await loadReefTrip(region,{...opts,slim:true});}
  catch{return loadReefTrip(region,opts);}
}

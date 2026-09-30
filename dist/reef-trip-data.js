// A region-sized canonical export, only while its exact publication is current.
import {loadManifest,FEED_ROOT,manifestState} from './seafloor-data.js';
import {evidenceConfidence} from './spot-ranking.js';
import {pointInGeometry} from './geo-screen.js';
import {geometryTrack} from './gpx.js';
export async function loadReefTrip(region,{fetchImpl=globalThis.fetch,now=Date.now()}={}) {
  const gate=await loadManifest(region,fetchImpl,now);
  if(gate.state!=='ready')throw Error(gate.reason);
  const m=gate.manifest;
  if(m.export_file!=='habitat-export.geojson'||!/^[a-f0-9]{64}$/.test(m.export_sha256||''))throw Error('Ranked reef export is awaiting the next seafloor publication.');
  if(!Number.isInteger(m.export_bytes)||m.export_bytes<=0||m.export_bytes>32*1024*1024)throw Error('Reef export size is unavailable or too large.');
  const response=await fetchImpl(`${FEED_ROOT}regions/${region}/habitat-export.geojson`,{cache:'no-store',signal:AbortSignal.timeout(18000)});
  if(!response.ok)throw Error('Ranked reef boundaries could not load. Try again.');
  if(!response.body)throw Error('Reef export body is unavailable.');
  const reader=response.body.getReader(),chunks=[];let length=0;
  try{
    for(;;){const {value,done}=await reader.read();if(done)break;length+=value.length;
      if(length>m.export_bytes)throw Error('Reef export exceeds its published size.');chunks.push(value);}
  }catch(e){await reader.cancel().catch(()=>{});throw e;}finally{reader.releaseLock();}
  const bytes=new Uint8Array(length);let offset=0;
  for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  if(bytes.byteLength!==m.export_bytes)throw Error('Reef export revision changed. Reload the plan.');
  const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(n=>n.toString(16).padStart(2,'0')).join('');
  if(hash!==m.export_sha256)throw Error('Reef export checksum changed. Reload the plan.');
  const latest=await loadManifest(region,fetchImpl);
  if(latest.state!=='ready'||latest.manifest.export_sha256!==m.export_sha256)throw Error('Reef publication changed while loading. Select Best available again.');
  const data=JSON.parse(new TextDecoder().decode(bytes));
  if(data.region!==region||data.type!=='FeatureCollection'||!Array.isArray(data.features)||data.expires_at!==m.expires_at
      ||manifestState(m,region,Date.now()).state!=='ready')throw Error('Reef export is expired or belongs to another region.');
  const seen=new Set(),targets=[],areas=[];
  for(const f of data.features){
    const p=f.properties,w=p?.waypoint;
    if(!p||p.region!==region||p.tier!==2||p.status!=='habitat'||p.exportable!==true||p.screen?.status!=='pass'
      ||typeof p.id!=='string'||seen.has(p.id)||!Number.isFinite(w?.longitude)||!Number.isFinite(w?.latitude))throw Error('Reef export contains an unqualified or duplicate area.');
    geometryTrack(p.id,'',f.geometry);
    if(!pointInGeometry([w.longitude,w.latitude],f.geometry)||!['A','B','C'].includes(p.terrain?.grade)||!Number.isFinite(p.terrain?.score))throw Error('Reef reference point or terrain score is invalid.');
    seen.add(p.id);
    const c=evidenceConfidence(p);
    const t={id:p.id,canonical_habitat:true,name:p.id,label:'Surveyed reef habitat',latitude:w.latitude,longitude:w.longitude,
      center_depth_ft:null,neighborhood_depth_ft:[p.depth_min_ft,p.depth_max_ft],vertical_datum:p.vertical_datum,
      habitat_grade:p.terrain?.grade,habitat_score:p.terrain?.score,metrics:p.terrain,
      species_fit:p.fit,resolution_m:p.resolution_m,evidence_confidence:c,
      area_ids:[p.id],drift_id:null,source_url:p.source_urls?.[0]||'',survey_year:p.source_year,
      terrain_interpretation:`${p.terrain?.relief_210m_m?.toFixed(1)??'Unknown'} m local relief; ${p.area_ha?.toFixed(1)??'unknown'} ha reef footprint.`,
      special_note:'Interior reef reference point, not a sampled point depth. Search the reef on your sounder and test your drift.',
      evidence_status:c?`${c.percent}% habitat evidence index (${c.version}); not catch probability.`:'Evidence confidence unavailable.',
      ais_status:'No charter AIS confirmation implied.'};
    targets.push(t);areas.push({id:p.id,geometry:f.geometry,target_ids:[p.id],area_ha:p.area_ha,
      extent_note:`Canonical screened reef boundary; nominal ${Math.round(p.depth_min_ft)}-${Math.round(p.depth_max_ft)} ft. ${t.evidence_status}`});
  }
  return {targets,areas,drifts:[],publication:{...m,verified_at:new Date().toISOString()},source_validation_date:m.built_at};
}

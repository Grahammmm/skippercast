// Planning sectors are discovery extents, never fishing spots or legal boundaries.
let packet;
export async function loadCoastalSectors() {
  if(packet) return packet;
  const response=await fetch('data/coastal-sectors.json',{signal:AbortSignal.timeout(10000)});
  if(!response.ok) throw Error('Coastal sector index unavailable');
  const value=await response.json();
  if(value.schema_version!==1 || !Array.isArray(value.sectors) || !value.sectors.length) throw Error('Invalid coastal sector index');
  packet=value;return value;
}
export function sectorsForCoast(value,coastId) {
  return (value?.sectors||[]).filter(sector=>sector.coast===coastId);
}
export function sectorAt(value,coastId,point) {
  if(!Number.isFinite(point?.latitude)||!Number.isFinite(point?.longitude)) return null;
  return sectorsForCoast(value,coastId).find(sector=>point.longitude>=sector.bounds[0] && point.longitude<=sector.bounds[2]
    && point.latitude>=sector.latitude[0] && (point.latitude<sector.latitude[1] || point.latitude===42 && sector.latitude[1]===42)) || null;
}
export async function loadSurveyDiscovery(sectors) {
  for(const url of [sectors.survey_feed_url,'data/noaa-survey-discovery.json']) {
    try {
      const response=await fetch(url,{cache:'no-cache',signal:AbortSignal.timeout(7000)});
      if(!response.ok) continue;
      const data=await response.json();
      if(data.schema_version===1 && data.scope==='noaa-bag-survey-discovery' && data.sector_count===sectors.sectors.length && Array.isArray(data.sectors)
        && data.sectors.length===sectors.sectors.length && typeof data.collected_at==='string' && ['ok','degraded'].includes(data.health?.status)) return data;
    }catch{/* Keep the local dated fallback. */}
  }
  return null;
}

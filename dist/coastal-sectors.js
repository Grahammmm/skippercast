// Planning sectors are discovery extents, never fishing spots or legal boundaries.
let packet;
const NOAA_HOSTS=new Set(['www.ngdc.noaa.gov','data.ngdc.noaa.gov','www.ncei.noaa.gov']);
export function trustedNoaaLink(value,id,kind='product') {
  if(typeof value!=='string'||!/^[A-Z][0-9]{5}$/.test(id)) return false;
  try {const url=new URL(value);
    return url.protocol==='https:' && NOAA_HOSTS.has(url.hostname) && !url.username && !url.password
      && (kind==='catalog'?url.pathname.endsWith(`/${id}.html`):url.pathname.includes(`/${id}/`));
  }catch{return false;}
}
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
        && data.sectors.length===sectors.sectors.length && typeof data.collected_at==='string' && ['ok','degraded'].includes(data.health?.status)
        && data.sectors.every(row=>Array.isArray(row.surveys) && row.surveys.every(item=>trustedNoaaLink(item.catalog_url,item.id,'catalog')))) return data;
    }catch{/* Keep the local dated fallback. */}
  }
  return null;
}

export async function loadSurveyProducts(sectors) {
  for(const url of [sectors.survey_product_feed_url,'data/noaa-survey-products.json']) {
    try {
      const response=await fetch(url,{cache:'no-cache',signal:AbortSignal.timeout(7000)});
      if(!response.ok) continue;
      const data=await response.json();
      if(data.schema_version===1 && data.scope==='noaa-survey-product-links' && Array.isArray(data.surveys)
        && data.survey_count===data.surveys.length && typeof data.collected_at==='string'
        && ['ok','degraded'].includes(data.health?.status)
        && data.surveys.every(row=>trustedNoaaLink(row.catalog_url,row.id,'catalog')
          && ['bag','report','xyz'].every(kind=>Array.isArray(row.products?.[kind])
            && row.products[kind].every(link=>trustedNoaaLink(link,row.id))))) return data;
    }catch{/* Keep the local dated fallback. */}
  }
  return null;
}

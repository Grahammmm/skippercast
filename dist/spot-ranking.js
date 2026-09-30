// Versioned evidence index. Percentages describe habitat evidence, never catch odds.
export const CONFIDENCE_VERSION = 'habitat-evidence-v1';
const finite = Number.isFinite;
const fraction = n => finite(n) && n >= 0 && n <= 1;
export const fitLabel = n => ({3:'Strong',2:'Good',1:'Secondary'}[n] || 'Unknown');
export function evidenceConfidence(p) {
  if (!Array.isArray(p.source_ids) || !p.source_ids.length || !fraction(p.metric_support_fraction)
      || !finite(p.resolution_m) || p.resolution_m <= 0) return null;
  const substrate = fraction(p.substrate?.known_fraction) ? p.substrate.known_fraction : 0;
  const components = {originalSurvey:25, metricSupport:25*p.metric_support_fraction,
    resolution:p.resolution_m<=4?20:p.resolution_m<=16?10:0,
    substrate:20*substrate, surveyDate:Number.isInteger(p.source_year)?5:0,
    independent: p.substrate?.independent_confirmation===true && p.independent_evidence?.length ? 5:0};
  const cap = !p.interpolation_mask || p.interpolation_mask === 'unknown' ? 90 : 100;
  return {percent:Math.min(cap,Math.round(Object.values(components).reduce((a,b)=>a+b,0))),
    version:CONFIDENCE_VERSION, components, cap,
    meaning:'Habitat evidence confidence index; not a calibrated probability of fish, catch or safe navigation.'};
}
export function distanceNm(a,b) {
  const rad=n=>n*Math.PI/180, dlat=rad(b.latitude-a.latitude), dlon=rad(b.longitude-a.longitude);
  const h=Math.sin(dlat/2)**2+Math.cos(rad(a.latitude))*Math.cos(rad(b.latitude))*Math.sin(dlon/2)**2;
  return 3440.065*2*Math.asin(Math.min(1,Math.sqrt(h)));
}
const fits = (t,species) => species==='lingcod' ? t.species_fit?.lingcod : species==='rockfish' ? t.species_fit?.['rockfish-reef']
  : Math.min(t.species_fit?.lingcod??0,t.species_fit?.['rockfish-reef']??0);
export function waypointTitle(t,rank=t.trip_rank) {
  const depth=t.neighborhood_depth_ft.map(n=>Math.round(n)).join('-');
  return `${String(rank).padStart(2,'0')} ${t.trip_species==='lingcod'?'LC':t.trip_species==='rockfish'?'RF':'LR'} H${t.trip_fit} C${t.evidence_confidence.percent}% ${depth}ft`;
}
export function bestSpots(atlas,screen,{species='reef',count=20,maxDepth=300,bounds=null,origin=null,maxDistanceNm=Infinity,minSeparationNm=.15,minConfidence=60}={}) {
  if(!screen?.ready()) throw Error('Refresh protected-area checks before selecting spots.');
  if(!['reef','lingcod','rockfish'].includes(species)) throw Error('Best reef spots supports lingcod and rockfish.');
  if(!finite(maxDepth)||maxDepth<=0||maxDepth>300||!Number.isInteger(count)||count<1||count>50) throw Error('Invalid trip filters.');
  const byArea=new Set(), selected=[];
  const eligible=atlas.targets.filter(t=>{
    const [lo,hi]=t.neighborhood_depth_ft||[];
    return t.canonical_habitat && t.evidence_confidence?.percent>=minConfidence && finite(lo)&&finite(hi)&&lo>=0&&hi<=maxDepth
      && t.resolution_m<=4 && [1,2,3].includes(fits(t,species)) && fits(t,species)>=2
      && screen.pointAllowed(t) && t.area_ids?.length && t.area_ids.every(id=>{
        const a=atlas.areas.find(a=>a.id===id);return a&&screen.geometryAllowed(a.geometry);
      }) && (!bounds||(t.longitude>=bounds[0]&&t.latitude>=bounds[1]&&t.longitude<=bounds[2]&&t.latitude<=bounds[3]))
      && (!origin||distanceNm(origin,t)<=maxDistanceNm);
  }).map(t=>({...t,trip_fit:fits(t,species),trip_species:species})).sort((a,b)=>b.trip_fit-a.trip_fit
    ||b.evidence_confidence.percent-a.evidence_confidence.percent||b.habitat_score-a.habitat_score||a.id.localeCompare(b.id));
  for(const t of eligible){
    if(t.area_ids.some(id=>byArea.has(id))||selected.some(s=>distanceNm(s,t)<minSeparationNm))continue;
    t.trip_rank=selected.length+1;t.name=waypointTitle(t);t.distance_nm=origin?distanceNm(origin,t):null;
    for(const id of t.area_ids)byArea.add(id);selected.push(t);if(selected.length===count)break;
  }
  return selected;
}

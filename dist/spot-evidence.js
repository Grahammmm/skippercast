import {getRegion,assetURL} from './region.js?v=8.11';
import {esc} from './marine-charts.js?v=8.11';
import {terrainSource} from './terrain-evidence.js?v=8.11';
const cache=new Map();
export function spotEvidence(target,species,profile,region){
  const measured=[],inferred=[],unknown=[];
  const source=terrainSource(target);
  if(Number.isFinite(target.center_depth_ft))measured.push(`Center ${target.center_depth_ft} ft ${source.datum}; ${source.producer} survey ${target.survey_year}. ${source.grid}.`);
  if(target.metrics){
    if(Number.isFinite(target.metrics.rugose_or_bedrock_fraction_210m))measured.push(`${Math.round(target.metrics.rugose_or_bedrock_fraction_210m*100)}% mapped rock/rough cover in the analysis neighborhood.`);
    if(Number.isFinite(target.metrics.relief_210m_m))measured.push(`${(target.metrics.relief_210m_m*3.28084).toFixed(0)} ft local relief${target.rating?' across the central 90% of analysis depths':''}.`);
    else if(Number.isFinite(target.rating?.relief_90_percent_m))measured.push(`${(target.rating.relief_90_percent_m*3.28084).toFixed(0)} ft central 90% depth range in the 250 m analysis neighborhood.`);
    inferred.push(`Terrain grade ${target.habitat_grade} (${target.habitat_score}/100) summarizes physical structure. It is not a species or catch score.`);
  }else if(target.recorded_validation){const v=target.recorded_validation;measured.push(`Recorded geometry depth: ${v.minimum_ft}–${v.maximum_ft} ft.`);}
  if(profile)inferred.push(profile.habitat);
  if(!measured.length)measured.push('Read this layer’s own source and spatial resolution; no measured local relief is attached to this card.');
  unknown.push('Current fish presence, catch rate and individual boulder dimensions are unverified.');
  if(region.coverage.groundtruth?.status!=='ready')unknown.push('A qualifying local camera or sample record has not been attached to this spot.');
  unknown.push('AIS activity is a separate evidence layer. A slow vessel or historical visit does not by itself prove fishing or a catch.');
  return {measured,inferred,unknown};
}
export async function mountSpotEvidence(container,target,species){
  const region=getRegion(),card=document.createElement('details');card.className='spot-evidence';card.innerHTML='<summary>Why this spot · evidence & technique</summary>';container.append(card);
  try{
    if(!cache.has(region.id))cache.set(region.id,fetch(assetURL('ecology'),{signal:AbortSignal.timeout(10000)}).then(r=>{if(!r.ok)throw Error('Evidence unavailable');return r.json();}).catch(e=>{cache.delete(region.id);throw e;}));
    const dossier=await cache.get(region.id);if(dossier.region_id!==region.id||!card.isConnected)return;
    const profile=dossier.profiles[species],e=spotEvidence(target,species,profile,region);
    const body=document.createElement('div');body.innerHTML=['measured','inferred','unknown'].map((key,i)=>`<h3>${['Mapped evidence','Interpretation','What is still unknown'][i]}</h3><ul>${e[key].map(s=>`<li>${esc(s)}</li>`).join('')}</ul>`).join('');
    if(profile){
      body.innerHTML+=`<h3>${esc(profile.name)} · approach</h3><p>${esc(profile.method)}</p><p>${esc(profile.condition_response)}</p><details><summary>Species, season & confidence</summary><p>${esc(profile.life_stage)}</p><p>${esc(profile.timing)}</p><strong>What would strengthen this spot</strong><ul>${profile.evidence_needed.map(s=>`<li>${esc(s)}</li>`).join('')}</ul><p class="small">Regional interpretation reviewed ${esc(dossier.reviewed_at)}. ${esc(dossier.interpretation)}</p></details>`;
      const sources=document.createElement('details');sources.innerHTML='<summary>Agency evidence & geographic limits</summary>';
      for(const p of profile.sources){const text=document.createElement('p');text.textContent=`${p.name} · ${p.region_scope} · ${p.life_stage}. ${p.claims.map(c=>c.claim).join(' ')}`;sources.append(text);
        for(const c of p.claims){const u=new URL(c.source_url);if(u.protocol!=='https:')continue;const a=document.createElement('a');a.href=u.href;a.target='_blank';a.rel='noopener';a.textContent=p.name+' primary source ↗';sources.append(a);}}
      body.append(sources);
    }
    card.append(body);
  }catch{card.append(document.createTextNode('Species evidence could not load. The map’s original source notes remain available; no new confidence has been assigned.'));}
}

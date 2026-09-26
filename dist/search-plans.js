import {getRegion,assetURL} from './region.js?v=8.12';
import {esc,local,num} from './marine-charts.js?v=8.12';
import {nearestSearchForecast,searchWindow,oceanSearchAreas} from './search-plan-data.js?v=8.12';
import {loadPrimaryStrategies,strategyMarkup} from './primary-strategy.js?v=8.12';
export async function initSearchPlans(map,screen,onSelect){
 const region=getRegion();let data,strategies=null,state=null,ocean=null,shown=[],generation=0,timer;
 const layer=L.layerGroup().addTo(map),panel=document.createElement('details');panel.className='search-plan-card';panel.innerHTML='<summary>Where to focus · loading</summary><div></div>';document.querySelector('.map-wrap').append(panel);
 panel.addEventListener('toggle',()=>{if(panel.open)document.getElementById('species-regulations').open=false;});document.getElementById('species-regulations').addEventListener('toggle',e=>{if(e.target.open)panel.open=false;});
 L.DomEvent.disableClickPropagation(panel);L.DomEvent.disableScrollPropagation(panel);
 document.addEventListener('skippercast:forecast',e=>{state=e.detail;if(data)queue();});
 document.addEventListener('skippercast:ocean-cells',e=>{ocean=e.detail;if(data)queue();});
 const url=assetURL('search_plans')||`regions/${region.id}/search-plans.json`;
 try{const r=await fetch(url,{signal:AbortSignal.timeout(20000)});if(!r.ok)throw Error();data=await r.json();if(data.region_id!==region.id||data.method!=='species-search-v1')throw Error();}catch{data=null;panel.innerHTML='<summary>Search areas unavailable</summary><p>Refresh to retry the regional habitat package.</p>';return;}
 void loadPrimaryStrategies(region.id).then(packet=>{strategies=packet;queue();}).catch(()=>{strategies=null;});
 function species(){return document.getElementById('species-select').value;}
 function select(entry){
  const {feature:f,rating,near}=entry,p=f.properties,profile=data.profiles[species()];
  const assessment=Number.isFinite(rating.conditions)?`${num(rating.conditions)}/10 boat conditions · ${rating.confidence.toLowerCase()} confidence`:'Conditions incomplete';
  const html=`<div class="eyebrow">SPECIES SEARCH AREA · ${esc(profile.name)}</div><h2>${esc(p.name)}</h2><p><strong>${esc(assessment)}</strong><br>${esc(local(state?.time||Date.now()/1000,{weekday:'short',hour:'numeric'}))} + four hours · local sample, transit not evaluated</p><p>${esc(profile.search_for)}</p><h3>How to fish it</h3>${strategyMarkup(strategies?.strategies?.[species()],{compact:true})}<h3>Why this outline</h3><p>${p.habitat_kind==='ocean'?`Three adjacent populated ocean-model cells; ${p.temperature_c.map(t=>num(t*9/5+32)).join('–')}°F. The water-transition ordering is a search heuristic, not a fish forecast. Frame ${esc(local(p.frame_time,{month:'short',day:'numeric',hour:'numeric'}))}.`:`The outline follows ${esc(p.habitat_kind)} habitat from the published survey. It does not fill unmapped gaps or extend the reef into surrounding water.`}</p><p>${esc(p.depth_note||'Water-column search: bottom depth and fish depth are unverified.')}</p><h3>Confirm before committing</h3><ul>${profile.required_to_confirm.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p>${esc(profile.caution)}</p><p>${esc(near?`Forecast sample ${near.p.name}, ${near.d.toFixed(1)} nm away; coarse model, not reef-scale shelter.`:'No geographically suitable forecast sample; conditions are withheld.')}</p>${rating.reasons.length?`<p>${esc(rating.reasons.join(' · '))}</p>`:''}<p>Fish and bait presence are unconfirmed. Check the selected species’ Rules card; this habitat outline is not permission to fish.</p><button id="search-area-weather" class="primary">Conditions near this area</button><details><summary>Evidence and method</summary><p>${esc(profile.tactics_basis)}</p>${[...(profile.source_links||[]),...(p.source_url?[{title:'Mapped source',url:p.source_url}]:[])].filter(s=>s.url?.startsWith('https://')).map(s=>`<p><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)} ↗</a></p>`).join('')}<p>Source date: ${esc(p.source_date||'See survey record')}. No charter catch or AIS claim is assigned.</p></details>`;
  onSelect(html,{...p,label:p.name,geometry:f.geometry},'search-area-weather');
 }
 async function render(){
  const run=++generation;layer.clearLayers();const profile=data.profiles[species()];if(!profile)return;
  const time=state?.time||Math.floor(Date.now()/3600000)*3600;
  const validOcean=ocean&&Math.abs(ocean.selectedTime-time)<1?ocean:null;
  let pool=data.features.filter(f=>f.properties.species.includes(species()));
  if(['offshore','pelagic'].includes(profile.kind))pool=pool.concat(oceanSearchAreas(validOcean,profile,region));
  const view=map.getBounds();pool=pool.filter(f=>{const b=f.properties.bounds;return view.intersects([[b[1],b[0]],[b[3],b[2]]]);});
  const cache=new Map();const ranked=pool.map(feature=>{const near=nearestSearchForecast(feature.properties,profile);if(near&&!cache.has(near.i))cache.set(near.i,searchWindow(state?.bundle,near.i,species(),time));const rating=near?cache.get(near.i):{conditions:null,confidence:'Low',reasons:['No nearby marine forecast sample']};return {feature,near,rating};});
  ranked.sort((a,b)=>(b.rating.conditions??-1)-(a.rating.conditions??-1)||Number(b.feature.properties.depth_qualified)-Number(a.feature.properties.depth_qualified)||(b.feature.properties.gradient||0)-(a.feature.properties.gradient||0));
  shown=[];
  if(screen.ready())for(const row of ranked){if(run!==generation)return;if(screen.geometryAllowed(row.feature.geometry))shown.push(row);if(shown.length===3)break;if(shown.length===0)await new Promise(resolve=>setTimeout(resolve,0));}
  if(run!==generation)return;
  const head=panel.querySelector('summary'),body=panel.querySelector('div');head.textContent=`Where to focus · ${shown.length?shown.length+' areas to investigate':'evidence needed'}`;
  body.innerHTML=`<p>${esc(profile.search_for)}</p><small>${esc(local(time,{weekday:'short',hour:'numeric'}))} · four-hour fishing window · fish presence unconfirmed</small>${!screen.ready()?'<p>Current protected-area check unavailable; outlines withheld.</p>':!shown.length?`<p>${profile.kind==='offshore'?'No usable ocean search cells in this view and forecast window. Ocean forecasts have a shorter horizon than the seven-day weather outlook.':esc(profile.caution)} No suitable published footprint is available in this view.</p>`:''}<div class="search-plan-choices">${shown.map((r,i)=>`<button data-search="${i}"><strong>${i+1}. ${esc(r.feature.properties.name)}</strong><span>${Number.isFinite(r.rating.conditions)?num(r.rating.conditions)+'/10 boat conditions':'Habitat only · conditions incomplete'}</span></button>`).join('')}</div><details><summary>Starter rig & fishing sequence</summary>${strategyMarkup(strategies?.strategies?.[species()],{compact:true})}<p>${esc(profile.condition_response)}</p><p>${esc(profile.caution)}</p></details><small>Shortlist ordered by modeled boat conditions, then surveyed evidence. Not a bite or safe-trip rating. Check Rules before fishing.</small>`;
  if(!document.getElementById('layer-areas').checked)return;
  shown.forEach((entry,i)=>{const p=entry.feature.properties,r=entry.rating,color=r.conditions===null?'#6b7185':r.conditions<4?'#b06b25':'#007c78';L.geoJSON(entry.feature,{style:{color,weight:3,fillOpacity:.12,dashArray:r.conditions===null?'6 5':undefined}}).bindTooltip(`${i+1}. ${p.name} · investigate`).on('click',()=>select(entry)).addTo(layer);});
 }
 panel.addEventListener('click',e=>{const b=e.target.closest('[data-search]');if(b){const entry=shown[Number(b.dataset.search)];if(entry)select(entry);}});
 function queue(){clearTimeout(timer);timer=setTimeout(render,120);}
 document.addEventListener('skippercast:species',()=>{ocean=null;queue();});document.getElementById('layer-areas').addEventListener('change',queue);map.on('moveend',queue);setInterval(queue,60000);render();return {refresh:queue};
}

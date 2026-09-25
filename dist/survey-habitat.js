// Evidence geometry stays separate from depth-qualified/exportable fishing targets.
import {assetURL,getRegion} from './region.js?v=8.11';
import {esc} from './marine-charts.js?v=8.11';
import {habitatGroups} from './map-response.js?v=8.11';
import {positions} from './geo-screen.js?v=8.11';

export function habitatMatches(feature, species, region=getRegion()) {
  const p=feature.properties, target=region.target_options?.find(t=>t.id===species);
  if(!target || p.fishing_target===true || p.military_access==='unverified')return false;
  if(Array.isArray(p.species_ids))return p.species_ids.includes(species);
  return target.habitat_kinds.includes(p.habitat_kind);
}
export function habitatDetails(feature, region=getRegion()) {
  const p=feature.properties;
  const unit={rock:'Mapped hard bottom',mixed:'Mapped mixed bottom',sediment:'Mapped soft bottom',kelp:'Historical kelp detections'}[p.habitat_kind] || 'Survey context';
  const native=p.sampled_original_depth_ft;
  const depth=native?`Original measured cells inside this outline: ${Number(native.minimum).toFixed(0)}–${Number(native.maximum).toFixed(0)} ft; most sampled cells (5th–95th percentile) ${Number(native.p05).toFixed(0)}–${Number(native.p95).toFixed(0)} ft. Historical survey; gaps and safe approach are not established`:Array.isArray(p.view_depth_range_ft)?`${p.view_depth_range_ft.map(x=>Number(x).toFixed(0)).join('–')} ft across the image window, not the whole habitat outline`:Array.isArray(p.depth_range_ft)?`${p.depth_range_ft.map(x=>Number(x).toFixed(0)).join('–')} ft in sampled cells`:p.depth_note || 'No complete native-depth range attached';
  const sourceLinks=[{title:'Habitat source',url:p.source_url},...(p.source_links||[])].filter(s=>String(s.url).startsWith('https://'));
  return `<div class="eyebrow">SURVEY HABITAT · ${esc(p.island_name || p.island || region.name)}</div><h2>${esc(p.name)}</h2>
    <div class="area-facts"><strong>${unit}</strong><span>${Number(p.area_km2).toFixed(3)} km² · ${p.habitat_kind==='kelp'?'observed':'compiled'} ${esc(p.source_date)}</span></div>
    <p>${p.habitat_kind==='kelp'?'This outline records canopy or subsurface kelp detected by the source survey. It does not establish live kelp, seabed type or fish today.':p.habitat_kind==='mixed'?'Mixed hard and soft substrate: look for the transition using your sounder. The source does not establish continuous reef or continuous sand.':p.habitat_kind==='rock'?'The source classifies this footprint as hard substrate. Look for relief and edges with your sounder; the classification alone cannot identify shelter-sized crevices or individual boulders.':'The source classifies this as sediment habitat. Look for bait and transitions in bottom type; a soft-bottom outline does not locate a fish.'}</p>
    <p class="evidence-note"><strong>Habitat evidence · fish presence unverified</strong><br>${esc(depth)}. ${p.depth_qualified?'See the source depth screen.':'This is context, not a depth-qualified fishing waypoint.'} No charter AIS or catch rank is assigned.</p>
    <button id="survey-weather" class="primary">Conditions near this area ↗</button>
    <details class="detail-section"><summary>Survey precision & legal screening</summary>
      <p>${esc(p.limitations || 'Classification dates and source methods differ. Some rock edges and sediment can have changed since mapping. A detailed outline is not survey accuracy.')}</p>
      <p>${Array.isArray(p.native_source_codes)?`Original classes: ${p.native_source_codes.map(esc).join(', ')}. `:''}${p.survey_cell_m?`${esc(p.survey_cell_m)} m bathymetry cells. `:''}${esc(p.vertical_datum || 'Vertical reference unavailable')}. ${esc(p.bathymetry_source_date || '')}</p>
      <p>MPAs and groundfish exclusion areas are removed from these outlines. A buffer is a conservative processing margin, not permission to fish alongside a boundary. Date, gear and local access restrictions still apply.</p>
      <p>${sourceLinks.map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)} ↗</a>`).join(' · ')}</p>
    </details>`;
}
export async function initSurveyHabitat(map, screen, onSelect, onFocus=()=>{}) {
  const panel=document.getElementById('regional-explore'),focus=document.getElementById('map-focus');
  const region=getRegion();
  if(region.map.focus_areas?.length) {
    panel.hidden=false;
    for(const f of region.map.focus_areas)focus.add(new Option(f.name,f.id));
    const focusArea=()=>{
      const area=region.map.focus_areas.find(f=>f.id===focus.value),b=area?.bounds || region.fishing_bounds;
      map.fitBounds([[b[1],b[0]],[b[3],b[2]]],{paddingTopLeft:[24,110],paddingBottomRight:[24,115],maxZoom:12});
      const url=new URL(location.href);if(focus.value==='all')url.searchParams.delete('focus');else url.searchParams.set('focus',focus.value);history.replaceState(null,'',url);
      document.getElementById('map-options').close();
      if(area){const sample=region.forecast_points.find(p=>p.id===area.forecast_point);onFocus(sample?{...sample,label:area.name+' marine reference'}:{latitude:(b[1]+b[3])/2,longitude:(b[0]+b[2])/2,label:area.name+' browsing area'});}
    };
    focus.addEventListener('change',focusArea);
    const requested=new URL(location.href).searchParams.get('focus');
    if(region.map.focus_areas.some(f=>f.id===requested)){focus.value=requested;focusArea();}
  }
  if(!assetURL('survey_habitat'))return;
  document.body.classList.add('survey-region');
  const r=await fetch(assetURL('survey_habitat'),{signal:AbortSignal.timeout(20000)});if(!r.ok)throw Error('Survey habitat unavailable');
  const data=await r.json();if(data.region_id!==region.id || data.type!=='FeatureCollection')throw Error('Survey region mismatch');
  const layer=L.layerGroup().addTo(map),toggle=document.getElementById('survey-habitat-toggle');
  const status=document.getElementById('habitat-layer-status');
  const legend=L.control({position:'bottomright'});
  legend.onAdd=()=>{const el=L.DomUtil.create('div','survey-habitat-key');el.textContent='Teal: rock · sand: sediment · green: dated kelp';return el;};legend.addTo(map);
  const entries=data.features.map(f=>({feature:f,bounds:f.properties.bounds?L.latLngBounds([[f.properties.bounds[1],f.properties.bounds[0]],[f.properties.bounds[3],f.properties.bounds[2]]]):L.geoJSON(f.geometry).getBounds()}));
  let screened=[],screenRevision=null,checking=false,checkError=false,request=0,worker,deadline;
  const fail=()=>{checkError=true;checking=false;screened=[];clearTimeout(deadline);worker?.terminate();draw();};
  try{
    worker=new Worker(new URL('./habitat-screen-worker.js?v=8.11',import.meta.url),{type:'module'});
    worker.postMessage({type:'init',geometries:data.features.map(f=>f.geometry)});
    worker.addEventListener('message',({data:result})=>{
      if(checkError || result.request!==request || result.revision!==screen.revision() || !screen.ready())return;
      screened=result.allowed.map(i=>entries[i]);checking=false;clearTimeout(deadline);draw();
    });
    worker.addEventListener('error',fail);
    worker.addEventListener('messageerror',fail);
  }catch{checkError=true;}
  const legal=()=>{
    const revision=screen.revision();if(revision===screenRevision)return;
    screenRevision=revision;screened=[];request++;checking=false;clearTimeout(deadline);
    const snapshot=screen.snapshot();if(!snapshot || checkError)return;
    checking=true;
    try{worker.postMessage({type:'screen',request,revision,closures:snapshot.geometries});deadline=setTimeout(fail,30000);}catch{fail();}
  };
  const draw=()=>{
    layer.clearLayers();
    const species=document.getElementById('species-select').value;
    const eligible=screened.filter(e=>habitatMatches(e.feature,species,region));
    const target=region.target_options.find(t=>t.id===species);
    const gap=target?.empty_map_note || 'No mapped habitat for this target in the imported survey coverage. This does not mean the species is absent.';
    status.textContent=checkError?'Habitat geometry check unavailable · layer withheld':checking?'Checking full habitat outlines against current closures…':screen.ready()?eligible.length?`${eligible.length} matching habitat patches · context; target depth filter does not apply`:gap:'Current closure screen unavailable · habitat layer withheld';
    const key=legend.getContainer();
    key.textContent=checkError?'Habitat geometry check unavailable':checking?'Checking habitat boundaries…':!screen.ready()?'Habitat withheld · closure check unavailable':!toggle.checked?'Habitat preview overlay off · pink: closures':eligible.length?'Habitat preview · teal: rock · sand: sediment · green: dated kelp · pink: closures':target?.kind==='offshore'?'Offshore search references · fish unverified':gap;
    key.setAttribute('role','status');
    if(!toggle.checked || !document.getElementById('layer-areas').checked || checkError || checking || !screen.ready() || screenRevision!==screen.revision())return;
    const zoom=map.getZoom(),minimum=zoom<9?.04:zoom<11?.004:0;
    const shown=eligible.filter(e=>e.bounds.intersects(map.getBounds()) && e.feature.properties.area_km2>=minimum);
    if(eligible.length && !shown.length){
      key.textContent='No matching habitat in this view. ';
      const button=document.createElement('button');button.type='button';button.textContent='Show mapped habitat';
      button.onclick=()=>map.fitBounds(eligible.reduce((b,e)=>b.extend(e.bounds),L.latLngBounds([])),{padding:[60,110],maxZoom:11});key.append(button);
    }
    if(zoom<10){
      if(shown.length)key.textContent='Mapped habitat groups · tap to see outlines';
      for(const group of habitatGroups(shown,p=>map.project(p,zoom))){
        const bounds=group.reduce((b,e)=>b.extend(e.bounds),L.latLngBounds([]));
        // An overview badge counts source polygons; it is not a fishing waypoint.
        let center=bounds.getCenter();
        if(!screen.pointAllowed({latitude:center.lat,longitude:center.lng})){const [lng,lat]=positions(group[0].feature.geometry)[0];center=L.latLng(lat,lng);}
        L.marker(center,{icon:L.divIcon({className:'habitat-cluster',html:`<span>${group.length}</span>`,iconSize:[44,44]}),title:`${group.length} mapped habitat outlines · tap to zoom`})
          .on('click',()=>map.fitBounds(bounds,{padding:[60,110],maxZoom:12})).addTo(layer);
      }
      return;
    }
    for(const {feature:f} of shown){
      const p=f.properties,color={rock:'#157f85',mixed:'#647d8b',sediment:'#ac7b45',kelp:'#487d2a'}[p.habitat_kind]||'#647d8b';
      const shape=L.geoJSON(f,{style:{color,weight:zoom>=12?1.4:1,fillColor:color,fillOpacity:zoom>=11?.12:.07},onEachFeature:(_,s)=>s.on('add',()=>{const el=s.getElement();if(el){el.setAttribute('role','button');el.setAttribute('tabindex','0');el.setAttribute('aria-label',p.name+' · '+p.habitat_kind+' survey habitat');el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();s.fire('click',{},true);}});}})});
      shape.bindTooltip(esc(p.name)+' · '+esc(p.habitat_kind)+' habitat')
        .on('click',()=>onSelect(habitatDetails(f,region),{...p,geometry:f.geometry})).addTo(layer);
    }
    if(eligible.length && minimum)status.textContent+=' · zoom in for finer patches';
  };
  let scheduled=false;
  const schedule=()=>{if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;legal();draw();});};
  toggle.addEventListener('change',schedule);
  document.getElementById('layer-areas').addEventListener('change',schedule);
  document.getElementById('species-select').addEventListener('change',schedule);
  document.addEventListener('skippercast:boundaries',schedule);
  map.on('moveend',schedule);legal();draw();
  return {draw};
}

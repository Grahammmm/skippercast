import {initChart} from './chart-map.js?v=8.13';
import {initNavigation} from './navigation.js?v=8.13';
import {esc} from './marine-charts.js?v=8.13';
import {viewFromURL} from './location-context.js?v=8.13';
import {mappedPackageAt} from './map-response.js?v=8.13';
import {coastAt,coastURL,sourceFresh,initCoastSelector,initCoastalContext,coastalTargetOptions} from './coasts.js?v=8.13';
import {loadCoastalSectors,loadSurveyDiscovery,loadSurveyProducts,sectorsForCoast,sectorAt} from './coastal-sectors.js?v=8.14';
import {updateCoastalForecast} from './coastal-forecast-v2.js?v=8.16';

export async function initCoastalDiscovery(catalog,coast) {
  document.body.classList.add('coastal-discovery');
  initCoastSelector(catalog,coast);
  const view=viewFromURL(location.href),p=view&&coastAt(view,catalog)?.id===coast.id?view:null;
  const map=L.map('map',{minZoom:7,maxZoom:18,zoomControl:false}).setView(p?[p.latitude,p.longitude]:coast.view.slice(0,2),p?.zoom||coast.view[2]);
  L.control.zoom({position:'bottomright'}).addTo(map);
  const caption=document.getElementById('location-caption');
  initChart(map,message=>{caption.textContent=message;});
  const navigation=initNavigation({onMapVisible:()=>map.invalidateSize()});
  const select=document.getElementById('species-select');
  let targetOptions=coast.target_options,selectionTouched=false;
  select.replaceChildren(...targetOptions.map(t=>new Option(t.name,t.id)));
  const desired=new URL(location.href).searchParams.get('target');select.value=coast.targets.includes(desired)?desired:coast.targets[0];select.disabled=false;
  const rules=document.getElementById('species-regulations');
  function targetInfo() {
    const t=targetOptions.find(t=>t.id===select.value);
    rules.innerHTML=`<summary>${esc(t.name)} · check local season</summary><div class="reg-body"><p>${esc(t.note)}</p><p>Potential regional target; surveyed spots and date-specific legal evaluation are not yet available here. Seasons, gear, depth and protected areas can restrict fishing.</p><p><a href="${esc(coast.rules_url)}" target="_blank" rel="noopener">Official ${esc(coast.name)} regulations ↗</a></p>${t.sources.map(url=>`<p><a href="${esc(url)}" target="_blank" rel="noopener">Species habitat source ↗</a></p>`).join('')}<p id="coastal-mpa-status" role="status">Checking MPA boundaries…</p></div>`;
    const url=new URL(location.href);url.searchParams.set('target',select.value);history.replaceState(null,'',url);
    const guide=document.getElementById('coastal-target-guide');guide.innerHTML=`<h2>${esc(t.name)}</h2><p>${esc(t.note)}</p><a href="${esc(coast.rules_url)}" target="_blank" rel="noopener">Check this coast’s rules ↗</a>`;
    drawMPAs();
  }
  const packages=(await fetch('regions/index.json').then(r=>{if(!r.ok)throw Error('Mapped-area directory unavailable');return r.json();})).regions.filter(r=>coast.packages.includes(r.id));
  const sectorPacket=await loadCoastalSectors();
  const sectors=sectorsForCoast(sectorPacket,coast.id).slice().reverse();
  const links=packages.map(r=>`<a class="coastal-package" href="${esc(coastURL(location.href,coast,{packageId:r.id}).pathname+coastURL(location.href,coast,{packageId:r.id}).search+'#map')}">${esc(r.name)} · open detailed map ↗</a>`).join('');
  const panel=document.getElementById('guide-panel');
  panel.innerHTML=`<h1>${esc(coast.name)} coast</h1><p>${esc(coast.limits)}</p><section id="coastal-target-guide"></section><details id="coastal-seasonal" class="guide-topic" open><summary>Regional species & seasonal watch</summary></details><details class="guide-topic"><summary>Explore ${sectors.length} local planning sectors</summary><div class="sector-choices">${sectors.map(s=>`<button type="button" class="sector-choice" data-sector="${esc(s.id)}">${esc(s.name)}<small data-survey-summary="${esc(s.id)}">${s.published_candidate_points?`${s.published_candidate_points} published point candidates in partial packages`:'Survey-qualified points not published'}</small></button>`).join('')}</div><details id="sector-survey-details" class="guide-topic"><summary>Original seabed survey products</summary><div id="sector-survey-list" aria-live="polite">Choose a sector to inspect its source surveys.</div></details><p class="small">${esc(sectorPacket.scope)} <a href="${esc(sectorPacket.survey_discovery[0].url)}" target="_blank" rel="noopener">USGS survey catalog ↗</a></p><p class="small" id="survey-discovery-status">Loading NOAA survey catalog leads…</p></details><h2>Detailed mapping</h2><p>${packages.length?'Open a reviewed local data package:':'Source discovery covers regional species and MPAs. Survey-qualified fishing spots, local weather and exports have not been published for this coast.'}</p>${links}<p class="small">${esc(catalog.scope)}</p>`;
  if(coast.id==='northern'){
    const note=document.createElement('p');note.className='small';
    note.innerHTML='Off Cape Mendocino, an optional <a href="https://doi.org/10.5066/P9U0SUGL" target="_blank" rel="noopener">USGS hard-seabed context layer ↗</a> is available in Map Options. Historical substrate is not a verified fish location or legal-depth clearance.';
    panel.append(note);
  }
  let selectedSector=null,surveyData=null,productData=null;
  const sourceSelector=document.createElement('select');
  sourceSelector.id='survey-sector-select';
  sourceSelector.setAttribute('aria-label','Choose a coastal sector for original survey sources');
  sourceSelector.replaceChildren(new Option('Choose a sector',''),...sectors.map(s=>new Option(s.name,s.id)));
  panel.querySelector('#sector-survey-details').insertBefore(sourceSelector,panel.querySelector('#sector-survey-list'));
  function showSurveySources(){
    const list=panel.querySelector('#sector-survey-list');
    if(!selectedSector){list.textContent='Choose a sector to inspect its source surveys.';return;}
    const row=surveyData?.sectors.find(x=>x.sector_id===selectedSector.id);
    if(!row){list.textContent=`${selectedSector.name}: NOAA survey catalog unavailable. No seabed coverage inferred.`;return;}
    const products=new Map((productData?.surveys||[]).map(item=>[item.id,item]));
    const sorted=[...row.surveys].sort((a,b)=>(b.year||0)-(a.year||0)||a.id.localeCompare(b.id));
    const entry=lead=>{const p=products.get(lead.id),bag=p?.products?.bag?.[0],report=p?.products?.report?.[0];
      return `<li><strong>${esc(lead.id)}</strong> · ${esc(lead.year||'date unknown')} · ${esc(lead.locality||'locality not recorded')}<br><a href="${esc(lead.catalog_url)}" target="_blank" rel="noopener">NOAA catalog ↗</a>${bag?` · <a href="${esc(bag)}" target="_blank" rel="noopener">BAG grid ↗</a>`:''}${report?` · <a href="${esc(report)}" target="_blank" rel="noopener">Survey report ↗</a>`:''}${p?.status==='retained'?' · product links retained from an earlier check':''}</li>`;};
    list.innerHTML=`<p><strong>${esc(selectedSector.name)}</strong> · ${sorted.length} intersecting NOAA survey leads. Catalog footprints and product links are not verified fishing grounds or continuous bottom coverage.</p>${productData?`<p class="small">Product pages checked ${esc(productData.collected_at.slice(0,10))} · ${esc(productData.health.status)}.</p>`:'<p class="small">Original product-link inventory unavailable; use each NOAA catalog.</p>'}<ul class="survey-source-list">${sorted.slice(0,20).map(entry).join('')}</ul>${sorted.length>20?`<details><summary>Show ${sorted.length-20} more surveys</summary><ul class="survey-source-list">${sorted.slice(20).map(entry).join('')}</ul></details>`:''}`;
  }
  sourceSelector.addEventListener('change',()=>{selectedSector=sectors.find(s=>s.id===sourceSelector.value)||null;showSurveySources();});
  panel.addEventListener('click',event=>{const button=event.target.closest('[data-sector]');if(!button)return;const sector=sectors.find(s=>s.id===button.dataset.sector);if(!sector)return;selectedSector=sector;sourceSelector.value=sector.id;panel.querySelector('#sector-survey-details').open=true;showSurveySources();navigation.showView('map');requestAnimationFrame(()=>{map.invalidateSize();map.fitBounds([[sector.bounds[1],sector.bounds[0]],[sector.bounds[3],sector.bounds[2]]],{padding:[20,20],maxZoom:10});});});
  void loadSurveyDiscovery(sectorPacket).then(data=>{
    surveyData=data;showSurveySources();
    const status=panel.querySelector('#survey-discovery-status');
    if(!data){status.textContent='NOAA survey catalog unavailable; no survey coverage is inferred.';return;}
    status.textContent=`NOAA BAG catalog checked ${data.collected_at.slice(0,10)} · ${data.health.status==='ok'?'all sectors queried':'some queries failed; old leads retained'}. Survey leads need grid review.`;
    for(const sector of sectors){const row=data.sectors.find(x=>x.sector_id===sector.id),label=panel.querySelector(`[data-survey-summary="${sector.id}"]`);if(!row||!label)continue;
      const published=sector.published_candidate_points?`${sector.published_candidate_points} published point candidates · `:'';
      label.textContent=`${published}${row.surveys.length} NOAA BAG survey leads${row.status==='ok'?'':' · dated/retained'}`;
    }
  });
  void loadSurveyProducts(sectorPacket).then(data=>{productData=data;showSurveySources();});
  const forecastPanel=document.getElementById('forecast-panel');
  document.getElementById('export-panel').innerHTML=`<h1>Fishing-plan export</h1><p>Only reviewed, surveyed fishing areas can be exported. Choose a detailed mapped area; discovery sectors and survey catalog footprints are not waypoints.</p>${links||'<p>This coast’s detailed fishing package is pending.</p>'}<a href="#map">Back to map</a>`;
  const banner=document.getElementById('best-day-banner');banner.innerHTML='<span>Coastal guide</span><strong>Species & sources</strong>';banner.addEventListener('click',()=>navigation.showView('guide'));
  const options=document.getElementById('map-options');
  // Keep the existing chart selector, then discard controls for layers this browse mode does not own.
  const chartLabel=document.getElementById('base-map').closest('label');
  const body=options.querySelector('.options-body');body.replaceChildren(chartLabel);
  const detail=document.createElement('div');detail.innerHTML=`<p class="small">Clean chart: depths, coastal features and navigation aids. MPAs stay visible. Full NOAA restores all chart symbols.</p><h3>${esc(coast.name)} · ${esc(coast.limits)}</h3>${links||'<p>Detailed fishing maps are pending for this coast.</p>'}`;body.append(detail);
  if(coast.id==='northern'){
    const context=L.layerGroup();map.createPane('historicalSeabed').style.zIndex=425;
    const label=document.createElement('label');label.className='map-layer-option';
    const check=document.createElement('input');check.type='checkbox';
    const title=document.createElement('span');title.textContent='Cape Mendocino · surveyed hard seabed context';
    label.append(check,title);body.append(label);
    const note=document.createElement('p');note.className='small';note.textContent='Historical USGS video-supervised 2 m seafloor character, generalized to 20 m for display. It does not establish legal depth, fish presence or a permitted fishing spot.';body.append(note);
    let loaded=false;
    check.addEventListener('change',async()=>{
      if(!check.checked){map.removeLayer(context);return;}
      if(loaded){context.addTo(map);return;}
      try{
        const response=await fetch('data/cape-mendocino-seafloor-context.geojson',{signal:AbortSignal.timeout(12000)});
        if(!response.ok)throw Error('USGS seabed context unavailable');
        const data=await response.json();
        if(data.type!=='FeatureCollection'||data.scope!=='generalized-seafloor-character-context'||data.source_id!=='cape-mendocino-character-2023'
          ||!Array.isArray(data.features)||data.features.length<1||data.features.some(f=>f.properties?.fishing_target!==false||f.properties?.exportable!==false||f.properties?.depth_qualified!==false)) throw Error('Unreviewed USGS context');
        L.geoJSON(data,{pane:'historicalSeabed',style:{color:'#79552d',weight:1,fillColor:'#b4844b',fillOpacity:.22}})
          .bindPopup(`<strong>Historical hard, rugged seabed</strong><p>USGS class model, generalized 20 m display. Not a fishing target, legal depth screen, catch report or navigation surface.</p><a href="${esc(data.source_url)}" target="_blank" rel="noopener">Original USGS data ↗</a>`).addTo(context);
        context.addTo(map);loaded=true;
      }catch(error){check.checked=false;note.textContent=error.message+' · consult the original USGS release.';}
    });
  }
  document.getElementById('open-map-options').addEventListener('click',()=>options.showModal());document.getElementById('close-map-options').addEventListener('click',()=>options.close());
  const note=document.getElementById('region-note');note.hidden=true;
  const empty=document.getElementById('map-empty');empty.hidden=false;empty.classList.add('coverage-message');
  empty.innerHTML=`<strong>${packages.length?'Choose a mapped fishing area':'Fishing spots not mapped here yet'}</strong><p>${packages.length?'Zoom into a mapped area to load its fishing grounds, or open one below.':'Species guidance and MPAs are available. Selecting a species cannot display fishing spots until regional survey data is added.'}</p>${links}`;
  let boundaries=null,boundaryTime=null,mpaStatus='Checking MPA boundaries…',navigating=false,mpaShapes=[];
  const mpaLayer=L.layerGroup().addTo(map);map.createPane('coastalMPAs').style.zIndex=440;
  function drawMPAs() {
    for(const {shape,bounds} of mpaShapes) {
      if(bounds.intersects(map.getBounds())) {if(!mpaLayer.hasLayer(shape))mpaLayer.addLayer(shape);}
      else if(mpaLayer.hasLayer(shape))mpaLayer.removeLayer(shape);
    }
    const status=document.getElementById('coastal-mpa-status');if(status)status.textContent=mpaStatus;
  }
  let forecastTimer=null,forecastKey='';
  function refreshForecast(point,sector){
    if(location.hash!=='#forecast')return;
    const key=`${point.latitude.toFixed(2)},${point.longitude.toFixed(2)}`;
    if(key===forecastKey)return;
    forecastKey=key;clearTimeout(forecastTimer);
    forecastTimer=setTimeout(()=>void updateCoastalForecast(forecastPanel,point,sector),350);
  }
  function move() {
    const p=map.getCenter(),point={latitude:p.lat,longitude:p.lng},next=coastAt(point,catalog);
    const mapped=mappedPackageAt(point,packages,map.getZoom());
    if(mapped&&!navigating){navigating=true;caption.textContent=`Loading ${mapped.name} fishing grounds…`;location.replace(coastURL(location.href,coast,{packageId:mapped.id,point,zoom:map.getZoom(),target:select.value}));return;}
    if(next && next.id!==coast.id && !navigating) {navigating=true;location.replace(coastURL(location.href,next,{point,zoom:map.getZoom(),target:select.value}));return;}
    const sector=sectorAt(sectorPacket,coast.id,point);
    caption.textContent=next?`${coast.name} · ${sector?.name||coast.limits}${sector?' · discovery sector':''}`:'Outside California coastal browse coverage';
    select.disabled=!next;rules.hidden=!next;
    const url=coastURL(location.href,coast,{point,zoom:map.getZoom(),target:select.value,overview:true});url.hash=location.hash;history.replaceState(null,'',url);
    drawMPAs();
    refreshForecast(point,sector);
  }
  window.addEventListener('hashchange',()=>{if(location.hash==='#forecast'){forecastKey='';const p=map.getCenter();refreshForecast({latitude:p.lat,longitude:p.lng},sectorAt(sectorPacket,coast.id,{latitude:p.lat,longitude:p.lng}));}});
  select.addEventListener('change',()=>{selectionTouched=true;targetInfo();});map.on('moveend',move);targetInfo();move();
  void initCoastalContext(catalog,coast).then(status=>{
    const current=select.value;targetOptions=coastalTargetOptions(coast,status);
    select.replaceChildren(...targetOptions.map(t=>new Option(t.name,t.id)));
    select.value=!selectionTouched&&targetOptions.some(t=>t.id===desired)?desired:current;
    targetInfo();
  });
  // The daily collector checks the statewide feature count; saved geometry preserves its original timestamp.
  for(const url of [catalog.feed_url,'data/coastal-boundaries.json']) {
    try {
      const r=await fetch(url,{cache:'no-cache',signal:AbortSignal.timeout(12000)});if(!r.ok)continue;
      const data=await r.json();if(data.scope!=='california-coast-directory')continue;
      const record=data.sources?.mpas,geo=record?.data?.geojson;
      if(geo?.type!=='FeatureCollection'||geo.exceededTransferLimit||geo.features?.length!==record.data.feature_count||geo.features.length<100||!geo.features.every(f=>['Polygon','MultiPolygon'].includes(f.geometry?.type)&&typeof f.properties?.NAME==='string'))continue;
      boundaries=geo;boundaryTime=record.data_retrieved_at;
      mpaStatus=`MPAs shown · checked ${boundaryTime?.slice(0,10)||'date unavailable'}${sourceFresh(record)?'':' · refresh unavailable; consult CDFW'}`;break;
    }catch{/* Do not retimestamp saved boundaries. */}
  }
  if(!boundaries)mpaStatus='MPA boundaries unavailable · consult CDFW before planning';
  mpaShapes=(boundaries?.features||[]).map(f=>{
    const shape=L.geoJSON(f,{pane:'coastalMPAs',style:{color:'#bd3869',weight:2,fillOpacity:.08}})
      .bindTooltip(esc(f.properties.NAME)).bindPopup(`<strong>${esc(f.properties.FULLNAME||f.properties.NAME)}</strong><p>${esc(mpaStatus)}</p><a href="https://wildlife.ca.gov/Conservation/Marine/MPAs" target="_blank" rel="noopener">Official boundaries & rules ↗</a>`);
    return {shape,bounds:shape.getBounds()};
  });
  drawMPAs();
}

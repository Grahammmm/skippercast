import {initChart} from './chart-map.js?v=8.11';
import {initNavigation} from './navigation.js?v=8.11';
import {esc} from './marine-charts.js?v=8.11';
import {viewFromURL} from './location-context.js?v=8.11';
import {mappedPackageAt} from './map-response.js?v=8.11';
import {coastAt,coastURL,sourceFresh,initCoastSelector,initCoastalContext,coastalTargetOptions} from './coasts.js?v=8.11';
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
    rules.innerHTML=`<summary>${esc(t.name)} · check local season</summary><div class="reg-body"><p>${esc(t.note)}</p><p>Potential regional target; surveyed spots and date-specific legal evaluation are not yet available here. Seasons, gear, depth and protected areas can restrict fishing.</p><p><a href="${esc(coast.rules_url)}" target="_blank" rel="noopener">Official ${esc(coast.name)} regulations ↗</a></p>${select.value==='reef'&&coast.groundfish_table_url?`<p><a href="${esc(coast.groundfish_table_url)}" target="_blank" rel="noopener">Official ${esc(coast.name)} groundfish table (PDF) ↗</a></p>`:''}${t.sources.map(url=>`<p><a href="${esc(url)}" target="_blank" rel="noopener">Species habitat source ↗</a></p>`).join('')}<p id="coastal-mpa-status" role="status">Checking MPA boundaries…</p><p id="coastal-federal-status" role="status">Checking federal groundfish areas…</p></div>`;
    const url=new URL(location.href);url.searchParams.set('target',select.value);history.replaceState(null,'',url);
    const guide=document.getElementById('coastal-target-guide');guide.innerHTML=`<h2>${esc(t.name)}</h2><p>${esc(t.note)}</p><a href="${esc(coast.rules_url)}" target="_blank" rel="noopener">Check this coast’s rules ↗</a>`;
    drawMPAs();
    drawFederal();
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
  if(coast.id==='southern'){
    const islandNote=document.createElement('details');islandNote.className='guide-topic';
    islandNote.innerHTML='<summary>Offshore island seabed review</summary><div id="island-native-review" class="small">Loading original-grid screening…</div>';
    panel.querySelector('#sector-survey-details').after(islandNote);
  }
  let selectedSector=null,surveyData=null,productData=null,nativeDepthData=null,regularDepthData=null,usgsDatumData=null;
  function showIslandReview(){
    const box=panel.querySelector('#island-native-review');if(!box)return;
    const names={'anacapa':'Anacapa','santa-cruz':'Santa Cruz','santa-rosa':'Santa Rosa','san-miguel':'San Miguel',
      'santa-barbara-island':'Santa Barbara Island','catalina':'Santa Catalina','san-clemente':'San Clemente','san-nicolas':'San Nicolas'};
    const variable=nativeDepthData?.offshore_islands||[],regular=regularDepthData?.offshore_islands||[];
    if(!variable.length&&!regular.length){box.textContent='Original island-grid screening unavailable.';return;}
    const byId=rows=>new Map(rows.map(row=>[row.sector_id,row]));const v=byId(variable),r=byId(regular);
    box.innerHTML=`<p>These approximate island envelopes keep original NOAA depth-cell evidence out of mainland sector counts. They are not surveyed extents, target spots, legal clearance or fish forecasts.</p><ul class="survey-source-list">${Object.entries(names).map(([id,name])=>{
      const fine=v.get(id)?.source_files_with_eligible_cells||0,grid=r.get(id)?.source_files_with_eligible_cells||0;
      return `<li>${esc(name)} · ${fine} variable-grid and ${grid} regular-grid file(s) with depth/uncertainty-eligible cells</li>`;
    }).join('')}</ul><p><a href="data/noaa-vr-native-depth-review.json" target="_blank" rel="noopener">Variable-grid source receipts ↗</a> · <a href="data/noaa-regular-native-depth-review.json" target="_blank" rel="noopener">Regular-grid source receipts ↗</a></p>`;
  }
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
    const native=nativeDepthData?.sectors.find(item=>item.sector_id===selectedSector.id);
    const regular=regularDepthData?.sectors.find(item=>item.sector_id===selectedSector.id);
    const usgs=usgsDatumData?.sectors.find(item=>item.sector_id===selectedSector.id);
    const usgsSources=(usgs?.intersecting_source_indices||[]).map(i=>usgsDatumData.sources[i]).filter(Boolean);
    const usgsSummary=usgs?`<p class="small">USGS original bathymetry: ${usgs.source_grid_bbox_count} raster bounding box(es) intersect this planning sector. None is qualified as MLLW fishing depth; these single-band grids lack per-cell product uncertainty. An intersecting box can include unmapped water.</p>${usgsSources.length?`<details><summary>Original USGS bathymetry sources and vertical datums</summary><ul class="survey-source-list">${usgsSources.map(item=>`<li>${esc(item.title)} · ${esc(item.native_resolution_m.join(' × '))} m · ${esc(item.structured_vertical_datum_code||'output datum not structurally verified')}${item.vertical_datum_evidence==='unverified-text-mentions'?' · datum only mentioned in source text':''}<br><a href="${esc(item.metadata_url)}" target="_blank" rel="noopener">Original XML ↗</a> · <a href="${esc(item.archive_url)}" target="_blank" rel="noopener">Original grid ↗</a></li>`).join('')}</ul></details>`:''}`:'';
    const nativeSummary=nativeDepthData&&!native?'<p class="small">Original variable-grid screen has no record for this sector.</p>'
      :native?.source_files_with_eligible_cells?`<p class="small">Original fine-grid review: ${native.source_files_with_eligible_cells} NOAA file(s) contain depth- and uncertainty-eligible cells in this browse sector. This does not verify rock, legal access, fish presence or continuous coverage; surveys may overlap. <a href="data/noaa-vr-native-depth-review.json" target="_blank" rel="noopener">Method and source hashes ↗</a></p>`
      :native?'<p class="small">No depth- and uncertainty-eligible cells were found in the audited fine-resolution variable grids here. Other surveys and data types remain unreviewed.</p>':'';
    const regularSummary=regular?.source_files_with_eligible_cells?`<p class="small">Original regular-grid review: ${regular.source_files_with_eligible_cells} NOAA file(s) contain depth- and uncertainty-eligible native cells here. Cell centers were checked against this sector; this does not verify rock, legal access, fish presence or continuous coverage. Surveys may overlap. <a href="data/noaa-regular-native-depth-review.json" target="_blank" rel="noopener">Method and source hashes ↗</a></p>`
      :regular?'<p class="small">No depth- and uncertainty-eligible cells were found in the audited fine-resolution regular BAG files here. Other surveys and data types remain unreviewed.</p>':'';
    const sorted=[...row.surveys].sort((a,b)=>(b.year||0)-(a.year||0)||a.id.localeCompare(b.id));
    const entry=lead=>{const p=products.get(lead.id),bag=p?.products?.bag?.[0],report=p?.products?.report?.[0];
      return `<li><strong>${esc(lead.id)}</strong> · ${esc(lead.year||'date unknown')} · ${esc(lead.locality||'locality not recorded')}<br><a href="${esc(lead.catalog_url)}" target="_blank" rel="noopener">NOAA catalog ↗</a>${bag?` · <a href="${esc(bag)}" target="_blank" rel="noopener">BAG grid ↗</a>`:''}${report?` · <a href="${esc(report)}" target="_blank" rel="noopener">Survey report ↗</a>`:''}${p?.status==='retained'?' · product links retained from an earlier check':''}</li>`;};
    list.innerHTML=`<p><strong>${esc(selectedSector.name)}</strong> · ${sorted.length} intersecting NOAA survey leads. Catalog footprints and product links are not verified fishing grounds or continuous bottom coverage.</p>${regularSummary}${nativeSummary}${usgsSummary}${productData?`<p class="small">Product pages checked ${esc(productData.collected_at.slice(0,10))} · ${esc(productData.health.status)}.</p>`:'<p class="small">Original product-link inventory unavailable; use each NOAA catalog.</p>'}<ul class="survey-source-list">${sorted.slice(0,20).map(entry).join('')}</ul>${sorted.length>20?`<details><summary>Show ${sorted.length-20} more surveys</summary><ul class="survey-source-list">${sorted.slice(20).map(entry).join('')}</ul></details>`:''}`;
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
  void fetch('data/noaa-vr-native-depth-review.json',{signal:AbortSignal.timeout(10000)}).then(async response=>{
    if(!response.ok)throw Error('Native-grid review unavailable');
    const data=await response.json();
    if(data.scope!=='california-original-vr-native-depth-review'||data.status!=='ok'||data.survey_file_count!==data.files?.length
      ||data.sectors?.length!==sectorPacket.sectors.length||data.files.some(file=>file.status!=='ok'))throw Error('Incomplete native-grid review');
    nativeDepthData=data;showSurveySources();showIslandReview();
  }).catch(()=>{/* Keep original survey catalog usable if the optional native review is unavailable. */});
  void fetch('data/noaa-regular-native-depth-review.json',{signal:AbortSignal.timeout(10000)}).then(async response=>{
    if(!response.ok)throw Error('Regular native-grid review unavailable');
    const data=await response.json();
    if(data.scope!=='california-original-regular-native-depth-review'||data.status!=='ok'||data.survey_file_count!==data.files?.length
      ||data.sectors?.length!==sectorPacket.sectors.length||data.files.some(file=>file.status!=='ok'))throw Error('Incomplete regular native-grid review');
    regularDepthData=data;showSurveySources();showIslandReview();
  }).catch(()=>{/* Keep original survey catalog usable if the optional native review is unavailable. */});
  void fetch('data/usgs-depth-datum-ledger.json',{signal:AbortSignal.timeout(10000)}).then(async response=>{
    if(!response.ok)throw Error('USGS datum ledger unavailable');
    const data=await response.json();
    if(data.scope!=='california-usgs-original-bathymetry-datum-ledger'||data.sectors?.length!==sectorPacket.sectors.length
      ||data.source_grid_count!==data.sources?.length||data.sources.some(source=>source.depth_qualified_for_fishing!==false))throw Error('Invalid USGS datum ledger');
    usgsDatumData=data;showSurveySources();
  }).catch(()=>{/* NOAA original source links remain available if this optional ledger fails. */});
  const forecastPanel=document.getElementById('forecast-panel');
  document.getElementById('export-panel').innerHTML=`<h1>Fishing-plan export</h1><p>Only reviewed, surveyed fishing areas can be exported. Choose a detailed mapped area; discovery sectors and survey catalog footprints are not waypoints.</p>${links||'<p>This coast’s detailed fishing package is pending.</p>'}<a href="#map">Back to map</a>`;
  const banner=document.getElementById('best-day-banner');banner.innerHTML='<span>Coastal guide</span><strong>Species & sources</strong>';banner.addEventListener('click',()=>navigation.showView('guide'));
  const options=document.getElementById('map-options');
  // Keep the existing chart selector, then discard controls for layers this browse mode does not own.
  const chartLabel=document.getElementById('base-map').closest('label');
  const body=options.querySelector('.options-body');body.replaceChildren(chartLabel);
  const detail=document.createElement('div');detail.innerHTML=`<p class="small">Clean chart: depths, coastal features and navigation aids. MPAs stay visible. Full NOAA restores all chart symbols.</p><h3>${esc(coast.name)} · ${esc(coast.limits)}</h3>${links||'<p>Detailed fishing maps are pending for this coast.</p>'}`;body.append(detail);
  const statewideContext=L.layerGroup();let statewideShapes=[],statewideLoaded=false;
  map.createPane('statewideHistoricalSeabed').style.zIndex=424;
  const statewideLabel=document.createElement('label');statewideLabel.className='map-layer-option';
  const statewideCheck=document.createElement('input');statewideCheck.type='checkbox';
  const statewideTitle=document.createElement('span');statewideTitle.textContent='USGS hard seabed · historical context';
  statewideLabel.append(statewideCheck,statewideTitle);body.append(statewideLabel);
  const statewideNote=document.createElement('p');statewideNote.className='small';
  statewideNote.textContent='Optional surveyed seabed where original USGS class grids exist. Some coasts have no mapped patches. These are not fishing spots, legal depth checks or navigation guidance.';
  body.append(statewideNote);
  function drawStatewideContext(){
    if(!statewideCheck.checked||!statewideLoaded)return;
    for(const {shape,bounds} of statewideShapes){
      if(bounds.intersects(map.getBounds())){if(!statewideContext.hasLayer(shape))statewideContext.addLayer(shape);}
      else if(statewideContext.hasLayer(shape))statewideContext.removeLayer(shape);
    }
  }
  map.on('moveend',drawStatewideContext);
  statewideCheck.addEventListener('change',async()=>{
    if(!statewideCheck.checked){map.removeLayer(statewideContext);return;}
    if(statewideLoaded){statewideContext.addTo(map);drawStatewideContext();return;}
    statewideNote.textContent='Loading original-grid context…';
    try{
      const response=await fetch(`data/usgs-hard-context-${encodeURIComponent(coast.id)}.geojson`,{signal:AbortSignal.timeout(20000)});
      if(!response.ok)throw Error('USGS hard-seabed context unavailable');
      const data=await response.json();
      if(data.type!=='FeatureCollection'||data.scope!=='generalized-statewide-usgs-hard-bottom-context'||data.coast_id!==coast.id||!Array.isArray(data.features)
        ||data.features.some(f=>f.properties?.fishing_target!==false||f.properties?.exportable!==false||f.properties?.depth_qualified!==false||!f.properties?.metadata_url))throw Error('Unreviewed USGS context');
      statewideShapes=data.features.map(f=>{
        const p=f.properties;
        const shape=L.geoJSON(f,{pane:'statewideHistoricalSeabed',style:{color:'#8b612e',weight:1,fillColor:'#d7a35e',fillOpacity:.24}})
          .bindPopup(`<strong>Historical hard, rugged seabed</strong><p>${esc(p.block_id)} · USGS ${esc(p.source_year)} · generalized 20 m view. No fishing target, legal-depth clearance, catch report or navigation accuracy.</p><a href="${esc(p.metadata_url)}" target="_blank" rel="noopener">Original USGS metadata ↗</a>`);
        return {shape,bounds:shape.getBounds()};
      });
      statewideLoaded=true;statewideContext.addTo(map);drawStatewideContext();
      const sources=new Set(data.features.map(f=>f.properties.block_id||f.properties.release_id));
      statewideNote.textContent=data.features.length?`${data.features.length} historical outlines from ${sources.size} USGS source areas on this coast. Smaller patches and unmapped stretches are absent; MPAs remain visible. No fishing spot or legal depth is implied.`:'No reviewed USGS hard-bottom outlines are available on this coast yet. NOAA survey grids still require native substrate and depth review.';
    }catch(error){statewideCheck.checked=false;statewideNote.textContent=error.message+' · consult the original USGS catalog.';}
  });
  if(['san-francisco','central','southern'].includes(coast.id)){
    const pointConception=coast.id==='central';
    const gaviota=coast.id==='southern';
    const nativePane=pointConception?'pointConceptionNativeHard':gaviota?'gaviotaNativeHard':'sfNativeHard';
    const nativeFile=pointConception?'point-conception-native-hard-context.geojson':gaviota?'gaviota-native-hard-context.geojson':'sf-native-hard-context.geojson';
    const nativeLayer=L.layerGroup();map.createPane(nativePane).style.zIndex=426;
    const nativeLabel=document.createElement('label');nativeLabel.className='map-layer-option';
    const nativeCheck=document.createElement('input');nativeCheck.type='checkbox';
    const nativeTitle=document.createElement('span');nativeTitle.textContent=pointConception?'Point Conception · surveyed hard bottom':gaviota?'Cojo–Gaviota · surveyed hard bottom':'Bodega–Bolinas · surveyed hard bottom';
    nativeLabel.append(nativeCheck,nativeTitle);body.append(nativeLabel);
    const nativeNote=document.createElement('p');nativeNote.className='small';
    nativeNote.textContent='Optional historical NOAA 1–2 m depth and USGS hard-seabed intersection. Research context only; not a fishing target, current legal clearance or navigation chart.'+(pointConception?' Check Point Conception military danger-zone notices before travel.':'');
    body.append(nativeNote);
    let nativeLoaded=false,nativeShapes=[];
    function drawNative(){if(!nativeCheck.checked||!nativeLoaded)return;
      for(const {shape,bounds} of nativeShapes){
        if(bounds.intersects(map.getBounds())){if(!nativeLayer.hasLayer(shape))nativeLayer.addLayer(shape);}
        else if(nativeLayer.hasLayer(shape))nativeLayer.removeLayer(shape);
      }
    }
    map.on('moveend',drawNative);
    nativeCheck.addEventListener('change',async()=>{
      if(!nativeCheck.checked){map.removeLayer(nativeLayer);return;}
      if(nativeLoaded){nativeLayer.addTo(map);drawNative();return;}
      nativeNote.textContent='Loading original-cell research layer…';
      try{
        const response=await fetch(`data/${nativeFile}`,{signal:AbortSignal.timeout(20000)});
        if(!response.ok)throw Error('Original-cell research layer unavailable');
        const data=await response.json();
        if(data.type!=='FeatureCollection'||data.scope!==`${coast.id}-native-noaa-usgs-hard-bottom-context`
          ||data.coast_id!==coast.id||!Array.isArray(data.features)
          ||data.features.some(f=>f.properties?.fishing_target!==false||f.properties?.exportable!==false
            ||f.properties?.legal_clearance!==false||f.properties?.fish_confirmed!==false
            ||f.properties?.depth_qualified_for_target!==false))throw Error('Unreviewed original-cell layer');
        nativeShapes=data.features.map(f=>{
          const p=f.properties;
          const shape=L.geoJSON(f,{pane:nativePane,style:{color:'#396a75',weight:1.4,fillColor:'#70aab4',fillOpacity:.22}})
            .bindPopup(`<strong>Historical surveyed hard bottom</strong><p>NOAA ${esc(p.survey_id)} · ${esc(p.survey_dates[0].slice(0,4))} survey · source depth ${esc(p.depth_ft_range.join('–'))} ft MLLW · USGS hard-seabed class. This is not a fish location, legal clearance or navigation chart.</p><p>MPA/GEA screen compiled ${esc(data.mpa_screened_at.slice(0,10))}; recheck current rules and charts.${pointConception?' Check <a href="https://www.vandenberg.spaceforce.mil/About-Us/Environmental/Vandenberg-SFB-Maritime-Updates/" target="_blank" rel="noopener">Vandenberg maritime status ↗</a> before travel.':''}</p><a href="${esc(p.noaa_bag_url)}" target="_blank" rel="noopener">Original NOAA depth grid ↗</a> · <a href="${esc(p.usgs_metadata_urls[0])}" target="_blank" rel="noopener">USGS class metadata ↗</a>`);
          return {shape,bounds:shape.getBounds()};
        });
        nativeLoaded=true;nativeLayer.addTo(map);drawNative();
        nativeNote.textContent=`${data.features.length} reviewed historical hard-bottom outlines. Current fishing permission, YRCA rules, depth changes and catch presence still need review.${pointConception?' Vandenberg danger-zone status must be checked before travel.':''} No points enter plans or exports.`;
      }catch(error){nativeCheck.checked=false;nativeNote.textContent=error.message+' · use original NOAA and USGS sources.';}
    });
  }
  if(coast.id==='central'){
    const sedimentLayer=L.layerGroup();map.createPane('centralSedimentContext').style.zIndex=422;
    const sedimentLabel=document.createElement('label');sedimentLabel.className='map-layer-option';
    const sedimentCheck=document.createElement('input');sedimentCheck.type='checkbox';
    const sedimentTitle=document.createElement('span');sedimentTitle.textContent='USGS thin-sediment interpretation · central coast';
    sedimentLabel.append(sedimentCheck,sedimentTitle);body.append(sedimentLabel);
    const sedimentNote=document.createElement('p');sedimentNote.className='small';
    sedimentNote.textContent='Optional 50 m interpretation of 0–2.5 m sediment above an ancient surface. Broad geology context only; it does not identify rock piles, fish or legal depth.';
    body.append(sedimentNote);
    let sedimentLoaded=false,sedimentShapes=[];
    function drawSediment(){if(!sedimentCheck.checked||!sedimentLoaded)return;
      for(const {shape,bounds} of sedimentShapes){
        if(bounds.intersects(map.getBounds())){if(!sedimentLayer.hasLayer(shape))sedimentLayer.addLayer(shape);}
        else if(sedimentLayer.hasLayer(shape))sedimentLayer.removeLayer(shape);
      }
    }
    map.on('moveend',drawSediment);
    sedimentCheck.addEventListener('change',async()=>{
      if(!sedimentCheck.checked){map.removeLayer(sedimentLayer);return;}
      if(sedimentLoaded){sedimentLayer.addTo(map);drawSediment();return;}
      sedimentNote.textContent='Loading original USGS sediment interpretation…';
      try{
        const response=await fetch('data/usgs-central-thin-sediment-context.geojson',{signal:AbortSignal.timeout(20000)});
        if(!response.ok)throw Error('USGS sediment context unavailable');
        const data=await response.json();
        if(data.type!=='FeatureCollection'||data.scope!=='usgs-central-interpreted-sediment-context'
          ||data.source?.id!=='usgs-point-sur-arguello-sediment-thickness-2019'||!Array.isArray(data.features)
          ||data.features.some(f=>f.properties?.kind!=='estimated-thin-sediment'||f.properties?.fishing_target!==false
            ||f.properties?.exportable!==false||f.properties?.depth_qualified!==false||f.properties?.fish_confirmed!==false))throw Error('Unreviewed USGS sediment context');
        sedimentShapes=data.features.map(f=>{
          const p=f.properties;
          const shape=L.geoJSON(f,{pane:'centralSedimentContext',style:{color:'#627887',weight:1,fillColor:'#9fb8c5',fillOpacity:.22}})
            .bindPopup(`<strong>Interpreted thin sediment</strong><p>USGS ${esc(data.source.publication_year)} · estimated 0–2.5 m sediment above an ancient surface, 50 m source grid. This does not establish exposed rock, a fishing spot, legal depth or safe navigation.</p><p>${esc(p.sector_ids.join(', '))}</p><a href="${esc(data.source.publication_url)}" target="_blank" rel="noopener">Original USGS study ↗</a>`);
          return {shape,bounds:shape.getBounds()};
        });
        sedimentLoaded=true;sedimentLayer.addTo(map);drawSediment();
        sedimentNote.textContent=`${data.features.length} broad historical sediment areas. Negative source pixels were excluded; current MPAs and local rules still control fishing.`;
      }catch(error){sedimentCheck.checked=false;sedimentNote.textContent=error.message+' · consult the original USGS study.';}
    });
  }
  const predictedContext=L.layerGroup();map.createPane('predictedSeabed').style.zIndex=423;
  const predictedLabel=document.createElement('label');predictedLabel.className='map-layer-option';
  const predictedCheck=document.createElement('input');predictedCheck.type='checkbox';
  const predictedTitle=document.createElement('span');predictedTitle.textContent='CDFW predicted hard seabed · statewide context';
  predictedLabel.append(predictedCheck,predictedTitle);body.append(predictedLabel);
  const predictedNote=document.createElement('p');predictedNote.className='small';
  predictedNote.textContent='Coarse 40 m view of CDFW’s rugosity-based hard-bottom prediction. It may include interpolated pixels. No precise rock edge, fishing spot or legal depth is implied.';
  body.append(predictedNote);
  let predictedLoaded=false,predictedShapes=[];
  function drawPredictedContext(){
    if(!predictedCheck.checked||!predictedLoaded)return;
    for(const {shape,bounds} of predictedShapes){
      if(bounds.intersects(map.getBounds())){if(!predictedContext.hasLayer(shape))predictedContext.addLayer(shape);}
      else if(predictedContext.hasLayer(shape))predictedContext.removeLayer(shape);
    }
  }
  map.on('moveend',drawPredictedContext);
  predictedCheck.addEventListener('change',async()=>{
    if(!predictedCheck.checked){map.removeLayer(predictedContext);return;}
    if(predictedLoaded){predictedContext.addTo(map);drawPredictedContext();return;}
    predictedNote.textContent='Loading CDFW predicted substrate…';
    try{
      const response=await fetch(`data/cdfw-predicted-hard-${encodeURIComponent(coast.id)}.geojson`,{signal:AbortSignal.timeout(20000)});
      if(!response.ok)throw Error('CDFW predicted substrate unavailable');
      const data=await response.json();
      if(data.type!=='FeatureCollection'||data.scope!=='cdfw-predicted-hard-substrate-context'||data.coast_id!==coast.id||!Array.isArray(data.features)
        ||data.features.some(f=>f.properties?.fishing_target!==false||f.properties?.exportable!==false||f.properties?.depth_qualified!==false||!f.properties?.metadata_url))throw Error('Unreviewed predicted substrate');
      predictedShapes=data.features.map(f=>{
        const p=f.properties;
        const shape=L.geoJSON(f,{pane:'predictedSeabed',style:{color:'#785a79',weight:1,fillColor:'#b58eb6',fillOpacity:.23}})
          .bindPopup(`<strong>CDFW predicted hard substrate</strong><p>Rugosity proxy, generalized to 40 m; shallow gaps may be interpolated. No verified rock edge, fish location, legal depth or navigation accuracy.</p><p>California Coastal and Seafloor Mapping Project, California Department of Fish and Wildlife · CC BY 4.0</p><a href="${esc(p.metadata_url)}" target="_blank" rel="noopener">Original CDFW metadata ↗</a>`);
        return {shape,bounds:shape.getBounds()};
      });
      predictedLoaded=true;predictedContext.addTo(map);drawPredictedContext();
      predictedNote.textContent=`${data.features.length} broad predicted-hard patches on this coast. MPAs remain visible. Use surveyed bottom and current rules before choosing a fishing position.`;
    }catch(error){predictedCheck.checked=false;predictedNote.textContent=error.message+' · consult the original CDFW dataset.';}
  });
  const federalLayer=L.layerGroup().addTo(map);map.createPane('federalGroundfish').style.zIndex=438;
  let federalShapes=[],federalStatus='Checking NOAA federal groundfish areas…',federalLoaded=false,federalTouched=false;
  const federalLabel=document.createElement('label');federalLabel.className='map-layer-option';
  const federalCheck=document.createElement('input');federalCheck.type='checkbox';federalCheck.checked=select.value==='reef';
  const federalTitle=document.createElement('span');federalTitle.textContent='Groundfish exclusion areas (GEAs)';
  federalLabel.append(federalCheck,federalTitle);body.append(federalLabel);
  const otherFederalLabel=document.createElement('label');otherFederalLabel.className='map-layer-option';
  const otherFederalCheck=document.createElement('input');otherFederalCheck.type='checkbox';
  const otherFederalTitle=document.createElement('span');otherFederalTitle.textContent='Other NOAA groundfish areas (CCA/YRCA)';
  otherFederalLabel.append(otherFederalCheck,otherFederalTitle);body.append(otherFederalLabel);
  const federalNote=document.createElement('p');federalNote.className='small';
  federalNote.textContent='GEAs prohibit recreational groundfish fishing. CCAs remain for groundfish trawl fisheries and do not restrict recreational groundfish under Amendment 32. YRCA rules depend on method. NOAA GIS is approximate; check 50 CFR.';body.append(federalNote);
  federalCheck.addEventListener('change',()=>{federalTouched=true;drawFederal();});
  otherFederalCheck.addEventListener('change',drawFederal);
  function drawFederal(){
    if(!federalTouched)federalCheck.checked=select.value==='reef';
    for(const {shape,bounds,areaType} of federalShapes){
      const visible=federalLoaded&&(areaType==='GEA'?federalCheck.checked:otherFederalCheck.checked);
      if(visible&&bounds.intersects(map.getBounds())){if(!federalLayer.hasLayer(shape))federalLayer.addLayer(shape);}
      else if(federalLayer.hasLayer(shape))federalLayer.removeLayer(shape);
    }
    const status=document.getElementById('coastal-federal-status');if(status)status.textContent=federalStatus;
  }
  map.on('moveend',drawFederal);
  void (async()=>{
    for(const url of ['https://raw.githubusercontent.com/Grahammmm/skippercast/data/noaa-federal-areas.json','data/noaa-federal-areas.json']){
      try{
        const response=await fetch(url,{cache:'no-cache',signal:AbortSignal.timeout(9000)});if(!response.ok)continue;
        const data=await response.json();
        if(data.scope!=='noaa-west-coast-groundfish-conservation-areas'||data.type!=='FeatureCollection'
          ||data.feature_count!==data.features?.length||data.features.length<25
          ||!data.features.some(f=>f.properties?.source_layer==='GEA_Cordell_Bank_20260623')
          ||data.features.some(f=>!['GEA','CCA','YRCA'].includes(f.properties?.area_type)
            ||!['Polygon','MultiPolygon'].includes(f.geometry?.type)||f.properties?.exportable_as_fishing_spot!==false
            ||!/^https:\/\/www\.ecfr\.gov\/current\/title-50\//.test(f.properties?.cfr_boundary_url||'')))continue;
        const age=Date.now()-Date.parse(data.retrieved_at);
        federalStatus=`NOAA GEA boundaries loaded · retrieved ${data.retrieved_at.slice(0,10)}${data.status==='ok'&&Number.isFinite(age)&&age>=0&&age<=36*3600000?'':' · refresh unverified; check NOAA and 50 CFR'}`;
        federalShapes=data.features.map(f=>{
          const p=f.properties;
          const rule=p.area_type==='GEA'?'Recreational groundfish fishing is prohibited here. Continuous recreational transit requires no deployed gear.'
            :p.area_type==='CCA'?'The former recreational CCA restriction was removed by Amendment 32; this CCA remains for groundfish trawl fisheries.'
            :'YRCA applicability depends on fishery and gear; check the current regulation before fishing.';
          const style=p.area_type==='GEA'?{color:'#945526',weight:2,dashArray:'5 4',fillColor:'#b57635',fillOpacity:.1}
            :{color:'#687b85',weight:1,dashArray:'2 5',fillColor:'#aab8bd',fillOpacity:.04};
          const shape=L.geoJSON(f,{pane:'federalGroundfish',style})
            .bindTooltip(esc(p.name)).bindPopup(`<strong>${esc(p.name)}</strong><p>${esc(p.area_type)} · ${esc(rule)} NOAA GIS is approximate; fishing rules depend on date and exact location.</p><p>${esc(federalStatus)}</p><a href="${esc(p.cfr_boundary_url)}" target="_blank" rel="noopener">Official 50 CFR boundary ↗</a>${p.area_type==='CCA'?'<p><a href="https://wildlife.ca.gov/Conservation/Marine/Cowcod" target="_blank" rel="noopener">CDFW Amendment 32 explanation ↗</a></p>':''}`);
          return {shape,bounds:shape.getBounds(),areaType:p.area_type};
        });
        federalLoaded=true;drawFederal();return;
      }catch{/* Try dated bundled snapshot without changing its retrieval time. */}
    }
    federalStatus='NOAA federal area geometry unavailable · check NOAA and 50 CFR before groundfish planning';drawFederal();
  })();
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
    drawFederal();
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

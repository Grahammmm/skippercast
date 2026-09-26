import {initChart} from './chart-map.js?v=8.12';
import {initNavigation} from './navigation.js?v=8.12';
import {esc} from './marine-charts.js?v=8.12';
import {viewFromURL} from './location-context.js?v=8.12';
import {mappedPackageAt} from './map-response.js?v=8.12';
import {coastAt,coastURL,sourceFresh,initCoastSelector,initCoastalContext,coastalTargetOptions,localTargetAdvisory} from './coasts.js?v=8.34';
import {loadCoastalSectors,loadSurveyDiscovery,loadSurveyProducts,sectorsForCoast,sectorAt} from './coastal-sectors.js?v=8.14';
import {updateCoastalForecast} from './coastal-forecast-v2.js?v=8.16';
import {matchMontereyToStatewide,montereyResearchPopup} from './coastal-research-context.js?v=2';

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
  function updateLocalTargetAdvisory() {
    const advisory=localTargetAdvisory(coast,select.value,map.getCenter().lat);
    for(const id of ['coastal-local-rule','coastal-local-guide']){
      const line=document.getElementById(id);if(!line)continue;
      line.hidden=!advisory;
      if(advisory)line.innerHTML=`${esc(advisory.text)} <a href="${esc(advisory.url)}" target="_blank" rel="noopener">CDFW source ↗</a>`;
      else line.replaceChildren();
    }
  }
  function targetInfo() {
    const t=targetOptions.find(t=>t.id===select.value);
    rules.innerHTML=`<summary>${esc(t.name)} · check local season</summary><div class="reg-body"><p>${esc(t.note)}</p><p id="coastal-local-rule" class="small" role="status" hidden></p><p>Potential regional target; surveyed spots and date-specific legal evaluation are not yet available here. Seasons, gear, depth and protected areas can restrict fishing.</p><p><a href="${esc(coast.rules_url)}" target="_blank" rel="noopener">Official ${esc(coast.name)} regulations ↗</a></p>${select.value==='reef'&&coast.groundfish_table_url?`<p><a href="${esc(coast.groundfish_table_url)}" target="_blank" rel="noopener">Official ${esc(coast.name)} groundfish table (PDF) ↗</a></p>`:''}${t.sources.map(url=>`<p><a href="${esc(url)}" target="_blank" rel="noopener">Species habitat source ↗</a></p>`).join('')}<p id="coastal-mpa-status" role="status">Checking MPA boundaries…</p><p id="coastal-federal-status" role="status">Checking federal groundfish areas…</p></div>`;
    const url=new URL(location.href);url.searchParams.set('target',select.value);history.replaceState(null,'',url);
    const guide=document.getElementById('coastal-target-guide');guide.innerHTML=`<h2>${esc(t.name)}</h2><p>${esc(t.note)}</p><p id="coastal-local-guide" class="small" role="status" hidden></p><a href="${esc(coast.rules_url)}" target="_blank" rel="noopener">Check this coast’s rules ↗</a>`;
    updateLocalTargetAdvisory();
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
    const note=document.createElement('details');note.className='guide-topic';
    note.innerHTML='<summary>Cape Mendocino original-seabed review</summary><p class="small">The optional USGS hard-seabed map layer shows generalized historical context. A separate review matched original NOAA H11975 fine-resolution depth and uncertainty cells to original USGS hard/rugose cells and excluded current MPA/GEA snapshots and 11 historical submerged-rock hazards. Its 12.4 million retained mixed-resolution cells are a <strong>source-review count, not fishing spots or square meters</strong>. H11973 and H11974 had no actual high-resolution grid footprints over that USGS source, even where an overview box suggested overlap. Current charts, safe approach, date-specific rules and fish presence still need review.</p><p class="small"><a href="data/noaa-cape-mendocino-vr-source-coverage.json" target="_blank" rel="noopener">Original-grid coverage receipt ↗</a> · <a href="data/noaa-h11975-cape-mendocino-hard-depth-screen.json" target="_blank" rel="noopener">Depth/substrate screen ↗</a> · <a href="https://www.ngdc.noaa.gov/nos/H10001-H12000/H11975.html" target="_blank" rel="noopener">NOAA survey ↗</a> · <a href="https://doi.org/10.5066/P9U0SUGL" target="_blank" rel="noopener">USGS source ↗</a></p>';
    panel.append(note);
  }
  if(coast.id==='southern'){
    const islandNote=document.createElement('details');islandNote.className='guide-topic';
    islandNote.innerHTML='<summary>Offshore island seabed review</summary><div id="island-native-review" class="small">Loading original-grid screening…</div>';
    panel.querySelector('#sector-survey-details').after(islandNote);
  }
  let selectedSector=null,surveyData=null,productData=null,nativeDepthData=null,regularDepthData=null,usgsDatumData=null,videoAuditData=null,reefcheckData=null,crfsData=null,readinessData=null,nosOverlapData=null;
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
    const readiness=readinessData?.sectors.find(item=>item.sector_id===selectedSector.id);
    const readinessSummary=readiness?`<p class="small"><strong>Atlas build status:</strong> ${readiness.status==='partial-local-targets'?'Some local point candidates published; the full sector is not mapped.':'Source review only; no qualified fishing points published for this sector.'} ${readiness.native_variable_depth_file_leads} variable-grid and ${readiness.native_regular_depth_file_leads} regular-grid original survey file(s) have some depth-screened cells; ${readiness.native_substrate_screen_files_with_eligible_sector_cells??0} substrate-screen file(s) have eligible native cells here, from ${readiness.native_substrate_review_file_leads} intersecting file envelope(s)${readiness.held_file_leads?`; ${readiness.held_file_leads} file lead(s) remain on hold`:''}. These are source counts, not reef or target counts. ${esc(readiness.next_source_step)} <a href="data/california-atlas-readiness.json" target="_blank" rel="noopener">Review all 19 sectors ↗</a></p>`:'';
    const hard=readiness?.nbs_original_hard_footprint_screen;
    const hardFootprintSummary=hard?`<details><summary>Measured hard-bottom source check · ${Number(hard.tiles_with_strict_original_hard_overlap)} matching tile(s)</summary><p class="small">${Number(hard.inventoried_tiles)} NOAA tile envelope(s) touch selected historical USGS hard-bottom outlines here; ${Number(hard.tiles_with_qualified_depth)} contain some measured 25–200 ft MLLW cells passing the strict depth and uncertainty screen; ${Number(hard.tiles_with_strict_original_hard_overlap)} also align with original USGS hard-class pixels outside buffered mapped closures. This is a limited source sample, not an exact reef, current fish location or fishing permission. Zero means no match in this sample. <a href="data/nbs-hard-footprint-original-class-overlap.json" target="_blank" rel="noopener">Inspect original-class review ↗</a></p></details>`:'';
    const usgsAreaLeads=readiness?.usgs_ds781_map_area_leads||[];
    const usgsCatalogSummary=usgsAreaLeads.length?`<details><summary>USGS State Waters map-area sources · ${usgsAreaLeads.length}</summary><p class="small">${readiness.usgs_ds781_opened_native_character_rasters||0} original character raster(s) opened for these broad map-area leads; ${readiness.usgs_ds781_verified_original_class_meanings||0} have rock-class meanings checked against the original raster table or hash-pinned USGS metadata (${readiness.usgs_ds781_verified_original_class_tables||0} had descriptive raster tables), from ${readiness.usgs_ds781_native_character_archive_leads||0} archive lead(s). These are source checks, not inspected fishing spots, complete measured footprints, or legal depth. <a href="data/usgs-ds781-native-character-review.json" target="_blank" rel="noopener">Native raster review ↗</a> · <a href="data/usgs-ds781-character-semantics.json?v=8.49" target="_blank" rel="noopener">Original class meanings ↗</a></p><ul class="survey-source-list">${usgsAreaLeads.map(area=>`<li>${esc(area.name)} · ${area.bathymetry_product_links} bathymetry, ${area.seafloor_character_product_links} seafloor-character and ${area.habitat_product_links} habitat archive link(s); ${area.fgdc_metadata_reviewed} original FGDC metadata record(s) read, ${area.fgdc_metadata_unavailable} unavailable; ${area.explicit_public_domain_metadata} explicitly say public-domain redistribution${area.bathymetry_datum_declarations.length?`; bathymetry datum: ${area.bathymetry_datum_declarations.map(esc).join(', ')}`:''}${area.priority_product_status==='index-link-mismatch'?' · index link points to another map area; held for source correction':''}<br><a href="${esc(area.catalog_url)}" target="_blank" rel="noopener">USGS catalog ↗</a></li>`).join('')}</ul><p><a href="data/usgs-ds781-source-leads.json" target="_blank" rel="noopener">Original product and metadata links ↗</a></p></details>`:'';
    const seabedSummary=readiness?`<p class="small">NOAA historical bottom descriptions: ${readiness.historical_noaa_seabed_samples} sparse sample point(s) in this broad sector. The statewide source spans 1968–2016 and has missing codes; zero here means no service sample, not no habitat. These are not reef outlines or fishing pins. <a href="data/noaa-seabed-samples-sector-review.json" target="_blank" rel="noopener">Source audit ↗</a></p>`:'';
    const nos=nosOverlapData?.sectors.find(item=>item.sector_id===selectedSector.id);
    const nosSummary=nos?.uncurated_rock_word_samples?`<p class="small">Rock-description check: ${nos.uncurated_rock_word_samples} historical free-text sample(s); ${nos.qualified_outside_mpa_buffer} land on an audited 25–200 ft original MLLW cell outside the 100 m MPA review buffer. ${selectedSector.id==='bodega-reyes'?`${nos.qualified_inside_reviewed_bodega_hard_outline} also fall within the separately mapped Bodega hard-bottom outlines.`:'An independent hard-class footprint has not been joined for this sector.'} A sample cannot establish a reef edge or fishing spot. <a href="data/noaa-seabed-samples-native-overlap-review.json" target="_blank" rel="noopener">Native-cell review ↗</a></p>`:'';
    const reef=reefcheckData?.sectors.find(item=>item.sector_id===selectedSector.id);
    const reefSummary=reef?`<p class="small">Historical Reef Check scuba transects (2006–2019): ${reef.events} at ${reef.distinct_site_labels_and_coordinates} site label/coordinate combination(s); lingcod observed on ${reef.events_with_lingcod_present} transects and some rockfish on ${reef.events_with_any_rockfish_present}. Zero means no transects in this archive, not no fish. These selected shallow reefs include protected sites and have at least 250 m position uncertainty. Counts are not fish abundance, a present-day bite forecast, or fishing pins. <a href="data/reefcheck-statewide-observation-review.json" target="_blank" rel="noopener">Statewide source review ↗</a></p>`:'';
    const crfs=crfsData?.sectors.find(item=>item.sector_id===selectedSector.id);
    const crfsSummary=crfs?`<p class="small">CDFW historical recreational survey: ${crfs.reported_blocks} reported one-minute blocks in this broad sector; ${crfs.blocks_2021_2024_all_catch.positive||0} have positive combined rockfish/cabezon/greenling/lingcod catch per bottomfish angler for 2021–2024, while ${crfs.blocks_2021_2024_all_catch.unavailable||0} lack a recent value. This mixes species and fishing modes. Interview-reported blocks can share one trip and are not exact catch sites, MPA clearance or a present-day bite rating. <a href="data/cdfw-crfs-rcgl-sector-review.json" target="_blank" rel="noopener">CDFW source review ↗</a></p>`:'';
    const row=surveyData?.sectors.find(x=>x.sector_id===selectedSector.id);
    if(!row){
      const video=videoAuditData?.sectors.find(item=>item.id===selectedSector.id);
      list.innerHTML=`<p>${esc(selectedSector.name)}: NOAA survey catalog unavailable. No seabed coverage inferred.</p>${readinessSummary}${hardFootprintSummary}${usgsCatalogSummary}${seabedSummary}${nosSummary}${crfsSummary}${reefSummary}${video?`<p class="small">USGS historical camera transects: ${video.bottom_observations||0} bottom observations in this latitude band. These are not fishing spots or current fish abundance. <a href="data/usgs-video-observation-audit.json" target="_blank" rel="noopener">Original archive receipts ↗</a></p>`:''}`;
      return;
    }
    const products=new Map((productData?.surveys||[]).map(item=>[item.id,item]));
    const native=nativeDepthData?.sectors.find(item=>item.sector_id===selectedSector.id);
    const regular=regularDepthData?.sectors.find(item=>item.sector_id===selectedSector.id);
    const usgs=usgsDatumData?.sectors.find(item=>item.sector_id===selectedSector.id);
    const video=videoAuditData?.sectors.find(item=>item.id===selectedSector.id);
    const videoSummary=video?`<p class="small">USGS historical camera transects: ${video.bottom_observations||0} bottom observations in this latitude band, including ${video.rock_boulder_cobble_observations||0} labeled rock, boulder or cobble. Rockfish were coded in ${video.rockfish_positive_observations||0} observations (${video.rockfish_field_observations||0} with that field); lingcod in ${video.lingcod_positive_observations||0} (${video.lingcod_field_observations||0} with that field). These are dated visual records with variable position accuracy, not current fish abundance, map-wide habitat or fishing coordinates. <a href="data/usgs-video-observation-audit.json" target="_blank" rel="noopener">Cruise dates and source receipts ↗</a></p>`:'';
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
    list.innerHTML=`<p><strong>${esc(selectedSector.name)}</strong> · ${sorted.length} intersecting NOAA survey leads. Catalog footprints and product links are not verified fishing grounds or continuous bottom coverage.</p>${readinessSummary}${hardFootprintSummary}${usgsCatalogSummary}${seabedSummary}${nosSummary}${crfsSummary}${regularSummary}${nativeSummary}${usgsSummary}${reefSummary}${videoSummary}${productData?`<p class="small">Product pages checked ${esc(productData.collected_at.slice(0,10))} · ${esc(productData.health.status)}.</p>`:'<p class="small">Original product-link inventory unavailable; use each NOAA catalog.</p>'}<ul class="survey-source-list">${sorted.slice(0,20).map(entry).join('')}</ul>${sorted.length>20?`<details><summary>Show ${sorted.length-20} more surveys</summary><ul class="survey-source-list">${sorted.slice(20).map(entry).join('')}</ul></details>`:''}`;
  }
   void fetch('data/california-atlas-readiness.json?v=8.49',{signal:AbortSignal.timeout(10000)}).then(r=>{if(!r.ok)throw Error('Atlas queue unavailable');return r.json();}).then(data=>{readinessData=data;showSurveySources();}).catch(()=>{});
  void fetch('data/noaa-seabed-samples-native-overlap-review.json',{signal:AbortSignal.timeout(10000)}).then(async r=>{
    if(!r.ok)throw Error('NOAA native-sample review unavailable');
    const data=await r.json();
    if(data.scope!=='nos-rock-description-versus-original-noaa-depth-triage'||data.fishing_target!==false||data.exportable!==false
      ||data.sectors?.length!==sectorPacket.sectors.length
      ||data.sectors.reduce((sum,item)=>sum+item.uncurated_rock_word_samples,0)!==18
      ||data.sectors.reduce((sum,item)=>sum+item.qualified_outside_mpa_buffer,0)!==1)throw Error('Incomplete NOAA native-sample review');
    nosOverlapData=data;showSurveySources();
  }).catch(()=>{/* Older source summary remains usable without this optional native-cell cross-check. */});
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
  void fetch('data/cdfw-crfs-rcgl-sector-review.json',{signal:AbortSignal.timeout(10000)}).then(async response=>{
    if(!response.ok)throw Error('CDFW historical survey review unavailable');
    const data=await response.json();
    if(data.schema_version!==1||data.records_reviewed!==4471||data.source_last_edit_ms!==1753738702086
      ||data.fishing_target!==false||data.current_fish_presence!==false||data.exportable!==false
      ||data.sectors?.length!==sectorPacket.sectors.length
      ||new Set(data.sectors.map(item=>item.sector_id)).size!==sectorPacket.sectors.length
      ||data.sectors.some(item=>!sectorPacket.sectors.some(sector=>sector.id===item.sector_id)
        ||!Number.isInteger(item.reported_blocks)||item.reported_blocks<0
        ||['positive','zero','unavailable'].some(key=>!Number.isInteger(item.blocks_2021_2024_all_catch[key]||0)
          ||(item.blocks_2021_2024_all_catch[key]||0)<0)
        ||Object.values(item.blocks_2021_2024_all_catch).reduce((a,b)=>a+b,0)!==item.reported_blocks)
      ||data.sectors.reduce((a,item)=>a+item.reported_blocks,0)+data.outside_browse_sectors!==data.records_reviewed)
      throw Error('Invalid CDFW historical survey review');
    crfsData=data;showSurveySources();
  }).catch(()=>{/* Historical catch context is optional and never a fishing-target input. */});
  void fetch('data/reefcheck-statewide-observation-review.json',{signal:AbortSignal.timeout(10000)}).then(async response=>{
    if(!response.ok)throw Error('Historical Reef Check review unavailable');
    const data=await response.json();
    if(data.schema_version!==1||data.scope!=='statewide-historical-shallow-diver-observation-audit'
      ||data.fishing_target!==false||data.current_fish_presence!==false||data.exportable!==false
      ||data.sectors?.length!==sectorPacket.sectors.length
      ||data.archive_table_rows?.['event.txt']!==19375
      ||new Set(data.sectors.map(item=>item.sector_id)).size!==sectorPacket.sectors.length
      ||data.sectors.some(item=>!sectorPacket.sectors.some(sector=>sector.id===item.sector_id)
        ||!Number.isInteger(item.events)||item.events<0
        ||!Number.isInteger(item.distinct_site_labels_and_coordinates)||item.distinct_site_labels_and_coordinates<0
        ||!Number.isInteger(item.events_with_lingcod_present)||item.events_with_lingcod_present<0
        ||!Number.isInteger(item.events_with_any_rockfish_present)||item.events_with_any_rockfish_present<0
        ||item.events_with_lingcod_present>item.events
        ||item.events_with_any_rockfish_present>item.events))throw Error('Invalid historical Reef Check audit');
    reefcheckData=data;showSurveySources();
  }).catch(()=>{/* Historical biology is optional context, never a reason to infer fishing spots. */});
  void fetch('data/usgs-video-observation-audit.json',{signal:AbortSignal.timeout(10000)}).then(async response=>{
    if(!response.ok)throw Error('USGS video audit unavailable');
    const data=await response.json();
    if(data.schema_version!==1||data.scope!=='usgs-ds781-statewide-original-video-audit'||data.fishing_target!==false
      ||data.sectors?.length!==sectorPacket.sectors.length||data.cruises?.length!==12)throw Error('Invalid USGS video audit');
    videoAuditData=data;showSurveySources();
  }).catch(()=>{/* Survey source links remain available without this optional historical audit. */});
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
      let monterey=new Map(),montereyDetailUnavailable=false;
      if(coast.id==='central'){
        try{
          const [originalResponse,depthResponse]=await Promise.all([
            fetch('data/usgs-offshore-monterey-hard-context.geojson',{signal:AbortSignal.timeout(15000)}),
            fetch('data/usgs-offshore-monterey-bathy-context-review.json',{signal:AbortSignal.timeout(15000)})]);
          if(!originalResponse.ok||!depthResponse.ok)throw Error('Monterey original-depth review unavailable');
          monterey=matchMontereyToStatewide(data,await originalResponse.json(),await depthResponse.json());
        }catch{montereyDetailUnavailable=true;}
      }
      statewideShapes=data.features.map(f=>{
        const p=f.properties;
        const shape=L.geoJSON(f,{pane:'statewideHistoricalSeabed',style:{color:'#8b612e',weight:1,fillColor:'#d7a35e',fillOpacity:.24}})
          .bindPopup(monterey.has(p.id)?montereyResearchPopup(f,monterey.get(p.id)):`<strong>Historical hard, rugged seabed</strong><p>${esc(p.block_id||p.release_id)} · USGS ${esc(p.source_year)} · generalized 20 m view. No fishing target, legal-depth clearance, catch report or navigation accuracy.</p><a href="${esc(p.metadata_url)}" target="_blank" rel="noopener">Original USGS metadata ↗</a>`);
        return {shape,bounds:shape.getBounds()};
      });
      statewideLoaded=true;statewideContext.addTo(map);drawStatewideContext();
      const sources=new Set(data.features.map(f=>f.properties.block_id||f.properties.release_id));
      statewideNote.textContent=data.features.length?`${data.features.length} historical outlines from ${sources.size} USGS source areas on this coast. Smaller patches and unmapped stretches are absent; MPAs remain visible. No fishing spot or legal depth is implied.${montereyDetailUnavailable?' Monterey original-depth details unavailable.':''}`:'No reviewed USGS hard-bottom outlines are available on this coast yet. NOAA survey grids still require native substrate and depth review.';
    }catch(error){statewideCheck.checked=false;statewideNote.textContent=error.message+' · consult the original USGS catalog.';}
  });
  if(['northern','san-francisco','central','southern'].includes(coast.id)){
    const northern=coast.id==='northern';
    const pointConception=coast.id==='central';
    const gaviota=coast.id==='southern';
    const nativePane=northern?'capeNativeHard':pointConception?'pointConceptionNativeHard':gaviota?'gaviotaNativeHard':'sfNativeHard';
    const nativeFile=northern?'cape-mendocino-native-hard-context.geojson':pointConception?'point-conception-native-hard-context.geojson':gaviota?'gaviota-native-hard-context.geojson':'sf-native-hard-context.geojson';
    const chartReview=northern?['cape-mendocino-enc-context-review.json','cape-mendocino-hard-context']:
      pointConception?['point-conception-enc-context-review.json','point-conception-hard-context']:
      gaviota?['gaviota-enc-context-review.json','gaviota-hard-context']:null;
    const nativeLayer=L.layerGroup();map.createPane(nativePane).style.zIndex=426;
    const nativeLabel=document.createElement('label');nativeLabel.className='map-layer-option';
    const nativeCheck=document.createElement('input');nativeCheck.type='checkbox';
    const nativeTitle=document.createElement('span');nativeTitle.textContent=northern?'Cape Mendocino · screened hard bottom':pointConception?'Point Conception · surveyed hard bottom':gaviota?'Cojo–Gaviota · surveyed hard bottom':'Bodega–Bolinas · surveyed hard bottom';
    nativeLabel.append(nativeCheck,nativeTitle);body.append(nativeLabel);
    const nativeNote=document.createElement('p');nativeNote.className='small';
    nativeNote.textContent='Optional historical NOAA native-depth and USGS hard-seabed intersection. Research context only; not a fishing target, current legal clearance or navigation chart.'+(pointConception?' Check Point Conception military danger-zone notices before travel.':'');
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
            ||f.properties?.depth_qualified_for_target!==false
            ||(northern&&(!Number.isFinite(f.properties?.sampled_relief_5_95_m)||!Number.isFinite(f.properties?.approx_display_area_m2)
              ||f.properties?.depth_range_kind!=='screened-policy-not-local-depth-range'))))throw Error('Unreviewed original-cell layer');
        const chart=chartReview?await fetch(`data/${chartReview[0]}`,{cache:'no-cache',signal:AbortSignal.timeout(10000)})
          .then(async response=>response.ok?response.json():null).catch(()=>null):null;
        const reviewedChart=chart?.schema_version===1&&chart.scope_id===chartReview?.[1]
          &&chart.status==='research-screen-only'&&chart.queried_layers===18
          &&Object.values(chart.context_outlines_in_scope_by_survey||{}).reduce((sum,count)=>sum+count,0)===data.features.length
          &&Array.isArray(chart.outlines_near_charted_dangers)
          &&chart.outlines_near_charted_dangers.every(row=>data.features.some(f=>f.properties.id===row.context_id)
            &&row.charted_dangers_within_buffer>0)?chart:null;
        const dangerById=new Map((reviewedChart?.outlines_near_charted_dangers||[])
          .map(row=>[row.context_id,row.charted_dangers_within_buffer]));
        const overlap=await fetch('data/usgs-video-native-overlap.json',{signal:AbortSignal.timeout(10000)})
          .then(async response=>response.ok?response.json():null).catch(()=>null);
        const reviewedOverlap=overlap?.schema_version===1&&overlap.scope==='usgs-video-vs-native-hard-context-review'
          &&overlap.fishing_target===false&&overlap.exportable===false&&overlap.minimum_interior_clearance_m===25
          ?overlap.layers?.find(layer=>layer.context_file===nativeFile&&layer.outline_count===data.features.length):null;
        const cameraById=new Map((reviewedOverlap?.matched_outlines||[]).map(item=>[item.outline_id,item]));
        let priorityById=new Map(),priorityClosureDate='';
        if(northern||pointConception){
          const priorityStem=northern?'cape-mendocino':'point-conception';
          const priorityCount=northern?32:4;
          const queueName=northern?'cape-mendocino-original-habitat-site-review-queue.json':'point-conception-regular-site-review-queue.json';
          const [queue,closures]=await Promise.all([
            fetch(`data/${queueName}`,{signal:AbortSignal.timeout(10000)}).then(r=>r.ok?r.json():null).catch(()=>null),
            fetch(`data/${priorityStem}-shortlist-closure-review.json`,{signal:AbortSignal.timeout(10000)}).then(r=>r.ok?r.json():null).catch(()=>null)
          ]);
          const ids=new Set(data.features.map(f=>f.properties.id));
          if(queue?.scope==='original-habitat-site-review-queue'&&queue.fishing_target===false&&queue.exportable===false
            &&queue.source_context_outlines===data.features.length&&queue.research_shortlist_count===priorityCount
            &&new Set(queue.research_shortlist.map(row=>row.context_id)).size===priorityCount
            &&queue.research_shortlist.every(row=>ids.has(row.context_id)&&row.fishing_target===false)
            &&closures?.scope==='original-habitat-shortlist-fresh-closure-audit'&&closures.fishing_target===false
            &&closures.exportable===false&&closures.shortlist_count===priorityCount&&closures.held_count===0&&closures.buffer_m===100
            &&closures.outlines.length===priorityCount&&new Set(closures.outlines.map(row=>row.context_id)).size===priorityCount
            &&closures.outlines.every(row=>ids.has(row.context_id)
              &&queue.research_shortlist.some(item=>item.context_id===row.context_id)&&row.fishing_target===false
              &&row.within_closure_review_buffer===false)){
            const cleared=new Map(closures.outlines.map(row=>[row.context_id,row]));
            priorityById=new Map(queue.research_shortlist.map((row,index)=>[row.context_id,{...row,rank:index+1,closure:cleared.get(row.context_id)}]));
            priorityClosureDate=closures.audited_at.slice(0,10);
          }
        }
        nativeShapes=data.features.map(f=>{
          const p=f.properties;
          const camera=cameraById.get(p.id);
          const chartedDangers=dangerById.get(p.id);
          const priority=priorityById.get(p.id);
          const depthText=northern?`original cells screened to ${esc(p.depth_screen_ft.join('–'))} ft MLLW planning range; no polygon-specific depth claim`:`source depth ${esc(p.depth_ft_range.join('–'))} ft MLLW`;
          const structureText=northern?`<p>Approximate displayed patch ${esc(p.approx_display_area_m2.toLocaleString())} m²; sampled 5–95% bottom relief ${esc(p.sampled_relief_5_95_m)} m. These describe historical physical structure, not a fish or bite rating.</p>`:'';
          const cameraText=camera?.interior_windows?`<p>USGS camera, ${esc(camera.observation_dates.join(', '))}: ${camera.interior_windows} annotated windows on ${camera.distinct_transects} historical transect(s) at least 25 m inside this displayed outline. ${camera.rock_boulder_cobble_windows} labeled rock/boulder/cobble; ${camera.sand_mud_windows} sand/mud. This supports mixed bottom along the camera path, not fish presence or the whole patch. <a href="${esc(camera.source_urls[0])}" target="_blank" rel="noopener">Original camera log ↗</a></p>`:'';
          const dangerText=chartedDangers?`<p><strong>Charted danger nearby:</strong> ${esc(chartedDangers)} feature(s) within 100 m in a limited NOAA ENC Direct screen dated ${esc(reviewedChart.enc_checked_at.slice(0,10))}. Do not use this outline for navigation or as a fishing waypoint.</p>`:
            reviewedChart?`<p>No nearby feature in the selected chart-danger classes as of ${esc(reviewedChart.enc_checked_at.slice(0,10))}; this does not clear the site or route.</p>`:
            '<p>Current charted hazards have not been matched to this displayed outline.</p>';
          const priorityText=priority?`<p><strong>Physical habitat research priority ${priority.rank} of ${priorityById.size}.</strong> This patch passed the project's area, relief and sampled-depth triage. A ${esc(priorityClosureDate)} GIS screen found the outline ${esc(priority.closure.nearest_cdfw_mpa_m)} m from the nearest CDFW MPA and ${esc(priority.closure.nearest_noaa_gea_m)} m from the nearest federal GEA. The screen may be stale; exact rules, current chart, safe approach and fish presence remain unverified. It is not a fishing score or waypoint.</p>`:'';
          const shape=L.geoJSON(f,{pane:nativePane,style:{color:chartedDangers?'#a56a1e':priority?'#126f68':'#396a75',weight:chartedDangers?2.2:priority?2.4:1.4,fillColor:chartedDangers?'#e4af58':priority?'#5fa79b':'#70aab4',fillOpacity:priority?.28:.22}})
            .bindPopup(`<strong>${priority?'Historical hard-bottom research priority':'Historical surveyed hard bottom'}</strong><p>NOAA ${esc(p.survey_id)} · ${esc(p.survey_dates[0].slice(0,4))} survey · ${depthText} · USGS hard-seabed class. This is not a fish location, legal clearance or navigation chart.</p>${priorityText}${dangerText}${structureText}${cameraText}<p>MPA/GEA screen compiled ${esc(data.mpa_screened_at.slice(0,10))}; recheck current rules and charts.${pointConception?' Check <a href="https://www.vandenberg.spaceforce.mil/About-Us/Environmental/Vandenberg-SFB-Maritime-Updates/" target="_blank" rel="noopener">Vandenberg maritime status ↗</a> before travel.':''}</p><a href="${esc(p.noaa_bag_url)}" target="_blank" rel="noopener">Original NOAA depth grid ↗</a> · <a href="${esc(p.usgs_metadata_urls[0])}" target="_blank" rel="noopener">USGS class metadata ↗</a>`);
          return {shape,bounds:shape.getBounds()};
        });
        nativeLoaded=true;nativeLayer.addTo(map);drawNative();
        nativeNote.textContent=`${data.features.length} historical hard-bottom outlines.${priorityById.size?` ${priorityById.size} stronger physical research priorities are outlined in teal, with a dated ${priorityClosureDate} MPA/GEA distance check.`:''}${reviewedChart?` ${dangerById.size} amber outlines have nearby charted danger features in a limited ${reviewedChart.enc_checked_at.slice(0,10)} screen.`:' Current chart-danger matching is unavailable for this layer.'} Current fishing permission, charts, YRCA rules, depth changes and catch presence still need review.${pointConception?' Vandenberg danger-zone status must be checked before travel.':''} No points enter plans or exports.`;
      }catch(error){nativeCheck.checked=false;nativeNote.textContent=error.message+' · use original NOAA and USGS sources.';}
    });
  }
  const measuredHardResearch={
    northern:{name:'Cape Mendocino',sectors:['humboldt-cape'],uncertainty:1},
    'san-francisco':{name:'Bodega–Point Reyes',sectors:['arena-bodega','bodega-reyes'],uncertainty:1},
    central:{name:'Estero Bay–Point Conception',sectors:['cambria-morro','morro-conception'],uncertainty:2}
  }[coast.id];
  if(measuredHardResearch){
    const hardLayer=L.layerGroup();map.createPane('measuredHardResearch').style.zIndex=427;
    const hardLabel=document.createElement('label');hardLabel.className='map-layer-option';
    const hardCheck=document.createElement('input');hardCheck.type='checkbox';
    const hardTitle=document.createElement('span');hardTitle.textContent=`${measuredHardResearch.name} · measured-depth hard-bottom research`;
    hardLabel.append(hardCheck,hardTitle);body.append(hardLabel);
    const hardNote=document.createElement('p');hardNote.className='small';
    hardNote.textContent=`Optional historical USGS bottom class intersected with NOAA measured depth, ≤${measuredHardResearch.uncertainty} m supplied uncertainty. No verified fish or fishing points.`;
    body.append(hardNote);
    let hardLoaded=false,hardShapes=[];
    function drawHard(){if(!hardCheck.checked||!hardLoaded)return;
      for(const {shape,bounds} of hardShapes){
        if(bounds.intersects(map.getBounds())){if(!hardLayer.hasLayer(shape))hardLayer.addLayer(shape);}
        else if(hardLayer.hasLayer(shape))hardLayer.removeLayer(shape);
      }
    }
    map.on('moveend',drawHard);
    hardCheck.addEventListener('change',async()=>{
      if(!hardCheck.checked){map.removeLayer(hardLayer);return;}
      if(hardLoaded){hardLayer.addTo(map);drawHard();return;}
      hardNote.textContent='Loading reviewed original-cell research outlines…';
      try{
        const response=await fetch(`data/${encodeURIComponent(coast.id)}-nbs-usgs-hard-research-context.geojson`,{signal:AbortSignal.timeout(20000)});
        if(!response.ok)throw Error('Measured-depth source review unavailable');
        const data=await response.json();
        if(data.type!=='FeatureCollection'||data.scope!==`${coast.id}-nbs-usgs-hard-research-context`
          ||data.coast_id!==coast.id||data.maximum_screen_uncertainty_m!==measuredHardResearch.uncertainty
          ||!Array.isArray(data.features)
          ||data.features.some(f=>!measuredHardResearch.sectors.includes(f.properties?.sector_id)||f.properties?.fishing_target!==false
            ||f.properties?.exportable!==false||f.properties?.legal_clearance!==false
            ||f.properties?.fish_confirmed!==false||f.properties?.depth_qualified_for_target!==false
            ||!Number.isFinite(f.properties?.maximum_supplied_uncertainty_m)
            ||f.properties.maximum_supplied_uncertainty_m>measuredHardResearch.uncertainty
            ||!Array.isArray(f.properties?.usgs_sources)||!f.properties.usgs_sources.length))throw Error('Unreviewed measured-depth source layer');
        const cameraReview=await fetch('data/usgs-video-nbs-hard-overlap.json',{signal:AbortSignal.timeout(10000)})
          .then(async response=>response.ok?response.json():null).catch(()=>null);
        const sourceFile=`${coast.id}-nbs-usgs-hard-research-context.geojson`;
        const cameraLayer=cameraReview?.scope==='usgs-video-vs-native-hard-context-review'
          &&cameraReview.fishing_target===false&&cameraReview.exportable===false
          &&cameraReview.minimum_interior_clearance_m===25
          ?cameraReview.layers?.find(layer=>layer.context_file===sourceFile
            &&layer.context_compiled_at===data.compiled_at&&layer.outline_count===data.features.length):null;
        const cameraById=new Map((cameraLayer?.matched_outlines||[])
          .filter(row=>row.interior_windows>0).map(row=>[row.outline_id,row]));
        hardShapes=data.features.map(f=>{
          const p=f.properties;
          const source=p.usgs_sources[0];
          const camera=cameraById.get(p.id);
          const cameraText=camera?`<p>USGS camera ${esc(camera.observation_dates.join(', '))}: ${esc(camera.interior_windows)} annotated windows on ${esc(camera.distinct_transects)} historical transect(s) at least 25 m inside this displayed outline. ${esc(camera.rock_boulder_cobble_windows)} labeled rock/boulder/cobble; ${esc(camera.sand_mud_windows)} sand/mud.${camera.rockfish_positive_windows?` Rockfish appeared in ${esc(camera.rockfish_positive_windows)} windows; these are old sightings, not catches or a current fish forecast.`:''} <a href="${esc(camera.source_urls[0])}" target="_blank" rel="noopener">Original camera log ↗</a></p>`:'<p>No position-qualified camera observation is attached to this outline.</p>';
          const shape=L.geoJSON(f,{pane:'measuredHardResearch',style:{color:camera?'#256f77':'#866b37',weight:camera?2:1.4,fillColor:camera?'#6eb5b5':'#c9b078',fillOpacity:.23}})
            .bindPopup(`<strong>Historical measured-depth hard-bottom research</strong><p>${esc(p.sector_id)} · ${esc(p.measured_depth_ft_range.join('–'))} ft MLLW in NOAA measured cells; supplied uncertainty up to ${esc(p.maximum_supplied_uncertainty_m)} m. ${esc(p.approx_display_area_m2.toLocaleString())} m² displayed in conservative ${esc(p.display_cell_m)} m squares. USGS class-3 rock/boulder interpretation is historical. This does not establish a rated fishing spot, legal access or navigation safety.</p>${cameraText}<p>MPA and federal exclusion screen compiled ${esc(data.mpa_screened_at.slice(0,10))}; recheck present boundaries and rules.</p><a href="${esc(p.nbs_raster_url)}" target="_blank" rel="noopener">NOAA source tile ↗</a> · <a href="${esc(source.metadata_url)}" target="_blank" rel="noopener">USGS bottom-class metadata ↗</a>`);
          return {shape,bounds:shape.getBounds()};
        });
        hardLoaded=true;hardLayer.addTo(map);drawHard();
        hardNote.textContent=`${data.features.length} historical research outlines near ${measuredHardResearch.name}.${cameraById.size?` ${cameraById.size} teal outlines have dated USGS camera observations.`:''} These are not verified fishing grounds or exportable positions; current charts, rules and fish presence still require review.`;
      }catch(error){hardCheck.checked=false;hardNote.textContent=error.message+' · consult NOAA and USGS sources.';}
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
    updateLocalTargetAdvisory();
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

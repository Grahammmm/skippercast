import {initChart} from './chart-map.js?v=8.8';
import {initNavigation} from './navigation.js?v=8.8';
import {esc} from './marine-charts.js?v=8.8';
import {viewFromURL} from './location-context.js?v=8.8';
import {coastAt,coastURL,sourceFresh,initCoastSelector,initCoastalContext,coastalTargetOptions} from './coasts.js?v=8.8';

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
  const links=packages.map(r=>`<a class="coastal-package" href="${esc(coastURL(location.href,coast,{packageId:r.id}).pathname+coastURL(location.href,coast,{packageId:r.id}).search+'#map')}">${esc(r.name)} · open detailed map ↗</a>`).join('');
  const panel=document.getElementById('guide-panel');
  panel.innerHTML=`<h1>${esc(coast.name)} coast</h1><p>${esc(coast.limits)}</p><section id="coastal-target-guide"></section><details id="coastal-seasonal" class="guide-topic" open><summary>Regional species & seasonal watch</summary></details><h2>Detailed mapping</h2><p>${packages.length?'Open a reviewed local data package:':'Source discovery covers regional species and MPAs. Survey-qualified fishing spots, local weather and exports have not been published for this coast.'}</p>${links}<p class="small">${esc(catalog.scope)}</p>`;
  for(const [id,title] of [['forecast-panel','Local forecast coverage'],['export-panel','Fishing-plan export']]) {
    document.getElementById(id).innerHTML=`<h1>${title}</h1><p>Select a detailed mapped area to use its conditions and fishing-plan export. Other regions’ forecasts and waypoints are never substituted here.</p>${links||'<p>This coast’s detailed data package is pending.</p>'}<a href="#map">Back to map</a>`;
  }
  const banner=document.getElementById('best-day-banner');banner.innerHTML='<span>Coastal guide</span><strong>Species & sources</strong>';banner.addEventListener('click',()=>navigation.showView('guide'));
  const options=document.getElementById('map-options');
  // Keep the existing chart selector, then discard controls for layers this browse mode does not own.
  const chartLabel=document.getElementById('base-map').closest('label');
  const body=options.querySelector('.options-body');body.replaceChildren(chartLabel);
  const detail=document.createElement('div');detail.innerHTML=`<p class="small">Clean chart: depths, coastal features and navigation aids. MPAs stay visible. Full NOAA restores all chart symbols.</p><h3>${esc(coast.name)} · ${esc(coast.limits)}</h3>${links||'<p>Detailed fishing maps are pending for this coast.</p>'}`;body.append(detail);
  document.getElementById('open-map-options').addEventListener('click',()=>options.showModal());document.getElementById('close-map-options').addEventListener('click',()=>options.close());
  const note=document.getElementById('region-note');note.hidden=false;note.textContent='Coastal guide · select a mapped area in Options for fishing spots';
  document.getElementById('map-empty').hidden=true;
  let boundaries=null,boundaryTime=null,mpaStatus='Checking MPA boundaries…',navigating=false;
  const mpaLayer=L.layerGroup().addTo(map);map.createPane('coastalMPAs').style.zIndex=440;
  function drawMPAs() {
    mpaLayer.clearLayers();
    for(const f of boundaries?.features||[]) {
      const shape=L.geoJSON(f,{pane:'coastalMPAs',style:{color:'#bd3869',weight:2,fillOpacity:.08}});
      if(!shape.getBounds().intersects(map.getBounds()))continue;
      shape.bindTooltip(esc(f.properties.NAME)).bindPopup(`<strong>${esc(f.properties.FULLNAME||f.properties.NAME)}</strong><p>Marine protected area. Species-specific restrictions apply.</p><p>${esc(mpaStatus)}</p><a href="https://wildlife.ca.gov/Conservation/Marine/MPAs" target="_blank" rel="noopener">Official boundaries & rules ↗</a>`).addTo(mpaLayer);
    }
    const status=document.getElementById('coastal-mpa-status');if(status)status.textContent=mpaStatus;
  }
  function move() {
    const p=map.getCenter(),point={latitude:p.lat,longitude:p.lng},next=coastAt(point,catalog);
    if(next && next.id!==coast.id && !navigating) {navigating=true;location.replace(coastURL(location.href,next,{point,zoom:map.getZoom(),target:select.value}));return;}
    caption.textContent=next?`${coast.name} · ${coast.limits}`:'Outside California coastal browse coverage';
    select.disabled=!next;rules.hidden=!next;
    const url=coastURL(location.href,coast,{point,zoom:map.getZoom(),target:select.value,overview:true});url.hash=location.hash;history.replaceState(null,'',url);
    drawMPAs();
  }
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
  drawMPAs();
}

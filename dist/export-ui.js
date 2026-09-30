import {getRegion,getRegionDirectory} from './region.js';
import {esc} from './marine-charts.js';
import {buildExport,offlineNotes,readDraft,draftKey} from './trip-export.js';
import {navigate} from '../web/state.ts';
import {track} from '../web/telemetry.ts';
import {loadReefTrip} from './reef-trip-data.js';
import {bestSpots,fitLabel,waypointTitle} from './spot-ranking.js';
import {HOME_PORT_KEY} from './home-port.js';

const DEVICE_HELP={
  generic:['Chartplotter model not selected','Download GPX, copy it to storage supported by your model, then use its Import menu. Most reviewed plotters use SD/microSD; USB support varies. Inserting media alone does not import a plan.','https://www8.garmin.com/manuals/webhelp/GUID-3E67C80C-0812-4EEC-BC60-699751B9CF6F/EN-US/GPSMAP_x3_OM_EN-US.pdf'],
  garmin:['Garmin GPSMAP / ECHOMAP','Use a compatible SD/microSD card. Select GPX as the data-transfer file type, then Manage User Data → Data Transfer → Merge from Card. Avoid Replace from Card if you want to retain existing data. Menu names depend on model.','https://support.garmin.com/en-US/?faq=zFDPlv7AnK2eNWRp2AgMkA'],
  lowrance:['Lowrance HDS','Copy GPX to a compatible memory card. In Storage / Files, select the file and Import. Verify the instructions for your model and software. HDS PRO total capacity: 3,000 waypoints, 100 trails, 10,000 points per trail.','https://www.lowrance.com/hds-pro/specs/'],
  simrad:['Simrad NSS / NSX','Use a compatible memory card; USB is model-specific. Use Files or the waypoint/route/track import controls to import GPX. NSX total capacity: 6,000 waypoints, 50 tracks, 12,000 points per track. Other Simrad models differ.','https://www.simrad-yachting.com/en-eu/nsx/specifications/'],
  raymarine:['Raymarine Axiom','Copy GPX to compatible storage. In LightHouse 4, use My data → Import/export → Import from card, or select the file in Files. Axiom 2 total capacity: 10,000 waypoints and 15 tracks (10,000 points per track).','https://docs.raymarine.com/81406/en-US/latest/index.html'],
  inavx:['iNavX on iPad / iPhone','Use Share / Save file to open GPX in iNavX. Or download, open the file from Files → Downloads, then Share → iNavX. Display imported waypoints and tracks. No USB or memory card is required.','https://inavx.com/h/inavx/waypoints.htm'],
};
export function initExport({atlas,screen,map,getVisible,navigation,onConditions=()=>{}}) {
  const root=document.getElementById('export-content'), region=getRegion();
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:region.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  let raw=null;try{raw=localStorage.getItem(draftKey(region.id));}catch{}
  const tripAtlas={...atlas,targets:[...atlas.targets],areas:[...atlas.areas]};
  const draft=readDraft(raw,atlas,today);let search='',storageOK=true,ranked=false,filtersDirty=false,ports=[],canonical=null;
  let restorePending=!!draft.rankedPlan,restoring=false,selectionRevision=0,selectionLoading=false;
  let savedPort;try{savedPort=localStorage.getItem(HOME_PORT_KEY);}catch{}
  root.innerHTML=`<div class="export-card export-plan">
    <label>Region<select id="export-region">${getRegionDirectory().map(r=>`<option value="${esc(r.id)}" ${r.id===region.id?'selected':''}>${esc(r.name)}</option>`).join('')}</select></label>
    <div class="export-fields"><label>Plan name<input id="export-name" maxlength="80" value="${esc(draft.name)}"></label><label>Fishing date<input type="date" id="export-date" value="${esc(draft.date)}"></label></div>
    <p class="export-note" id="export-storage">Saved on this browser for each region. Separate from your account’s trip alerts.</p>
    </div>
    <details class="export-card" id="export-spots" open><summary><span>1. Choose your spots</span><strong id="export-selection-count"></strong></summary>
      <div class="export-card-body">
      <button class="primary export-best" id="export-best">Best available · up to 20 reef spots</button>
      <p class="export-note">Ranked reef habitat. Confidence % describes habitat evidence.</p>
      <details class="export-trip-filters"><summary>Trip filters</summary><div class="export-fields">
      <label>Target<select id="export-species"><option value="reef">Lingcod + rockfish</option><option value="lingcod">Lingcod</option><option value="rockfish">Rockfish</option></select></label>
      <label>Maximum spots<select id="export-limit"><option>10</option><option selected>20</option><option>30</option><option>50</option></select></label>
      <label>Maximum depth (ft)<input id="export-depth" type="number" value="300" min="25" max="300"></label>
      <label>Search area<select id="export-best-scope"><option value="region">Selected region</option><option value="map">Current map view</option></select></label>
      <label>From port<select id="export-port"><option value="">No distance limit</option></select></label>
      <label>Maximum one-way distance (nm)<input id="export-distance" type="number" min="1" max="100" value="20"></label>
      </div><p class="export-note">Distance is straight-line reference only. Habitat ranks stay fixed; check the selected day’s conditions separately.</p></details>
      <p><button id="export-map">Show ranked spots on map</button> <button id="export-conditions">Check trip conditions</button></p>
      <details><summary>How ranking and confidence work</summary><p>3/3 Strong, 2/3 Good, 1/3 Secondary habitat fit. The combined target uses the weaker of the two fits. We select distinct reefs at least 0.15 nm apart; fewer than your limit may qualify.</p><p>Confidence index: original survey 25 points, valid metric support up to 25, fine resolution up to 20, interpreted substrate coverage up to 20, known survey year 5, documented independent support 5. Unknown interpolation flags cap it at 90%. This is an evidence rubric, not a statistical probability of catching fish. Reef depths are nominal; verify them on your sounder.</p></details>
      <p>Start with a set, then check only the spots you want. Current map and filtered sets use your species and depth filters.</p>
      <div class="export-presets"><button data-scope="map">Current map</button><button data-scope="filtered">Filtered spots</button><button data-scope="region">Whole region</button><button data-scope="none">Clear selection</button></div>
      <p id="export-scope-status" role="status"></p>
      <label>Find a spot<input id="export-search" type="search" placeholder="Name, ID or grade" autocomplete="off"></label><div id="export-spot-list" class="export-spot-list" role="group" aria-label="Choose fishing spots"></div>
      </div></details>
    <details class="export-card" id="export-layers"><summary><span>2. What to include</span><strong id="export-layer-count">Waypoints</strong></summary><div class="export-card-body export-checks">
      ${[
        ['waypoints','Fishing waypoints','Selected positions with terrain, depth and source notes.'],
        ['outlines','Linked reef outlines','Partial habitat boundaries as tracks, included once per area.'],
        ['alignments','Structure alignment lines','Fixed survey alignments as tracks. Not forecast drifts or routes.'],
        ['exclusions','Protected-area outlines','AVOID tracks for MPAs and mapped groundfish exclusions; whole outlines that intersect your chosen coverage.'],
      ].map(([id,name,description])=>`<label class="export-check"><input type="checkbox" data-layer="${id}" ${draft.layers[id]?'checked':''}><span><strong>${name}</strong><small>${description}</small></span></label>`).join('')}
      <label>Protected-area coverage<select id="export-avoid-scope"><option value="map">Current map view</option><option value="region">Whole selected region</option></select></label>
      <p class="export-note">GPX carries coordinates and text. Chart imagery, bathymetry, live forecasts and predicted drift guides remain in the app. Static outlines do not replace official charts or current rules.</p>
      </div></details>
    <section class="export-card export-transfer" aria-labelledby="export-transfer-title"><h2 id="export-transfer-title">3. Take your plan aboard</h2>
      <div id="export-counts" class="export-counts" aria-live="polite"></div><p id="export-validation" role="status"></p>
      <div class="export-actions"><button class="primary" id="export-download">Download GPX</button><button id="export-share">Share / Save file</button><button id="export-notes">Download offline notes</button></div>
      <p id="export-action-status" role="status"></p>
      <details class="export-help"><summary>USB, memory card &amp; iNavX help</summary>
      <label>Your chartplotter<select id="export-device">${Object.entries(DEVICE_HELP).map(([id,[name]])=>`<option value="${id}">${name}</option>`).join('')}</select></label><p id="export-device-help"></p><a id="export-device-source" target="_blank" rel="noopener">Official device reference ↗</a>
      <ol><li>Back up your existing waypoints and tracks.</li><li>Download the GPX. Copy it to the USB drive or SD/microSD card your model supports, or share it to iNavX.</li><li>Import using the device’s menu. Enable waypoints and tracks, then compare a name and coordinate with SkipperCast.</li></ol>
      <p>GPX interchange is not a guarantee for every device. Total device capacities include existing data; check free space and your model’s limits. Many plotters store far fewer tracks than waypoints. Start with a small waypoint-only set. Reimporting can create duplicates.</p>
      <p>Offline notes are a separate HTML file for a phone, tablet or computer, not for import into a plotter. Files do not update automatically. Recheck rules and conditions before departure.</p>
      </details></section>`;
  const $=id=>document.getElementById(id);
  $('export-best').disabled=true;
  function persist(){try{localStorage.setItem(draftKey(region.id),JSON.stringify(draft));storageOK=true;}catch{storageOK=false;}$('export-storage').textContent=storageOK?'Saved on this browser for each region. Separate from your account’s trip alerts.':'Browser storage is unavailable. Keep this page open until you download your plan.';}
  $('export-avoid-scope').value=draft.avoidScope;
  function request(){
    if(restorePending)throw Error('Saved ranked plan needs current reef data. Restore it or select Best available again.');
    if(filtersDirty)throw Error("Trip filters changed. Select Best available again before exporting.");
    if(draft.layers.exclusions&&draft.avoidScope==='map'&&!map.getSize().x)throw Error('Open the map to choose its coverage first, or choose Whole selected region for protected-area outlines.');
    const b=map.getBounds();return {atlas:tripAtlas,screen,ids:draft.ids,layers:draft.layers,region,title:`${draft.name||'My fishing day'} · ${draft.date||today}`,bounds:draft.avoidScope==='region'?region.mpa.bounds:[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()]};
  }
  const resultTargets=()=>draft.ids.map(id=>tripAtlas.targets.find(t=>t.id===id)).filter(Boolean);
  function updateSummary(){
    for(const id of ['export-map','export-conditions'])$(id).disabled=!ranked||filtersDirty||!draft.ids.length;
    $('export-selection-count').textContent=`${draft.ids.length} selected`;
    $('export-layer-count').textContent=`${Object.values(draft.layers).filter(Boolean).length} layers`;
    try{
      const {counts:c}=buildExport(request());
      $('export-counts').innerHTML=`<strong>${c.waypoints} <span>waypoints</span></strong><strong>${c.tracks} <span>tracks</span></strong>`;
      $('export-validation').textContent=`${c.outlines} reef outlines · ${c.alignments} alignments · ${c.exclusions} AVOID outlines. ${c.trackPoints.toLocaleString()} track points; largest track ${c.largestTrack.toLocaleString()}.${c.tracks>15?' More than 15 tracks: check your device’s free track capacity or reduce outlines.':''} Boundaries checked again when you export.`;
      for(const id of ['export-download','export-share','export-notes'])$(id).disabled=false;
      if(ranked)document.dispatchEvent(new CustomEvent('skippercast:trip-ranked',{detail:{targets:resultTargets(),areas:tripAtlas.areas.filter(a=>draft.ids.includes(a.id)),publication:tripAtlas.publication}}));
    }catch(error){
      $('export-counts').textContent=`${draft.ids.length} spots in your plan`;
      $('export-validation').textContent=error.message;
      for(const id of ['export-download','export-share','export-notes'])$(id).disabled=true;
    }
  }
  function renderList(){
    const list=$('export-spot-list');if(!list)return;
    const matches=tripAtlas.targets.filter(t=>(!ranked||t.trip_rank)&&`${t.id} ${t.label} ${t.habitat_grade}`.toLowerCase().includes(search)).sort((a,b)=>ranked?a.trip_rank-b.trip_rank:0);
    list.innerHTML=matches.map(t=>`<label class="export-check"><input type="checkbox" data-spot="${esc(t.id)}" ${draft.ids.includes(t.id)?'checked':''}><span><strong>${esc(t.trip_rank?'#'+t.trip_rank+' · '+fitLabel(t.trip_fit)+' · '+t.evidence_confidence.percent+'% confidence':t.label)}</strong><small>${esc(t.trip_rank?t.name:t.id)} · grade ${esc(t.habitat_grade)} · ${esc(t.canonical_habitat?t.neighborhood_depth_ft.map(n=>Math.round(n)).join('–'):t.center_depth_ft)} ft</small>${t.trip_rank?`<small>${esc(t.terrain_interpretation)}</small>`:''}</span></label>`).join('')||'<p>No matching spots. Your existing selection is retained.</p>';
  }
  function open(){navigation.showView('export');updateSummary();$('export-panel').scrollTop=0;$('export-heading').tabIndex=-1;$('export-heading').focus({preventScroll:true});}
  function add(id){if(!tripAtlas.targets.some(t=>t.id===id))return;selectionRevision++;if(ranked&&!tripAtlas.targets.find(t=>t.id===id)?.trip_rank){ranked=false;document.dispatchEvent(new CustomEvent('skippercast:trip-ranked',{detail:{targets:[],areas:[]}}));}if(!draft.ids.includes(id)){draft.ids.push(id);track('spot_saved');}persist();renderList();updateSummary();}
  $('export-region').onchange=()=>{persist();const url=new URL(location.href);url.searchParams.set('region',$('export-region').value);for(const key of ['view','focus','spot','target'])url.searchParams.delete(key);url.hash='export';navigate(url);};
  for(const [id,key] of [['export-name','name'],['export-date','date']])$(id).addEventListener('input',()=>{selectionRevision++;draft[key]=$(id).value;persist();});
  $('export-search')?.addEventListener('input',e=>{search=e.target.value.trim().toLowerCase();renderList();});
  root.addEventListener('change',e=>{
    selectionRevision++;
    if(e.target.dataset.spot){const id=e.target.dataset.spot;draft.ids=e.target.checked?[...new Set([...draft.ids,id])]:draft.ids.filter(x=>x!==id);}
    if(e.target.dataset.layer)draft.layers[e.target.dataset.layer]=e.target.checked;
    if(e.target.id==='export-avoid-scope')draft.avoidScope=e.target.value;
    persist();updateSummary();
  });
  root.addEventListener('click',e=>{
    const scope=e.target.closest('[data-scope]')?.dataset.scope;if(!scope)return;
    selectionRevision++;
    ranked=false;filtersDirty=false;restorePending=false;draft.rankedPlan=null;document.dispatchEvent(new CustomEvent('skippercast:trip-ranked',{detail:{targets:[],areas:[]}}));
    if(scope==='map'&&!map.getSize().x){$('export-scope-status').textContent='Open the map to choose an area first. Your selection is retained.';return;}
    const targets=scope==='region'?atlas.targets:scope==='none'?[]:getVisible().filter(t=>scope==='filtered'||map.getBounds().contains([t.latitude,t.longitude]));
    draft.ids=targets.map(t=>t.id);persist();renderList();updateSummary();
    $('export-scope-status').textContent=`${draft.ids.length} spots selected. ${scope==='region'?'Whole-region selection ignores map filters. Review individual spots below.':'Your previous selection has been replaced.'}`;
  });
  const save=(file)=>{const url=URL.createObjectURL(file),a=document.createElement('a');a.href=url;a.download=file.name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);};
  async function deliver(kind){
    try{
      if(draft.ids.some(id=>tripAtlas.targets.find(t=>t.id===id)?.canonical_habitat)){
        const latest=await loadReefTrip(region.id);
        if(latest.publication.export_sha256!==canonical?.publication.export_sha256)throw Error('Reef data changed. Select Best available again before exporting.');
        tripAtlas.publication=latest.publication;
      }
      // Repeat the authoritative screen here, even if the preview count was valid moments ago.
      const result=buildExport(request());
      const base=`SkipperCast-${region.id}-${draft.date||today}-${result.counts.waypoints}wp`;
      const file=new File([kind==='notes'?offlineNotes(result,region,{...draft,date:draft.date||today}):result.gpx],`${base}.${kind==='notes'?'html':'gpx'}`,{type:kind==='notes'?'text/html':'application/gpx+xml'});
      if(kind==='share'&&navigator.canShare?.({files:[file]})){await navigator.share({files:[file],title:draft.name});$('export-action-status').textContent='File handed to the share sheet. Confirm the import inside your chartplotter app.';}
      else {save(file);$('export-action-status').textContent=`Download requested: ${file.name}. Find it in Downloads or your chosen save location.${kind==='share'?' This browser cannot share this file directly.':''}`;}
    }catch(error){$('export-action-status').textContent=error.name==='AbortError'?'Share cancelled. Your plan is retained.':error.message;updateSummary();}
  }

  async function selectBest(){
    const revision=++selectionRevision;selectionLoading=true;
    const filters={species:$('export-species').value,count:Number($('export-limit').value),maxDepth:Number($('export-depth').value),maxDistanceNm:Number($('export-distance').value)};
    const portID=$('export-port').value,scope=$('export-best-scope').value,b=map.getBounds();
    filters.bounds=scope==='map'?[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()]:null;
    const button=$('export-best');button.disabled=true;$('export-scope-status').textContent='Loading current screened reefs…';
    try{
      await portsLoaded;
      const loaded=await loadReefTrip(region.id);
      if(revision!==selectionRevision)return;
      const port=ports.find(p=>p.id===portID);
      if(scope==='map'&&!map.getSize().x)throw Error('Open the map first to choose its area.');
      const depth=filters.maxDepth, distance=filters.maxDistanceNm;
      if(depth>300||depth<25||!Number.isFinite(distance)||distance<=0)throw Error('Choose a depth from 25–300 ft and a positive distance.');
      const selected=bestSpots(loaded,screen,{...filters,origin:port?{latitude:port.match[0],longitude:port.match[1]}:null});
      if(!selected.length)throw Error('No ranked reefs meet these filters and current checks. Widen the area or distance; no weaker spots were added.');
      canonical=loaded;tripAtlas.publication=loaded.publication;
      tripAtlas.targets=[...atlas.targets,...loaded.targets.map(t=>selected.find(s=>s.id===t.id)||t)];
      tripAtlas.areas=[...atlas.areas,...loaded.areas];tripAtlas.source_validation_date=loaded.source_validation_date;
      draft.ids=selected.map(t=>t.id);draft.layers={waypoints:true,outlines:true,alignments:false,exclusions:false};ranked=true;filtersDirty=false;
      restorePending=false;draft.rankedPlan={sha256:loaded.publication.export_sha256,species:filters.species,priorities:selected.map(t=>({id:t.id,rank:t.trip_rank}))};
      if(draft.name==='My fishing day')draft.name='Lingcod + rockfish';
      if(draft.date===today){const d=new Date(today+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+(5-d.getUTCDay()+7)%7);draft.date=d.toISOString().slice(0,10);}
      $('export-name').value=draft.name;$('export-date').value=draft.date;
      for(const el of root.querySelectorAll('[data-layer]'))el.checked=draft.layers[el.dataset.layer];
      persist();renderList();updateSummary();
      $('export-scope-status').textContent=`${selected.length} distinct reef spots ranked. Waypoints + reef outlines only. ${selected.length<Number($('export-limit').value)?'Fewer than your requested limit qualified. ':''}Check conditions for ${draft.date} before committing to the trip.`;
      document.dispatchEvent(new CustomEvent('skippercast:trip-ranked',{detail:{targets:selected,areas:loaded.areas.filter(a=>draft.ids.includes(a.id)),publication:tripAtlas.publication}}));
    }catch(error){if(revision===selectionRevision)$('export-scope-status').textContent=error.message;}
    finally{selectionLoading=false;button.disabled=false;if(revision!==selectionRevision&&$('export-scope-status').textContent==='Loading current screened reefs…')$('export-scope-status').textContent='Selection changed while loading. Select Best available again to apply it.';}
  }
  $('export-best').onclick=selectBest;
  $('export-map').onclick=()=>{if(!ranked||filtersDirty)return;navigation.showView('map');document.dispatchEvent(new CustomEvent('skippercast:trip-ranked',{detail:{targets:resultTargets(),areas:tripAtlas.areas.filter(a=>draft.ids.includes(a.id)),publication:tripAtlas.publication,fit:true}}));};
  $('export-conditions').onclick=()=>onConditions({date:draft.date,target:tripAtlas.targets.find(t=>t.id===draft.ids[0]),species:$('export-species').value});
  for(const id of ['export-species','export-limit','export-depth','export-best-scope','export-port','export-distance'])$(id).addEventListener('change',()=>{
    $('export-best').textContent=`Best available · up to ${$('export-limit').value} reef spots`;
    if(ranked){filtersDirty=true;$('export-scope-status').textContent='Trip filters changed. Select Best available again to apply them.';updateSummary();}
  });
  const portsLoaded=fetch('data/home-ports.json').then(r=>r.ok?r.json():null).then(d=>{
    ports=(d?.ports||[]).filter(p=>p.region===region.id);
    for(const p of ports)$('export-port').add(new Option(p.name,p.id));
    $('export-port').value=ports.some(p=>p.id===savedPort)?savedPort:ports[0]?.id||'';
  }).catch(()=>{}).finally(()=>{if(!selectionLoading)$('export-best').disabled=false;});
  async function restore(){
    if(!restorePending||restoring||selectionLoading)return;restoring=true;const revision=selectionRevision;
    try{
      const loaded=await loadReefTrip(region.id),plan=draft.rankedPlan;
      if(!restorePending||!plan||revision!==selectionRevision)return;
      if(plan.sha256!==loaded.publication.export_sha256)throw Error('Saved reef data changed. Select Best available again; your saved selections have been retained for review.');
      if(plan.priorities.some(p=>!loaded.targets.some(t=>t.id===p.id)))throw Error('Saved reefs are unavailable. Select Best available again.');
      canonical=loaded;tripAtlas.publication=loaded.publication;
      tripAtlas.targets=[...atlas.targets,...loaded.targets.map(t=>{
        const p=plan.priorities.find(p=>p.id===t.id);if(!p)return t;
        const fit=plan.species==='lingcod'?t.species_fit.lingcod:plan.species==='rockfish'?t.species_fit['rockfish-reef']:Math.min(t.species_fit.lingcod,t.species_fit['rockfish-reef']);
        const s={...t,trip_rank:p.rank,trip_fit:fit,trip_species:plan.species};s.name=waypointTitle(s);return s;
      })];
      tripAtlas.areas=[...atlas.areas,...loaded.areas];tripAtlas.source_validation_date=loaded.source_validation_date;
      $('export-species').value=plan.species;ranked=draft.ids.every(id=>plan.priorities.some(p=>p.id===id));restorePending=false;
      $('export-scope-status').textContent='Saved ranked reefs restored from the current publication. Check your trip conditions before departure.';
      renderList();updateSummary();
    }catch(e){if(revision===selectionRevision)$('export-scope-status').textContent=e.message;}
    finally{restoring=false;}
  }
  $('export-download').onclick=()=>deliver('gpx');$('export-share').onclick=()=>deliver('share');$('export-notes').onclick=()=>deliver('notes');
  function deviceHelp(){const [,text,url]=DEVICE_HELP[$('export-device').value];$('export-device-help').textContent=text;$('export-device-source').href=url;}
  $('export-device').onchange=deviceHelp;deviceHelp();renderList();updateSummary();
  document.addEventListener('skippercast:boundaries',()=>{if(document.body.dataset.view==='export')updateSummary();});
  window.addEventListener('hashchange',()=>{if(location.hash==='#export'){renderList();updateSummary();void restore();}});
  if(location.hash==='#export')void restore();
  setInterval(()=>{if(document.body.dataset.view==='export')updateSummary();},60000);
  return {open,add,conditions(target){onConditions({date:draft.date,target,species:target.trip_species});},review(id){add(id);open();},mount(container,target){
    if(!tripAtlas.targets.some(t=>t.id===target.id))return;
    const row=document.createElement('div');row.className='button-row';
    const addButton=document.createElement('button');addButton.textContent=draft.ids.includes(target.id)?'Added to day plan':'Add to day plan';
    addButton.onclick=()=>{add(target.id);addButton.textContent='Added to day plan';};
    const review=document.createElement('button');review.textContent='Review & export';review.onclick=open;
    row.append(addButton,review);container.append(row);
  }};
}

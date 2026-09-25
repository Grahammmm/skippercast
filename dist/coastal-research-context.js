// Optional, non-exportable source context for discovery sectors without a full package.
import {esc} from './marine-charts.js?v=8.11';

export function validateMontereyResearch(context, depth) {
  if(context?.type!=='FeatureCollection' || context.scope!=='generalized-statewide-usgs-hard-bottom-context'
    || !Array.isArray(context.features) || context.features.length!==88
    || depth?.scope!=='original-usgs-bathymetry-vs-habitat-context'
    || depth.source_id!=='offshore-monterey-character-2016'
    || depth.vertical_datum!=='NAVD88' || depth.mllw_conversion_reviewed!==false
    || depth.product_uncertainty_grid_available!==false || depth.context_outlines!==88
    || depth.fishing_target!==false || depth.exportable!==false
    || !Array.isArray(depth.outlines) || depth.outlines.length!==88)throw Error('Monterey research receipts changed');
  const rows=new Map(depth.outlines.map(row=>[row.context_id,row]));
  if(rows.size!==88 || context.features.some(feature=>{
    const p=feature.properties,row=rows.get(p?.id);
    return !row || p.block_id!=='OffshoreMonterey' || p.fishing_target!==false
      || p.exportable!==false || p.depth_qualified!==false || p.fish_confirmed!==false
      || p.source_file_sha256!=='8ca813f1fbfd7afb231914d7a9ebdb5667559bf0172a2024f3d45e9180d94e08'
      || p.source_metadata_sha256!=='3ed18fdaac9509ed23dac4fb976da9cd77c0d1509e4a6d28a090ce2b65e341db'
      || !['Polygon','MultiPolygon'].includes(feature.geometry?.type)
      || row.depth_qualified_for_target!==false;
  }))throw Error('Monterey outline/receipt mismatch');
  return rows;
}

export function montereyResearchPopup(feature,row) {
  const d=row.depth_m_below_navd88;
  const depth=d && [d.minimum,d.p10,d.p90,d.maximum].every(Number.isFinite)
    ? `Original sampled bottom: ${Math.round(d.minimum*3.28084)}–${Math.round(d.maximum*3.28084)} ft below NAVD88; central 10th–90th percentile ${Math.round(d.p10*3.28084)}–${Math.round(d.p90*3.28084)} ft. This is not chart MLLW depth.`
    : 'No measured depth cells under this outline.';
  const camera=row.historical_camera_interior_windows
    ? `${row.historical_camera_interior_windows} historical camera windows inside this display outline on ${row.distinct_historical_transects} transect(s); ${row.historical_rockfish_positive_windows} coded rockfish. These are dated observations, not current fish or catches.`
    : 'No interior historical camera match in the reviewed archive.';
  return `<strong>Monterey · historical hard-bottom context</strong><p>${esc(feature.properties.source_class)}. Display geometry is generalized, not an exact rock edge.</p><p>${esc(depth)}</p><p>${esc(camera)}</p><p>Research only: MLLW conversion, product uncertainty, current chart, route and date-specific rules are not cleared. Check the live MPA layer; no fishing rank or export is assigned.</p><a href="${esc(feature.properties.metadata_url)}" target="_blank" rel="noopener">Original USGS metadata ↗</a>`;
}

export function addMontereyResearchOption(map,body,select) {
  const layer=L.layerGroup(),pane=map.createPane('montereyResearch');pane.style.zIndex=425;
  const label=document.createElement('label');label.className='map-layer-option';
  const check=document.createElement('input');check.type='checkbox';
  const title=document.createElement('span');title.textContent='Monterey · historical hard bottom';
  label.append(check,title);body.append(label);
  const note=document.createElement('p');note.className='small';body.append(note);
  let loaded=false;
  const show=()=>{
    const reef=select.value==='reef';
    note.textContent=reef?'Optional 88 USGS research outlines. They are not depth-qualified fishing spots; open an outline for original sample depths.':'This hard-bottom research layer is shown with the lingcod & rockfish selector.';
    if(!check.checked || !reef)map.removeLayer(layer);
    else if(loaded)layer.addTo(map);
  };
  select.addEventListener('change',show);
  check.addEventListener('change',async()=>{
    show();if(!check.checked || select.value!=='reef' || loaded)return;
    try{
      const [contextResponse,depthResponse]=await Promise.all([
        fetch('data/usgs-offshore-monterey-hard-context.geojson',{signal:AbortSignal.timeout(15000)}),
        fetch('data/usgs-offshore-monterey-bathy-context-review.json',{signal:AbortSignal.timeout(15000)})]);
      if(!contextResponse.ok || !depthResponse.ok)throw Error('Monterey original-source context unavailable');
      const context=await contextResponse.json(),depth=await depthResponse.json();
      const rows=validateMontereyResearch(context,depth);
      L.geoJSON(context,{pane:'montereyResearch',style:{color:'#176b70',weight:1.5,fillColor:'#4a9691',fillOpacity:.15},
        onEachFeature:(feature,shape)=>shape.bindPopup(montereyResearchPopup(feature,rows.get(feature.properties.id)))}).addTo(layer);
      loaded=true;show();
    }catch(error){check.checked=false;show();note.textContent=`${error.message}. Consult the original USGS source.`;}
  });
  show();
}

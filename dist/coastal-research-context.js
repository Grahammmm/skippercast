// Original sampled-depth annotations for Monterey's existing USGS context layer.
import {esc} from './marine-charts.js?v=8.12';

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

export function matchMontereyToStatewide(statewide, original, depth) {
  const sourceRows=validateMontereyResearch(original,depth);
  const regional=statewide?.features?.filter(f=>f.properties?.release_id==='F70Z71C8') || [];
  if(statewide?.coast_id!=='central' || regional.length!==88)throw Error('Statewide Monterey context changed');
  const byId=new Map(regional.map(f=>[f.properties.id,f]));
  if(byId.size!==88)throw Error('Duplicate statewide Monterey outline');
  const result=new Map();
  for(const feature of original.features){
    const suffix=feature.properties.id.split('-').at(-1),id=`usgs-doi-F70Z71C8-${suffix}`;
    const partner=byId.get(id);
    if(!partner || JSON.stringify(partner.geometry)!==JSON.stringify(feature.geometry)
      || partner.properties.source_file_sha256!==feature.properties.source_file_sha256)
      throw Error('Statewide and original Monterey outlines differ');
    result.set(id,sourceRows.get(feature.properties.id));
  }
  return result;
}

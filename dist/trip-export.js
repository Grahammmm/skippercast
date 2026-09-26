// Shared export contract. Rendering and hardware instructions do not decide what is safe to serialize.
import {tripFeatures, featuresGPX, geometryTrack, xml} from './gpx.js?v=8.12';

export const DEFAULT_LAYERS={waypoints:true,outlines:false,alignments:false,exclusions:false};
export const draftKey=region=>`skippercast.export.v1.${region}`;
const validDate=value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value;
export function readDraft(raw,atlas,today) {
  let value;try{value=JSON.parse(raw);}catch{}
  const ids=new Set(atlas.targets.map(t=>t.id));
  return {ids:[...new Set(Array.isArray(value?.ids)?value.ids:[])].filter(id=>ids.has(id)),
    name:typeof value?.name==='string'?value.name.slice(0,80):'My fishing day',
    date:validDate(value?.date)?value.date:today,
    avoidScope:value?.avoidScope==='region'?'region':'map',
    layers:Object.fromEntries(Object.entries(DEFAULT_LAYERS).map(([k,v])=>[k,typeof value?.layers?.[k]==='boolean'?value.layers[k]:v]))};
}
const pairs=g=>g?.coordinates?.flat(Infinity) || [];
function extent(geometry){
  const values=pairs(geometry),xs=[],ys=[];
  for(let i=0;i<values.length;i+=2){xs.push(values[i]);ys.push(values[i+1]);}
  return [Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)];
}
const overlap=(a,b)=>a[0]<=b[2]&&a[2]>=b[0]&&a[1]<=b[3]&&a[3]>=b[1];
const validPoint=t=>Number.isFinite(t.latitude)&&Math.abs(t.latitude)<=90&&Number.isFinite(t.longitude)&&Math.abs(t.longitude)<=180;
export function buildExport({atlas,screen,ids,layers=DEFAULT_LAYERS,region,title='SkipperCast fishing day',bounds,now=new Date()}) {
  if(!screen?.ready())throw Error('Protected-area checks are unavailable or older than 36 hours. Return to the map and refresh before exporting.');
  const features=ids.length?tripFeatures(atlas,ids,layers):{selected:[],waypoints:[],areas:[],drifts:[]};
  if(features.selected.some(t=>!validPoint(t)||!screen.pointAllowed(t)))throw Error('A selected spot fails the current protected-area check. Review your selection on the map.');
  if([...features.areas,...features.drifts].some(f=>!screen.geometryAllowed(f.geometry)))throw Error('A selected outline or alignment intersects a protected area, or cannot be checked. Turn off that layer or choose a different spot.');
  const snapshot=screen.exportExclusions?.();
  if(layers.exclusions)for(const f of snapshot?.features||[])geometryTrack('Boundary validation','',f.geometry);
  // Avoid outlines use the current map extent, unless the user explicitly requests this whole region.
  const exportBounds=bounds||region.mpa.bounds;
  const exclusions=layers.exclusions?(snapshot?.features||[]).filter(f=>overlap(extent(f.geometry),exportBounds)):[];
  if(layers.exclusions&&!snapshot)throw Error('Current protected-area outlines are unavailable. Refresh before exporting.');
  if(!features.waypoints.length&&!features.areas.length&&!features.drifts.length&&!exclusions.length)throw Error('Select at least one spot and an included layer, or protected-area outlines within the chosen coverage.');
  const geometry=[...features.areas,...features.drifts,...exclusions].map(f=>f.geometry);
  const vertices=geometry.map(g=>pairs(g).length/2);
  const counts={waypoints:features.waypoints.length,outlines:features.areas.length,alignments:features.drifts.length,exclusions:exclusions.length,tracks:geometry.length,trackPoints:vertices.reduce((n,x)=>n+x,0),largestTrack:Math.max(0,...vertices)};
  const stamp=now.toISOString();
  const gpx=featuresGPX(atlas,features,title,{exclusions,checkedAt:snapshot?.checked_at,createdAt:stamp});
  return {gpx,counts,features,exclusions,created_at:stamp,boundary_checked_at:snapshot?.checked_at||null,region_id:region.id,source_validation_date:atlas.source_validation_date||null,layers:{...layers},avoid_bounds:exportBounds};
}
const safeLink=value=>{try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)?xml(u.href):'';}catch{return '';}};
export function offlineNotes(result,region,draft) {
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${xml(draft.name)} · SkipperCast</title><style>body{font:17px/1.55 system-ui,sans-serif;max-width:760px;margin:auto;padding:24px;color:#173d47}article{border-top:1px solid #ccd9db;padding:16px 0}h1{line-height:1.2}h2{font-size:1.2em}a{color:#006c65;overflow-wrap:anywhere}dt{font-weight:bold}dd{margin:0 0 12px}pre{white-space:pre-wrap}@media print{body{padding:0}article{break-inside:avoid}}</style><h1>${xml(draft.name)}</h1><p>${xml(region.name)} · Planned date ${xml(draft.date)}</p><p>Created ${xml(result.created_at)}. Protected-area source check ${xml(result.boundary_checked_at||'current session')}.</p><p>${result.counts.waypoints} waypoints · ${result.counts.tracks} reference tracks. WGS84 coordinates. Habitat research, not verified fish presence or navigation routes.</p><p><strong>Before departure:</strong> check current regulations, closures, marine conditions and harbor access. This file does not update offline. The planned date is a label, not a future clearance. Follow your official navigation chart and sounder.</p><p><a href="https://skippercast.com/?region=${xml(region.id)}#map">Reopen this region</a> · <a href="${safeLink(region.regulations_url)}">Official regional regulations</a></p>
  ${result.features.selected.map(t=>`<article><h2>${xml(t.id)} · ${xml(t.label)}</h2><p>${xml(t.latitude)}, ${xml(t.longitude)} · ${xml(t.center_depth_ft)} ft center · ${xml(t.neighborhood_depth_ft.join('–'))} ft nearby (survey MLLW)</p><dl><dt>Structure</dt><dd>${xml(t.terrain_interpretation)}</dd><dt>Priority</dt><dd>${xml(t.habitat_grade)} · ${xml(t.habitat_score)}/100 terrain score, not catch probability.</dd><dt>Evidence</dt><dd>${xml(t.evidence_status)} ${xml(t.ais_status)} Survey ${xml(t.survey_year)}.</dd><dt>Approach notes</dt><dd>${xml(t.special_note||'Locate structure and fish on your sounder; measure your actual drift before setting up.')} Fixed alignment tracks do not predict drift or provide a safe approach.</dd></dl><a href="${safeLink(t.source_url)}">Survey source</a></article>`).join('')}
  ${result.exclusions.length?`<article><h2>AVOID reference outlines</h2><ul>${result.exclusions.map(f=>`<li>${xml(f.properties.FULLNAME||f.properties.NAME)}</li>`).join('')}</ul><p>Includes whole outlines intersecting the chosen coverage. Outline tracks carry no protected-area fill or enforcement behavior on a chartplotter. They are a static reference, not a complete legal clearance.</p></article>`:''}<details><summary>Export record</summary><p>Atlas validation: ${xml(result.source_validation_date||"unavailable")}. Included layers: ${xml(Object.entries(result.layers).filter(([,v])=>v).map(([k])=>k).join(", "))}. AVOID selection bounds (west, south, east, north): ${xml(result.avoid_bounds.join(", "))}.</p></details><p>Forecast imagery, bathymetry tiles, live drift predictions and unqualified habitat previews are not embedded in GPX.</p></html>`;
}

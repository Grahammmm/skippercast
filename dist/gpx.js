export const xml = (value) =>
  String(value ?? "").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&apos;",
      })[c],
  );
export function tripFeatures(atlas,ids,options={}) {
  const selected=[...new Set(ids)].map(id=>atlas.targets.find(t=>t.id===id));
  if(!selected.length||selected.some(t=>!t))throw new Error('Unknown target or empty selection');
  const areaIds=new Set(options.outlines===false?[]:selected.flatMap(t=>t.area_ids));
  const driftIds=new Set(options.alignments===false?[]:selected.map(t=>t.drift_id).filter(Boolean));
  if([...areaIds].some(id=>!atlas.areas.some(a=>a.id===id)) || [...driftIds].some(id=>!atlas.drifts.some(d=>d.id===id)))throw Error('A selected spot has missing linked geometry. Refresh its regional data.');
  return {selected,waypoints:options.waypoints===false?[]:selected,
    areas:options.outlines===false?[]:atlas.areas.filter(a=>areaIds.has(a.id)),
    drifts:options.alignments===false?[]:atlas.drifts.filter(d=>driftIds.has(d.id))};
}
export function geometryTrack(name,description,geometry) {
  const segments=geometry.type==='Polygon'?geometry.coordinates:geometry.type==='MultiPolygon'?geometry.coordinates.flat():geometry.type==='LineString'?[geometry.coordinates]:geometry.type==='MultiLineString'?geometry.coordinates:[];
  if(!segments.length || segments.some(s=>s.length<2 || s.some(p=>!Number.isFinite(p[0])||!Number.isFinite(p[1])||Math.abs(p[0])>180||Math.abs(p[1])>90)))throw Error('Invalid export geometry');
  if(geometry.type.includes('Polygon') && segments.some(r=>r.length<4 || r[0][0]!==r.at(-1)[0] || r[0][1]!==r.at(-1)[1]))throw Error('Invalid export polygon: boundary rings must be closed and contain at least four positions.');
  return `<trk><name>${xml(name)}</name><desc>${xml(description)}</desc>${segments.map(ring=>`<trkseg>${ring.map(([lon,lat])=>`<trkpt lat="${lat}" lon="${lon}"/>`).join('')}</trkseg>`).join('')}</trk>`;
}
// Keep each polygon ring in a separate track segment, including interior holes.
export function tripGPX(atlas, ids, title='SkipperCast fishing set', options={}) {
  const features=tripFeatures(atlas,ids,options);
  return featuresGPX(atlas,features,title,options);
}
export function featuresGPX(atlas,features,title,options={}) {
  const selected=features.waypoints;
  const points=selected.map(t=>{
  const notes = [
    t.label,
    t.terrain_interpretation,
    `Terrain ${t.habitat_grade} ${t.habitat_score}/100; not catch probability.`,
    `Center ${t.center_depth_ft} ft; nearby ${t.neighborhood_depth_ft.join("–")} ft MLLW.`,
    t.evidence_status,
    t.ais_status,
    `Survey ${t.survey_year}; screen ${atlas.source_validation_date}.`,
    t.special_note,
    "Check current regulations, closures, conditions and sounder depths.",
  ].join(" ");
  return `<wpt lat="${t.latitude}" lon="${t.longitude}"><name>${xml(t.name)}</name><cmt>${xml(t.id)}</cmt><desc>${xml(notes)}</desc><link href="${xml(t.source_url)}"/><sym>Fishing Area</sym></wpt>`;
  });
  const tracks=features.areas.map(a=>geometryTrack(a.id,a.extent_note,a.geometry));
  for(const drift of features.drifts)tracks.push(geometryTrack(drift.id,`${drift.basis} Not a navigation route.`,drift.geometry));
  for(const f of options.exclusions||[])tracks.push(geometryTrack(`AVOID ${f.properties.NAME}`,`Protected-area reference. ${f.properties.FULLNAME||f.properties.NAME}. ${f.properties.CCR||''} Exported ${options.checkedAt||'with snapshot'}. Static outline; not a live legal boundary service. Consult official charts and rules.`,f.geometry));
  return `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="SkipperCast" xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>${xml(title)}</name><desc>WGS84 coordinates. Habitat research; tracks show outlines and structure alignments, not navigation routes. Check current rules and charted hazards.</desc>${options.createdAt?`<time>${xml(options.createdAt)}</time>`:""}</metadata>${points.join('')}${tracks.join("")}</gpx>\n`;
}
export function targetGPX(atlas,id){return tripGPX(atlas,[id],atlas.targets.find(t=>t.id===id)?.name+' habitat research');}

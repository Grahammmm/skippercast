const xml = (value) =>
  String(value ?? "").replace(
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
// Keep each polygon ring in a separate track segment, including interior holes.
export function tripGPX(atlas, ids, title='SkipperCast fishing set') {
  const selected=[...new Set(ids)].map(id=>atlas.targets.find(t=>t.id===id));
  if(!selected.length||selected.some(t=>!t))throw new Error('Unknown target or empty selection');
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
  const areaIds=new Set(selected.flatMap(t=>t.area_ids));
  const driftIds=new Set(selected.map(t=>t.drift_id).filter(Boolean));
  const tracks = atlas.areas
    .filter((a) => areaIds.has(a.id))
    .map((a) => {
      const polygons =
        a.geometry.type === "Polygon"
          ? [a.geometry.coordinates]
          : a.geometry.coordinates;
      return `<trk><name>${xml(a.id)}</name><desc>${xml(a.extent_note)}</desc>${polygons.flatMap((p) => p.map((ring) => `<trkseg>${ring.map(([lon, lat]) => `<trkpt lat="${lat}" lon="${lon}"/>`).join("")}</trkseg>`)).join("")}</trk>`;
    });
  for(const drift of atlas.drifts.filter(d=>driftIds.has(d.id)))
    tracks.push(
      `<trk><name>${xml(drift.id)}</name><desc>${xml(drift.basis)} Not a navigation route.</desc><trkseg>${drift.geometry.coordinates.map(([lon, lat]) => `<trkpt lat="${lat}" lon="${lon}"/>`).join("")}</trkseg></trk>`,
    );
  return `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="SkipperCast" xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>${xml(title)}</name><desc>WGS84 coordinates. Habitat research; tracks show outlines and structure alignments, not navigation routes. Check current rules and charted hazards.</desc></metadata>${points.join('')}${tracks.join("")}</gpx>\n`;
}
export function targetGPX(atlas,id){return tripGPX(atlas,[id],atlas.targets.find(t=>t.id===id)?.name+' habitat research');}

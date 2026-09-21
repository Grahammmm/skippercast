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
export function targetGPX(atlas, id) {
  const t = atlas.targets.find((t) => t.id === id);
  if (!t) throw new Error("Unknown target");
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
  const point = `<wpt lat="${t.latitude}" lon="${t.longitude}"><name>${xml(t.name)}</name><desc>${xml(notes)}</desc><link href="${xml(t.source_url)}"/><sym>Fishing Area</sym></wpt>`;
  const tracks = atlas.areas
    .filter((a) => t.area_ids.includes(a.id))
    .map((a) => {
      const polygons =
        a.geometry.type === "Polygon"
          ? [a.geometry.coordinates]
          : a.geometry.coordinates;
      return `<trk><name>${xml(a.id)}</name><desc>${xml(a.extent_note)}</desc>${polygons.flatMap((p) => p.map((ring) => `<trkseg>${ring.map(([lon, lat]) => `<trkpt lat="${lat}" lon="${lon}"/>`).join("")}</trkseg>`)).join("")}</trk>`;
    });
  const drift = atlas.drifts.find((d) => d.id === t.drift_id);
  if (drift)
    tracks.push(
      `<trk><name>${xml(drift.id)}</name><desc>${xml(drift.basis)} Not a navigation route.</desc><trkseg>${drift.geometry.coordinates.map(([lon, lat]) => `<trkpt lat="${lat}" lon="${lon}"/>`).join("")}</trkseg></trk>`,
    );
  return `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="SkipperCast" xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>${xml(t.name)} habitat research</name></metadata>${point}${tracks.join("")}</gpx>\n`;
}

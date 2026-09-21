// Bundled GPX must pass the same current boundary screen as its map geometry.
export function atlasExportAllowed(atlas, screen, targetId=null) {
  if(!atlas || !screen?.ready()) return false;
  const targets=targetId ? atlas.targets.filter(t=>t.id===targetId) : atlas.targets;
  if(!targets.length || targets.some(t=>!screen.pointAllowed(t))) return false;
  const ids=new Set(targets.map(t=>t.id));
  const areas=atlas.areas.filter(a=>a.target_ids.some(id=>ids.has(id)));
  const drifts=atlas.drifts.filter(d=>ids.has(d.target_id));
  return [...areas,...drifts].every(g=>screen.geometryAllowed(g.geometry));
}

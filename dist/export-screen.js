// Bundled GPX must pass the same current boundary screen as its map geometry.
import {tripFeatures} from './gpx.js?v=8.5';
export function atlasExportAllowed(atlas, screen, targetId=null) {
  if(!atlas || !screen?.ready()) return false;
  const targets=targetId ? atlas.targets.filter(t=>t.id===targetId) : atlas.targets;
  if(!targets.length || targets.some(t=>!screen.pointAllowed(t))) return false;
  try{const f=tripFeatures(atlas,targets.map(t=>t.id));return [...f.areas,...f.drifts].every(g=>screen.geometryAllowed(g.geometry));}catch{return false;}
}

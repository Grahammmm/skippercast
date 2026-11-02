// WGS84 geometry screening for the local atlas. Boundary contact is excluded.
const boxes = new WeakMap();
export function positions(g) {
  if (!g) return [];
  const out = [];
  function walk(c) {
    if (typeof c?.[0] === "number") out.push(c);
    else for (const child of c || []) walk(child);
  }
  walk(g.coordinates);
  return out;
}
function bbox(g) {
  if (!boxes.has(g)) {
    const p = positions(g);
    boxes.set(g, p.reduce((b,p)=>[Math.min(b[0],p[0]),Math.min(b[1],p[1]),Math.max(b[2],p[0]),Math.max(b[3],p[1])],[Infinity,Infinity,-Infinity,-Infinity]));
  }
  return boxes.get(g);
}
function onSegment(p, a, b) {
  const cross = (p[1]-a[1])*(b[0]-a[0])-(p[0]-a[0])*(b[1]-a[1]);
  return Math.abs(cross) < 1e-12 && p[0] >= Math.min(a[0],b[0])-1e-10 && p[0] <= Math.max(a[0],b[0])+1e-10 && p[1] >= Math.min(a[1],b[1])-1e-10 && p[1] <= Math.max(a[1],b[1])+1e-10;
}
function inRing(p, ring) {
  let inside = false;
  for (let i=0,j=ring.length-1;i<ring.length;j=i++) {
    const a=ring[j],b=ring[i];
    if (onSegment(p,a,b)) return 2;
    if ((a[1]>p[1]) !== (b[1]>p[1]) && p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]) inside=!inside;
  }
  return inside ? 1 : 0;
}
export function pointInGeometry(p, g) {
  if(!g)return false;
  const b=bbox(g);
  if(p[0]<b[0]-1e-10||p[0]>b[2]+1e-10||p[1]<b[1]-1e-10||p[1]>b[3]+1e-10)return false;
  const polygons = g?.type === "Polygon" ? [g.coordinates] : g?.type === "MultiPolygon" ? g.coordinates : [];
  return polygons.some(rings => {
    const outer = inRing(p,rings[0]);
    if (!outer) return false;
    if (outer === 2) return true;
    const holes=rings.slice(1).map(r=>inRing(p,r));
    return holes.includes(2) || !holes.includes(1);
  });
}
function edges(g) {
  const lines = g.type === "Polygon" ? g.coordinates : g.type === "MultiPolygon" ? g.coordinates.flat() : g.type === "LineString" ? [g.coordinates] : g.type === "MultiLineString" ? g.coordinates : [];
  return lines.flatMap(line=>line.slice(1).map((p,i)=>[line[i],p]));
}
function cross(a,b,c) { return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]); }
function intersects(a,b,c,d) {
  if (onSegment(a,c,d)||onSegment(b,c,d)||onSegment(c,a,b)||onSegment(d,a,b)) return true;
  return cross(a,b,c)*cross(a,b,d)<0 && cross(c,d,a)*cross(c,d,b)<0;
}
export function geometryIntersects(a,b) {
  if (!a || !b) return false;
  const x=bbox(a),y=bbox(b);
  if (x[2]<y[0]||y[2]<x[0]||x[3]<y[1]||y[3]<x[1]) return false;
  if (positions(a).some(p=>pointInGeometry(p,b)) || positions(b).some(p=>pointInGeometry(p,a))) return true;
  const eb=edges(b);
  return edges(a).some(([p,q])=>eb.some(([r,s])=>intersects(p,q,r,s)));
}
// SC-LAUNCH-1: the one run-time closure check every output uses. Inputs are EPSG:4326 lon/lat; the margin is
// measured in metres in a local equirectangular frame at the screened geometry's latitude (the standard series
// for metres per degree), never in degrees. A geometry touching, inside, or within `marginM` of a closure is hit.
// The smallest MPA/GEA clearance a reviewed atlas or survey build here applies is 75 m (southern-california; central
// 102 m), cut from buffer polygons in a projected CRS: in this frame those outlines measure 74.89 m at the closest.
// 70 m keeps a 5 m allowance for that so the run-time screen agrees with every reviewed build.
export const PLANNING_MARGIN_M = 70;
const mPerDeg = lat => {
  const r = lat * Math.PI / 180;
  return [111412.84 * Math.cos(r) - 93.5 * Math.cos(3 * r), 111132.92 - 559.82 * Math.cos(2 * r) + 1.175 * Math.cos(4 * r)];
};
function segDist2(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy;
  const t = l ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l)) : 0;
  const x = a[0] + t * dx - p[0], y = a[1] + t * dy - p[1];
  return x * x + y * y;
}
export function withinMargin(a, b, marginM = PLANNING_MARGIN_M) {
  if (!a || !b) return false;
  const x = bbox(a), y = bbox(b);
  if (!x.every(Number.isFinite) || !y.every(Number.isFinite)) return false;
  const [kx, ky] = mPerDeg((x[1] + x[3]) / 2), m = Math.max(0, marginM), dx = m / kx, dy = m / ky;
  const near = (p, q) => p[0] - dx <= q[2] && q[0] <= p[2] + dx && p[1] - dy <= q[3] && q[1] <= p[3] + dy;
  if (!near(x, y)) return false;
  if (geometryIntersects(a, b)) return true;
  if (m === 0) return false;
  const proj = p => [p[0] * kx, p[1] * ky];
  const parts = (g, box) => {
    const e = edges(g).filter(([p, q]) => near([Math.min(p[0], q[0]), Math.min(p[1], q[1]), Math.max(p[0], q[0]), Math.max(p[1], q[1])], box));
    const segs = e.length || edges(g).length ? e : positions(g).map(p => [p, p]);
    return {segs: segs.map(([p, q]) => [proj(p), proj(q)]), pts: positions(g).filter(p => near([p[0], p[1], p[0], p[1]], box)).map(proj)};
  };
  const A = parts(a, y), B = parts(b, x), m2 = m * m;
  return A.pts.some(p => B.segs.some(([s, t]) => segDist2(p, s, t) <= m2)) || B.pts.some(p => A.segs.some(([s, t]) => segDist2(p, s, t) <= m2));
}
export const pointGeometry = (longitude, latitude) => ({type: 'Point', coordinates: [longitude, latitude]});
// The closures (anything with a `geometry`) that any of `geometries` touches or comes within `marginM` of.
/** @template {{geometry: unknown}} T @param {readonly unknown[]} geometries @param {readonly T[]} closures @param {number} [marginM] @returns {T[]} */
export function closureHits(geometries, closures, marginM = PLANNING_MARGIN_M) {
  const gs = geometries.filter(Boolean);
  return closures.filter(c => gs.some(g => withinMargin(g, c.geometry, marginM)));
}
export function circleGeometry(latitude, longitude, radiusM, steps=64) {
  const ring=Array.from({length:steps},(_,i)=>{
    const a=i/steps*2*Math.PI;
    return [longitude+Math.sin(a)*radiusM/(111320*Math.cos(latitude*Math.PI/180)),latitude+Math.cos(a)*radiusM/111320];
  });
  ring.push(ring[0]);
  return {type:"Polygon",coordinates:[ring]};
}

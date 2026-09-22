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
export function circleGeometry(latitude, longitude, radiusM, steps=64) {
  const ring=Array.from({length:steps},(_,i)=>{
    const a=i/steps*2*Math.PI;
    return [longitude+Math.sin(a)*radiusM/(111320*Math.cos(latitude*Math.PI/180)),latitude+Math.cos(a)*radiusM/111320];
  });
  ring.push(ring[0]);
  return {type:"Polygon",coordinates:[ring]};
}

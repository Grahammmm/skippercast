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
// Squared distance from point p to segment ab (projected metres). segD2 is the one copy of the arithmetic, on bare numbers.
function segD2(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay, l = dx * dx + dy * dy;
  const t = l ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l)) : 0;
  const x = ax + t * dx - px, y = ay + t * dy - py;
  return x * x + y * y;
}
function segDist2(p, a, b) { return segD2(p[0], p[1], a[0], a[1], b[0], b[1]); }
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
// SC0022-04: is the whole of `g`, plus the `marginM` search halo of the closure screen, inside the envelope a boundary file was
// asked for? A closure that lies wholly outside that envelope is absent from the file, so it could sit within `marginM` of a
// place near the edge: that edge strip is withheld, not cleared. Bounds are a finite, ordered, non-wrapping, non-polar WGS84
// [west, south, east, north]. Anything missing, malformed or out of range is false; this never throws and never assumes worldwide coverage.
const GEOMETRY_DEPTH = {Point: 0, MultiPoint: 1, LineString: 1, MultiLineString: 2, Polygon: 2, MultiPolygon: 3};
/** Every position of `g` (each ring and part), or null when `g` is empty, unsupported or holds a bad coordinate. */
function checkedPositions(g) {
  const depth = GEOMETRY_DEPTH[g?.type];
  if (depth === undefined) return null;
  const out = [];
  const walk = (c, d) => {
    if (d === 0) {
      if (!Array.isArray(c) || c.length < 2 || !Number.isFinite(c[0]) || !Number.isFinite(c[1]) || Math.abs(c[0]) > 180 || Math.abs(c[1]) > 90) return false;
      out.push(c); return true;
    }
    return Array.isArray(c) && c.length > 0 && c.every(child => walk(child, d - 1));
  };
  return walk(g.coordinates, depth) ? out : null;
}
export function geometryCoveredByBounds(g, bounds, marginM = PLANNING_MARGIN_M) {
  if (!Array.isArray(bounds) || bounds.length !== 4 || !bounds.every(v => typeof v === 'number' && Number.isFinite(v))) return false;
  const [west, south, east, north] = bounds;
  if (!(west < east && south < north) || west < -180 || east > 180 || south < -90 || north > 90) return false;
  if (typeof marginM !== 'number' || !Number.isFinite(marginM) || marginM < 0) return false;
  const ps = checkedPositions(g);
  if (!ps) return false;
  // Smallest metres per degree anywhere in the envelope's latitude range, so the degree padding is never too small.
  const lats = [south, north, ...(south < 0 && north > 0 ? [0] : [])];
  const kx = Math.min(...lats.map(l => mPerDeg(l)[0])), ky = Math.min(...lats.map(l => mPerDeg(l)[1]));
  if (!(kx > 1) || !(ky > 1)) return false;
  const dx = marginM / kx, dy = marginM / ky;
  if (!Number.isFinite(dx) || !Number.isFinite(dy)) return false;
  return ps.every(p => p[0] >= west + dx && p[0] <= east - dx && p[1] >= south + dy && p[1] <= north - dy);
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
// BF-closures-everywhere: the ONE verdict every output that names a place carries. `s` is a screen as the app holds it: the planner's
// (protected-areas.js `initProtectedAreas`: exportExclusions), the marks' (web/map/habitat.ts `MarkScreen`: status + boundaries), or a
// ready/pointAllowed/geometryAllowed one. A screen that is missing, not current or not loaded is `screened: false`, never "clear".
/** @typedef {{inside: boolean, name: string | null, distanceM: number | null, screened: boolean}} PlaceVerdict */
/** @param {any} s @returns {{name: string | null, geometry: any}[] | null} the closures, or null when `s` cannot say. */
function closuresOf(s) {
  if (!s) return null;
  if (Array.isArray(s.boundaries)) return s.status === 'ready' ? s.boundaries.map(b => ({name: b.name ?? null, geometry: b.geometry})) : null;
  if (typeof s.exportExclusions !== 'function') return null;
  const x = s.exportExclusions();
  return x ? x.features.map(f => ({name: f.properties?.FULLNAME || f.properties?.NAME || null, geometry: f.geometry})) : null;
}
/** Metres between two geometries, 0 when they touch, overlap or one holds the other; null when either has no coordinates. */
export function distanceM(a, b) {
  const pa = positions(a), pb = positions(b);
  if (!pa.length || !pb.length) return null;
  if (geometryIntersects(a, b)) return 0;
  const lat = (pa[0][1] + pb[0][1]) / 2, [kx, ky] = mPerDeg(lat);
  const A = projectPoints(pa, kx, ky), B = projectPoints(pb, kx, ky), SA = projectSegments(a, A, kx, ky), SB = projectSegments(b, B, kx, ky);
  // SC1407-01: a box gap is skipped only when, shrunk by `tol` (far above the few ulps segD2's rounding can move a point), it is
  // still farther than the best so far: an exact lower bound, so the minimum (and every verdict) is unchanged. Off for
  // non-finite or huge coordinates, where segD2 may give NaN and the old Math.min answer must be kept.
  const big = Math.max(maxAbs(A), maxAbs(B), maxAbs(SA), maxAbs(SB)), tol = big < 1e100 ? big * 2 ** -40 + 1e-150 : -1;
  const ab = nearest2(A, SB, Infinity, tol);
  return ab !== ab ? NaN : Math.sqrt(nearest2(B, SA, ab, tol));
}
// SC1407-01 (#1762): distanceM projects each position and edge once per pair (not once per comparison) and scans with plain
// loops (no spread into Math.min, which throws RangeError on ~10^5 positions). The projection depends on the pair's latitude.
function projectTo(p, kx, ky, out, i) { out[i] = p[0] * kx; out[i + 1] = p[1] * ky; }
function projectPoints(ps, kx, ky) {
  const out = new Float64Array(ps.length * 2);
  for (let i = 0; i < ps.length; i++) projectTo(ps[i], kx, ky, out, 2 * i);
  return out;
}
// Each segment as 8 numbers: projected ends [ax, ay, bx, by] and their box [minx, miny, maxx, maxy]. A geometry with no
// edges (Point, MultiPoint, one-position lines) gives a zero-length segment at each position, as before.
function projectSegments(g, pts, kx, ky) {
  const e = edges(g), n = e.length || pts.length / 2, out = new Float64Array(n * 8);
  let prev = null;
  for (let i = 0, j = 0; i < n; i++, j += 8) {
    if (!e.length) { out[j] = out[j + 2] = pts[2 * i]; out[j + 1] = out[j + 3] = pts[2 * i + 1]; }
    else {
      const [p, q] = e[i];
      if (p === prev && i) { out[j] = out[j - 6]; out[j + 1] = out[j - 5]; } else projectTo(p, kx, ky, out, j);
      projectTo(q, kx, ky, out, j + 2); prev = q;
    }
    out[j + 4] = Math.min(out[j], out[j + 2]); out[j + 5] = Math.min(out[j + 1], out[j + 3]);
    out[j + 6] = Math.max(out[j], out[j + 2]); out[j + 7] = Math.max(out[j + 1], out[j + 3]);
  }
  return out;
}
function maxAbs(v) { let m = 0; for (let i = 0; i < v.length; i++) { const x = Math.abs(v[i]); if (!(x <= m)) { if (x !== x) return Infinity; m = x; } } return m; }
// The smallest squared distance from any point of `pts` to any segment of `segs`, starting from `best`; NaN as soon as one is NaN.
function nearest2(pts, segs, best, tol) {
  for (let i = 0; i < pts.length; i += 2) {
    const px = pts[i], py = pts[i + 1];
    for (let j = 0; j < segs.length; j += 8) {
      if (tol >= 0) {
        const gx = Math.max(segs[j + 4] - px, px - segs[j + 6], 0) - tol, gy = Math.max(segs[j + 5] - py, py - segs[j + 7], 0) - tol;
        if ((gx > 0 ? gx * gx : 0) + (gy > 0 ? gy * gy : 0) > best) continue;
      }
      const d = segD2(px, py, segs[j], segs[j + 1], segs[j + 2], segs[j + 3]);
      if (d < best) best = d; else if (d !== d) return NaN;
    }
  }
  return best;
}
// A closure whose box is over FAR_M from the place's box is not measured (distanceM stays null when none is nearer): keeps a 500 KB boundary file cheap.
const FAR_M = 20000;
function farApart(a, b) {
  const x = bbox(a), y = bbox(b);
  if (![...x, ...y].every(Number.isFinite)) return true;
  const [kx, ky] = mPerDeg((x[1] + x[3]) / 2);
  return Math.max(x[0] - y[2], y[0] - x[2], 0) * kx > FAR_M || Math.max(x[1] - y[3], y[1] - x[3], 0) * ky > FAR_M;
}
/**
 * One place's verdict: `place` is {latitude, longitude} plus an optional `geometry` / `geometries` (a line, a leg, an area).
 * `inside` is true when any of it touches or lies in a closure; `name` and `distanceM` are those of the nearest closure
 * (distanceM 0 when inside). Outputs refuse a place whose `placeRefused(v)` is true. A place outside the screen's `coversGeometry` is `screened: false`.
 * @returns {PlaceVerdict}
 */
export function screenPlace(s, place) {
  const none = {inside: false, name: null, distanceM: null, screened: false};
  const shapes = [...(place?.geometry ? [place.geometry] : []), ...(place?.geometries ?? [])];
  if (Number.isFinite(place?.longitude) && Number.isFinite(place?.latitude)) shapes.push(pointGeometry(place.longitude, place.latitude));
  if (!shapes.length) return none;
  // SC0022-04: a screen that knows what area its boundary file covers must cover every shape (and its search halo), else the place is
  // not checked, never clear. Screens without the method (marks, legacy fixtures) keep their own contract.
  if (typeof s?.coversGeometry === 'function') {
    try { if (!shapes.every(g => s.coversGeometry(g) === true)) return none; } catch { return none; }
  }
  const closures = closuresOf(s);
  if (!closures) {
    // A screen that only answers allowed/not: current means it can say, and a "no" is inside.
    if (!s || typeof s.ready !== 'function' || !s.ready() || typeof s.pointAllowed !== 'function') return none;
    const blocked = shapes.some(g => g.type === 'Point' ? !s.pointAllowed({longitude: g.coordinates[0], latitude: g.coordinates[1]}) : !s.geometryAllowed(g));
    return {inside: blocked, name: null, distanceM: blocked ? 0 : null, screened: true};
  }
  let near = null;
  for (const c of closures) for (const g of shapes) { if (farApart(g, c.geometry)) continue; const d = distanceM(g, c.geometry); if (d !== null && (!near || d < near.d)) near = {d, name: c.name}; }
  return {inside: near?.d === 0, name: near?.name ?? null, distanceM: near ? Math.round(near.d * 10) / 10 : null, screened: true};
}
/** True when an output must not hand the place over as clear: not checked, inside a closure, or within the planning margin of one. */
export const placeRefused = v => !v.screened || v.inside || (v.distanceM !== null && v.distanceM <= PLANNING_MARGIN_M);
// SC-PERF-PROTCHECK-1: a hash of the exact boundary data a screen holds (plus the envelope it covers and the margin), so a flag the
// publisher computed against the same data can stand in for the check. The same float64 word stream and hash as
// src/skippercast/seafloor/protected_screen.py `fingerprint`; change both together (tests/unit/test_protected_screen_flags.py).
// Not a security hash: it keys a cache, and the export-time check (trip-export.js) still runs the full screen on every picked spot.
export const FINGERPRINT_VERSION = 2;
// `names` is the closure name each geometry is shown under (FULLNAME || NAME || null), in geometry order: a verdict carries it, so a
// metadata-only boundary refresh (same coordinates, new name) must change the print.
export function boundaryFingerprint(geometries, bounds, names = []) {
  const out = [FINGERPRINT_VERSION, PLANNING_MARGIN_M, ...bounds, geometries.length];
  const walk = c => {
    if (typeof c?.[0] === 'number') out.push(1, c[0], c[1]);
    else { const kids = c || []; out.push(0, kids.length); for (const child of kids) walk(child); }
  };
  geometries.forEach((g, i) => {
    const name = names[i];
    if (name === null || name === undefined) out.push(-1);
    else { out.push(name.length); for (let k = 0; k < name.length; k++) out.push(name.charCodeAt(k)); }
    let code = 0;
    for (const ch of g?.type || '') code += ch.charCodeAt(0);
    out.push(code); walk(g?.coordinates);
  });
  const view = new DataView(new ArrayBuffer(out.length * 8));
  out.forEach((v, i) => view.setFloat64(i * 8, v, true));
  let h1 = 0x811c9dc5, h2 = 0x01000193;
  for (let i = 0; i < out.length * 2; i++) {
    const w = view.getUint32(i * 4, true);
    h1 = Math.imul(h1 ^ w, 16777619) >>> 0;
    h2 = Math.imul(h2 ^ w, 2246822519) >>> 0; h2 = (h2 ^ (h2 >>> 15)) >>> 0;
  }
  const hex = n => n.toString(16).padStart(8, '0');
  return `ps${FINGERPRINT_VERSION}-${hex(h1)}${hex(h2)}-${out.length * 2}`;
}

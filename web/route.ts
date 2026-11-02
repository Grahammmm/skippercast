// Charted routes (FSC-04): a water-only route from the region's harbor to a chosen place, around land
// (headlands, Morro Rock, the breakwater), on the region's land-water product (web/land-water.ts). It is a
// planning sum on the NOAA shoreline, not a navigation route or passage plan; the shoreline is not a
// navigation boundary. It passes only where the product says water, so never over land, the 25 m edge band
// or unknown cells, and returns its length in nm, or a named reason when no route can be computed.
//
// The search grid splits each zoom-12 product cell into 4×4 sub-cells (~60 m) and joins tiles by global
// sub-cell index (x = tileX·grid·4 + col, y = tileY·grid·4 + row). A sub-cell is passable when its centre
// classifies water: a clean water (`w`) cell, or a mixed (`m`) cell whose centre the lines file calls water
// (not edge, not land). Without lines every mixed cell is blocked. Moves go to the 8 neighbours; a diagonal
// needs both orthogonal neighbours passable (no corner cutting). A move that touches a mixed cell must also
// classify water at 1/4, 1/2 and 3/4 of its length: the edge band is at least 50 m wide where a line crosses
// a move (at most ~90 m), so one of those points falls inside it. A* with the great-circle distance
// (dist/spot-ranking.js `distanceNm`) as segment cost and heuristic. The path is not smoothed: its stair
// steps overstate the length by at most ~8 % (a 22.5° course on the 8-way grid), and the length is never
// below the straight line. Erasable syntax only (Node tests import it); no DOM, no fetch, no signals.
import {distanceNm} from '../dist/spot-ranking.js';
import {linesPlace, placeOf, type LandWaterLines, type LandWaterModel} from './land-water.ts';
import {M_PER_NMI} from './units.ts';

/** Most sub-cells one search expands before it gives up (`too-far`). */
export const MAX_NODES = 400_000;
/** How far (m) a start or end may snap to the nearest passable sub-cell centre (berths and marks sit at the shore). */
export const SNAP_M = 300;

export interface RoutePoint {readonly latitude: number; readonly longitude: number}
export type RouteFailure = 'no-product' | 'lines-needed' | 'start-not-water' | 'end-not-water' | 'no-route' | 'too-far';
/**
 * A route: `nm` is the raw length (start → first centre → … → last centre → end; callers round), `points` the
 * passable sub-cell centres it runs through. Or a named failure: `lines-needed` when the lines file is not
 * loaded (null) and a mixed cell blocked the start, the end or the only passage.
 */
export type Route = {readonly ok: true; readonly nm: number; readonly points: RoutePoint[]} | {readonly ok: false; readonly reason: RouteFailure};

const SUB = 4, UNIT = 100000, EARTH_M = 6378137;
const fail = (reason: RouteFailure): Route => ({ok: false, reason});
/** A heap entry [f, push order, sub-cell id]; lower f first, then earlier push (deterministic ties). */
type Item = [number, number, number];
const less = (a: Item, b: Item): boolean => a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]);
const toLat = (fy: number, n: number): number => Math.atan(Math.sinh(Math.PI * (1 - 2 * fy / n))) * 180 / Math.PI;

/** A* over the passable sub-cells from `from` to `to` (both {latitude, longitude}); `maxNodes` is for tests. */
export function waterRoute(model: LandWaterModel | null, lines: LandWaterLines | null | false, from: RoutePoint, to: RoutePoint, maxNodes: number = MAX_NODES): Route {
  if (!model) return fail('no-product');
  const n = 2 ** model.zoom, S = model.grid * SUB, size = n * S, Q = 4 * size;
  let sawMixed = false;
  // Per-tile subsets of the lines: only segments that can reach a point in the tile (edge: within twice the
  // edge distance of it; parity: spanning its rows and not wholly west of it). linesPlace on the subset
  // gives the same answer as on the whole file, without scanning every segment.
  const near = new Map<string, LandWaterLines>();
  const subset = (all: LandWaterLines, tx: number, ty: number): LandWaterLines => {
    const key = `${tx}/${ty}`, hit = near.get(key);
    if (hit) return hit;
    const latN = toLat(ty, n), x0 = (tx / n * 360 - 180) * UNIT, x1 = ((tx + 1) / n * 360 - 180) * UNIT;
    const y1 = latN * UNIT, y0 = toLat(ty + 1, n) * UNIT;
    const mx = 2 * model.edgeM / (111320 * Math.cos(latN * Math.PI / 180)) * UNIT, my = 2 * model.edgeM / 110540 * UNIT;
    const pick = (s: Float64Array, edge: boolean): Float64Array => {
      const out: number[] = [];
      for (let i = 0; i < s.length; i += 4) {
        const ax = s[i]!, ay = s[i + 1]!, bx = s[i + 2]!, by = s[i + 3]!;
        if (Math.max(ay, by) < y0 - my || Math.min(ay, by) > y1 + my || Math.max(ax, bx) < x0 - mx) continue;
        if (edge && Math.min(ax, bx) > x1 + mx) continue;
        out.push(ax, ay, bx, by);
      }
      return Float64Array.from(out);
    };
    const part = {edge: pick(all.edge, true), parity: pick(all.parity, false)};
    near.set(key, part);
    return part;
  };
  const at = (qx: number, qy: number): RoutePoint => ({latitude: toLat(qy / Q * n, n), longitude: qx / Q * 360 - 180});
  // Whether a point in quarter-sub-cell units classifies water: 0 no, 1 in a clean water cell, 2 in a mixed one.
  // The memo keeps -1 for a mixed cell blocked because lines are null, so every lookup (cached too) flags it.
  const memo = new Map<number, number>();
  const water = (qx: number, qy: number): number => {
    const id = qy * Q + qx;
    let v = memo.get(id);
    if (v === undefined) {
      v = 0;
      if (qx >= 0 && qy >= 0 && qx < Q && qy < Q) {
        const p = at(qx, qy), cell = placeOf(model, null, p);
        if (cell.state === 'water') v = 1;
        else if (cell.state === 'unknown' && cell.reason === 'pending') {
          if (lines === null) v = -1;
          else if (lines && linesPlace(model, subset(lines, Math.floor(qx / Q * n), Math.floor(qy / Q * n)), p).state === 'water') v = 2;
        }
      }
      memo.set(id, v);
    }
    if (v < 0) sawMixed = true;
    return Math.max(v, 0);
  };
  const cellWater = (gx: number, gy: number): number => water(4 * gx + 2, 4 * gy + 2);
  const centre = (id: number): RoutePoint => at(4 * (id % size) + 2, 4 * Math.floor(id / size) + 2);
  // The nearest passable sub-cell centre within SNAP_M of p (first in row order on a tie), or -1.
  const snap = (p: RoutePoint): number => {
    if (!Number.isFinite(p?.latitude) || !Number.isFinite(p?.longitude) || Math.abs(p.latitude) > 85) return -1;
    const fx = (p.longitude + 180) / 360 * size, fy = (1 - Math.asinh(Math.tan(p.latitude * Math.PI / 180)) / Math.PI) / 2 * size;
    const r = Math.ceil(SNAP_M / (2 * Math.PI * EARTH_M * Math.cos(p.latitude * Math.PI / 180) / size)) + 1;
    let best = -1, bestM = Infinity;
    for (let gy = Math.floor(fy) - r; gy <= Math.floor(fy) + r; gy++) {
      for (let gx = Math.floor(fx) - r; gx <= Math.floor(fx) + r; gx++) {
        if (gx < 0 || gy < 0 || gx >= size || gy >= size) continue;
        const m = distanceNm(p, centre(gy * size + gx)) * M_PER_NMI;
        if (m <= SNAP_M && m < bestM && cellWater(gx, gy)) { best = gy * size + gx; bestM = m; }
      }
    }
    return best;
  };
  const start = snap(from);
  if (start < 0) return fail(sawMixed ? 'lines-needed' : 'start-not-water');
  sawMixed = false;
  const end = snap(to);
  if (end < 0) return fail(sawMixed ? 'lines-needed' : 'end-not-water');
  sawMixed = false;
  // A* over sub-cell ids (gy·size + gx); a binary heap ordered by f, then push order (deterministic ties).
  const goal = centre(end), g = new Map<number, number>([[start, 0]]), parent = new Map<number, number>(), closed = new Set<number>();
  const heap: Item[] = [];
  let seq = 0, expanded = 0;
  const push = (f: number, id: number): void => {
    const item: Item = [f, seq++, id];
    let i = heap.push(item) - 1;
    for (let up = (i - 1) >> 1; i > 0 && less(item, heap[up]!); i = up, up = (i - 1) >> 1) heap[i] = heap[up]!;
    heap[i] = item;
  };
  const pop = (): Item => {
    const top = heap[0]!, last = heap.pop()!;
    if (!heap.length) return top;
    let i = 0;
    for (;;) {
      const l = 2 * i + 1, r = l + 1;
      let m = i, mv = last;
      if (l < heap.length && less(heap[l]!, mv)) { m = l; mv = heap[l]!; }
      if (r < heap.length && less(heap[r]!, mv)) { m = r; mv = heap[r]!; }
      if (m === i) break;
      heap[i] = mv; i = m;
    }
    heap[i] = last;
    return top;
  };
  push(distanceNm(centre(start), goal), start);
  while (heap.length) {
    const [, , id] = pop();
    if (closed.has(id)) continue;
    if (id === end) {
      const points: RoutePoint[] = [];
      for (let k: number | undefined = id; k !== undefined; k = parent.get(k)) points.push(centre(k));
      points.reverse();
      const nm = distanceNm(from, points[0]!) + g.get(id)! + distanceNm(points[points.length - 1]!, to);
      // The triangle inequality keeps nm at or above the straight line; max() only absorbs float rounding.
      return {ok: true, nm: Math.max(nm, distanceNm(from, to)), points};
    }
    if (++expanded > maxNodes) return fail('too-far');
    closed.add(id);
    const gx = id % size, gy = Math.floor(id / size), here = cellWater(gx, gy), base = g.get(id)!, c = centre(id);
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const nx = gx + dx, ny = gy + dy, next = ny * size + nx;
        const there = cellWater(nx, ny);
        if ((!dx && !dy) || closed.has(next) || !there) continue;
        let mixed = here === 2 || there === 2;
        if (dx && dy) {
          const a = cellWater(nx, gy), b = cellWater(gx, ny);
          if (!a || !b) continue;
          mixed ||= a === 2 || b === 2;
        }
        if (mixed && ![1, 2, 3].every(k => water(4 * gx + 2 + k * dx, 4 * gy + 2 + k * dy))) continue;
        const cost = base + distanceNm(c, centre(next));
        if (cost < (g.get(next) ?? Infinity)) { g.set(next, cost); parent.set(next, id); push(cost + distanceNm(centre(next), goal), next); }
      }
    }
  }
  return fail(sawMixed && lines === null ? 'lines-needed' : 'no-route');
}

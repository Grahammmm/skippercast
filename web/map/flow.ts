// Streamlines for the Chart's Currents layer (FE-15, design § 9), ported from
// fish's src/map/coast.ts (`buildFlowPaths`, `animate`) onto packages/coast's
// surface field, which is imported (web/map/surface-field.js), never copied:
// seeds on a screen grid, bounded midpoint integration through the field
// interpolated from adjacent wet cells only, and a path that ends where the
// field has a gap, on land or at the edge. Arrows follow the toward-bearing;
// the dash motion is illustrative. The Chart is north up (engine.ts), so east
// is +x and north is −y on screen (Mercator keeps angles).
//
// Erasable syntax only: tests/test_flow.mjs imports this file by type stripping.
import {surfaceField, vectorReading, type SurfaceField} from './surface-field.js';
import type {CurrentField, CurrentFrame} from './frames.ts';

export interface Point {x: number; y: number}
export interface FlowPath {readonly points: readonly Point[]; readonly speed: number; readonly fast: boolean}
/** A unit direction on screen and the speed in knots at (x, y), or null where nothing may be drawn. */
export type ScreenVector = (x: number, y: number) => {x: number; y: number; speed: number} | null;

/** fish's constants: seeds every 64 px from 24 px in, 5 px midpoint steps, at most 13 each way. */
export const SEEDS = {spacing: 64, offset: 24} as const;
export const STEP_PX = 5;
export const MAX_STEPS = 13;
/** Water slower than this (m/s) has no direction worth drawing. */
export const STILL_MS = 0.012;
/** § 9: paths faster than the frame's 80th percentile cell speed draw in --flow-fast. */
export const FAST_PERCENTILE = 0.8;
/** Dash and gap in px; the dash offset moves at 10 + 12 × knots px/s (fish). */
export const DASH = [11, 43] as const;
/** At most this many seeds, so streamlines, on any screen: 64 px seeds would trace about 2,000 on a 4K display. */
export const MAX_PATHS = 300;

/** Seed spacing in px: fish's 64, widened evenly on a large screen so that at most MAX_PATHS seeds fall on it. */
export function seedSpacing(width: number, height: number): number {
  const count = (s: number): number => Math.ceil((width - s * SEEDS.offset / SEEDS.spacing) / s) * Math.ceil((height - s * SEEDS.offset / SEEDS.spacing) / s);
  let spacing = Math.max(SEEDS.spacing, Math.sqrt(width * height / MAX_PATHS));
  while (count(spacing) > MAX_PATHS) spacing *= 1.05;
  return spacing;
}

/**
 * The frame's wet cells as packages/coast's surface field (u, v in m/s). As fish, a cell
 * spacing beyond 1.6 × the native sample spacing is refused, so sparse cells never bridge a gap.
 */
export function frameField(field: CurrentField, frame: CurrentFrame): SurfaceField | null {
  const cells = frame.cells;
  if (!cells.length) return null;
  const latitude = cells.reduce((n, c) => n + c.lat, 0) / cells.length, km = field.nativeResolutionKm * field.sampleStride;
  return surfaceField(cells.map(c => ({lon: c.lon, lat: c.lat, values: [c.uMs, c.vMs]})),
    {maxStep: [km / 111 / Math.cos(latitude * Math.PI / 180) * 1.6, km / 111 * 1.6]});
}

/** The frame's 80th percentile cell speed in knots (nearest rank). */
export function fastSpeed(frame: CurrentFrame): number {
  const speeds = frame.cells.map(c => c.speedKnots).filter(Number.isFinite).sort((a, b) => a - b);
  return speeds.length ? speeds[Math.max(0, Math.ceil(FAST_PERCENTILE * speeds.length) - 1)]! : Infinity;
}

/** The field seen on screen: `unproject` maps a pixel to degrees; `blocked` marks land. */
export function screenVector(field: SurfaceField, unproject: (x: number, y: number) => {lon: number; lat: number}, blocked: (x: number, y: number) => boolean = () => false): ScreenVector {
  return (x, y) => {
    if (blocked(x, y)) return null;
    const at = unproject(x, y), v = field.sample(at.lon, at.lat);
    if (!v) return null;
    const [u = 0, n = 0] = v, m = Math.hypot(u, n);
    return m < STILL_MS ? null : {x: u / m, y: -n / m, speed: vectorReading(v).speedKnots};
  };
}

/** Streamlines over a width × height screen, at most MAX_PATHS; `fast` is the speed (knots) above which a path is fast. */
export function flowPaths(vector: ScreenVector, width: number, height: number, fast: number): FlowPath[] {
  const paths: FlowPath[] = [];
  const inside = (p: Point): boolean => p.x >= 0 && p.y >= 0 && p.x <= width && p.y <= height;
  const spacing = seedSpacing(width, height), offset = spacing * SEEDS.offset / SEEDS.spacing;
  for (let y = offset; y < height; y += spacing) {
    for (let x = offset; x < width; x += spacing) {
      const seed = vector(x, y);
      if (!seed || paths.length === MAX_PATHS) continue;
      const halves: Point[][] = [];
      for (const sign of [-1, 1]) {
        const points: Point[] = [];
        let p: Point = {x, y};
        for (let i = 0; i < MAX_STEPS; i++) {
          const a = vector(p.x, p.y);
          if (!a) break;
          const b = vector(p.x + sign * a.x * STEP_PX / 2, p.y + sign * a.y * STEP_PX / 2);
          if (!b) break;
          const next = {x: p.x + sign * b.x * STEP_PX, y: p.y + sign * b.y * STEP_PX};
          if (!inside(next) || !vector(next.x, next.y)) break;
          points.push(next);
          p = next;
        }
        halves.push(points);
      }
      const points = [...halves[0]!.reverse(), {x, y}, ...halves[1]!];
      if (points.length > 5) paths.push({points, speed: seed.speed, fast: seed.speed > fast});
    }
  }
  return paths;
}

export interface FlowColours {readonly flow: string; readonly fast: string}
type Context = Pick<CanvasRenderingContext2D, 'beginPath' | 'moveTo' | 'lineTo' | 'stroke' | 'arc' | 'fill' | 'setLineDash'
  | 'strokeStyle' | 'fillStyle' | 'globalAlpha' | 'lineWidth' | 'lineDashOffset'>;

const trace = (ctx: Context, points: readonly Point[]): void => {
  ctx.beginPath();
  points.forEach((p, i) => { if (i) ctx.lineTo(p.x, p.y); else ctx.moveTo(p.x, p.y); });
};

/** The still layer: each path faint, a head at 58% pointing along the flow, and the source cells as faint dots. */
export function drawBase(ctx: Context, paths: readonly FlowPath[], colours: FlowColours, cells: readonly Point[]): void {
  ctx.setLineDash([]);
  ctx.strokeStyle = colours.flow; ctx.fillStyle = colours.flow;
  ctx.globalAlpha = 0.28;
  for (const c of cells) { ctx.beginPath(); ctx.arc(c.x, c.y, 1.5, 0, 2 * Math.PI); ctx.fill(); }
  for (const {points} of paths) {
    ctx.globalAlpha = 0.19; ctx.lineWidth = 1;
    trace(ctx, points); ctx.stroke();
    const j = Math.floor(points.length * 0.58), p = points[j]!, q = points[Math.min(j + 1, points.length - 1)]!;
    const angle = Math.atan2(q.y - p.y, q.x - p.x), dx = Math.cos(angle), dy = Math.sin(angle);
    ctx.globalAlpha = 0.7;
    ctx.beginPath(); ctx.moveTo(p.x - dx * 5 + dy * 2.5, p.y - dy * 5 - dx * 2.5); ctx.lineTo(p.x, p.y); ctx.lineTo(p.x - dx * 5 - dy * 2.5, p.y - dy * 5 + dx * 2.5); ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

/** One frame of dashes at `seconds`; a constant `seconds` (0 under reduced motion) draws them still. */
export function drawDashes(ctx: Context, paths: readonly FlowPath[], colours: FlowColours, seconds: number): void {
  ctx.globalAlpha = 0.7; ctx.lineWidth = 1.45;
  ctx.setLineDash([...DASH]);
  paths.forEach((path, i) => {
    ctx.strokeStyle = path.fast ? colours.fast : colours.flow;
    ctx.lineDashOffset = -seconds * (10 + path.speed * 12) - i * 7;
    trace(ctx, path.points); ctx.stroke();
  });
  ctx.setLineDash([]); ctx.globalAlpha = 1;
}

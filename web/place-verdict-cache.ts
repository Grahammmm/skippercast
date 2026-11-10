// SC1407-02 (#1762 R1): a protected-area verdict depends on the place and the screen's boundary data, not on the hour,
// so a time-dock step must not run the distance screen (dist/geo-screen.js `screenPlace`) again for the same place.
// This is one small in-memory cache in front of exactly two callers: the atlas picks (web/ranking.ts `atlasScreened`)
// and the Boat run line (web/brief/run.ts `runRouteScreen`).
//
// A screen object alone is never a key: the planner screen (dist/protected-areas.js) keeps its identity while refresh()
// swaps its boundaries, and a hand-built mark screen can change status in place. A verdict is reused only while the
// screen's optional `verdictRevision()` returns the same non-empty string; its contract covers every verdict-affecting
// input the screen holds (boundary geometry, closure names and order, covered envelope and region binding, readiness,
// status and check times). A screen without it, or whose method throws or returns anything else, is screened uncached.
// The key is the region, the screen's identity, that revision and the exact place (every coordinate, no rounding).
// Only checked verdicts (`screened: true`, clear or refused) are kept, at most VERDICT_CACHE_CAP of them (least
// recently used goes first); a revision change drops that screen's entries and a region change drops them all.
// No DOM, fetch, timer or storage. Erasable syntax only: Node tests import it by type stripping.
import {effect} from '@preact/signals';
import {screenPlace, type PlaceVerdict} from '../dist/geo-screen.js';
import {region} from './state.ts';

/** The most verdicts one cache holds, atlas places and run lines together. */
export const VERDICT_CACHE_CAP = 256;

/** What screenPlace reads for one place: a point and/or a geometry and further geometries (EPSG:4326 lon/lat). */
export interface VerdictPlace {readonly latitude?: number; readonly longitude?: number; readonly geometry?: unknown; readonly geometries?: readonly unknown[]}
export type Evaluate = (screen: unknown, place: VerdictPlace) => PlaceVerdict;
export interface PlaceVerdictCache {
  /**
   * The verdict for `place` on `screen` in `regionId`: a stored copy while the screen's revision is unchanged, else the
   * evaluator's answer (stored only when checked). `tag` names the caller's place (an atlas target id, 'run').
   */
  verdict(regionId: string | null, screen: unknown, place: VerdictPlace, tag?: string): PlaceVerdict;
  clear(): void;
  readonly size: number;
}

interface ScreenMeta {readonly id: number; last: string | null; readonly keys: Set<string>}
interface Entry {readonly verdict: PlaceVerdict; readonly meta: ScreenMeta}

/** The screen's own revision for verdict reuse, or null when it cannot give one (absent, throwing, empty or not a string). */
function revisionOf(screen: unknown): string | null {
  if (!screen || typeof screen !== 'object') return null;
  try {
    const f = (screen as {verdictRevision?: unknown}).verdictRevision;
    if (typeof f !== 'function') return null;
    const r: unknown = f.call(screen);
    return typeof r === 'string' && r !== '' ? r : null;
  } catch { return null; }
}

/** A number exactly as it is (negative zero kept apart); null for anything that is not a finite number. */
const num = (n: unknown): string | null => typeof n === 'number' && Number.isFinite(n) ? (Object.is(n, -0) ? '-0' : String(n)) : null;

/** Nested coordinate arrays in order, or null when any leaf is not a finite number. */
function coords(c: unknown): string | null {
  if (!Array.isArray(c)) return num(c);
  const parts: string[] = [];
  for (const x of c) { const s = coords(x); if (s === null) return null; parts.push(s); }
  return `[${parts.join(',')}]`;
}

/** A geometry's type and every coordinate in order; null for anything else (extra members, a collection, a bad number). */
function geometryKey(g: unknown): string | null {
  if (!g || typeof g !== 'object' || Array.isArray(g)) return null;
  const o = g as Record<string, unknown>;
  if (typeof o.type !== 'string' || !Object.keys(o).every(k => k === 'type' || k === 'coordinates')) return null;
  const c = coords(o.coordinates);
  return c === null ? null : `${JSON.stringify(o.type)}${c}`;
}

/** The exact place as screenPlace reads it, or null when some of it cannot be keyed (and so is not cached). */
export function placeKey(place: VerdictPlace): string | null {
  if (!place || typeof place !== 'object') return null;
  const parts: string[] = [];
  for (const k of ['latitude', 'longitude'] as const) {
    if (place[k] === undefined) { parts.push('_'); continue; }
    const s = num(place[k]); if (s === null) return null; parts.push(s);
  }
  if (place.geometry === undefined || place.geometry === null) parts.push('_');
  else { const s = geometryKey(place.geometry); if (s === null) return null; parts.push(s); }
  if (place.geometries === undefined) parts.push('_');
  else {
    if (!Array.isArray(place.geometries)) return null;
    const gs: string[] = [];
    for (const g of place.geometries) { const s = g === null || g === undefined ? '_' : geometryKey(g); if (s === null) return null; gs.push(s); }
    parts.push(`[${gs.join(',')}]`);
  }
  return parts.join('|');
}

/** A cache of its own (tests pass an evaluator to count calls); the app uses `placeVerdicts`. */
export function placeVerdictCache(evaluate: Evaluate = screenPlace as Evaluate, cap: number = VERDICT_CACHE_CAP): PlaceVerdictCache {
  let entries = new Map<string, Entry>(), screens = new WeakMap<object, ScreenMeta>(), nextId = 0, lastRegion: string | null = null;
  const drop = (key: string): void => { const e = entries.get(key); if (e) { e.meta.keys.delete(key); entries.delete(key); } };
  /** The screen's metadata after observing `rev`: a different revision than last seen (null included) drops its entries. */
  const observe = (screen: object, rev: string | null): ScreenMeta => {
    let meta = screens.get(screen);
    if (!meta) { meta = {id: ++nextId, last: rev, keys: new Set()}; screens.set(screen, meta); }
    if (meta.last !== rev) { for (const key of [...meta.keys]) drop(key); meta.last = rev; }
    return meta;
  };
  const clear = (): void => { entries = new Map(); screens = new WeakMap(); lastRegion = null; };
  return {
    verdict(regionId, screen, place, tag = '') {
      if (regionId === null || typeof regionId !== 'string' || !screen || typeof screen !== 'object') return evaluate(screen, place);
      if (regionId !== lastRegion) { clear(); lastRegion = regionId; }
      const before = revisionOf(screen), meta = observe(screen, before), at = placeKey(place);
      if (before === null || at === null) return evaluate(screen, place);
      const key = `${meta.id}\u0000${regionId}\u0000${before}\u0000${tag}\u0000${at}`;
      const hit = entries.get(key);
      if (hit) { entries.delete(key); entries.set(key, hit); return {...hit.verdict}; }
      const v = evaluate(screen, place);
      const after = revisionOf(screen);
      // The screen changed while it answered: the answer stands for this call only.
      if (after !== before) { observe(screen, after); return v; }
      if (v && typeof v === 'object' && v.screened === true) {
        entries.set(key, {verdict: Object.freeze({...v}), meta}); meta.keys.add(key);
        while (entries.size > cap) drop(entries.keys().next().value!);
      }
      return v;
    },
    clear,
    get size() { return entries.size; },
  };
}

/** The app's one cache, for atlasScreened and runRouteScreen only; emptied on every region change the store sees. */
export const placeVerdicts = placeVerdictCache();
effect(() => { void region.value; placeVerdicts.clear(); });

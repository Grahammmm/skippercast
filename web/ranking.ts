// "Where to look" ranking (FE-34, design § 8, § 10, § 12): the top four places
// inside the profile's depth limit, from one source at a time and labelled by it,
// never with scores mixed across sources.
//
// - Terrain habitat: where packages/coast has reviewed terrain for the region
//   (web/coast-context.ts `hasCoastTerrain`) and its release loads, the reviewed
//   reef habitat in packages/coast `rankedHabitat` order (species fit, then the
//   physical terrain score), kept to the region and the profile's depth limit as
//   the terrain viewer keeps them. A pick selects `?habitat=`.
// - Survey reef atlas: elsewhere, or while the release is unavailable, the
//   atlas marks the Chart draws (web/map/habitat.ts: the target's family, the
//   run-time protected-area screen) ordered by v1's fit (dist/species-fit.js),
//   then the atlas habitat score. A pick selects `?spot=`.
//
// A place without a published depth band is never ranked, so nothing outside the
// limit can appear. Distance is from the region's harbor (dist/spot-ranking.js
// `distanceNm`). The fit badge is § 12's one wording; reasons describe terrain,
// never fish. Erasable syntax only: tests/test_ranking.mjs imports it.
import {signal} from '@preact/signals';
import {distanceNm} from '../dist/spot-ranking.js';
import {speciesFit} from '../dist/species-fit.js';
import {speciesOptions} from '../packages/coast/src/habitat-types.ts';
import {hasCoastTerrain} from './coast-context.ts';
import {PROFILE_TABLE, terrainDepthLimitFt, type Profile} from './profile.ts';
import type {HabitatFeature} from './map/coast-ranking.js';
import {fitLine, markFit, markShown, withheld, type AtlasTarget, type MarkData, type MarkScreen} from './map/habitat.ts';

/** How many places the brief lists (§ 10). */
export const TOP = 4;

export type PickKind = 'spot' | 'habitat';
/** One "where to look" row: the selection it makes, then what the row shows. */
export interface Pick {
  readonly id: string; readonly kind: PickKind; readonly name: string;
  readonly distance: string; readonly depth: string; readonly fit: string; readonly reason: string;
}
export type RankingSource = 'terrain' | 'atlas';
/** One source's list: its label and basis sentence (§ 12), its picks, and what to say when it has none. */
export interface Ranking {readonly source: RankingSource | null; readonly label: string; readonly basis: string; readonly picks: readonly Pick[]; readonly empty: string}

export interface Origin {readonly latitude: number; readonly longitude: number; readonly name: string}
/** The region's harbor (region.json `harbor`), the port distances are measured from. */
export function harborOrigin(data: MarkData | null): Origin | null {
  const h = (data?.region as {harbor?: {name?: unknown; latitude?: unknown; longitude?: unknown}} | undefined)?.harbor;
  return h && typeof h.latitude === 'number' && typeof h.longitude === 'number' && Number.isFinite(h.latitude) && Number.isFinite(h.longitude)
    ? {latitude: h.latitude, longitude: h.longitude, name: typeof h.name === 'string' ? h.name : 'the harbor'} : null;
}

const distance = (origin: Origin | null, p: {latitude: number; longitude: number}): string =>
  origin ? `${distanceNm(origin, p).toFixed(1)} nm` : '—';
const band = (lo: number, hi: number): string => `~${Math.round(lo)}–${Math.round(hi)} ft`;
const known = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);

/** The atlas marks the Chart draws for `target`, inside `limitFt` on their deepest nearby depth, best fit first. */
export function atlasPicks(data: MarkData | null, screen: MarkScreen, target: string, limitFt: number, origin: Origin | null = harborOrigin(data)): Pick[] {
  const rated = (data?.atlas?.targets ?? []).filter(t => {
    const [lo, hi] = t.neighborhood_depth_ft ?? [];
    return markShown(t, target) && known(lo) && known(hi) && hi <= limitFt && !withheld(t, screen);
  }).map(t => ({t, fit: markFit(t, target), score: (t as AtlasTarget & {habitat_score?: number}).habitat_score ?? 0}));
  rated.sort((a, b) => (b.fit?.n ?? 0) - (a.fit?.n ?? 0) || b.score - a.score || a.t.id.localeCompare(b.t.id));
  return rated.slice(0, TOP).map(({t, fit}) => {
    const [lo, hi] = t.neighborhood_depth_ft as [number, number];
    const reason = speciesFit(t, target === 'rockfish' || target === 'rockfish-reef' || target === 'gopher-rockfish' ? 'rockfish' : 'lingcod')?.reason;
    return {id: t.id, kind: 'spot', name: t.label, distance: distance(origin, t), depth: band(lo, hi),
      fit: fit?.line ?? 'Habitat fit unrated for this target', reason: reason ?? t.terrain_interpretation ?? 'Surveyed reef terrain.'};
  });
}

/** The coast species' label as § 12 writes it ("lingcod", "reef rockfish"); null for the all-reef option. */
const speciesLabel = (coast: string): string | null => {
  const o = speciesOptions.find(s => s.id === coast);
  return o && o.field ? o.label.toLowerCase() : null;
};

/**
 * The region's reviewed terrain habitat, already in packages/coast `rankedHabitat` order for the coast species,
 * inside `limitFt` on its deepest nominal depth, as picks.
 */
export function habitatPicks(ranked: readonly HabitatFeature[], region: string, coast: string, limitFt: number, origin: Origin | null): Pick[] {
  const field = speciesOptions.find(s => s.id === coast)?.field ?? null, label = speciesLabel(coast);
  return ranked.filter(f => {
    const p = f.properties;
    return p.region === region && known(p.depth_min_ft) && known(p.depth_max_ft) && p.depth_max_ft <= limitFt && known(p.waypoint_latitude) && known(p.waypoint_longitude);
  }).slice(0, TOP).map(f => {
    const p = f.properties, id = String(f.id ?? p.id), n = field ? Number(p[field]) : NaN;
    return {id, kind: 'habitat', name: `Reef habitat ${id}`, distance: distance(origin, {latitude: p.waypoint_latitude, longitude: p.waypoint_longitude}),
      depth: band(p.depth_min_ft, p.depth_max_ft), fit: label && n >= 1 && n <= 3 ? fitLine(label, n) : 'Screened reef habitat',
      reason: `Terrain score ${p.terrain_score}/100${p.terrain_grade ? ` · grade ${p.terrain_grade}` : ''}.`};
  });
}

/** The reviewed terrain release as the brief holds it: not asked for, loading, loaded, or unavailable. */
export type TerrainHabitat =
  | {readonly state: 'idle' | 'loading' | 'unavailable'}
  | {readonly state: 'ready'; readonly features: readonly HabitatFeature[]; readonly expiresAt: number; readonly rank: (f: readonly HabitatFeature[], field: string | null, now?: number) => HabitatFeature[]};
export const terrainHabitat = signal<TerrainHabitat>({state: 'idle'});

type Loader = () => Promise<typeof import('./map/coast-ranking.js')>;
/** Load the reviewed release once (it is coast-wide); a failure leaves the atlas ranking in place. */
export async function loadTerrainHabitat(loader: Loader = () => import('./map/coast-ranking.js')): Promise<void> {
  if (terrainHabitat.peek().state !== 'idle') return;
  terrainHabitat.value = {state: 'loading'};
  try {
    const m = await loader(), {features, expiresAt} = await m.loadReviewedHabitat();
    terrainHabitat.value = Array.isArray(features) && Number.isFinite(expiresAt) ? {state: 'ready', features, expiresAt, rank: m.rankedHabitat} : {state: 'unavailable'};
  } catch { terrainHabitat.value = {state: 'unavailable'}; }
}

export interface RankingInputs {
  readonly region: string | null; readonly profile: Profile; readonly target: string; readonly coast: string;
  readonly data: MarkData | null; readonly screen: MarkScreen; readonly terrain: TerrainHabitat; readonly now: number;
}

const ATLAS_BASIS = 'Survey reef atlas marks that pass the current protected-area check, ordered by habitat fit, then the atlas habitat score. '
  + 'Depths are the nominal range near each mark in the survey\'s own vertical reference; distances are straight-line from';
const TERRAIN_BASIS = 'Reviewed coastal terrain habitat, screened against protected areas, ordered by species fit, then the physical terrain score. '
  + 'Depths are nominal; distances are straight-line from';

/** The list the brief shows for these inputs: terrain habitat where it binds and loads, else the atlas; one source, never both. */
export function ranking(i: RankingInputs): Ranking {
  const limit = terrainDepthLimitFt(i.profile);
  const origin = harborOrigin(i.data), from = ` ${origin?.name ?? 'the harbor'}. A ranked place is a place to look; fish presence is unverified.`;
  const within = `within ${limit} ft`;
  if (PROFILE_TABLE[i.profile].whereToLook === 'shore-runs')
    return {source: null, label: '', basis: '', picks: [], empty: 'Shore runs and their review status show on the Chart.'};
  const t = i.terrain, field = speciesOptions.find(s => s.id === i.coast);
  if (i.region && hasCoastTerrain(i.region) && t.state === 'ready' && field && field.id !== 'halibut' && field.id !== 'surfperch' && t.expiresAt > i.now) {
    const picks = habitatPicks(t.rank(t.features, field.field, i.now), i.region, i.coast, limit, origin);
    return {source: 'terrain', label: 'Reviewed terrain habitat', basis: TERRAIN_BASIS + from, picks, empty: `No reviewed terrain habitat ${within} for this target.`};
  }
  if (!i.data) return {source: null, label: '', basis: '', picks: [], empty: 'Ranked places load with the map.'};
  const picks = atlasPicks(i.data, i.screen, i.target, limit, origin);
  const empty = i.screen.status !== 'ready' ? i.screen.note : `No surveyed reef marks ${within} for this target.`;
  return {source: 'atlas', label: 'Survey reef atlas', basis: ATLAS_BASIS + from, picks, empty};
}

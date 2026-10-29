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
// `distanceNm`). With a range to consider (web/reach.ts, #644), only places
// whose straight-line distance is inside it are ranked; without a harbor
// position the range cannot be measured and is not applied. The fit badge is § 12's one wording; reasons describe terrain,
// never fish.
//
// CI6-01B: every place that passes those filters is then checked for land or water
// (web/land-water.ts, docs/land-water-method.md). Only water is ranked; land and
// unknown places are withheld and counted in the basis, and without a land/water
// check (no product for the region, or one not loaded yet) nothing is ranked.
// Erasable syntax only: tests/test_ranking.mjs imports it.
import {signal} from '@preact/signals';
import {distanceNm} from '../dist/spot-ranking.js';
import {speciesFit} from '../dist/species-fit.js';
import {speciesOptions} from '../packages/coast/src/habitat-types.ts';
import {hasCoastTerrain} from './coast-context.ts';
import {yardsFromShore} from './shore-distance.ts';
import {PROFILE_TABLE, terrainDepthLimitFt, type Profile} from './profile.ts';
import {LAND_WATER_BASIS, NO_LAND_WATER, keepWater, withheldNote, type Place} from './land-water.ts';
import type {HabitatFeature} from './map/coast-ranking.js';
import {CHECKING, fitLine, markFit, markShown, withheld, type AtlasTarget, type MarkData, type MarkScreen} from './map/habitat.ts';

/** How many places the brief lists (§ 10). */
export const TOP = 4;

export type PickKind = 'spot' | 'habitat';
/** One "where to look" row: the selection it makes, then what the row shows. */
export interface Pick {
  readonly id: string; readonly kind: PickKind; readonly name: string;
  readonly distance: string; readonly depth: string; readonly fit: string; readonly reason: string;
  /** Straight-line nautical miles from the harbor (the Boat brief's run time); null without a harbor. */
  readonly nm: number | null;
}
export type RankingSource = 'terrain' | 'atlas';
/** One source's list: its label and basis sentence (§ 12), its picks, and what to say when it has none. */
export interface Ranking {readonly source: RankingSource | null; readonly label: string; readonly basis: string; readonly picks: readonly Pick[]; readonly empty: string;
  /** The harbor the picks' distances run from; absent before the region's marks load. */
  readonly harbor?: string;
  /** The range to consider the picks were kept inside (nm, one way); absent when none applied. */
  readonly reach?: number;
  /** Places that passed every other filter but are not confirmed water (web/land-water.ts), withheld. */
  readonly withheld?: number;
  /** Some place waits on the land/water lines file; the list shows once it loads. */
  readonly pending?: boolean}

/**
 * Where a run distance starts: a named harbor or launch from published data, never the device's position.
 * "Use my location" (web/ports.ts `locatePort`) only suggests the nearest listed port; tests/test_ranking.mjs
 * fails if any other web/ file reads the device position.
 */
export interface Origin {readonly latitude: number; readonly longitude: number; readonly name: string}
/** The region's harbor (region.json `harbor`), the port distances are measured from. */
export function harborOrigin(data: MarkData | null): Origin | null {
  const h = (data?.region as {harbor?: {name?: unknown; latitude?: unknown; longitude?: unknown}} | undefined)?.harbor;
  return h && typeof h.latitude === 'number' && typeof h.longitude === 'number' && Number.isFinite(h.latitude) && Number.isFinite(h.longitude)
    ? {latitude: h.latitude, longitude: h.longitude, name: typeof h.name === 'string' ? h.name : 'the harbor'} : null;
}

const miles = (origin: Origin | null, p: {latitude: number; longitude: number}): number | null => origin ? distanceNm(origin, p) : null;
const distance = (nm: number | null): string => nm === null ? '—' : `${nm.toFixed(1)} nm`;
const band = (lo: number, hi: number): string => `~${Math.round(lo)}–${Math.round(hi)} ft`;
const known = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
/** Inside the range: always without one; with one, only a measured distance at or under it. */
const inside = (nm: number | null, maxNm: number | null): boolean => maxNm === null || (nm !== null && nm <= maxNm);

/** What keeps a place in the list beyond depth and the screen (#644): the range from the origin, and Spear's swim from shore. */
export interface Keep {
  readonly maxNm: number | null;
  /** Spear from shore: the overview shoreline and the farthest swim (yards). */
  readonly shore: {readonly lines: readonly (readonly number[])[][]; readonly maxYd: number} | null;
}
export const KEEP_ALL: Keep = Object.freeze({maxNm: null, shore: null});
/** Yards from shore, rounded to 25 for display, when the shore filter applies; else null. */
const swim = (keep: Keep, p: {latitude: number; longitude: number}): number | null => keep.shore ? yardsFromShore(p, keep.shore.lines) : null;
const kept = (keep: Keep, nm: number | null, yd: number | null): boolean => inside(nm, keep.maxNm) && (!keep.shore || (yd !== null && yd <= keep.shore.maxYd));
const swimText = (yd: number): string => `~${Math.max(25, Math.round(yd / 25) * 25)} yd from shore`;

/** Picks after the land/water check: the water ones, and how many others were withheld or wait on the lines file. */
export interface Screened {readonly picks: Pick[]; readonly withheld: number; readonly pending: boolean}

/** The atlas marks the Chart draws for `target`, inside `limitFt` on their deepest nearby depth, on water, best fit first. */
export function atlasPicks(data: MarkData | null, screen: MarkScreen, target: string, limitFt: number, origin: Origin | null = harborOrigin(data), keep: Keep = KEEP_ALL, place: Place = NO_LAND_WATER): Pick[] {
  return atlasScreened(data, screen, target, limitFt, origin, keep, place).picks;
}

function atlasScreened(data: MarkData | null, screen: MarkScreen, target: string, limitFt: number, origin: Origin | null, keep: Keep, place: Place): Screened {
  const rated = (data?.atlas?.targets ?? []).filter(t => {
    const [lo, hi] = t.neighborhood_depth_ft ?? [];
    return markShown(t, target) && known(lo) && known(hi) && hi <= limitFt && !withheld(t, screen) && kept(keep, miles(origin, t), swim(keep, t));
  }).map(t => ({t, fit: markFit(t, target), score: (t as AtlasTarget & {habitat_score?: number}).habitat_score ?? 0}));
  rated.sort((a, b) => (b.fit?.n ?? 0) - (a.fit?.n ?? 0) || b.score - a.score || a.t.id.localeCompare(b.t.id));
  const {kept: onWater, withheld: held, pending} = keepWater(rated.map(r => ({...r, latitude: r.t.latitude, longitude: r.t.longitude})), place);
  return {withheld: held, pending, picks: onWater.slice(0, TOP).map(({t, fit}) => {
    const [lo, hi] = t.neighborhood_depth_ft as [number, number];
    // Only the two supported species screens can supply a target-specific reason.
    const species = target === 'lingcod' ? 'lingcod'
      : target === 'rockfish' || target === 'rockfish-reef' || target === 'gopher-rockfish' ? 'rockfish' : null;
    const reason = species ? speciesFit(t, species)?.reason : null;
    const nm = miles(origin, t), yd = swim(keep, t);
    return {id: t.id, kind: 'spot', name: t.label, distance: yd === null ? distance(nm) : swimText(yd), nm, depth: band(lo, hi),
      fit: fit?.line ?? 'Habitat fit unrated for this target', reason: reason ?? t.terrain_interpretation ?? 'Surveyed reef terrain.'};
  })};
}

/** The coast species' label as § 12 writes it ("lingcod", "reef rockfish"); null for the all-reef option. */
const speciesLabel = (coast: string): string | null => {
  const o = speciesOptions.find(s => s.id === coast);
  return o && o.field ? o.label.toLowerCase() : null;
};

/**
 * The region's reviewed terrain habitat, already in packages/coast `rankedHabitat` order for the coast species,
 * inside `limitFt` on its deepest nominal depth, admitted by the current waypoint screen and on water, as picks.
 */
export function habitatPicks(ranked: readonly HabitatFeature[], screen: MarkScreen, region: string, coast: string, limitFt: number, origin: Origin | null, keep: Keep = KEEP_ALL, place: Place = NO_LAND_WATER): Pick[] {
  return habitatScreened(ranked, screen, region, coast, limitFt, origin, keep, place).picks;
}

function habitatScreened(ranked: readonly HabitatFeature[], screen: MarkScreen, region: string, coast: string, limitFt: number, origin: Origin | null, keep: Keep, place: Place): Screened {
  const field = speciesOptions.find(s => s.id === coast)?.field ?? null, label = speciesLabel(coast);
  const admitted = ranked.filter(f => {
    const p = f.properties;
    return p.region === region && known(p.depth_min_ft) && known(p.depth_max_ft) && p.depth_max_ft <= limitFt && known(p.waypoint_latitude) && known(p.waypoint_longitude)
      && !withheld({latitude: p.waypoint_latitude, longitude: p.waypoint_longitude}, screen)
      && kept(keep, miles(origin, {latitude: p.waypoint_latitude, longitude: p.waypoint_longitude}), swim(keep, {latitude: p.waypoint_latitude, longitude: p.waypoint_longitude}));
  });
  const {kept: onWater, withheld: held, pending} = keepWater(admitted.map(f => ({f, latitude: f.properties.waypoint_latitude, longitude: f.properties.waypoint_longitude})), place);
  return {withheld: held, pending, picks: onWater.slice(0, TOP).map(({f}) => {
    const p = f.properties, id = String(f.id ?? p.id), n = field ? Number(p[field]) : NaN;
    const at = {latitude: p.waypoint_latitude, longitude: p.waypoint_longitude}, nm = miles(origin, at), yd = swim(keep, at);
    return {id, kind: 'habitat', name: `Reef habitat ${id}`, distance: yd === null ? distance(nm) : swimText(yd), nm,
      depth: band(p.depth_min_ft, p.depth_max_ft), fit: label && n >= 1 && n <= 3 ? fitLine(label, n) : 'Screened reef habitat',
      reason: `Terrain score ${p.terrain_score}/100${p.terrain_grade ? ` · grade ${p.terrain_grade}` : ''}.`};
  })};
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
  /** The range to consider (nm, one way, web/reach.ts); null or absent ranks the whole region. */
  readonly reachNm?: number | null;
  /** Where distances run from instead of the harbor (Kayak's chosen launch, web/launches.ts); null or absent: the harbor. */
  readonly origin?: Origin | null;
  /**
   * Spear from shore (web/reach.ts `shoreSwimLimit`): the farthest swim in yards, and the region's overview shoreline
   * (web/shore-distance.ts); lines null while loading or unavailable, so the limit is not applied and the basis says so.
   */
  readonly shore?: {readonly maxYd: number; readonly lines: readonly (readonly number[])[][] | null} | null;
  /** The region's land/water check (web/land-water.ts `placeFor`); absent, every place is unknown and withheld. */
  readonly place?: Place;
}

const ATLAS_BASIS = 'Survey reef atlas marks that pass the current protected-area check, ordered by habitat fit, then the atlas habitat score. '
  + 'Depths are the nominal range near each mark in the survey\'s own vertical reference; distances are straight-line from';
const TERRAIN_BASIS = 'Reviewed coastal terrain habitat that passes the current protected-area and closure check, ordered by species fit, then the physical terrain score. '
  + 'Depths are nominal; distances are straight-line from';

/** The list the brief shows for these inputs: terrain habitat where it binds and loads, else the atlas; one source, never both. */
export function ranking(i: RankingInputs): Ranking {
  const limit = terrainDepthLimitFt(i.profile);
  const origin = i.origin ?? harborOrigin(i.data), harbor = origin?.name ?? 'the harbor';
  // A range applies only where it can be measured: from a harbor or launch position.
  const reach = origin && known(i.reachNm) && i.reachNm > 0 ? i.reachNm : null;
  // A swim limit applies only once the shoreline has loaded; until then the basis says it is not applied.
  const shore = i.shore && i.shore.lines ? {lines: i.shore.lines, maxYd: i.shore.maxYd} : null;
  const keep: Keep = {maxNm: reach, shore};
  const ranged = reach === null ? '' : ` Only places within your ${Number(reach.toFixed(1))} nm range are listed.`;
  const swum = shore ? ` Only places within ${shore.maxYd} yd of the mapped shoreline are listed, measured straight to the simplified overview line, so the distance is approximate and not a swim route.`
    : i.shore ? ' Your swim limit is not applied: the shoreline to measure from has not loaded, or this region has none.' : '';
  // Without a harbor or launch position no distance is measured, and the basis says so rather than naming one.
  const from = `${origin ? ` ${harbor}.` : ' the region\'s harbor, which has no published position here, so no distance is shown.'}${ranged}${swum} ${LAND_WATER_BASIS} A ranked place is a place to look; fish presence is unverified.`;
  const place = i.place ?? NO_LAND_WATER;
  /** The basis, the list and the empty line once the land/water check has run. */
  const checked = (s: Screened, basis: string, empty: string) => ({
    basis: s.withheld ? `${basis} ${withheldNote(s.withheld)}` : basis,
    picks: s.pending ? [] : s.picks,
    empty: s.pending ? 'Checking land and water for these places…' : s.withheld && !s.picks.length ? `${withheldNote(s.withheld)} ${empty}` : empty,
    ...(s.withheld ? {withheld: s.withheld} : {}), ...(s.pending ? {pending: true} : {}),
  });
  const within = `within ${limit} ft${reach === null ? '' : ` and ${Number(reach.toFixed(1))} nm of ${harbor}`}${shore ? ` and ${shore.maxYd} yd of shore` : ''}`;
  const extra = {...(origin ? {harbor: origin.name} : {}), ...(reach === null ? {} : {reach})};
  if (PROFILE_TABLE[i.profile].whereToLook === 'shore-runs')
    return {source: null, label: '', basis: '', picks: [], empty: 'Shore runs and their review status show on the Chart.'};
  const t = i.terrain, field = speciesOptions.find(s => s.id === i.coast);
  if (i.region && hasCoastTerrain(i.region) && t.state === 'ready' && field && field.id !== 'halibut' && field.id !== 'surfperch' && t.expiresAt > i.now) {
    const screen = i.screen ?? CHECKING;
    const s = habitatScreened(t.rank(t.features, field.field, i.now), screen, i.region, i.coast, limit, origin, keep, place);
    const empty = screen.status !== 'ready' ? screen.note : s.withheld ? `No other reviewed terrain habitat ${within} for this target.`
      : `No reviewed terrain habitat passes the current protected-area and closure check ${within} for this target.`;
    return {source: 'terrain', label: 'Reviewed terrain habitat', ...checked(s, TERRAIN_BASIS + from, empty), ...extra};
  }
  if (!i.data) return {source: null, label: '', basis: '', picks: [], empty: 'Ranked places load with the map.'};
  const s = atlasScreened(i.data, i.screen, i.target, limit, origin, keep, place);
  const empty = i.screen.status !== 'ready' ? i.screen.note : s.withheld ? `No other surveyed reef marks ${within} for this target.`
    : `No surveyed reef marks ${within} for this target.`;
  return {source: 'atlas', label: 'Survey reef atlas', ...checked(s, ATLAS_BASIS + from, empty), ...extra};
}

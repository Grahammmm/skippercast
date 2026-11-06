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
//
// SCJ-2a: for a species the trip planner ranks, the reef list is the planner's answer (dist/spot-ranking.js `bestSpots`
// over the seafloor publication `loadReefTrip` reads): same places, same depths for equal filters; a pick moves the Chart.
// While it is expired or unavailable, or for another coast species, the lists above apply.
// SCJ-2b: its places pass the planner's own protected-area screen (web/trip.ts `protectedScreen`, the one export screens
// through); until that screen has loaded the list shows the checking line, and a screen not current withholds every place.
import {signal} from '@preact/signals';
import {bestSpots, distanceNm} from '../dist/spot-ranking.js';
import {screenPlace, type PlaceVerdict} from '../dist/geo-screen.js';
import {loadReefTrip} from '../dist/reef-trip-data.js';
import {loadManifest, manifestState} from '../dist/seafloor-data.js';
import {speciesFit} from '../dist/species-fit.js';
import {speciesOptions} from '../packages/coast/src/habitat-types.ts';
import {hasCoastTerrain} from './coast-context.ts';
import {yardsFromShore} from './shore-distance.ts';
import {PROFILE_TABLE, terrainDepthLimitFt, type Profile} from './profile.ts';
import {LAND_WATER_BASIS, NO_LAND_WATER, keepWater, withheldNote, type LandWaterLines, type LandWaterModel, type Place} from './land-water.ts';
import {waterRoute, type Route, type RouteFailure, type RoutePoint} from './route.ts';
import type {HabitatFeature} from './map/coast-ranking.js';
import {CHECKING, SCREEN_NOTES, fitLine, markAreas, markFit, markFitCopy, markShown, withheld, type AtlasTarget, type MarkData, type MarkScreen} from './map/habitat.ts';
import {cp, type CopyVar, type MarkCopyPart} from './mark-copy.ts';
import type {StringId} from './i18n.ts';

/** How many places the brief lists (§ 10). */
export const TOP = 4;

export type PickKind = 'spot' | 'habitat' | 'reef';
/**
 * SC1137-05: display-only catalogue parts for the words this file writes (never for a published name or sentence). A Spanish page resolves
 * them at render (web/brief/ranking-copy.ts); English, and any pick or list built without them, shows the plain fields below.
 */
type Parts = readonly MarkCopyPart[];
export interface PickCopy {readonly name?: Parts; readonly fit?: Parts; readonly reason?: Parts; readonly distance?: Parts}
export interface RankingCopy {readonly label?: Parts; readonly about?: Parts; readonly basis?: Parts; readonly empty?: Parts}
type RankKey = `source.${RankingSource}` | `about.${RankingSource}` | `basis.${RankingSource}`
  | 'basis.from' | 'basis.noOrigin' | 'basis.ranged' | 'basis.swum' | 'basis.swimOff' | 'basis.water' | 'basis.fish' | 'basis.homePort' | 'withheld.one' | 'withheld.many'
  | 'within' | 'within.reach' | 'within.shore'
  | 'empty.pending' | 'empty.missing' | 'empty.shore' | 'empty.homePort' | 'empty.loadingPublication' | 'empty.mapLoading' | 'empty.screenNotCurrent'
  | `empty.${RankingSource}.${'other' | 'none'}`
  | 'name.reefHabitat' | 'fit.screened' | `species.${'lingcod' | 'rockfish-reef' | 'gopher-rockfish' | 'cabezon-shallow-reef'}` | 'swim'
  | 'reason.terrain' | 'reason.terrainGraded' | 'reason.surveyed' | 'reason.relief' | 'reason.nearby';
const rp = (key: RankKey, vars?: Readonly<Record<string, CopyVar>>): MarkCopyPart => cp(`ranking.${key}` as StringId, vars);
/** One "where to look" row: the selection it makes, then what the row shows. */
export interface Pick {
  readonly id: string; readonly kind: PickKind; readonly name: string;
  readonly distance: string; readonly depth: string; readonly fit: string; readonly reason: string;
  /** Straight-line nautical miles from the harbor (the Boat brief's run time); null without a harbor. */
  readonly nm: number | null;
  /** Where the pick is: a 'reef' row moves the Chart there, and it is the Boat run's destination (web/brief/Run.tsx). */
  readonly at: {readonly latitude: number; readonly longitude: number};
  /** BF-closures-everywhere: the protected-area verdict for this place (dist/geo-screen.js `screenPlace`); a pick never exists without one. */
  readonly screen: PlaceVerdict;
  readonly copy?: PickCopy;
}
export type RankingSource = 'terrain' | 'atlas' | 'publication';
/** One source's list: its label and basis sentence (§ 12), its picks, and what to say when it has none. */
export interface Ranking {readonly source: RankingSource | null; readonly label: string; readonly basis: string; readonly picks: readonly Pick[]; readonly empty: string;
  /** The harbor the picks' distances run from; absent before the region's marks load. */
  readonly harbor?: string;
  /** The position the picks' distances run from (the Boat run's start); absent with `harbor`. */
  readonly origin?: {readonly latitude: number; readonly longitude: number};
  /** The range to consider the picks were kept inside (nm, one way); absent when none applied. */
  readonly reach?: number;
  /** Places that passed every other filter but are not confirmed water (web/land-water.ts), withheld. */
  readonly withheld?: number;
  /** Some place waits on the land/water lines file; the list shows once it loads. */
  readonly pending?: boolean;
  /** SC1137-05: the label, basis and empty line as catalogue parts for a Spanish page; absent, the plain fields are shown. */
  readonly copy?: RankingCopy}

/**
 * Where a run distance starts: a named harbor or launch from published data, never the device's position.
 * "Use my location" (web/ports.ts `locatePort`) only suggests the nearest listed port; tests/test_ranking.mjs
 * fails if any other web/ file reads the device position.
 */
export interface Origin {readonly latitude: number; readonly longitude: number; readonly name: string;
  /** The harbor is published without a name, so `name` is the generated fallback (a Spanish page says it in Spanish). */ readonly unnamed?: true}
/** The region's harbor (region.json `harbor`), the port distances are measured from. */
export function harborOrigin(data: MarkData | null): Origin | null {
  const h = (data?.region as {harbor?: {name?: unknown; latitude?: unknown; longitude?: unknown}} | undefined)?.harbor;
  return h && typeof h.latitude === 'number' && typeof h.longitude === 'number' && Number.isFinite(h.latitude) && Number.isFinite(h.longitude)
    ? {latitude: h.latitude, longitude: h.longitude, name: typeof h.name === 'string' ? h.name : 'the harbor', ...(typeof h.name === 'string' ? {} : {unnamed: true as const})} : null;
}

const miles = (origin: Origin | null, p: {latitude: number; longitude: number}): number | null => origin ? distanceNm(origin, p) : null;
const distance = (nm: number | null): string => nm === null ? '—' : `${nm.toFixed(1)} nm`;
const band = (lo: number, hi: number): string => `~${Math.round(lo)}–${Math.round(hi)} ft`;
const known = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
/** RF1050-16: a depth band enters a list only if it is finite, nonnegative, ordered and wholly inside the limit; nothing is coerced, swapped or repaired. */
const validDepthBand = (lo: unknown, hi: unknown, limitFt: number): boolean => known(lo) && known(hi) && known(limitFt) && limitFt > 0 && lo >= 0 && lo <= hi && hi <= limitFt;
/** The same test for a published `[lo, hi]` pair: exactly two entries. */
const validDepthPair = (pair: unknown, limitFt: number): boolean => Array.isArray(pair) && pair.length === 2 && validDepthBand(pair[0], pair[1], limitFt);
/** Inside the range: always without one; with one, only a measured distance at or under it. */
const inside = (nm: number | null, maxNm: number | null): boolean => maxNm === null || (nm !== null && nm <= maxNm);

/** What keeps a place in the list beyond depth and the screen (#644): the range from the origin, and Spear's swim from shore. */
export interface Keep {
  readonly maxNm: number | null;
  /** Spear from shore: the overview shoreline and the farthest swim (yards). */
  readonly shore: {readonly lines: readonly (readonly number[])[][]; readonly maxYd: number} | null;
  /** How many picks a list keeps; absent, TOP (the Boat brief asks for more, so a water route can refill a dropped pick). */ readonly top?: number;
}
export const KEEP_ALL: Keep = Object.freeze({maxNm: null, shore: null});
/** Yards from shore, rounded to 25 for display, when the shore filter applies; else null. */
const swim = (keep: Keep, p: {latitude: number; longitude: number}): number | null => keep.shore ? yardsFromShore(p, keep.shore.lines) : null;
const kept = (keep: Keep, nm: number | null, yd: number | null): boolean => inside(nm, keep.maxNm) && (!keep.shore || (yd !== null && yd <= keep.shore.maxYd));
const swimYd = (yd: number): number => Math.max(25, Math.round(yd / 25) * 25);
const swimText = (yd: number): string => `~${swimYd(yd)} yd from shore`;
const swimCopy = (yd: number | null): Pick['copy'] => yd === null ? {} : {distance: [rp('swim', {yd: swimYd(yd)})]};
/** The coast species' name as a catalogue part (the four with a fit field), else null. */
const speciesPart = (coast: string): MarkCopyPart | null => speciesOptions.some(s => s.id === coast && s.field) ? rp(`species.${coast}` as RankKey) : null;
/** The generated relief or nearby-habitat reason of dist/species-fit.js as parts, only where the numbers rebuild the very same English sentence. */
function speciesReasonCopy(t: AtlasTarget, species: 'lingcod' | 'rockfish', reason: string): Parts | undefined {
  const m = t.metrics, pct = Math.round(Number(m?.rugose_or_bedrock_fraction_210m) * 100);
  const v = species === 'lingcod' ? Number(m?.relief_210m_m).toFixed(1) : Number(m?.rough_habitat_within_250m_ha).toFixed(1);
  return species === 'lingcod' ? (`${v} m local relief; ${pct}% mapped rough cover.` === reason ? [rp('reason.relief', {m: v, pct})] : undefined)
    : (`${v} ha nearby rough habitat; ${pct}% mapped rough cover.` === reason ? [rp('reason.nearby', {ha: v, pct})] : undefined);
}

/** Picks after the land/water check: the water ones, and how many others were withheld or wait on the lines file. */
export interface Screened {readonly picks: Pick[]; readonly withheld: number; readonly pending: boolean}

/** The atlas marks the Chart draws for `target`, inside `limitFt` on their deepest nearby depth, on water, best fit first. */
export function atlasPicks(data: MarkData | null, screen: MarkScreen, target: string, limitFt: number, origin: Origin | null = harborOrigin(data), keep: Keep = KEEP_ALL, place: Place = NO_LAND_WATER): Pick[] {
  return atlasScreened(data, screen, target, limitFt, origin, keep, place).picks;
}

function atlasScreened(data: MarkData | null, screen: MarkScreen, target: string, limitFt: number, origin: Origin | null, keep: Keep, place: Place): Screened {
  const rated = (data?.atlas?.targets ?? []).filter(t => {
    return markShown(t, target) && validDepthPair(t.neighborhood_depth_ft, limitFt) && !withheld(t, screen, markAreas(t, data?.atlas)) && kept(keep, miles(origin, t), swim(keep, t));
  }).map(t => ({t, fit: markFit(t, target), score: (t as AtlasTarget & {habitat_score?: number}).habitat_score ?? 0}));
  rated.sort((a, b) => (b.fit?.n ?? 0) - (a.fit?.n ?? 0) || b.score - a.score || a.t.id.localeCompare(b.t.id));
  const {kept: onWater, withheld: held, pending} = keepWater(rated.map(r => ({...r, latitude: r.t.latitude, longitude: r.t.longitude})), place);
  return {withheld: held, pending, picks: onWater.slice(0, keep.top ?? TOP).map(({t, fit}) => {
    const [lo, hi] = t.neighborhood_depth_ft as [number, number];
    // Only the two supported species screens can supply a target-specific reason.
    const species = target === 'lingcod' ? 'lingcod'
      : target === 'rockfish' || target === 'rockfish-reef' || target === 'gopher-rockfish' ? 'rockfish' : null;
    const reason = species ? speciesFit(t, species)?.reason : null;
    const nm = miles(origin, t), yd = swim(keep, t);
    // SC1137-05: the generated words as parts; a published terrain_interpretation is never given any.
    const reasonParts = reason && species ? speciesReasonCopy(t, species, reason) : reason ? undefined : t.terrain_interpretation === undefined ? [rp('reason.surveyed')] : undefined;
    return {id: t.id, kind: 'spot', name: t.label, distance: yd === null ? distance(nm) : swimText(yd), nm, at: {latitude: t.latitude, longitude: t.longitude}, depth: band(lo, hi),
      screen: screenPlace(screen, {latitude: t.latitude, longitude: t.longitude, geometries: markAreas(t, data?.atlas)}),
      fit: fit?.line ?? 'Habitat fit unrated for this target', reason: reason ?? t.terrain_interpretation ?? 'Surveyed reef terrain.',
      copy: {...swimCopy(yd), fit: fit ? markFitCopy(target, fit.n) : [cp('mark.layer.habitat.fitUnrated')], ...(reasonParts ? {reason: reasonParts} : {})}};
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
    return p.region === region && validDepthBand(p.depth_min_ft, p.depth_max_ft, limitFt) && known(p.waypoint_latitude) && known(p.waypoint_longitude)
      && !withheld({latitude: p.waypoint_latitude, longitude: p.waypoint_longitude, geometry: f.geometry}, screen)
      && kept(keep, miles(origin, {latitude: p.waypoint_latitude, longitude: p.waypoint_longitude}), swim(keep, {latitude: p.waypoint_latitude, longitude: p.waypoint_longitude}));
  });
  const {kept: onWater, withheld: held, pending} = keepWater(admitted.map(f => ({f, latitude: f.properties.waypoint_latitude, longitude: f.properties.waypoint_longitude})), place);
  return {withheld: held, pending, picks: onWater.slice(0, keep.top ?? TOP).map(({f}) => {
    const p = f.properties, id = String(f.id ?? p.id), n = field ? Number(p[field]) : NaN;
    const at = {latitude: p.waypoint_latitude, longitude: p.waypoint_longitude}, nm = miles(origin, at), yd = swim(keep, at);
    const species = speciesPart(coast), rated = !!label && n >= 1 && n <= 3;
    return {id, kind: 'habitat', name: 'Reef habitat', distance: yd === null ? distance(nm) : swimText(yd), nm, at, screen: screenPlace(screen, {...at, geometry: f.geometry}),
      depth: band(p.depth_min_ft, p.depth_max_ft), fit: label && n >= 1 && n <= 3 ? fitLine(label, n) : 'Screened reef habitat',
      reason: `Terrain score ${p.terrain_score}/100${p.terrain_grade ? ` · grade ${p.terrain_grade}` : ''}.`,
      copy: {...swimCopy(yd), name: [rp('name.reefHabitat')], fit: rated && species ? [cp('mark.layer.habitat.fit', {species, n})] : [rp('fit.screened')],
        reason: [p.terrain_grade ? rp('reason.terrainGraded', {score: String(p.terrain_score), grade: String(p.terrain_grade)}) : rp('reason.terrain', {score: String(p.terrain_score)})]}};
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

/** A target as `loadReefTrip` publishes it (the fields read here). */
export interface PublishedReef {readonly id: string; readonly latitude: number; readonly longitude: number; readonly neighborhood_depth_ft: readonly number[]; readonly terrain_interpretation?: string}
type Ranked = PublishedReef & {readonly name: string; readonly trip_fit: number};
/** The planner's seafloor habitat-export publication as the brief holds it, for one region. */
export type ReefPublication = {readonly state: 'idle' | 'loading' | 'unavailable'; readonly region?: string;
    /** The export hash the planner's gate rejected (held, unavailable or superseded); set only by `recheckReefPublication`. */
    readonly rejected?: string}
  | {readonly state: 'ready'; readonly region: string; readonly loaded: {readonly targets: readonly PublishedReef[]; readonly areas: readonly {id: string; geometry: unknown}[]; readonly publication: {export_sha256?: string} & Record<string, unknown>}};
export const reefPublication = signal<ReefPublication>({state: 'idle'});
type ReefLoader = (region: string) => Promise<unknown>;
/** The manifest gate as dist/seafloor-data.js `loadManifest` returns it (the fields read here). */
type ReefGate = (region: string) => Promise<{readonly state: string; readonly manifest?: {readonly export_sha256?: string} | null}>;

/** Each load's number: only the latest load may write its answer, so A→B→A never lets the first A's late answer land. */
let generation = 0;
async function startLoad(region: string, loader: ReefLoader): Promise<void> {
  const mine = ++generation;
  reefPublication.value = {state: 'loading', region};
  let next: ReefPublication;
  try {
    const l = await loader(region) as {targets?: unknown; areas?: unknown; publication?: unknown} | null;
    next = l && Array.isArray(l.targets) && Array.isArray(l.areas) && l.publication && typeof l.publication === 'object'
      ? {state: 'ready', region, loaded: l as Extract<ReefPublication, {state: 'ready'}>['loaded']} : {state: 'unavailable', region};
  } catch { next = {state: 'unavailable', region}; }
  // A load started after this one (another region, or the same region again) keeps its own answer.
  if (mine === generation) reefPublication.value = next;
}

/** Load the region's publication once (another region starts again); a failure leaves the list above in place. */
export async function loadReefPublication(region: string, loader: ReefLoader = loadReefTrip): Promise<void> {
  const was = reefPublication.peek();
  if (was.state !== 'idle' && was.region === region) return;
  await startLoad(region, loader);
}

/**
 * The planner's every-minute re-check (web/map/ranked.ts `recheckPlan`, web/trip.ts): a ready publication stays only while
 * the live manifest is ready with the same export hash; otherwise it is withheld (unavailable, its hash rejected) at once,
 * so a held, unavailable or superseded publication ranks nothing. As the planner lifts a rejection only on a later
 * verification, a rejected publication returns only through a fresh `loadReefTrip` once the manifest is ready again
 * (a superseded one reloads at once). A load or another check started meanwhile wins.
 */
export async function recheckReefPublication(region: string, gate: ReefGate = r => loadManifest(r), loader: ReefLoader = loadReefTrip): Promise<void> {
  const was = reefPublication.peek();
  const held = was.state === 'ready' ? was.loaded.publication.export_sha256 : was.state === 'unavailable' ? was.rejected : undefined;
  if (was.region !== region || !held) return;
  let live: string | undefined;
  try { const g = await gate(region); live = g.state === 'ready' ? g.manifest?.export_sha256 : undefined; } catch { live = undefined; }
  if (reefPublication.peek() !== was) return;
  if (was.state === 'ready') {
    if (live === held) return;
    reefPublication.value = {state: 'unavailable', region, rejected: held};
    if (!live) return;
  } else if (!live) return;
  await startLoad(region, loader);
}

const rankSpots = bestSpots as unknown as (atlas: unknown, screen: unknown, o: Record<string, unknown>) => Ranked[];
/** SCJ-2b: the trip planner's protected-area screen (web/trip.ts `protectedScreen`), declared here so this file does not import trip.ts. */
export type PlannerScreenState = {readonly state: 'idle' | 'loading' | 'failed'} | {readonly state: 'loaded'; readonly region?: string;
  readonly screen: {ready(): boolean; pointAllowed(p: {latitude: number; longitude: number}): boolean; geometryAllowed(g: unknown): boolean}};
type ReadyScreen = Extract<PlannerScreenState, {state: 'loaded'}>['screen'];
/** The publication list's line while the planner's screen has loaded but is not current (failed, never checked, or past 36 h). */
export const SCREEN_NOT_CURRENT = 'Protected-area check not current · fishing places withheld';

/** The planner's ranking of the publication (`bestSpots`, same filters, the planner's screen), then Spear's swim, as picks. */
function publicationScreened(loaded: Extract<ReefPublication, {state: 'ready'}>['loaded'], screen: ReadyScreen, species: string, label: string | null, coast: string,
  limitFt: number, origin: Origin | null, keep: Keep, place: Place): Screened {
  if (!screen.ready() || !(limitFt > 0)) return {picks: [], withheld: 0, pending: false};
  let pending = false;
  const watched: Place = p => { const at = place(p); pending ||= at.state === 'unknown' && at.reason === 'pending'; return at; };
  const stats = {withheld: 0};
  // RF1050-16: malformed depth bands are dropped before the 50-candidate cap so they cannot starve a valid place; the cached publication is not touched.
  const maxDepth = Math.min(limitFt, 300);
  const eligible = {...loaded, targets: loaded.targets.filter(t => validDepthPair(t?.neighborhood_depth_ft, maxDepth))};
  const ranked = rankSpots(eligible, screen, {species, count: 50, maxDepth, origin, maxDistanceNm: keep.maxNm ?? Infinity, place: watched, stats});
  return {withheld: stats.withheld, pending, picks: ranked.filter(t => kept(keep, miles(origin, t), swim(keep, t))).slice(0, keep.top ?? TOP).map(t => {
    const [lo, hi] = t.neighborhood_depth_ft as [number, number], nm = miles(origin, t), yd = swim(keep, t);
    const species = speciesPart(coast);
    return {id: t.id, kind: 'reef', name: t.name, distance: yd === null ? distance(nm) : swimText(yd), nm, depth: band(lo, hi),
      fit: label ? fitLine(label, t.trip_fit) : 'Screened reef habitat', reason: t.terrain_interpretation ?? 'Surveyed reef terrain.', at: {latitude: t.latitude, longitude: t.longitude},
      screen: screenPlace(screen, {latitude: t.latitude, longitude: t.longitude, geometries: areasOf(loaded, t)}),
      copy: {...swimCopy(yd), fit: label && species ? [cp('mark.layer.habitat.fit', {species, n: t.trip_fit})] : [rp('fit.screened')],
        ...(t.terrain_interpretation === undefined ? {reason: [rp('reason.surveyed')]} : {})}};
  })};
}
/** The reef areas a published place lies in (its `area_ids` in the publication's `areas`). */
const areasOf = (loaded: unknown, t: unknown): unknown[] => {
  const ids = (t as {area_ids?: string[]}).area_ids ?? [], areas = (loaded as {areas?: {id: string; geometry: unknown}[]}).areas ?? [];
  return areas.filter(a => ids.includes(a.id)).map(a => a.geometry);
};
/** The coast species the planner ranks, as `bestSpots` names it. */
const PLANNER_SPECIES: Readonly<Record<string, string>> = {lingcod: 'lingcod', 'rockfish-reef': 'rockfish', all: 'reef'};

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
  /** SCJ-7: the region's region.json is a 404, so there is nothing to rank and the empty line says so. */
  readonly missing?: boolean;
  /** SCJ-2a: the planner's seafloor publication; absent, the list is the terrain or atlas one. */
  readonly publication?: ReefPublication;
  /** SCJ-2b: the planner's protected-area screen, which admits the publication's places; absent, idle or loading, the list is still checking. */
  readonly plannerScreen?: PlannerScreenState;
  /** SCJ-2c: the home port the distances run from is still loading; nothing is measured until it lands. */
  readonly originPending?: boolean;
  /** SC1322-10: how many picks to list; absent, TOP. The Boat brief asks for ROUTE_BUDGET, then `routedPicks` keeps TOP. */ readonly top?: number;
}
/** Where the current region's region.json read stands (web/app/App.tsx loadRegion writes it); here so the brief reads it without the shell. */
export const regionLoad = signal<{id: string; state: 'loading' | 'ready' | 'error' | 'missing'} | null>(null);

const ATLAS_BASIS = 'Survey reef atlas marks that pass the current protected-area check, ordered by habitat fit, then the atlas habitat score. '
  + 'Depths are the nominal range near each mark in the survey\'s own vertical reference; distances are straight-line from';
const TERRAIN_BASIS = 'Reviewed coastal terrain habitat that passes the current protected-area and closure check, ordered by species fit, then the physical terrain score. '
  + 'Depths are nominal; distances are straight-line from';
const CHECKING_NOTE: StringId = 'mark.layer.habitat.screen.checking';
const PUBLICATION_BASIS = 'Places from the seafloor reef publication the trip planner uses, ranked as the planner ranks them: species fit, then habitat evidence confidence, then the terrain score, '
  + 'kept only where they pass the planner\'s current protected-area check. Depths are the nominal range near each place; distances are straight-line from';

/** The list the brief shows for these inputs: terrain habitat where it binds and loads, else the atlas; one source, never both. */
export function ranking(i: RankingInputs): Ranking {
  const limit = terrainDepthLimitFt(i.profile);
  const origin = i.origin ?? harborOrigin(i.data), harbor = origin?.name ?? 'the harbor';
  // A range applies only where it can be measured: from a harbor or launch position.
  const reach = origin && known(i.reachNm) && i.reachNm > 0 ? i.reachNm : null;
  // A swim limit applies only once the shoreline has loaded; until then the basis says it is not applied.
  const shore = i.shore && i.shore.lines ? {lines: i.shore.lines, maxYd: i.shore.maxYd} : null;
  const keep: Keep = {maxNm: reach, shore, ...(i.top ? {top: i.top} : {})};
  const ranged = reach === null ? '' : ` Only places within your ${Number(reach.toFixed(1))} nm range are listed.`;
  const swum = shore ? ` Only places within ${shore.maxYd} yd of the mapped shoreline are listed, measured straight to the simplified overview line, so the distance is approximate and not a swim route.`
    : i.shore ? ' Your swim limit is not applied: the shoreline to measure from has not loaded, or this region has none.' : '';
  // Without a harbor or launch position no distance is measured, and the basis says so rather than naming one.
  const from = `${origin ? ` ${harbor}.` : ' the region\'s harbor, which has no published position here, so no distance is shown.'}${ranged}${swum} ${LAND_WATER_BASIS} A ranked place is a place to look; fish presence is unverified.`;
  const place = i.place ?? NO_LAND_WATER;
  // SC1137-05: the same sentences as catalogue parts, built from the same numbers and flags (the English strings above are what English shows).
  const harborVar: CopyVar = origin?.unnamed ? cp('where.harbor') : harbor;
  const fromCopy: MarkCopyPart[] = [origin ? rp('basis.from', {harbor: harborVar}) : rp('basis.noOrigin'),
    ...(reach === null ? [] : [rp('basis.ranged', {nm: Number(reach.toFixed(1))})]),
    ...(shore ? [rp('basis.swum', {yd: shore.maxYd})] : i.shore ? [rp('basis.swimOff')] : []), ' ', rp('basis.water'), ' ', rp('basis.fish')];
  const withinCopy = rp('within', {ft: limit, reach: reach === null ? '' : rp('within.reach', {nm: Number(reach.toFixed(1)), harbor: harborVar}), shore: shore ? rp('within.shore', {yd: shore.maxYd}) : ''});
  const withheldCopy = (n: number): MarkCopyPart => rp(n === 1 ? 'withheld.one' : 'withheld.many', {n});
  const headCopy = (source: RankingSource): RankingCopy => ({label: [rp(`source.${source}`)], about: [rp(`about.${source}`)], basis: [rp(`basis.${source}`), ...fromCopy]});
  /** The basis, the list and the empty line once the land/water check has run. */
  const checked = (s: Screened, source: RankingSource, basis: string, empty: string, emptyCopy: Parts | undefined) => {
    const head = headCopy(source), parts = s.pending ? [rp('empty.pending')] : emptyCopy ? (s.withheld && !s.picks.length ? [withheldCopy(s.withheld), ' ', ...emptyCopy] : emptyCopy) : undefined;
    return {
      basis: s.withheld ? `${basis} ${withheldNote(s.withheld)}` : basis,
      picks: s.pending ? [] : s.picks,
      empty: s.pending ? 'Checking land and water for these places…' : s.withheld && !s.picks.length ? `${withheldNote(s.withheld)} ${empty}` : empty,
      ...(s.withheld ? {withheld: s.withheld} : {}), ...(s.pending ? {pending: true} : {}),
      copy: {...head, ...(s.withheld ? {basis: [...head.basis!, ' ', withheldCopy(s.withheld)]} : {}), ...(parts ? {empty: parts} : {})} as RankingCopy,
    };
  };
  const within = `within ${limit} ft${reach === null ? '' : ` and ${Number(reach.toFixed(1))} nm of ${harbor}`}${shore ? ` and ${shore.maxYd} yd of shore` : ''}`;
  const extra = {...(origin ? {harbor: origin.name, origin: {latitude: origin.latitude, longitude: origin.longitude}} : {}), ...(reach === null ? {} : {reach})};
  const bare = (empty: string, key: 'empty.missing' | 'empty.shore' | 'empty.loadingPublication' | 'empty.mapLoading') =>
    ({source: null, label: '', basis: '', picks: [], empty, copy: {empty: [rp(key)]}} as Ranking);
  // A region that does not exist has nothing to rank for any profile, Shore included.
  if (i.missing) return bare('No ranked places: this region does not exist.', 'empty.missing');
  if (PROFILE_TABLE[i.profile].whereToLook === 'shore-runs')
    return bare('Shore runs and their review status show on the Chart.', 'empty.shore');
  if (i.originPending) { // SCJ-2c: no harbour-based numbers that change under the user once the port lands.
    const r = ranking({...i, originPending: false, reachNm: null}); // only its source and label are kept
    return {source: r.source, label: r.label, basis: r.source ? 'Distances run from your home port, which is still loading.' : '', picks: [], empty: 'Finding your home port…',
      copy: {...(r.copy?.label ? {label: r.copy.label} : {}), ...(r.copy?.about ? {about: r.copy.about} : {}), ...(r.source ? {basis: [rp('basis.homePort')]} : {}), empty: [rp('empty.homePort')]}};
  }
  const pub = i.publication, plannerSpecies = Object.hasOwn(PLANNER_SPECIES, i.coast) ? PLANNER_SPECIES[i.coast] : undefined;
  if (pub && i.region && plannerSpecies) {
    if (pub.region !== i.region || pub.state === 'idle' || pub.state === 'loading')
      return bare('Loading ranked reef places…', 'empty.loadingPublication');
    if (pub.state === 'ready' && manifestState(pub.loaded.publication, i.region, i.now).state === 'ready') {
      const ps = i.plannerScreen, head = {source: 'publication' as const, label: 'Seafloor reef publication', basis: PUBLICATION_BASIS + from, picks: [], ...extra};
      const lead = headCopy('publication'), notCurrent = {...lead, empty: [rp('empty.screenNotCurrent')]};
      // Until the planner's screen has loaded for this region nothing is shown; one that is not current withholds every place.
      if (ps?.state !== 'loaded' || ps.region !== undefined && ps.region !== i.region)
        return ps?.state === 'failed' ? {...head, empty: SCREEN_NOT_CURRENT, copy: notCurrent} : {...head, empty: SCREEN_NOTES.checking, copy: {...lead, empty: [cp(CHECKING_NOTE)]}};
      if (!ps.screen.ready()) return {...head, empty: SCREEN_NOT_CURRENT, copy: notCurrent};
      const s = publicationScreened(pub.loaded, ps.screen, plannerSpecies, speciesLabel(i.coast), i.coast, limit, origin, keep, place);
      const empty = s.withheld ? `No other ranked reef places ${within} for this target.`
        : `No ranked reef places pass the current protected-area check ${within} for this target.`;
      return {source: 'publication', label: 'Seafloor reef publication', ...checked(s, 'publication', PUBLICATION_BASIS + from, empty, [rp(s.withheld ? 'empty.publication.other' : 'empty.publication.none', {within: withinCopy})]), ...extra};
    }
  }
  const t = i.terrain, field = speciesOptions.find(s => s.id === i.coast);
  if (i.region && hasCoastTerrain(i.region) && t.state === 'ready' && field && field.id !== 'halibut' && field.id !== 'surfperch' && t.expiresAt > i.now) {
    const screen = i.screen ?? CHECKING;
    const s = habitatScreened(t.rank(t.features, field.field, i.now), screen, i.region, i.coast, limit, origin, keep, place);
    const empty = screen.status !== 'ready' ? screen.note : s.withheld ? `No other reviewed terrain habitat ${within} for this target.`
      : `No reviewed terrain habitat passes the current protected-area and closure check ${within} for this target.`;
    const emptyCopy = screen.status !== 'ready' ? screen.noteCopy : [rp(s.withheld ? 'empty.terrain.other' : 'empty.terrain.none', {within: withinCopy})];
    return {source: 'terrain', label: 'Reviewed terrain habitat', ...checked(s, 'terrain', TERRAIN_BASIS + from, empty, emptyCopy), ...extra};
  }
  if (!i.data) return bare('Ranked places load with the map.', 'empty.mapLoading');
  const s = atlasScreened(i.data, i.screen, i.target, limit, origin, keep, place);
  const empty = i.screen.status !== 'ready' ? i.screen.note : s.withheld ? `No other surveyed reef marks ${within} for this target.`
    : `No surveyed reef marks ${within} for this target.`;
  const emptyCopy = i.screen.status !== 'ready' ? i.screen.noteCopy : [rp(s.withheld ? 'empty.atlas.other' : 'empty.atlas.none', {within: withinCopy})];
  return {source: 'atlas', label: 'Survey reef atlas', ...checked(s, 'atlas', ATLAS_BASIS + from, empty, emptyCopy), ...extra};
}

/** SC1322-10: the most water routes one Boat list computes; picks past it keep their straight line. */
export const ROUTE_BUDGET = 24;
/** A Boat pick whose `nm` is the water route where one was computed, else the straight line (and why no route, when one was tried). */
export type RoutedPick = Pick & {readonly basis: 'water' | 'straight'; readonly why?: RouteFailure;
  /** SC0452-07: a copy of a computed route's bends (snapped ends included), so the run line can screen the line it times; absent without a route. */
  readonly routePoints?: readonly RoutePoint[]};
/** A route, or null when it is not computed yet (the brief paints the list first): that pick keeps its labelled straight line. */
export type RouteFn = (model: LandWaterModel | null, lines: LandWaterLines | null | false, from: RoutePoint, to: RoutePoint) => Route | null;
/**
 * SC1322-10: the Boat list by water (web/route.ts, FSC-04). `picks` come in rank order, already inside the range by straight
 * line, a lower bound on any water route, so a place outside it is never routed and the ranking stays straight-line cheap.
 * Each is routed in turn until `limit` are kept or ROUTE_BUDGET routes ran; one whose route runs past `maxNm` is dropped and
 * the next fills its place. Without a route a pick keeps its straight line, labelled, and is kept or dropped by it.
 */
export function routedPicks(picks: readonly Pick[], origin: RoutePoint | null | undefined, model: LandWaterModel | null, lines: LandWaterLines | null | false,
  maxNm: number | null, limit: number, route: RouteFn = waterRoute): RoutedPick[] {
  const out: RoutedPick[] = []; let calls = 0;
  for (const p of picks) {
    if (out.length >= limit) break;
    if (p.nm == null) { out.push({...p, basis: 'straight'}); continue; }
    if (!inside(p.nm, maxNm)) continue;
    const r = origin && p.at && calls < ROUTE_BUDGET ? (calls++, route(model, lines, origin, p.at)) : null;
    if (r?.ok && !inside(r.nm, maxNm)) continue;
    const nm = r?.ok ? r.nm : p.nm;
    out.push({...p, nm, basis: r?.ok ? 'water' : 'straight', distance: `${nm.toFixed(1)} nm ${r?.ok ? 'by water' : 'straight line'}`, ...(r && !r.ok ? {why: r.reason} : {}),
      ...(r?.ok && Array.isArray(r.points) ? {routePoints: r.points.map(q => ({latitude: q.latitude, longitude: q.longitude}))} : {})});
  }
  return out;
}

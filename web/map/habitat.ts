// Reef marks, survey habitat and geology as data (FE-18, design § 9, § 12): a region's
// published atlas, survey habitat and geology as the Chart's features and the mark
// card's lines, and the terrain's selections as cards. v1's rules are kept: the fit is
// dist/species-fit.js; dist/species.js `matchesSpecies`, dist/survey-habitat.js
// `habitatMatches` and dist/geology.js's filter are restated (those modules import v1's
// region store) and pinned to v1 by tests/test_marks_layer.mjs. Habitat fit is terrain
// and depth suitability from surveys, never a count or promise of fish, with one wording
// in both presentations: "fits <species> habitat n of 3", 3 the strongest (v1's pins,
// packages/coast's `fit_*`). Erasable syntax only: the tests import it by type stripping.
//
// v1's run-time screen (dist/protected-areas.js `pointAllowed`, #489) is kept too: a mark
// shows only while the region's protected areas and closures were checked within 36 hours
// and the mark lies outside all of them (dist/geo-screen.js, boundary contact counts as
// inside). Otherwise it is withheld, and the card and legend say why.
import {pointInGeometry} from '../../dist/geo-screen.js';
import {speciesFit} from '../../dist/species-fit.js';
import type {CoastSelection, CoastTargetDetail} from '../../packages/coast/src/embed-types.ts';
import {speciesOptions} from '../../packages/coast/src/habitat-types.ts';
import {withinDepth, type Profile} from '../profile.ts';
import type {ChartMark} from './coastline.ts';
import {CDFW_MPA_PAGE, NOAA_GEA_PAGE, type ScreenSource} from './mpa.ts';

type Props = Record<string, unknown>;
export interface Feature {readonly type: 'Feature'; readonly geometry: unknown; readonly properties: Props}
export interface Collection {readonly type: 'FeatureCollection'; readonly features: readonly Feature[]}
export const EMPTY: Collection = Object.freeze({type: 'FeatureCollection', features: []});

/** The published fields these functions read (data/atlas.json, regions/<id>/region.json and its assets). */
export interface AtlasTarget {
  id: string; label: string; latitude: number; longitude: number; source_id?: string; source_name?: string; survey_year?: number;
  habitat_grade?: string; neighborhood_depth_ft?: number[]; metrics?: Record<string, number | null>; terrain_interpretation?: string;
  evidence_status?: string; recorded_validation?: {closed_or_screened_area_clearance_m?: number}; qualification?: {closure_clearance_m?: number};
}
export interface Atlas {source_validation_date?: string; targets: AtlasTarget[]; sources?: {id: string; name?: string; credit?: string; rights?: string}[]}
export interface RegionData {
  id: string; assets?: Record<string, string | null>; source_names?: Record<string, string>; target_options?: {id: string; habitat_kinds?: string[]}[];
  regulations_url?: string; mpa?: {bounds?: number[]; minimum_features?: number}; daily_feed?: string;
}
export type Survey = Collection & {created_at?: string; mpa_margin_m?: number; source_kind?: string};
export type Geology = Collection & {source?: {attribution?: string; derivation?: string; limitations?: string}};
/** One region's published layers; a missing or failed layer is null and stays blank. */
export interface MarkData {readonly region: RegionData; readonly atlas: Atlas | null; readonly survey: Survey | null; readonly geology: Geology | null}

const REEF = new Set(['reef', 'all', 'lingcod', 'rockfish', 'rockfish-reef', 'gopher-rockfish', 'cabezon', 'cabezon-shallow-reef']);
/** The v1 target whose habitat a v2 target reads: reef species read reef habitat; others (halibut, dungeness) their own. */
export const habitatFamily = (target: string): string => REEF.has(target) ? 'reef' : target;
/** v1's two fit screens (dist/species-fit.js) by target; `reef` is v1's combined fit, the weaker of the two. */
const SCREENS: Readonly<Record<string, readonly ('lingcod' | 'rockfish')[]>> = {
  lingcod: ['lingcod'], rockfish: ['rockfish'], 'rockfish-reef': ['rockfish'], 'gopher-rockfish': ['rockfish'], reef: ['lingcod', 'rockfish'], all: ['lingcod', 'rockfish'],
};

/** The one fit wording (§ 12), 3 the strongest. */
export const fitLine = (species: string, n: number): string => `Fits ${species} habitat ${n} of 3`;

/** A mark's fit for `target` as v1's pin shows it (4 − speciesFit rank), or null where no screen rates it. */
export function markFit(t: AtlasTarget, target: string): {n: number; line: string} | null {
  const screens = SCREENS[target];
  const fits = (screens ?? []).map(s => speciesFit(t, s));
  if (!screens || fits.some(f => !f)) return null;
  const n = 4 - Math.max(...fits.map(f => f!.rank));
  return {n, line: fitLine(screens.join(' and '), n)};
}

/** dist/species.js `matchesSpecies` for the target's family: reef and rockfish show every mark, lingcod its rough relief. */
export function markShown(t: AtlasTarget, target: string): boolean {
  if (habitatFamily(target) !== 'reef') return false;
  const m = t.metrics ?? {};
  return target !== 'lingcod' || ((m.relief_210m_m ?? -1) >= 3 && (m.rugose_or_bedrock_fraction_210m ?? -1) >= 0.6);
}

/** dist/survey-habitat.js `habitatMatches` with the region passed in. */
export function surveyMatches(p: Props, family: string, region: RegionData): boolean {
  const option = region.target_options?.find(o => o.id === family);
  if (!option || p.fishing_target === true || p.military_access === 'unverified') return false;
  return Array.isArray(p.species_ids) ? p.species_ids.includes(family) : (option.habitat_kinds ?? []).includes(String(p.habitat_kind));
}

/** dist/geology.js: rock and mixed units for reef targets, sediment for halibut and dungeness, nothing for the rest. */
export const geologyShown = (kind: unknown, family: string): boolean =>
  family === 'reef' ? kind !== 'sediment' : (family === 'halibut' || family === 'dungeness') && kind === 'sediment';

const point = (t: AtlasTarget): unknown => ({type: 'Point', coordinates: [t.longitude, t.latitude]});
const keep = (f: Feature, extra: Props): Feature => ({type: 'Feature', geometry: f.geometry, properties: {id: f.properties.id, ...extra}});
const collection = (features: Feature[]): Collection => ({type: 'FeatureCollection', features});

/** v1's check age window (dist/protected-areas.js `freshEnough`): at most 36 h old and 5 min ahead. */
export const SCREEN_MAX_AGE_MS = 36 * 3600000;
const AHEAD_MS = 300000;
export const freshCheck = (at: string | null | undefined, now: number): boolean => {
  const age = now - Date.parse(at ?? '');
  return age >= -AHEAD_MS && age <= SCREEN_MAX_AGE_MS;
};
/** What the screen checked against: v1's `data` and `checked`, `live` for its own ds582 query, and `extra` with `extraChecked`. */
export type ScreenInputs = ScreenSource & {readonly live: boolean};
export interface Boundary {readonly name: string; readonly federal: boolean; readonly geometry: unknown}
export type ScreenStatus = 'checking' | 'ready' | 'stale' | 'unavailable';
/** The screen at one time: its legend line, the source line for a withheld card, and when a ready screen goes stale. */
export interface MarkScreen {readonly status: ScreenStatus; readonly note: string; readonly source: string; readonly boundaries: readonly Boundary[]; readonly until: number}
/** v1's lines while marks are withheld (dist/app.js `updateReefCoverage`, dist/protected-areas.js status). */
export const SCREEN_NOTES = {
  checking: 'Checking protected areas before showing fishing spots…',
  unavailable: 'Protected-area check unavailable · fishing spots withheld',
  stale: 'Boundary check stale; fishing targets withheld',
} as const;
export const CHECKING: MarkScreen = Object.freeze({status: 'checking', note: SCREEN_NOTES.checking, source: 'CDFW ds582 check in progress', boundaries: [], until: Infinity});

const boundary = (f: Props): Boundary => {
  const p = (f.properties ?? {}) as Props;
  return {name: String(p.FULLNAME || p.NAME || 'Protected area'), federal: p.Type === 'GEA', geometry: f.geometry};
};
/** v1's `freshEnough` at `now`: ready only while the boundaries, and the region's closures if it names any, were checked within the window. */
export function assessScreen(i: ScreenInputs | null, now: number): MarkScreen {
  if (!i) return CHECKING;
  const c = i.closures, at = i.areas ? i.checkedAt : null;
  const when = (t: string | null | undefined, live = false) => live ? 'checked this session' : t ? `checked ${t.slice(0, 10)}` : 'check unavailable';
  const source = [`CDFW ds582 ${when(at, i.live && !!at)}`, c !== undefined && `NOAA closures ${when(c?.checkedAt)}`].filter(Boolean).join(' · ');
  const fresh = freshCheck(at, now) && (c === undefined || !!c && freshCheck(c.checkedAt, now));
  if (!fresh) {
    const status = i.areas ? 'stale' : 'unavailable';
    return {status, note: SCREEN_NOTES[status], source, boundaries: [], until: Infinity};
  }
  return {status: 'ready', source, until: Math.min(...[at!, c?.checkedAt].filter(t => t != null).map(t => Date.parse(t!))) + SCREEN_MAX_AGE_MS,
    note: `Reef marks inside protected areas${c ? ' or groundfish exclusions' : ''} are withheld · ${i.live ? 'boundaries checked this session' : `boundary snapshot ${at!.slice(0, 10)}`}`,
    boundaries: [...i.areas!, ...c?.areas ?? []].map(boundary)};
}

/** dist/region.js `acceptsFeed`: the region's own feed (Morro Bay's predates the region id). */
export const acceptsFeed = (d: Props | null | undefined, region: string): boolean => d?.region_id === region || (!d?.region_id && region === 'morro-bay');
/** dist/daily-feed.js `validDailyPart` with the region passed in: one part of the region's daily feed as the Worker's /api/daily returns it. */
export function validDailyPart(d: Props | null | undefined, part: string, region: string): boolean {
  if (d?.schema_version !== 1 || d.part !== part || !acceptsFeed(d, region)) return false;
  if (!Number.isFinite(Date.parse(String(d.generated_at))) || d.catch_probability !== null || d.bite_score !== null) return false;
  const body = part === 'regulations' ? d.regulations : d.sources;
  return !!body && typeof body === 'object' && (part === 'regulations' || !Array.isArray(body));
}
/** One record of the daily feed (pipeline/collect.py `source`). */
export interface DailyRecord {readonly status?: unknown; readonly data_retrieved_at?: unknown; readonly data?: {readonly sha256?: unknown; readonly geojson?: unknown} | null}
/**
 * v1's closure refresh: the feed's daily check of NOAA's coordinate file renews the closures' check time while
 * its hash matches the published file's, and a changed file voids it; without a check the file's own time stands.
 */
export function closureCheckedAt(c: {readonly checkedAt: string | null; readonly sha256: string | null}, r: DailyRecord | null | undefined): string | null {
  if (r?.status !== 'ok') return c.checkedAt;
  return typeof c.sha256 === 'string' && r.data?.sha256 === c.sha256 && typeof r.data_retrieved_at === 'string' ? r.data_retrieved_at : null;
}

/** Why a mark is withheld: the screen's own line, or the areas it lies in; null when it shows (v1's `pointAllowed`). */
export interface Withheld {readonly reading: string; readonly inside: readonly Boundary[]}
export function withheld(t: {latitude: number; longitude: number}, screen: MarkScreen): Withheld | null {
  if (screen.status !== 'ready') return {reading: screen.note, inside: []};
  const inside = screen.boundaries.filter(b => pointInGeometry([t.longitude, t.latitude], b.geometry));
  return inside.length ? {reading: `Inside ${inside.map(b => b.name).join('; ')}`, inside} : null;
}

/** The marks the target, profile and run-time screen admit (the profile's depth limit on the deepest nearby depth), with their fit badge. */
export function markFeatures(atlas: Atlas | null | undefined, target: string, profile: Profile, screen: MarkScreen): Collection {
  return collection((atlas?.targets ?? []).filter(t => markShown(t, target) && withinDepth(profile, t.neighborhood_depth_ft?.[1]) && !withheld(t, screen)).map(t => {
    const fit = markFit(t, target);
    return {type: 'Feature', geometry: point(t), properties: {id: t.id, ...fit ? {fit: String(fit.n)} : {}}};
  }));
}
export const surveyFeatures = (data: MarkData | null, target: string): Collection => !data?.survey ? EMPTY
  : collection(data.survey.features.filter(f => surveyMatches(f.properties, habitatFamily(target), data.region)).map(f => keep(f, {kind: f.properties.habitat_kind})));
export const geologyFeatures = (data: MarkData | null, target: string): Collection => !data?.geology ? EMPTY
  : collection(data.geology.features.filter(f => geologyShown(f.properties.kind, habitatFamily(target))).map(f => keep(f, {kind: f.properties.kind})));

/** CDFW's ocean sport fishing regulations, for a region whose data names no regional page (v1's species.js names the Central one). */
export const CDFW_REGULATIONS = 'https://wildlife.ca.gov/Fishing/Ocean/Regulations';
/** The official page the regulations line links: the region's own CDFW page if its data names one, else CDFW's ocean page. Never advice. */
export function regulationsLink(region: RegionData): {href: string; label: string} {
  const own = region.regulations_url;
  return typeof own === 'string' && /^https:\/\/wildlife\.ca\.gov\//.test(own)
    ? {href: own, label: 'CDFW regional fishing regulations'} : {href: CDFW_REGULATIONS, label: 'CDFW ocean fishing regulations'};
}
/** The card's regulations line: what the layer's own build screened, then the rules check (FE-54 adds the rules themselves). */
const rules = (screen?: string | false): string => screen ? `${screen}; check current rules before you fish.` : 'Check current rules before you fish.';
const isoDate = (value: unknown): string => {
  const s = String(value ?? '');
  return /^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : s.slice(0, 10);
};
const joined = (...parts: unknown[]): string => parts.filter(p => typeof p === 'string' && p.trim()).join(' · ');
const depthRange = (d: readonly number[] | undefined): string => d?.length === 2 ? `~${Math.round(d[0]!)}–${Math.round(d[1]!)} ft` : '';

/** An atlas mark's card: fit, grade and nearby depth range; survey and atlas dates; credit and rights per feature in the basis. */
export function atlasCard(t: AtlasTarget, data: MarkData, target: string): ChartMark {
  const source = data.atlas?.sources?.find(s => s.id === t.source_id), date = data.atlas?.source_validation_date;
  const screened = t.recorded_validation?.closed_or_screened_area_clearance_m ?? t.qualification?.closure_clearance_m;
  return {
    id: `spot:${t.id}`, name: t.label, kind: joined('Reef mark', t.habitat_grade && `grade ${t.habitat_grade}`, depthRange(t.neighborhood_depth_ft)),
    reading: markFit(t, target)?.line ?? 'Habitat fit unrated for this target',
    source: joined(t.source_name ?? data.region.source_names?.[t.source_id ?? ''] ?? source?.name ?? t.source_id, t.survey_year && `surveyed ${t.survey_year}`, date && `atlas ${date}`),
    // v1's wording (dist/terrain-evidence.js): a build-time screen with its measured clearance, never a promise.
    rules: rules(typeof screened === 'number' && screened > 0 && !!date && `Screened against protected areas with ${Math.round(screened)} m clearance in the atlas of ${date}`),
    regulations: regulationsLink(data.region),
    basis: [t.terrain_interpretation, t.evidence_status, source && joined(source.credit, source.rights)].filter(Boolean).join(' '),
  };
}

/** v1's words for a target inside a protected area (dist/regulations.js) or a NOAA closure (dist/protected-areas.js). */
const WITHHELD_MPA = 'SkipperCast withholds fishing targets in all mapped protected areas, including conservation areas that allow some activities. Consult the exact official rules.';
const WITHHELD_GEA = 'NOAA groundfish closure. SkipperCast excludes all target species here as a conservative planning rule. Federal regulations control over this supplemental map.';
/** A linked mark the run-time screen withholds, or has yet to check: why, the check, and the official page; never its position or fit. */
export function withheldCard(t: AtlasTarget, w: Withheld, screen: MarkScreen): ChartMark {
  const federal = w.inside.length > 0 && w.inside.every(b => b.federal);
  return {
    id: `spot:${t.id}`, name: screen.status === 'checking' ? 'Checking reef mark' : 'Reef mark withheld', kind: `Reef mark · ${t.id}`, reading: w.reading, source: screen.source,
    rules: w.inside.length ? (federal ? WITHHELD_GEA : WITHHELD_MPA) : 'Check current rules and boundaries before you fish.',
    regulations: federal ? {href: NOAA_GEA_PAGE, label: 'NOAA groundfish closed areas'} : {href: CDFW_MPA_PAGE, label: 'CDFW marine protected areas'},
    basis: 'Atlas marks are checked again in the browser against current protected-area boundaries and the region\'s closures before they show. '
      + 'A mark inside one is withheld, and every mark is withheld while that check is unavailable or more than 36 hours old.',
  };
}

const UNIT: Readonly<Record<string, string>> = {rock: 'Mapped hard bottom', mixed: 'Mapped mixed bottom', sediment: 'Mapped soft bottom', kelp: 'Historical kelp detections'};
/** A survey habitat outline's card, from the published feature (v1's habitatDetails facts). */
export function surveyCard(p: Props, survey: Survey, region: RegionData): ChartMark {
  const kelp = p.habitat_kind === 'kelp', area = Number(p.area_km2), margin = survey.mpa_margin_m;
  return {
    id: `survey:${String(p.id)}`, name: String(p.name ?? 'Survey habitat'), kind: UNIT[String(p.habitat_kind)] ?? 'Survey context',
    reading: Number.isFinite(area) ? `${area.toFixed(3)} km²` : '—',
    source: joined(survey.source_kind ?? 'Survey habitat', `${kelp ? 'observed' : 'compiled'} ${isoDate(p.source_date)}`),
    rules: rules(typeof margin === 'number' && `MPAs subtracted with a ${margin} m margin when built on ${isoDate(survey.created_at)}`), regulations: regulationsLink(region),
    basis: [p.limitations, p.depth_note].filter(Boolean).join(' '),
  };
}

/** A geology unit's card (v1's geology.js facts). */
export function geologyCard(p: Props, geology: Geology, region: RegionData): ChartMark {
  const s = geology.source ?? {};
  return {
    id: `geology:${String(p.id)}`, name: String(p.label ?? 'Geology'), kind: `Geology · map unit ${String(p.unit ?? '—')}`,
    reading: Number.isFinite(Number(p.area_km2)) ? `${Number(p.area_km2)} km²` : '—', source: s.attribution ?? 'Geological map',
    rules: rules(/MPA exclusion/i.test(s.derivation ?? '') && 'MPAs excluded when the layer was built'), regulations: regulationsLink(region),
    basis: [s.derivation, s.limitations].filter(Boolean).join(' '),
  };
}

const degrees = (value: number, positive: string, negative: string): string => `${Math.abs(value).toFixed(4)}° ${value >= 0 ? positive : negative}`;
const place = (s: {latitude: number; longitude: number}): string => `${degrees(s.latitude, 'N', 'S')}, ${degrees(s.longitude, 'E', 'W')}`;

/** The terrain's habitat selection before its evidence arrives: its id and position. */
export const terrainCard = (s: CoastSelection): ChartMark => ({id: `habitat:${s.id ?? ''}`, name: 'Selected habitat', kind: s.id ? `Terrain habitat · ${s.id}` : 'Terrain habitat',
  reading: place(s), source: 'Coastal terrain selection', basis: 'Chosen in the 2D or 3D terrain, where its evidence and source lines show.'});

/** The renderer's evidence (onTargetDetail) verbatim, its "species fit n/3" in § 12's wording; the first sentence is the source line. */
export function terrainDetailCard(d: CoastTargetDetail, coastSpecies: string): ChartMark {
  const label = speciesOptions.find(o => o.id === coastSpecies)?.label.toLowerCase() ?? coastSpecies;
  const facts = d.facts.split(' · ').map(part => {
    const fit = /^species fit ([1-3])\/3$/.exec(part);
    return fit ? fitLine(label, Number(fit[1])).toLowerCase() : part;
  }).join(' · ');
  const [source = '', ...rest] = d.evidence.split(/(?<=\.) /);
  return {id: `habitat:${d.id}`, name: d.title, kind: `Terrain ${d.kind} habitat · ${d.id}`, reading: facts, source, basis: rest.join(' ') || d.evidence};
}

/** packages/coast `resolveHabitatSelection`'s receipt (web/map/coast-habitat.d.ts). */
export interface HabitatReceipt {readonly id: string; readonly latitude: number; readonly longitude: number; readonly expiresAt: string; readonly kind: 'reef' | 'shore'}
/** A `?habitat=` restored without graphics: the reviewed release admits the id here until the receipt expires. */
export const receiptCard = (r: HabitatReceipt): ChartMark => ({
  id: `habitat:${r.id}`, name: r.kind === 'shore' ? 'Shore habitat' : 'Reef habitat', kind: `Terrain habitat · ${r.id}`, reading: place(r),
  source: `Reviewed coastal habitat · valid until ${r.expiresAt.slice(0, 10)}`,
  basis: 'Restored from the reviewed habitat release; its evidence lines show in the 2D and 3D terrain.',
});

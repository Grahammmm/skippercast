// The trip planner's ranked spots on the Chart (#495, FE-51 follow-up; design § 9): v1's
// numbered pins (dist/trip-ranking-layer.js) as a GeoJSON source and layers. The plan comes
// from the planner's `skippercast:trip-ranked` event (web/trip.ts); a spot draws only while
// the planner's own protected-area screen is current and allows it and its reef area, the
// marks' run-time screen (#492, marks.ts `markScreen`) is ready and does not withhold it,
// and the plan's seafloor publication is ready, so a cleared, withheld or changed plan
// draws nothing. Pins are numbered in the planner's order (`trip_rank`), never a forecast
// of fish. As in v1, spots within 44 px of an earlier pin at the camera's zoom join it
// ("1 +4"); a click on such a pin zooms to its spots, and a lone pin opens the one mark
// card with v1's lines and "Review & export". Erasable syntax only: Node tests import it.
import {computed, signal} from '@preact/signals';
import {manifestState} from '../../dist/seafloor-data.js';
import {setParams} from '../state.ts';
import type {ChartMark} from './coastline.ts';
import {regulationsLink, withheld, type Collection, type RegionData} from './habitat.ts';
import {RANKED_SOURCE} from './layers.ts';
import {markData, markScreen} from './marks.ts';
import type {Palette} from './palette.ts';
import {camera, cameraParam, zoomForSpan, type Camera} from './stage.ts';
import {LABEL_FONT} from './style.ts';

export const RANKED_PICK = 'ranked-target';
export const RANKED_PIN = 'ranked-pin';
/** v1's grouping distance and the pin's target: 44 px. */
const GROUP_PX = 44;

/** A ranked spot as dist/spot-ranking.js `bestSpots` returns it (the fields read here). */
export interface RankedTarget {
  readonly id: string; readonly name: string; readonly latitude: number; readonly longitude: number; readonly trip_rank: number;
  readonly trip_fit?: number; readonly evidence_confidence?: {readonly percent?: number} | null; readonly area_ids?: readonly string[];
  readonly terrain_interpretation?: string; readonly special_note?: string; readonly evidence_status?: string; readonly survey_year?: number;
}
/** The event's detail (dist/export-ui.js): no targets when the plan is cleared. */
export interface RankedPlan {
  readonly targets: readonly RankedTarget[];
  readonly areas: readonly {readonly id: string; readonly geometry: unknown}[];
  readonly publication?: {readonly region?: string; readonly export_sha256?: string; readonly verified_at?: string};
  /** Set when the publication changed after the plan was ranked. */
  readonly invalid?: boolean;
  readonly fit?: boolean;
}
/** The planner's protected-area screen (dist/protected-areas.js `initProtectedAreas`). */
export interface RankedScreen {
  ready(): boolean;
  pointAllowed(p: {latitude: number; longitude: number}): boolean;
  geometryAllowed(geometry: unknown): boolean;
}
export const NO_PLAN: RankedPlan = Object.freeze({targets: [], areas: []});

/** The ranked spots the planner's screen admits, in rank order (web/trip.ts writes them). */
export const rankedSpots = signal<readonly RankedTarget[]>([]);
/**
 * The ranked spots the Chart draws: those the marks' run-time screen (#492) also shows, so the
 * Chart never draws a spot it withholds as a mark; while that screen is checking, stale or
 * unavailable, none. Ranks stay the planner's.
 */
export const drawnSpots = computed(() => { const s = markScreen.value; return rankedSpots.value.filter(t => !withheld(t, s)); });

/**
 * v1's draw gate (dist/trip-ranking-layer.js): nothing unless the screen is current, the plan has
 * spots, and its publication is ready for `region` and not rejected since it was verified (a later
 * verification lifts the rejection); then, in rank order, each spot whose point and reef areas the
 * screen allows.
 */
export function screenRanked(plan: RankedPlan, screen: RankedScreen | null, rejected: Map<string, number>, region: string | null, now = Date.now()): RankedTarget[] {
  if (!screen?.ready() || !plan.targets.length) return [];
  const publication = plan.publication, hash = publication?.export_sha256 ?? '', heldAt = rejected.get(hash);
  if (heldAt !== undefined) {
    if (!(Date.parse(publication?.verified_at ?? '') > heldAt)) return [];
    rejected.delete(hash);
  }
  if (plan.invalid || manifestState(publication, region, now).state !== 'ready') return [];
  const allowed = (id: string): boolean => plan.areas.some(a => a.id === id && screen.geometryAllowed(a.geometry));
  return [...plan.targets].sort((a, b) => a.trip_rank - b.trip_rank).filter(t => !!t.trip_rank && screen.pointAllowed(t) && !!t.area_ids?.every(allowed));
}

/** A seafloor publication gate as dist/seafloor-data.js `loadManifest` returns it (the fields read here). */
export interface PublicationGate { readonly state: string; readonly manifest?: {readonly export_sha256?: string} | null }

/**
 * The planner's every-minute re-check (web/trip.ts): a plan with spots stays as it is while its
 * publication is ready with the same export hash; otherwise it becomes invalid and its hash is held
 * in `rejected` from `now`, so `screenRanked` draws nothing until a later verification.
 */
export function recheckPlan(plan: RankedPlan, gate: PublicationGate, rejected: Map<string, number>, now = Date.now()): RankedPlan {
  const hash = plan.publication?.export_sha256;
  if (!plan.targets.length || !hash || (gate.state === 'ready' && gate.manifest?.export_sha256 === hash)) return plan;
  rejected.set(hash, now);
  return {...plan, invalid: true};
}

/** Web Mercator in `?view=` pixels (256 px tiles), as v1's Leaflet measures its pins. */
const pixel = (t: {latitude: number; longitude: number}, zoom: number) => {
  const world = 256 * 2 ** zoom, sin = Math.sin(t.latitude * Math.PI / 180);
  return {x: (t.longitude + 180) / 360 * world, y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * world};
};

/** One pin per group at `zoom`, at its best-ranked spot, with how many more it holds and their extent. */
export function rankedFeatures(spots: readonly RankedTarget[], zoom: number | null): Collection {
  if (zoom === null) return {type: 'FeatureCollection', features: []};
  const groups: {at: {x: number; y: number}; members: RankedTarget[]}[] = [];
  for (const t of spots) {
    const at = pixel(t, zoom), near = groups.find(g => Math.hypot(g.at.x - at.x, g.at.y - at.y) < GROUP_PX);
    if (near) near.members.push(t); else groups.push({at, members: [t]});
  }
  return {type: 'FeatureCollection', features: groups.map(({members}) => {
    const first = members[0]!, lat = members.map(m => m.latitude), lon = members.map(m => m.longitude);
    return {type: 'Feature', geometry: {type: 'Point', coordinates: [first.longitude, first.latitude]}, properties: {
      id: first.id, rank: first.trip_rank, more: members.length - 1,
      west: Math.min(...lon), south: Math.min(...lat), east: Math.max(...lon), north: Math.max(...lat)}};
  })};
}

/** The camera's zoom: pins regroup when it changes, never on a pan. */
export const rankedZoom = computed(() => camera.value?.zoom ?? null);

/** The Chart's source and layers: a 44 px target, the numbered disc and the "+n" of a group, from the palette. */
export function rankedStyle(p: Palette) {
  return {
    source: {type: 'geojson', data: {type: 'FeatureCollection', features: []}},
    layers: [
      {id: RANKED_PICK, type: 'circle', source: RANKED_SOURCE, paint: {'circle-radius': GROUP_PX / 2, 'circle-color': p.bg, 'circle-opacity': 0}},
      {id: RANKED_PIN, type: 'circle', source: RANKED_SOURCE, paint: {'circle-radius': 16, 'circle-color': p.mint, 'circle-stroke-color': p.bg, 'circle-stroke-width': 2.5}},
      {id: 'ranked-number', type: 'symbol', source: RANKED_SOURCE,
        layout: {'text-field': ['to-string', ['get', 'rank']], 'text-font': [LABEL_FONT], 'text-size': 15, 'text-allow-overlap': true, 'text-ignore-placement': true},
        paint: {'text-color': p.bg}},
      {id: 'ranked-more', type: 'symbol', source: RANKED_SOURCE, filter: ['>', ['get', 'more'], 0],
        layout: {'text-field': ['concat', '+', ['to-string', ['get', 'more']]], 'text-font': [LABEL_FONT], 'text-size': 12, 'text-anchor': 'left',
          'text-offset': [1.4, -1.2], 'text-allow-overlap': true, 'text-ignore-placement': true},
        paint: {'text-color': p.text, 'text-halo-color': p.bg, 'text-halo-width': 2}},
    ],
  };
}

/** The camera that shows `targets` (FE-51's "Show ranked spots on map", and a group's click). */
export function fitCamera(targets: readonly {latitude: number; longitude: number}[]): Camera | null {
  if (!targets.length) return null;
  const lat = targets.map(t => t.latitude), lon = targets.map(t => t.longitude);
  const latitude = (Math.min(...lat) + Math.max(...lat)) / 2, longitude = (Math.min(...lon) + Math.max(...lon)) / 2;
  const span = Math.max((Math.max(...lon) - Math.min(...lon)) * 111320 * Math.cos(latitude * Math.PI / 180), (Math.max(...lat) - Math.min(...lat)) * 110540);
  return {latitude, longitude, zoom: zoomForSpan(span * 1.3)};
}

/** A click on a group's pin moves the Chart to its spots (v1's fitBounds) and returns true. */
export function zoomToGroup(properties: Record<string, unknown> | null): boolean {
  const p = properties ?? {}, [west, south, east, north] = [p.west, p.south, p.east, p.north].map(Number) as [number, number, number, number];
  if (!(Number(p.more) > 0) || ![west, south, east, north].every(Number.isFinite)) return false;
  const at = fitCamera([{latitude: south, longitude: west}, {latitude: north, longitude: east}]);
  if (at) setParams({view: cameraParam(at)});
  return !!at;
}

const joined = (...parts: unknown[]): string => parts.filter(p => typeof p === 'string' && p.trim()).join(' · ');

/** A ranked spot's card: v1's heading and line (rank, habitat fit, evidence confidence), its interpretation and note in the basis. */
export function rankedCard(t: RankedTarget, region: RegionData | null): ChartMark {
  const percent = t.evidence_confidence?.percent;
  return {
    id: `ranked:${t.id}`, name: `#${t.trip_rank} · ${t.name}`, kind: 'Ranked trip spot · numbered in the planner\'s order',
    reading: joined(t.trip_fit && `Habitat ${t.trip_fit}/3`, typeof percent === 'number' && `${percent}% evidence confidence`) || 'Habitat fit unrated',
    source: joined('Seafloor publication', t.survey_year && `surveyed ${t.survey_year}`),
    rules: 'Drawn while this session\'s protected-area check is current; check current rules before you fish.',
    regulations: regulationsLink(region ?? {id: ''}),
    basis: [t.terrain_interpretation, t.special_note, t.evidence_status].filter(Boolean).join(' '),
    trip: t.id,
  };
}

/** The card for a clicked lone pin; null when its spot is no longer drawn. */
export function rankedMark(properties: Record<string, unknown> | null): ChartMark | null {
  const t = drawnSpots.peek().find(s => s.id === properties?.id);
  return t ? rankedCard(t, markData.peek()?.region ?? null) : null;
}

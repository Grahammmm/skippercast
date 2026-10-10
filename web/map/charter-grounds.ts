// Charter grounds on the Chart (FE-21, docs/plans/front-end/design.md § 9): the
// public part of the Charter fleet rail entry. The region's published charter
// evidence (region.json `assets.charters`, data/charter-grounds.json, the file
// dist/charter-grounds.js draws for v1) as hatched outlines in the --fleet
// (--amber) family, a name at zoom 11 and one mark card per ground.
//
// v1's rules are kept (dist/charter-grounds.js `matchingGrounds` and `draw`):
// broad regional names have no outline; only grounds reported for the target's
// species draw (the layer covers lingcod and rockfish only); the profile's depth
// limit applies to the outline's deepest survey depth; and v1's run-time
// protected-area screen (dist/protected-areas.js `pointAllowed` and
// `geometryAllowed`, the reef marks' screen, web/map/habitat.ts, #489) must be
// ready with the ground's anchor outside and its outline clear of every area.
// The basis sentences are v1's own, copied verbatim. Nothing here infers a
// boat position, a catch or a bite: the outlines are search windows around
// named grounds from published trip records.
//
// Erasable syntax only: tests/test_fleet_public_layers.mjs imports it by type stripping.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {geometryIntersects, pointInGeometry} from '../../dist/geo-screen.js';
import {matchesTargetSpecies} from '../../dist/target-groups.js';
import {PROFILE_TABLE, withinDepth, type Profile} from '../profile.ts';
import {layers, profile, region, species} from '../state.ts';
import type {ChartMark} from './coastline.ts';
import {cloudLayerIds} from './clouds.ts';
import type {Engine, Overlay} from './engine.ts';
import type {MarkScreen} from './habitat.ts';
import {layerEntry, setRailNote} from './layers.ts';
import {MARK_PICK, markData, markScreen} from './marks.ts';
import {readPalette, type Palette} from './palette.ts';
import {LABEL_FONT} from './style.ts';

const REGISTRY_ID = 'charter-grounds';
export const GROUNDS_SOURCE = 'charter-grounds';
export const HATCH_SOURCE = 'charter-grounds-hatch';
/** A transparent fill: the click target for a ground's card. */
export const GROUNDS_FILL = 'charter-grounds-fill';
export const GROUNDS_HATCH = 'charter-grounds-hatch';
export const GROUNDS_LINE = 'charter-grounds-line';
export const GROUNDS_LABEL = 'charter-grounds-label';
/** Hatch spacing in degrees of longitude plus latitude: about 200 m. */
export const HATCH_STEP = 0.002;
/** Names show from this `?view=` zoom, as the protected areas' do. */
export const LABEL_MIN_ZOOM = 11;
export const BROAD = 'Broad regional name';
/** Commercial AIS's layers (web/map/commercial-ais.ts): the grounds draw under them. */
export const AIS_HEAT = 'commercial-ais-heat';
export const AIS_LINE = 'commercial-ais-line';
export const AIS_LAYERS = [AIS_HEAT, AIS_LINE] as const;
/** § 9: fleet layers draw under the cloud frames, the marks, the selection and the coastline. */
export const fleetBefore = (): string[] => [...cloudLayerIds(), MARK_PICK];

/** v1's lines (dist/charter-grounds.js) for what is not drawn. */
export const NOTES = {
  none: 'No charter grounds verified for this region',
  failed: 'Reports unavailable · see evidence',
  species: 'Only lingcod and rockfish are supported by this layer.',
  loading: 'Loading charter grounds.',
  filtered: 'Charter grounds · filtered',
} as const;

type Json = Record<string, unknown>;
export interface Ground {
  id: string; label: string; precision: string; location_confidence: string; boundary_note: string; reported_ground: string;
  map_species: string[]; report_count: number; report_dates: string[]; boats: string[]; latest_report: string;
  reports: {species: string[]}[]; latitude: number; longitude: number; geometry: {type: string; coordinates: unknown};
  area_km2: number; depth_ft: [number, number]; survey_year: number; datum: string;
}
export interface Evidence {audit_date: string; grounds: Ground[]}
type Geometry = {type: string; coordinates: unknown};
type Feature = {type: 'Feature'; geometry: Geometry; properties: Json};
export type Collection = {type: 'FeatureCollection'; features: Feature[]};

/** v1's run-time screen for a feature: ready, its anchor outside every area and its outline clear of them (`pointAllowed && geometryAllowed`). */
export function screened(at: {latitude: number; longitude: number}, geometry: unknown, screen: MarkScreen): boolean {
  return screen.status === 'ready' && !screen.boundaries.some(b => pointInGeometry([at.longitude, at.latitude], b.geometry) || geometryIntersects(geometry, b.geometry));
}

/** The grounds that draw for `target` and `profile` under `screen` (v1's `matchingGrounds` with its area and search filters left to the Fleet view). */
export function shownGrounds(evidence: Evidence | null, target: string, p: Profile, screen: MarkScreen): Ground[] {
  return (evidence?.grounds ?? []).filter(g => g.precision !== BROAD && g.map_species.some(id => matchesTargetSpecies(id, target)) &&
    g.reports.some(r => r.species.some(id => matchesTargetSpecies(id, target))) && withinDepth(p, g.depth_ft[1]) && screened(g, g.geometry, screen));
}

const rings = (g: Geometry): number[][][] => g.type === 'Polygon' ? g.coordinates as number[][][] : g.type === 'MultiPolygon' ? (g.coordinates as number[][][][]).flat() : [];

/**
 * Diagonal hatch lines clipped to a polygon (even-odd across all its rings, so holes stay open): the lines
 * lon + lat = c every `step`, cut where they cross the outline. MapLibre has no hatch fill without an image.
 */
export function hatchLines(geometry: Geometry, step = HATCH_STEP): number[][][] {
  const edges = rings(geometry).flatMap(r => r.slice(1).map((q, i) => [r[i]!, q] as const));
  if (!edges.length) return [];
  const sums = edges.flatMap(([p]) => [p[0]! + p[1]!]);
  const lines: number[][][] = [];
  const low = Math.min(...sums), high = Math.max(...sums);
  for (let k = Math.floor(low / step) + 1; k * step < high; k++) {
    const c = k * step;
    const cuts: number[][] = [];
    for (const [p, q] of edges) {
      const a = p[0]! + p[1]! - c, b = q[0]! + q[1]! - c;
      if ((a > 0) === (b > 0)) continue;
      const t = a / (a - b);
      cuts.push([p[0]! + t * (q[0]! - p[0]!), p[1]! + t * (q[1]! - p[1]!)]);
    }
    cuts.sort((x, y) => x[0]! - y[0]!);
    for (let i = 0; i + 1 < cuts.length; i += 2) lines.push([cuts[i]!, cuts[i + 1]!]);
  }
  return lines;
}

/** The outlines and their hatching, as the two GeoJSON sources. */
export function groundCollections(grounds: readonly Ground[]): {outlines: Collection; hatch: Collection} {
  return {
    outlines: {type: 'FeatureCollection', features: grounds.map(g => ({type: 'Feature', geometry: g.geometry, properties: {id: g.id, label: g.label}}))},
    hatch: {type: 'FeatureCollection', features: grounds.map(g => ({type: 'Feature', geometry: {type: 'MultiLineString', coordinates: hatchLines(g.geometry)}, properties: {id: g.id}}))},
  };
}

/** The sources and layers: a transparent pick fill, the hatch, a dashed outline and the name, in the --fleet colour. */
export function groundsOverlay(p: Palette, data: {outlines: Collection; hatch: Collection}): Overlay {
  const fleet = p.amber;
  return {
    sources: {[GROUNDS_SOURCE]: {type: 'geojson', data: data.outlines} as MapLibre.SourceSpecification, [HATCH_SOURCE]: {type: 'geojson', data: data.hatch} as MapLibre.SourceSpecification},
    layers: [
      {id: GROUNDS_FILL, type: 'fill', source: GROUNDS_SOURCE, paint: {'fill-color': fleet, 'fill-opacity': 0}},
      {id: GROUNDS_HATCH, type: 'line', source: HATCH_SOURCE, paint: {'line-color': fleet, 'line-width': 1, 'line-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0.25, 12, 0.6]}},
      {id: GROUNDS_LINE, type: 'line', source: GROUNDS_SOURCE, layout: {'line-join': 'round'}, paint: {'line-color': fleet, 'line-width': 2, 'line-dasharray': [4, 2]}},
      {id: GROUNDS_LABEL, type: 'symbol', source: GROUNDS_SOURCE, minzoom: LABEL_MIN_ZOOM - 1,
        layout: {'text-field': ['get', 'label'], 'text-font': [LABEL_FONT], 'text-size': 12, 'text-max-width': 8},
        paint: {'text-color': fleet, 'text-halo-color': p.bg, 'text-halo-width': 1.2}},
    ] as MapLibre.LayerSpecification[],
  };
}

const date = (s: string): string => new Date(`${s}T12:00:00Z`).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'});

/**
 * The mark card for a ground: v1's card lines (dist/charter-grounds.js `select`), without boat names or report links.
 * The depths are the survey raster's nominal values: the published file says its datum is unverified, so no datum is named here.
 */
export function groundMark(g: Ground, evidence: Evidence): ChartMark {
  return {
    id: `charter:${g.id}`, name: g.label, kind: `Charter-reported ground · ${g.precision}`,
    reading: `${g.report_count} reported trips · ${g.boats.length} boat${g.boats.length === 1 ? '' : 's'} · latest report ${date(g.latest_report)}. Outline survey depths ${g.depth_ft.join('–')} ft (nominal, ${g.survey_year} survey)`,
    source: `Published trip reports · research checked ${date(evidence.audit_date)}`,
    basis: `${layerEntry(REGISTRY_ID).basis} Reported area, exact stops unknown. Captains named “${g.reported_ground}”; they did not publish GPS positions or fishing depths. `
      + `Location precision: ${g.location_confidence}. Report counts are not catch rates or a popularity ranking. ${g.boundary_note}`,
  };
}

export interface GroundsState {readonly drawn: number; readonly note: string; readonly audit: string | null}
/** What the Fleet entry's legend row shows for the grounds. */
export const groundsState = signal<GroundsState>({drawn: 0, note: '', audit: null});

export interface FleetLayerOptions {engine: ReadonlySignal<Engine | null>; fetchFn?: typeof fetch; page?: () => string; palette?: () => Palette}

/** Load a region asset once per path; null when it fails. */
export function assetLoader<T>(fetchFn: typeof fetch, page: () => string, valid: (d: unknown) => boolean) {
  const cache = new Map<string, Promise<T | null>>();
  return (path: string): Promise<T | null> => {
    let p = cache.get(path);
    if (!p) cache.set(path, p = fetchFn(new URL(path, page()).href, {signal: AbortSignal.timeout(15000)})
      .then(r => r.ok ? r.json() : null).then(d => valid(d) ? d as T : null, () => null));
    return p;
  };
}

/** Draws the grounds while the Fleet entry is on; created with the Chart (web/map/chart.ts `layers`). */
export function createCharterGrounds({engine, fetchFn = (...a) => fetch(...a), page = () => location.href, palette = () => readPalette()}: FleetLayerOptions) {
  const load = assetLoader<Evidence>(fetchFn, page, d => Array.isArray((d as Evidence | null)?.grounds));
  const evidence = signal<{path: string; data: Evidence | null} | null>(null);
  const on = computed(() => layers.value.includes('fleet'));
  const path = computed(() => { const m = markData.value; return m && m.region.id === region.value ? m.region.assets?.charters ?? '' : null; });
  const target = computed(() => species.value ?? PROFILE_TABLE[profile.value].defaultTarget);
  const shown = computed(() => {
    const e = evidence.value;
    return e && e.path === path.value && e.data ? shownGrounds(e.data, target.value, profile.value, markScreen.value) : [];
  });
  let drawn = false, drawnOn: Engine | null = null;
  const disposers = [
    effect(() => {
      const p = path.value;
      if (!on.value || !p || evidence.peek()?.path === p) return;
      void load(p).then(data => { if (path.peek() === p) evidence.value = {path: p, data}; });
    }),
    effect(() => {
      const p = path.value, e = evidence.value, list = shown.value, ready = !!e && e.path === p;
      const note = !on.value ? '' : p === null ? NOTES.loading : !p ? NOTES.none : !ready ? NOTES.loading : !e.data ? NOTES.failed
        : !['lingcod', 'rockfish'].some(s => matchesTargetSpecies(s, target.value)) ? NOTES.species
        : markScreen.value.status !== 'ready' ? markScreen.value.note : list.length ? '' : NOTES.filtered;
      groundsState.value = {drawn: on.value ? list.length : 0, note, audit: ready && e.data ? e.data.audit_date : null};
      setRailNote('fleet', on.value && list.length ? `${list.length} charter ground${list.length === 1 ? '' : 's'}` : note);
    }),
    effect(() => {
      const e = engine.value, list = on.value ? shown.value : [];
      if (!e) return;
      if (!list.length) { if (drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, null); drawn = false; drawnOn = e; return; }
      const data = groundCollections(list);
      // § 9 draw order: above the seafloor, under commercial AIS, the cloud frames and the marks.
      if (!drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, groundsOverlay(palette(), data), [...AIS_LAYERS, ...fleetBefore()]);
      e.setData(GROUNDS_SOURCE, data.outlines); e.setData(HATCH_SOURCE, data.hatch);
      drawn = true; drawnOn = e;
    }),
  ];
  return {
    destroy() { for (const dispose of disposers) dispose(); groundsState.value = {drawn: 0, note: '', audit: null}; setRailNote('fleet', ''); },
    pick: {layers: [GROUNDS_FILL] as const, ordered: true, mark: (_layer: string, properties: Record<string, unknown> | null): ChartMark | null => {
      const e = evidence.peek(), g = shown.peek().find(x => x.id === properties?.id);
      return g && e?.data ? groundMark(g, e.data) : null;
    }},
  };
}

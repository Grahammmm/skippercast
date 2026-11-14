// SC1407-15: the planning route the trip dialog's "Show route on Chart" computes, drawn as one dashed line under the marks.
// Memory only: one signal the planner (web/planner.ts) owns. It is never saved, shared, exported or sent, and the route
// download never reads it. The planner clears it whenever the stops, their order, the region, the boundary screen or the
// land-water data change, or the route builder would now refuse; this file only holds, projects and draws what it is given.
//
// Erasable syntax only: tests/test_planning_route_preview.mjs imports this file by type stripping.
import {effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {region as activeRegion} from '../state.ts';
import type {Engine, Overlay} from './engine.ts';
import {MARK_PICK} from './marks.ts';
import {readPalette, type Palette} from './palette.ts';
import {PLANNING_ROUTE_SOURCE} from './layers.ts';

export const PLANNING_ROUTE_LINE = 'planning-route-line';
const REGISTRY_ID = 'planning-route';

export interface PlanningRoutePreview {
  readonly region: string;
  /** The returned route points in order, copied; never recomputed, smoothed or snapped. */
  readonly points: readonly Readonly<{latitude: number; longitude: number}>[];
  readonly nm: number;
  /** The boundary screen's own check time, as the builder returned it. */
  readonly checkedAt: string;
}
export type Collection = {type: 'FeatureCollection'; features: {type: 'Feature'; geometry: {type: 'LineString'; coordinates: number[][]}; properties: Record<string, never>}[]};

/** The one preview, or null. Only the planner's owner token may set or clear it. */
export const planningRoute = signal<PlanningRoutePreview | null>(null);
let owner: object | null = null;

/** Replace the preview with `route` (copied), for `token`'s planner; a replacement clears the old line first. */
export function publishPlanningRoute(token: object, route: PlanningRoutePreview): void {
  planningRoute.value = null;
  owner = token;
  planningRoute.value = Object.freeze({region: route.region, nm: route.nm, checkedAt: route.checkedAt,
    points: Object.freeze(route.points.map(p => Object.freeze({latitude: p.latitude, longitude: p.longitude})))});
}
/** Remove the preview if `token` published it (a stale planner cannot clear a newer one's). */
export function clearPlanningRoute(token: object): void {
  if (owner !== token) return;
  owner = null;
  planningRoute.value = null;
}

/** Exactly one LineString of the returned points ([longitude, latitude], in order), or nothing for no preview or another region's. */
export function planningRouteFeatures(route: PlanningRoutePreview | null, region: string | null): Collection {
  if (!route || route.region !== region || route.points.length < 2) return {type: 'FeatureCollection', features: []};
  return {type: 'FeatureCollection', features: [{type: 'Feature', geometry: {type: 'LineString', coordinates: route.points.map(p => [p.longitude, p.latitude])}, properties: {}}]};
}

/** One dashed line in the amber role; noninteractive (no hit layer is registered for it). */
export function planningRouteOverlay(p: Palette, data: Collection): Overlay {
  return {
    sources: {[PLANNING_ROUTE_SOURCE]: {type: 'geojson', data} as MapLibre.SourceSpecification},
    layers: [{id: PLANNING_ROUTE_LINE, type: 'line', source: PLANNING_ROUTE_SOURCE, layout: {'line-join': 'round'},
      paint: {'line-color': p.amber, 'line-width': 2.5, 'line-opacity': 0.95, 'line-dasharray': [2, 2]}}] as MapLibre.LayerSpecification[],
  };
}

export interface PlanningRouteLayerOptions {engine: ReadonlySignal<Engine | null>; palette?: () => Palette; host?: HTMLElement}

/** Draws the preview while a valid one exists for the shown region; created with the Chart (web/map/chart.ts `layers`). Destroying it only detaches the renderer. */
export function createPlanningRouteLayer({engine, palette = () => readPalette(), host}: PlanningRouteLayerOptions) {
  let drawn = false, drawnOn: Engine | null = null;
  const dispose = effect(() => {
    const e = engine.value, data = planningRouteFeatures(planningRoute.value, activeRegion.value);
    if (host) host.dataset.planningRoute = data.features.length ? '1' : '';
    if (!e) return;
    if (!data.features.length) { if (drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, null); drawn = false; drawnOn = e; return; }
    // § 9 draw order: above the reach ring, under the marks, so a mark stays on top and clickable.
    if (!drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, planningRouteOverlay(palette(), data), MARK_PICK);
    e.setData(PLANNING_ROUTE_SOURCE, data);
    drawn = true; drawnOn = e;
  });
  return {destroy() { dispose(); if (host) delete host.dataset.planningRoute; }};
}

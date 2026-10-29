// The reach ring on the Chart (#644, walkthrough slice 5; owner decision C):
// the range to consider the Boat or Kayak user saved on this device
// (web/reach.ts), drawn as a dashed circle around the region's harbor
// (web/ranking.ts `harborOrigin`) with one label naming it a straight line,
// not a route. Nothing draws for Shore or Spear, without a saved range, or
// before the region's marks name a harbor. The ring is the same great-circle
// distance "Where to look" filters by, so a listed place sits inside it.
// It never says the water inside is reachable, safe or fishable.
// Kayak's ring runs from its chosen launch (web/launches.ts) once the list
// loads, else from the harbor (#644, part 2).
//
// Erasable syntax only: tests/test_reach.mjs imports it by type stripping.
import {computed, effect, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {harborOrigin, type Origin} from '../ranking.ts';
import {launchOrigin, loadLaunchPoints} from '../launches.ts';
import {nmText, reachFor, reachRange, reachRing} from '../reach.ts';
import {profile, region} from '../state.ts';
import type {Engine, Overlay} from './engine.ts';
import {MARK_PICK, markData} from './marks.ts';
import {readPalette, type Palette} from './palette.ts';
import {LABEL_FONT} from './style.ts';

const REGISTRY_ID = 'reach';
export const REACH_SOURCE = 'reach';
export const REACH_LINE = 'reach-line';
export const REACH_LABEL = 'reach-label';

type Feature = {type: 'Feature'; geometry: {type: string; coordinates: unknown}; properties: Record<string, unknown>};
export type Collection = {type: 'FeatureCollection'; features: Feature[]};

/** The ring's label: the range, where it runs from, and that it is not a route. */
export const reachLabel = (nm: number, harbor: string): string => `${nmText(nm)} from ${harbor} · straight line, not a route`;

/** The ring as a line and its label at the ring's northernmost point; empty without an origin or a range. */
export function reachFeatures(origin: Origin | null, nm: number | null): Collection {
  if (!origin || nm === null || !(nm > 0)) return {type: 'FeatureCollection', features: []};
  const ring = reachRing(origin, nm);
  return {type: 'FeatureCollection', features: [
    {type: 'Feature', geometry: {type: 'LineString', coordinates: ring}, properties: {kind: 'ring', nm}},
    {type: 'Feature', geometry: {type: 'Point', coordinates: ring[0]!}, properties: {kind: 'label', label: reachLabel(nm, origin.name)}},
  ]};
}

/** A dashed --blue line and its label, haloed in the background colour. */
export function reachOverlay(p: Palette, data: Collection): Overlay {
  return {
    sources: {[REACH_SOURCE]: {type: 'geojson', data} as MapLibre.SourceSpecification},
    layers: [
      {id: REACH_LINE, type: 'line', source: REACH_SOURCE, filter: ['==', ['get', 'kind'], 'ring'], layout: {'line-join': 'round'},
        paint: {'line-color': p.blue, 'line-width': 1.5, 'line-opacity': 0.85, 'line-dasharray': [3, 3]}},
      {id: REACH_LABEL, type: 'symbol', source: REACH_SOURCE, filter: ['==', ['get', 'kind'], 'label'],
        layout: {'text-field': ['get', 'label'], 'text-font': [LABEL_FONT], 'text-size': 12, 'text-anchor': 'bottom', 'text-offset': [0, -0.4], 'text-allow-overlap': true},
        paint: {'text-color': p.blue, 'text-halo-color': p.bg, 'text-halo-width': 1.2}},
    ] as MapLibre.LayerSpecification[],
  };
}

export interface ReachLayerOptions {engine: ReadonlySignal<Engine | null>; palette?: () => Palette; host?: HTMLElement}

/** Draws the ring while the profile has a saved range and the region names a harbor; created with the Chart (web/map/chart.ts `layers`). */
export function createReach({engine, palette = () => readPalette(), host}: ReachLayerOptions) {
  const origin = computed(() => {
    const m = markData.value, id = region.value;
    if (!m || m.region.id !== id) return null;
    return (profile.value === 'kayak' ? launchOrigin(id) : null) ?? harborOrigin(m);
  });
  const launches = effect(() => { const id = region.value; if (id && profile.value === 'kayak' && typeof location !== 'undefined') void loadLaunchPoints(id); });
  const data = computed(() => { void reachRange.value; return reachFeatures(origin.value, reachFor(profile.value)); });
  let drawn = false, drawnOn: Engine | null = null, stopIdle: (() => void) | null = null;
  // The host's `data-reach-drawn` reports how many ring features MapLibre drew in view at the last idle.
  const watch = effect(() => {
    const e = engine.value;
    stopIdle?.(); stopIdle = null;
    if (e && host) stopIdle = e.view.on('idle', () => { host.dataset.reachDrawn = String(drawn ? e.rendered(REACH_LINE) : 0); });
  });
  const dispose = effect(() => {
    const e = engine.value, d = data.value;
    if (host) host.dataset.reach = d.features.length ? String(d.features[0]!.properties.nm) : '';
    if (!e) return;
    if (!d.features.length) { if (drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, null); drawn = false; drawnOn = e; return; }
    // § 9 draw order: above the fields and the fleet layers, under the marks, so a mark stays on top and clickable.
    if (!drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, reachOverlay(palette(), d), MARK_PICK);
    e.setData(REACH_SOURCE, d);
    drawn = true; drawnOn = e;
  });
  return {destroy() { dispose(); watch(); launches(); stopIdle?.(); if (host) { delete host.dataset.reach; delete host.dataset.reachDrawn; } }};
}

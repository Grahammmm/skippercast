// Commercial AIS 2024 on the Chart (FE-21, docs/plans/front-end/design.md § 9):
// the Charter fleet entry's option, off by default as in v1. The region's
// published aggregate (region.json `assets.commercial_ais`,
// data/commercial-ais-effort.geojson, the file dist/commercial-ais.js draws for
// v1): a few 0.01° grid cells of repeat-day apparent commercial fishing effort
// from Global Fishing Watch's v3 dataset, July and September 2024, as a heat
// fill in --fleet (--amber) whose opacity follows the cell's apparent fishing
// hours. v1's run-time protected-area screen applies (`pointAllowed` and
// `geometryAllowed`, as the charter grounds). The copy is v1's own, verbatim:
// apparent activity, never a verified catch spot, depth and species unknown.
// No position, track or vessel identifier is added here; the file is drawn as published.
//
// Erasable syntax only: tests/test_fleet_public_layers.mjs imports it by type stripping.
import {computed, effect, signal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {layers, region} from '../state.ts';
import {AIS_HEAT, AIS_LINE, aisBefore, assetLoader, screened, type Collection, type FleetLayerOptions} from './charter-grounds.ts';
import type {ChartMark} from './coastline.ts';
import type {Engine, Overlay} from './engine.ts';
import type {MarkScreen} from './habitat.ts';
import {layerEntry} from './layers.ts';
import {markData, markScreen} from './marks.ts';
import {readPalette, type Palette} from './palette.ts';

const REGISTRY_ID = 'commercial-ais';
export const AIS_SOURCE = 'commercial-ais';
export {AIS_HEAT, AIS_LINE};
/** The heat's opacity from no apparent fishing to the most in the drawn cells. */
export const HEAT_OPACITY: readonly [number, number] = [0.15, 0.45];

/** v1's lines (dist/commercial-ais.js). */
export const AIS_NOTES = {
  none: 'No reviewed commercial AIS layer for this region.',
  failed: 'Historical commercial AIS unavailable.',
  loading: 'Loading commercial AIS.',
} as const;
/** The source credit, verbatim from dist/commercial-ais.html. */
export const AIS_CREDIT = '© Global Fishing Watch. 2025. Global AIS-based Apparent Fishing Effort Dataset v3.0. SkipperCast extracted the region, applied a repeat-day filter and excluded MPAs.';
/** v1's status line for the drawn cells. */
export const aisSummary = (n: number): string => `${n} historical grid cells · Jul & Sep 2024 · depth unknown`;

export interface AisProps {
  id: string; label: string; gear_label: string; resolution_note: string; fishing_location_confidence: string; vessel_count_note: string;
  days_with_apparent_fishing: number; apparent_fishing_hours: number; active_dates_utc: string[]; latitude: number; longitude: number;
  attribution: string; source_url: string;
}
export interface AisFeature {type: 'Feature'; geometry: {type: string; coordinates: unknown}; properties: AisProps}
export interface AisCollection {type: 'FeatureCollection'; features: AisFeature[]}

/** The cells v1 draws: every published cell its run-time screen admits. */
export const shownCells = (data: AisCollection | null, screen: MarkScreen): AisFeature[] =>
  (data?.features ?? []).filter(f => screened(f.properties, f.geometry, screen));

/** The cells as the one GeoJSON source: geometry as published, with its id and hours. */
export const cellCollection = (cells: readonly AisFeature[]): Collection => ({type: 'FeatureCollection',
  features: cells.map(f => ({type: 'Feature', geometry: f.geometry, properties: {id: f.properties.id, hours: f.properties.apparent_fishing_hours}}))});

/** The heat fill and its outline in the --fleet colour; opacity rises with the cell's apparent fishing hours. */
export function aisOverlay(p: Palette, data: Collection): Overlay {
  const most = Math.max(1, ...data.features.map(f => Number(f.properties.hours) || 0));
  return {
    sources: {[AIS_SOURCE]: {type: 'geojson', data, attribution: layerEntry(REGISTRY_ID).attribution} as MapLibre.SourceSpecification},
    layers: [
      {id: AIS_HEAT, type: 'fill', source: AIS_SOURCE, paint: {'fill-color': p.amber, 'fill-opacity': ['interpolate', ['linear'], ['get', 'hours'], 0, HEAT_OPACITY[0], most, HEAT_OPACITY[1]]}},
      {id: AIS_LINE, type: 'line', source: AIS_SOURCE, paint: {'line-color': p.amber, 'line-width': 1.5}},
    ] as MapLibre.LayerSpecification[],
  };
}

const hours = (n: number): string => n.toLocaleString('en-US', {maximumFractionDigits: 1});

/** The mark card for a cell: v1's card lines (dist/commercial-ais.js `select`). */
export function aisMark(p: AisProps): ChartMark {
  return {
    id: `ais:${p.id}`, name: p.label, kind: 'Commercial AIS · historical 2024',
    reading: `${p.days_with_apparent_fishing} days with activity · ${hours(p.apparent_fishing_hours)} hr apparent fishing time. Apparent fishing activity, not a verified catch spot.`,
    source: `${p.attribution} Activity dates (UTC): ${p.active_dates_utc.join(', ')}`,
    basis: `${layerEntry(REGISTRY_ID).basis} Depth and target species unknown. This offshore context is not qualified for the 200-foot fishing limit. ${p.resolution_note} `
      + `Gear classification: ${p.gear_label}. ${p.fishing_location_confidence}. Local sportfishing-charter identity remains unverified. ${p.vessel_count_note}`,
  };
}

/** The Fleet entry's option (v1's "Show commercial AIS areas"): off by default. */
export const aisOn = signal(false);
export interface AisState {readonly offered: boolean; readonly drawn: number; readonly note: string}
export const aisState = signal<AisState>({offered: false, drawn: 0, note: ''});

/** Draws the cells while the Fleet entry and its option are on; created with the Chart (web/map/chart.ts `layers`). */
export function createCommercialAis({engine, fetchFn = (...a) => fetch(...a), page = () => location.href, palette = () => readPalette()}: FleetLayerOptions) {
  const load = assetLoader<AisCollection>(fetchFn, page, d => (d as AisCollection | null)?.type === 'FeatureCollection' && Array.isArray((d as AisCollection).features));
  const loaded = signal<{path: string; data: AisCollection | null} | null>(null);
  const on = computed(() => layers.value.includes('fleet') && aisOn.value);
  const path = computed(() => { const m = markData.value; return m && m.region.id === region.value ? m.region.assets?.commercial_ais ?? '' : null; });
  const cells = computed(() => { const l = loaded.value; return l && l.path === path.value && l.data ? shownCells(l.data, markScreen.value) : []; });
  let drawn = false, drawnOn: Engine | null = null;
  const disposers = [
    effect(() => {
      const p = path.value;
      if (!on.value || !p || loaded.peek()?.path === p) return;
      void load(p).then(data => { if (path.peek() === p) loaded.value = {path: p, data}; });
    }),
    effect(() => {
      const p = path.value, l = loaded.value, list = cells.value, ready = !!l && l.path === p;
      const note = !on.value ? '' : p === null || !ready && !!p ? AIS_NOTES.loading : !p ? AIS_NOTES.none : !l!.data ? AIS_NOTES.failed
        : markScreen.value.status !== 'ready' ? markScreen.value.note : aisSummary(list.length);
      aisState.value = {offered: !!p, drawn: on.value ? list.length : 0, note};
    }),
    effect(() => {
      const e = engine.value, list = on.value ? cells.value : [];
      if (!e) return;
      if (!list.length) { if (drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, null); drawn = false; drawnOn = e; return; }
      const data = cellCollection(list);
      // § 9 draw order: above the charter grounds, under the fleet activity layers, the cloud frames and the marks.
      if (!drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, aisOverlay(palette(), data), aisBefore());
      e.setData(AIS_SOURCE, data);
      drawn = true; drawnOn = e;
    }),
  ];
  return {
    destroy() { for (const dispose of disposers) dispose(); aisState.value = {offered: false, drawn: 0, note: ''}; },
    pick: {layers: [AIS_HEAT] as const, ordered: true, mark: (_layer: string, properties: Record<string, unknown> | null): ChartMark | null => {
      const f = cells.peek().find(x => x.properties.id === properties?.id);
      return f ? aisMark(f.properties) : null;
    }},
  };
}

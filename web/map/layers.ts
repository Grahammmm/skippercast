// The layer registry (FE-11, docs/plans/front-end/design.md § 9, § 3A.2): every
// map layer once, in draw order from the bottom up, with the presentations it
// draws in, its rail entry, the MapLibre sources it owns, its time behaviour,
// its legend and its basis sentence. The Chart (web/map/chart.ts) draws the
// entries it has a drawing for, and a source error marks only the entry that
// owns the source unavailable (sourceLayer). Later tasks fill in the entries
// whose `task` is theirs; the order and the presentations are fixed here.
// An entry that also draws on the terrain (FE-82: MPAs, reef marks, charter
// grounds) names its `terrain` drape in the same palette roles as its Chart
// style; the layer that loads its features publishes them (setTerrainLayer)
// and web/map/stage.ts hands them to the renderer's setOverlay.
//
// Erasable syntax only: tests/test_map_layers.mjs imports this file by type stripping.
import {batch, signal} from '@preact/signals';
import type {CoastOverlayColor, CoastOverlayFeature, CoastOverlayKind} from '../../packages/coast/src/embed-types.ts';
import type {Presentation} from '../coast-context.ts';
import type {RailId} from '../profile.ts';
import type {ChartMark} from './coastline.ts';
import type {Palette, PaletteKey} from './palette.ts';
import type {StatusPart} from './status-copy.ts';
import {BASEMAP_ATTRIBUTION, BASEMAP_SOURCE} from './style.ts';
// Types only: the stacking engine (and the generated layer tokens it reads) stays out of the app's first load.
import type {KitLayerId} from './stacking.ts';
import {t, type Language, type StringId} from '../i18n.ts';

/** Where a layer draws: the MapLibre Chart, the packages/coast terrain (2D and 3D), or both. */
export type LayerPresentation = 'chart' | 'terrain';
/** `static` never changes with the clock; `hour` follows the dock's forecast hour; `observed` shows real frames only. */
export type TimeBehaviour = 'static' | 'hour' | 'observed';
/** A rail entry, a base (one at a time, under the fields), or always drawn where its gate allows. */
export type LayerControl = RailId | 'base' | 'always';
export interface LegendRow {readonly label: string; readonly swatch?: PaletteKey}
/** Palette keys the terrain's overlays accept (packages/coast COAST_OVERLAY_COLORS). */
export type OverlayRole = CoastOverlayColor & PaletteKey;
/**
 * How an entry drapes on the terrain (packages/coast `setOverlay`): its Chart style's palette roles, never a colour.
 * `opacity` is a number or the palette key that carries it as CSS text (the protected-area fill's token).
 */
export interface TerrainDrape {
  readonly kind: CoastOverlayKind;
  readonly color: OverlayRole;
  readonly opacity?: number | 'mpaFillOpacity';
  readonly outline?: OverlayRole;
  readonly outlineOpacity?: number;
  /** A point's diameter in CSS pixels. */
  readonly size?: number;
}

export interface LayerEntry {
  readonly id: string;
  readonly label: string;
  readonly control: LayerControl;
  readonly presentations: readonly LayerPresentation[];
  /** MapLibre source ids the Chart adds for this layer; errors on them mark this layer unavailable. */
  readonly sources: readonly string[];
  readonly time: readonly TimeBehaviour[];
  /** One sentence: the product, its resolution and its age rule (D13). */
  readonly basis: string;
  readonly legend: readonly LegendRow[];
  /** Credit shown in the legend's attribution row while the layer is drawn. */
  readonly attribution?: string;
  /** When the layer may draw beyond its control: a zoom, a profile, an admin session. */
  readonly gate?: string;
  /** The dev-plan task that draws it. */
  readonly task: string;
  /** Its drape on the terrain, for an entry whose presentations include `terrain` and that the registry drapes (FE-82). */
  readonly terrain?: TerrainDrape;
}

export const COASTLINE_SOURCE = 'coastline';
export const ENC_SOURCE = 'enc';
/** Chart overlay for a region whose reviewed pointer resolves `ready`; not the terrain's `relief` entry or the Seafloor type rail. */
export const BOTTOM_RELIEF = 'bottom-relief';
/**
 * MSK-2: the kit's intended bottom-to-top slots (`overlays.draw_order`), mapped to MapLibre IDs. The relief raster adds a
 * per-attach suffix; the `nearshore-*` IDs are reserved for MSK-6 (hard edge, rock piles, pier and cast arcs).
 * The live Chart follows it through the `before` anchors each controller hands to `setOverlay`: the colour fields (water
 * temperature, chlorophyll, swell, in that order) go under DEPTH_BOTTOM and the contours under the basemap's place labels
 * (`PLACE_LABELS`, the top slot), whichever of them arrives first and with or without Swell. tests/test_map_layers.mjs
 * pins the slot mapping and the live insertion order.
 */
export const NEARSHORE_HARD_EDGE = 'nearshore-hard-edge';
export const NEARSHORE_PILE_OUTLINE = 'nearshore-pile-outline';
export const NEARSHORE_PILE_LABEL = 'nearshore-pile-label';
export const NEARSHORE_PIER = 'nearshore-pier';
export const NEARSHORE_CAST_ARCS = 'nearshore-cast-arcs';
export const NEARSHORE_DRAW_ORDER: readonly (readonly string[])[] = Object.freeze([
  [BOTTOM_RELIEF], ['water-temp', 'chlorophyll', 'swell'], ['depth-contours-line'], ['depth-contours-line-index'],
  [NEARSHORE_HARD_EDGE], [NEARSHORE_PILE_OUTLINE], ['depth-contours-label'], [NEARSHORE_PILE_LABEL],
  [NEARSHORE_PIER, NEARSHORE_CAST_ARCS], ['labels-places'],
]);

/**
 * MSKL-3: the layer kit's draw order (`stacking.z_order`, base relief z0 … labels z11) as MapLibre `before` anchors. Each slot
 * lists the run-time layers drawn in it, bottom-up: the web's own layers in their kit slot (an overlay names its lowest layer),
 * then the generated fragment's `skl-*` layers (stacking.ts SKL_SLOT_LAYERS). `zBefore(id)` is every layer above `id`, nearest
 * first, so the engine inserts an overlay under the nearest one already drawn and the order never depends on arrival.
 * SST contrast cells are the break glow's colour-field role (the fragment puts `skl-sst-breaks-glow` there); fronts are
 * isolines and the wind arrows are the arrow/barb slot, so both draw above the depth contours as the kit orders them.
 * The static Chart style (chart.ts chartStyle) still adds protected areas, habitat, marks and the coastline above the
 * basemap's labels; `mpa-fill` is therefore the last anchor, for a map without basemap labels.
 * IDs are literal here (no import of each layer module, which imports this registry, nor of the generated layer tokens, which
 * would add the whole token table to the first load); tests/test_stacking.mjs pins the slots to `stacking.z_order`, the
 * `skl-*` IDs to the generated fragment and the web IDs to the modules' constants.
 */
/** `stacking.z_order` slot ids, bottom-up. */
export const Z_SLOTS = Object.freeze(['base-relief', 'color-field', 'veils', 'radar', 'depth-contours', 'polygons', 'isolines', 'particles',
  'arrows-barbs', 'routes', 'points', 'labels'] as const);
export type ZSlot = typeof Z_SLOTS[number];
const WEB_SLOT_LAYERS: Readonly<Partial<Record<ZSlot, readonly string[]>>> = Object.freeze({
  'base-relief': [BOTTOM_RELIEF],
  'color-field': ['water-temp', 'sst-contrast', 'chlorophyll', 'swell'],
  'depth-contours': ['depth-contours-unresolved-fill'],
  isolines: ['sst-fronts-band'],
  'arrows-barbs': ['wind-casing'],
  labels: ['labels-places'],
});
/** style/generated/maplibre-layers-v1.0.0.json's `skl-*` layers by `skippercast:z`, in fragment order. */
export const SKL_SLOT_LAYERS: Readonly<Record<ZSlot, readonly string[]>> = Object.freeze({
  'base-relief': [],
  'color-field': ['skl-sst-fill-fill', 'skl-chlorophyll-fill', 'skl-kd490-fill', 'skl-currents-fill', 'skl-subsurface-temp-fill', 'skl-salinity-fill',
    'skl-wind-fill', 'skl-waves-swell-fill', 'skl-visibility-fog-fill', 'skl-sst-breaks-glow'],
  veils: ['skl-clouds-veil', 'skl-sea-ice-veil'],
  radar: ['skl-radar'],
  'depth-contours': [],
  polygons: ['skl-hazard-fill', 'skl-zone-line', 'skl-mpa-fill', 'skl-mpa-line', 'skl-kelp', 'skl-shore-halo', 'skl-shore', 'skl-ais-fill', 'skl-ais-line',
    'skl-upwelling-ribbon'],
  isolines: ['skl-sst-band-edge', 'skl-sea-ice-edge', 'skl-sst-iso-minor', 'skl-sst-iso-index', 'skl-ssh-positive', 'skl-ssh-negative', 'skl-ssh-zero',
    'skl-isobar-minor', 'skl-isobar-bold'],
  particles: ['skl-currents-streamlines', 'skl-wind-particles'],
  'arrows-barbs': ['skl-wind-barbs', 'skl-wave-arrows'],
  routes: ['skl-track', 'skl-route-halo', 'skl-route'],
  points: ['skl-waypoint', 'skl-pier-halo', 'skl-pier', 'skl-ramp', 'skl-tide-pin', 'skl-station-pin', 'skl-spot-others', 'skl-spot-badge'],
  labels: ['skl-sst-iso-label', 'skl-isobar-label', 'skl-pressure-centers', 'skl-zone-label', 'skl-mpa-label', 'skl-ais-label', 'skl-waypoint-num',
    'skl-leg-label', 'skl-station-chip', 'skl-spot-rank'],
});
const STATIC_TOP = 'mpa-fill';
/**
 * `skl-*` layers a web overlay already draws inside its own group (an overlay is inserted whole under one anchor): the SST
 * band edges are part of the water-temp overlay (sst-bands.ts SST_BAND_EDGE), so they move with it and are no anchor.
 */
const IN_WEB_GROUP: readonly string[] = ['skl-sst-band-edge'];
/** Every z_order slot's anchors, bottom-up. */
export const Z_ORDER_ANCHORS: readonly {readonly slot: ZSlot; readonly layers: readonly string[]}[] = Object.freeze(
  Z_SLOTS.map(slot => Object.freeze({slot, layers: Object.freeze([...WEB_SLOT_LAYERS[slot] ?? [], ...SKL_SLOT_LAYERS[slot].filter(id => !IN_WEB_GROUP.includes(id))])})));
/** The MapLibre layers an overlay whose lowest layer is `layer` (or which draws in slot `layer`) goes under, nearest first. */
export function zBefore(layer: string): string[] {
  const at = Z_ORDER_ANCHORS.findIndex(s => s.slot === layer || s.layers.includes(layer));
  if (at < 0) throw new Error(t('dev.unknownLayer', 'en', {id: layer}));
  const own = Z_ORDER_ANCHORS[at]!, rest = own.slot === layer ? [] : own.layers.slice(own.layers.indexOf(layer) + 1);
  return [...rest, ...Z_ORDER_ANCHORS.slice(at + 1).flatMap(s => s.layers), STATIC_TOP];
}

/**
 * MSKL-3: one registry row per kit layer (style/layers-v1.0.0.json, 01 sst-fill … 24 ais-fleet). `appIds` are the
 * registry entries that draw it today (the token's `app_layer_ids` that exist here). `noData` layers have no authorized
 * live source (LAYERS-KIT-PLAN § 2): their module (web/map/kit-layers/<id>.ts) draws nothing, never switches itself on,
 * and their legend row says "no data yet". Copy: `layer.skl.<id>.label`.
 */
export interface KitLayerRow {readonly id: KitLayerId; readonly appIds: readonly string[]; readonly noData: boolean; readonly labelId: StringId}
export const NO_DATA_YET: readonly KitLayerId[] = Object.freeze(['kd490', 'ssh', 'upwelling', 'subsurface-temp', 'salinity', 'sea-ice', 'pressure', 'precip-radar', 'visibility-fog']);
/**
 * DATA-LIVE-9 (E2E-16): who may ask for the relief overlay. Everyone, signed out included, on the Chart in the coast view
 * while the base map works; there is deliberately no admin or preview input. The pointer then decides: no `ready`
 * pointer means nothing is drawn and no archive or tile is requested. The private Morro study preview and this overlay
 * would both paint the seabed, so the study preview, when an admin turns it on, takes the Chart.
 */
export const reliefWanted = (s: {presentation: string; view: string; basemapAvailable: boolean; studyPreviewOn: boolean}) =>
  s.presentation === 'chart' && s.view === 'coast' && s.basemapAvailable && !s.studyPreviewOn;
/** The seafloor publication's admitted features (web/map/seafloor.ts, FE-14). */
export const SEAFLOOR_SOURCE = 'seafloor';
/** FE-18's GeoJSON sources (web/map/marks.ts): survey habitat, geology, atlas reef marks and the selection. */
export const SURVEY_SOURCE = 'survey-habitat';
export const GEOLOGY_SOURCE = 'geology';
export const MARKS_SOURCE = 'marks';
/** The same marks as a density below `?view=` zoom 10 (#620); the Marks entry owns it. */
export const DENSITY_SOURCE = 'marks-density';
export const SELECTION_SOURCE = 'selection';
/** The trip planner's ranked spots (web/map/ranked.ts, #495). */
export const RANKED_SOURCE = 'trip-ranked';
/** The signed-in owner's private saved spots (web/map/saved-spots.ts, SC0922-04); in memory only. */
export const SAVED_SPOTS_SOURCE = 'private-saved-spots';
/** The trip dialog's ephemeral planning route (web/map/planning-route.ts, SC1407-15); memory only. */
export const PLANNING_ROUTE_SOURCE = 'planning-route';
/** Temp contrast's supported analysis cells (web/map/contrast.ts, CI6-03). */
export const CONTRAST_SOURCE = 'sst-contrast';
/** Temp fronts' observed edges (web/map/fronts.ts, BF-sst-fronts). */
export const FRONTS_SOURCE = 'sst-fronts';
export const COASTLINE_ATTRIBUTION = t('layer.attr.coastline', 'en');
export const ENC_ATTRIBUTION = t('layer.attr.enc', 'en');
export const MPA_SOURCE = 'mpas';
/** The region's shelf depth contours (web/map/depth-contours.ts, CI6-13). */
export const DEPTH_CONTOURS_SOURCE = 'depth-contours';
/**
 * The on-map CC BY 4.0 credit for ds582 (catalog `cdfw-mpas`): creator, dataset, licence. The legend
 * row's basis gives it in full with the metadata and licence links. Kept short so that, beside the
 * coastline credit, MapLibre's attribution stays one line on a phone: the box paints when MapLibre
 * loads, and a wrapped box becomes the page's largest paint (the LCP budget, design § 13).
 */
export const MPA_ATTRIBUTION = t('layer.attr.mpa', 'en');

const STATIC: readonly TimeBehaviour[] = ['static'];
const entry = (e: Omit<LayerEntry, 'sources' | 'legend' | 'time'> & Partial<Pick<LayerEntry, 'sources' | 'legend' | 'time'>>): LayerEntry =>
  Object.freeze({sources: [], legend: [], time: STATIC, ...e});

/** § 9 draw order, bottom to top. The ENC chart sits with the bases, above the aerial. */
const build = (lang: Language): readonly LayerEntry[] => Object.freeze([
  entry({id: 'basemap', label: copy('basemap', 'label', lang), control: 'base', presentations: ['chart'], sources: [BASEMAP_SOURCE], attribution: BASEMAP_ATTRIBUTION,
    basis: copy('basemap', 'basis', lang), task: 'FE-10'}),
  entry({id: 'aerial', label: copy('aerial', 'label', lang), control: 'base', presentations: ['chart'],
    basis: copy('aerial', 'basis', lang), task: 'FE-23'}),
  entry({id: 'chart', label: copy('chart', 'label', lang), control: 'base', presentations: ['chart'], sources: [ENC_SOURCE], attribution: ENC_ATTRIBUTION, gate: 'zoom ≥ 10',
    basis: copy('chart', 'basis', lang), task: 'FE-11'}),
  // The renderer always draws the terrain itself; the Seafloor entry holds its options and its reefs and pins (FE-80).
  entry({id: 'relief', label: copy('relief', 'label', lang), control: 'seafloor', presentations: ['terrain'],
    basis: copy('relief', 'basis', lang), task: 'FE-80'}),
  entry({id: 'water-temp', label: copy('water-temp', 'label', lang), control: 'water-temp', presentations: ['chart'], time: ['observed'], legend: [{label: copy('water-temp', 'legend0', lang), swatch: 'sst0'}],
    basis: copy('water-temp', 'basis', lang), task: 'FE-16'}),
  entry({id: 'water-temp-contours', label: copy('water-temp-contours', 'label', lang), control: 'water-temp', presentations: ['chart'], time: ['observed'],
    basis: copy('water-temp-contours', 'basis', lang), task: 'FE-16'}),
  // CI6-03: its own rail entry, off by default, because Water temp (on by default for Shore) must not turn it on.
  entry({id: 'sst-contrast', label: copy('sst-contrast', 'label', lang), control: 'sst-contrast', presentations: ['chart'], time: ['observed'], sources: [CONTRAST_SOURCE],
    attribution: t('layer.attr.sst', 'en'),
    legend: [{label: copy('sst-contrast', 'legend0', lang), swatch: 'contrast1'}],
    basis: copy('sst-contrast', 'basis', lang),
    task: 'CI6-03'}),
  // BF-sst-fronts: observed fronts as edges with their age and an uncertainty band; its own rail entry, off by default, beside (never in place of) Temp contrast.
  entry({id: 'sst-fronts', label: copy('sst-fronts', 'label', lang), control: 'sst-fronts', presentations: ['chart'], time: ['observed'], sources: [FRONTS_SOURCE],
    attribution: t('layer.attr.sst', 'en'),
    legend: [{label: copy('sst-fronts', 'legend0', lang), swatch: 'contrast2'}],
    basis: copy('sst-fronts', 'basis', lang),
    task: 'CI6-15'}),
  entry({id: 'chlorophyll', label: copy('chlorophyll', 'label', lang), control: 'chlorophyll', presentations: ['chart'], sources: ['chlorophyll'], time: ['observed'],
    legend: [{label: '≤0.01 mg/m³', swatch: 'depth0'}, {label: '0.1 mg/m³', swatch: 'blue'}, {label: '1 mg/m³', swatch: 'mint'}, {label: '10 mg/m³', swatch: 'amber'}, {label: '100 mg/m³', swatch: 'coral'}],
    attribution: t('layer.attr.chlorophyll', 'en'),
    basis: copy('chlorophyll', 'basis', lang), task: 'CI6-08'}),
  entry({id: 'swell', label: copy('swell', 'label', lang), control: 'swell', presentations: ['chart'], time: ['hour'], legend: [{label: copy('swell', 'legend0', lang), swatch: 'swell2'}],
    basis: copy('swell', 'basis', lang), task: 'FE-17'}),
  entry({id: 'wind', label: copy('wind', 'label', lang), control: 'swell', presentations: ['chart'], sources: ['wind-arrows', 'wind-labels'], time: ['hour'],
    attribution: 'NOAA NCEP', legend: [{label: copy('wind', 'legend0', lang), swatch: 'mapInk'}],
    basis: copy('wind', 'basis', lang), task: 'CI6-10'}),
  // CI6-13: shelf contours from reviewed survey grids, every zoom, Chart only; the ENC base above zoom 10 is unchanged.
  entry({id: 'depth-contours', label: copy('depth-contours', 'label', lang), control: 'always', presentations: ['chart'], sources: [DEPTH_CONTOURS_SOURCE],
    attribution: t('layer.attr.depth', 'en'), legend: [{label: copy('depth-contours', 'legend0', lang), swatch: 'sknContourIndex'}, {label: copy('depth-contours', 'legend1', lang), swatch: 'mapLabel'}],
    basis: copy('depth-contours', 'basis', lang), task: 'CI6-13'}),

  entry({id: 'mpas', label: copy('mpas', 'label', lang), control: 'always', presentations: ['chart', 'terrain'],
    terrain: {kind: 'fill', color: 'mpaFill', opacity: 'mpaFillOpacity', outline: 'mpaLine'}, sources: [MPA_SOURCE], attribution: MPA_ATTRIBUTION,
    legend: [{label: copy('mpas', 'legend0', lang), swatch: 'mpaLine'}],
    basis: copy('mpas', 'basis', lang), task: 'FE-19'}),
  entry({id: 'habitat', label: copy('habitat', 'label', lang), control: 'always', presentations: ['chart'], gate: 'zoom ≥ 10', sources: [SURVEY_SOURCE, GEOLOGY_SOURCE],
    legend: [{label: copy('habitat', 'legend0', lang), swatch: 'habRock'}, {label: copy('habitat', 'legend1', lang), swatch: 'habMixed'}, {label: copy('habitat', 'legend2', lang), swatch: 'habSoft'}, {label: copy('habitat', 'legend3', lang), swatch: 'habKelp'}],
    basis: copy('habitat', 'basis', lang), task: 'FE-18'}),
  entry({id: 'shore-runs', label: copy('shore-runs', 'label', lang), control: 'always', presentations: ['chart'], gate: 'profile = shore', sources: ['shore-runs', 'shore-access'],
    legend: [{label: copy('shore-runs', 'legend0', lang), swatch: 'amber'}, {label: copy('shore-runs', 'legend1', lang), swatch: 'amber'}],
    basis: copy('shore-runs', 'basis', lang), task: 'FE-36'}),
  entry({id: 'seafloor', label: copy('seafloor', 'label', lang), control: 'seafloor', presentations: ['chart'], sources: [SEAFLOOR_SOURCE],
    legend: [{label: copy('seafloor', 'legend0', lang), swatch: 'depth0'}, {label: copy('seafloor', 'legend1', lang), swatch: 'depth2'}, {label: copy('seafloor', 'legend2', lang), swatch: 'depth3'}],
    basis: copy('seafloor', 'basis', lang), task: 'FE-14'}),
  // FE-21: v1's own sentences, verbatim (dist/charter-grounds.js; dist/commercial-ais.html), pinned by tests/test_fleet_public_layers.mjs.
  // On the terrain the hatch reads as a faint fill of the same colour: the drape has no line pattern.
  entry({id: 'charter-grounds', label: copy('charter-grounds', 'label', lang), control: 'fleet', presentations: ['chart', 'terrain'],
    terrain: {kind: 'fill', color: 'amber', opacity: 0.15, outline: 'amber'}, sources: ['charter-grounds', 'charter-grounds-hatch'],
    legend: [{label: copy('charter-grounds', 'legend0', lang), swatch: 'amber'}],
    basis: copy('charter-grounds', 'basis', lang), task: 'FE-21'}),
  entry({id: 'commercial-ais', label: copy('commercial-ais', 'label', lang), control: 'fleet', presentations: ['chart'], sources: ['commercial-ais'], attribution: t('layer.attr.ais', 'en'),
    legend: [{label: copy('commercial-ais', 'legend0', lang), swatch: 'amber'}],
    basis: copy('commercial-ais', 'basis', lang), task: 'FE-21'}),
  entry({id: 'fleet-heat', label: copy('fleet-heat', 'label', lang), control: 'fleet', presentations: ['chart'], gate: 'admin', sources: ['fleet-heat'],
    legend: [{label: copy('fleet-heat', 'legend0', lang), swatch: 'amber'}],
    basis: copy('fleet-heat', 'basis', lang), task: 'FE-24'}),
  entry({id: 'fleet-tracks', label: copy('fleet-tracks', 'label', lang), control: 'fleet', presentations: ['chart'], gate: 'admin', sources: ['fleet-tracks'],
    legend: [{label: copy('fleet-tracks', 'legend0', lang), swatch: 'amber'}],
    basis: copy('fleet-tracks', 'basis', lang), task: 'FE-24'}),
  entry({id: 'fleet-events', label: copy('fleet-events', 'label', lang), control: 'fleet', presentations: ['chart'], gate: 'admin', sources: ['fleet-events'],
    legend: [{label: copy('fleet-events', 'legend0', lang), swatch: 'amber'}],
    basis: copy('fleet-events', 'basis', lang), task: 'FE-24'}),
  entry({id: 'currents', label: copy('currents', 'label', lang), control: 'currents', presentations: ['chart', 'terrain'], time: ['hour', 'observed'], legend: [{label: copy('currents', 'legend0', lang), swatch: 'flow'}, {label: copy('currents', 'legend1', lang), swatch: 'flowFast'}],
    basis: copy('currents', 'basis', lang), task: 'FE-15'}),
  entry({id: 'clouds', label: copy('clouds', 'label', lang), control: 'clouds', presentations: ['chart'], time: ['observed'],
    basis: copy('clouds', 'basis', lang), task: 'FE-22'}),
  // #644: the Boat or Kayak range to consider, around the harbor; under the marks so they stay on top.
  entry({id: 'reach', label: copy('reach', 'label', lang), control: 'always', presentations: ['chart'], gate: t('layer.gate.reach', 'en'), sources: ['reach'],
    legend: [{label: copy('reach', 'legend0', lang), swatch: 'blue'}],
    basis: copy('reach', 'basis', lang), task: 'FE-51'}),
  // SC1407-15: the planning route the trip dialog shows before it is downloaded; Chart only, memory only, under the marks.
  entry({id: 'planning-route', label: copy('planning-route', 'label', lang), control: 'always', presentations: ['chart'], sources: [PLANNING_ROUTE_SOURCE],
    legend: [{label: copy('planning-route', 'legend0', lang), swatch: 'amber'}],
    basis: copy('planning-route', 'basis', lang), task: 'SC1407-15'}),
  entry({id: 'marks', label: copy('marks', 'label', lang), control: 'always', presentations: ['chart', 'terrain'],
    terrain: {kind: 'point', color: 'bg', opacity: 0.75, outline: 'mint', size: 14}, gate: t('layer.gate.marks', 'en'), sources: [DENSITY_SOURCE, MARKS_SOURCE],
    legend: [{label: copy('marks', 'legend0', lang), swatch: 'markRing'}, {label: copy('marks', 'legend1', lang), swatch: 'depth1'}],
    basis: copy('marks', 'basis', lang), task: 'FE-18'}),
  entry({id: 'selection', label: copy('selection', 'label', lang), control: 'always', presentations: ['chart'], sources: [SELECTION_SOURCE],
    basis: copy('selection', 'basis', lang), task: 'FE-18'}),
  entry({id: 'trip-ranked', label: copy('trip-ranked', 'label', lang), control: 'always', presentations: ['chart'], sources: [RANKED_SOURCE], gate: t('layer.gate.ranked', 'en'),
    legend: [{label: copy('trip-ranked', 'legend0', lang), swatch: 'mint'}],
    basis: copy('trip-ranked', 'basis', lang), task: 'FE-51'}),
  // SC0922-04: the owner's own positions, off by default and session-only (not a rail entry, a link layer or a profile default).
  entry({id: 'saved-spots', label: copy('saved-spots', 'label', lang), control: 'always', presentations: ['chart'], sources: [SAVED_SPOTS_SOURCE], gate: t('layer.gate.saved', 'en'),
    basis: copy('saved-spots', 'basis', lang), task: 'SC0922-04'}),
  entry({id: 'stations', label: copy('stations', 'label', lang), control: 'stations', presentations: ['chart'], sources: ['stations'], time: ['observed', 'hour'],
    legend: [{label: copy('stations', 'legend0', lang), swatch: 'blue'}, {label: copy('stations', 'legend1', lang), swatch: 'mint'}, {label: copy('stations', 'legend2', lang), swatch: 'mapLabel'}, {label: copy('stations', 'legend3', lang), swatch: 'blue'}],
    attribution: t('layer.attr.stations', 'en'), basis: copy('stations', 'basis', lang), task: 'CI6-18'}),
  entry({id: 'coastline', label: copy('coastline', 'label', lang), control: 'always', presentations: ['chart'], sources: [COASTLINE_SOURCE], attribution: COASTLINE_ATTRIBUTION,
    basis: copy('coastline', 'basis', lang), task: 'FE-11'}),
]);

/** A registry sentence or label from the catalogue (layer.<id>.label | basis | legend<N>). */
const copy = (id: string, part: string, lang: Language): string => t(`layer.${id}.${part}` as StringId, lang);

/** The registry by language, built once from the catalogue; no language is read here. English is the compatibility export. */
const REGISTRY: Readonly<Record<Language, readonly LayerEntry[]>> = Object.freeze({en: build('en'), es: build('es')});
/** The English registry: the ids, order, sources, gates and English copy every reader and test relies on. */
export const LAYERS: readonly LayerEntry[] = REGISTRY.en;

/**
 * MSKL-3: the 24 kit layers, in kit order, each with the registry entries that draw it today (the token's `app_layer_ids`
 * that exist in this registry; tests/test_stacking.mjs pins both lists to style/layers-v1.0.0.json).
 */
const KIT_APP_IDS: Readonly<Record<KitLayerId, readonly string[]>> = {
  'sst-fill': ['water-temp'], 'sst-breaks': ['water-temp-contours', 'sst-contrast', 'sst-fronts'], chlorophyll: ['chlorophyll'], kd490: [],
  ssh: [], upwelling: [], currents: ['currents'], 'subsurface-temp': [], salinity: [], 'sea-ice': [], wind: ['wind'], pressure: [],
  'waves-swell': ['swell'], tides: [], 'precip-radar': [], clouds: ['clouds'], 'visibility-fog': [], stations: ['stations'],
  'marine-zones-mpas': ['mpas'], 'kelp-habitat': ['habitat', 'shore-runs'], places: [], 'spots-marks': ['marks', 'trip-ranked'],
  'routes-tracks': ['planning-route'], 'ais-fleet': ['commercial-ais'],
};
export const KIT_LAYERS: readonly KitLayerRow[] = Object.freeze((Object.keys(KIT_APP_IDS) as KitLayerId[]).map(id => Object.freeze({
  id, appIds: KIT_APP_IDS[id], noData: NO_DATA_YET.includes(id), labelId: `layer.skl.${id}.label` as StringId,
})));
/** The kit row for `id`, or null when `id` is not a kit layer. */
export const kitLayer = (id: string): KitLayerRow | null => KIT_LAYERS.find(k => k.id === id) ?? null;

/** The registry entry for `id`; throws on an unknown id so a typo cannot hide a layer. */
export function layerEntry(id: string): LayerEntry {
  const found = LAYERS.find(e => e.id === id);
  if (!found) throw new Error(t('dev.unknownLayer', 'en', {id}));
  return found;
}

/** A layer's label, basis sentence and prose legend rows in `lang`; the swatches and numeric rows are the registry's own. Throws on an unknown id. */
export function layerCopy(id: string, lang: Language = 'en'): Pick<LayerEntry, 'label' | 'basis' | 'legend'> {
  layerEntry(id);
  const found = REGISTRY[lang === 'es' ? 'es' : 'en'].find(e => e.id === id)!;
  return {label: found.label, basis: found.basis, legend: found.legend};
}

/** The layer that owns MapLibre source `sourceId`, or null for a source no entry owns. */
export function sourceLayer(sourceId: string | undefined): string | null {
  return sourceId ? LAYERS.find(e => e.sources.includes(sourceId))?.id ?? null : null;
}

/**
 * The note under a rail entry's name, written by the layer that draws it: what it shows or why it
 * cannot ("no fresh frame · last 1:28 pm"). Empty: no note. The rail reads it (FE-22 first).
 */
export const railNotes = signal<Readonly<Partial<Record<RailId, string>>>>({});
/** SC1352-02: catalogue parts for a rail note, kept beside it (never the translated text) so the rail can show it in the page's language. */
export const railNoteCopies = signal<Readonly<Partial<Record<RailId, readonly StatusPart[]>>>>({});
export function setRailNote(rail: RailId, note: string, copy?: readonly StatusPart[]): void {
  const parts = note && copy?.length ? copy : undefined, held = railNoteCopies.peek()[rail];
  const copyChanged = JSON.stringify(held) !== JSON.stringify(parts), noteChanged = (railNotes.peek()[rail] ?? '') !== note;
  if (!copyChanged && !noteChanged) return;
  batch(() => {
    if (copyChanged) { const {[rail]: _gone, ...rest} = railNoteCopies.peek(); railNoteCopies.value = parts ? {...rest, [rail]: parts} : rest; }
    if (noteChanged) railNotes.value = {...railNotes.peek(), [rail]: note};
  });
}

/** The entries a rail entry (or the base choice) turns on and off, in draw order. */
export const railLayers = (rail: LayerControl): LayerEntry[] => LAYERS.filter(e => e.control === rail);

/**
 * Whether turning rail entry `rail` (or choosing a base) changes what presentation `shown` draws: one of
 * its layers draws there. In 2D and 3D an entry that draws nothing reads "Chart only" and cannot be
 * switched, so it never toggles a hidden layer (FE-20).
 */
export const drawsIn = (rail: LayerControl, shown: Presentation): boolean =>
  railLayers(rail).some(e => e.presentations.includes(shown === 'chart' ? 'chart' : 'terrain'));
export const CHART_ONLY = t('rail.chartOnly', 'en');
/** The "Chart only" reason in `lang`. */
export const chartOnly = (lang: Language = 'en'): string => t('rail.chartOnly', lang);

/** The entries that draw in `presentation`, in draw order. */
export const layersIn = (presentation: LayerPresentation): LayerEntry[] => LAYERS.filter(e => e.presentations.includes(presentation));

/** The legend's attribution row for the drawn layers, in draw order, without repeats. */
export function attributionFor(drawn: readonly string[]): string {
  return [...new Set(LAYERS.filter(e => e.attribution && drawn.includes(e.id)).map(e => e.attribution as string))].join(' · ');
}

/** A registry layer's features for the terrain, and what a pick of one of them selects. */
export interface TerrainLayer {
  readonly features: readonly CoastOverlayFeature[];
  /** The card for a picked feature, or null when the pick selects through the link (a reef mark's `?spot=`), as the Chart's pick does. */
  pick(feature: string | number): ChartMark | null;
}
/** GeoJSON features as overlay features, each under the id `id` gives it (the Chart's feature id, so a pick names the same feature). */
export function overlayFeatures<F extends {readonly geometry?: unknown; readonly properties?: unknown}>(
  features: readonly F[], id: (feature: F, index: number) => string | number): CoastOverlayFeature[] {
  return features.map((f, i) => ({id: id(f, i), geometry: f.geometry as CoastOverlayFeature['geometry'], properties: (f.properties ?? null) as CoastOverlayFeature['properties']}));
}
/** Each draped entry's current features, published by the layer that loads them; stage.ts drapes them. */
export const terrainLayers = signal<Readonly<Record<string, TerrainLayer>>>({});
export function setTerrainLayer(id: string, layer: TerrainLayer | null): void {
  const now = terrainLayers.peek();
  if (!layer && !(id in now)) return;
  const next = {...now};
  if (layer) next[id] = layer; else delete next[id];
  terrainLayers.value = next;
}

/** The overlay style for `drape`, its roles left as roles (the renderer resolves them from the overlay palette) and its opacity resolved from `p`. */
export function drapeStyle(drape: TerrainDrape, p: Pick<Palette, 'mpaFillOpacity'>) {
  const opacity = drape.opacity === 'mpaFillOpacity' ? Number(p.mpaFillOpacity) : drape.opacity;
  return {
    color: drape.color,
    ...(opacity !== undefined && Number.isFinite(opacity) ? {opacity} : {}),
    ...(drape.outline ? {outline: drape.outline} : {}),
    ...(drape.outlineOpacity !== undefined ? {outlineOpacity: drape.outlineOpacity} : {}),
    ...(drape.size !== undefined ? {size: drape.size} : {}),
  };
}

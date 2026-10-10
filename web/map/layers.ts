// The layer registry (FE-11, docs/plans/front-end/design.md § 9, § 3A.2): every
// map layer once, in draw order from the bottom up, with the presentations it
// draws in, its rail entry, the MapLibre sources it owns, its time behaviour,
// its legend and its basis sentence. The Chart (web/map/chart.ts) draws the
// entries it has a drawing for, and a source error marks only the entry that
// owns the source unavailable (sourceLayer). Later tasks fill in the entries
// whose `task` is theirs; the order and the presentations are fixed here.
//
// Erasable syntax only: tests/test_map_layers.mjs imports this file by type stripping.
import {signal} from '@preact/signals';
import type {Presentation} from '../coast-context.ts';
import type {RailId} from '../profile.ts';
import type {PaletteKey} from './palette.ts';
import {BASEMAP_ATTRIBUTION, BASEMAP_SOURCE} from './style.ts';

/** Where a layer draws: the MapLibre Chart, the packages/coast terrain (2D and 3D), or both. */
export type LayerPresentation = 'chart' | 'terrain';
/** `static` never changes with the clock; `hour` follows the dock's forecast hour; `observed` shows real frames only. */
export type TimeBehaviour = 'static' | 'hour' | 'observed';
/** A rail entry, a base (one at a time, under the fields), or always drawn where its gate allows. */
export type LayerControl = RailId | 'base' | 'always';
export interface LegendRow {readonly label: string; readonly swatch?: PaletteKey}

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
}

export const COASTLINE_SOURCE = 'coastline';
export const ENC_SOURCE = 'enc';
/** The seafloor publication's admitted features (web/map/seafloor.ts, FE-14). */
export const SEAFLOOR_SOURCE = 'seafloor';
/** FE-18's GeoJSON sources (web/map/marks.ts): survey habitat, geology, atlas reef marks and the selection. */
export const SURVEY_SOURCE = 'survey-habitat';
export const GEOLOGY_SOURCE = 'geology';
export const MARKS_SOURCE = 'marks';
export const SELECTION_SOURCE = 'selection';
/** The trip planner's ranked spots (web/map/ranked.ts, #495). */
export const RANKED_SOURCE = 'trip-ranked';
export const COASTLINE_ATTRIBUTION = 'NOAA NGS · CUSP shoreline';
export const ENC_ATTRIBUTION = 'NOAA ENC display · planning only';
export const MPA_SOURCE = 'mpas';
/**
 * The on-map CC BY 4.0 credit for ds582 (catalog `cdfw-mpas`): creator, dataset, licence. The legend
 * row's basis gives it in full with the metadata and licence links. Kept short so that, beside the
 * coastline credit, MapLibre's attribution stays one line on a phone: the box paints when MapLibre
 * loads, and a wrapped box becomes the page's largest paint (the LCP budget, design § 13).
 */
export const MPA_ATTRIBUTION = 'CDFW ds582 · CC BY 4.0';

const STATIC: readonly TimeBehaviour[] = ['static'];
const entry = (e: Omit<LayerEntry, 'sources' | 'legend' | 'time'> & Partial<Pick<LayerEntry, 'sources' | 'legend' | 'time'>>): LayerEntry =>
  Object.freeze({sources: [], legend: [], time: STATIC, ...e});

/** § 9 draw order, bottom to top. The ENC chart sits with the bases, above the aerial. */
export const LAYERS: readonly LayerEntry[] = Object.freeze([
  entry({id: 'basemap', label: 'Basemap', control: 'base', presentations: ['chart'], sources: [BASEMAP_SOURCE], attribution: BASEMAP_ATTRIBUTION,
    basis: 'OpenStreetMap data in a Protomaps extract, rebuilt quarterly; the build date names the archive.', task: 'FE-10'}),
  entry({id: 'aerial', label: 'Aerial', control: 'base', presentations: ['chart'],
    basis: 'USGS/USDA NAIP natural-colour mosaic, dated imagery.', task: 'FE-23'}),
  entry({id: 'chart', label: 'Chart detail', control: 'base', presentations: ['chart'], sources: [ENC_SOURCE], attribution: ENC_ATTRIBUTION, gate: 'zoom ≥ 10',
    basis: 'NOAA electronic navigational chart display service, drawn from zoom 10; for planning, never for navigation.', task: 'FE-11'}),
  // The renderer draws relief whatever the rail says; FE-80 moves its options into the Seafloor entry.
  entry({id: 'relief', label: 'Terrain relief', control: 'always', presentations: ['terrain'],
    basis: 'Reviewed regional terrain and imagery, checked by hash in the browser before it draws.', task: 'FE-80'}),
  entry({id: 'water-temp', label: 'Water temp', control: 'water-temp', presentations: ['chart'], time: ['observed'], legend: [{label: 'Cold to warm', swatch: 'sst0'}],
    basis: 'The bound coast report\'s daily sea-surface temperature analysis, named with its product, grid and age where it draws and withheld 72 hours after analysis; surface water only, neither bottom temperature nor a forecast.', task: 'FE-16'}),
  entry({id: 'water-temp-contours', label: 'Water temp contours', control: 'water-temp', presentations: ['chart'], time: ['observed'],
    basis: 'Half-degree Fahrenheit contours of the same analysis, labelled at whole degrees.', task: 'FE-16'}),
  entry({id: 'swell', label: 'Swell', control: 'swell', presentations: ['chart'], time: ['hour'], legend: [{label: 'Primary swell height', swatch: 'swell2'}],
    basis: 'NOAA GFS-Wave model forecast of the primary swell on the region\'s forecast grid, from a run issued within 36 hours, and where a coast report binds, its nearshore model sites (CDIP MOP) as rings; model output, not buoy observations.', task: 'FE-17'}),
  entry({id: 'mpas', label: 'Marine protected areas', control: 'always', presentations: ['chart'], sources: [MPA_SOURCE], attribution: MPA_ATTRIBUTION,
    legend: [{label: 'Marine protected area', swatch: 'mpaLine'}],
    basis: 'CDFW marine protected areas, ds582; boundaries are context, rules are in the regulations page.', task: 'FE-19'}),
  entry({id: 'habitat', label: 'Habitat', control: 'always', presentations: ['chart'], gate: 'zoom ≥ 10', sources: [SURVEY_SOURCE, GEOLOGY_SOURCE],
    legend: [{label: 'Hard bottom', swatch: 'depth1'}, {label: 'Mixed bottom', swatch: 'muted'}, {label: 'Soft bottom', swatch: 'amber'}, {label: 'Kelp', swatch: 'mint'}],
    basis: 'Survey habitat and geology polygons, each with its survey and year.', task: 'FE-18'}),
  entry({id: 'shore-runs', label: 'Shore runs', control: 'always', presentations: ['chart'], gate: 'profile = shore',
    basis: 'ESI 2006 sandy-shore runs with public access points.', task: 'FE-36'}),
  entry({id: 'seafloor', label: 'Seafloor', control: 'seafloor', presentations: ['chart'], sources: [SEAFLOOR_SOURCE],
    legend: [{label: 'Strongest grade or fit', swatch: 'depth0'}, {label: 'Weakest grade or fit', swatch: 'depth2'}, {label: 'Surveyed cell', swatch: 'depth3'}],
    basis: 'Terrain screening of original seafloor surveys (grids of 16 m or finer, 250 m coverage cells) at nominal 25–300 ft in each survey\'s own vertical datum, drawn only while its 35-day legal screen is current.', task: 'FE-14'}),
  // FE-21: v1's own sentences, verbatim (dist/charter-grounds.js; dist/commercial-ais.html), pinned by tests/test_fleet_public_layers.mjs.
  entry({id: 'charter-grounds', label: 'Charter grounds', control: 'fleet', presentations: ['chart'], sources: ['charter-grounds', 'charter-grounds-hatch'],
    legend: [{label: 'Charter ground', swatch: 'amber'}],
    basis: 'These are named areas from published trip records, not AIS-confirmed fishing positions. Only lingcod and rockfish are supported by this layer. The outlines are our survey-depth-screened search windows, not published charter boundaries.', task: 'FE-21'}),
  entry({id: 'commercial-ais', label: 'Commercial AIS 2024', control: 'fleet', presentations: ['chart'], sources: ['commercial-ais'], attribution: 'Global Fishing Watch · CC BY-NC 4.0',
    legend: [{label: 'Apparent fishing hours', swatch: 'amber'}],
    basis: 'These two months are a dated sample, not a continuous season or a live fleet feed. Each outline preserves an original 0.01° statistical grid cell, about 0.9 × 1.1 km here. Apparent fishing effort is not proof of fishing or catches.', task: 'FE-21'}),
  entry({id: 'fleet-heat', label: 'Fleet heat', control: 'fleet', presentations: ['chart'], gate: 'admin', sources: ['fleet-heat'],
    legend: [{label: 'Activity heat · aggregate cells', swatch: 'amber'}],
    basis: 'Inferred from movement; filters in the Fleet view.', task: 'FE-24'}),
  entry({id: 'fleet-tracks', label: 'Fleet tracks', control: 'fleet', presentations: ['chart'], gate: 'admin', sources: ['fleet-tracks'],
    legend: [{label: 'Trip tracks · by segment; gaps dashed', swatch: 'amber'}],
    basis: 'Inferred from movement; filters in the Fleet view.', task: 'FE-24'}),
  entry({id: 'fleet-events', label: 'Fleet events', control: 'fleet', presentations: ['chart'], gate: 'admin', sources: ['fleet-events'],
    legend: [{label: 'Activity stops · sized by dwell', swatch: 'amber'}],
    basis: 'Inferred from movement; filters in the Fleet view.', task: 'FE-24'}),
  entry({id: 'currents', label: 'Currents', control: 'currents', presentations: ['chart', 'terrain'], time: ['hour', 'observed'], legend: [{label: 'Surface flow', swatch: 'flow'}, {label: 'Fastest fifth', swatch: 'flowFast'}],
    basis: 'WCOFS surface forecast at about 4 km, or HF radar observed within 6 hours at 1 or 6 km; arrows follow the toward-bearing and their motion is illustrative.', task: 'FE-15'}),
  entry({id: 'clouds', label: 'Clouds', control: 'clouds', presentations: ['chart'], time: ['observed'],
    basis: 'GOES infrared, observed frames within 90 minutes; a loop of real frames, never a forecast.', task: 'FE-22'}),
  entry({id: 'marks', label: 'Marks', control: 'always', presentations: ['chart'], gate: 'zoom ≥ 10', sources: [MARKS_SOURCE],
    legend: [{label: 'Reef mark; badge: habitat fit, 3 strongest', swatch: 'mint'}],
    basis: 'Atlas reef marks, each with its source survey.', task: 'FE-18'}),
  entry({id: 'selection', label: 'Selection', control: 'always', presentations: ['chart'], sources: [SELECTION_SOURCE],
    basis: 'The selected mark, outlined.', task: 'FE-18'}),
  entry({id: 'trip-ranked', label: 'Ranked trip spots', control: 'always', presentations: ['chart'], sources: [RANKED_SOURCE], gate: 'a ranked trip plan',
    legend: [{label: 'Ranked trip spot; number: the planner\'s order', swatch: 'mint'}],
    basis: 'The trip planner\'s ranked reefs from the current seafloor publication, numbered in its order and drawn while its protected-area check and the marks\' run-time screen are current.', task: 'FE-51'}),
  entry({id: 'coastline', label: 'Coastline', control: 'always', presentations: ['chart'], sources: [COASTLINE_SOURCE], attribution: COASTLINE_ATTRIBUTION,
    basis: 'NOAA NGS CUSP shoreline, 1994–2010 sources.', task: 'FE-11'}),
]);

/** The registry entry for `id`; throws on an unknown id so a typo cannot hide a layer. */
export function layerEntry(id: string): LayerEntry {
  const found = LAYERS.find(e => e.id === id);
  if (!found) throw new Error(`Unknown map layer ${id}`);
  return found;
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
export function setRailNote(rail: RailId, note: string): void {
  if ((railNotes.peek()[rail] ?? '') !== note) railNotes.value = {...railNotes.peek(), [rail]: note};
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
export const CHART_ONLY = 'Chart only';

/** The entries that draw in `presentation`, in draw order. */
export const layersIn = (presentation: LayerPresentation): LayerEntry[] => LAYERS.filter(e => e.presentations.includes(presentation));

/** The legend's attribution row for the drawn layers, in draw order, without repeats. */
export function attributionFor(drawn: readonly string[]): string {
  return [...new Set(LAYERS.filter(e => e.attribution && drawn.includes(e.id)).map(e => e.attribution as string))].join(' · ');
}

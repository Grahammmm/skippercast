// The layer registry (FE-11, docs/plans/front-end/design.md § 9, § 3A.2): every
// map layer once, in draw order from the bottom up, with the presentations it
// draws in, its rail entry, the MapLibre sources it owns, its time behaviour,
// its legend and its basis sentence. The Chart (web/map/chart.ts) draws the
// entries it has a drawing for, and a source error marks only the entry that
// owns the source unavailable (sourceLayer). Later tasks fill in the entries
// whose `task` is theirs; the order and the presentations are fixed here.
//
// Erasable syntax only: tests/test_map_layers.mjs imports this file by type stripping.
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
export const COASTLINE_ATTRIBUTION = 'NOAA NGS · CUSP shoreline';
export const ENC_ATTRIBUTION = 'NOAA ENC display · planning only';

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
  entry({id: 'relief', label: 'Terrain relief', control: 'seafloor', presentations: ['terrain'],
    basis: 'Reviewed regional terrain and imagery, checked by hash in the browser before it draws.', task: 'FE-80'}),
  entry({id: 'water-temp', label: 'Water temp', control: 'water-temp', presentations: ['chart'], time: ['observed'], legend: [{label: 'Cold to warm', swatch: 'sst0'}],
    basis: 'MUR daily analysis, 0.01°, sampled at 0.02°, with the analysis age shown.', task: 'FE-16'}),
  entry({id: 'water-temp-contours', label: 'Water temp contours', control: 'water-temp', presentations: ['chart'], time: ['observed'],
    basis: 'Half-degree Fahrenheit contours of the same MUR analysis.', task: 'FE-16'}),
  entry({id: 'swell', label: 'Swell', control: 'swell', presentations: ['chart'], time: ['hour'], legend: [{label: 'Significant height', swatch: 'blue'}],
    basis: 'Model wave forecast on the region grid; nearshore sites from the CDIP MOP model.', task: 'FE-17'}),
  entry({id: 'mpas', label: 'Marine protected areas', control: 'always', presentations: ['chart'], legend: [{label: 'Marine protected area', swatch: 'mpaLine'}],
    basis: 'CDFW marine protected areas, ds582; boundaries are context, rules are in the regulations page.', task: 'FE-19'}),
  entry({id: 'habitat', label: 'Habitat', control: 'always', presentations: ['chart'], gate: 'zoom ≥ 10',
    basis: 'Survey habitat and geology polygons, each with its survey and year.', task: 'FE-18'}),
  entry({id: 'shore-runs', label: 'Shore runs', control: 'always', presentations: ['chart'], gate: 'profile = shore',
    basis: 'ESI 2006 sandy-shore runs with public access points.', task: 'FE-36'}),
  entry({id: 'seafloor', label: 'Seafloor', control: 'seafloor', presentations: ['chart'], legend: [{label: 'Terrain grade', swatch: 'depth1'}],
    basis: 'USGS survey relief, nominal 0–300 ft; gaps are unsurveyed.', task: 'FE-14'}),
  entry({id: 'charter-grounds', label: 'Charter grounds', control: 'fleet', presentations: ['chart'], legend: [{label: 'Charter ground', swatch: 'amber'}],
    basis: 'Charter grounds verified for this region; each ground lists its sources.', task: 'FE-21'}),
  entry({id: 'commercial-ais', label: 'Commercial AIS 2024', control: 'fleet', presentations: ['chart'],
    basis: 'Commercial AIS effort for 2024 by cell, with its dates, classified gear, resolution and sources.', task: 'FE-21'}),
  entry({id: 'fleet-heat', label: 'Fleet heat', control: 'fleet', presentations: ['chart'], gate: 'admin',
    basis: 'Inferred from movement; filters in the Fleet view.', task: 'FE-24'}),
  entry({id: 'fleet-tracks', label: 'Fleet tracks', control: 'fleet', presentations: ['chart'], gate: 'admin',
    basis: 'Inferred from movement; filters in the Fleet view.', task: 'FE-24'}),
  entry({id: 'fleet-events', label: 'Fleet events', control: 'fleet', presentations: ['chart'], gate: 'admin',
    basis: 'Inferred from movement; filters in the Fleet view.', task: 'FE-24'}),
  entry({id: 'currents', label: 'Currents', control: 'currents', presentations: ['chart', 'terrain'], time: ['hour', 'observed'], legend: [{label: 'Surface flow', swatch: 'flow'}, {label: 'Fast flow', swatch: 'flowFast'}],
    basis: 'WCOFS surface forecast at about 4 km, or HF radar at 6 km when observed within the hour.', task: 'FE-15'}),
  entry({id: 'clouds', label: 'Clouds', control: 'clouds', presentations: ['chart'], time: ['observed'],
    basis: 'GOES infrared, observed frames within 90 minutes; a loop of real frames, never a forecast.', task: 'FE-22'}),
  entry({id: 'marks', label: 'Marks', control: 'always', presentations: ['chart'], gate: 'zoom ≥ 10',
    basis: 'Atlas reef marks, each with its source survey.', task: 'FE-18'}),
  entry({id: 'selection', label: 'Selection', control: 'always', presentations: ['chart'],
    basis: 'The selected mark, outlined.', task: 'FE-18'}),
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

/** The entries a rail entry turns on and off, in draw order. */
export const railLayers = (rail: RailId): LayerEntry[] => LAYERS.filter(e => e.control === rail);

/** The entries that draw in `presentation`, in draw order. */
export const layersIn = (presentation: LayerPresentation): LayerEntry[] => LAYERS.filter(e => e.presentations.includes(presentation));

/** The legend's attribution row for the drawn layers, in draw order, without repeats. */
export function attributionFor(drawn: readonly string[]): string {
  return [...new Set(LAYERS.filter(e => e.attribution && drawn.includes(e.id)).map(e => e.attribution as string))].join(' · ');
}

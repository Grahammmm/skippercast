// Nearshore wave rings (FE-27, docs/plans/front-end/design.md § 9 Swell): the
// bound coast report's nearshore model sites (CDIP MOP in the SLO report) as
// rings on the Chart, part of the Swell layer (web/map/swell.ts).
//
// - Sites: packages/coast freshNearshore for the binding's area (available,
//   current, issued under 48 hours ago and fetched under 3 hours ago), then
//   nearshoreAt for the dock's hour (the sample nearest it within 90 minutes,
//   inside the site's span). A site outside that window, or whose sample has no
//   height, draws no ring. Outside a report binding nothing draws, and Swell is
//   as it was before FE-27.
// - Rings: radius 4 px plus 3 px per foot of modelled significant height, the
//   same at every zoom, 15 ft and above alike; outline only, in --blue.
// - A click opens the one mark card (chartPick) with the site's name, height,
//   period and direction, the model sample's time and the run's age. The basis
//   says it is model output, never a buoy observation or breakers at a beach.
//
// Erasable syntax only: tests/test_nearshore_layer.mjs imports it by type stripping.
import type * as MapLibre from 'maplibre-gl';
import type {NearshoreHour, NearshoreSite} from '../../packages/coast/src/enrichment-types.ts';
import type {Report} from '../../packages/coast/src/types.ts';
import {compass} from '../landing/readings.ts';
import type {ChartMark} from './coastline.ts';
import {freshNearshore, nearshoreAt, nearshoreSampleLabel} from './nearshore-model.js';
import type {Palette} from './palette.ts';

export const NEARSHORE_SOURCE = 'swell-nearshore';
export const NEARSHORE_LAYER = 'swell-nearshore';
/** A transparent circle at least 44 px across under each ring, so a 0–2 ft ring is still a 44 px tap target. */
export const NEARSHORE_HIT = 'swell-nearshore-hit';
/** Ring radius in pixels: RING_BASE plus RING_PER_FT per foot, up to RING_MAX_FT. */
export const RING_BASE = 4;
export const RING_PER_FT = 3;
export const RING_MAX_FT = 15;
const HOUR = 3_600_000;

export interface Ring {readonly site: NearshoreSite; readonly hour: NearshoreHour; readonly waveFt: number}
export interface Rings {
  /** Changes with the sites, their runs and the samples drawn. */
  readonly key: string;
  readonly rings: readonly Ring[];
  /** The product, from the report's status for the sites' source ("CDIP MOP"). */
  readonly product: string;
  readonly collection: {type: 'FeatureCollection'; features: {type: 'Feature'; properties: {id: string; radius: number}; geometry: {type: 'Point'; coordinates: [number, number]}}[]};
}

const age = (ms: number): string => { const h = Math.floor(Math.max(0, ms) / HOUR); return h < 1 ? 'under 1 h' : `${h} h`; };
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
export const ringRadius = (ft: number): number => RING_BASE + RING_PER_FT * Math.min(Math.max(ft, 0), RING_MAX_FT);

/** The report's own name for a site's source: "CDIP MOP · nearshore model" gives "CDIP MOP". */
function productOf(report: Report, sourceId: string): string {
  const label = Array.isArray(report.sources) ? report.sources.find(s => s?.id === sourceId)?.label : undefined;
  return typeof label === 'string' && label ? label.split(' · ')[0]!.trim() : sourceId;
}

/** The rings for the bound area at the dock's hour `at`, or null when none draws (no binding, no fresh site, no sample). */
export function nearshoreRings(report: Report | null, areaId: string | null, at: Date, now: Date): Rings | null {
  if (!report || !areaId) return null;
  const rings: Ring[] = [];
  for (const site of freshNearshore(report, areaId, now)) {
    const hour = finite(site.lat) && finite(site.lon) ? nearshoreAt(site, at.toISOString()) : undefined;
    if (hour && finite(hour.waveFt) && hour.waveFt >= 0) rings.push({site, hour, waveFt: hour.waveFt});
  }
  if (!rings.length) return null;
  return {
    key: rings.map(r => `${r.site.id}|${r.site.issuedAt}|${r.site.fetchedAt}|${r.hour.at}`).join(','), rings, product: productOf(report, rings[0]!.site.sourceId),
    collection: {type: 'FeatureCollection', features: rings.map(r => ({type: 'Feature', properties: {id: r.site.id, radius: ringRadius(r.waveFt)},
      geometry: {type: 'Point', coordinates: [r.site.lon, r.site.lat]}}))},
  };
}

/** The ring's tap target: transparent, radius at least 22 px (a 44 px circle), drawn just under the ring. */
export function ringHitLayer(p: Palette): MapLibre.LayerSpecification {
  return {id: NEARSHORE_HIT, type: 'circle', source: NEARSHORE_SOURCE, paint: {'circle-radius': ['max', 22, ['get', 'radius']], 'circle-color': p.blue, 'circle-opacity': 0}};
}

/** The ring layer: an outline sized by the feature's radius, above the swell field. */
export function ringLayer(p: Palette): MapLibre.LayerSpecification {
  return {id: NEARSHORE_LAYER, type: 'circle', source: NEARSHORE_SOURCE,
    paint: {'circle-radius': ['get', 'radius'], 'circle-color': p.blue, 'circle-opacity': 0, 'circle-stroke-color': p.blue, 'circle-stroke-width': 2, 'circle-stroke-opacity': 0.9}};
}

/** One sentence or two: the product, what a ring is, its window and its scale. */
export function ringBasis(product: string): string {
  return `${product} nearshore model sites from the bound coast report: modelled significant wave height at each site, the sample nearest the selected hour within 90 minutes, `
    + `drawn while the model was issued under 48 hours ago and retrieved under 3 hours ago. Model output, not a buoy observation and not breakers at a beach. `
    + `Ring radius ${RING_BASE} px plus ${RING_PER_FT} px per foot; ${RING_MAX_FT} ft and above draw alike.`;
}

/** The legend's line for the drawn rings. */
export function ringSummary(r: Rings, now: Date): string {
  const issued = r.rings.map(x => Date.parse(x.site.issuedAt ?? '')).filter(Number.isFinite);
  const run = issued.length ? ` · issued ${age(now.getTime() - Math.max(...issued))} ago` : '';
  return `${r.rings.length} nearshore model site${r.rings.length === 1 ? '' : 's'} · ${r.product}${run} · ring ${RING_BASE} px + ${RING_PER_FT} px per ft`;
}

/** The mark card for a clicked ring, or null when `id` is not drawn. */
export function ringMark(r: Rings, id: unknown, now: Date, tz: string): ChartMark | null {
  const ring = r.rings.find(x => x.site.id === id);
  if (!ring) return null;
  const {site, hour} = ring, from = finite(hour.directionDeg) ? ` · from ${compass(hour.directionDeg)} ${Math.round(hour.directionDeg)}°` : '';
  const issued = site.issuedAt ? ` · issued ${age(now.getTime() - Date.parse(site.issuedAt))} ago` : '';
  const depth = finite(site.waterDepthM) ? ` The site is in ${site.waterDepthM} m of water (${site.depthDatum}).` : '';
  return {
    id: `nearshore:${site.id}|${hour.at}`, name: site.name, kind: 'Nearshore model site',
    reading: `${ring.waveFt.toFixed(1)} ft${finite(hour.periodS) ? ` · ${hour.periodS.toFixed(1)} s` : ''}${from}`,
    source: `${r.product} · ${nearshoreSampleLabel(site, hour, tz).slice(site.name.length + 3)}${issued}`,
    basis: `${ringBasis(r.product)}${depth}`,
  };
}

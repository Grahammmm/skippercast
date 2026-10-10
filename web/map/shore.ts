// Shore runs and access points on the Chart (FE-36, docs/plans/front-end/design.md
// § 8, § 9 Shore runs). The region's reviewed shore-habitat package
// (catalog/shore-habitat/<id>.geojson, published by the platform build as
// dist/regions/<id>/shore-habitat.geojson, FE-43) draws only with
// `profile=shore`: each ESI 2006 sandy-shore run as a wide soft --amber line
// tinted by its priority (web/brief/shore.ts), its public access points as
// pins with a 44 px target, and one mark card per run with its review dates,
// the method guidance and the official rules link.
//
// Expiry is honoured: a run past its source review is not drawn (the terrain's
// rule, packages/coast viewer `loadShore`); an expired access or rules review,
// or a protected-area check that is not current, holds the run; a run or
// access point inside a protected area is blocked and draws muted without pins.
// The terrain draws its own shore features (packages/coast), so this is Chart only.
//
// Erasable syntax only: tests/test_shore.mjs imports it by type stripping.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import type {Report} from '../../packages/coast/src/types.ts';
import {geometryIntersects, pointInGeometry} from '../../dist/geo-screen.js';
import {shoreGuidance, shoreReviewLines, shoreShown, shoreStatus, rankRuns, type ShoreRunClocks, type ShoreStatus} from '../brief/shore.ts';
import {coastData} from '../coast-data.ts';
import {PROFILE_TABLE} from '../profile.ts';
import {profile, region, species} from '../state.ts';
import {assetLoader} from './charter-grounds.ts';
import type {ChartMark} from './coastline.ts';
import type {Engine, Overlay} from './engine.ts';
import type {MarkScreen} from './habitat.ts';
import {layerEntry} from './layers.ts';
import {markScreen} from './marks.ts';
import {freshNearshore} from './nearshore-model.js';
import {readPalette, type Palette} from './palette.ts';
import {SEAFLOOR_CELLS} from './seafloor.ts';

const REGISTRY_ID = 'shore-runs';
export const RUNS_SOURCE = 'shore-runs';
export const ACCESS_SOURCE = 'shore-access';
export const RUNS_LINE = 'shore-runs-line';
/** A transparent wide line under the run: its tap target. */
export const RUNS_HIT = 'shore-runs-hit';
export const ACCESS_PIN = 'shore-access-pin';
/** A transparent 44 px circle under each pin. */
export const ACCESS_HIT = 'shore-access-hit';
/** Line opacity by priority: 0.6 for a current run (§ 9), fainter as the clocks age; Hold and Blocked draw muted. */
export const PRIORITY_OPACITY = [0.5, 0.3, 0.45, 0.6] as const;

/** How often the runs are re-ranked against their review clocks. */
export const RECHECK_MS = 10 * 60_000;
export const shoreURL = (id: string): string => `regions/${id}/shore-habitat.geojson`;

type Position = [number, number];
export interface AccessPoint {readonly id: string; readonly name: string; readonly coordinates: Position; readonly sourceUrl: string; readonly checkedAt: string}
export interface RunProps extends ShoreRunClocks {
  readonly id: string; readonly name: string; readonly areaId: string; readonly region: string; readonly shoreClass: string;
  readonly sourceYear: number; readonly sourceUrl: string; readonly access: readonly AccessPoint[]; readonly accessUrl: string; readonly attribution: string;
}
export interface Run {readonly type: 'Feature'; readonly id: string; readonly geometry: {readonly type: 'MultiLineString'; readonly coordinates: Position[][]}; readonly properties: RunProps}
export interface ShorePackage {readonly type: 'FeatureCollection'; readonly regionId: string; readonly features: readonly Run[]}
export interface ShownRun {readonly run: Run; readonly name: string; readonly status: ShoreStatus}

export const validPackage = (d: unknown, id: string): boolean => {
  const p = d as ShorePackage | null;
  return p?.type === 'FeatureCollection' && p.regionId === id && Array.isArray(p.features);
};

/** Protected areas the run's line or access points lie in; null while the check is not current. */
export function insideAreas(run: Run, screen: MarkScreen): string[] | null {
  if (screen.status !== 'ready') return null;
  return screen.boundaries.filter(b => geometryIntersects(run.geometry, b.geometry)
    || run.properties.access.some(a => pointInGeometry(a.coordinates, b.geometry))).map(b => b.name);
}

/** The runs that draw at `now`, ranked, each with its status. */
export function shownRuns(pkg: ShorePackage | null, screen: MarkScreen, report: Report | null, now: number): ShownRun[] {
  const runs = (pkg?.features ?? []).filter(f => f?.geometry?.type === 'MultiLineString' && f.properties?.region === pkg!.regionId && shoreShown(f.properties, now));
  return rankRuns(runs.map(run => ({run, name: run.properties.name, status: shoreStatus(run.properties, {
    now, inside: insideAreas(run, screen), conditions: !!report && freshNearshore(report, run.properties.areaId, new Date(now)).length > 0})})));
}

/** The two GeoJSON sources: runs with their priority, and the access points of runs that are not blocked. */
export function shoreCollections(runs: readonly ShownRun[]) {
  return {
    runs: {type: 'FeatureCollection' as const, features: runs.map(r => ({type: 'Feature' as const, geometry: r.run.geometry,
      properties: {id: r.run.id, priority: r.status.priority, held: r.status.priority === 0 ? 1 : 0}}))},
    access: {type: 'FeatureCollection' as const, features: runs.filter(r => r.status.label !== 'Blocked').flatMap(r => r.run.properties.access.map(a => ({
      type: 'Feature' as const, geometry: {type: 'Point' as const, coordinates: a.coordinates}, properties: {id: r.run.id, access: a.id}})))},
  };
}

/** Sources and layers: a wide soft run line (priority tint, Hold and Blocked muted and dashed), its hit line, then the pins and their hit circles. */
export function shoreOverlay(p: Palette, data: ReturnType<typeof shoreCollections>): Overlay {
  const held = ['==', ['get', 'held'], 1];
  return {
    sources: {[RUNS_SOURCE]: {type: 'geojson', data: data.runs} as MapLibre.SourceSpecification, [ACCESS_SOURCE]: {type: 'geojson', data: data.access} as MapLibre.SourceSpecification},
    layers: [
      {id: RUNS_HIT, type: 'line', source: RUNS_SOURCE, layout: {'line-cap': 'round'}, paint: {'line-color': p.amber, 'line-width': 22, 'line-opacity': 0}},
      {id: RUNS_LINE, type: 'line', source: RUNS_SOURCE, layout: {'line-cap': 'round', 'line-join': 'round'}, paint: {
        'line-color': ['case', held, p.muted, p.amber], 'line-blur': 3,
        'line-width': ['interpolate', ['linear'], ['zoom'], 8, 4, 13, 12],
        'line-opacity': ['match', ['get', 'priority'], 3, PRIORITY_OPACITY[3], 2, PRIORITY_OPACITY[2], 1, PRIORITY_OPACITY[1], PRIORITY_OPACITY[0]]}},
      {id: ACCESS_HIT, type: 'circle', source: ACCESS_SOURCE, paint: {'circle-radius': 22, 'circle-color': p.amber, 'circle-opacity': 0}},
      {id: ACCESS_PIN, type: 'circle', source: ACCESS_SOURCE, paint: {'circle-radius': 5, 'circle-color': p.bg, 'circle-stroke-color': p.amber, 'circle-stroke-width': 2}},
    ] as MapLibre.LayerSpecification[],
  };
}

/** The card for a run: its status and reasons, review dates, access points, method guidance and the rules link. */
export function runMark(r: ShownRun, target: string): ChartMark {
  const p = r.run.properties, guide = shoreGuidance(target);
  const access = r.status.label === 'Blocked' ? '' : ` Public access: ${p.access.map(a => a.name).join('; ')}.`;
  return {
    id: `shore:${p.id}`, name: p.name, kind: `Shore run · ${r.status.label}`,
    reading: `${r.status.reasons.join('; ')}.${access} ${shoreReviewLines(p)}.`,
    source: `NOAA ESI ${p.sourceYear} · ${p.shoreClass} · access points from the California Coastal Commission inventory`,
    basis: `${layerEntry(REGISTRY_ID).basis} ${guide.text} Historical shoreline classification; access points are inventory references, not opening status or directions.`,
    regulations: {href: guide.href, label: guide.label},
  };
}

export interface ShoreState {readonly drawn: number; readonly held: number; readonly blocked: number}
export const shoreState = signal<ShoreState>({drawn: 0, held: 0, blocked: 0});

export interface ShoreOptions {
  engine: ReadonlySignal<Engine | null>;
  fetchFn?: typeof fetch; page?: () => string; palette?: () => Palette; now?: () => number;
  report?: ReadonlySignal<Report | null>;
}

/** Draws the shore runs while the profile is Shore; created with the Chart (web/map/chart.ts `layers`). */
export function createShore({engine, fetchFn = (...a) => fetch(...a), page = () => location.href, palette = () => readPalette(), now = () => Date.now(),
  report = computed(() => coastData.coastReport.value?.data ?? null)}: ShoreOptions) {
  const pkg = signal<{region: string; data: ShorePackage | null} | null>(null);
  const load = assetLoader<ShorePackage>(fetchFn, page, d => validPackage(d, (d as ShorePackage | null)?.regionId ?? ''));
  // Review clocks expire during a session: re-rank every RECHECK_MS.
  const tick = signal(0);
  const timer = setInterval(() => { tick.value++; }, RECHECK_MS);
  const on = computed(() => profile.value === 'shore');
  const target = computed(() => species.value ?? PROFILE_TABLE[profile.value].defaultTarget);
  const shown = computed(() => {
    const p = pkg.value;
    void tick.value;
    return on.value && p && p.region === region.value ? shownRuns(p.data, markScreen.value, report.value, now()) : [];
  });
  let drawn = false, drawnOn: Engine | null = null;
  const disposers = [
    effect(() => {
      const id = region.value;
      if (!on.value || !id || pkg.peek()?.region === id) return;
      void load(shoreURL(id)).then(data => { if (region.peek() === id) pkg.value = {region: id, data: data && validPackage(data, id) ? data : null}; });
    }),
    effect(() => {
      const list = shown.value;
      shoreState.value = {drawn: list.length, held: list.filter(r => r.status.label === 'Hold').length, blocked: list.filter(r => r.status.label === 'Blocked').length};
    }),
    effect(() => {
      const e = engine.value, list = shown.value;
      if (!e) return;
      if (!list.length) { if (drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, null); drawn = false; drawnOn = e; return; }
      const data = shoreCollections(list);
      // § 9 draw order: above the habitat polygons, under the seafloor candidates.
      if (!drawn || e !== drawnOn) e.setOverlay(REGISTRY_ID, shoreOverlay(palette(), data), SEAFLOOR_CELLS);
      e.setData(RUNS_SOURCE, data.runs); e.setData(ACCESS_SOURCE, data.access);
      drawn = true; drawnOn = e;
    }),
  ];
  const pick = (id: unknown): ChartMark | null => {
    const r = shown.peek().find(x => x.run.id === id);
    return r ? runMark(r, target.peek()) : null;
  };
  return {
    destroy() { clearInterval(timer); for (const dispose of disposers) dispose(); shoreState.value = {drawn: 0, held: 0, blocked: 0}; },
    pick: {layers: [ACCESS_HIT, RUNS_HIT] as const, mark: (_layer: string, properties: Record<string, unknown> | null): ChartMark | null => pick(properties?.id)},
  };
}

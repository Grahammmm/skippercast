// Shore runs and access points on the Chart (FE-36, docs/plans/front-end/design.md
// § 8, § 9 Shore runs). The region's reviewed shore-habitat package
// (catalog/shore-habitat/<id>.geojson, published by the platform build as
// dist/regions/<id>/shore-habitat.geojson, FE-43) draws only with
// `profile=shore`: each ESI 2006 shore run (sandy, or rocky where reviewed) as a wide soft --amber line
// tinted by its priority (web/brief/shore.ts), its public access points as
// pins with a 44 px target, and one mark card per run with its review dates,
// the method guidance and the official rules link.
//
// Expiry is honoured: a run past its source review is not drawn (the terrain's
// rule, packages/coast viewer `loadShore`), and neither is a run never reviewed (null clocks; counted in
// `shoreState.unreviewed`, said as "not yet reviewed", never as expired or current); only a protected-area check that is
// not current, a marine alert check that is not current (or no coast report), a marine
// alert for the area or a county beach-health notice holds
// guidance (web/brief/shore.ts); a run or
// access point inside a protected area is blocked and draws muted without pins.
// Review age does not set priority; all original dates remain visible on the card.
// The terrain draws its own shore features (packages/coast), so this is Chart only.
//
// Erasable syntax only: tests/test_shore.mjs imports it by type stripping.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import type {Report} from '../../packages/coast/src/types.ts';
import {closureHits} from '../../dist/geo-screen.js';
import {activeAlerts, alertCheckCurrent, beachNotices, nextShoreChange, shoreGuidance, shoreNeverReviewed, shoreGuidanceCopy, shoreLabelCopy, shoreReviewCopy, shoreReviewLines, shoreShown, shoreStatus, shoreStatusCopy, rankRuns, type ShoreRunClocks, type ShoreStatus, type ShoreStatusCopy} from '../brief/shore.ts';
import {cp, joinParts} from '../mark-copy.ts';
import {zone} from '../app/region-info.ts';
import type {StringId} from '../i18n.ts';
import {coastData} from '../coast-data.ts';
import {PROFILE_TABLE} from '../profile.ts';
import {DEFAULT_ZONE} from '../zone.ts';
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
const SID = (key: string): StringId => `mark.layer.shore.${key}` as StringId;
export const RUNS_SOURCE = 'shore-runs';
export const ACCESS_SOURCE = 'shore-access';
export const RUNS_LINE = 'shore-runs-line';
/** A transparent wide line under the run: its tap target. */
export const RUNS_HIT = 'shore-runs-hit';
export const ACCESS_PIN = 'shore-access-pin';
/** A transparent 44 px circle under each pin. */
export const ACCESS_HIT = 'shore-access-hit';
/** Line opacity by model coverage: 0.6 with a fresh sample; Hold and Blocked draw muted. */
export const PRIORITY_OPACITY = {0: 0.5, 2: 0.45, 3: 0.6} as const;

/** How often model coverage and source visibility are refreshed. */
export const RECHECK_MS = 10 * 60_000;
export const shoreURL = (id: string): string => `regions/${id}/shore-habitat.geojson`;

type Position = [number, number];
export interface AccessPoint {readonly id: string; readonly name: string; readonly coordinates: Position; readonly sourceUrl: string; readonly checkedAt: string}
export interface RunProps extends ShoreRunClocks {
  readonly id: string; readonly name: string; readonly areaId: string; readonly region: string; readonly substrate?: string; readonly shoreClass: string;
  readonly sourceYear: number; readonly sourceUrl: string; readonly access: readonly AccessPoint[]; readonly accessUrl: string; readonly attribution: string;
}
export interface Run {readonly type: 'Feature'; readonly id: string; readonly geometry: {readonly type: 'MultiLineString'; readonly coordinates: Position[][]}; readonly properties: RunProps}
export interface ShorePackage {readonly type: 'FeatureCollection'; readonly regionId: string; readonly features: readonly Run[]}
/** `copy` is display-only (SC1352-08): the reasons as catalogue parts, from the inputs the status was decided with. It never changes the status. */
export interface ShownRun {readonly run: Run; readonly name: string; readonly status: ShoreStatus; readonly copy?: ShoreStatusCopy}

export const validPackage = (d: unknown, id: string): boolean => {
  const p = d as ShorePackage | null;
  return p?.type === 'FeatureCollection' && p.regionId === id && Array.isArray(p.features);
};

/** Protected areas the run's line or access points lie in; null while the check is not current. */
export function insideAreas(run: Run, screen: MarkScreen): string[] | null {
  if (screen.status !== 'ready') return null;
  return closureHits([run.geometry, ...run.properties.access.map(a => ({type: 'Point', coordinates: a.coordinates}))], screen.boundaries).map(b => b.name);
}

/** The runs that draw at `now`, ranked, each with its status. */
export function shownRuns(pkg: ShorePackage | null, screen: MarkScreen, report: Report | null, now: number): ShownRun[] {
  const runs = (pkg?.features ?? []).filter(f => f?.geometry?.type === 'MultiLineString' && f.properties?.region === pkg!.regionId && shoreShown(f.properties, now));
  return rankRuns(runs.map(run => {
    const area = run.properties.areaId;
    const inputs = {
      now, inside: insideAreas(run, screen), conditions: !!report && freshNearshore(report, area, new Date(now)).length > 0,
      alertCheck: !!report && alertCheckCurrent(report, now),
      alerts: report ? activeAlerts(report.alerts ?? [], area, now).map(a => a.event) : [],
      notices: report ? beachNotices(report, area, now).map(n => n.name) : []};
    const status = shoreStatus(run.properties, inputs), copy = shoreStatusCopy(inputs, status);
    return {run, name: run.properties.name, status, ...(copy ? {copy} : {})};
  }));
}

/** The two GeoJSON sources: runs with their priority, and the access points of runs that are not blocked. */
export function shoreCollections(runs: readonly ShownRun[]) {
  const held = (r: ShownRun) => r.status.priority === 0 ? 1 : 0;
  return {
    runs: {type: 'FeatureCollection' as const, features: runs.map(r => ({type: 'Feature' as const, geometry: r.run.geometry,
      properties: {id: r.run.id, priority: r.status.priority, held: held(r)}}))},
    access: {type: 'FeatureCollection' as const, features: runs.filter(r => r.status.label !== 'Blocked').flatMap(r => r.run.properties.access.map(a => ({
      type: 'Feature' as const, geometry: {type: 'Point' as const, coordinates: a.coordinates}, properties: {id: r.run.id, access: a.id, held: held(r)}})))},
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
        'line-opacity': ['match', ['get', 'priority'], 3, PRIORITY_OPACITY[3], 2, PRIORITY_OPACITY[2], PRIORITY_OPACITY[0]]}},
      {id: ACCESS_HIT, type: 'circle', source: ACCESS_SOURCE, paint: {'circle-radius': 22, 'circle-color': p.amber, 'circle-opacity': 0}},
      {id: ACCESS_PIN, type: 'circle', source: ACCESS_SOURCE, paint: {'circle-radius': 5, 'circle-color': p.bg, 'circle-stroke-color': ['case', held, p.muted, p.amber], 'circle-stroke-width': 2}},
    ] as MapLibre.LayerSpecification[],
  };
}

/** The card for a run: its status and reasons, review dates, access points, method guidance and the rules link. */
export function runMark(r: ShownRun, target: string, now = Date.now(), tz: string = DEFAULT_ZONE): ChartMark {
  const p = r.run.properties, guide = shoreGuidance(target, p.substrate);
  const blocked = r.status.label === 'Blocked', names = p.access.map(a => a.name).join('; ');
  const access = blocked ? '' : ` Public access: ${names}.`;
  const label = shoreLabelCopy(r.status.label), gc = shoreGuidanceCopy(target, p.substrate);
  // Display wording only: the reasons come from the status's own inputs, or stay as written when there are none.
  const reasons = r.copy ? r.copy.reasons : r.status.reasons;
  return {
    id: `shore:${p.id}`, name: p.name, kind: `Shore run · ${r.status.label}`,
    reading: `${r.status.reasons.join('; ')}.${access} ${shoreReviewLines(p, now, tz)}.`,
    source: `NOAA ESI ${p.sourceYear} · ${p.shoreClass} · access points from the California Coastal Commission inventory`,
    basis: `${layerEntry(REGISTRY_ID).basis} ${guide.text} Historical shoreline classification; access points are inventory references, not opening status or directions.`,
    regulations: {href: guide.href, label: guide.label},
    copy: {
      ...(label ? {kind: [cp(SID('kind'), {status: label})]} : {}),
      reading: [...joinParts(reasons.map(x => [x]), '; '), '.', ...(blocked ? [] : [' ', cp(SID('access'), {names})]), ' ', ...shoreReviewCopy(p, now, tz), '.'],
      source: [cp(SID('source'), {year: p.sourceYear, shoreClass: p.shoreClass})],
      basis: [cp('layer.shore-runs.basis'), ' ', ...gc.text, ' ', cp(SID('historical'))],
      regulationsLabel: [...gc.label],
    },
  };
}

/** `unreviewed` counts the region's runs left out because no owner review exists yet; it is not an expiry and not a Current status. */
export interface ShoreState {readonly drawn: number; readonly held: number; readonly blocked: number; readonly unreviewed: number}
export const shoreState = signal<ShoreState>({drawn: 0, held: 0, blocked: 0, unreviewed: 0});

/** How many of the package's runs have never been reviewed (null source clocks): withheld from Chart, said in the state. */
export const unreviewedCount = (pkg: ShorePackage | null): number =>
  (pkg?.features ?? []).filter(f => f?.geometry?.type === 'MultiLineString' && f.properties?.region === pkg!.regionId && shoreNeverReviewed(f.properties)).length;

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
  // Refresh model coverage and source visibility every RECHECK_MS.
  const tick = signal(0);
  const timer = setInterval(() => { tick.value++; }, RECHECK_MS);
  // An alert or source clock that turns by the next tick (at it included) re-checks a second after it, past
  // every strict boundary; a threshold landing exactly on a tick or on a report's arrival is not dropped.
  let soon: ReturnType<typeof setTimeout> | undefined;
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
      const r = report.value;
      void tick.value;
      clearTimeout(soon);
      const t = now(), next = r ? nextShoreChange(r, t) : null;
      if (next !== null && next - t <= RECHECK_MS) soon = setTimeout(() => { tick.value++; }, next - t + 1000);
    }),
    effect(() => {
      const id = region.value;
      if (!on.value || !id || pkg.peek()?.region === id && pkg.peek()?.data) return;
      void load(shoreURL(id)).then(data => { if (region.peek() === id) pkg.value = {region: id, data: data && validPackage(data, id) ? data : null}; });
    }),
    effect(() => {
      const list = shown.value;
      const p = pkg.value;
      shoreState.value = {drawn: list.length, held: list.filter(r => r.status.label === 'Hold').length, blocked: list.filter(r => r.status.label === 'Blocked').length,
        unreviewed: on.value && p && p.region === region.value ? unreviewedCount(p.data) : 0};
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
    // The zone is read now, not at load: the matching region's own, else Pacific (web/app/region-info.ts `zone`).
    return r ? runMark(r, target.peek(), now(), zone()) : null;
  };
  return {
    destroy() { clearInterval(timer); clearTimeout(soon); for (const dispose of disposers) dispose(); shoreState.value = {drawn: 0, held: 0, blocked: 0, unreviewed: 0}; },
    pick: {layers: [ACCESS_HIT, RUNS_HIT] as const, mark: (_layer: string, properties: Record<string, unknown> | null): ChartMark | null => pick(properties?.id)},
  };
}

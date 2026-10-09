// Water temp (FE-16, docs/plans/front-end/design.md § 9): the bound coast
// report's daily sea-surface temperature analysis on the Chart, as a texture
// (web/map/field.ts) in an image source, with 0.5 °F contours labelled at whole
// degrees, under the protected areas.
//
// - Data: `spatial.surfaceTemperature` of the coast report (web/coast-data.ts,
//   FE-74), requested only while Water temp is on, for the region's place when
//   it binds a local report (Morro Bay and Cambria). The product is the one that
//   report carries, named by the report's own status for that source id: on
//   2026-10-09 the bridge served Fish's report with NASA JPL MUR (0.01°, sampled
//   every 0.02°); SkipperCast's own report (FE-87) carries NOAA Geo-Polar Blended
//   (0.05°). Other regions draw nothing and the rail says so.
// - Gate: fish's rule, the analysis and its retrieval each under 72 hours old
//   (at most 5 minutes ahead of the clock), the source's status `ok`, and the
//   analysis no later than the dock's hour. Otherwise nothing draws, and the
//   rail and legend give the reason and the analysis date.
// - Grid: packages/coast `surfaceField` at the analysis's own sample spacing.
//   The texture and contours cover complete quads only: masked land and missing
//   cells stay blank. A grid it refuses draws nothing, and a refused or stale
//   replacement removes the texture and contours of the analysis before it.
// - Legend: the range is packages/coast `temperatureRange` of every sample (the
//   whole degrees around its extremes) and the ramp the `--sst-*` tokens
//   (web/map/palette.ts), which equal its `temperatureColors`. The analysis
//   error stays in the legend's basis and the click reading.
//
// Erasable syntax only: tests/test_field_texture.mjs imports it by type stripping.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {coastData, type CoastData, type CoastStatus} from '../coast-data.ts';
import type {SurfaceTemperature} from '../../packages/coast/src/spatial-types.ts';
import type {CoastReportContext} from '../../packages/coast/src/state/report-binding.ts';
import type {Report} from '../../packages/coast/src/types.ts';
import {day, hour, layers} from '../state.ts';
import {chartMark} from './chart.ts';
import type {ChartMark} from './coastline.ts';
import type {Engine, Overlay} from './engine.ts';
import {fieldTexture} from './field.ts';
import {layerEntry, setRailNote} from './layers.ts';
import {MPA_FILL} from './mpa.ts';
import {ramps, readPalette, type Palette} from './palette.ts';
import {shownPresentation, terrainHour} from './stage.ts';
import {LABEL_FONT} from './style.ts';
import {fieldContours, surfaceField, temperatureRange, type SurfaceField} from './surface-field.js';

const REGISTRY_ID = 'water-temp' as const;
export const SST_SOURCE = 'water-temp';
export const CONTOUR_SOURCE = 'water-temp-contours';
export const SST_LAYER = 'water-temp';
export const CONTOUR_LAYER = 'water-temp-contours';
export const CONTOUR_LABELS = 'water-temp-labels';
export const SST_OPACITY = 0.8;
const HOUR = 3_600_000;
/** fish's `live(…, 72)`: an analysis, and its retrieval, under 72 hours old and at most 5 minutes ahead. */
export const MAX_AGE_MS = 72 * HOUR;
const AHEAD_MS = 5 * 60_000;

/** An analysis that passed the gate, with its grid. */
export interface Analysis {
  /** Changes with the product, its analysis time or its retrieval: a new key is a new texture. */
  readonly key: string;
  readonly sst: SurfaceTemperature;
  /** The product, from the report's status label ("NASA JPL MUR · surface temperature analysis" gives "NASA JPL MUR"). */
  readonly product: string;
  readonly field: SurfaceField;
  /** The legend's range: whole degrees Fahrenheit around the analysis's extremes. */
  readonly range: readonly [number, number];
  /** The analysis error's smallest and largest values, °F. */
  readonly error: readonly [number, number];
  /** "analysis Oct 7 · 42 h old" */
  readonly stamp: string;
}
export interface WaterTempStatus {
  readonly drawn: Analysis | null;
  /** The rail's short note. */
  readonly note: string;
  /** Why nothing draws, for the legend; '' when an analysis draws or the layer is off. */
  readonly reason: string;
  /** One sentence or two: product, grid, date and age, error, and what the field is not. */
  readonly basis: string;
}

export const WATER_TEMP_BASIS = layerEntry('water-temp').basis;
const OFF: WaterTempStatus = {drawn: null, note: '', reason: '', basis: WATER_TEMP_BASIS};
const none = (note: string, reason: string): WaterTempStatus => ({...OFF, note, reason});

const dates = new Map<string, Intl.DateTimeFormat>();
/** "Oct 7" in the region's zone. */
export function dayText(iso: string, tz: string): string {
  let f = dates.get(tz);
  if (!f) dates.set(tz, f = new Intl.DateTimeFormat('en-US', {timeZone: tz, month: 'short', day: 'numeric'}));
  return f.format(new Date(iso));
}
/** "under 1 h", "42 h", "3 d". */
const age = (ms: number): string => { const h = Math.floor(Math.max(0, ms) / HOUR); return h < 1 ? 'under 1 h' : h < 72 ? `${h} h` : `${Math.floor(h / 24)} d`; };
const fresh = (iso: string, now: Date): boolean => { const d = now.getTime() - Date.parse(iso); return Number.isFinite(d) && d >= -AHEAD_MS && d < MAX_AGE_MS; };
const deg = (value: number): string => `${Number(value.toFixed(3))}°`;
const fahrenheit = (value: number): string => `${value.toFixed(1)} °F`;

/** The analysis's sentence: product, grid, date, age and error, then what it is not. */
export function analysisBasis(a: Analysis, now: Date, tz: string): string {
  const {sst} = a, grid = sst.sampleSpacingDeg > sst.nativeResolutionDeg ? `${deg(sst.nativeResolutionDeg)} grid sampled every ${deg(sst.sampleSpacingDeg)}` : `${deg(sst.nativeResolutionDeg)} grid`;
  const [low, high] = a.error.map(fahrenheit) as [string, string];
  return `${a.product} daily analysis on a ${grid}, for ${dayText(sst.analysedAt, tz)} (${age(now.getTime() - Date.parse(sst.analysedAt))} old), `
    + `with an analysis error of ${low === high ? low : `${low} to ${high}`}. Surface water only, neither bottom temperature nor a forecast; masked land and missing cells stay blank.`;
}

// One grid per analysis object: the dock's hour and the clock re-judge the gate, never rebuild the field.
const grids = new WeakMap<SurfaceTemperature, {field: SurfaceField; range: [number, number]; error: [number, number]} | null>();
function grid(sst: SurfaceTemperature): {field: SurfaceField; range: [number, number]; error: [number, number]} | null {
  if (grids.has(sst)) return grids.get(sst)!;
  const points = Array.isArray(sst.points) && sst.points.every(p => p !== null && typeof p === 'object') ? sst.points : [], step = sst.sampleSpacingDeg;
  const field = Number.isFinite(step) && step > 0 && Number.isFinite(sst.nativeResolutionDeg) ? surfaceField(points.map(p => ({lon: p.lon, lat: p.lat, values: [p.tempF, p.errorF]})), {step: [step, step]}) : null;
  const errors = points.map(p => p.errorF);
  const built = field ? {field, range: temperatureRange(points.map(p => p.tempF)), error: [Math.min(...errors), Math.max(...errors)] as [number, number]} : null;
  grids.set(sst, built);
  return built;
}

/** What Water temp shows for the report's state at the dock's hour `at`. */
export function analysisStatus(on: boolean, status: CoastStatus, report: Report | null, at: Date, now: Date, tz: string): WaterTempStatus {
  if (!on) return OFF;
  if (status === 'unbound') return none('no analysis for this region', 'Water temp unavailable: no local surface-temperature analysis covers this region yet.');
  if (status === 'error' || status === 'invalid') return none('unavailable', 'Water temp unavailable: the coast report failed to load.');
  if (status === 'expired') return none('expired', 'Water temp unavailable: the coast report passed its age limit.');
  if (!report) return none('loading', 'Loading the coast report.');
  const sst = report.spatial?.surfaceTemperature;
  const source = sst && Array.isArray(report.sources) ? report.sources.find(s => s?.id === sst.sourceId) : undefined;
  if (!sst || sst.kind !== 'analysis' || !Number.isFinite(Date.parse(sst.analysedAt)) || source?.outcome !== 'ok' || source.kind !== 'analysis' || typeof source.label !== 'string' || !source.label)
    return none('no analysis in the report', 'Water temp unavailable: the coast report carries no surface-temperature analysis that loaded.');
  const product = source.label.split(' · ')[0]!.trim(), date = dayText(sst.analysedAt, tz);
  if (!fresh(sst.analysedAt, now) || !fresh(sst.fetchedAt, now))
    return none(`no fresh analysis · last ${date}`, `Water temp unavailable: the latest ${product} analysis, for ${date}, is past its 72-hour age limit.`);
  if (Date.parse(sst.analysedAt) > at.getTime())
    return none(`analysis after this hour · ${date}`, `Water temp unavailable: the ${product} analysis, for ${date}, is later than the selected hour.`);
  const built = grid(sst);
  if (!built) return none(`grid cannot be drawn · ${date}`,
    `Water temp unavailable: the ${product} analysis for ${date} is not a grid that can be drawn without bridging gaps, and no earlier analysis is shown.`);
  const stamp = `analysis ${date} · ${age(now.getTime() - Date.parse(sst.analysedAt))} old`;
  const drawn: Analysis = {key: `${sst.sourceId}|${sst.analysedAt}|${sst.fetchedAt}`, sst, product, ...built, stamp};
  return {drawn, note: stamp, reason: '', basis: analysisBasis(drawn, now, tz)};
}

type Line = {type: 'Feature'; properties: {level: number; label: string; major: boolean}; geometry: {type: 'LineString'; coordinates: number[][]}};
const end = (p: number[]): string => `${Math.round(p[0]! * 1e7)},${Math.round(p[1]! * 1e7)}`;
/**
 * packages/coast `fieldContours` every 0.5 °F across `range`, its two-point segments joined into lines
 * per level (so a label fits along them); whole degrees are `major` and carry their label with the unit.
 */
export function contourLines(field: SurfaceField, range: readonly [number, number]): {type: 'FeatureCollection'; features: Line[]} {
  const levels = Array.from({length: (range[1] - range[0]) * 2 + 1}, (_, i) => range[0] + i / 2), byLevel = new Map<number, number[][][]>();
  for (const f of fieldContours(field, levels).features) {
    const list = byLevel.get(f.properties.level) ?? [];
    list.push(f.geometry.coordinates);
    byLevel.set(f.properties.level, list);
  }
  const features: Line[] = [];
  for (const [level, segments] of byLevel) {
    const ends = new Map<string, number[]>(), used = new Uint8Array(segments.length);
    segments.forEach((s, i) => { for (const p of s) ends.set(end(p), [...ends.get(end(p)) ?? [], i]); });
    const other = (s: number[][], at: number[]): number[] => end(s[0]!) === end(at) ? s[1]! : s[0]!;
    const grow = (line: number[][]): void => {
      for (let j = ends.get(end(line.at(-1)!))?.find(i => !used[i]); j !== undefined; j = ends.get(end(line.at(-1)!))?.find(i => !used[i])) {
        used[j] = 1;
        line.push(other(segments[j]!, line.at(-1)!));
      }
    };
    segments.forEach((s, i) => {
      if (used[i]) return;
      used[i] = 1;
      const ahead = [...s], behind = [s[0]!];
      grow(ahead); grow(behind);
      const major = Number.isInteger(level);
      features.push({type: 'Feature', properties: {level, label: `${major ? level : level.toFixed(1)} °F`, major},
        geometry: {type: 'LineString', coordinates: [...behind.slice(1).reverse(), ...ahead]}});
    });
  }
  return {type: 'FeatureCollection', features};
}

/** The texture, its contours and their labels, under the protected areas (§ 9 order); filled by setImage and setData. */
export function waterTempOverlay(p: Palette): Overlay {
  const width: MapLibre.ExpressionSpecification = ['interpolate', ['linear'], ['zoom'], 7, 0.5, 12, 1.2];
  return {
    sources: {
      [SST_SOURCE]: {type: 'image', coordinates: [[0, 1], [1, 1], [1, 0], [0, 0]]},
      [CONTOUR_SOURCE]: {type: 'geojson', data: {type: 'FeatureCollection', features: []}},
    },
    layers: [
      {id: SST_LAYER, type: 'raster', source: SST_SOURCE, paint: {'raster-opacity': SST_OPACITY, 'raster-resampling': 'linear', 'raster-fade-duration': 0}},
      {id: CONTOUR_LAYER, type: 'line', source: CONTOUR_SOURCE, layout: {'line-join': 'round'},
        paint: {'line-color': p.text, 'line-width': width, 'line-opacity': ['case', ['get', 'major'], 0.5, 0.25]}},
      {id: CONTOUR_LABELS, type: 'symbol', source: CONTOUR_SOURCE, filter: ['get', 'major'],
        layout: {'symbol-placement': 'line', 'symbol-spacing': 360, 'text-field': ['get', 'label'], 'text-font': [LABEL_FONT], 'text-size': 11},
        paint: {'text-color': p.text, 'text-halo-color': p.bg, 'text-halo-width': 1.2}},
    ],
  };
}

/** The mark card's reading at a clicked point inside the drawn field, or null outside it. */
export function sstMark(a: Analysis, at: {lon: number; lat: number}, now: Date, tz: string): ChartMark | null {
  const v = a.field.sample(at.lon, at.lat);
  if (!v) return null;
  return {
    id: `sst:${a.key}`, name: 'Surface temperature', kind: `Daily analysis · ${dayText(a.sst.analysedAt, tz)}`,
    reading: `${fahrenheit(v[0]!)} · analysis error ${fahrenheit(v[1]!)}`,
    source: `${a.product} · ${a.stamp}`,
    basis: `${analysisBasis(a, now, tz)} Display interpolation between adjacent ocean samples, which adds no measurements.`,
  };
}

/** What the rail and legend show for Water temp. */
export const waterTempState = signal<WaterTempStatus>(OFF);

export interface WaterTempOptions {
  engine: ReadonlySignal<Engine | null>;
  zone: () => string;
  /** The region's report context, or null until the region is known. */
  place: () => CoastReportContext | null;
  data?: Pick<CoastData, 'coastReport' | 'coastStatus' | 'setPlace' | 'load'>;
  palette?: () => Palette;
  now?: () => Date;
}

export function createWaterTemp(o: WaterTempOptions): {reading(at: {lon: number; lat: number}): ChartMark | null; destroy(): void} {
  const {engine, zone, place, data = coastData, palette = () => readPalette(), now = () => new Date()} = o;
  const tick = signal(0);
  const on = computed(() => layers.value.includes(REGISTRY_ID));
  const status = computed(() => {
    void tick.value;
    const t = now(), known = place() !== null;
    return analysisStatus(on.value, known ? data.coastStatus.value.report : 'loading', data.coastReport.value?.data ?? null,
      terrainHour(hour.value, t, day.value, zone()), t, zone());
  });
  let drawnKey = '', drawnOn: Engine | null = null, timer: ReturnType<typeof setTimeout> | undefined;
  const withdraw = (): void => { if (chartMark.peek()?.id.startsWith('sst:')) chartMark.value = null; };

  const disposers = [
    // Ask for the report only while Water temp is on, for the region's place once it is known.
    effect(() => {
      const p = place();
      if (!on.value || !p) return;
      data.setPlace(p);
      void data.load('report');
    }),
    effect(() => {
      const s = status.value;
      waterTempState.value = s;
      setRailNote(REGISTRY_ID, on.value ? s.note : '');
    }),
    // A new analysis repaints; no analysis (off, refused, stale) removes the texture and the contours at once.
    effect(() => {
      const e = engine.value, a = status.value.drawn, key = a?.key ?? '';
      if (!e || (key === drawnKey && e === drawnOn)) return;
      if (key !== drawnKey) withdraw();
      drawnKey = key; drawnOn = e;
      if (!a) { e.setOverlay(REGISTRY_ID, null); return; }
      const p = palette();
      e.setOverlay(REGISTRY_ID, waterTempOverlay(p), MPA_FILL);
      e.setImage(SST_SOURCE, fieldTexture(a.field, a.range, ramps(p).sst, v => v[0]!));
      e.setData(CONTOUR_SOURCE, contourLines(a.field, a.range));
    }),
    // Re-judge at the analysis's 72-hour limit and at the next whole hour (the dock's default hour moves on).
    effect(() => {
      const a = status.value.drawn, t = now().getTime();
      clearTimeout(timer);
      if (!on.value) return;
      const limit = a ? Math.min(Date.parse(a.sst.analysedAt), Date.parse(a.sst.fetchedAt)) + MAX_AGE_MS : Infinity;
      timer = setTimeout(() => { tick.value++; }, Math.min(Math.max(1000, Math.min(limit, (Math.floor(t / HOUR) + 1) * HOUR) - t + 1000), 2 ** 31 - 1));
    }),
  ];
  return {
    reading(at) {
      const a = status.peek().drawn;
      return a && drawnKey === a.key && shownPresentation.peek() === 'chart' ? sstMark(a, at, now(), zone()) : null;
    },
    destroy() {
      for (const dispose of disposers) dispose();
      clearTimeout(timer);
      withdraw();
      waterTempState.value = OFF;
      setRailNote(REGISTRY_ID, '');
    },
  };
}

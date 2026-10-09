// Swell (FE-17, docs/plans/front-end/design.md § 9): NOAA GFS-Wave's primary
// swell on the region's forecast grid (web/map/forecast-grid.ts), drawn on the
// Chart as a field for the dock's hour: a height texture (web/map/field.ts),
// period isolines and short direction strokes at low density. No circles, no
// arrow per grid point, and nothing animates.
//
// - Gate: the dock's hour through web/map/frames.ts forecastTime, FE-12's
//   forecast gate (a run issued at most 36 hours ago, a feed retrieved at most
//   6 hours ago, the listed hour nearest within 90 minutes). Otherwise nothing
//   draws, and the rail and legend say why with the run's time.
// - Field: packages/coast surfaceField over the grid's samples at that hour,
//   [height ft, period s, sin and cos of the from-direction], so directions
//   blend as unit vectors. Complete quads only: a missing sample leaves its
//   cells blank, and nothing reaches past the grid.
// - Texture: height on the --swell-* ramp (web/map/palette.ts) over a fixed
//   0–15 ft scale, so a colour means the same height at every hour.
// - Isolines: packages/coast fieldContours of period at whole seconds,
//   labelled with the unit ("13 s"), dashed.
// - Strokes: one every half grid step inside the field, along the way the swell
//   travels (a faint tail, a bright head); none where the corners' directions
//   disagree too much to blend.
// - An hour change replaces the texture, isolines and strokes in one effect,
//   so the next frame MapLibre draws shows the new hour.
// - The legend names the model, its run and age and the valid hour, as a model
//   forecast and never a buoy observation; a click reads height, period and
//   direction there.
//
// Erasable syntax only: tests/test_swell_layer.mjs imports it by type stripping.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {compass} from '../landing/readings.ts';
import {day, hour, layers, region} from '../state.ts';
import {chartMark} from './chart.ts';
import type {ChartMark} from './coastline.ts';
import type {Engine, Overlay} from './engine.ts';
import {fieldTexture, isolines} from './field.ts';
import {WAVE_MODEL, loadForecast, swellPoints, type WaveForecast} from './forecast-grid.ts';
import {forecastTime} from './frames.ts';
import {layerEntry, setRailNote} from './layers.ts';
import {MPA_FILL} from './mpa.ts';
import {ramps, readPalette, type Palette} from './palette.ts';
import {shownPresentation, terrainHour} from './stage.ts';
import {LABEL_FONT} from './style.ts';
import {surfaceField, type SurfaceField} from './surface-field.js';

const REGISTRY_ID = 'swell' as const;
export const SWELL_SOURCE = 'swell';
export const ISOLINE_SOURCE = 'swell-period';
export const STROKE_SOURCE = 'swell-direction';
export const SWELL_LAYER = 'swell';
export const ISOLINE_LAYER = 'swell-period';
export const ISOLINE_LABELS = 'swell-period-labels';
export const STROKE_CASING = 'swell-direction-casing';
export const STROKE_LAYER = 'swell-direction';
export const SWELL_OPACITY = 0.75;
/** The texture's scale in feet: fixed, so the same colour is the same height at every hour. */
export const HEIGHT_SCALE: readonly [number, number] = [0, 15];
/** Blended from-direction vectors shorter than this mean the corners disagree: no stroke, "mixed" in a reading. */
export const MIN_AGREEMENT = 0.5;
const HOUR = 3_600_000;
/** The feed is read again this often while Swell is on (it is cached for five minutes at the edge). */
export const REFRESH_MS = 30 * 60_000;

/** The field for one listed hour. */
export interface SwellFrame {
  /** Changes with the run, its retrieval or the hour: a new key is a new texture. */
  readonly key: string;
  /** [height ft, period s, sin and cos of the from-direction] */
  readonly field: SurfaceField;
  readonly validAt: number;
  readonly issuedAt: number;
  readonly step: readonly [number, number];
  readonly height: readonly [number, number];
  readonly period: readonly [number, number];
  /** The samples' blended from-direction, degrees true, or null when they disagree. */
  readonly from: number | null;
  /** "run Oct 8, 5 pm · 13 h old · valid Thu Oct 9, 3 pm" */
  readonly stamp: string;
}
export interface SwellStatus {
  readonly drawn: SwellFrame | null;
  /** The rail's short note. */
  readonly note: string;
  /** Why nothing draws, for the legend; '' when a frame draws or the layer is off. */
  readonly reason: string;
  readonly basis: string;
}
export interface SwellLoad {readonly state: 'idle' | 'loading' | 'ready' | 'error'; readonly region: string | null; readonly forecast: WaveForecast | null; readonly at: number}

export const SWELL_BASIS = layerEntry('swell').basis;
const OFF: SwellStatus = {drawn: null, note: '', reason: '', basis: SWELL_BASIS};
const none = (note: string, reason: string): SwellStatus => ({...OFF, note, reason});

const formats = new Map<string, Intl.DateTimeFormat>();
function parts(ms: number, tz: string): Record<string, string> {
  let f = formats.get(tz);
  if (!f) formats.set(tz, f = new Intl.DateTimeFormat('en-US', {timeZone: tz, weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', hour12: true}));
  return Object.fromEntries(f.formatToParts(new Date(ms)).map(p => [p.type, p.value]));
}
/** "Oct 8, 5 pm" in the region's zone. */
export const runText = (ms: number, tz: string): string => { const p = parts(ms, tz); return `${p.month} ${p.day}, ${p.hour} ${(p.dayPeriod ?? '').toLowerCase()}`; };
/** "Thu 3 pm", or with its date: "Thu Oct 9, 3 pm". */
export const validText = (ms: number, tz: string, dated = false): string => {
  const p = parts(ms, tz);
  return `${p.weekday} ${dated ? `${p.month} ${p.day}, ` : ''}${p.hour} ${(p.dayPeriod ?? '').toLowerCase()}`;
};
const age = (ms: number): string => { const h = Math.floor(Math.max(0, ms) / HOUR); return h < 1 ? 'under 1 h' : h < 72 ? `${h} h` : `${Math.floor(h / 24)} d`; };
const span = ([low, high]: readonly [number, number], unit: string): string => low.toFixed(1) === high.toFixed(1) ? `${low.toFixed(1)} ${unit}` : `${low.toFixed(1)}–${high.toFixed(1)} ${unit}`;
const deg = (n: number): string => `${Number(n.toFixed(3))}°`;
const bearing = (sin: number, cos: number): number | null => Math.hypot(sin, cos) < MIN_AGREEMENT ? null : (Math.atan2(sin, cos) * 180 / Math.PI + 360) % 360;

/** The legend's reading for the frame: heights, periods and the blended direction. */
export const frameSummary = (f: SwellFrame): string =>
  `${span(f.height, 'ft')} · ${span(f.period, 's')} · ${f.from === null ? 'direction mixed' : `from ${compass(f.from)}`}`;

/** The frame's sentence: model, grid, run, valid hour, what it is not, and how it is drawn. */
export function frameBasis(f: SwellFrame, now: Date, tz: string): string {
  const [dx, dy] = f.step, grid = Math.abs(dx - dy) < 1e-6 ? deg(dx) : `${deg(dx)} × ${deg(dy)}`;
  return `${WAVE_MODEL.name} (${WAVE_MODEL.resolution}) model forecast of the primary swell, sampled on the region's ${grid} forecast grid; `
    + `run of ${runText(f.issuedAt, tz)} (${age(now.getTime() - f.issuedAt)} old), valid ${validText(f.validAt, tz, true)}. A model forecast, not a buoy observation. `
    + `Colour runs from ${HEIGHT_SCALE[0]} ft to ${HEIGHT_SCALE[1]} ft and above at every hour; dashed lines join equal period in whole seconds; strokes run the way the swell travels. Outside the grid stays blank.`;
}

// One frame per forecast and hour: play and the clock re-judge the gate, never rebuild a field.
const frames = new WeakMap<WaveForecast, Map<number, SwellFrame | null>>();
/** The field at listed hour `validAt` (epoch ms), or null when no complete grid cell has height, period and direction. */
export function swellFrame(f: WaveForecast, validAt: number, now: Date, tz: string): SwellFrame | null {
  let memo = frames.get(f);
  if (!memo) frames.set(f, memo = new Map());
  if (!memo.has(validAt)) {
    const points = swellPoints(f, validAt / 1000), field = f.step && f.model ? surfaceField(points, {step: [f.step[0], f.step[1]]}) : null;
    const used = field ? points.filter(p => field.quads.some(q => q.corners.includes(p))) : [];
    const range = (k: number): [number, number] => [Math.min(...used.map(p => p.values[k]!)), Math.max(...used.map(p => p.values[k]!))];
    const sum = (k: number): number => used.reduce((n, p) => n + p.values[k]!, 0) / used.length;
    memo.set(validAt, field && f.step && f.model ? {key: `${f.region}|${f.model.issued}|${f.retrieved}|${validAt}`, field, validAt, issuedAt: f.model.issued * 1000,
      step: f.step, height: range(0), period: range(1), from: bearing(sum(2), sum(3)), stamp: ''} : null);
  }
  const frame = memo.get(validAt) ?? null;
  return frame && {...frame, stamp: `run ${runText(frame.issuedAt, tz)} · ${age(now.getTime() - frame.issuedAt)} old · valid ${validText(validAt, tz, true)}`};
}

/** What Swell shows for the feed's state at the dock's hour `at`. */
export function swellStatus(on: boolean, load: SwellLoad, at: Date, now: Date, tz: string): SwellStatus {
  if (!on) return OFF;
  const f = load.forecast, name = WAVE_MODEL.name;
  if (!f) return load.state === 'error' ? none('unavailable', 'Swell unavailable: the regional wave forecast failed to load.') : none('loading', 'Loading the regional wave forecast.');
  if (!f.step) return none('no forecast grid for this region', 'Swell unavailable: this region\'s forecast points do not form a grid, so no field is drawn.');
  if (!f.model) return none('unavailable', `Swell unavailable: the regional forecast carries no ${name} run.`);
  const issued = f.model.issued * 1000, run = runText(issued, tz);
  const t = forecastTime(f.model.times.map(s => s * 1000), issued, f.retrieved, at, now);
  if (t === null) {
    if (now.getTime() - issued > 36 * HOUR) return none(`no fresh forecast · run ${run}`, `Swell unavailable: the latest ${name} run, of ${run}, is past its 36-hour age limit.`);
    if (now.getTime() - f.retrieved > 6 * HOUR) return none(`no fresh forecast · run ${run}`, 'Swell unavailable: the regional forecast was last retrieved more than 6 hours ago.');
    const last = f.model.times.at(-1);
    return none('no forecast for this hour', `Swell unavailable: the selected hour is outside the ${name} run of ${run}${last === undefined ? '' : `, which ends ${validText(last * 1000, tz, true)}`}.`);
  }
  const frame = swellFrame(f, t, now, tz);
  if (!frame) return none(`no complete grid cell · valid ${validText(t, tz)}`,
    `Swell unavailable: no cell of the ${name} grid has height, period and direction at all four corners for ${validText(t, tz, true)}; missing samples stay blank.`);
  return {drawn: frame, note: `valid ${validText(t, tz)} · run ${age(now.getTime() - issued)} old`, reason: '', basis: frameBasis(frame, now, tz)};
}

/** Period isolines at whole seconds through the field's complete quads, each labelled with the unit. */
export function periodLines(f: SwellFrame): ReturnType<typeof isolines> {
  const field = surfaceField(f.field.quads.flatMap(q => q.corners).filter((p, i, all) => all.indexOf(p) === i).map(p => ({lon: p.lon, lat: p.lat, values: [p.values[1]!]})), {step: [f.step[0], f.step[1]]});
  const levels = Array.from({length: Math.floor(f.period[1]) - Math.ceil(f.period[0]) + 1}, (_, i) => Math.ceil(f.period[0]) + i);
  return field ? isolines(field, levels, level => ({label: `${level} s`, major: true})) : {type: 'FeatureCollection', features: []};
}

type Stroke = {type: 'Feature'; properties: {part: 'tail' | 'head'}; geometry: {type: 'LineString'; coordinates: number[][]}};
/** One stroke every half grid step inside the field, centred there, pointing the way the swell travels: a tail and a head. */
export function directionStrokes(f: SwellFrame): {type: 'FeatureCollection'; features: Stroke[]} {
  const [west, south, east, north] = f.field.bounds, sx = f.step[0] / 2, sy = f.step[1] / 2, features: Stroke[] = [];
  for (let j = 0; j < Math.round((north - south) / sy); j++) for (let i = 0; i < Math.round((east - west) / sx); i++) {
    const lon = west + (i + 0.5) * sx, lat = south + (j + 0.5) * sy, v = f.field.sample(lon, lat), from = v && bearing(v[2]!, v[3]!);
    if (from === null || from === undefined) continue;
    // About half the spacing long, in kilometres on the ground; the swell travels away from `from`.
    const kx = 111.32 * Math.cos(lat * Math.PI / 180), ky = 110.57, km = 0.5 * Math.min(sx * kx, sy * ky), to = (from + 180) * Math.PI / 180;
    const at = (t: number): number[] => [lon + Math.sin(to) * km * (t - 0.5) / kx, lat + Math.cos(to) * km * (t - 0.5) / ky];
    features.push({type: 'Feature', properties: {part: 'tail'}, geometry: {type: 'LineString', coordinates: [at(0), at(0.6)]}},
      {type: 'Feature', properties: {part: 'head'}, geometry: {type: 'LineString', coordinates: [at(0.6), at(1)]}});
  }
  return {type: 'FeatureCollection', features};
}

/** The texture, period isolines with their labels and the direction strokes, under the protected areas (§ 9). */
export function swellOverlay(p: Palette): Overlay {
  const empty = {type: 'geojson' as const, data: {type: 'FeatureCollection' as const, features: []}};
  const width = (low: number, high: number): MapLibre.ExpressionSpecification => ['interpolate', ['linear'], ['zoom'], 7, low, 12, high];
  const head = (a: number, b: number): MapLibre.ExpressionSpecification => ['case', ['==', ['get', 'part'], 'head'], a, b];
  return {
    sources: {[SWELL_SOURCE]: {type: 'image', coordinates: [[0, 1], [1, 1], [1, 0], [0, 0]]}, [ISOLINE_SOURCE]: empty, [STROKE_SOURCE]: empty},
    layers: [
      {id: SWELL_LAYER, type: 'raster', source: SWELL_SOURCE, paint: {'raster-opacity': SWELL_OPACITY, 'raster-resampling': 'linear', 'raster-fade-duration': 0}},
      {id: ISOLINE_LAYER, type: 'line', source: ISOLINE_SOURCE, layout: {'line-join': 'round'},
        paint: {'line-color': p.text, 'line-width': width(0.6, 1.2), 'line-opacity': 0.45, 'line-dasharray': [3, 2]}},
      {id: ISOLINE_LABELS, type: 'symbol', source: ISOLINE_SOURCE,
        layout: {'symbol-placement': 'line', 'symbol-spacing': 320, 'text-field': ['get', 'label'], 'text-font': [LABEL_FONT], 'text-size': 11},
        paint: {'text-color': p.text, 'text-halo-color': p.bg, 'text-halo-width': 1.2}},
      {id: STROKE_CASING, type: 'line', source: STROKE_SOURCE, layout: {'line-cap': 'round'},
        paint: {'line-color': p.bg, 'line-opacity': 0.45, 'line-width': head(4, 3)}},
      {id: STROKE_LAYER, type: 'line', source: STROKE_SOURCE, layout: {'line-cap': 'round'},
        paint: {'line-color': p.text, 'line-opacity': head(0.95, 0.4), 'line-width': head(2.2, 1.2)}},
    ],
  };
}

/** The mark card's reading at a clicked point inside the drawn field, or null outside it. */
export function swellMark(f: SwellFrame, at: {lon: number; lat: number}, now: Date, tz: string): ChartMark | null {
  const v = f.field.sample(at.lon, at.lat);
  if (!v) return null;
  const from = bearing(v[2]!, v[3]!);
  return {
    id: `swell:${f.key}`, name: 'Primary swell', kind: `Model forecast · valid ${validText(f.validAt, tz, true)}`,
    reading: `${v[0]!.toFixed(1)} ft · ${v[1]!.toFixed(1)} s · ${from === null ? 'direction mixed' : `from ${compass(from)} ${Math.round(from)}°`}`,
    source: `${WAVE_MODEL.name} · ${f.stamp}`,
    basis: `${frameBasis(f, now, tz)} Display interpolation between adjacent grid samples, which adds no measurements.`,
  };
}

/** What the rail and legend show for Swell. */
export const swellState = signal<SwellStatus>(OFF);

export interface SwellOptions {
  engine: ReadonlySignal<Engine | null>;
  zone: () => string;
  fetchFn?: typeof fetch;
  page?: () => string;
  palette?: () => Palette;
  now?: () => Date;
}

export function createSwell(o: SwellOptions): {reading(at: {lon: number; lat: number}): ChartMark | null; destroy(): void} {
  const {engine, zone, fetchFn = (...a) => fetch(...a), page = () => location.href, palette = () => readPalette(), now = () => new Date()} = o;
  const tick = signal(0), load = signal<SwellLoad>({state: 'idle', region: null, forecast: null, at: 0});
  const on = computed(() => layers.value.includes(REGISTRY_ID));
  const status = computed(() => {
    void tick.value;
    const t = now(), l = load.value, id = region.value;
    return swellStatus(on.value, l.region === id ? l : {state: 'loading', region: id, forecast: null, at: 0}, terrainHour(hour.value, t, day.value, zone()), t, zone());
  });
  let alive = true, drawnKey = '', drawnOn: Engine | null = null, timer: ReturnType<typeof setTimeout> | undefined;
  const withdraw = (): void => { if (chartMark.peek()?.id.startsWith('swell:')) chartMark.value = null; };

  async function read(id: string): Promise<void> {
    const kept = load.peek().region === id ? load.peek().forecast : null, at = now().getTime();
    load.value = {state: 'loading', region: id, forecast: kept, at};
    const next = await loadForecast(id, fetchFn, page());
    if (!alive || region.peek() !== id) return;
    // A failed refresh keeps the last good feed, whose run leaves through the gate.
    load.value = {state: next || kept ? 'ready' : 'error', region: id, forecast: next ?? kept, at};
  }

  const disposers = [
    // Read the region's feed only while Swell is on: on a region change, and again every REFRESH_MS.
    effect(() => {
      const id = region.value, l = load.peek();
      void tick.value;
      if (!on.value || !id) return;
      if (l.region !== id || (l.state !== 'loading' && now().getTime() - l.at >= REFRESH_MS)) void read(id);
    }),
    effect(() => {
      const s = status.value;
      swellState.value = s;
      setRailNote(REGISTRY_ID, on.value ? s.note : '');
    }),
    // A new frame (an hour, a run, a region) repaints at once; none (off, refused, stale) removes everything.
    effect(() => {
      const e = engine.value, f = status.value.drawn, key = f?.key ?? '';
      if (!e || (key === drawnKey && e === drawnOn)) return;
      if (key !== drawnKey) withdraw();
      drawnKey = key; drawnOn = e;
      if (!f) { e.setOverlay(REGISTRY_ID, null); return; }
      const p = palette();
      e.setOverlay(REGISTRY_ID, swellOverlay(p), MPA_FILL);
      e.setImage(SWELL_SOURCE, fieldTexture(f.field, HEIGHT_SCALE, ramps(p).swell, v => v[0]!));
      e.setData(ISOLINE_SOURCE, periodLines(f));
      e.setData(STROKE_SOURCE, directionStrokes(f));
    }),
    // Re-judge at the next whole hour (the dock's default hour moves on), at the run's and the feed's age limits, and to refresh.
    effect(() => {
      const l = load.value, f = l.forecast, t = now().getTime();
      clearTimeout(timer);
      if (!on.value) return;
      const limits = [...l.region ? [l.at + REFRESH_MS] : [], ...f?.model ? [f.model.issued * 1000 + 36 * HOUR, f.retrieved + 6 * HOUR].filter(x => x > t) : []];
      const next = Math.min((Math.floor(t / HOUR) + 1) * HOUR, ...limits);
      timer = setTimeout(() => { tick.value++; }, Math.min(Math.max(1000, next - t + 1000), 2 ** 31 - 1));
    }),
  ];
  return {
    reading(at) {
      const f = status.peek().drawn;
      return f && drawnKey === f.key && shownPresentation.peek() === 'chart' ? swellMark(f, at, now(), zone()) : null;
    },
    destroy() {
      alive = false;
      for (const dispose of disposers) dispose();
      clearTimeout(timer);
      withdraw();
      swellState.value = OFF;
      setRailNote(REGISTRY_ID, '');
    },
  };
}

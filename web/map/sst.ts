// Water temp (FE-16, docs/plans/front-end/design.md § 9): the bound coast
// report's daily sea-surface temperature analysis on the Chart, as a texture
// (web/map/field.ts) in an image source, with 0.5 °F contours labelled at whole
// degrees, under the swell field (FE-17) and the protected areas.
//
// - Data: `spatial.surfaceTemperature` of the coast report (web/coast-data.ts,
//   FE-74), requested only while Water temp is on, for the region's place when
//   it binds a local report (Morro Bay and Cambria). The product is the one that
//   report carries, named by the report's own status for that source id: on
//   2026-10-09 the bridge served Fish's report with NASA JPL MUR (0.01°, sampled
//   every 0.02°); SkipperCast's own report (FE-87) carries NOAA Geo-Polar Blended
//   (0.05°). A place with no local report reads its region's own published
//   analysis instead (web/map/habitat-feed.ts, #491): the conditions feed's
//   NOAA Geo-Polar Blended layer, its tiles checked by SHA-256 in the browser.
//   A region whose feed lists no analysis draws nothing and the rail says so.
// - Gate: fish's rule, the analysis and its retrieval each under 72 hours old
//   (at most 5 minutes ahead of the clock), the source's status `ok`, and the
//   analysis no later than the dock's hour. A regional feed's analysis takes its
//   layer's own status (`ok` or `retained`) and its own `max_age_hours`. Otherwise nothing draws, and the
//   rail and legend give the reason and the analysis date.
// - Grid: packages/coast `surfaceField` at the analysis's own sample spacing.
//   The texture and contours cover complete quads only: masked land and missing
//   cells stay blank. A grid it refuses draws nothing, and a refused or stale
//   replacement removes the texture and contours of the analysis before it.
// - Legend: the displayed band range and step follow supported water in the
//   settled Chart viewport. The analysis error stays in the basis and reading.
//
// Erasable syntax only: tests/test_field_texture.mjs imports it by type stripping.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {coastData, type CoastData, type CoastStatus} from '../coast-data.ts';
import {regionalSST, type RegionalSST} from './habitat-feed.ts';
import type {SurfaceTemperature} from '../../packages/coast/src/spatial-types.ts';
import type {CoastReportContext} from '../../packages/coast/src/state/report-binding.ts';
import type {Report} from '../../packages/coast/src/types.ts';
import {day, hour, layers} from '../state.ts';
import {chartMark} from './chart.ts';
import type {ChartMark} from './coastline.ts';
import {CONTRAST_LAYER} from './contrast.ts';
import type {Engine, Overlay} from './engine.ts';
import {isolines, mercatorDisplay, sampleDisplay, textureSize, type Corners} from './field.ts';
import {layerEntry, setRailNote} from './layers.ts';
import {LAYERS_STYLE} from './layers-style.gen.ts';
import {DEPTH_BOTTOM} from './depth-contours.ts';
import {COAST_NOT_SAVED, COAST_OFFLINE_COPY, NOT_SAVED, TILES_NOT_SAVED, TILES_OFFLINE_COPY, watchOffline} from './offline.ts';
import {pair, sp, type StatusCopy} from './status-copy.ts';
import {MPA_FILL} from './mpa.ts';
import {kitMinZoom} from './nearshore-paint.ts';
import {NEARSHORE_STYLE} from './nearshore-style.gen.ts';
import {readPalette, type Palette} from './palette.ts';
import {camera, shownPresentation, terrainHour} from './stage.ts';
import {sstBandLayers, sstBandModel, sstBandPixels, sstRamp, SST_BAND_SOURCE, SST_STYLE} from './sst-bands.ts';
import {LABEL_FONT, PLACE_LABELS} from './style.ts';
import {surfaceField, temperatureRange, type SurfaceField} from './surface-field.js';
import {SWELL_LAYER} from './swell.ts';
import {paintEdits} from './theme-restyle.ts';

const REGISTRY_ID = 'water-temp' as const;
export const SST_SOURCE = 'water-temp';
export const CONTOUR_SOURCE = 'water-temp-contours';
export const SST_LAYER = 'water-temp';
export const CONTOUR_LAYER = 'water-temp-contours';
export const CONTOUR_LABELS = 'water-temp-labels';
const HOUR = 3_600_000;
/** fish's `live(…, 72)`: an analysis, and its retrieval, under 72 hours old and at most 5 minutes ahead. */
export const MAX_AGE_MS = LAYERS_STYLE.layers['sst-fill'].data_age.max_age_h * HOUR;
const AHEAD_MS = 5 * 60_000;

/** An analysis that passed the gate, with its grid. */
export interface Analysis {
  /** Metadata for the reading card ID. Paint follows the analysis object, not these timestamps. */
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
  /** The age limit it was judged by: 72 hours for a report's, the layer's own for a regional feed's. */
  readonly limitMs: number;
}
export interface WaterTempStatus {
  readonly drawn: Analysis | null;
  /** The rail's short note. */
  readonly note: string;
  /** Why nothing draws, for the legend; '' when an analysis draws or the layer is off. */
  readonly reason: string;
  /** One sentence or two: product, grid, date and age, error, and what the field is not. */
  readonly basis: string;
  /** SC1352-02: catalogue parts for `note`, `reason` and the legend `stamp`; absent when off or when a producer attaches none. */
  readonly copy?: StatusCopy;
}

export const WATER_TEMP_BASIS = layerEntry('water-temp').basis;
const OFF: WaterTempStatus = {drawn: null, note: '', reason: '', basis: WATER_TEMP_BASIS};
const none = (note: string, reason: string, copy?: StatusCopy): WaterTempStatus => ({...OFF, note, reason, ...(copy ? {copy} : {})});

const dates = new Map<string, Intl.DateTimeFormat>();
/** "Oct 7" in the region's zone. */
export function dayText(iso: string, tz: string): string {
  let f = dates.get(tz);
  if (!f) dates.set(tz, f = new Intl.DateTimeFormat('en-US', {timeZone: tz, month: 'short', day: 'numeric'}));
  return f.format(new Date(iso));
}
/** "under 1 h", "42 h", "3 d". */
const age = (ms: number): string => { const h = Math.floor(Math.max(0, ms) / HOUR); return h < 1 ? 'under 1 h' : h < 72 ? `${h} h` : `${Math.floor(h / 24)} d`; };
const fresh = (iso: string, now: Date, limit = MAX_AGE_MS): boolean => { const d = now.getTime() - Date.parse(iso); return Number.isFinite(d) && d >= -AHEAD_MS && d < limit; };
/** Age check for an already admitted SST source; source status and dock hour are separate. */
export function sstDataIsFresh(
  {analysedAt, fetchedAt}: Pick<SurfaceTemperature, 'analysedAt' | 'fetchedAt'>,
  now: Date,
  limitMs = MAX_AGE_MS,
): boolean {
  return fresh(analysedAt, now, limitMs) && fresh(fetchedAt, now, limitMs);
}
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
export function analysisStatus(on: boolean, status: CoastStatus, report: Report | null, at: Date, now: Date, tz: string, offline = false): WaterTempStatus {
  if (!on) return OFF;
  if (offline && status === 'error' && !report) return none(NOT_SAVED, COAST_NOT_SAVED, COAST_OFFLINE_COPY);
  if (status === 'unbound') return none('no analysis for this region', 'Water temp unavailable: no local surface-temperature analysis covers this region yet.', pair(sp('map.status.common.noRegion'), sp('map.status.sst.noRegion')));
  if (status === 'error' || status === 'invalid') return none('unavailable', 'Water temp unavailable: the coast report failed to load.', pair(sp('map.status.common.unavailable'), sp('map.status.sst.reportFailed')));
  if (status === 'expired') return none('expired', 'Water temp unavailable: the coast report passed its age limit.', pair(sp('map.status.common.expired'), sp('map.status.sst.reportExpired')));
  if (!report) return none('loading', 'Loading the coast report.', pair(sp('map.status.common.loading'), sp('map.status.sst.loadingReport')));
  const sst = report.spatial?.surfaceTemperature;
  const source = sst && Array.isArray(report.sources) ? report.sources.find(s => s?.id === sst.sourceId) : undefined;
  if (!sst || sst.kind !== 'analysis' || !Number.isFinite(Date.parse(sst.analysedAt)) || source?.outcome !== 'ok' || source.kind !== 'analysis' || typeof source.label !== 'string' || !source.label)
    return none('no analysis in the report', 'Water temp unavailable: the coast report carries no surface-temperature analysis that loaded.', pair(sp('map.status.sst.noReportNote'), sp('map.status.sst.noReportAnalysis')));
  return judge(sst, source.label.split(' · ')[0]!.trim(), MAX_AGE_MS, at, now, tz);
}

const stale = (product: string, analysedAt: string, limit: number, tz: string): WaterTempStatus => {
  const date = dayText(analysedAt, tz), when = {day: analysedAt, tz};
  return none(`no fresh analysis · last ${date}`, `Water temp unavailable: the latest ${product} analysis, for ${date}, is past its ${Math.round(limit / HOUR)}-hour age limit.`,
    pair(sp('map.status.common.staleNote', {date: when}), sp('map.status.sst.stale', {product, date: when, hours: Math.round(limit / HOUR)})));
};

/** What Water temp shows from the region's own feed (`null` while it loads) for a place with no local report. */
export function regionalStatus(on: boolean, feed: RegionalSST | null, at: Date, now: Date, tz: string, offline = false): WaterTempStatus {
  if (!on) return OFF;
  if (offline && feed?.state === 'error' && feed.network) return none(NOT_SAVED, TILES_NOT_SAVED, TILES_OFFLINE_COPY);
  if (!feed) return none('loading', 'Loading the region\'s surface-temperature analysis.', pair(sp('map.status.common.loading'), sp('map.status.common.loadingRegion')));
  if (feed.state === 'none') return none('no analysis for this region', 'Water temp unavailable: no local surface-temperature analysis covers this region yet.', pair(sp('map.status.common.noRegion'), sp('map.status.sst.noRegion')));
  if (feed.state === 'error') return none('unavailable', 'Water temp unavailable: the region\'s surface-temperature analysis failed to load or failed its checks.', pair(sp('map.status.common.unavailable'), sp('map.status.sst.feedFailed')));
  if (feed.state === 'listed') return feed.analysedAt && (feed.layerStatus === 'stale' || !fresh(feed.analysedAt, now, feed.maxAgeMs))
    ? stale(feed.product, feed.analysedAt, feed.maxAgeMs, tz)
    : none('no analysis in the feed', 'Water temp unavailable: the region\'s feed carries no surface-temperature analysis that loaded.', pair(sp('map.status.common.noFeedAnalysis'), sp('map.status.sst.noFeedAnalysis')));
  return judge(feed.sst, feed.product, feed.maxAgeMs, at, now, tz);
}

/** The shared gate: age (the analysis's and its retrieval's), the dock's hour, then the grid. */
function judge(sst: SurfaceTemperature, product: string, limit: number, at: Date, now: Date, tz: string): WaterTempStatus {
  const date = dayText(sst.analysedAt, tz), when = {day: sst.analysedAt, tz};
  if (!sstDataIsFresh(sst, now, limit)) return stale(product, sst.analysedAt, limit, tz);
  if (Date.parse(sst.analysedAt) > at.getTime())
    return none(`analysis after this hour · ${date}`, `Water temp unavailable: the ${product} analysis, for ${date}, is later than the selected hour.`,
      pair(sp('map.status.common.afterHourNote', {date: when}), sp('map.status.sst.afterHour', {product, date: when})));
  const built = grid(sst);
  if (!built) return none(`grid cannot be drawn · ${date}`,
    `Water temp unavailable: the ${product} analysis for ${date} is not a grid that can be drawn without bridging gaps, and no earlier analysis is shown.`,
    pair(sp('map.status.sst.gridNote', {date: when}), sp('map.status.sst.noGrid', {product, date: when})));
  const stamp = `analysis ${date} · ${age(now.getTime() - Date.parse(sst.analysedAt))} old`;
  const drawn: Analysis = {key: `${sst.sourceId}|${sst.analysedAt}|${sst.fetchedAt}`, sst, product, ...built, stamp, limitMs: limit};
  const shown = sp('map.status.common.stamp', {date: when, age: {age: now.getTime() - Date.parse(sst.analysedAt)}});
  return {drawn, note: stamp, reason: '', basis: analysisBasis(drawn, now, tz), copy: {note: [shown], stamp: [`${product} · `, shown]}};
}

/**
 * packages/coast `fieldContours` every kit `overlays.sst_isoline_step_f` (0.5 °F) across `range`, joined into lines per level
 * (field.ts `isolines`); whole degrees are `major` and carry their label with the unit.
 */
export function contourLines(field: SurfaceField, range: readonly [number, number], step: number = NEARSHORE_STYLE.overlays.sst_isoline_step_f): ReturnType<typeof isolines> {
  const levels = Array.from({length: Math.round((range[1] - range[0]) / step) + 1}, (_, i) => range[0] + i * step);
  return isolines(field, levels, level => { const major = Number.isInteger(level); return {label: `${major ? level : level.toFixed(1)} °F`, major}; });
}

/** The texture, its contours and their labels, under the protected areas (§ 9 order); filled by setImage and setData. A live theme switch re-runs the same layer builder with the new palette (`themePaint`); ids and sources stay.
 * MSK-2: the texture's opacity follows the kit's field opacity by zoom, and the isotherms draw from the kit's isoline zoom. */
function waterTempLayers(p: Palette): Overlay['layers'] {
  const width: MapLibre.ExpressionSpecification = ['interpolate', ['linear'], ['zoom'], 7, 0.5, 12, 1.2];
  const isolines = kitMinZoom(NEARSHORE_STYLE.overlays.isolines_from_zoom);
  const [fill, edge] = sstBandLayers(p);
  return [
    {...fill, id: SST_LAYER, source: SST_SOURCE}, edge,
    {id: CONTOUR_LAYER, type: 'line', source: CONTOUR_SOURCE, minzoom: isolines, layout: {'line-join': 'round'},
      paint: {'line-color': p.text, 'line-width': width, 'line-opacity': ['case', ['get', 'major'], 0.5, 0.25]}},
    {id: CONTOUR_LABELS, type: 'symbol', source: CONTOUR_SOURCE, minzoom: isolines, filter: ['get', 'major'],
      layout: {'symbol-placement': 'line', 'symbol-spacing': 360, 'text-field': ['get', 'label'], 'text-font': [LABEL_FONT], 'text-size': 11},
      paint: {'text-color': p.text, 'text-halo-color': p.bg, 'text-halo-width': 1.2}},
  ];
}

/** One shared function, so equal overlays stay equal. A live theme switch re-runs the same layer builder with the new palette; ids and sources stay. */
const themePaint = (pal: Palette) => paintEdits(waterTempLayers(pal));
export function waterTempOverlay(p: Palette): Overlay {
  return {
    sources: {
      [SST_SOURCE]: {type: 'image', coordinates: [[0, 1], [1, 1], [1, 0], [0, 0]]},
      [SST_BAND_SOURCE]: {type: 'geojson', data: {type: 'FeatureCollection', features: []}},
      [CONTOUR_SOURCE]: {type: 'geojson', data: {type: 'FeatureCollection', features: []}},
    },
    layers: waterTempLayers(p), themePaint,
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

function imageGrid(field: SurfaceField) {
  const {width, height} = textureSize(field), [west, south, east, north] = field.bounds;
  const view = mercatorDisplay(field.bounds, width, height);
  const samples = sampleDisplay(view, (lon, lat) => field.sample(lon, lat)?.[0] ?? NaN);
  const coordinates: Corners = [[west, north], [east, north], [east, south], [west, south]];
  return {width, height, coordinates, view, samples};
}

function visibleWater(e: Engine, raster: ReturnType<typeof imageGrid>) {
  if (!e.view) return raster.samples;
  const {width, height} = e.view.size();
  if (!width || !height) return raster.samples;
  const nw = e.view.unproject(0, 0), se = e.view.unproject(width, height);
  const {view} = raster;
  const columns = view.lon.map((lon, x) => lon >= nw.lon && lon <= se.lon ? x : -1).filter(x => x >= 0);
  const rows = view.lat.map((lat, y) => lat <= nw.lat && lat >= se.lat ? y : -1).filter(y => y >= 0);
  return Float64Array.from(rows.flatMap(y => columns.map(x => raster.samples[y * raster.width + x]!)));
}

export interface WaterTempOptions {
  engine: ReadonlySignal<Engine | null>;
  zone: () => string;
  /** The region's report context, or null until the region is known. */
  place: () => CoastReportContext | null;
  data?: Pick<CoastData, 'coastReport' | 'coastStatus' | 'setPlace' | 'load'>;
  palette?: () => Palette;
  now?: () => Date;
  /** For the regional feed of a place with no local report. */
  fetchFn?: typeof fetch;
  page?: () => string;
}
/** A regional feed is read again after an hour, keeping the last result until the next arrives. */
const FEED_REFRESH_MS = HOUR;

export function createWaterTemp(o: WaterTempOptions): {reading(at: {lon: number; lat: number}): ChartMark | null; destroy(): void} {
  const {engine, zone, place, data = coastData, palette = () => readPalette(), now = () => new Date(),
    fetchFn = (...a) => fetch(...a), page = () => location.href} = o;
  const tick = signal(0);
  const connection = watchOffline();
  const on = computed(() => layers.value.includes(REGISTRY_ID));
  const report = computed(() => place() !== null ? data.coastStatus.value.report : 'loading');
  /** The regional feed's latest result for a region, null while its first read is in flight. */
  const feed = signal<{region: string; result: RegionalSST | null} | null>(null);
  const status = computed(() => {
    void tick.value;
    const t = now(), p = place(), at = terrainHour(hour.value, t, day.value, zone());
    if (report.value === 'unbound' && p) {
      const f = feed.value;
      return regionalStatus(on.value, f?.region === p.regionId ? f.result : null, at, t, zone(), connection.offline.value);
    }
    return analysisStatus(on.value, report.value, data.coastReport.value?.data ?? null, at, t, zone(), connection.offline.value);
  });
  let feedRegion = '', feedAt = 0, feedAbort: AbortController | undefined;
  let painted: SurfaceTemperature | null = null, drawnOn: Engine | null = null, timer: ReturnType<typeof setTimeout> | undefined;
  let raster: ReturnType<typeof imageGrid> | undefined;
  let restyleBands: ((p: Palette) => void) | undefined;
  const bandState = signal<ReturnType<typeof sstBandModel>>(null);
  const resized = signal(0);
  const withdraw = (): void => { if (chartMark.peek()?.id.startsWith('sst:')) chartMark.value = null; };

  const disposers = [
    // Ask for the report only while Water temp is on, for the region's place once it is known.
    effect(() => {
      const p = place();
      if (!on.value || !p) return;
      data.setPlace(p);
      void data.load('report');
    }),
    // A place with no local report reads its region's feed, again after an hour while Water temp stays on.
    effect(() => {
      void tick.value;
      const p = place(), id = p?.regionId ?? '', t = now().getTime();
      if (!on.value || !p || report.value !== 'unbound' || (id === feedRegion && t - feedAt < FEED_REFRESH_MS)) return;
      feedAbort?.abort();
      const abort = feedAbort = new AbortController();
      if (id !== feedRegion) feed.value = {region: id, result: null};
      feedRegion = id; feedAt = t;
      regionalSST(id, {fetchFn, page: page(), now: new Date(t), signal: abort.signal})
        .then(result => { if (!abort.signal.aborted) feed.value = {region: id, result}; }, () => { /* aborted by a newer read */ });
    }),
    effect(() => {
      const s = status.value, band = bandState.value;
      waterTempState.value = s.drawn && band ? {...s, drawn: {...s.drawn, range: [band.low, band.high]}, basis: `${band.legend}. ${s.basis}`} : s;
      setRailNote(REGISTRY_ID, on.value ? s.note : '', on.value ? s.copy?.note : undefined);
    }),
    effect(() => engine.value?.view?.on?.('resize', () => { resized.value++; })),
    // A new analysis repaints; no analysis (off, refused, stale) removes the texture and the contours at once.
    effect(() => {
      const e = engine.value, a = status.value.drawn, generation = e ? a?.sst ?? null : null;
      if (generation === painted && e === drawnOn) return;
      if (generation !== painted) withdraw();
      painted = null; drawnOn = e; raster = undefined; restyleBands = undefined;
      if (!e) return;
      if (!a) { bandState.value = null; e.setOverlay(REGISTRY_ID, null); return; }
      const p = palette();
      // § 9 order: under Temp contrast, else swell, wind, depth contours, or protected areas.
      const overlay = waterTempOverlay(p);
      let paintedKey = '', edgeKey = '';
      raster = imageGrid(a.field);
      restyleBands = (pal: Palette): void => {
        const grid = raster, band = bandState.peek();
        if (!grid || !band) return;
        const bounds = [band.low, band.high, band.step].join();
        const ramp = sstRamp(pal), key = [bounds, ...ramp].join();
        if (key === paintedKey) return;
        paintedKey = key;
        const {width, height, coordinates, samples} = grid;
        e.setImage(SST_SOURCE, {width, height, coordinates, data: sstBandPixels(samples, band, ramp)});
        if (bounds !== edgeKey) {
          edgeKey = bounds;
          const levels = Array.from({length: band.count - 1}, (_, i) => band.low + (i + 1) * band.step);
          e.setData(SST_BAND_SOURCE, isolines(a.field, levels, () => ({label: '', major: false})));
        }
      };
      e.setOverlay(REGISTRY_ID, {...overlay, themePaint: (pal: Palette) => { restyleBands?.(pal); return overlay.themePaint!(pal); }},
        [CONTRAST_LAYER, 'chlorophyll', SWELL_LAYER, 'wind-casing', DEPTH_BOTTOM, PLACE_LABELS, MPA_FILL]);
      e.setData(CONTOUR_SOURCE, contourLines(a.field, a.range));
      painted = a.sst;
    }),
    effect(() => {
      const e = engine.value, a = status.value.drawn, zoom = camera.value?.zoom ?? SST_STYLE.zoom;
      void resized.value;
      if (!e || !a || e !== drawnOn || a.sst !== painted || !raster) return;
      const band = sstBandModel(visibleWater(e, raster), zoom);
      // An empty viewport must not let off-screen temperatures set its range.
      bandState.value = band;
      restyleBands?.(palette());
    }),
    // Re-judge at the analysis's 72-hour limit and at the next whole hour (the dock's default hour moves on).
    effect(() => {
      const a = status.value.drawn, t = now().getTime();
      clearTimeout(timer);
      if (!on.value) return;
      const limit = a ? Math.min(Date.parse(a.sst.analysedAt), Date.parse(a.sst.fetchedAt)) + a.limitMs : Infinity;
      timer = setTimeout(() => { tick.value++; }, Math.min(Math.max(1000, Math.min(limit, (Math.floor(t / HOUR) + 1) * HOUR) - t + 1000), 2 ** 31 - 1));
    }),
  ];
  return {
    reading(at) {
      const a = status.peek().drawn;
      return a && painted === a.sst && drawnOn === engine.peek() && shownPresentation.peek() === 'chart' ? sstMark(a, at, now(), zone()) : null;
    },
    destroy() {
      connection.destroy();
      for (const dispose of disposers) dispose();
      clearTimeout(timer);
      feedAbort?.abort();
      withdraw();
      waterTempState.value = OFF;
      setRailNote(REGISTRY_ID, '');
    },
  };
}

// Temp contrast (CI6-03, docs/plans/front-end/design.md § 9): the change in sea-surface
// temperature per distance across the region's published daily analysis, on the
// Chart, drawn only in cells where that change is larger than the analysis error.
//
// - Data: the conditions feed's `sst-analysis` layer (web/map/habitat-feed.ts
//   `regionalContrast`), its tiles checked by length and SHA-256 in the browser, as
//   Water temp's. The pipeline (src/skippercast/pipeline/habitat_dynamics.py
//   `gradients`) publishes each cell's centred native-grid gradient
//   (`temperature_gradient_c_per_km`) and `thermal_contrast_supported`: 1 where the
//   temperature change across the west and east, or the south and north, neighbours
//   exceeds the sum of their analysis errors. On 2026-10-20 the feed carried NOAA
//   Geo-Polar Blended at 0.05° for every region. The feed is read for every region,
//   bound to a coast report or not: a report carries no gradient.
// - Supported only (`contrastCells`): a cell draws only where the flag is 1 and,
//   checked again here from the tile's own temperatures and errors, one neighbour
//   pair's change exceeds its summed analysis error. A change within the error, a
//   cell with a missing neighbour or error, and masked land never draw.
// - Gate: the layer's own status (`ok` or `retained`), the analysis and its retrieval
//   under the layer's own age limit and never past 72 hours (at most 5 minutes ahead
//   of the clock), and the analysis no later than the dock's hour. Otherwise nothing
//   draws and the rail and legend say why.
// - Drawing: each supported cell as its own grid square, coloured on a fixed scale of
//   °F per nautical mile (CONTRAST_SCALE, the `--contrast-*` tokens), no interpolation
//   between cells. This is not the observed front the catalogue asks for (CI6-15).
//
// Erasable syntax only: tests/test_sst_contrast.mjs imports it by type stripping.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import type {CoastReportContext} from '../../packages/coast/src/state/report-binding.ts';
import {day, hour, layers} from '../state.ts';
import {chartMark} from './chart.ts';
import type {ChartMark} from './coastline.ts';
import type {Engine, Overlay} from './engine.ts';
import {regionalContrast, type ContrastSample, type RegionalContrast} from './habitat-feed.ts';
import {CONTRAST_SOURCE, layerEntry, setRailNote} from './layers.ts';
import {MPA_FILL} from './mpa.ts';
import {readPalette, type Palette} from './palette.ts';
import {shownPresentation, terrainHour} from './stage.ts';
import {SWELL_LAYER} from './swell.ts';

const REGISTRY_ID = 'sst-contrast' as const;
export const CONTRAST_LAYER = 'sst-contrast';
export const CONTRAST_OPACITY = 0.75;
const HOUR = 3_600_000;
/** The withhold rule: past 72 hours an analysis never draws, whatever limit its layer names. */
export const MAX_AGE_MS = 72 * HOUR;
const AHEAD_MS = 5 * 60_000;
/** °C per km to °F per nautical mile: 1.8 °F per °C, 1.852 km per nautical mile. */
export const F_PER_NMI = 1.8 * 1.852;
/** The legend's fixed scale, °F per nautical mile; stronger changes take the top colour. */
export const CONTRAST_SCALE = [0, 0.3] as const;

/** A drawn cell: its centre and its gradient in both units. */
export interface ContrastCell {readonly lat: number; readonly lon: number; readonly cPerKm: number; readonly fPerNmi: number}
export interface DrawnContrast {
  /** Changes with the product, its analysis time or its retrieval. */
  readonly key: string;
  readonly product: string;
  readonly analysedAt: string;
  readonly fetchedAt: string;
  readonly nativeResolutionDeg: number;
  readonly spacingDeg: readonly [number, number];
  /** The source's own credit line, or ''. */
  readonly credit: string;
  readonly cells: readonly ContrastCell[];
  /** Cells with a published gradient, drawn or not. */
  readonly judged: number;
  /** "analysis Oct 7 · 42 h old" */
  readonly stamp: string;
  /** The age limit it was judged by. */
  readonly limitMs: number;
}
export interface ContrastStatus {
  readonly drawn: DrawnContrast | null;
  readonly note: string;
  readonly reason: string;
  readonly basis: string;
}

export const CONTRAST_BASIS = layerEntry(REGISTRY_ID).basis;
const OFF: ContrastStatus = {drawn: null, note: '', reason: '', basis: CONTRAST_BASIS};
const none = (note: string, reason: string): ContrastStatus => ({...OFF, note, reason});

const dates = new Map<string, Intl.DateTimeFormat>();
/** "Oct 7" in the region's zone. */
function dayText(iso: string, tz: string): string {
  let f = dates.get(tz);
  if (!f) dates.set(tz, f = new Intl.DateTimeFormat('en-US', {timeZone: tz, month: 'short', day: 'numeric'}));
  return f.format(new Date(iso));
}
const age = (ms: number): string => { const h = Math.floor(Math.max(0, ms) / HOUR); return h < 1 ? 'under 1 h' : h < 72 ? `${h} h` : `${Math.floor(h / 24)} d`; };
const fresh = (iso: string, now: Date, limit: number): boolean => { const d = now.getTime() - Date.parse(iso); return Number.isFinite(d) && d >= -AHEAD_MS && d < limit; };
const deg = (value: number): string => `${Number(value.toFixed(3))}°`;
/** The layer's own limit, never past 72 hours. */
export const ageLimit = (layerMs: number): number => Math.min(layerMs, MAX_AGE_MS);

const key = (lat: number, lon: number): string => `${Math.round(lat * 1e6)},${Math.round(lon * 1e6)}`;
const beats = (a: ContrastSample | undefined, b: ContrastSample | undefined): boolean =>
  !!a && !!b && a.tempC !== null && b.tempC !== null && a.errorC !== null && b.errorC !== null && Math.abs(a.tempC - b.tempC) > a.errorC + b.errorC;

/**
 * The cells Temp contrast draws: flagged supported by the pipeline and, from the tile's own neighbours, a west-east
 * or south-north change that exceeds the pair's summed analysis error. Everything else is left out.
 */
export function contrastCells(samples: readonly ContrastSample[], spacingDeg: readonly [number, number]): ContrastCell[] {
  const [dy, dx] = spacingDeg, at = new Map(samples.map(s => [key(s.lat, s.lon), s]));
  const near = (s: ContrastSample, y: number, x: number): ContrastSample | undefined => at.get(key(s.lat + y * dy, s.lon + x * dx));
  const out: ContrastCell[] = [];
  for (const s of samples) {
    const g = s.gradientCPerKm;
    if (s.supported !== 1 || g === null || !(g >= 0) || s.tempC === null) continue;
    if (!beats(near(s, 0, -1), near(s, 0, 1)) && !beats(near(s, -1, 0), near(s, 1, 0))) continue;
    out.push({lat: s.lat, lon: s.lon, cPerKm: g, fPerNmi: g * F_PER_NMI});
  }
  return out;
}

/** The drawn analysis's sentence: product, grid, date and age, the support rule, then what it is not. */
export function contrastBasis(d: DrawnContrast, now: Date, tz: string): string {
  const grid = d.spacingDeg[0] > d.nativeResolutionDeg ? `${deg(d.nativeResolutionDeg)} grid sampled every ${deg(d.spacingDeg[0])}` : `${deg(d.nativeResolutionDeg)} grid`;
  return `${d.product} daily analysis on a ${grid}, for ${dayText(d.analysedAt, tz)} (${age(now.getTime() - Date.parse(d.analysedAt))} old), partly interpolated, with gaps under cloud filled. `
    + `Drawn in °F per nautical mile only in the ${d.cells.length} of ${d.judged} cells where the change across neighbouring cells exceeds their summed analysis error, `
    + `and withheld past its ${Math.round(d.limitMs / HOUR)}-hour age limit. Surface water only; a contrast cell is not a fish or catch location.${d.credit ? ` Credit: ${d.credit}.` : ''}`;
}

const stale = (product: string, analysedAt: string, limit: number, tz: string): ContrastStatus => {
  const date = dayText(analysedAt, tz);
  return none(`no fresh analysis · last ${date}`, `Temp contrast withheld: the latest ${product} analysis, for ${date}, is past its ${Math.round(limit / HOUR)}-hour age limit.`);
};

/** What Temp contrast shows from the region's feed (`null` while it loads) at the dock's hour `at`. */
export function contrastStatus(on: boolean, feed: RegionalContrast | null, at: Date, now: Date, tz: string): ContrastStatus {
  if (!on) return OFF;
  if (!feed) return none('loading', 'Loading the region\'s surface-temperature analysis.');
  if (feed.state === 'none') return none('no analysis for this region', 'Temp contrast unavailable: no published surface-temperature analysis covers this region yet.');
  if (feed.state === 'error') return none('unavailable', 'Temp contrast unavailable: the region\'s surface-temperature analysis failed to load or failed its checks.');
  if (feed.state === 'listed') {
    const limit = ageLimit(feed.maxAgeMs);
    if (feed.analysedAt && (feed.layerStatus === 'stale' || !fresh(feed.analysedAt, now, limit))) return stale(feed.product, feed.analysedAt, limit, tz);
    return feed.gradients ? none('no analysis in the feed', 'Temp contrast unavailable: the region\'s feed carries no surface-temperature analysis that loaded.')
      : none('no gradient in the feed', 'Temp contrast unavailable: the region\'s surface-temperature analysis publishes no temperature gradient.');
  }
  const limit = ageLimit(feed.maxAgeMs), date = dayText(feed.analysedAt, tz);
  if (!fresh(feed.analysedAt, now, limit) || !fresh(feed.fetchedAt, now, limit)) return stale(feed.product, feed.analysedAt, limit, tz);
  if (Date.parse(feed.analysedAt) > at.getTime())
    return none(`analysis after this hour · ${date}`, `Temp contrast unavailable: the ${feed.product} analysis, for ${date}, is later than the selected hour.`);
  const cells = contrastCells(feed.samples, feed.spacingDeg);
  if (!cells.length) return none(`no contrast above the error · ${date}`,
    `Nothing drawn: in the ${feed.product} analysis for ${date}, no cell's change across neighbouring cells exceeds their summed analysis error.`);
  const stamp = `analysis ${date} · ${age(now.getTime() - Date.parse(feed.analysedAt))} old`;
  const drawn: DrawnContrast = {key: `${feed.sourceId}|${feed.analysedAt}|${feed.fetchedAt}`, product: feed.product, analysedAt: feed.analysedAt, fetchedAt: feed.fetchedAt,
    nativeResolutionDeg: feed.nativeResolutionDeg, spacingDeg: feed.spacingDeg, credit: feed.credit, cells, judged: feed.samples.filter(s => s.gradientCPerKm !== null).length, stamp, limitMs: limit};
  return {drawn, note: stamp, reason: '', basis: contrastBasis(drawn, now, tz)};
}

export type ContrastFeature = {type: 'Feature'; properties: {f: number}; geometry: {type: 'Polygon'; coordinates: number[][][]}};
/** Each drawn cell as its own grid square, with its gradient in °F per nautical mile (`f`). */
export function contrastFeatures(d: Pick<DrawnContrast, 'cells' | 'spacingDeg'>): {type: 'FeatureCollection'; features: ContrastFeature[]} {
  const [dy, dx] = d.spacingDeg.map(s => s / 2) as [number, number];
  return {type: 'FeatureCollection', features: d.cells.map(c => ({type: 'Feature', properties: {f: Number(c.fPerNmi.toFixed(4))}, geometry: {type: 'Polygon',
    coordinates: [[[c.lon - dx, c.lat - dy], [c.lon + dx, c.lat - dy], [c.lon + dx, c.lat + dy], [c.lon - dx, c.lat + dy], [c.lon - dx, c.lat - dy]]]}}))};
}

/** The cells as one fill layer on the fixed scale, under the swell field and the protected areas (§ 9 order). */
export function contrastOverlay(p: Palette): Overlay {
  const [low, high] = CONTRAST_SCALE;
  return {
    sources: {[CONTRAST_SOURCE]: {type: 'geojson', data: {type: 'FeatureCollection', features: []}}},
    layers: [{id: CONTRAST_LAYER, type: 'fill', source: CONTRAST_SOURCE, paint: {
      'fill-color': ['interpolate', ['linear'], ['get', 'f'], low, p.contrast0, (low + high) / 2, p.contrast1, high, p.contrast2] as MapLibre.ExpressionSpecification,
      'fill-opacity': CONTRAST_OPACITY, 'fill-antialias': false}}],
  };
}

/** The mark card's reading in a drawn cell, or null outside every drawn cell. */
export function contrastMark(d: DrawnContrast, at: {lon: number; lat: number}, now: Date, tz: string): ChartMark | null {
  const [dy, dx] = d.spacingDeg.map(s => s / 2) as [number, number];
  const c = d.cells.find(c => Math.abs(at.lat - c.lat) <= dy && Math.abs(at.lon - c.lon) <= dx);
  if (!c) return null;
  return {
    id: `sst-contrast:${d.key}`, name: 'Temperature contrast', kind: `Daily analysis · ${dayText(d.analysedAt, tz)}`,
    reading: `${c.fPerNmi.toFixed(2)} °F per nautical mile (${c.cPerKm.toFixed(3)} °C per km)`,
    source: `${d.product} · ${d.stamp}`, basis: contrastBasis(d, now, tz),
  };
}

/** What the rail and legend show for Temp contrast. */
export const contrastState = signal<ContrastStatus>(OFF);

export interface ContrastOptions {
  engine: ReadonlySignal<Engine | null>;
  zone: () => string;
  /** The region's report context, or null until the region is known: only its region id is read. */
  place: () => CoastReportContext | null;
  palette?: () => Palette;
  now?: () => Date;
  fetchFn?: typeof fetch;
  page?: () => string;
}
/** The feed is read again after an hour, keeping the last result until the next arrives. */
const FEED_REFRESH_MS = HOUR;

export function createContrast(o: ContrastOptions): {reading(at: {lon: number; lat: number}): ChartMark | null; destroy(): void} {
  const {engine, zone, place, palette = () => readPalette(), now = () => new Date(), fetchFn = (...a) => fetch(...a), page = () => location.href} = o;
  const tick = signal(0);
  const on = computed(() => layers.value.includes(REGISTRY_ID));
  const feed = signal<{region: string; result: RegionalContrast | null} | null>(null);
  const status = computed(() => {
    void tick.value;
    const t = now(), p = place(), f = feed.value;
    return contrastStatus(on.value, p && f?.region === p.regionId ? f.result : null, terrainHour(hour.value, t, day.value, zone()), t, zone());
  });
  let feedRegion = '', feedAt = 0, feedAbort: AbortController | undefined;
  let drawnKey = '', drawnOn: Engine | null = null, timer: ReturnType<typeof setTimeout> | undefined;
  const withdraw = (): void => { if (chartMark.peek()?.id.startsWith('sst-contrast:')) chartMark.value = null; };

  const disposers = [
    // Read only while Temp contrast is on, again after an hour.
    effect(() => {
      void tick.value;
      const p = place(), id = p?.regionId ?? '', t = now().getTime();
      if (!on.value || !p || (id === feedRegion && t - feedAt < FEED_REFRESH_MS)) return;
      feedAbort?.abort();
      const abort = feedAbort = new AbortController();
      if (id !== feedRegion) feed.value = {region: id, result: null};
      feedRegion = id; feedAt = t;
      regionalContrast(id, {fetchFn, page: page(), now: new Date(t), signal: abort.signal})
        .then(result => { if (!abort.signal.aborted) feed.value = {region: id, result}; }, () => { /* aborted by a newer read */ });
    }),
    effect(() => {
      const s = status.value;
      contrastState.value = s;
      setRailNote(REGISTRY_ID, on.value ? s.note : '');
    }),
    // A new analysis redraws; none (off, stale, nothing supported) removes the cells at once.
    effect(() => {
      const e = engine.value, d = status.value.drawn, k = d?.key ?? '';
      if (!e || (k === drawnKey && e === drawnOn)) return;
      if (k !== drawnKey) withdraw();
      drawnKey = k; drawnOn = e;
      if (!d) { e.setOverlay(REGISTRY_ID, null); return; }
      e.setOverlay(REGISTRY_ID, contrastOverlay(palette()), [SWELL_LAYER, MPA_FILL]);
      e.setData(CONTRAST_SOURCE, contrastFeatures(d));
    }),
    // Re-judge at the age limit and at the next whole hour (the dock's default hour moves on).
    effect(() => {
      const d = status.value.drawn, t = now().getTime();
      clearTimeout(timer);
      if (!on.value) return;
      const limit = d ? Math.min(Date.parse(d.analysedAt), Date.parse(d.fetchedAt)) + d.limitMs : Infinity;
      timer = setTimeout(() => { tick.value++; }, Math.min(Math.max(1000, Math.min(limit, (Math.floor(t / HOUR) + 1) * HOUR) - t + 1000), 2 ** 31 - 1));
    }),
  ];
  return {
    reading(at) {
      const d = status.peek().drawn;
      return d && drawnKey === d.key && shownPresentation.peek() === 'chart' ? contrastMark(d, at, now(), zone()) : null;
    },
    destroy() {
      for (const dispose of disposers) dispose();
      clearTimeout(timer);
      feedAbort?.abort();
      withdraw();
      contrastState.value = OFF;
      setRailNote(REGISTRY_ID, '');
    },
  };
}

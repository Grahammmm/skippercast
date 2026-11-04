// Temp fronts (BF-sst-fronts): the offshore temperature edges the pipeline publishes (src/skippercast/pipeline/sst_fronts.py)
// beside the region's conditions feed as `sst-fronts.json`, drawn on the Chart as a line with its uncertainty band.
//
// - Product: an edge with the time it was observed, never a point or a hotspot. Each front carries its gradient strength and
//   a band: the position is uncertain by the analysis's own stated error divided by the strength, either side of the line.
//   The band is drawn as a width in metres (it scales with the zoom), the line on top of it. Beside Temp contrast (a grid-square
//   product, web/map/contrast.ts), never in place of it.
// - Gate: a front is drawn only while its observation is no older than the file's `max_age_hours` (catalog/feed-health.json) and never
//   past 72 hours, and not more than 5 minutes ahead of the clock. Past that nothing draws and the rail says "no current front data".
//   A file that is absent, unreadable or malformed reads the same: the rest of the map is unaffected.
// - The age is given in words ("observed 6 hours ago"), never as a bare timestamp.
//
// Erasable syntax only: tests/test_sst_fronts_layer.mjs imports it by type stripping.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import type {CoastReportContext} from '../../packages/coast/src/state/report-binding.ts';
import {layers} from '../state.ts';
import {chartMark} from './chart.ts';
import type {ChartMark} from './coastline.ts';
import {DEPTH_BOTTOM} from './depth-contours.ts';
import type {Engine, Overlay} from './engine.ts';
import {FRONTS_SOURCE, layerEntry, setRailNote} from './layers.ts';
import {MPA_FILL} from './mpa.ts';
import {readPalette, type Palette} from './palette.ts';
import {shownPresentation} from './stage.ts';
import {SWELL_LAYER} from './swell.ts';

const REGISTRY_ID = 'sst-fronts' as const;
export const FRONTS_LAYER = 'sst-fronts';
export const FRONTS_BAND_LAYER = 'sst-fronts-band';
const HOUR = 3_600_000;
export const MAX_AGE_MS = 72 * HOUR;
const AHEAD_MS = 5 * 60_000;
const REFRESH_MS = HOUR;
const METRES_PER_PIXEL_Z0 = 78271.517;
export const NONE = 'no current front data';
export const FRONTS_BASIS = layerEntry(REGISTRY_ID).basis;

export interface Front {readonly id: string; readonly observedAt: string; readonly strengthCPerKm: number; readonly uncertaintyC: number; readonly bandHalfWidthKm: number; readonly lines: readonly (readonly (readonly [number, number])[])[]}
export interface FrontsDoc {readonly product: string; readonly credit: string; readonly maxAgeMs: number; readonly observedAt: string | null; readonly fronts: readonly Front[]}
export type FrontsFeed = {readonly state: 'none'} | {readonly state: 'error'} | {readonly state: 'ready'; readonly doc: FrontsDoc};
export interface DrawnFronts {readonly key: string; readonly product: string; readonly credit: string; readonly observedAt: string; readonly limitMs: number; readonly fronts: readonly Front[]}
export interface FrontsStatus {readonly drawn: DrawnFronts | null; readonly note: string; readonly reason: string; readonly basis: string}

const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const text = (v: unknown): v is string => typeof v === 'string' && v.trim() !== '';
const record = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const line = (v: unknown): [number, number][] | null => {
  if (!Array.isArray(v) || v.length < 2) return null;
  const out: [number, number][] = [];
  for (const p of v) { if (!Array.isArray(p) || !num(p[0]) || !num(p[1]) || Math.abs(p[0]) > 180 || Math.abs(p[1]) > 90) return null; out.push([p[0], p[1]]); }
  return out;
};
function front(v: unknown): Front | null {
  if (!record(v) || !text(v.id) || !text(v.observed_at) || !num(v.strength_c_per_km) || v.strength_c_per_km <= 0 || !num(v.uncertainty_c) || v.uncertainty_c < 0
    || !num(v.band_half_width_km) || v.band_half_width_km < 0 || !record(v.geometry)) return null;
  const g = v.geometry, raw = g.type === 'LineString' ? [g.coordinates] : g.type === 'MultiLineString' && Array.isArray(g.coordinates) ? g.coordinates : null;
  const lines = raw?.map(line) ?? [];
  if (!raw || !lines.length || lines.some(l => l === null)) return null;
  return {id: v.id, observedAt: v.observed_at, strengthCPerKm: v.strength_c_per_km, uncertaintyC: v.uncertainty_c, bandHalfWidthKm: v.band_half_width_km, lines: lines.flatMap(l => l ? [l] : [])};
}
/** The published document, or null when it is not this region's fronts file in the pipeline's shape. */
export function readFronts(data: unknown, regionId: string): FrontsDoc | null {
  if (!record(data) || data.schema_version !== 1 || data.region_id !== regionId || data.layer_id !== REGISTRY_ID || !text(data.product) || !num(data.max_age_hours) || data.max_age_hours <= 0
    || !Array.isArray(data.fronts) || !(data.observed_at === null || text(data.observed_at))) return null;
  const fronts = data.fronts.map(front);
  if (fronts.some(f => f === null)) return null;
  return {product: data.product, credit: typeof data.credit === 'string' ? data.credit.trim() : '', maxAgeMs: data.max_age_hours * HOUR, observedAt: data.observed_at,
    fronts: fronts.flatMap(f => f ? [f] : [])};
}
/** The region's fronts file beside its conditions feed: 404 is `none`; a failed read or a malformed file is `error`. */
export async function regionalFronts(regionId: string, o: {fetchFn: typeof fetch; page: string; signal?: AbortSignal}): Promise<FrontsFeed> {
  try {
    if (!/^[a-z0-9-]+$/.test(regionId)) return {state: 'error'};
    const r = await o.fetchFn(new URL(`/feeds/conditions/regions/${regionId}/sst-fronts.json`, o.page).href, o.signal ? {signal: o.signal} : {});
    if (r.status === 404) return {state: 'none'};
    const doc = r.ok ? readFronts(await r.json(), regionId) : null;
    return doc ? {state: 'ready', doc} : {state: 'error'};
  } catch (error) {
    if (o.signal?.aborted) throw error;
    return {state: 'error'};
  }
}

const plural = (n: number, unit: string): string => `${n} ${unit}${n === 1 ? '' : 's'}`;
/** "6 hours ago": the age in words, never a bare timestamp. */
export function ageWords(ms: number): string {
  const minutes = Math.floor(Math.max(0, ms) / 60_000), hours = Math.floor(minutes / 60);
  return minutes < 1 ? 'less than a minute ago' : minutes < 60 ? `${plural(minutes, 'minute')} ago` : hours < 48 ? `${plural(hours, 'hour')} ago` : `${plural(Math.floor(hours / 24), 'day')} ago`;
}
const ageOf = (iso: string, now: Date): number => now.getTime() - Date.parse(iso);
const fresh = (iso: string, now: Date, limit: number): boolean => { const d = ageOf(iso, now); return Number.isFinite(d) && d >= -AHEAD_MS && d <= limit; };
export const ageLimit = (fileMs: number): number => Math.min(fileMs, MAX_AGE_MS);

export function frontsBasis(d: DrawnFronts, now: Date): string {
  return `Offshore temperature fronts found in the ${d.product} daily analysis, observed ${ageWords(ageOf(d.observedAt, now))}, drawn as an edge with a band: the position is uncertain by the analysis's own stated error divided by the front's strength, either side of the line. `
    + `Withheld past its ${Math.round(d.limitMs / HOUR)}-hour age limit. Surface water only; a front is an edge to search along, not a fish or catch location.${d.credit ? ` Credit: ${d.credit}.` : ''}`;
}
const none = (reason: string, note = NONE): FrontsStatus => ({drawn: null, note, reason, basis: FRONTS_BASIS});
const OFF: FrontsStatus = {drawn: null, note: '', reason: '', basis: FRONTS_BASIS};

/** What Temp fronts shows from the region's file (`null` while it loads). Each front is judged by its own observation time. */
export function frontsStatus(on: boolean, feed: FrontsFeed | null, now: Date): FrontsStatus {
  if (!on) return OFF;
  if (!feed) return none('Loading the region\'s offshore temperature fronts.', 'loading');
  if (feed.state === 'none') return none('No current front data: no offshore temperature fronts are published for this region yet.');
  if (feed.state === 'error') return none('No current front data: the region\'s fronts file could not be read or failed its checks.');
  const {doc} = feed, limit = ageLimit(doc.maxAgeMs), current = doc.fronts.filter(f => fresh(f.observedAt, now, limit));
  const limitText = `${Math.round(limit / HOUR)}-hour`;
  if (doc.fronts.length > current.length || (!doc.fronts.length && (!doc.observedAt || !fresh(doc.observedAt, now, limit))))
    return none(`No current front data: the latest fronts are past their ${limitText} age limit or carry no usable observation time.`);
  if (!current.length) return none(`No front found in the analysis observed ${ageWords(ageOf(doc.observedAt ?? '', now))}.`, `no front · observed ${ageWords(ageOf(doc.observedAt ?? '', now))}`);
  const observedAt = current.map(f => f.observedAt).sort().at(-1) ?? '';
  const drawn: DrawnFronts = {key: `${doc.product}|${observedAt}|${current.map(f => f.id).join(',')}`, product: doc.product, credit: doc.credit, observedAt, limitMs: limit, fronts: current};
  return {drawn, note: `${plural(current.length, 'front')} · observed ${ageWords(ageOf(observedAt, now))}`, reason: '', basis: frontsBasis(drawn, now)};
}

export type FrontFeature = {type: 'Feature'; properties: {id: string; px0: number}; geometry: {type: 'MultiLineString'; coordinates: number[][][]}};
/** Each front as one line; `px0` is the band's full width in pixels at zoom 0 (doubling with each zoom), so the band keeps its width in metres. */
export function frontFeatures(d: Pick<DrawnFronts, 'fronts'>): {type: 'FeatureCollection'; features: FrontFeature[]} {
  return {type: 'FeatureCollection', features: d.fronts.map(f => {
    const points = f.lines.flat(), lat = points.reduce((s, p) => s + p[1], 0) / points.length;
    // Ground metres per pixel shrink by cos(latitude) in Web Mercator.
    const metresPerPixel = METRES_PER_PIXEL_Z0 * Math.max(Math.cos(lat * Math.PI / 180), 1e-6);
    return {type: 'Feature', properties: {id: f.id, px0: Number((2 * f.bandHalfWidthKm * 1000 / metresPerPixel).toFixed(8))}, geometry: {type: 'MultiLineString', coordinates: f.lines.map(l => l.map(p => [p[0], p[1]]))}};
  })};
}
/** The band under the line, both lines only: no fill, no point. */
export function frontsOverlay(p: Palette): Overlay {
  const band: MapLibre.ExpressionSpecification = ['interpolate', ['exponential', 2], ['zoom'], 0, ['get', 'px0'], 24, ['*', ['get', 'px0'], 2 ** 24]];
  return {
    sources: {[FRONTS_SOURCE]: {type: 'geojson', data: {type: 'FeatureCollection', features: []}}},
    layers: [
      {id: FRONTS_BAND_LAYER, type: 'line', source: FRONTS_SOURCE, layout: {'line-cap': 'round', 'line-join': 'round'}, paint: {'line-color': p.contrast1, 'line-opacity': 0.35, 'line-width': band}},
      {id: FRONTS_LAYER, type: 'line', source: FRONTS_SOURCE, layout: {'line-cap': 'round', 'line-join': 'round'}, paint: {'line-color': p.contrast2, 'line-opacity': 0.9, 'line-width': 1.5}},
    ],
  };
}

/** The mark card's reading on a drawn front: the nearest line within its band (at least 1 km), else null. */
export function frontsMark(d: DrawnFronts, at: {lon: number; lat: number}, now: Date): ChartMark | null {
  const kx = 111.195 * Math.cos(at.lat * Math.PI / 180), ky = 111.195;
  const km = (p: readonly [number, number]): [number, number] => [(p[0] - at.lon) * kx, (p[1] - at.lat) * ky];
  const near = (f: Front): number => Math.min(...f.lines.flatMap(l => l.slice(1).map((b, i) => {
    const [ax, ay] = km(l[i]!), [bx, by] = km(b), dx = bx - ax, dy = by - ay, t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) || 1)));
    return Math.hypot(ax + t * dx, ay + t * dy);
  })));
  const hit = d.fronts.map(f => ({f, d: near(f)})).filter(h => h.d <= Math.max(1, h.f.bandHalfWidthKm)).sort((a, b) => a.d - b.d)[0]?.f;
  if (!hit) return null;
  const age = ageWords(ageOf(hit.observedAt, now));
  return {id: `sst-fronts:${d.key}:${hit.id}`, name: 'Temperature front', kind: `Observed ${age}`,
    reading: `${hit.strengthCPerKm.toFixed(2)} °C per km, position uncertain by about ±${hit.bandHalfWidthKm.toFixed(1)} km (analysis error ${hit.uncertaintyC.toFixed(2)} °C)`,
    source: `${d.product} · observed ${age}`, basis: frontsBasis(d, now)};
}

/** What the rail and legend show for Temp fronts. */
export const frontsState = signal<FrontsStatus>(OFF);

export interface FrontsOptions {
  engine: ReadonlySignal<Engine | null>;
  place: () => CoastReportContext | null;
  palette?: () => Palette;
  now?: () => Date;
  fetchFn?: typeof fetch;
  page?: () => string;
}

export function createFronts(o: FrontsOptions): {reading(at: {lon: number; lat: number}): ChartMark | null; destroy(): void} {
  const {engine, place, palette = () => readPalette(), now = () => new Date(), fetchFn = (...a) => fetch(...a), page = () => location.href} = o;
  const tick = signal(0), on = computed(() => layers.value.includes(REGISTRY_ID));
  const feed = signal<{region: string; result: FrontsFeed | null} | null>(null);
  const status = computed(() => { void tick.value; const p = place(), f = feed.value; return frontsStatus(on.value, p && f?.region === p.regionId ? f.result : null, now()); });
  let feedRegion = '', feedAt = 0, feedAbort: AbortController | undefined, drawnKey = '', drawnOn: Engine | null = null, timer: ReturnType<typeof setTimeout> | undefined;
  const withdraw = (): void => { if (chartMark.peek()?.id.startsWith('sst-fronts:')) chartMark.value = null; };
  const disposers = [
    // Read only while Temp fronts is on, again after an hour; a failed read keeps the map working and says so.
    effect(() => {
      void tick.value;
      const p = place(), id = p?.regionId ?? '', t = now().getTime();
      if (!on.value || !p || (id === feedRegion && t - feedAt < REFRESH_MS)) return;
      feedAbort?.abort();
      const abort = feedAbort = new AbortController();
      if (id !== feedRegion) feed.value = {region: id, result: null};
      feedRegion = id; feedAt = t;
      regionalFronts(id, {fetchFn, page: page(), signal: abort.signal}).then(result => { if (!abort.signal.aborted) feed.value = {region: id, result}; }, () => { /* aborted by a newer read */ });
    }),
    effect(() => { const s = status.value; frontsState.value = s; setRailNote(REGISTRY_ID, on.value ? s.note : ''); }),
    // New fronts redraw; none (off, stale, nothing found) removes the lines at once.
    effect(() => {
      const e = engine.value, d = status.value.drawn, k = d?.key ?? '';
      if (!e || (k === drawnKey && e === drawnOn)) return;
      if (k !== drawnKey) withdraw();
      drawnKey = k; drawnOn = e;
      if (!d) { e.setOverlay(REGISTRY_ID, null); return; }
      e.setOverlay(REGISTRY_ID, frontsOverlay(palette()), [SWELL_LAYER, 'wind-casing', DEPTH_BOTTOM, MPA_FILL]);
      e.setData(FRONTS_SOURCE, frontFeatures(d));
    }),
    // Re-judge at the age limit of the oldest drawn front and at the next hour.
    effect(() => {
      const d = status.value.drawn, t = now().getTime();
      clearTimeout(timer);
      if (!on.value) return;
      const limit = d ? Math.min(...d.fronts.map(f => Date.parse(f.observedAt))) + d.limitMs : Infinity;
      timer = setTimeout(() => { tick.value++; }, Math.min(Math.max(1000, Math.min(limit, (Math.floor(t / HOUR) + 1) * HOUR) - t + 1000), 2 ** 31 - 1));
    }),
  ];
  return {
    reading(at) { const d = status.peek().drawn; return d && drawnKey === d.key && shownPresentation.peek() === 'chart' ? frontsMark(d, at, now()) : null; },
    destroy() { for (const dispose of disposers) dispose(); clearTimeout(timer); feedAbort?.abort(); withdraw(); frontsState.value = OFF; setRailNote(REGISTRY_ID, ''); },
  };
}

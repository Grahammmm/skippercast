// CI6-10: GFS tile-derived regional samples, sharing the Swell rail, not its
// run gate. Sparse arrows at actual samples: no inferred coastal detail.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import {day, hour, layers, region} from '../state.ts';
import type {Engine, Overlay} from './engine.ts';
import {loadForecast, sample, type WaveForecast} from './forecast-grid.ts';
import {forecastTime} from './frames.ts';
import {layerEntry} from './layers.ts';
import {MPA_FILL} from './mpa.ts';
import {DEPTH_BOTTOM} from './depth-contours.ts';
import {readPalette, type Palette} from './palette.ts';
import {terrainHour} from './stage.ts';
import {LABEL_FONT} from './style.ts';
import {runText, validText} from './swell.ts';

export const WIND_MODEL = 'gfs_global';
export const WIND_ARROWS = 'wind-arrows', WIND_LABELS = 'wind-labels';
const HOUR = 3_600_000, REFRESH = HOUR / 2;
export interface WindSample {readonly lon: number; readonly lat: number; readonly knots: number; readonly from: number}
export interface WindFrame {
  readonly key: string;
  readonly validAt: number;
  readonly points: readonly WindSample[];
  readonly step: readonly [number, number];
  readonly stamp: string;
}
export interface WindStatus {readonly drawn: WindFrame | null; readonly reason: string; readonly basis: string}
const OFF: WindStatus = {drawn: null, reason: '', basis: layerEntry('wind').basis};
export const windState = signal<WindStatus>(OFF);

/** Values are already knots in the tile-derived feed; never silently reinterpret m/s. */
export function windPoints(f: WaveForecast, epoch: number): WindSample[] {
  if (!f.model) return [];
  return f.lattice.flatMap(p => {
    const d = f.model!.data[p.index], meta = {data_end_time: f.model!.end};
    const knots = sample(d, 'wind_speed_10m', epoch, 'kn', meta), from = sample(d, 'wind_direction_10m', epoch, '°', meta);
    // sample's generic direction check applies to names ending in direction,
    // so the 10 m variable must additionally check its upper bound here.
    return knots === null || from === null || from > 360 ? [] : [{lon: p.lon, lat: p.lat, knots, from}];
  });
}

export function windStatus(on: boolean, f: WaveForecast | null, at: Date, now: Date, tz: string, failed = false): WindStatus {
  if (!on) return OFF;
  const none = (reason: string): WindStatus => ({...OFF, reason});
  if (!f) return none(failed ? 'Wind unavailable: the regional forecast failed to load.' : 'Loading the regional wind forecast.');
  if (!f.step) return none('Wind unavailable: this region has no forecast grid.');
  if (!f.model) return none('Wind unavailable: the regional forecast carries no NOAA GFS run.');
  const issued = f.model.issued * 1000, run = runText(issued, tz);
  const validAt = forecastTime(f.model.times.map(t => t * 1000), issued, f.retrieved, at, now);
  if (validAt === null) {
    const age = now.getTime() - issued, retrievalAge = now.getTime() - f.retrieved;
    const why = age < -300_000 || retrievalAge < -300_000 ? 'a timestamp is ahead of the device clock'
      : age > 36 * HOUR ? 'the run is past its 36-hour age limit'
      : retrievalAge > 6 * HOUR ? 'retrieval is past its 6-hour age limit'
      : 'no listed forecast hour is available within 90 minutes inside the run';
    return none(`Wind unavailable: NOAA GFS run ${run}; ${why}.`);
  }
  const points = windPoints(f, validAt / 1000);
  if (!points.length) return none('Wind unavailable: no unit-checked wind samples at this forecast hour.');
  const stamp = `run ${run} · ${Math.floor(Math.max(0, now.getTime() - issued) / HOUR)} h old · valid ${validText(validAt, tz, true)}`;
  const grid = f.step.map(v => `${Number(v.toFixed(3))}°`).join(' × ');
  return {drawn: {key: `${f.region}|${issued}|${f.retrieved}|${validAt}`, validAt, points, step: f.step, stamp}, reason: '',
    basis: `${OFF.basis} Regional sampling grid ${grid}; ${stamp}. Fixed-length arrows show direction, not speed; labels give speed. Calm samples have a 0 kt label and no arrow. Missing samples stay blank; headlands and harbors are not resolved.`};
}

/** Arrow shafts and two head strokes in geographic coordinates; from -> toward. */
export function windGeometry(f: WindFrame) {
  const arrows: {type: 'Feature'; properties: Record<string, never>; geometry: {type: 'MultiLineString'; coordinates: number[][][]}}[] = [];
  const labels: {type: 'Feature'; properties: {label: string}; geometry: {type: 'Point'; coordinates: number[]}}[] = [];
  for (const p of f.points) {
    labels.push({type: 'Feature', properties: {label: `${Number(p.knots.toFixed(1))} kt`}, geometry: {type: 'Point', coordinates: [p.lon, p.lat]}});
    if (p.knots === 0) continue;
    const angle = (p.from + 180) * Math.PI / 180, sin = Math.sin(angle), cos = Math.cos(angle);
    const kx = 111.32 * Math.cos(p.lat * Math.PI / 180), ky = 110.57;
    const length = 0.35 * Math.min(f.step[0] * kx, f.step[1] * ky);
    const at = (along: number, across = 0) => [p.lon + (along * sin + across * cos) * length / kx, p.lat + (along * cos - across * sin) * length / ky];
    arrows.push({type: 'Feature', properties: {}, geometry: {type: 'MultiLineString', coordinates: [[at(-0.5), at(0.5)], [at(0.2, -0.18), at(0.5), at(0.2, 0.18)]]}});
  }
  return {arrows: {type: 'FeatureCollection' as const, features: arrows}, labels: {type: 'FeatureCollection' as const, features: labels}};
}

export function windOverlay(p: Palette): Overlay {
  const empty = {type: 'geojson' as const, attribution: layerEntry('wind').attribution, data: {type: 'FeatureCollection' as const, features: []}};
  return {sources: {[WIND_ARROWS]: empty, [WIND_LABELS]: empty}, layers: [
    {id: 'wind-casing', type: 'line', source: WIND_ARROWS, paint: {'line-color': p.bg, 'line-width': 4}},
    {id: WIND_ARROWS, type: 'line', source: WIND_ARROWS, paint: {'line-color': p.text, 'line-width': 2}},
    {id: WIND_LABELS, type: 'symbol', source: WIND_LABELS, layout: {'text-field': ['get', 'label'], 'text-font': [LABEL_FONT], 'text-size': 11, 'text-offset': [0, 1.6]},
      paint: {'text-color': p.text, 'text-halo-color': p.bg, 'text-halo-width': 1.5}},
  ]};
}

export function createWind(o: {engine: ReadonlySignal<Engine | null>; zone: () => string; fetchFn?: typeof fetch; page?: () => string; palette?: () => Palette; now?: () => Date}) {
  const {engine, zone, fetchFn = (...a) => fetch(...a), page = () => location.href, palette = () => readPalette(), now = () => new Date()} = o;
  const tick = signal(0), load = signal<{region: string | null; forecast: WaveForecast | null; at: number; loading: boolean; failed: boolean}>({region: null, forecast: null, at: 0, loading: false, failed: false});
  const on = computed(() => layers.value.includes('swell'));
  const status = computed(() => {
    void tick.value;
    const l = load.value, clock = now();
    return windStatus(on.value, l.region === region.value ? l.forecast : null, terrainHour(hour.value, clock, day.value, zone()), clock, zone(), l.region === region.value && l.failed);
  });
  let alive = true, generation = 0, timer: ReturnType<typeof setTimeout> | undefined, drawnOn: Engine | null = null, drawnKey = '';
  async function read(id: string) {
    const seq = ++generation, previous = load.peek(), kept = previous.region === id ? previous.forecast : null, at = now().getTime();
    load.value = {region: id, forecast: kept, at, loading: true, failed: false};
    const forecast = await loadForecast(id, fetchFn, page(), WIND_MODEL);
    if (!alive || seq !== generation || region.peek() !== id) return;
    load.value = {region: id, forecast: forecast ?? kept, at, loading: false, failed: !forecast && !kept};
  }
  const disposers = [
    effect(() => {
      void tick.value;
      const id = region.value, l = load.peek();
      if (on.value && id && (l.region !== id || (!l.loading && now().getTime() - l.at >= REFRESH))) void read(id);
    }),
    effect(() => { windState.value = status.value; }),
    effect(() => {
      const e = engine.value, f = status.value.drawn, key = f?.key ?? '';
      if (drawnOn && drawnOn !== e) drawnOn.setOverlay('wind', null);
      if (!e) { drawnOn = null; drawnKey = ''; return; }
      if (drawnOn === e && drawnKey === key) return;
      drawnOn = e; drawnKey = key;
      if (!f) { e.setOverlay('wind', null); return; }
      e.setOverlay('wind', windOverlay(palette()), [DEPTH_BOTTOM, MPA_FILL]);
      const data = windGeometry(f);
      e.setData(WIND_ARROWS, data.arrows); e.setData(WIND_LABELS, data.labels);
    }),
    effect(() => {
      void tick.value;
      clearTimeout(timer);
      const l = load.value, t = now().getTime(), f = l.forecast;
      if (!on.value) return;
      const limits = [(Math.floor(t / HOUR) + 1) * HOUR, l.at + REFRESH,
        ...(f?.model ? [f.model.issued * 1000 + 36 * HOUR, f.retrieved + 6 * HOUR] : [])].filter(n => n > t);
      timer = setTimeout(() => { tick.value++; }, Math.max(1000, Math.min(...limits) - t + 1000));
    }),
  ];
  return {destroy() {
    alive = false; generation++;
    disposers.forEach(dispose => dispose()); clearTimeout(timer);
    drawnOn?.setOverlay('wind', null); windState.value = OFF;
  }};
}

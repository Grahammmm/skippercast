// CI6-08: native observed cell footprints, never a smoothed or gap-filled field.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import {layers, region} from '../state.ts';
import type {Engine, Overlay} from './engine.ts';
import {chlorophyllFresh, regionalChlorophyll, type ChlorophyllObservation, type RegionalChlorophyll} from './habitat-feed.ts';
import {layerEntry, setRailNote} from './layers.ts';
import {MPA_FILL} from './mpa.ts';
import {SWELL_LAYER} from './swell.ts';
import {readPalette, type Palette} from './palette.ts';

const ID = 'chlorophyll', HOUR = 3_600_000;
export const CHLOROPHYLL_SCALE = [0.01, 0.1, 1, 10, 100] as const;
const BASIS = layerEntry(ID).basis;
export interface ChlorophyllStatus {readonly drawn: ChlorophyllObservation | null; readonly basis: string; readonly note: string}
const OFF: ChlorophyllStatus = {drawn: null, basis: BASIS, note: ''};
export const chlorophyllState = signal<ChlorophyllStatus>(OFF);

export function chlorophyllStatus(on: boolean, feed: RegionalChlorophyll | null, now: Date): ChlorophyllStatus {
  if (!on) return OFF;
  if (feed?.state !== 'ready') return {...OFF, note: !feed ? 'loading' : feed.state === 'error' ? 'unavailable: feed checks failed' : 'no fresh populated observation'};
  const o = feed.observation;
  if (!chlorophyllFresh(o, now)) return {...OFF, note: `withheld · last sample ${o.sampleAt}`};
  const age = Math.max(0, (now.getTime() - Date.parse(o.sampleAt)) / HOUR);
  return {drawn: o, note: `sample ${o.sampleAt} · ${age.toFixed(1)} h old`,
    basis: `${o.product}, native ${o.resolution[0]}° × ${o.resolution[1]}° grid; sample ${o.sampleAt} (${age.toFixed(1)} h old). Withheld at ${o.maxAgeMs / HOUR} h. Surface chlorophyll proxy, not bait or fish. Cloud gaps stay empty; no interpolation.`};
}

/** Each value covers only its original pixel. Missing cells produce no geometry. */
export function chlorophyllCells(o: ChlorophyllObservation) {
  const [dy, dx] = o.resolution;
  return {type: 'FeatureCollection' as const, features: o.cells.map(({lat, lon, value}) => ({type: 'Feature' as const, properties: {value},
    geometry: {type: 'Polygon' as const, coordinates: [[[lon - dx / 2, lat - dy / 2], [lon + dx / 2, lat - dy / 2],
      [lon + dx / 2, lat + dy / 2], [lon - dx / 2, lat + dy / 2], [lon - dx / 2, lat - dy / 2]]]}}))};
}

export function chlorophyllOverlay(o: ChlorophyllObservation, p: Palette): Overlay {
  return {sources: {[ID]: {type: 'geojson', data: chlorophyllCells(o), attribution: layerEntry(ID).attribution}},
    layers: [{id: ID, type: 'fill', source: ID, paint: {'fill-antialias': false, 'fill-opacity': 0.75,
      'fill-color': ['interpolate', ['linear'], ['log10', ['get', 'value']], -2, p.depth0, -1, p.blue, 0, p.mint, 1, p.amber, 2, p.coral]}}]};
}

export function createChlorophyll(o: {engine: ReadonlySignal<Engine | null>; fetchFn?: typeof fetch; page?: () => string; now?: () => Date; palette?: () => Palette}) {
  const {fetchFn = (...args) => fetch(...args), page = () => location.href, now = () => new Date(), palette = readPalette} = o;
  const on = computed(() => layers.value.includes(ID)), tick = signal(0);
  const feed = signal<{region: string; value: RegionalChlorophyll} | null>(null);
  let abort: AbortController | undefined, requested = '', requestedAt = -Infinity;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const status = computed(() => { void tick.value; return chlorophyllStatus(on.value, feed.value?.region === region.value ? feed.value.value : null, now()); });
  const disposers = [
    effect(() => {
      void tick.value;
      const id = region.value, t = now().getTime();
      if (!on.value || !id) { abort?.abort(); requested = ''; return; }
      if (requested === id && t - requestedAt < HOUR) return;
      abort?.abort();
      const controller = abort = new AbortController();
      requested = id; requestedAt = t;
      regionalChlorophyll(id, {fetchFn, page: page(), now: new Date(t), signal: controller.signal})
        .then(value => { if (!controller.signal.aborted) feed.value = {region: id, value}; }, () => {});
    }),
    effect(() => {
      const s = status.value, e = o.engine.value;
      chlorophyllState.value = s;
      setRailNote(ID, s.note);
      if (e) {
        e.setOverlay(ID, s.drawn ? chlorophyllOverlay(s.drawn, palette()) : null, [SWELL_LAYER, MPA_FILL]);
        if (s.drawn) e.setData(ID, chlorophyllCells(s.drawn));
      }
    }),
    effect(() => {
      clearTimeout(timer);
      if (!on.value) return;
      const s = status.value, t = now().getTime();
      const expiry = s.drawn ? Date.parse(s.drawn.sampleAt) + s.drawn.maxAgeMs : Infinity;
      timer = setTimeout(() => { tick.value++; }, Math.max(1, Math.min(HOUR, expiry - t)));
    }),
  ];
  return {reading: () => null, destroy() {
    disposers.forEach(dispose => dispose()); abort?.abort(); clearTimeout(timer);
    o.engine.peek()?.setOverlay(ID, null); chlorophyllState.value = OFF; setRailNote(ID, '');
  }};
}

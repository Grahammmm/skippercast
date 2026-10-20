// Stations owns only physical station dots. Swell's shared nearshore renderer
// owns MOP rings for either control, so enabling both never duplicates targets.
import {computed, effect, signal, type ReadonlySignal} from '@preact/signals';
import locations from '../../catalog/station-locations.json' with {type: 'json'};
import {counties} from '../../packages/coast/src/counties.ts';
import {coastData} from '../coast-data.ts';
import type {RegionalDailyFeed} from '../brief/types.ts';
import {sharedFetch} from '../shared-fetch.ts';
import {area, day, hour, layers, region} from '../state.ts';
import {chartMark} from './chart.ts';
import {COASTLINE_GLOW} from './coastline.ts';
import type {Engine, Overlay} from './engine.ts';
import {layerEntry, setRailNote} from './layers.ts';
import {readPalette, type Palette} from './palette.ts';
import {terrainHour} from './stage.ts';
import {stationGeoJSON, stationPins, type StationPin, type StationRegion} from './station-model.ts';

export const STATION_SOURCE = 'stations', STATION_DOTS = 'station-dots', STATION_HIT = 'station-hit';
export const stationState = signal<{pins: readonly StationPin[]; note: string}>({pins: [], note: ''});
export function stationOverlay(p: Palette): Overlay {
  return {sources: {[STATION_SOURCE]: {type: 'geojson', data: {type: 'FeatureCollection', features: []}, attribution: layerEntry('stations').attribution}}, layers: [
    {id: STATION_HIT, type: 'circle', source: STATION_SOURCE, paint: {'circle-radius': 22, 'circle-color': p.blue, 'circle-opacity': 0}},
    {id: STATION_DOTS, type: 'circle', source: STATION_SOURCE, paint: {'circle-radius': 6, 'circle-stroke-width': 2, 'circle-stroke-color': p.bg,
      'circle-color': ['case', ['get', 'stale'], p.muted, ['==', ['get', 'kind'], 'coops'], p.mint, p.blue]}},
  ]};
}
export function createStations(o: {engine: ReadonlySignal<Engine | null>; feed: () => RegionalDailyFeed | null; zone: () => string;
  fetchFn?: typeof fetch; palette?: () => Palette; now?: () => Date}) {
  const {fetchFn = sharedFetch, palette = readPalette, now = () => new Date()} = o;
  const config = signal<StationRegion | null>(null), error = signal(false), tick = signal(0);
  const on = computed(() => layers.value.includes('stations'));
  let generation = 0, alive = true;
  const pins = computed(() => {
    void tick.value;
    const r = config.value;
    if (!on.value || r?.id !== region.value) return [];
    const report = coastData.coastBinding.value ? coastData.coastReport.value?.data ?? null : null;
    const county = report ? counties[report.countyId] ?? null : null;
    const t = now();
    return stationPins({region: r, context: area.value, catalog: locations, feed: o.feed(), report, county, now: t, at: terrainHour(hour.value, t, day.value, o.zone())});
  });
  const disposers = [
    effect(() => {
      const id = region.value, enabled = on.value, token = ++generation;
      if (!enabled || !id) return;
      if (config.peek()?.id === id) return;
      config.value = null; error.value = false;
      void (async () => {
        try {
          const response = await fetchFn(`regions/${encodeURIComponent(id)}/region.json`, {signal: AbortSignal.timeout(10_000)});
          const data = response.ok ? await response.json() as StationRegion : null;
          if (!alive || token !== generation) return;
          if (!data || data.id !== id || !data.stations) {error.value = true; return;}
          config.value = data;
        } catch { if (alive && token === generation) error.value = true; }
      })();
    }),
    effect(() => {
      const all = pins.value, enabled = on.value, e = o.engine.value;
      const missing = all.filter(p => !p.location).map(p => `${p.mark.name}: location unavailable`);
      const note = !enabled ? '' : !all.length ? error.value ? 'Station configuration unavailable' : 'Loading station configuration'
        : `${all.filter(p => p.location).length} station locations · latest readings with individual times${missing.length ? `; ${missing.join('; ')}` : ''}`;
      stationState.value = {pins: all, note}; setRailNote('stations', note);
      if (e) {
        e.setOverlay('stations', enabled && all.length ? stationOverlay(palette()) : null, COASTLINE_GLOW);
        if (enabled && all.length) e.setData(STATION_SOURCE, stationGeoJSON(all));
      }
      const selected = chartMark.peek();
      if (selected?.id.startsWith('station:')) chartMark.value = all.find(p => p.mark.id === selected.id)?.mark ?? null;
    }),
  ];
  // Rejudge stale clocks while visible, without adding provider measurement calls.
  const timer = setInterval(() => { if (on.peek()) tick.value++; }, 60_000);
  return {pick: {layers: [STATION_DOTS, STATION_HIT], mark: (_layer: string, properties: Record<string, unknown> | null) => pins.peek().find(p => p.key === properties?.id)?.mark ?? null},
    destroy() {alive = false; generation++; clearInterval(timer); disposers.forEach(d => d()); o.engine.peek()?.setOverlay('stations', null);
      if (chartMark.peek()?.id.startsWith('station:')) chartMark.value = null;
      stationState.value = {pins: [], note: ''}; setRailNote('stations', '');}};
}

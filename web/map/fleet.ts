// Charter fleet activity on the Chart (FE-24, docs/plans/front-end/design.md § 9;
// docs/plans/charter-fleet/design.md § 14): the admin part of the Charter fleet
// rail entry. A port of dist/fleet-activity.js's drawing to MapLibre; v1's module
// stays as it is and its access check, queries, paging, sizes and status line are
// imported from it (on first use, so a visitor's bundle never carries it).
//
// Admin gated exactly as v1: only while the entry is on, v1's `fleetAccess` asks
// /api/session first and, for an admin, the map API's filters probe, which is a 404
// whenever FLEET_ENABLED or FLEET_MAP_ENABLED is off (server/fleet/map.ts), so the
// client never decides access. Without access the entry offers no activity options.
// With it, three options under the entry (off by default, as v1's toggles) draw
// heat cells (opacity ∝ dwell), trip tracks (by segment kind, gaps and NOAA
// planning-only rows dashed) and activity events (radius ∝ √dwell, drift filled,
// troll ringed), all in the --fleet (--amber) family, for the map's bounds with
// no filters: the filter form moves to the Fleet view in FE-53. Every card says
// the activity is inferred from movement.
//
// Erasable syntax only: tests/test_fleet_layers_v2.mjs imports it by type stripping.
import {computed, effect, signal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {layers, region} from '../state.ts';
import {ACTIVITY_LAYERS, fleetBefore, type Collection, type FleetLayerOptions} from './charter-grounds.ts';
import type {ChartMark} from './coastline.ts';
import type {Engine, MapView, Overlay} from './engine.ts';
import {layerEntry} from './layers.ts';
import {markData} from './marks.ts';
import {readPalette, type Palette} from './palette.ts';

type V1 = typeof import('../../dist/fleet-activity.js');
const loadV1 = (): Promise<V1> => import('../../dist/fleet-activity.js');
/** v1's `fetchLayer`, typed: checkJs is off, so its defaulted options infer too narrowly. */
type FetchLayer = (layer: string, filters: Record<string, string>, options: {region: string; bbox?: number[]; fetcher?: typeof fetch; signal?: AbortSignal}) => Promise<unknown>;

/** v1's order (dist/fleet-activity.js `LAYERS`): the rail lists them so. */
export const ACTIVITY = ['events', 'tracks', 'heat'] as const;
export type Activity = typeof ACTIVITY[number];
/** The registry entry for each option. */
export const ACTIVITY_ENTRY: Readonly<Record<Activity, string>> = {heat: 'fleet-heat', tracks: 'fleet-tracks', events: 'fleet-events'};
const [HEAT, TRACKS, TRACKS_DASHED, EVENTS] = ACTIVITY_LAYERS;
export {HEAT as FLEET_HEAT, TRACKS as FLEET_TRACKS, TRACKS_DASHED as FLEET_TRACKS_DASHED, EVENTS as FLEET_EVENTS};
export const FLEET_SOURCE = {heat: 'fleet-heat', tracks: 'fleet-tracks', events: 'fleet-events'} as const;
/** Line width and opacity by segment kind: fishing bold, transit and port faint, gaps dashed. */
export const SEGMENT_WIDTH: Readonly<Record<string, number>> = {'in-port': 1.5, transit: 2, 'fishing-drift': 4, 'fishing-troll': 4, gap: 2};
export const SEGMENT_OPACITY: Readonly<Record<string, number>> = {'in-port': 0.35, transit: 0.55, 'fishing-drift': 0.9, 'fishing-troll': 0.9, gap: 0.55};

type Props = Record<string, unknown>;
interface Feature {type: 'Feature'; geometry: {type: string; coordinates: unknown}; properties: Props}
export interface LayerResult {features: Feature[]; more: boolean; ignored: string[]; trips: number}

/** Whether this viewer may see the activity options (v1's `fleetAccess` answered with the filters). */
export const activityAccess = signal(false);
/** The options that are on; each one loads only while it is. */
export const activityOn = signal<readonly Activity[]>([]);
/** v1's status line for what is drawn, or why nothing is; empty while no option is on. */
export const activityStatus = signal('');
export function toggleActivity(name: Activity, on: boolean): void {
  activityOn.value = ACTIVITY.filter(a => a === name ? on : activityOn.peek().includes(a));
}

/** The map's bounds as minLon,minLat,maxLon,maxLat (v1's `mapBBox`), or null before it has a size. */
export function viewBBox(view: Pick<MapView, 'size' | 'unproject'>): [number, number, number, number] | null {
  const {width, height} = view.size();
  if (!(width > 0 && height > 0)) return null;
  const nw = view.unproject(0, 0), se = view.unproject(width, height);
  const w = Math.max(-180, nw.lon), s = Math.max(-90, se.lat), e = Math.min(180, se.lon), n = Math.min(90, nw.lat);
  return w < e && s < n ? [w, s, e, n] : null;
}

/** The drawn features as the three GeoJSON sources, each keyed by `key` and carrying its drawing values. */
export function activityCollections(v1: V1, results: Partial<Record<Activity, LayerResult>>): Record<Activity, Collection> {
  const heat = results.heat?.features ?? [], most = Math.max(0, ...heat.map(f => Number(f.properties.dwell_min) || 0));
  const out = (name: Activity, extra: (p: Props) => Props): Collection => ({type: 'FeatureCollection',
    features: (results[name]?.features ?? []).map(f => ({type: 'Feature', geometry: f.geometry, properties: {key: String(f.properties.id), ...extra(f.properties)}}))});
  return {
    heat: out('heat', p => ({opacity: v1.heatOpacity(p.dwell_min, most), planning: !!p.planning_only})),
    tracks: out('tracks', p => ({width: SEGMENT_WIDTH[String(p.segment_kind)] ?? 2, opacity: SEGMENT_OPACITY[String(p.segment_kind)] ?? 0.55,
      dashed: p.segment_kind === 'gap' || !!p.planning_only})),
    events: out('events', p => ({radius: v1.eventRadius(p.dwell_min), drift: p.kind !== 'troll', planning: !!p.planning_only})),
  };
}

/** Heat under tracks under events, every colour the --fleet token. */
export function activityOverlay(p: Palette, data: Record<Activity, Collection>): Overlay {
  const fleet = p.amber, src = (name: Activity) => ({type: 'geojson', data: data[name]} as MapLibre.SourceSpecification);
  return {
    sources: {[FLEET_SOURCE.heat]: src('heat'), [FLEET_SOURCE.tracks]: src('tracks'), [FLEET_SOURCE.events]: src('events')},
    layers: [
      {id: HEAT, type: 'fill', source: FLEET_SOURCE.heat, paint: {'fill-color': fleet, 'fill-opacity': ['get', 'opacity'], 'fill-outline-color': fleet}},
      {id: TRACKS, type: 'line', source: FLEET_SOURCE.tracks, filter: ['!', ['get', 'dashed']], layout: {'line-join': 'round', 'line-cap': 'round'},
        paint: {'line-color': fleet, 'line-width': ['get', 'width'], 'line-opacity': ['get', 'opacity']}},
      {id: TRACKS_DASHED, type: 'line', source: FLEET_SOURCE.tracks, filter: ['get', 'dashed'],
        paint: {'line-color': fleet, 'line-width': ['get', 'width'], 'line-opacity': ['get', 'opacity'], 'line-dasharray': [3, 3]}},
      {id: EVENTS, type: 'circle', source: FLEET_SOURCE.events, paint: {'circle-radius': ['get', 'radius'], 'circle-color': fleet,
        'circle-opacity': ['case', ['get', 'drift'], 0.55, 0.05], 'circle-stroke-color': fleet, 'circle-stroke-width': ['case', ['get', 'drift'], 1, 2.5],
        'circle-stroke-opacity': ['case', ['get', 'planning'], 0.45, 1]}},
    ] as MapLibre.LayerSpecification[],
  };
}

const label = (v: unknown): string => v ? String(v).replace(/[-_]+/g, ' ').replace(/^./, c => c.toUpperCase()) : '—';
const minutes = (n: unknown): string => {
  const m = Math.round(Number(n));
  if (n === null || n === undefined || !Number.isFinite(m)) return '—';
  return m >= 60 ? `${Math.floor(m / 60)} hr ${m % 60} min` : `${m} min`;
};
function clock(iso: unknown, zone: string): string {
  const t = Date.parse(String(iso));
  if (!Number.isFinite(t)) return '—';
  try { return new Intl.DateTimeFormat('en-US', {timeZone: zone, hour: 'numeric', minute: '2-digit'}).format(t); } catch { return `${new Date(t).toISOString().slice(11, 16)} UTC`; }
}
const boat = (p: Props): string => String(p.vessel_name || p.vessel_id || 'Unnamed boat');
const nm = (n: unknown): string => n !== null && n !== undefined && Number.isFinite(Number(n)) ? `${Number(n).toFixed(1)} nm` : '—';

/** The mark card for a feature of `layer`: v1's card facts as one card, each saying the activity is inferred from movement. */
export function activityMark(v1: V1, layer: Activity, p: Props, zone: string): ChartMark {
  const planning = p.planning_only ? ' · NOAA planning-only' : '';
  const rights = `Source: ${p.source || '—'} · rights: ${p.rights || '—'}${p.classifier_version ? ` · classifier ${p.classifier_version}` : ''}`;
  const basis = `${layerEntry(ACTIVITY_ENTRY[layer]).basis} Basis: ${p.basis || 'inferred-from-movement'}. AIS reception can miss boats or drop out offshore.`
    + (p.planning_only ? ' NOAA planning-only: MarineCadastre backfill for verification and internal use; keep it off paid surfaces.' : '');
  const kind = (k: unknown) => v1.EVENT_STYLE[String(k) as keyof V1['EVENT_STYLE']]?.label ?? label(k);
  if (layer === 'events') return {id: `fleet:event:${p.id}`, name: boat(p), kind: `Fleet activity · admin${planning}`, source: rights, basis,
    reading: `${kind(p.kind)} · ${minutes(p.dwell_min)} on ${p.local_date || '—'}, ${clock(p.started_at, zone)}–${clock(p.ended_at, zone)} · ${label(p.port_id)} · ${label(p.trip_type)}. ${v1.INFERRED}`};
  if (layer === 'tracks') {
    const segment = v1.SEGMENT_STYLE[String(p.segment_kind) as keyof V1['SEGMENT_STYLE']]?.label ?? label(p.segment_kind);
    const ports = [p.depart_port_id, p.return_port_id].filter(Boolean).map(label).join(' → ') || '—';
    return {id: `fleet:track:${p.id}`, name: boat(p), kind: `Fleet trip · admin${planning}`, source: rights, basis,
      reading: `${segment} segment · trip of ${p.local_date || '—'}, ${clock(p.departed_at, zone)}–${p.returned_at ? clock(p.returned_at, zone) : 'open'} · ${ports} · `
        + `${nm(p.distance_nm)}, furthest ${nm(p.max_offshore_nm)} offshore · fishing time ${minutes(p.fishing_min)}. ${v1.INFERRED}`};
  }
  const dates = p.first_date || p.last_date ? `${p.first_date || '?'} to ${p.last_date || '?'}` : '—';
  return {id: `fleet:heat:${p.id}`, name: `${kind(p.kind)} cell`, kind: `Fleet activity heat · admin${planning}`, source: `${rights} · computed ${p.computed_at || '—'}`, basis,
    reading: `${minutes(p.dwell_min)} total dwell · ${p.vessels_n ?? '—'} boats · ${p.events_n ?? '—'} stops · ${dates}. ${v1.INFERRED}`};
}

export interface FleetActivityOptions extends FleetLayerOptions {zone?: () => string}

/** Draws the admin activity layers while the Fleet entry and an option are on; created with the Chart (web/map/chart.ts `layers`). */
export function createFleetActivity({engine, fetchFn = (...a) => fetch(...a), palette = () => readPalette(), zone = () => 'America/Los_Angeles'}: FleetActivityOptions) {
  const entryOn = computed(() => layers.value.includes('fleet'));
  /** The state-level fleet region for the loaded coastal region (v1's `fleetRegion`); null until both are known. */
  const coastal = computed(() => { const m = markData.value; return m && m.region.id === region.value ? m.region : null; });
  const access = signal<{region: string; fleet: string | null} | null>(null);
  const bbox = signal<string>('');
  const results = signal<{key: string; data: Partial<Record<Activity, LayerResult>>} | null>(null);
  let v1: V1 | null = null, controller: AbortController | null = null, drawn = false, drawnOn: Engine | null = null, unwatch: (() => void) | null = null;
  const checks = new Map<string, Promise<string | null>>();

  const disposers = [
    // v1's access check, once per region, and only once the entry is on.
    effect(() => {
      const r = coastal.value;
      if (!entryOn.value || !r || access.peek()?.region === r.id) return;
      let check = checks.get(r.id);
      if (!check) checks.set(r.id, check = loadV1().then(async m => {
        v1 = m;
        const fleet = m.fleetRegion(r);
        return fleet && await m.fleetAccess(fleet, fetchFn) ? fleet : null;
      }, () => null));
      void check.then(fleet => { if (coastal.peek()?.id === r.id) access.value = {region: r.id, fleet}; });
    }),
    effect(() => {
      const a = access.value;
      activityAccess.value = !!a?.fleet && a.region === coastal.value?.id;
    }),
    // The map's bounds, after each settled move.
    effect(() => {
      const e = engine.value;
      unwatch?.(); unwatch = null;
      if (!e) return;
      const read = () => { const b = viewBBox(e.view); bbox.value = b ? b.map(v => v.toFixed(3)).join(',') : ''; };
      read();
      unwatch = e.view.on('idle', read);
    }),
    // Load the options that are on, for the bounds; a newer request aborts the older.
    effect(() => {
      const wanted = entryOn.value && activityAccess.value ? activityOn.value : [], fleet = access.value?.fleet, box = bbox.value;
      controller?.abort(); controller = null;
      if (!wanted.length || !fleet || !v1 || !box) { results.value = null; activityStatus.value = ''; return; }
      const key = `${fleet}|${box}|${wanted.join(',')}`;
      if (results.peek()?.key === key) return;
      const mine = controller = new AbortController(), m = v1, fetchLayer = v1.fetchLayer as unknown as FetchLayer;
      activityStatus.value = 'Loading fleet activity…';
      void Promise.all(wanted.map(name => fetchLayer(name, {}, {region: fleet, bbox: box.split(',').map(Number), fetcher: fetchFn, signal: mine.signal}))).then(loaded => {
        if (mine !== controller) return;
        results.value = {key, data: Object.fromEntries(wanted.map((name, i) => [name, loaded[i] as LayerResult]))};
        activityStatus.value = m.statusText(results.value.data);
      }, error => {
        if (mine !== controller || (error as Error)?.name === 'AbortError') return;
        results.value = null;
        activityStatus.value = 'Fleet activity could not load. The map and other layers remain available.';
      });
    }),
    effect(() => {
      const e = engine.value, r = results.value;
      if (!e) return;
      if (!r || !v1) { if (drawn || e !== drawnOn) e.setOverlay('fleet-activity', null); drawn = false; drawnOn = e; return; }
      const data = activityCollections(v1, r.data);
      // § 9 draw order: above the charter grounds and commercial AIS, under the cloud frames and the marks.
      if (!drawn || e !== drawnOn) e.setOverlay('fleet-activity', activityOverlay(palette(), data), fleetBefore());
      for (const name of ACTIVITY) e.setData(FLEET_SOURCE[name], data[name]);
      drawn = true; drawnOn = e;
    }),
  ];
  const owner: Record<string, Activity> = {[HEAT]: 'heat', [TRACKS]: 'tracks', [TRACKS_DASHED]: 'tracks', [EVENTS]: 'events'};
  return {
    destroy() {
      for (const dispose of disposers) dispose();
      unwatch?.(); controller?.abort();
      activityAccess.value = false; activityStatus.value = '';
    },
    pick: {layers: [EVENTS, TRACKS, TRACKS_DASHED, HEAT] as const, ordered: true, mark: (layer: string, properties: Record<string, unknown> | null): ChartMark | null => {
      const name = owner[layer], f = name ? results.peek()?.data[name]?.features.find(x => String(x.properties.id) === properties?.key) : undefined;
      return f && v1 && name ? activityMark(v1, name, f.properties, zone()) : null;
    }},
  };
}

// The Chart presentation (FE-11, docs/plans/front-end/design.md § 3A.2, § 4, § 9):
// MapLibre over the self-hosted Protomaps basemap, the region's coastline glow
// and the optional NOAA ENC chart base (`?base=chart`). It registers with the
// map stage (web/map/stage.ts `renderers`) and shares the stage's camera with
// the terrain: the stage's camera moves the chart, and a settled chart move
// writes the camera and `?view=` (no history entry), so Chart → 3D → Chart
// returns to the same place. MapLibre loads by dynamic import on the first
// Chart view (web/map/maplibre.js), after the app's first paint. The Seafloor
// rail entry draws the region's seafloor publication (web/map/seafloor.ts, FE-14).
// The region's protected areas (FE-19, web/map/mpa.ts) draw under the seafloor,
// always on; the host's `data-mpa`, `data-mpa-drawn` and `data-mpa-labels`
// report their state and what MapLibre drew in view.
//
// Erasable syntax only: tests/test_map_layers.mjs imports this file by type
// stripping and passes a fake library, so no GPU or MapLibre is needed.
import {effect, signal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {appView, base, region, setParams} from '../state.ts';
import {COASTLINE_PICK, coastlineLayers, coastlineMark, coastlineSource, shorelineURL, type ChartMark} from './coastline.ts';
import {createEngine, ZOOM_OFFSET, type Engine, type MapLibraryModule} from './engine.ts';
import {COASTLINE_SOURCE, ENC_SOURCE, MPA_SOURCE, SEAFLOOR_SOURCE, attributionFor, layerEntry} from './layers.ts';
import {IDLE, LOADING, MPA_FILL, MPA_LABEL, loadMpas, mpaLayers, mpaMark, mpaSource, mpaState} from './mpa.ts';
import {readPalette, type Palette} from './palette.ts';
import {SEAFLOOR_PICK, createSeafloor, seafloorLayers, seafloorSource} from './seafloor.ts';
import {BASEMAP_SOURCE, basemapStyle} from './style.ts';
import {camera, cameraParam, parseCamera, shownPresentation, type Camera} from './stage.ts';

/** FE-10's pointer to the current basemap archive, under the page's /feeds/ route. */
export const BASEMAP_MANIFEST = 'feeds/tiles/basemap/manifest.json';
const ARCHIVE_KEY = /^tiles\/basemap\/[A-Za-z0-9._-]{1,120}\.pmtiles$/;
/** NOAA's chart display WMS (the v1 chart's service and its fishing layer set). */
export const ENC_WMS = 'https://gis.charttools.noaa.gov/arcgis/rest/services/MCS/NOAAChartDisplay/MapServer/exts/MaritimeChartService/WMSServer'
  + '?service=WMS&request=GetMap&version=1.3.0&layers=0,1,2,6&styles=&format=image/png&transparent=false&crs=EPSG:3857&width=512&height=512&bbox={bbox-epsg-3857}';
export const ENC_LAYER = 'chart-enc';
/** The ENC base draws from `?view=` zoom 10 (§ 4). */
export const ENC_MIN_ZOOM = 10;

/** The Chart's selection, for the mark card. */
export const chartMark = signal<ChartMark | null>(null);
/** Registry layers whose source failed; the legend says so and the rest of the chart keeps drawing. */
export const unavailable = signal<readonly string[]>([]);
/** True when MapLibre could not start (no WebGL); the stage then shows its "Map unavailable." panel. */
export const chartFailed = signal(false);

/** The basemap archive's absolute URL from the manifest, or null when there is no valid manifest. */
export async function basemapArchive(fetchFn: typeof fetch, page: string): Promise<string | null> {
  try {
    const response = await fetchFn(new URL(BASEMAP_MANIFEST, page).href, {signal: AbortSignal.timeout(15000)});
    if (!response.ok) return null;
    const manifest = await response.json() as {key?: unknown};
    return typeof manifest.key === 'string' && ARCHIVE_KEY.test(manifest.key) ? new URL(`feeds/${manifest.key}`, page).href : null;
  } catch { return null; }
}

export interface ChartStyleOptions {palette: Palette; archive: string | null; page: string; region: string; base: string}
/** The whole Chart style: the token basemap (or only its water without an archive), the ENC base, the protected areas, the seafloor (hidden), then the coastline on top. */
export function chartStyle(o: ChartStyleOptions): MapLibre.StyleSpecification {
  const style = basemapStyle(o.palette, {archive: o.archive ?? '', assets: new URL('basemap/', o.page).href});
  const layers: unknown[] = o.archive ? style.layers : style.layers.filter(l => l.source !== BASEMAP_SOURCE);
  const sources: Record<string, unknown> = o.archive ? {...style.sources} : {};
  sources[ENC_SOURCE] = {type: 'raster', tiles: [ENC_WMS], tileSize: 512, minzoom: ENC_MIN_ZOOM - ZOOM_OFFSET, maxzoom: 18, attribution: layerEntry('chart').attribution};
  sources[MPA_SOURCE] = mpaSource();
  sources[SEAFLOOR_SOURCE] = seafloorSource();
  sources[COASTLINE_SOURCE] = coastlineSource(o.region, o.page);
  layers.push({id: ENC_LAYER, type: 'raster', source: ENC_SOURCE, minzoom: ENC_MIN_ZOOM - ZOOM_OFFSET, layout: {visibility: o.base === 'chart' ? 'visible' : 'none'}});
  layers.push(...mpaLayers(o.palette), ...seafloorLayers(o.palette), ...coastlineLayers(o.palette));
  return {...style, sources, layers} as unknown as MapLibre.StyleSpecification;
}

/** Mark a registry layer unavailable once. */
export function markUnavailable(layer: string, error?: unknown): void {
  if (unavailable.peek().includes(layer)) return;
  console.warn(`Chart layer ${layer} unavailable`, error);
  unavailable.value = [...unavailable.peek(), layer];
}

export interface ChartOptions {
  host: HTMLElement;
  load?: () => Promise<MapLibraryModule>;
  fetchFn?: typeof fetch;
  palette?: () => Palette;
  /** The page URL relative feeds and regions resolve against. */
  page?: () => string;
  /** Milliseconds a settled chart move waits before it is written to `?view=`. */
  viewDelay?: number;
}

const loadLibrary = (): Promise<MapLibraryModule> => import('./maplibre.js');

export function createChart(options: ChartOptions): {destroy(): void} {
  const {host, load = loadLibrary, fetchFn = (...a) => fetch(...a), palette = () => readPalette(), page = () => location.href, viewDelay = 400} = options;
  const engine = signal<Engine | null>(null);
  let mounting = false, alive = true, applied = '', drawnRegion: string | null = null, seafloor: ReturnType<typeof createSeafloor> | null = null;
  let viewTimer: ReturnType<typeof setTimeout> | undefined;
  const show = (c: Camera): void => { applied = cameraParam(c); host.dataset.view = applied; };

  const onMove = (seen: Camera): void => {
    const next = parseCamera(cameraParam(seen));
    if (!next) return;
    const k = cameraParam(next);
    host.dataset.view = k;
    if (k === applied || shownPresentation.peek() !== 'chart' || appView.peek() !== 'coast') return;
    applied = k;
    camera.value = next;
    clearTimeout(viewTimer);
    viewTimer = setTimeout(() => { if (alive && shownPresentation.peek() === 'chart' && appView.peek() === 'coast') setParams({view: k}); }, viewDelay);
  };

  async function mount(): Promise<void> {
    const at = camera.peek(), id = region.peek();
    if (mounting || engine.peek() || chartFailed.peek() || !at || !id) return;
    mounting = true;
    try {
      const [library, archive] = await Promise.all([load(), basemapArchive(fetchFn, page())]);
      if (!alive) return;
      if (!archive) markUnavailable('basemap', new Error(`No basemap archive at ${BASEMAP_MANIFEST}`));
      const start = camera.peek() ?? at;
      const e: Engine = createEngine(library, {
        host, camera: start, onMove, onLayerError: markUnavailable, pickLayers: [SEAFLOOR_PICK, COASTLINE_PICK, MPA_FILL], attribution: archive ? attributionFor(['basemap']) : undefined,
        style: chartStyle({palette: palette(), archive, page: page(), region: id, base: base.peek()}),
        onPick: (layer, properties) => {
          chartMark.value = layer === COASTLINE_PICK ? coastlineMark(properties) : layer === SEAFLOOR_PICK ? seafloor?.mark(String(properties?.id ?? '')) ?? null
            : layer === MPA_FILL ? mpaMark(properties) : null;
        },
        onIdle: () => { host.dataset.mpaDrawn = String(e.rendered(MPA_FILL)); host.dataset.mpaLabels = String(e.rendered(MPA_LABEL)); },
      });
      engine.value = e;
      seafloor = createSeafloor({engine: e, open: url => new library.PMTiles(url), fetchFn, page,
        size: () => ({width: host.clientWidth, height: host.clientHeight}),
        onHide: () => { if (chartMark.peek()?.id.startsWith('seafloor:')) chartMark.value = null; }});
      drawnRegion = id;
      show(start);
    } catch (error) {
      console.error('Chart unavailable', error);
      if (alive) chartFailed.value = true;
    } finally {
      mounting = false;
    }
  }

  const disposers = [
    // The first Chart view loads MapLibre; a terrain-only visit never does.
    effect(() => { if (shownPresentation.value === 'chart' && camera.value && region.value) void mount(); }),
    // The shared camera moves the chart, hidden or shown, unless the chart is already there.
    effect(() => { const e = engine.value, c = camera.value; if (e && c && cameraParam(c) !== applied) { show(c); e.setCamera(c); } }),
    effect(() => {
      const e = engine.value, id = region.value;
      if (!e || !id || id === drawnRegion) return;
      drawnRegion = id;
      chartMark.value = null;
      unavailable.value = unavailable.peek().filter(layer => layer !== 'coastline');
      e.setData(COASTLINE_SOURCE, new URL(shorelineURL(id), page()).href);
    }),
    effect(() => { engine.value?.setVisible(ENC_LAYER, base.value === 'chart'); }),
    // The region's protected areas, checked before they draw; a region change replaces them.
    effect(() => { const e = engine.value, id = region.value; if (e && id) void drawMpas(e, id); }),
    effect(() => { host.dataset.mpa = mpaState.value.status; }),
  ];
  async function drawMpas(e: Engine, id: string): Promise<void> {
    mpaState.value = LOADING;
    unavailable.value = unavailable.peek().filter(layer => layer !== 'mpas');
    const {state, data} = await loadMpas(id, fetchFn, page());
    if (!alive || engine.peek() !== e || region.peek() !== id) return;
    e.setData(MPA_SOURCE, data);
    mpaState.value = state;
    if (state.status === 'unavailable') markUnavailable('mpas', new Error(state.detail));
  }

  return {
    destroy() {
      if (!alive) return;
      alive = false;
      clearTimeout(viewTimer);
      for (const dispose of disposers) dispose();
      seafloor?.destroy();
      engine.peek()?.destroy();
      engine.value = null;
      chartMark.value = null;
      unavailable.value = [];
      mpaState.value = IDLE;
    },
  };
}

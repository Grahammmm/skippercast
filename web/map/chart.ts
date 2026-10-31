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
// always on; the host's `data-mpa` reports their state. With diagnostics enabled,
// `data-mpa-drawn` and `data-mpa-labels` report what MapLibre drew in view.
// Habitat, geology, reef marks and the selection (FE-18) come from web/map/marks.ts.
// Registry layers with run-time sources (FE-22's clouds, FE-16's water
// temperature) are created with the Chart and draw through its engine
// (`layers`, Engine.setOverlay); a click on open water asks them for a reading.
// The trip planner's ranked spots (#495, web/map/ranked.ts) draw above the marks;
// the host's `data-ranked` and `data-ranked-drawn` report how many ranked spots
// both screens admit and, with diagnostics enabled, how many pins MapLibre drew in view.
// The first idle of a visit's first Chart view may fly the camera (#646,
// web/map/flyover.ts); the host's `data-flyover` reads flying, done or stopped.
//
// Erasable syntax only: tests/test_map_layers.mjs imports this file by type
// stripping and passes a fake library, so no GPU or MapLibre is needed.
import {effect, signal, type ReadonlySignal} from '@preact/signals';
import type * as MapLibre from 'maplibre-gl';
import {appView, base, habitat, region, selection, setParams, view} from '../state.ts';
import {harborOrigin} from '../ranking.ts';
import {placeWaypoint} from '../waypoint-placement.ts';
import {shareStatic, sharedFetch} from '../shared-fetch.ts';
import {chartFilesPending} from '../chart-files.ts';
import {loadPoster, poster} from './poster.ts';
import {COASTLINE_PICK, coastlineFetchPath, coastlineLayers, coastlineMark, coastlineSource, shorelineOverviewURL, shorelinePublished, shorelineURL, type ChartMark} from './coastline.ts';
import {createCurrents, type Currents, type CurrentsOptions} from './currents.ts';
import {createEngine, ZOOM_OFFSET, type Engine, type MapLibraryModule} from './engine.ts';
import {openBandPadding, toEdge, type Box} from './open-band.ts';
import {browserGate, flyoverLegs, markFlyoverSeen, mayFly, type FlyoverGate} from './flyover.ts';
import {COASTLINE_SOURCE, DENSITY_SOURCE, ENC_SOURCE, MARKS_SOURCE, MPA_SOURCE, RANKED_SOURCE, SEAFLOOR_SOURCE, attributionFor, layerEntry, overlayFeatures, setTerrainLayer} from './layers.ts';
import {GEOLOGY_PICK, MARK_PICK, SURVEY_PICK, chartPick, createMarks, markData, markSources, markStyle} from './marks.ts';
import {IDLE, LOADING, MPA_FILL, MPA_LABEL, loadMpas, mpaLayers, mpaMark, mpaSource, mpaState, type MpaResult} from './mpa.ts';
import {readPalette, type Palette} from './palette.ts';
import {RANKED_PICK, RANKED_PIN, drawnSpots, rankedFeatures, rankedMark, rankedStyle, rankedZoom, zoomToGroup} from './ranked.ts';
import {SEAFLOOR_PICK, createSeafloor, seafloorLayers, seafloorSource} from './seafloor.ts';
import {BASEMAP_MANIFEST, BASEMAP_SOURCE, basemapArchive, basemapStyle} from './style.ts';
import {camera, cameraParam, parseCamera, shownPresentation, type Camera} from './stage.ts';

/** FE-10's manifest reader moved to style.ts with the basemap (FE-25 reads it on the landing without the Chart). */
export {BASEMAP_MANIFEST, basemapArchive};

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

export interface ChartStyleOptions {palette: Palette; archive: string | null; page: string; region: string; base: string;
  /** The shoreline file to draw (coastline.ts `shorelineFor`); the full one when absent. */
  shoreline?: string}
/**
 * A click's card: the picked feature's (a mark, a seafloor candidate, a protected area, any drawn layer's pick), else
 * the first reading at the point: a drawn seafloor coverage cell (#706), then the drawn surface current (FE-15) or
 * water temperature (FE-16). A cell never displaces a more specific pick.
 */
export function clickMark(other: ChartMark | null, at: {lon: number; lat: number} | null, readings: readonly ((at: {lon: number; lat: number}) => ChartMark | null)[]): ChartMark | null {
  if (other || !at) return other;
  for (const read of readings) { const mark = read(at); if (mark) return mark; }
  return null;
}

/** The whole Chart style in § 9 order: the token basemap (or only its water without an archive), the ENC base, the protected areas, habitat, the seafloor (hidden), marks, the ranked trip spots, then the coastline on top. */
export function chartStyle(o: ChartStyleOptions): MapLibre.StyleSpecification {
  const style = basemapStyle(o.palette, {archive: o.archive ?? '', assets: new URL('basemap/', o.page).href});
  const layers: unknown[] = o.archive ? style.layers : style.layers.filter(l => l.source !== BASEMAP_SOURCE);
  const sources: Record<string, unknown> = o.archive ? {...style.sources} : {};
  sources[ENC_SOURCE] = {type: 'raster', tiles: [ENC_WMS], tileSize: 512, minzoom: ENC_MIN_ZOOM - ZOOM_OFFSET, maxzoom: 18, attribution: layerEntry('chart').attribution};
  sources[MPA_SOURCE] = mpaSource();
  sources[SEAFLOOR_SOURCE] = seafloorSource();
  sources[COASTLINE_SOURCE] = coastlineSource(o.region, o.page, o.shoreline ?? shorelineURL(o.region));
  const marks = markStyle(o.palette), ranked = rankedStyle(o.palette);
  Object.assign(sources, marks.sources, {[RANKED_SOURCE]: ranked.source});
  layers.push({id: ENC_LAYER, type: 'raster', source: ENC_SOURCE, minzoom: ENC_MIN_ZOOM - ZOOM_OFFSET, layout: {visibility: o.base === 'chart' ? 'visible' : 'none'}});
  layers.push(...mpaLayers(o.palette), ...marks.habitat, ...seafloorLayers(o.palette), ...marks.marks, ...ranked.layers, ...coastlineLayers(o.palette));
  return {...style, sources, layers} as unknown as MapLibre.StyleSpecification;
}

/** Mark a registry layer unavailable once. */
export function markUnavailable(layer: string, error?: unknown): void {
  if (unavailable.peek().includes(layer)) return;
  console.warn(`Chart layer ${layer} unavailable`, error);
  unavailable.value = [...unavailable.peek(), layer];
}

/**
 * A registry layer the Chart draws at run time (FE-22's clouds, FE-16's water temperature): created
 * with the Chart, handed its engine once MapLibre is up. A field layer reads itself at a click on open water.
 */
export type ChartLayer = (engine: ReadonlySignal<Engine | null>) => {
  destroy(): void;
  reading?(at: {lon: number; lat: number}): ChartMark | null;
  /**
   * Its own clickable map layers and the card for a feature of them: asked before the Chart's (FE-27's nearshore
   * rings), or with `ordered` among them, the topmost drawn feature winning (FE-21's fleet areas, under the marks).
   */
  pick?: {readonly layers: readonly string[]; readonly ordered?: boolean; mark(layer: string, properties: Record<string, unknown> | null): ChartMark | null};
};

export interface ChartOptions {
  host: HTMLElement;
  layers?: readonly ChartLayer[];
  load?: () => Promise<MapLibraryModule>;
  fetchFn?: typeof fetch;
  palette?: () => Palette;
  /** The page URL relative feeds and regions resolve against. */
  page?: () => string;
  /** Milliseconds a settled chart move waits before it is written to `?view=`. */
  viewDelay?: number;
  /** Report rendered-feature counts for debugging; defaults to the page URL's exact `diagnostics=1` opt-in. */
  diagnostics?: boolean;
  /** The region's zone and report place, for the Currents layer (FE-15, web/map/currents.ts). */
  zone?: () => string;
  place?: CurrentsOptions['place'];
  /** The flyover's browser gates (#646), given whether the link names a place; flyover.ts `browserGate` by default. */
  flyoverGate?: (linked: boolean) => FlyoverGate;
  /** RF0905-1: what covers the map on a phone; by default the top card and the sheet. */
  covers?: () => readonly Box[];
}

const loadLibrary = (): Promise<MapLibraryModule> => import('./maplibre.js');

export function createChart(options: ChartOptions): {destroy(): void} {
  const {host, layers = [], load = loadLibrary, palette = () => readPalette(), page = () => location.href, viewDelay = 400, flyoverGate = browserGate} = options;
  const diagnostics = options.diagnostics ?? (new URL(page()).searchParams.get('diagnostics') === '1');
  const covers = options.covers ?? ((): Box[] => typeof document === 'undefined' ? [] : [...document.querySelectorAll('.app-top, .ui-sheet')]
    .map(el => el.matches('.ui-sheet') ? toEdge(el.getBoundingClientRect(), host.getBoundingClientRect?.().bottom ?? NaN) : el.getBoundingClientRect()));
  // The marks, the protected areas and the masthead read the same region files: one request each (the startup budget).
  const fetchFn = shareStatic(options.fetchFn ?? sharedFetch);
  const engine = signal<Engine | null>(null);
  const mpas = signal<{region: string; data: MpaResult['data']} | null>(null);
  let mounting = false, alive = true, applied = '', drawnRegion: string | null = null, seafloor: ReturnType<typeof createSeafloor> | null = null;
  // #617: the shoreline file drawn now, and the region whose full shoreline has loaded (kept on zooming out: no second request).
  let drawnShore = '', detailRegion: string | null = null;
  // #617: the poster (poster.ts) is asked for once, on the first mount, and goes on the first idle or user move.
  let posterAsked = false, painted = false;
  const posterDone = (): void => { painted = true; poster.value = null; };
  let currents: Currents | null = null;
  let sourceContext = {};
  let viewTimer: ReturnType<typeof setTimeout> | undefined;
  const show = (c: Camera): void => { applied = cameraParam(c); host.dataset.view = applied; };
  const marks = createMarks({fetchFn, page, onError: markUnavailable});
  // #646: asked once, at the first idle of the first mount, and only if nothing moved the camera before it.
  let flyAsked = false;
  const flyIfFirst = (e: Engine): void => {
    if (flyAsked) return;
    flyAsked = true;
    const at = camera.peek(), linked = !!(view.peek() || selection.peek() || habitat.peek());
    if (!at || shownPresentation.peek() !== 'chart' || appView.peek() !== 'coast' || !mayFly(flyoverGate(linked))) return;
    const data = markData.peek(), harbor = data && data.region.id === region.peek() ? harborOrigin(data) : null;
    markFlyoverSeen();
    host.dataset.flyover = 'flying';
    e.flyover(flyoverLegs(at, harbor), finished => { if (alive) host.dataset.flyover = finished ? 'done' : 'stopped'; });
  };

  const onMove = (seen: Camera): void => {
    const next = parseCamera(cameraParam(seen));
    if (!next) return;
    const k = cameraParam(next);
    host.dataset.view = k;
    if (k === applied || shownPresentation.peek() !== 'chart' || appView.peek() !== 'coast') return;
    applied = k;
    posterDone();
    camera.value = next;
    clearTimeout(viewTimer);
    viewTimer = setTimeout(() => { if (alive && shownPresentation.peek() === 'chart' && appView.peek() === 'coast') setParams({view: k}); }, viewDelay);
  };

  async function mount(): Promise<void> {
    const at = camera.peek(), id = region.peek();
    if (mounting || engine.peek() || chartFailed.peek() || !at || !id) return;
    mounting = true;
    if (!posterAsked) { posterAsked = true; void loadPoster(id, page(), () => painted, options.fetchFn); }
    try {
      const [library, archive] = await Promise.all([load(), basemapArchive(fetchFn, page())]);
      if (!alive) return;
      if (!archive) markUnavailable('basemap', new Error(`No basemap archive at ${BASEMAP_MANIFEST}`));
      const start = camera.peek() ?? at;
      const e: Engine = createEngine(library, {
        host, camera: start, onMove,
        sourceContext: () => sourceContext,
        onSourceTileLoaded: sourceId => {
          if (alive && sourceId === ENC_SOURCE) unavailable.value = unavailable.peek().filter(layer => layer !== 'chart');
        },
        // #617: an overview shoreline that fails falls back to the full one; any other failure marks its layer.
        onLayerError: (layer, error) => {
          const id = region.peek();
          if (layer === 'coastline' && id && drawnShore === shorelineOverviewURL(id)) {
            console.warn('Overview shoreline unavailable; loading the full shoreline', error);
            detailRegion = id; drawnShore = shorelineURL(id); engine.peek()?.setData(COASTLINE_SOURCE, new URL(drawnShore, page()).href);
          } else markUnavailable(layer, error);
        }, attribution: archive ? attributionFor(['basemap']) : undefined,
        pickLayers: [RANKED_PICK, MARK_PICK, SURVEY_PICK, GEOLOGY_PICK, SEAFLOOR_PICK, COASTLINE_PICK, MPA_FILL, ...drawn.flatMap(l => l.pick?.ordered ? l.pick.layers : [])],
        pickFirst: () => drawn.flatMap(l => l.pick && !l.pick.ordered ? l.pick.layers : []),
        // RF0850-2: while region.json is loading the style draws no shoreline; the camera effect asks once the list is known.
        style: chartStyle({palette: palette(), archive, page: page(), region: id, base: base.peek(), shoreline: drawnShore = chartFilesPending(id) ? '' : coastlineFetchPath(id, start.zoom) ?? ''}),
        onPick: (layer, properties, at) => {
          if (placeWaypoint(region.peek(), at)) return;
          // A grouped ranked pin zooms to its spots and keeps the selection, as v1's does (#495).
          if (layer === RANKED_PICK && zoomToGroup(properties)) return;
          const other = layer === COASTLINE_PICK ? coastlineMark(properties) : layer === SEAFLOOR_PICK ? seafloor?.mark(String(properties?.id ?? '')) ?? null
            : layer === MPA_FILL ? mpaMark(properties) : layer === RANKED_PICK ? rankedMark(properties)
            : drawn.find(l => layer !== null && l.pick?.layers.includes(layer))?.pick?.mark(layer!, properties) ?? null;
          // A mark selects its spot; any other pick is the Chart's own selection (one at a time, FE-18).
          chartMark.value = chartPick(layer, properties, clickMark(other, at, [p => seafloor?.cellAt(p) ?? null, fieldReading]));
        },
        onIdle: () => {
          if (!painted) { posterDone(); flyIfFirst(e); try { performance.mark('skippercast-chart-idle'); } catch { /* no timing API */ } }
          else flyAsked = true;
          if (diagnostics) {
            host.dataset.mpaDrawn = String(e.rendered(MPA_FILL)); host.dataset.mpaLabels = String(e.rendered(MPA_LABEL));
            host.dataset.rankedDrawn = String(e.rendered(RANKED_PIN));
          }
        },
      });
      // Before `engine` is set: its effect would otherwise send the style's own shoreline again (a second 0.6 MB request).
      drawnRegion = id;
      engine.value = e;
      // RF0905-1: below the 1024 px layout break the centre draws in the open band, at mount and on resize only (never on a detent change).
      let padded = false;
      const pad = (): void => {
        const rect = host.getBoundingClientRect?.();
        if (!rect || !alive) return;
        if (host.clientWidth < 1024) { const p = openBandPadding(rect, covers()); e.setPadding(p); padded = p.top + p.bottom > 0; }
        else if (padded) { e.setPadding({top: 0, bottom: 0, left: 0, right: 0}); padded = false; }
      };
      pad(); e.view.on('resize', pad);
      seafloor = createSeafloor({engine: e, open: url => new library.PMTiles(url), fetchFn, page,
        size: () => ({width: host.clientWidth, height: host.clientHeight}),
        onHide: () => { if (chartMark.peek()?.id.startsWith('seafloor:')) chartMark.value = null; }});
      currents = createCurrents({view: e.view, palette, zone: options.zone, place: options.place,
        onHide: () => { if (chartMark.peek()?.id.startsWith('current:')) chartMark.value = null; }});
      show(start);
    } catch (error) {
      console.error('Chart unavailable', error);
      posterDone();
      if (alive) chartFailed.value = true;
    } finally {
      mounting = false;
    }
  }

  const disposers = [
    // A fresh token also rejects an old request after switching away and back.
    effect(() => { region.value; sourceContext = {}; }),
    // The first Chart view loads MapLibre; a terrain-only visit never does.
    effect(() => { if (shownPresentation.value === 'chart' && camera.value && region.value) void mount(); }),
    // The shared camera moves the chart, hidden or shown, unless the chart is already there.
    // A flyover stops first, so its moveend at the old centre still matches `applied` and writes nothing.
    effect(() => { const e = engine.value, c = camera.value; if (e && c && cameraParam(c) !== applied) { e.stopFlyover(); show(c); e.setCamera(c); } }),
    effect(() => {
      const e = engine.value, id = region.value;
      if (!e || !id) return;
      if (id !== drawnRegion) {
        drawnRegion = id;
        chartMark.value = null;
        unavailable.value = unavailable.peek().filter(layer => !['coastline', 'marks', 'habitat'].includes(layer));
      }
      // RF0850-2: once this region's list is known and names neither shoreline file, the coastline reads unavailable (once: markUnavailable keeps one entry).
      if (!chartFilesPending(id) && !shorelinePublished(id)) markUnavailable('coastline', new Error('no shoreline published for this region'));
    }),
    // The overview shoreline until the camera reaches the detail zoom, then the full one for the rest of the visit.
    // RF0850-2: nothing is asked while the region's list is pending; the effect runs again when it is published.
    // App.tsx's module effect exists before any Chart, so on a region change it marks the list pending before this runs.
    effect(() => {
      const e = engine.value, id = region.value, c = camera.value;
      if (!e || !id || !c || chartFilesPending(id)) return;
      const path = coastlineFetchPath(id, c.zoom, detailRegion === id);
      if (path === null) { if (drawnShore) { drawnShore = ''; e.setData(COASTLINE_SOURCE, {type: 'FeatureCollection', features: []}); } return; }
      if (path === shorelineURL(id)) detailRegion = id;
      if (path !== drawnShore) { drawnShore = path; e.setData(COASTLINE_SOURCE, new URL(path, page()).href); }
    }),
    effect(() => { engine.value?.setVisible(ENC_LAYER, base.value === 'chart'); }),
    // Another presentation or view, or a selection, ends a flyover where it is, north up.
    effect(() => { if (shownPresentation.value !== 'chart' || appView.value !== 'coast' || selection.value || habitat.value) engine.peek()?.stopFlyover(); }),
    // The region's protected areas, checked before they draw; a region change replaces them. They load with the
    // region, whatever the presentation, because the terrain drapes the same areas (FE-82).
    effect(() => { const id = region.value; if (id) void loadRegionMpas(id); }),
    effect(() => { const e = engine.value, m = mpas.value; if (e && m && m.region === region.value) e.setData(MPA_SOURCE, m.data); }),
    effect(() => { host.dataset.mpa = mpaState.value.status; }),
    // A new link selection (a mark, a terrain pick, Back) replaces the Chart's own: one selection at a time.
    effect(() => { if (selection.value || habitat.value) chartMark.value = null; }),
    ...Object.entries(markSources).map(([id, data]) => effect(() => {
      const e = engine.value, collection = data.value;
      if (!e) return;
      e.setData(id, collection);
      if (id === MARKS_SOURCE) host.dataset.marks = String(collection.features.length);
      if (id === DENSITY_SOURCE) host.dataset.density = String(collection.features.length);
    })),
    // The ranked trip spots, grouped at the camera's zoom; a spot that is cleared or withheld takes its card with it.
    effect(() => {
      const e = engine.value, spots = drawnSpots.value;
      host.dataset.ranked = String(spots.length);
      e?.setData(RANKED_SOURCE, rankedFeatures(spots, rankedZoom.value));
      const shown = chartMark.peek()?.trip;
      if (shown && !spots.some(s => s.id === shown)) chartMark.value = null;
    }),
  ];
  async function loadRegionMpas(id: string): Promise<void> {
    mpaState.value = LOADING;
    unavailable.value = unavailable.peek().filter(layer => layer !== 'mpas');
    setTerrainLayer('mpas', null);
    const {state, data} = await loadMpas(id, fetchFn, page());
    if (!alive || region.peek() !== id) return;
    mpas.value = {region: id, data};
    mpaState.value = state;
    if (state.status === 'unavailable') markUnavailable('mpas', new Error(state.detail));
    // A terrain pick of an area opens the same card as the Chart's click (mpaMark of the same feature).
    setTerrainLayer('mpas', {features: overlayFeatures(data.features, (_f, i) => i),
      pick: i => { const mark = mpaMark(data.features[Number(i)]?.properties as Record<string, unknown> | undefined); return mark && chartPick(null, null, mark); }});
  }

  const drawn = layers.map(create => create(engine));
  const fieldReading = (at: {lon: number; lat: number}): ChartMark | null =>
    currents?.reading(at) ?? drawn.map(l => l.reading?.(at) ?? null).find(m => m !== null) ?? null;
  return {
    destroy() {
      if (!alive) return;
      alive = false;
      clearTimeout(viewTimer);
      posterDone();
      for (const dispose of disposers) dispose();
      seafloor?.destroy();
      marks.destroy();
      currents?.destroy();
      for (const layer of drawn) layer.destroy();
      engine.peek()?.destroy();
      engine.value = null;
      chartMark.value = null;
      unavailable.value = [];
      mpaState.value = IDLE;
      setTerrainLayer('mpas', null);
    },
  };
}

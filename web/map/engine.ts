// MapLibre init for the Chart presentation (FE-11, docs/plans/front-end/design.md
// § 3, § 3A.2): the PMTiles protocol and the worker URL registered once, a
// north-up map (no rotation or pitch by any gesture or key; only the first-view
// flyover, #646, tilts and turns it and always returns it north up and flat), a nautical scale,
// zoom buttons, the attribution control, resize with its host, and error
// routing: a failing source marks only the registry layer that owns it
// (web/map/layers.ts), so one broken feed never blanks the chart.
//
// The library is passed in (web/map/maplibre.js loads it by dynamic import), so
// this file never imports MapLibre at run time and tests/test_map_layers.mjs
// drives it with a fake map. Erasable syntax only.
import type * as MapLibre from 'maplibre-gl';
import {FRAME_PROTOCOL, frameProtocol} from './frames.ts';
import {sourceLayer} from './layers.ts';
import type {FieldTexture} from './field.ts';
import type {ArchiveReader} from './seafloor.ts';
import {BASEMAP_SOURCE} from './style.ts';

/** What web/map/maplibre.js provides: the ESM build, its worker's URL, the PMTiles protocol and its archive reader. */
export interface MapLibraryModule {
  readonly lib: Pick<typeof MapLibre, 'Map' | 'NavigationControl' | 'ScaleControl' | 'AttributionControl' | 'setWorkerUrl' | 'addProtocol'>;
  readonly workerUrl: string;
  readonly Protocol: new () => {tile: MapLibre.AddProtocolAction};
  /** Reads archives the Chart decodes itself (the seafloor publication, web/map/seafloor.ts). */
  readonly PMTiles: new (url: string) => ArchiveReader;
}

/** A camera in the `?view=` convention (web/map/stage.ts): 256 px web-map zoom, as v1's chart writes it. */
export interface EngineCamera {readonly latitude: number; readonly longitude: number; readonly zoom: number}
/** MapLibre's zoom uses 512 px tiles: its zoom z shows what a 256 px web map shows at z + 1. */
export const ZOOM_OFFSET = 1;
/** RF2205-5: how long a click waits for a double-tap zoom before it picks (MapLibre's tap interval is 500 ms). */
export const PICK_SETTLE_MS = 550;
/** The span-to-zoom rule's range (stage.ts zoomForSpan), in `?view=` zoom. */
export const VIEW_ZOOM = {min: 7, max: 18} as const;

export interface EngineOptions {
  host: HTMLElement;
  style: MapLibre.StyleSpecification;
  camera: EngineCamera;
  /** After every settled move, in `?view=` zoom. */
  onMove(camera: EngineCamera): void;
  /** A source error, routed to the registry layer that owns the source. */
  onLayerError(layer: string, error: unknown): void;
  /** A loaded tile from the same source and context in which its request began. */
  onSourceTileLoaded?(sourceId: string): void;
  /** Changes invalidate pending tile recovery (for example, on a region change). */
  sourceContext?(): unknown;
  /** RF2205-5: a delayed pick is dropped unless this still returns the identity it had at the click (separate from sourceContext, so gesture state never resets tile recovery). Null means picking is closed: it never accepts a pick, even when null at both the click and the dispatch. */
  pickContext?(): unknown;
  /** A click: the first feature under it in `pickLayers`, or null for empty water, and where it fell. */
  onPick?(layer: string | null, properties: Record<string, unknown> | null, at: {lon: number; lat: number} | null): void;
  pickLayers?: readonly string[];
  /** Run-time layers asked before `pickLayers` (FE-27's nearshore rings, which draw under the protected areas); read at each click. */
  pickFirst?: () => readonly string[];
  /** Credit always shown (the basemap's): MapLibre lists a tiled source's own credit only if it was drawn when its metadata arrived. */
  attribution?: string;
  /** The map has settled and drawn every tile in view (MapLibre `idle`). */
  onIdle?(): void;
  /** A still backdrop (the landing's night map, FE-25): no gesture, key, control or label fade; the page credits the basemap itself. */
  still?: boolean;
}

/** One leg of the flyover (#646, web/map/flyover.ts): the tilt and turn to reach, in degrees, over `duration` milliseconds. */
export interface FlyLeg {readonly pitch: number; readonly bearing: number; readonly duration: number}
/** Input that stops a flyover: the visitor took the map. */
export const FLY_STOPPERS = ['pointerdown', 'touchstart', 'wheel', 'keydown'] as const;

/** What a GeoJSON source accepts: a URL or GeoJSON. */
export type SourceData = Parameters<MapLibre.GeoJSONSource['setData']>[0];

/** What a canvas overlay (web/map/currents.ts, FE-15) reads from the map; the Chart stays north up. */
export interface MapView {
  /** The map's canvas container: an overlay canvas added here sits above the map and under its controls. */
  container(): HTMLElement;
  /** The map's size in CSS pixels. */
  size(): {width: number; height: number};
  project(lon: number, lat: number): {x: number; y: number};
  unproject(x: number, y: number): {lon: number; lat: number};
  /** True while the camera moves, or before every tile in view has loaded (the next `idle` settles it). */
  busy(): boolean;
  /** The basemap's land polygons in the loaded tiles, as [lon, lat] rings, for clipping an overlay. */
  land(): number[][][];
  /** `idle`: the map has settled and drawn every tile in view. */
  on(type: 'movestart' | 'idle' | 'resize', listener: () => void): () => void;
}

/** A registry layer's sources and MapLibre layers added after the style (FE-22's cloud frames). */
export interface Overlay {
  readonly sources: Readonly<Record<string, MapLibre.SourceSpecification>>;
  readonly layers: readonly MapLibre.LayerSpecification[];
  /** RF1935-3: the first source error removes this overlay's layers and sources and is reported once; nothing re-adds the same object. */
  readonly stopOnError?: boolean;
}

export interface Engine {
  setCamera(camera: EngineCamera): void;
  /** Show or hide a style layer; before the style has loaded, the latest call per layer waits for it. */
  setVisible(layerId: string, visible: boolean): void;
  /** Replace a GeoJSON source's data; before the style has loaded, the latest data per source waits for it. */
  setData(sourceId: string, data: SourceData): void;
  /** How many features of `layerId` are drawn in view now (labels count once placed). */
  rendered(layerId: string): number;
  readonly view: MapView;
  /**
   * Draw registry layer `layer`'s overlay under map layer `before`, or under the first drawn layer of
   * a list (on top when none is); null removes it. Ids already drawn stay as they are, tiles included;
   * ids no longer listed are removed. Errors on its sources mark `layer` unavailable. Before the style
   * has loaded, the latest overlay per layer waits for it.
   */
  setOverlay(layer: string, overlay: Overlay | null, before?: string | readonly string[]): void;
  /** A raster layer's opacity (FE-22 shows one cloud frame at a time; the others keep loading); before the style has loaded, the latest call per layer waits for it. */
  setRasterOpacity(layerId: string, opacity: number): void;
  /**
   * Replace an overlay's image source with `texture` and its corners (FE-16's water temperature): the
   * pixels go straight to MapLibre, with no request. Before the style has loaded, the latest per source waits for it.
   */
  setImage(sourceId: string, texture: FieldTexture): void;
  /**
   * Fly `legs` in order around the current centre and zoom (#646), then call `done(true)`. Any input on the
   * host, setCamera, stopFlyover or destroy stops it early (`done(false)`); either way the Chart ends north up
   * and flat, with gestures still unable to tilt or turn it.
   */
  flyover(legs: readonly FlyLeg[], done?: (finished: boolean) => void): void;
  stopFlyover(): void;
  /** MapLibre's padding (RF0905-1: the phone's open band); the centre stays put. A library without setPadding ignores it. */
  setPadding(p: {top: number; bottom: number; left: number; right: number}): void;
  destroy(): void;
}

const prepared = new WeakSet<object>();
/** Registers the worker URL, the pmtiles:// and the Clouds frame protocols once per library instance. */
export function prepareLibrary(module: MapLibraryModule): void {
  if (prepared.has(module.lib)) return;
  module.lib.setWorkerUrl(module.workerUrl);
  module.lib.addProtocol('pmtiles', new module.Protocol().tile);
  module.lib.addProtocol(FRAME_PROTOCOL, frameProtocol());
  prepared.add(module.lib);
}

/** Folds a compact attribution that MapLibre opened (BL-SC-1): the credits stay in the DOM behind its toggle. A no-op when collapsed or expanded. */
export function collapseAttribution(container: Element): void {
  if (container.classList.contains('maplibregl-compact-show')) { container.classList.remove('maplibregl-compact-show'); container.removeAttribute('open'); }
}

/** The Map constructor's options: north up, no pitch, `?view=` zoom range, the stage's own accessible name; a still map takes no input. */
export function mapOptions(host: HTMLElement, style: MapLibre.StyleSpecification, camera: EngineCamera, still = false): MapLibre.MapOptions {
  return {
    ...still ? {interactive: false, fadeDuration: 0} : {},
    container: host, style,
    center: [camera.longitude, camera.latitude], zoom: camera.zoom - ZOOM_OFFSET,
    minZoom: VIEW_ZOOM.min - ZOOM_OFFSET, maxZoom: VIEW_ZOOM.max - ZOOM_OFFSET,
    dragRotate: false, pitchWithRotate: false, touchPitch: false, rollEnabled: false, maxPitch: 0,
    // The host follows its own size (a ResizeObserver), including when the stage shows it again.
    trackResize: false, attributionControl: false, renderWorldCopies: false,
    locale: {'Map.Title': 'Chart'},
  };
}

export function createEngine(module: MapLibraryModule, options: EngineOptions): Engine {
  prepareLibrary(module);
  const {lib} = module, {host} = options;
  const map = new lib.Map(mapOptions(host, options.style, options.camera, options.still));
  map.keyboard.disableRotation();
  map.touchZoomRotate.disableRotation();
  if (!options.still) {
    map.addControl(new lib.NavigationControl({showCompass: false}), 'bottom-right');
    map.addControl(new lib.ScaleControl({unit: 'nautical', maxWidth: 120}), 'bottom-right');
    // BL-SC-1: MapLibre's own rule makes the credits compact at ≤ 640 px; it opens them whenever they turn compact, so fold them once then.
    const attribution = new lib.AttributionControl(options.attribution ? {customAttribution: options.attribution} : {});
    map.addControl(attribution, 'bottom-right');
    let wasCompact = false;
    const fold = () => { const el = attribution._container; if (el && !wasCompact) collapseAttribution(el); wasCompact = !!el?.classList.contains('maplibregl-compact'); };
    fold();
    for (const type of ['resize', 'styledata', 'sourcedata'] as const) map.on(type, fold);
  }

  // The overlays drawn now, by registry layer (FE-22), so their source errors route to that layer.
  const overlays = new Map<string, Overlay>();
  const overlayOf = (sourceId: string | undefined): string | null =>
    sourceId === undefined ? null : [...overlays].find(([, o]) => sourceId in o.sources)?.[0] ?? null;

  // RF1935-3: overlays that failed (stopOnError) are detached for good; their source ids stay known so late errors are dropped.
  const failed = new WeakSet<Overlay>();
  const retired = new Set<string>();
  let destroyed = false;
  // Declared below with the other overlay helpers; hoisted function so the error handler can use it.
  function retire(layer: string, overlay: Overlay): void {
    failed.add(overlay);
    for (const l of overlay.layers) if (map.getLayer(l.id)) map.removeLayer(l.id);
    for (const id of Object.keys(overlay.sources)) { if (map.getSource(id)) map.removeSource(id); retired.add(id); }
    overlays.delete(layer);
  }

  map.on('error', (event: MapLibre.ErrorEvent & {sourceId?: string}) => {
    if (destroyed) return;
    const own = overlayOf(event.sourceId);
    if (own === null && event.sourceId !== undefined && retired.has(event.sourceId)) return;
    const stop = own === null ? undefined : overlays.get(own);
    if (own !== null && stop?.stopOnError) { retire(own, stop); options.onLayerError(own, event.error); return; }
    const layer = own ?? sourceLayer(event.sourceId);
    if (layer) options.onLayerError(layer, event.error);
    else console.error('Chart error', event.error);
  });
  // Metadata, idle and errored tiles are not recovery. Keep the request's actual
  // source object and context so late events cannot recover a replacement view.
  const tileRequests = new WeakMap<object, {id: string; source: unknown; context: unknown}>();
  map.on('sourcedataloading', event => {
    if (!options.onSourceTileLoaded || !event.tile || typeof event.tile !== 'object') return;
    const source = map.getSource(event.sourceId);
    if (source) tileRequests.set(event.tile, {id: event.sourceId, source, context: options.sourceContext?.()});
  });
  map.on('sourcedata', event => {
    if (!event.tile || typeof event.tile !== 'object') return;
    const request = tileRequests.get(event.tile);
    tileRequests.delete(event.tile);
    if (request && event.tile.state === 'loaded' && request.id === event.sourceId &&
        request.source === map.getSource(event.sourceId) && request.context === options.sourceContext?.()) {
      options.onSourceTileLoaded?.(event.sourceId);
    }
  });
  map.on('moveend', () => {
    const c = map.getCenter();
    options.onMove({latitude: c.lat, longitude: c.lng, zoom: map.getZoom() + ZOOM_OFFSET});
  });
  // RF2205-5: a click settles for PICK_SETTLE_MS before it picks, so a double-tap zoom never selects the mark under the finger.
  // dblclick, zoomstart and movestart (native touch zoom may fire no dblclick) drop the pending pick; clicks during a camera gesture are ignored until moveend.
  let cancelPick = (): void => {};
  let moving = false;
  if (options.onPick) {
    const pick = options.onPick;
    let timer: ReturnType<typeof setTimeout> | undefined;
    cancelPick = () => { clearTimeout(timer); timer = undefined; };
    const gestureStart = (): void => { moving = true; cancelPick(); };
    map.on('dblclick', cancelPick);
    map.on('zoomstart', gestureStart);
    map.on('movestart', gestureStart);
    map.on('moveend', () => { moving = false; });
    map.on('click', (event: MapLibre.MapMouseEvent) => {
      cancelPick();
      if (moving || destroyed) return;
      const query = (ids: readonly string[]) => { const layers = ids.filter(id => map.getLayer(id)); return layers.length ? map.queryRenderedFeatures(event.point, {layers})[0] : undefined; };
      const feature = query(options.pickFirst?.() ?? []) ?? query(options.pickLayers ?? []);
      const layer = feature?.layer.id ?? null, properties = feature ? feature.properties as Record<string, unknown> : null;
      const at = event.lngLat ? {lon: event.lngLat.lng, lat: event.lngLat.lat} : null;
      // A pickContext that answers null means picking is closed (Chart hidden, or not the shown view): it never accepts a pick, at the click or at dispatch.
      const gated = !!options.pickContext, context = options.pickContext?.();
      if (gated && context === null) return;
      timer = setTimeout(() => {
        timer = undefined;
        const now = options.pickContext?.();
        if (destroyed || moving || (gated && now === null) || now !== context) return;
        pick(layer, properties, at);
      }, PICK_SETTLE_MS);
    });
  }
  if (options.onIdle) map.on('idle', options.onIdle);
  const resize = typeof ResizeObserver === 'function' ? new ResizeObserver(() => map.resize()) : null;
  resize?.observe(host);
  // The style gate (FE-14), this file's one deferral: a style's layers and sources exist only
  // once MapLibre fires `style.load`. Until then setVisible keeps the latest visibility per
  // layer, setData the latest data per source, setOverlay the latest overlay per registry layer
  // (MapLibre refuses run-time sources and layers earlier), setRasterOpacity the latest
  // opacity per layer and setImage the latest texture per image source; all apply once when it
  // fires, overlays first so the others find their layers and sources. Afterwards (or for a
  // layer or source that already exists) every call applies at once. Layers route their
  // visibility, data and overlays through these calls rather than adding a deferral.
  let early: {
    visible: Map<string, boolean>; data: Map<string, SourceData>;
    overlays: Map<string, {overlay: Overlay | null; before?: string | readonly string[]}>; opacity: Map<string, number>; images: Map<string, FieldTexture>;
  } | null = {visible: new Map(), data: new Map(), overlays: new Map(), opacity: new Map(), images: new Map()};
  const show = (layerId: string, visible: boolean): void => { if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none'); };
  const fill = (sourceId: string, data: SourceData): void => { (map.getSource(sourceId) as MapLibre.GeoJSONSource | undefined)?.setData(data); };
  const draw = (layer: string, overlay: Overlay | null, before?: string | readonly string[]): void => {
    if (overlay && failed.has(overlay)) return;
    for (const id of Object.keys(overlay?.sources ?? {})) retired.delete(id);
    const old = overlays.get(layer), next = overlay ?? {sources: {}, layers: []};
    for (const l of old?.layers ?? []) if (!next.layers.some(n => n.id === l.id) && map.getLayer(l.id)) map.removeLayer(l.id);
    for (const id of Object.keys(old?.sources ?? {})) if (!(id in next.sources) && map.getSource(id)) map.removeSource(id);
    for (const [id, source] of Object.entries(next.sources)) if (!map.getSource(id)) map.addSource(id, source);
    const under = ([] as string[]).concat(before ?? []).find(id => map.getLayer(id));
    for (const l of next.layers) if (!map.getLayer(l.id)) map.addLayer(l, under);
    if (overlay) overlays.set(layer, overlay); else overlays.delete(layer);
  };
  const fade = (layerId: string, opacity: number): void => { if (map.getLayer(layerId)) map.setPaintProperty(layerId, 'raster-opacity', opacity); };
  const paint = (sourceId: string, t: FieldTexture): void => {
    const image = typeof ImageData === 'function' ? new ImageData(t.data, t.width, t.height) : t as unknown as ImageData;
    (map.getSource(sourceId) as MapLibre.ImageSource | undefined)?.updateImage({image, coordinates: t.coordinates});
  };
  map.on('style.load', () => {
    const pending = early;
    early = null;
    pending?.overlays.forEach(({overlay, before}, layer) => draw(layer, overlay, before));
    pending?.visible.forEach((visible, layerId) => show(layerId, visible));
    pending?.data.forEach((data, sourceId) => fill(sourceId, data));
    pending?.opacity.forEach((opacity, layerId) => fade(layerId, opacity));
    pending?.images.forEach((texture, sourceId) => paint(sourceId, texture));
  });

  // The flyover (#646): max pitch rises only while it flies; each leg starts at the last one's moveend.
  let flight: (() => void) | null = null;
  const smooth = (t: number): number => t * t * (3 - 2 * t);
  function flyover(legs: readonly FlyLeg[], done?: (finished: boolean) => void): void {
    flight?.();
    const center = map.getCenter(), zoom = map.getZoom();
    let next = 0, over = false;
    const finish = (finished: boolean): void => {
      if (over) return;
      over = true; flight = null;
      map.off('moveend', step);
      for (const type of FLY_STOPPERS) host.removeEventListener?.(type, stop, true);
      if (!finished) map.stop();
      if (map.getPitch() || map.getBearing()) map.jumpTo({bearing: 0, pitch: 0});
      map.setMaxPitch(0);
      done?.(finished);
    };
    const stop = (): void => finish(false);
    function step(): void {
      if (over) return;
      const leg = legs[next++];
      if (!leg) { finish(true); return; }
      map.easeTo({center, zoom, pitch: leg.pitch, bearing: leg.bearing, duration: leg.duration, easing: smooth});
    }
    flight = stop;
    map.setMaxPitch(Math.max(0, ...legs.map(l => l.pitch)));
    for (const type of FLY_STOPPERS) host.addEventListener?.(type, stop, {capture: true, passive: true});
    map.on('moveend', step);
    step();
  }

  return {
    flyover,
    stopFlyover() { flight?.(); },
    setPadding(p) { if (typeof map.setPadding === 'function') map.setPadding(p); },
    setCamera(c) { flight?.(); cancelPick(); map.jumpTo({center: [c.longitude, c.latitude], zoom: c.zoom - ZOOM_OFFSET}); },
    setVisible(layerId, visible) {
      if (early && !map.getLayer(layerId)) early.visible.set(layerId, visible);
      else { early?.visible.delete(layerId); show(layerId, visible); }
    },
    setData(sourceId, data) {
      if (early && !map.getSource(sourceId)) early.data.set(sourceId, data);
      else { early?.data.delete(sourceId); fill(sourceId, data); }
    },
    rendered: layerId => map.getLayer(layerId) ? map.queryRenderedFeatures({layers: [layerId]}).length : 0,
    view: {
      container: () => map.getCanvasContainer(),
      size: () => ({width: host.clientWidth, height: host.clientHeight}),
      project: (lon, lat) => map.project([lon, lat]),
      unproject: (x, y) => { const p = map.unproject([x, y]); return {lon: p.lng, lat: p.lat}; },
      busy: () => map.isMoving() || !map.loaded(),
      land: () => map.getSource(BASEMAP_SOURCE) ? map.querySourceFeatures(BASEMAP_SOURCE, {sourceLayer: 'earth'}).flatMap(f =>
        f.geometry.type === 'Polygon' ? f.geometry.coordinates : f.geometry.type === 'MultiPolygon' ? f.geometry.coordinates.flat() : []) : [],
      on: (type, listener) => { map.on(type, listener); return () => { map.off(type, listener); }; },
    },
    setOverlay(layer, overlay, before) {
      if (early) early.overlays.set(layer, {overlay, before});
      else draw(layer, overlay, before);
    },
    setRasterOpacity(layerId, opacity) {
      if (early && !map.getLayer(layerId)) early.opacity.set(layerId, opacity);
      else { early?.opacity.delete(layerId); fade(layerId, opacity); }
    },
    setImage(sourceId, texture) {
      if (early && !map.getSource(sourceId)) early.images.set(sourceId, texture);
      else { early?.images.delete(sourceId); paint(sourceId, texture); }
    },
    destroy() { destroyed = true; cancelPick(); retired.clear(); flight?.(); resize?.disconnect(); map.remove(); },
  };
}

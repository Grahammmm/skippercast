// MapLibre init for the Chart presentation (FE-11, docs/plans/front-end/design.md
// § 3, § 3A.2): the PMTiles protocol and the worker URL registered once, a
// north-up map (no rotation or pitch by any gesture or key), a nautical scale,
// zoom buttons, the attribution control, resize with its host, and error
// routing: a failing source marks only the registry layer that owns it
// (web/map/layers.ts), so one broken feed never blanks the chart.
//
// The library is passed in (web/map/maplibre.js loads it by dynamic import), so
// this file never imports MapLibre at run time and tests/test_map_layers.mjs
// drives it with a fake map. Erasable syntax only.
import type * as MapLibre from 'maplibre-gl';
import {sourceLayer} from './layers.ts';
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
  /** A click: the first feature under it in `pickLayers`, or null for empty water, and where it fell. */
  onPick?(layer: string | null, properties: Record<string, unknown> | null, at: {lon: number; lat: number} | null): void;
  pickLayers?: readonly string[];
  /** Credit always shown (the basemap's): MapLibre lists a tiled source's own credit only if it was drawn when its metadata arrived. */
  attribution?: string;
  /** The map has settled and drawn every tile in view (MapLibre `idle`). */
  onIdle?(): void;
}

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

export interface Engine {
  setCamera(camera: EngineCamera): void;
  /** Show or hide a style layer; before the style has loaded, the latest call per layer waits for it. */
  setVisible(layerId: string, visible: boolean): void;
  /** Replace a GeoJSON source's data; before the style has loaded, the latest data per source waits for it. */
  setData(sourceId: string, data: SourceData): void;
  /** How many features of `layerId` are drawn in view now (labels count once placed). */
  rendered(layerId: string): number;
  readonly view: MapView;
  destroy(): void;
}

const prepared = new WeakSet<object>();
/** Registers the worker URL and the pmtiles:// protocol once per library instance. */
export function prepareLibrary(module: MapLibraryModule): void {
  if (prepared.has(module.lib)) return;
  module.lib.setWorkerUrl(module.workerUrl);
  module.lib.addProtocol('pmtiles', new module.Protocol().tile);
  prepared.add(module.lib);
}

/** The Map constructor's options: north up, no pitch, `?view=` zoom range, the stage's own accessible name. */
export function mapOptions(host: HTMLElement, style: MapLibre.StyleSpecification, camera: EngineCamera): MapLibre.MapOptions {
  return {
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
  const map = new lib.Map(mapOptions(host, options.style, options.camera));
  map.keyboard.disableRotation();
  map.touchZoomRotate.disableRotation();
  map.addControl(new lib.NavigationControl({showCompass: false}), 'bottom-right');
  map.addControl(new lib.ScaleControl({unit: 'nautical', maxWidth: 120}), 'bottom-right');
  map.addControl(new lib.AttributionControl({compact: false, ...options.attribution ? {customAttribution: options.attribution} : {}}), 'bottom-right');

  map.on('error', (event: MapLibre.ErrorEvent & {sourceId?: string}) => {
    const layer = sourceLayer(event.sourceId);
    if (layer) options.onLayerError(layer, event.error);
    else console.error('Chart error', event.error);
  });
  map.on('moveend', () => {
    const c = map.getCenter();
    options.onMove({latitude: c.lat, longitude: c.lng, zoom: map.getZoom() + ZOOM_OFFSET});
  });
  if (options.onPick) {
    const pick = options.onPick;
    map.on('click', (event: MapLibre.MapMouseEvent) => {
      const layers = (options.pickLayers ?? []).filter(id => map.getLayer(id));
      const feature = layers.length ? map.queryRenderedFeatures(event.point, {layers})[0] : undefined;
      pick(feature?.layer.id ?? null, feature ? feature.properties as Record<string, unknown> : null, event.lngLat ? {lon: event.lngLat.lng, lat: event.lngLat.lat} : null);
    });
  }
  if (options.onIdle) map.on('idle', options.onIdle);
  const resize = typeof ResizeObserver === 'function' ? new ResizeObserver(() => map.resize()) : null;
  resize?.observe(host);
  // The style gate (FE-14), this file's one deferral: a style's layers and sources exist only
  // once MapLibre fires `style.load`. Until then setVisible keeps the latest visibility per
  // layer and setData the latest data per source; both apply once when it fires. Afterwards
  // (or for a layer or source that already exists) every call applies at once. Layers route
  // their visibility and data through setVisible and setData rather than adding a deferral.
  let early: {visible: Map<string, boolean>; data: Map<string, SourceData>} | null = {visible: new Map(), data: new Map()};
  const show = (layerId: string, visible: boolean): void => { if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none'); };
  const fill = (sourceId: string, data: SourceData): void => { (map.getSource(sourceId) as MapLibre.GeoJSONSource | undefined)?.setData(data); };
  map.on('style.load', () => {
    const pending = early;
    early = null;
    pending?.visible.forEach((visible, layerId) => show(layerId, visible));
    pending?.data.forEach((data, sourceId) => fill(sourceId, data));
  });

  return {
    setCamera(c) { map.jumpTo({center: [c.longitude, c.latitude], zoom: c.zoom - ZOOM_OFFSET}); },
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
    destroy() { resize?.disconnect(); map.remove(); },
  };
}

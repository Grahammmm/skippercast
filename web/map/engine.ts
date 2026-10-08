// MapLibre init for the Chart presentation (FE-11, docs/plans/front-end/design.md
// § 3, § 3A.2): the PMTiles protocol and the CSP worker registered once, a
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

/** What web/map/maplibre.js provides: the CSP build, its worker's URL and the PMTiles protocol. */
export interface MapLibraryModule {
  readonly lib: Pick<typeof MapLibre, 'Map' | 'NavigationControl' | 'ScaleControl' | 'AttributionControl' | 'setWorkerUrl' | 'addProtocol'>;
  readonly workerUrl: string;
  readonly Protocol: new () => {tile: MapLibre.AddProtocolAction};
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
  /** A click: the first feature under it in `pickLayers`, or null for empty water. */
  onPick?(layer: string | null, properties: Record<string, unknown> | null): void;
  pickLayers?: readonly string[];
  /** Credit always shown (the basemap's): MapLibre lists a tiled source's own credit only if it was drawn when its metadata arrived. */
  attribution?: string;
}

export interface Engine {
  setCamera(camera: EngineCamera): void;
  setVisible(layerId: string, visible: boolean): void;
  setData(sourceId: string, data: string): void;
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
      pick(feature?.layer.id ?? null, feature ? feature.properties as Record<string, unknown> : null);
    });
  }
  const resize = typeof ResizeObserver === 'function' ? new ResizeObserver(() => map.resize()) : null;
  resize?.observe(host);

  return {
    setCamera(c) { map.jumpTo({center: [c.longitude, c.latitude], zoom: c.zoom - ZOOM_OFFSET}); },
    setVisible(layerId, visible) { if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none'); },
    setData(sourceId, data) { (map.getSource(sourceId) as MapLibre.GeoJSONSource | undefined)?.setData(data); },
    destroy() { resize?.disconnect(); map.remove(); },
  };
}

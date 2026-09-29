// MapLibre GL 5 + PMTiles test of one layer: Morro Bay reef outlines as vector
// tiles, read by HTTP range from /feeds/tiles/ (R2 when connected, the site's
// own files until then). Compare with map-test-leaflet.html (today's approach).
import {VIEW, LAYER, NOAA_WMS, OSM_TILES, REEF_STYLE, reefLabel} from './map-test-common.js';

const params = new URLSearchParams(location.search);
// MapLibre zoom levels use 512 px tiles: its zoom z shows what Leaflet shows at z + 1.
// Zoom numbers in the URL and the test hooks are Leaflet-equivalent, so both pages match.
const toML = z => z - 1, fromML = z => z + 1;
const started = performance.now();
// CSP-safe build: the worker is a same-origin file, never a blob.
maplibregl.setWorkerUrl(new URL('vendor/maplibre-5.24.0/maplibre-gl-csp-worker.js', location.href).href);
const protocol = new pmtiles.Protocol();
maplibregl.addProtocol('pmtiles', protocol.tile);

const map = new maplibregl.Map({
  container: 'map',
  center: [VIEW.longitude, VIEW.latitude],
  zoom: toML(Number(params.get('z') || VIEW.zoom)),
  minZoom: toML(7), maxZoom: toML(18),
  attributionControl: {compact: true},
  style: {
    version: 8,
    sources: {
      osm: {type: 'raster', tiles: [OSM_TILES], tileSize: 256, maxzoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'},
      chart: {type: 'raster', tiles: [NOAA_WMS + '&bbox={bbox-epsg-3857}'], tileSize: 512, minzoom: toML(10), maxzoom: 18,
        attribution: '<a href="https://www.nauticalcharts.noaa.gov/data/gis-data-and-services.html">NOAA ENC display</a> · planning only'},
      reefs: {type: 'vector', url: 'pmtiles://' + new URL(LAYER.tiles, location.href).href, attribution: LAYER.attribution},
    },
    layers: [
      {id: 'osm', type: 'raster', source: 'osm'},
      {id: 'chart', type: 'raster', source: 'chart', minzoom: toML(10)},
      {id: 'reef-fill', type: 'fill', source: 'reefs', 'source-layer': 'reefs',
        paint: {'fill-color': REEF_STYLE.fillColor, 'fill-opacity': REEF_STYLE.fillOpacity}},
      {id: 'reef-line', type: 'line', source: 'reefs', 'source-layer': 'reefs',
        paint: {'line-color': REEF_STYLE.color, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.6, 12, REEF_STYLE.weight, 15, 2.4]}},
    ],
  },
});
map.addControl(new maplibregl.NavigationControl({showCompass: false}), 'bottom-right');
map.on('error', event => console.error('Map error:', event.error?.message || event));

map.on('click', 'reef-fill', event => {
  const feature = event.features?.[0];
  if (!feature) return;
  const html = document.createElement('div');
  html.className = 'reef-popup';
  html.textContent = reefLabel(feature.properties);
  new maplibregl.Popup({closeButton: true}).setLngLat(event.lngLat).setDOMContent(html).addTo(map);
});
map.on('mouseenter', 'reef-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
map.on('mouseleave', 'reef-fill', () => { map.getCanvas().style.cursor = ''; });

window.__maplibre = map;  // for inspection in tests
// Measurement hooks for research/scripts/measure_map_test.mjs.
map.once('idle', () => {
  window.__mapTest = {engine: 'maplibre', readyMs: Math.round(performance.now() - started),
    reefs: map.queryRenderedFeatures({layers: ['reef-fill']}).length};
});
window.__map = {
  jumpTo: (lng, lat, zoom) => map.jumpTo({center: [lng ?? VIEW.longitude, lat ?? VIEW.latitude], zoom: toML(zoom)}),
  panBy: (x, y) => map.panBy([x, y], {animate: false}),
  zoom: () => fromML(map.getZoom()),
  rendered: () => map.queryRenderedFeatures({layers: ['reef-fill']}).length,
  idle: () => new Promise(resolve => (map.loaded() && map.areTilesLoaded() ? resolve() : map.once('idle', resolve))),
};

// Leaflet baseline: the same reef outlines drawn the way the app does today,
// by downloading the whole atlas GeoJSON and adding every polygon to the map.
import {VIEW, LAYER, NOAA_WMS, OSM_TILES, REEF_STYLE, reefLabel} from './map-test-common.js';

const params = new URLSearchParams(location.search);
const started = performance.now();
await new Promise(resolve => (window.L ? resolve() : addEventListener('DOMContentLoaded', resolve)));
const map = L.map('map', {zoomControl: false, minZoom: 7, maxZoom: 18})
  .setView([VIEW.latitude, VIEW.longitude], Number(params.get('z') || VIEW.zoom));
L.control.zoom({position: 'bottomright'}).addTo(map);
L.tileLayer(OSM_TILES, {maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(map);
const [wmsBase, wmsQuery] = NOAA_WMS.split('?');
const wms = Object.fromEntries(new URLSearchParams(wmsQuery));
const chart = L.tileLayer.wms(wmsBase, {layers: wms.layers, format: 'image/png', transparent: false, version: '1.3.0', tileSize: 512, maxZoom: 18,
  attribution: '<a href="https://www.nauticalcharts.noaa.gov/data/gis-data-and-services.html">NOAA ENC display</a> · planning only'});
const syncChart = () => (map.getZoom() >= 10 ? chart.addTo(map) : map.removeLayer(chart));
map.on('zoomend', syncChart); syncChart();

const features = LAYER.features(await (await fetch(LAYER.geojson)).json());
const reefs = L.layerGroup().addTo(map);
const shapes = features.map(feature => L.geoJSON(feature, {style: {...REEF_STYLE}})
  .bindTooltip(reefLabel(feature.properties)).addTo(reefs));
const inView = () => shapes.filter(shape => map.getBounds().intersects(shape.getBounds())).length;
window.__mapTest = {engine: 'leaflet', readyMs: Math.round(performance.now() - started), reefs: inView()};
window.__map = {
  jumpTo: (lng, lat, zoom) => map.setView([lat ?? VIEW.latitude, lng ?? VIEW.longitude], zoom, {animate: false}),
  panBy: (x, y) => map.panBy([x, y], {animate: false}),
  zoom: () => map.getZoom(),
  rendered: inView,
  idle: () => new Promise(resolve => setTimeout(resolve, 50)),
};

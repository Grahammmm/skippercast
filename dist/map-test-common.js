// Shared settings for the map-engine test pages, so both draw the same view,
// base layers and reef style.
// ?layer=socal switches both pages to the densest layer in the app.
export const LAYERS = {
  morro: {view: {latitude: 35.34, longitude: -120.965, zoom: 12}, tiles: '/feeds/tiles/morro-bay-reef-outlines.pmtiles',
    geojson: 'data/atlas.json', features: data => data.areas.map(a => ({type: 'Feature', geometry: a.geometry, properties: {id: a.id, area_ha: a.area_ha}})),
    attribution: 'Reef outlines: USGS CSMP via SkipperCast (research-only)'},
  socal: {view: {latitude: 34.0, longitude: -119.55, zoom: 11}, tiles: '/feeds/tiles/socal-survey-habitat.pmtiles',
    geojson: 'regions/southern-california/survey-habitat.geojson', features: data => data.features,
    attribution: 'Survey habitat: NOAA / USGS via SkipperCast (research-only)'},
};
export const LAYER = LAYERS[new URLSearchParams(location.search).get('layer')] || LAYERS.morro;
export const VIEW = LAYER.view;
export const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
export const NOAA_WMS = 'https://gis.charttools.noaa.gov/arcgis/rest/services/MCS/NOAAChartDisplay/MapServer/exts/MaritimeChartService/WMSServer'
  + '?service=WMS&request=GetMap&version=1.3.0&layers=0,1,2,6&styles=&format=image/png&transparent=false&crs=EPSG:3857&width=512&height=512';
export const REEF_STYLE = {color: '#007f73', weight: 1.5, fillColor: '#19bca9', fillOpacity: 0.18};

export function reefLabel(p) {
  if (p.name) return `${p.name} · ${p.habitat_kind || 'habitat'} · research-only`;
  const area = Number(p.area_ha);
  return `${p.id} · ${Number.isFinite(area) ? area.toFixed(1) : '?'} ha partial reef footprint · research-only`;
}

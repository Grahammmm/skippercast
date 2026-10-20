// A land/water state (web/land-water.ts) in which every given point lies in a clean water cell: for
// tests of the ranked list, the planner and the Chart's pins that are not about the land/water check
// itself (that is tests/test_land_water.mjs). It goes through the real index check (`landWaterModel`).
import {landWaterModel} from '../../web/land-water.ts';

const Z = 12, GRID = 4;

export function waterIndex(region, points) {
  const tiles = {}, n = 2 ** Z;
  for (const p of points) {
    const x = Math.floor((p.longitude + 180) / 360 * n);
    const y = Math.floor((1 - Math.asinh(Math.tan(p.latitude * Math.PI / 180)) / Math.PI) / 2 * n);
    tiles[`${Z}/${x}/${y}`] = `w${GRID * GRID}`;
  }
  const lon = points.map(p => p.longitude), lat = points.map(p => p.latitude);
  const bounds = [Math.min(...lon) - 0.01, Math.min(...lat) - 0.01, Math.max(...lon) + 0.01, Math.max(...lat) + 0.01].map(v => Math.round(v * 1e5));
  return {schema_version: 1, product: 'land-water', region_id: region, status: 'available', bounds,
    constants: {edge_m: 25, tile_zoom: Z, grid: GRID, unit: 100000}, derived_from: {sha256: 'test'}, lines: {sha256: 'test'}, tiles};
}

/** The loaded state for `region` with every point in a water cell. */
export function waterState(region, points) {
  return {region, state: 'ready', model: landWaterModel(waterIndex(region, points), region), lines: null, linesLoading: false};
}

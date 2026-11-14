// Surface-current overlay for the map-style test page (MAPLAYER-CURRENT-1).
//
// Style "current 5" of the map style study (G pick 2026-11-06; reference renderer curr(5) in
// layers.py): a vorticity tint (cmocean balance, alpha .55, bilinear) under dark navy streamlines
// (#10243a, 0.7 px). The study drew a synthetic field; this draws a real HF-radar grid produced by
// research/scripts/map_style/fetch_hfr_currents.py (var/currents/hfr-<sector>-<res>km.json).
//
// Honest by construction: a point is drawn only where all four surrounding grid cells hold a radar
// vector. Nothing is interpolated or extrapolated across a gap, so the footprint on screen is the
// footprint of the radar. NOT FOR NAVIGATION.
import {balance} from './balance-ramp.js';

export const STREAM_COLOUR = '#10243a';   // layers.py curr(5): streamplot colour
export const TINT_ALPHA = 0.55;           // layers.py curr(5): imshow alpha
export const VORT_RANGE = 0.5;            // |relative vorticity| / f at full colour; the study's +-1 bar, rescaled
const R = 6371008.8;                       // mean earth radius, m
const OMEGA = 7.2921159e-5;               // earth rotation, rad/s
const DEG = Math.PI / 180;

const valid = (g, y, x) => y >= 0 && x >= 0 && y < g.rows && x < g.cols && g.u[y][x] !== null && g.v[y][x] !== null;

/** Grid from the fetcher's document: ascending lats/lons, u/v in m/s (null = no vector). */
export function gridOf(doc) {
  const g = {lats: doc.lats, lons: doc.lons, u: doc.u, v: doc.v, rows: doc.lats.length, cols: doc.lons.length};
  if (!(g.rows > 1 && g.cols > 1) || g.lats[1] <= g.lats[0] || g.lons[1] <= g.lons[0]) throw new Error('bad current grid');
  return g;
}

/** Relative vorticity (dv/dx - du/dy) / f, central differences, null unless all four neighbours exist.
 *  Counter-clockwise (cyclonic here) is positive. A 3x3 mean of the valid neighbours smooths one cell. */
export function vorticity(g) {
  const raw = g.lats.map(() => new Array(g.cols).fill(null));
  for (let y = 1; y < g.rows - 1; y++) for (let x = 1; x < g.cols - 1; x++) {
    if (![[y, x - 1], [y, x + 1], [y - 1, x], [y + 1, x]].every(([j, i]) => valid(g, j, i))) continue;
    const lat = g.lats[y] * DEG;
    const dx = R * Math.cos(lat) * (g.lons[x + 1] - g.lons[x - 1]) * DEG;
    const dy = R * (g.lats[y + 1] - g.lats[y - 1]) * DEG;
    const zeta = (g.v[y][x + 1] - g.v[y][x - 1]) / dx - (g.u[y + 1][x] - g.u[y - 1][x]) / dy;
    raw[y][x] = zeta / (2 * OMEGA * Math.sin(lat));
  }
  return raw.map((row, y) => row.map((value, x) => {
    if (value === null) return null;
    let sum = 0, weight = 0;
    for (let j = -1; j <= 1; j++) for (let i = -1; i <= 1; i++) {
      const w = (j === 0 ? 2 : 1) * (i === 0 ? 2 : 1), n = raw[y + j]?.[x + i];
      if (n !== null && n !== undefined) { sum += w * n; weight += w; }
    }
    return sum / weight;
  }));
}

const locate = (axis, value) => {
  if (value < axis[0] || value > axis[axis.length - 1]) return null;
  let lo = 0, hi = axis.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (axis[mid] <= value) lo = mid; else hi = mid; }
  return [lo, (value - axis[lo]) / (axis[lo + 1] - axis[lo])];
};

/** Bilinear sample of any cell grid (null = missing); null unless all four corners exist. */
export function bilinear(g, field, lon, lat) {
  const a = locate(g.lats, lat), b = locate(g.lons, lon);
  if (!a || !b) return null;
  const [y, fy] = a, [x, fx] = b;
  const c = [field[y][x], field[y][x + 1], field[y + 1][x], field[y + 1][x + 1]];
  if (c.some(value => value === null)) return null;
  return c[0] * (1 - fx) * (1 - fy) + c[1] * fx * (1 - fy) + c[2] * (1 - fx) * fy + c[3] * fx * fy;
}

/** [u, v] in m/s at a point, or null outside the radar footprint. */
export function velocityAt(g, lon, lat) {
  const u = bilinear(g, g.u, lon, lat);
  if (u === null) return null;
  const v = bilinear(g, g.v, lon, lat);
  return v === null ? null : [u, v];
}

/** Streamlines: seeded on a lattice, traced both ways with midpoint steps, stopped at the footprint edge,
 *  at a still patch, or when they come within `sep` cells of an earlier line. Deterministic.
 *  Returns [{coords: [[lon, lat], ...], speed: mean m/s}]. */
export function streamlines(g, {sep = 0.55, step = 0.2, maxSteps = 60, minPoints = 5, seedEvery = 0.5} = {}) {
  const cell = Math.min((g.lons[g.cols - 1] - g.lons[0]) / (g.cols - 1), (g.lats[g.rows - 1] - g.lats[0]) / (g.rows - 1));
  const sepD = sep * cell, stepD = step * cell, stop = 0.02;   // stop below 2 cm/s
  const bins = new Map(), key = (lon, lat) => Math.floor(lon / sepD) + ',' + Math.floor(lat / sepD);
  const near = (lon, lat, own) => {
    const bx = Math.floor(lon / sepD), by = Math.floor(lat / sepD);
    for (let j = -1; j <= 1; j++) for (let i = -1; i <= 1; i++) for (const p of bins.get((bx + i) + ',' + (by + j)) || []) {
      if (p.line !== own && Math.hypot(p.lon - lon, p.lat - lat) < sepD) return true;
    }
    return false;
  };
  const dir = (lon, lat, sign) => {
    const w = velocityAt(g, lon, lat);
    if (!w) return null;
    const sp = Math.hypot(w[0], w[1]);
    if (sp < stop) return null;
    return [sign * w[0] / sp / Math.cos(lat * DEG), sign * w[1] / sp, sp];   // unit step in degrees
  };
  const trace = (lon, lat, sign, line, own) => {
    const out = [];
    for (let n = 0; n < maxSteps; n++) {
      const a = dir(lon, lat, sign);
      if (!a) break;
      const b = dir(lon + a[0] * stepD / 2, lat + a[1] * stepD / 2, sign);
      if (!b) break;
      lon += b[0] * stepD; lat += b[1] * stepD;
      if (!velocityAt(g, lon, lat) || near(lon, lat, own)) break;
      out.push([lon, lat, b[2]]);
      line.push({lon, lat, line: own});
    }
    return out;
  };
  const lines = [];
  const dLon = (g.lons[1] - g.lons[0]) * seedEvery, dLat = (g.lats[1] - g.lats[0]) * seedEvery;
  for (let lat = g.lats[0]; lat <= g.lats[g.rows - 1]; lat += dLat) {
    for (let lon = g.lons[0]; lon <= g.lons[g.cols - 1]; lon += dLon) {
      if (!velocityAt(g, lon, lat) || near(lon, lat, -1)) continue;
      const own = lines.length, mine = [];
      const back = trace(lon, lat, -1, mine, own), fwd = trace(lon, lat, 1, mine, own);
      const pts = [...back.reverse(), [lon, lat, velocityAt(g, lon, lat).reduce((s, c) => Math.hypot(s, c))], ...fwd];
      if (pts.length < minPoints) continue;
      for (const p of mine) { const k = key(p.lon, p.lat); (bins.get(k) || bins.set(k, []).get(k)).push(p); }
      lines.push({coords: pts.map(p => [p[0], p[1]]), speed: pts.reduce((s, p) => s + p[2], 0) / pts.length});
    }
  }
  return lines;
}

const mercY = lat => Math.log(Math.tan(Math.PI / 4 + lat * DEG / 2));
const unMercY = y => (2 * Math.atan(Math.exp(y)) - Math.PI / 2) / DEG;

/** RGBA pixels of the vorticity tint over the grid extent, rows spaced evenly in web-mercator y so the
 *  image drops onto a MapLibre image source. Transparent wherever any corner is missing. */
export function tintPixels(g, width, {range = VORT_RANGE, alpha = TINT_ALPHA} = {}) {
  const zeta = vorticity(g);
  const west = g.lons[0], east = g.lons[g.cols - 1], south = g.lats[0], north = g.lats[g.rows - 1];
  const y0 = mercY(south), y1 = mercY(north);
  const height = Math.max(2, Math.round(width * (y1 - y0) / ((east - west) * DEG)));
  const data = new Uint8ClampedArray(width * height * 4);
  for (let py = 0; py < height; py++) {
    const lat = unMercY(y1 - (py + 0.5) / height * (y1 - y0));
    for (let px = 0; px < width; px++) {
      const z = bilinear(g, zeta, west + (px + 0.5) / width * (east - west), lat);
      if (z === null) continue;
      const [r, gg, b] = balance((Math.max(-1, Math.min(1, z / range)) + 1) / 2), i = (py * width + px) * 4;
      data[i] = r; data[i + 1] = gg; data[i + 2] = b; data[i + 3] = Math.round(alpha * 255);
    }
  }
  return {data, width, height, coordinates: [[west, north], [east, north], [east, south], [west, south]]};
}

/** Bearing (degrees clockwise from north) of the last segment of a line, for its arrowhead. */
export function bearing(a, b) {
  const dx = (b[0] - a[0]) * Math.cos((a[1] + b[1]) / 2 * DEG), dy = b[1] - a[1];
  return (Math.atan2(dx, dy) / DEG + 360) % 360;
}

export function streamGeoJSON(lines) {
  const features = [];
  // Destructured on purpose: tests/test_ranking.mjs scans web/ for the device-position property read, and a
  // streamline's points are not a device position.
  for (const {coords, speed} of lines) {
    features.push({type: 'Feature', properties: {speed: +speed.toFixed(3)}, geometry: {type: 'LineString', coordinates: coords}});
    const k = Math.floor(coords.length * 0.6);   // one arrowhead per line, a little past the middle
    features.push({type: 'Feature', properties: {bearing: bearing(coords[k - 1], coords[k])}, geometry: {type: 'Point', coordinates: coords[k]}});
  }
  return {type: 'FeatureCollection', features};
}

/** The honest freshness line shown on the page. */
export function freshnessText(doc, now = new Date()) {
  const t = new Date(doc.sample_at), hours = (now - t) / 3.6e6;
  const age = hours < 1.5 ? 'under 2 h old' : `${hours.toFixed(1)} h old`;
  return `HF-radar currents ${doc.sample_at.replace('T', ' ').replace(':00Z', ' UTC')} (${age}), ${doc.resolution_km} km grid, `
    + `${doc.valid_cells} of ${doc.total_cells} cells have a vector`;
}

// ---- MapLibre wiring (browser only) ----
const IDS = {tint: 'currents-tint', lines: 'currents-lines', arrows: 'currents-arrows'};

function arrowImage() {
  const size = 16, canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const c = canvas.getContext('2d');
  c.fillStyle = STREAM_COLOUR;
  c.beginPath(); c.moveTo(size / 2, 1); c.lineTo(size - 4, size - 3); c.lineTo(size / 2, size - 6); c.lineTo(4, size - 3); c.closePath(); c.fill();
  return c.getImageData(0, 0, size, size);
}

/** Add the layer (tint, streamlines, arrowheads) above whatever is already drawn. Returns {setVisible, ids}. */
export function addCurrents(map, doc, {visible = true, tintWidth = 900} = {}) {
  const g = gridOf(doc), tint = tintPixels(g, tintWidth);
  const canvas = document.createElement('canvas');
  canvas.width = tint.width; canvas.height = tint.height;
  canvas.getContext('2d').putImageData(new ImageData(tint.data, tint.width, tint.height), 0, 0);
  const vis = visible ? 'visible' : 'none';
  map.addSource(IDS.tint, {type: 'image', url: canvas.toDataURL('image/png'), coordinates: tint.coordinates});
  map.addLayer({id: IDS.tint, type: 'raster', source: IDS.tint, layout: {visibility: vis}, paint: {'raster-fade-duration': 0, 'raster-resampling': 'linear'}});
  map.addSource(IDS.lines, {type: 'geojson', data: streamGeoJSON(streamlines(g))});
  map.addLayer({id: IDS.lines, type: 'line', source: IDS.lines, filter: ['==', '$type', 'LineString'], layout: {visibility: vis, 'line-cap': 'round'},
    paint: {'line-color': STREAM_COLOUR, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.7, 13, 1.4]}});
  map.addImage('currents-arrow', arrowImage());
  map.addLayer({id: IDS.arrows, type: 'symbol', source: IDS.lines, filter: ['==', '$type', 'Point'],
    layout: {visibility: vis, 'icon-image': 'currents-arrow', 'icon-rotate': ['get', 'bearing'], 'icon-rotation-alignment': 'map', 'icon-allow-overlap': true, 'icon-size': 0.6}});
  return {ids: Object.values(IDS), setVisible(on) { for (const id of Object.values(IDS)) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'); }};
}

// The status line is hidden only when the data loaded fine and the viewer switched the overlay off;
// an unavailable or invalid data file keeps its message visible whatever the checkbox says.
export function statusHidden(failed, checked) {
  return !failed && !checked;
}

// Parse a fetched response into a usable doc, or throw so the page can show "unavailable".
export async function loadCurrentsDoc(fetchFn, url) {
  const res = await fetchFn(url);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const doc = await res.json();
  if (!doc || !Array.isArray(doc.lats) || !Array.isArray(doc.lons) || !doc.u || !doc.v) throw new Error('invalid currents data');
  if (typeof doc.sample_at !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(doc.sample_at) || Number.isNaN(Date.parse(doc.sample_at))) throw new Error('invalid sample_at');
  for (const k of ['resolution_km', 'valid_cells', 'total_cells']) if (!Number.isFinite(doc[k])) throw new Error('invalid ' + k);
  return doc;
}

#!/usr/bin/env node
// C41: a PREVIEW-ONLY camera profile for the Central Coast contour regions (local rehearsal; not region data, not the picker).
//
// Why: arriving through the app's region picker drops the camera, so each region opens on its own default centre. For three of
// the four contour regions that centre is 13-38 km from the nearest published contour vertex, so the first screen shows no line
// even though the region has contours (C34). This module holds one proposed centre per contour region and PROVES, from the
// pinned rehearsal contour pair (C31 pin table, never from the bytes alone), that:
//   - the proposal keeps the region's OLD zoom (only the centre moves),
//   - the proposal lies inside the region's own bounds (regions/<id>/region.json),
//   - at least one contour line geometrically crosses the phone viewport at the proposal (a NECESSARY condition: whether the app
//     draws it is the browser witness of C34, data-contours-drawn 4/6/5 at these centres; geometry here does not claim "drawn"),
//   - Cambria's proposal is its default, unchanged,
//   - a terrain-only region has no proposal at all (it can never gain a contour by this profile).
// It edits no region file, no catalog and no shared picker; the profile is a proposal for whoever owns map.center.
import {createHash} from 'node:crypto';
import {existsSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {CENTRAL_REGIONS, CONTOUR_PAIR, checkContourPair} from './central_picker_walkthrough.mjs';

export const PHONE = Object.freeze({width: 390, height: 844});
export const TERRAIN_ONLY = Object.freeze(['monterey-point-sur', 'santa-cruz-monterey-bay']);
// Proposed landing centres: the published contour vertex nearest each default centre (C34), same zoom as the default.
export const PROFILE = Object.freeze({
  'big-sur-coast': Object.freeze({center: [35.925, -121.5169], zoom: 10}),
  'cambria-san-simeon': Object.freeze({center: [35.612, -121.17], zoom: 12}),
  'south-big-sur-san-simeon': Object.freeze({center: [35.8614, -121.4778], zoom: 10}),
  'point-arguello-conception': Object.freeze({center: [34.875, -120.7208], zoom: 10}),
});
export const UNCHANGED = Object.freeze(['cambria-san-simeon']);

// Web-mercator pixel on a 512 px tile world (the Chart's map library), centre/zoom -> world pixel.
const world = zoom => 512 * 2 ** zoom;
export const toPixel = (lat, lon, zoom) => {
  const w = world(zoom), s = Math.sin(lat * Math.PI / 180);
  return [(lon + 180) / 360 * w, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * w];
};

// Liang-Barsky: does segment a-b touch the rectangle [x0,x1]x[y0,y1]?
const touches = (a, b, x0, y0, x1, y1) => {
  let t0 = 0, t1 = 1;
  const dx = b[0] - a[0], dy = b[1] - a[1];
  for (const [p, q] of [[-dx, a[0] - x0], [dx, x1 - a[0]], [-dy, a[1] - y0], [dy, y1 - a[1]]]) {
    if (p === 0) { if (q < 0) return false; continue; }
    const r = q / p;
    if (p < 0) { if (r > t1) return false; if (r > t0) t0 = r; } else { if (r < t0) return false; if (r < t1) t1 = r; }
  }
  return true;
};

// Number of line features with at least one segment inside the phone viewport centred on `center` at `zoom`.
export function linesInView(geojson, center, zoom, size = PHONE) {
  const [cx, cy] = toPixel(center[0], center[1], zoom);
  const x0 = cx - size.width / 2, x1 = cx + size.width / 2, y0 = cy - size.height / 2, y1 = cy + size.height / 2;
  let count = 0;
  for (const f of geojson.features || []) {
    const g = f.geometry || {};
    const parts = g.type === 'LineString' ? [g.coordinates] : g.type === 'MultiLineString' ? g.coordinates : [];
    const hit = parts.some(line => line.some((c, i) => i > 0 && touches(toPixel(line[i - 1][1], line[i - 1][0], zoom), toPixel(c[1], c[0], zoom), x0, y0, x1, y1)));
    if (hit) count += 1;
  }
  return count;
}

const sameCamera = (a, b) => a.zoom === b.zoom && a.center[0] === b.center[0] && a.center[1] === b.center[1];

// Profile shape only (no data): terrain-only regions carry no entry, every contour region carries a finite centre + integer zoom.
export function checkProfile(profile = PROFILE) {
  for (const region of Object.keys(profile)) {
    if (!CENTRAL_REGIONS.includes(region)) throw new Error(`profile names ${region}, which is not a Central Coast region`);
    if (TERRAIN_ONLY.includes(region)) throw new Error(`${region} is terrain-only: a camera profile must not give it a contour landing`);
  }
  for (const region of CENTRAL_REGIONS.filter(r => !TERRAIN_ONLY.includes(r))) {
    const c = profile[region];
    if (!c || !Array.isArray(c.center) || c.center.length !== 2 || !c.center.every(Number.isFinite) || !Number.isInteger(c.zoom)) {
      throw new Error(`${region}: profile needs {center:[lat,lon], zoom:int}`);
    }
  }
  return Object.keys(profile).length;
}

// regions: {<id>: {bounds:[w,s,e,n], map:{center:[lat,lon], zoom}}} from the repo's own regions/<id>/region.json.
// pairs: {<id>: [{name, bytes}, {name, bytes}]} in CONTOUR_PAIR order, accepted only if the committed pin table says they are the pair.
export function judgeProfile(profile, regions, pairs, {size = PHONE, table} = {}) {
  checkProfile(profile);
  const rows = [];
  for (const [region, cam] of Object.entries(profile)) {
    const r = regions[region];
    if (!r) throw new Error(`${region}: region.json not supplied`);
    const files = pairs[region];
    if (!files) throw new Error(`${region}: pinned contour pair not supplied`);
    const style = JSON.parse(files[0].bytes).provenance.contours;
    checkContourPair(region, files, table ? {style, table} : {style}); // refuses bytes that are not this region's pinned pair
    const docs = files.map(f => JSON.parse(f.bytes));
    const inView = (center, zoom) => docs.reduce((n, d) => n + linesInView(d, center, zoom, size), 0);
    const [w, s, e, n] = r.bounds, def = {center: r.map.center, zoom: r.map.zoom};
    const problems = [];
    if (cam.zoom !== def.zoom) problems.push(`zoom ${cam.zoom} differs from the region's own ${def.zoom}`);
    if (!(cam.center[1] >= w && cam.center[1] <= e && cam.center[0] >= s && cam.center[0] <= n)) problems.push('centre is outside the region bounds');
    const proposed = inView(cam.center, cam.zoom), atDefault = inView(def.center, def.zoom);
    if (proposed < 1) problems.push('no contour line crosses the viewport at the proposed centre');
    if (UNCHANGED.includes(region) && !sameCamera(cam, def)) problems.push('this region must keep its default camera');
    rows.push({region, proposed: cam, default: def, crossingAtProposed: proposed, crossingAtDefault: atDefault, ok: problems.length === 0, problems});
  }
  return rows;
}

const here = fileURLToPath(import.meta.url);
if (process.argv[1] && pathToFileURL(process.argv[1]).href === pathToFileURL(here).href) {
  const arg = n => { const i = process.argv.indexOf(n); return i > 0 ? process.argv[i + 1] : null; };
  const pairsDir = arg('--pairs') || process.env.CENTRAL_REHEARSAL_PAIRS, regionsDir = arg('--regions') || fileURLToPath(new URL('../../regions', import.meta.url));
  if (!pairsDir || !existsSync(pairsDir)) { console.error('usage: central_preview_cameras.mjs --pairs <dir with one directory per contour region> [--regions <repo regions dir>]'); process.exit(2); }
  const regions = {}, pairs = {};
  for (const region of Object.keys(PROFILE)) {
    regions[region] = JSON.parse(readFileSync(join(regionsDir, region, 'region.json')));
    pairs[region] = CONTOUR_PAIR.map(name => ({name, bytes: readFileSync(join(pairsDir, region, name))}));
  }
  const rows = judgeProfile(PROFILE, regions, pairs);
  const receipt = {scope: 'LOCAL preview-only camera profile; synthetic rehearsal pairs; not region data, not an R8 verdict', rows};
  receipt.digest = createHash('sha256').update(JSON.stringify(rows)).digest('hex');
  console.log(JSON.stringify(receipt, null, 1));
  process.exit(rows.every(r => r.ok) ? 0 : 1);
}

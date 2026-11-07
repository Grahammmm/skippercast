// MAPLAYER-CURRENT-1: the surface-current overlay's maths on a small synthetic grid. Offline; no map, no network.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {balance} from '../research/scripts/map_style/balance-ramp.js';
import {bearing, bilinear, freshnessText, gridOf, streamGeoJSON, streamlines, tintPixels, velocityAt, vorticity}
  from '../research/scripts/map_style/currents-layer.js';

const lats = [35.0, 35.05, 35.1, 35.15, 35.2, 35.25], lons = [-121.0, -120.95, -120.9, -120.85, -120.8, -120.75];
const field = fn => lats.map(la => lons.map(lo => fn(la, lo)));
const grid = (uf, vf) => gridOf({lats, lons, u: field(uf), v: field(vf)});

test('a uniform eastward flow has no spin and its streamlines run east', () => {
  const g = grid(() => 0.3, () => 0);
  const z = vorticity(g);
  assert.ok(z[2][2] !== null && Math.abs(z[2][2]) < 1e-9);
  const lines = streamlines(g);
  assert.ok(lines.length > 0);
  for (const line of lines) {
    const [a, b] = [line.coords[0], line.coords.at(-1)];
    assert.ok(b[0] > a[0] && Math.abs(b[1] - a[1]) < 1e-6, 'east, not drifting north or south');
  }
});

test('counter-clockwise rotation is positive spin, clockwise negative', () => {
  const ccw = grid((la, lo) => -(la - 35.125) * 6, (la, lo) => (lo + 120.875) * 6);
  const cw = grid((la, lo) => (la - 35.125) * 6, (la, lo) => -(lo + 120.875) * 6);
  assert.ok(vorticity(ccw)[2][2] > 0.1);
  assert.ok(vorticity(cw)[2][2] < -0.1);
  // colour: counter-clockwise is the red end of cmocean balance, clockwise the blue end
  const red = balance(1), blue = balance(0);
  assert.ok(red[0] > red[2] && blue[2] > blue[0]);
});

test('nothing is drawn across a gap: a missing vector blanks every point it touches', () => {
  const u = field(() => 0.2), v = field(() => 0.1);
  u[2][2] = null; v[2][2] = null;
  const g = gridOf({lats, lons, u, v});
  assert.equal(velocityAt(g, -120.9, 35.1), null);          // on the missing cell
  assert.equal(velocityAt(g, -120.92, 35.12), null);        // inside a square that has it as a corner
  assert.ok(velocityAt(g, -120.82, 35.22) !== null);        // a square that does not
  assert.equal(velocityAt(g, -122, 35.1), null);            // outside the grid
  assert.equal(vorticity(g)[2][3], null);                   // a neighbour of the gap has no centred difference
  const tint = tintPixels(g, 60);
  const alphaAt = (lon, lat) => {
    const px = Math.floor((lon - lons[0]) / (lons[5] - lons[0]) * tint.width);
    let best = 0; // find the row by scanning: rows are mercator-spaced, so pick the nearest by latitude
    const y0 = Math.log(Math.tan(Math.PI / 4 + lats[0] * Math.PI / 360)), y1 = Math.log(Math.tan(Math.PI / 4 + lats[5] * Math.PI / 360));
    const y = Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
    best = Math.floor((y1 - y) / (y1 - y0) * tint.height);
    return tint.data[(best * tint.width + px) * 4 + 3];
  };
  assert.equal(alphaAt(-120.9, 35.1), 0);
  assert.equal(alphaAt(-120.9, 35.13), 0, 'the square above the gap is blank too');
  assert.ok(alphaAt(-120.82, 35.17) > 0, 'a square whose four corners all have spin is tinted');
});

test('streamlines keep apart and every point stays inside the radar footprint', () => {
  const g = grid((la, lo) => -(la - 35.125) * 6, (la, lo) => (lo + 120.875) * 6);
  const lines = streamlines(g);
  assert.ok(lines.length >= 3);
  for (const line of lines) for (const [lon, lat] of line.coords) assert.ok(velocityAt(g, lon, lat) !== null);
  assert.deepEqual(streamlines(g), lines, 'deterministic');
});

test('bearing and arrowheads point the way the flow goes', () => {
  assert.ok(Math.abs(bearing([0, 35], [0.01, 35]) - 90) < 0.5);
  assert.ok(Math.abs(bearing([0, 35], [0, 35.01])) < 0.5 || Math.abs(bearing([0, 35], [0, 35.01]) - 360) < 0.5);
  const json = streamGeoJSON([{coords: [[0, 35], [0.01, 35], [0.02, 35], [0.03, 35], [0.04, 35]], speed: 0.3}]);
  const arrow = json.features.find(f => f.geometry.type === 'Point');
  assert.ok(Math.abs(arrow.properties.bearing - 90) < 0.5);
});

test('the freshness line names the data time, its age and the coverage', () => {
  const doc = {sample_at: '2026-11-07T14:00:00Z', resolution_km: 6, valid_cells: 539, total_cells: 1634};
  const text = freshnessText(doc, new Date('2026-11-07T16:06:00Z'));
  assert.match(text, /2026-11-07 14:00 UTC/);
  assert.match(text, /2\.1 h old/);
  assert.match(text, /539 of 1634 cells/);
});

test('bilinear gives the exact value at a cell and refuses outside', () => {
  const g = grid((la, lo) => la, () => 0);
  assert.ok(Math.abs(bilinear(g, g.u, -120.9, 35.1) - 35.1) < 1e-9);
  assert.equal(bilinear(g, g.u, -119, 35.1), null);
});

test('the colour table is the 256-entry cmocean balance and the output stays out of public builds', () => {
  const src = readFileSync(new URL('../research/scripts/map_style/balance-ramp.js', import.meta.url), 'utf8');
  assert.equal([...src.matchAll(/'([0-9a-f]{96})'/g)].map(m => m[1]).join('').length, 256 * 6);
  const build = readFileSync(new URL('../scripts/client-build.mjs', import.meta.url), 'utf8');
  assert.ok(!/var\/currents/.test(build), 'client-build never reads var/');
});

test('missing or invalid currents data keeps its status visible and draws nothing; overlay-off still hides valid data', async () => {
  const {statusHidden, loadCurrentsDoc} = await import('../research/scripts/map_style/currents-layer.js');
  assert.equal(statusHidden(true, false), false);   // failure shown even with the checkbox unchecked
  assert.equal(statusHidden(false, false), true);   // valid data, overlay deliberately off
  assert.equal(statusHidden(false, true), false);
  await assert.rejects(loadCurrentsDoc(async () => ({ok: false, status: 404, json: async () => ({})}), '/x'), /404/);
  await assert.rejects(loadCurrentsDoc(async () => ({ok: true, json: async () => ({foo: 1})}), '/x'), /invalid/);
  const good = {lats: [1], lons: [2], u: [[0]], v: [[0]], sample_at: '2026-11-07T14:00:00Z', resolution_km: 6, valid_cells: 1, total_cells: 1};
  const evil = {...good, sample_at: '<img src=x onerror=alert(1)>'};
  await assert.rejects(loadCurrentsDoc(async () => ({ok: true, json: async () => evil}), '/x'), /sample_at/);
  assert.equal(await loadCurrentsDoc(async () => ({ok: true, json: async () => good}), '/x'), good);
  const page = readFileSync(new URL('../research/scripts/map_style/bathy-deep-test.html', import.meta.url), 'utf8');
  assert.match(page, /statusHidden\(failed, box\.checked\)/);
  assert.match(page, /failed = true;/);
  assert.doesNotMatch(page, /line\.innerHTML/);
});

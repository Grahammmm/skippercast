// F14-16 / SCA-501: the radar style study must stay transparent wherever the native vector sampler has no vector.
// Contract protected: tintPixels is opaque only where velocityAt() (the footprint the streamlines use) is non-null.
// Believable bug: masking by the derived vorticity grid alone (e.g. a one-sided or gap-filling derivative, or a
// stencil that reads the cell's own vector) tints part of an observation gap.
// Note: with today's 4-neighbour central-difference stencil the derived grid is already a subset of the footprint, so
// these checks pass on main too; the explicit mask makes the invariant independent of the stencil.
import test from 'node:test';
import assert from 'node:assert/strict';
import {gridOf, tintPixels, velocityAt, TINT_ALPHA} from '../web/map/currents-layer.js';
import {balance} from '../web/map/balance-ramp.js';

const lats = [35.0, 35.05, 35.1, 35.15, 35.2, 35.25, 35.3], lons = [-121.0, -120.95, -120.9, -120.85, -120.8, -120.75, -120.7];
const DEG = Math.PI / 180, mercY = lat => Math.log(Math.tan(Math.PI / 4 + lat * DEG / 2)), unMercY = y => (2 * Math.atan(Math.exp(y)) - Math.PI / 2) / DEG;
const constant = () => ({u: lats.map(() => lons.map(() => 0.2)), v: lats.map(() => lons.map(() => 0.1))});
const W = 48;
// Every tinted pixel and the lon/lat of its centre, in the same web-mercator rows tintPixels uses.
function pixels(g) {
  const t = tintPixels(g, W), west = lons[0], east = lons.at(-1), y0 = mercY(lats[0]), y1 = mercY(lats.at(-1));
  const out = [];
  for (let py = 0; py < t.height; py++) for (let px = 0; px < W; px++) {
    const i = (py * W + px) * 4;
    out.push({lon: west + (px + 0.5) / W * (east - west), lat: unMercY(y1 - (py + 0.5) / t.height * (y1 - y0)), rgba: [...t.data.slice(i, i + 4)]});
  }
  return out;
}
const alphaAt = (px, lon, lat) => { const p = px.reduce((a, b) => Math.hypot(b.lon - lon, b.lat - lat) < Math.hypot(a.lon - lon, a.lat - lat) ? b : a); return p.rgba[3]; };

test('a missing centre vector leaves no opacity over the gap, whole-block gaps included', () => {
  for (const holes of [[[3, 3]], [[3, 3], [3, 4], [4, 3], [4, 4]], [[2, 2], [2, 3], [2, 4], [3, 2], [3, 3], [3, 4], [4, 2], [4, 3], [4, 4]], [[0, 0]], [[6, 6]]]) {
    const {u, v} = constant();
    for (const [y, x] of holes) { u[y][x] = null; v[y][x] = null; }
    const g = gridOf({lats, lons, u, v}), px = pixels(g);
    let seen = 0;
    for (const p of px) if (velocityAt(g, p.lon, p.lat) === null) { seen++; assert.equal(p.rgba[3], 0, `opaque pixel in a gap at ${p.lon},${p.lat} for ${JSON.stringify(holes)}`); }
    assert.ok(seen > 0, 'the control actually has gap pixels');
    // the hole's own node is transparent
    assert.equal(alphaAt(px, lons[holes[0][1]], lats[holes[0][0]]), 0);
  }
});

test('a vector missing in only one component is also a gap', () => {
  for (const which of ['u', 'v']) {
    const c = constant(); c[which][3][3] = null;
    const g = gridOf({lats, lons, ...c});
    for (const p of pixels(g)) if (velocityAt(g, p.lon, p.lat) === null) assert.equal(p.rgba[3], 0);
  }
});

test('positive control: a fully supported constant field still shows neutral colour, opaque everywhere', () => {
  const g = gridOf({lats, lons, ...constant()}), px = pixels(g);
  const neutral = balance(0.5), alpha = Math.round(TINT_ALPHA * 255);
  // Pixels in the outer ring of cells have no derivative (stencil needs interior nodes); the interior is the supported tint.
  const inner = px.filter(p => p.lon > lons[1] && p.lon < lons[5] && p.lat > lats[1] && p.lat < lats[5]);
  assert.ok(inner.length > 100);
  for (const p of inner) { assert.equal(p.rgba[3], alpha); assert.deepEqual(p.rgba.slice(0, 3), [...neutral]); }
});

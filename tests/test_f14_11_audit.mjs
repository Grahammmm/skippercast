import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import {createCurrents} from '../web/map/currents.ts';

const validAt = '2026-10-07T12:00:00Z';
const cells = Array.from({length: 25}, (_, i) => ({
  lon: (i % 5) * 0.04, lat: Math.floor(i / 5) * 0.04,
  uMs: 0.3, vMs: 0.1, speedKnots: 0.61, towardDeg: 72,
}));
const forecast = {
  id: 'wcofs', kind: 'forecast', label: 'Synthetic WCOFS', url: 'https://example.test/current',
  fetchedAt: validAt, issuedAt: '2026-10-07T03:00:00Z', sampleAt: null,
  nativeResolutionKm: 4, sampleStride: 1, horizontalDatum: 'NAD83', surfaceOnly: true,
  attribution: 'NOAA', license: 'public-domain-us-gov', limitations: 'Surface only.',
  frames: [{validAt, cells}],
};
const headland = {lon: 0.04, lat: 0.04}, wet = {lon: 0.05, lat: 0.04};
const rings = [[[0.035, 0.035], [0.045, 0.035], [0.045, 0.045], [0.035, 0.045]]];

function rig(land, {busy = false} = {}) {
  const listeners = new Map(), dots = [];
  let shift = 0, hides = 0;
  const view = {
    busy: () => busy, land: () => land, size: () => ({width: 320, height: 320}),
    project: (lon, lat) => ({x: lon * 1600 + shift, y: lat * 1600}),
    unproject: (x, y) => ({lon: (x - shift) / 1600, lat: y / 1600}),
    container: () => ({append() {}}),
    on(type, fn) { listeners.set(type, fn); return () => listeners.delete(type); },
  };
  const doc = {
    addEventListener() {}, removeEventListener() {},
    createElement() {
      const points = [];
      const ctx = {
        setTransform() {}, clearRect() {}, setLineDash() {}, stroke() {}, fill() {},
        beginPath() { points.length = 0; }, moveTo(x, y) { points.push([x, y]); }, lineTo(x, y) { points.push([x, y]); },
        arc(x, y) { dots.push([x, y]); },
        // Minimal Canvas double for the single axis-aligned rectangle supplied by the map.
        getImageData(_x, _y, w, h) {
          const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
          const data = new Uint8ClampedArray(w * h * 4);
          for (let y = Math.ceil(Math.min(...ys)); y < Math.max(...ys); y++) {
            for (let x = Math.ceil(Math.min(...xs)); x < Math.max(...xs); x++) data[(y * w + x) * 4 + 3] = 255;
          }
          return {data};
        },
      };
      return {dataset: {}, setAttribute() {}, remove() {}, getContext: () => ctx};
    },
  };
  const currents = createCurrents({
    view, doc, source: () => 'wcofs', shown: () => true, zone: () => 'UTC',
    now: () => new Date('2026-10-07T12:20:00Z'), onHide: () => { hides++; },
    palette: () => ({flow: 'blue', flowFast: 'cyan'}),
    motion: {matches: true, addEventListener() {}, removeEventListener() {}},
    data: {coastOcean: signal({data: {currents: [forecast]}}), coastStatus: signal({ocean: 'ready'})},
  });
  return {currents, dots, hides: () => hides,
    move: () => { listeners.get('movestart')(); shift = 32; },
    idle: () => { busy = false; listeners.get('idle')(); },
  };
}

// Regression: interpolating the coarse wet grid alone returns a reading where the overlay masks land.
test('current picks honor the displayed headland mask without losing the adjacent wet reading', t => {
  const {currents, dots} = rig(rings);
  t.after(() => currents.destroy());
  assert.ok(dots.some(([x, y]) => x === 128 && y === 64), 'the adjacent wet grid point draws');
  assert.ok(!dots.some(([x, y]) => x === 64 && y === 64), 'the coarse wet grid point on the headland is masked');
  assert.deepEqual(currentDetails(currents.reading(wet)), {
    kind: 'Forecast · valid Wed 12 pm', source: 'Synthetic WCOFS · issued 9 h ago', reading: '0.61 kt toward 72° true',
  });
  assert.equal(currents.reading(headland), null, 'the masked wet-grid point must not return a current');
});

function currentDetails({kind, source, reading}) { return {kind, source, reading}; }

// Regression: sampling before idle, reusing a screen mask after a pan, or retaining it after engine teardown.
test('camera movement and engine replacement invalidate pick eligibility until the new view is drawn', t => {
  const a = rig(rings);
  t.after(() => a.currents.destroy());
  const before = a.currents.reading(wet);
  assert.ok(before);
  a.move();
  assert.equal(a.currents.reading(wet), null, 'no reading against the cleared drawing during a pan');
  assert.equal(a.hides(), 1, 'withdraw the previously displayed reading');
  a.idle();
  assert.deepEqual(a.currents.reading(wet), before);
  assert.equal(a.currents.reading(headland), null, 'the mask was rebuilt at the shifted projection');
  a.currents.destroy();
  assert.equal(a.currents.reading(wet), null, 'the retired engine cannot serve a reading');

  const b = rig([], {busy: true});
  t.after(() => b.currents.destroy());
  assert.equal(b.currents.reading(headland), null, 'the replacement engine has not drawn yet');
  b.idle();
  assert.deepEqual(b.currents.reading(headland), before, 'the new engine uses its own empty mask');
});

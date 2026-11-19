import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

// F06-12: the same contract must pass on the synthetic reuse control and
// detect redundant work on the unmodified inspector. The latter is opt-in:
// node tests/test_f06_12_audit.mjs --baseline
const baseline = process.argv.includes('--baseline');
const source = name => readFileSync(new URL(`../src/skippercast/coastal/render/terrain_demo_${name}.js`, import.meta.url));
const sha256 = value => createHash('sha256').update(value).digest('hex');
const width = 1600, height = 1000, area = width * height;
const steps = ['initial', 'light', 'pan right', 'reset camera'];
const payload = {
  // Sloped, partly offscreen terrain with an overlapping nearer face and unsupported pixels.
  vertices: [[-11, -3, -6], [4, -3, -2], [1, 5, -9], [-2, -2, -1], [2, -2, -1], [0, 3, -1]],
  faces: [[0, 1, 2], [3, 4, 5]], center: [0, 0, 0], span: [10, 10],
  vertex_uncertainty_m: [0.25, 0.5, 0.75, 0.5, 1, 1.5], uncertainty_kind: 'synthetic uncertainty',
  grid_pixels: [[0, 0], [1, 0], [1, 1], [2, 0], [3, 0], [3, 1]],
  support: [[true, true, true, true], [false, true, false, true]],
  depth_m: [[6, 2, 1, 1], [null, 9, null, 1]], metadata: {},
};
const noop = () => {};
const viewWork = ['project', 'raster', 'visibleScan', 'updateRange', 'clippedCounts'];
const freshCounts = () => ({ project: 0, raster: 0, visibleScan: 0, updateRange: 0, clippedCounts: 0, depthOrZ: 0, triangles: 0, normals: 0 });

function replay(useBaseline) {
  let counts = freshCounts(), surface, viewport, pixels, pending, hit, slot = 0;
  const planes = [];
  const typed = (Type, length, key) => new Proxy(Type, {
    construct(target, args) {
      if (args[0] !== length) return Reflect.construct(target, args);
      // Fixture-only arena. The real rasterizer still writes every supported pixel.
      // Float64/Int32 sentinels are filled by raster; zero the normal plane as on allocation.
      const index = slot++;
      if (!useBaseline && planes[index]) return planes[index].fill(0);
      counts[key]++;
      const array = Reflect.construct(target, args);
      if (!useBaseline) planes[index] = array;
      return array;
    },
  });
  const ctx = {
    createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
    putImageData: image => { pixels = sha256(image.data); },
    // Only terrain RGBA from putImageData is read; no browser contour compositing.
    beginPath: noop, moveTo: noop, lineTo: noop, stroke: noop,
    measureText: text => ({ width: text.length * 8 }), fillRect: noop, fillText: noop,
  };
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const listeners = new Map();
      elements.set(id, {
        addEventListener: (event, fn) => listeners.set(event, fn),
        fire: (event, data = {}) => listeners.get(event)({ preventDefault: noop, ...data }),
      });
    }
    return elements.get(id);
  }
  const canvas = Object.assign(element('terrain'), {
    getContext: () => ctx, setPointerCapture: noop,
    getBoundingClientRect: () => ({ left: 0, top: 0, width, height }),
  });
  const context = vm.createContext({
    Float64Array: typed(Float64Array, area, 'depthOrZ'),
    Int32Array: typed(Int32Array, area, 'triangles'),
    Float32Array: typed(Float32Array, area * 3, 'normals'),
    TERRAIN_PAYLOAD: payload,
    TERRAIN_STYLE: { display_mode: 'Measured', subdivisions: 1, strength: 0, haloCells: 0 },
    document: { getElementById: element }, requestAnimationFrame: fn => { pending = fn; },
  });
  vm.runInContext(source('core').toString(), context, { filename: 'terrain_demo_core.js' });
  const C = vm.runInContext('TerrainCore', context);
  const ViewArray = vm.runInContext('Array', context), arrayFrom = ViewArray.from;
  ViewArray.from = function (values, ...args) {
    if (values === surface?.depth) counts.visibleScan++;
    return arrayFrom.call(this, values, ...args);
  };
  const wrap = (key, observe) => {
    const fn = C[key];
    C[key] = (...args) => observe(fn, args);
  };
  wrap('project', (fn, args) => { counts.project++; return fn(...args); });
  wrap('raster', (fn, args) => { counts.raster++; slot = 0; return (surface = fn(...args)); });
  wrap('updateRange', (fn, args) => {
    counts.updateRange++;
    const range = fn(...args);
    viewport = { visible: args[1].length, range: [...range] };
    return range;
  });
  wrap('clippedCounts', (fn, args) => {
    counts.clippedCounts++;
    const clipped = fn(...args);
    Object.assign(viewport, clipped);
    return clipped;
  });
  wrap('probe', (fn, args) => (hit = fn(...args)));

  let changeLight, pan, reset, probe;
  if (useBaseline) {
    const ui = source('ui');
    vm.runInContext(ui.toString(), context, { filename: 'terrain_demo_ui.js' });
    changeLight = () => { element('lightIntensity').value = '1'; element('lightIntensity').fire('input'); };
    pan = () => canvas.fire('keydown', { key: 'ArrowRight' });
    reset = () => element('reset').fire('click');
    probe = (clientX, clientY) => {
      const event = { pointerId: 1, clientX, clientY };
      canvas.fire('pointerdown', event);
      canvas.fire('pointerup', event);
    };
  } else {
    // Valid control, not production code: retain the view on light-only input,
    // rebuild its contents on camera input. Real core and real pixel math;
    // the fixed hashes below are recorded from the independent inspector path.
    const camera = { azimuth: 0, elevation: 90, ve: 1, width, height, scale: 84, panX: 0, panY: 0 };
    const light = { azimuth: 315, elevation: 45, intensity: 0.5 };
    const state = C.rangeState(), normals = C.smoothNormals(payload.vertices, payload.faces);
    let projected, range;
    function draw(rebuild) {
      if (rebuild) {
        projected = C.project(payload, camera);
        C.raster(payload, projected, width, height, normals);
        const visible = ViewArray.from(surface.depth).filter(Number.isFinite);
        range = C.updateRange(state, visible);
        C.clippedCounts(visible, range);
      }
      const image = ctx.createImageData(width, height);
      const { triangles, depth, shadeNormals: n } = surface;
      for (let k = 0; k < area; k++) {
        const rgb = triangles[k] < 0 ? [230, 235, 239]
          : C.color(depth[k], range, C.relief([n[k * 3], n[k * 3 + 1], n[k * 3 + 2]], light));
        image.data.set([...rgb, 255], k * 4);
      }
      ctx.putImageData(image, 0, 0);
    }
    draw(true);
    changeLight = () => { light.intensity = 1; draw(false); };
    pan = () => { camera.panX = 48; draw(true); };
    reset = () => { camera.panX = 0; draw(true); };
    probe = (x, y) => C.probe(payload, projected, [x, y]);
  }

  let previousBuffers;
  return [noop, changeLight, pan, reset].map(action => {
    action();
    if (pending) { const draw = pending; pending = null; draw(); }
    const buffers = [surface.depth, surface.z, surface.triangles, surface.shadeNormals].map(array => array.buffer);
    const sameStorage = previousBuffers ? buffers.every((buffer, i) => buffer === previousBuffers[i]) : null;
    previousBuffers = buffers;
    const mask = sha256(Uint8Array.from(surface.triangles, face => Number(face >= 0)));
    const frame = { counts, sameStorage, pixels, mask, viewport };
    counts = freshCounts();
    // Snapshot frame work before real pointer probes (which may independently project).
    frame.probes = [[800, 500], [0.5, 0.5]].map(([x, y]) => {
      probe(x, y);
      return hit && { triangle: hit.triangle, depth: hit.depth_m, uncertainty: hit.uncertainty_m };
    });
    counts = freshCounts();
    return frame;
  });
}

// Independent reference observations from the unchanged inspector (main f47fb6bb0f1342a7223c84f976439201ea682ae3).
// SHA-256 of every RGBA byte and of one support byte per pixel, not screenshots or timings.
const atRest = {
  mask: '39681e610b696a34622e796465571cd14465a2443b636108f9493c28a8133303',
  viewport: { visible: 418235, range: [1, 8.355835317460318], below: 3371, above: 8365 },
  probes: [{ triangle: 1, depth: 1, uncertainty: 1.0499999999999998 }, null],
};
const relit = { ...atRest, pixels: '84171799f4bc7e6e80f3f4f8e1bc31c93c878fce1829a491227074f9af77a044' };
const expected = [
  { ...atRest, pixels: '3a73ee15dde9ff7bb8a8cf2f08cafb76fd21b320fbb0f58b20cd42761d2aced8' },
  relit,
  {
    pixels: 'bc566fbc3a1e90ae1843a9fbf50f61dd6a8bfa0c625780837b6fa7daf12cd306',
    mask: 'cd43bc1e1dcedcc7c74b42eba33b62cca9ec33e6f6d4a1744ad6ea6e1b003724',
    viewport: { ...atRest.viewport, visible: 421435 },
    probes: [{ triangle: 1, depth: 1, uncertainty: 0.9785714285714286 }, null],
  },
  relit,
];

test(`F06-12 ${baseline ? 'unchanged inspector' : 'synthetic reuse control'}`, t => {
  const frames = replay(baseline);
  if (baseline) {
    t.diagnostic(`sources core=${sha256(source('core'))} ui=${sha256(source('ui'))}`);
    for (const [i, frame] of frames.entries()) t.diagnostic(`${steps[i]} ${JSON.stringify(frame)}`);
  }
  assert.deepEqual(frames.map(({ pixels, mask, viewport, probes }) => ({ pixels, mask, viewport, probes })), expected,
    'exact terrain pixels, support mask, visible-pixel statistics and hit/miss probes');

  const gaps = [];
  const light = frames[1];
  for (const key of viewWork) {
    if (light.counts[key]) gaps.push(`light rebuilt ${key}: ${light.counts[key]}`);
  }
  for (const [i, { counts, sameStorage }] of frames.entries()) {
    const { depthOrZ, triangles, normals } = counts;
    const allocations = depthOrZ + triangles + normals;
    if (i === 0) assert.deepEqual([depthOrZ, triangles, normals], [2, 1, 1], 'cold frame exercises all four planes');
    else if (allocations || !sameStorage) gaps.push(`${steps[i]} allocated ${allocations} raster planes; same storage=${sameStorage}`);
  }
  assert.deepEqual(gaps, [], 'warm light/camera frames must reuse view work or storage as applicable');
});

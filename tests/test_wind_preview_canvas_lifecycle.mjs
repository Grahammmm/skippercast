import assert from 'node:assert/strict';
import {setImmediate as settled} from 'node:timers/promises';
import test from 'node:test';
import {signal} from '@preact/signals';
import {createPreviewLayers, PREVIEW_LOADERS, previewStatus, togglePreview} from '../web/map/preview-layers.ts';

const attachWind = await PREVIEW_LOADERS.wind();
const now = new Date('2026-01-01T02:00:00Z');
const grid = {
  schema_version: 1, source_id: 'noaa-gfs', units: 'm/s', width: 2, height: 2,
  west: 0, north: 0, resolution_degrees: .25, max_age_hours: 18,
  run_time: '2026-01-01T00:00:00Z', data_time: '2026-01-01T01:00:00Z',
  u: [[2, 2], [2, 2]], v: [[1, 1], [1, 1]],
};

function fixture(t, context) {
  const nodes = new Set(), listeners = new Map(), frames = new Set(), timers = new Set();
  const effects = {insertions: 0, subscriptions: [], animationRequests: 0};
  const size = {width: 390, height: 620};
  const container = {appendChild(canvas) { effects.insertions++; nodes.add(canvas); }};
  const view = {
    container: () => container,
    size: () => size,
    on(type, listener) {
      effects.subscriptions.push(type);
      listeners.set(listener, type);
      return () => listeners.delete(listener);
    },
  };
  t.mock.method(globalThis, 'setInterval', () => { const id = Symbol(); timers.add(id); return id; });
  t.mock.method(globalThis, 'clearInterval', id => timers.delete(id));
  const browser = {
    requestAnimationFrame() {
      const id = ++effects.animationRequests;
      frames.add(id);
      return id;
    },
    cancelAnimationFrame: id => frames.delete(id),
    document: {createElement(tag) {
      assert.equal(tag, 'canvas');
      const canvas = {
        dataset: {}, style: {}, setAttribute() {},
        getContext: type => type === '2d' ? context : null,
        remove: () => nodes.delete(canvas),
      };
      return canvas;
    }},
  };
  const originals = Object.keys(browser).map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]);
  Object.assign(globalThis, browser);

  const layer = createPreviewLayers({
    engine: signal({view}), access: () => true, now: () => now,
    page: () => 'https://fixture.test/', fetchFn: async () => Response.json(grid),
    loaders: {wind: async () => attachWind},
  });
  const off = () => togglePreview('wind', false, true);
  t.after(() => {
    off();
    layer.destroy();
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  });
  return {
    nodes, listeners, frames, timers, size, effects, off,
    async on() { togglePreview('wind', true, true); await settled(); },
  };
}

// Startup used to attach the canvas and subscribe view callbacks before null.clearRect
// threw. The controller could report unavailable but had no handle to remove either.
test('a missing wind 2D context is unavailable without starting the overlay', async t => {
  const f = fixture(t, null);
  await f.on();
  assert.equal(previewStatus.value.wind?.state, 'unavailable');
  assert.deepEqual(f.effects, {insertions: 0, subscriptions: [], animationRequests: 0});
  f.off();
  assert.deepEqual([f.nodes.size, f.listeners.size, f.frames.size, f.timers.size], [0, 0, 0, 0]);
  assert.equal(previewStatus.value.wind, undefined);
});

// The capability check must not disable healthy previews or change their teardown.
test('healthy wind mounts, resizes, and cleans up on both toggles off', async t => {
  const f = fixture(t, {clearRect() {}});
  let previous;
  for (let mount = 0; mount < 2; mount++) {
    await f.on();
    assert.equal(previewStatus.value.wind?.state, 'ready');
    assert.deepEqual([f.nodes.size, f.listeners.size, f.frames.size, f.timers.size], [1, 2, 1, 1]);
    const [canvas] = f.nodes;
    assert.notEqual(canvas, previous, 'reattach uses a fresh canvas');
    previous = canvas;
    assert.equal(canvas.dataset.previewLayer, 'wind');
    assert.equal(canvas.hidden, false);
    assert.deepEqual([canvas.width, canvas.height], [f.size.width, f.size.height]);
    f.size.height += 20;
    const resize = [...f.listeners].find(([, type]) => type === 'resize')?.[0];
    assert.ok(resize, 'subscribed to map resize');
    resize();
    assert.equal(canvas.height, f.size.height);

    f.off();
    assert.deepEqual([f.nodes.size, f.listeners.size, f.frames.size, f.timers.size], [0, 0, 0, 0]);
    assert.equal(previewStatus.value.wind, undefined);
  }
});

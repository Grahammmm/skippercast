import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import {CLOUD_OPACITY, createClouds, frameId} from '../web/map/clouds.ts';
import {createEngine} from '../web/map/engine.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

// F14-15: hiding playback frames by opacity alone still installs their map
// resources. Observe actual engine add/remove operations on a synthetic map.
test('reduced motion installs only the newest eligible cloud frame and restores only fresh frames', t => {
  const page = 'https://fixture.invalid/map?region=morro-bay&layers=clouds';
  configureStore({v2: true, storage: null});
  syncFromURL(page);
  t.mock.timers.enable({apis: ['setTimeout', 'setInterval']});

  const handlers = new Map(), sources = new Map(), layers = new Map(), opacity = new Map();
  const added = [];
  class FakeMap {
    keyboard = {disableRotation() {}};
    touchZoomRotate = {disableRotation() {}};
    on(type, fn) { handlers.set(type, fn); }
    getSource(id) { return sources.get(id); }
    addSource(id, source) { sources.set(id, source); added.push(id); }
    removeSource(id) { sources.delete(id); }
    getLayer(id) { return layers.get(id); }
    addLayer(layer) { layers.set(layer.id, layer); }
    removeLayer(id) { layers.delete(id); opacity.delete(id); }
    setPaintProperty(id, name, value) { if (name === 'raster-opacity') opacity.set(id, value); }
    remove() {}
  }
  const engine = createEngine({lib: {Map: FakeMap, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/worker.js', Protocol: class {}}, {
    host: {}, style: {version: 8, sources: {}, layers: []}, still: true,
    camera: {latitude: 0, longitude: 0, zoom: 4}, onMove() {},
  });
  handlers.get('style.load')();

  let now = Date.parse('2026-10-02T03:00:00Z');
  const ago = minutes => new Date(now - minutes * 60_000).toISOString();
  const [stale, expiring, older, newest] = [91, 90, 12, 7].map(ago);
  const attribution = 'Synthetic GOES attribution';
  const cloud = {id: 'goes-longwave', kind: 'observation', layer: 'goes_longwave_imagery',
    observedAt: newest, fetchedAt: ago(0), availableTimes: [stale, expiring, older, newest], attribution};
  const motion = new EventTarget();
  motion.matches = true;
  const controller = createClouds({engine: signal(engine), zone: () => 'UTC', now: () => new Date(now),
    page: () => page, doc: new EventTarget(), motion, reported: () => cloud,
    fetchFn: async () => ({ok: false})});
  t.after(() => { controller.destroy(); engine.destroy(); });

  const installed = (times, label) => {
    const ids = times.map(frameId);
    assert.equal(sources.size, ids.length, label);
    assert.deepEqual([...sources.keys()].sort(), ids);
    assert.deepEqual([...layers.keys()].sort(), ids);
    assert.ok([...sources.values()].every(source => source.attribution === attribution));
  };
  const preferReduced = value => { motion.matches = value; motion.dispatchEvent(new Event('change')); };
  installed([newest], 'reduced at startup: exactly one installed source');
  assert.deepEqual(added, [frameId(newest)], 'playback-only sources were never added');
  assert.equal(opacity.get(frameId(newest)), CLOUD_OPACITY);

  preferReduced(false);
  installed([expiring, older, newest], 'normal motion: three eligible sources');
  preferReduced(true);
  installed([newest], 'switch to reduced motion: remove the playback-only sources');
  now += 60_000;
  t.mock.timers.tick(60_000);
  preferReduced(false);
  installed([older, newest], 'restore two eligible sources, not the frame that aged out');
  t.diagnostic('installed cloud sources: reduced startup 1 → normal 3 → reduced 1 → normal after expiry 2');
});

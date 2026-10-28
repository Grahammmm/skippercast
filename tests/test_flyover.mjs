// #646 (walkthrough slice 6, owner decision B): the Chart flyover's gates and
// flight plan (web/map/flyover.ts) and the engine's flight (web/map/engine.ts
// `flyover`) over a fake MapLibre: it ends north up and flat around the same
// centre and zoom, any input stops it, and max pitch is raised only while it flies.
import assert from 'node:assert/strict';
import test from 'node:test';
import {FLY_STOPPERS, createEngine} from '../web/map/engine.ts';
import {DEFAULT_TURN, FLYOVER_KEY, MAX_TILT, MAX_TURN, bearingTo, flyoverLegs, flyoverSeen, flyoverTurn, markFlyoverSeen, mayFly} from '../web/map/flyover.ts';

const OPEN = {reduced: false, saveData: false, hidden: false, linked: false, seen: false};
const CENTER = {latitude: 35.37, longitude: -120.95}, HARBOR = {latitude: 35.37, longitude: -120.86};

test('every gate must be open to fly', () => {
  assert.equal(mayFly(OPEN), true);
  for (const key of Object.keys(OPEN)) assert.equal(mayFly({...OPEN, [key]: true}), false, key);
});

test('the turn faces the harbor, within ±90°, with a gentle default', () => {
  assert.equal(Math.round(bearingTo(CENTER, HARBOR)), 90, 'due east');
  assert.equal(Math.round(bearingTo(HARBOR, CENTER)), -90, 'due west');
  assert.equal(flyoverTurn(CENTER, HARBOR), 90);
  assert.equal(flyoverTurn(CENTER, {latitude: 35.2, longitude: -120.95}), MAX_TURN, 'due south clamps');
  assert.equal(flyoverTurn({latitude: 35.37, longitude: -120.8}, {latitude: 35.5, longitude: -120.9}) < 0, true, 'north-west turns anticlockwise');
  assert.equal(flyoverTurn(CENTER, null), DEFAULT_TURN, 'no harbor');
  assert.equal(flyoverTurn(HARBOR, HARBOR), DEFAULT_TURN, 'on the harbor');
});

test('the flight tilts no steeper than MAX_TILT and ends north up and flat', () => {
  const legs = flyoverLegs(CENTER, HARBOR);
  assert.ok(legs.every(l => l.pitch <= MAX_TILT && l.duration > 0));
  assert.deepEqual({pitch: legs.at(-1).pitch, bearing: legs.at(-1).bearing}, {pitch: 0, bearing: 0});
  assert.equal(legs[1].bearing, 90);
  const total = legs.reduce((s, l) => s + l.duration, 0);
  assert.ok(total >= 15000 && total <= 30000, `about 20 s, got ${total}`);
});

test('the session flag survives denied storage', () => {
  const store = new Map();
  const storage = () => ({getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v)});
  assert.equal(flyoverSeen(storage), false);
  markFlyoverSeen(storage);
  assert.equal(store.get(FLYOVER_KEY), '1');
  assert.equal(flyoverSeen(storage), true);
  const denied = () => { throw new Error('SecurityError'); };
  assert.equal(flyoverSeen(denied), false);
  assert.doesNotThrow(() => markFlyoverSeen(denied));
});

/** A fake MapLibre that records eases; `finish()` ends the running ease as MapLibre does (moveend). */
function library() {
  const fake = {maps: []};
  class FakeMap {
    constructor(options) {
      Object.assign(this, {options, handlers: {}, eases: [], pitch: 0, bearing: 0, maxPitch: options.maxPitch, moving: false, stops: 0});
      this.center = {lat: options.center[1], lng: options.center[0]}; this.zoom = options.zoom;
      this.keyboard = {disableRotation() {}}; this.touchZoomRotate = {disableRotation() {}};
      fake.maps.push(this);
    }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    off(type, fn) { this.handlers[type] = (this.handlers[type] ?? []).filter(f => f !== fn); }
    fire(type) { for (const fn of [...this.handlers[type] ?? []]) fn({}); }
    addControl() {}
    getCenter() { return this.center; }
    getZoom() { return this.zoom; }
    getPitch() { return this.pitch; }
    getBearing() { return this.bearing; }
    setMaxPitch(p) { this.maxPitch = p; if (this.pitch > p) this.pitch = p; }
    easeTo(o) { this.eases.push(o); this.target = o; this.moving = true; }
    finish() { const o = this.target; this.moving = false; this.pitch = Math.min(o.pitch, this.maxPitch); this.bearing = o.bearing; this.fire('moveend'); }
    stop() { this.stops++; if (this.moving) { this.moving = false; this.fire('moveend'); } }
    jumpTo(o) { if ('pitch' in o) this.pitch = o.pitch; if ('bearing' in o) this.bearing = o.bearing; if (o.center) this.center = {lat: o.center[1], lng: o.center[0]}; if ('zoom' in o) this.zoom = o.zoom; this.stop(); this.fire('moveend'); }
    remove() {}
  }
  fake.module = {lib: {Map: FakeMap, NavigationControl: class {}, ScaleControl: class {}, AttributionControl: class {}, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  return fake;
}

function host() {
  const listeners = {};
  return {listeners, dataset: {}, addEventListener: (t, fn) => { (listeners[t] ??= []).push(fn); }, removeEventListener: (t, fn) => { listeners[t] = (listeners[t] ?? []).filter(f => f !== fn); },
    dispatch: t => { for (const fn of [...listeners[t] ?? []]) fn(); }};
}

function engine() {
  const fake = library(), h = host(), moves = [];
  const e = createEngine(fake.module, {host: h, style: {version: 8, sources: {}, layers: []}, camera: {latitude: 35.37, longitude: -120.95, zoom: 12},
    onMove: c => moves.push(c), onLayerError() {}});
  return {e, map: fake.maps[0], host: h, moves};
}

test('a full flight eases each leg around the same centre and zoom, then restores max pitch 0', () => {
  const {e, map, host, moves} = engine(), results = [];
  const legs = flyoverLegs(CENTER, HARBOR);
  e.flyover(legs, finished => results.push(finished));
  assert.equal(map.maxPitch, MAX_TILT, 'pitch allowed only while flying');
  for (const type of FLY_STOPPERS) assert.equal(host.listeners[type].length, 1, `${type} stops it`);
  for (let i = 0; i < legs.length; i++) { assert.equal(map.eases.length, i + 1); map.finish(); }
  assert.deepEqual(map.eases.map(o => [o.pitch, o.bearing]), legs.map(l => [l.pitch, l.bearing]));
  assert.ok(map.eases.every(o => o.zoom === 11 && o.center.lat === 35.37 && o.center.lng === -120.95));
  assert.deepEqual(results, [true]);
  assert.deepEqual([map.pitch, map.bearing, map.maxPitch], [0, 0, 0]);
  for (const type of FLY_STOPPERS) assert.equal(host.listeners[type].length, 0, `${type} listener removed`);
  assert.ok(moves.every(c => c.latitude === 35.37 && c.longitude === -120.95 && c.zoom === 12), 'the shared camera never changes');
});

test('the first touch stops the flight north up and flat where it is', () => {
  const {e, map, host} = engine(), results = [];
  e.flyover(flyoverLegs(CENTER, HARBOR), finished => results.push(finished));
  map.finish();  // tilted and half turned
  assert.ok(map.pitch > 0 && map.bearing !== 0);
  host.dispatch('pointerdown');
  assert.deepEqual(results, [false]);
  assert.deepEqual([map.pitch, map.bearing, map.maxPitch], [0, 0, 0]);
  const eases = map.eases.length;
  map.fire('moveend');
  assert.equal(map.eases.length, eases, 'no further legs');
  host.dispatch('wheel');
  assert.deepEqual(results, [false], 'done is called once');
});

test('setCamera, stopFlyover and destroy end a flight', () => {
  for (const end of [e => e.setCamera({latitude: 35.3, longitude: -120.9, zoom: 11}), e => e.stopFlyover(), e => e.destroy()]) {
    const {e, map} = engine(), results = [];
    e.flyover(flyoverLegs(CENTER, HARBOR), finished => results.push(finished));
    end(e);
    assert.deepEqual(results, [false]);
    assert.deepEqual([map.pitch, map.bearing, map.maxPitch], [0, 0, 0]);
  }
});

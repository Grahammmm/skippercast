// MB-14: the host-only coast embed controls behind the 3D view's camera cap, frame-rate watch and live theme.
// No GPU: the viewer is a prototype instance with just the state each method reads, as tests/coast/coast-overlays.test.ts does.
import assert from 'node:assert/strict';
import test from 'node:test';
import * as T from 'three';
import {CoastOverlays} from '../packages/coast/src/coast3d/overlays.ts';

const dark = Object.freeze({bg: '#07131d', line: '#223849', text: '#e6eff4', muted: '#8ba5b7', mint: '#69e0bc', blue: '#73bfff', coral: '#ff9c86', amber: '#eabd76', mpaFill: '#e8a877', mpaLine: '#e8b584'});
const light = Object.freeze({...dark, bg: '#f4f8f9', line: '#cfdbe2', text: '#0b2530', mint: '#087354', amber: '#8a5a00', mpaFill: '#c9733a', mpaLine: '#b0541c'});
const ring = [[-120.9, 35.4], [-120.8, 35.4], [-120.8, 35.5], [-120.9, 35.5], [-120.9, 35.4]];
const fill = {kind: 'fill', order: 0, style: {color: 'mpaFill', outline: 'mpaLine', opacity: 0.2}, features: [{id: 'zone', geometry: {type: 'Polygon', coordinates: [ring]}}]};
const marks = {kind: 'point', order: 1, style: {color: 'mint', outline: 'bg', size: 10}, features: [{id: 'm', geometry: {type: 'Point', coordinates: [-120.85, 35.45]}}]};
const parts = o => o.group.children;
const hex = part => '#' + part.material.color.getHexString();
const colours = o => parts(o).map(part => part.name + hex(part)).sort().join('|');

// Contract: a theme switch must not rebuild a drape. Bug it catches: setPalette re-running `set`, which would rebuild
// geometry (and, in the app, re-request or re-drape) instead of re-resolving each part's role colour.
test('setPalette re-resolves draped colours by role in place: same objects, geometry, order and opacity', () => {
  const o = new CoastOverlays(dark);
  o.set('zones', fill); o.set('marks', marks);
  const before = parts(o).map(part => [part, part.geometry, part.geometry.getAttribute('position').array.slice(), part.renderOrder, part.material.opacity]);
  const darkColours = colours(o);
  o.setPalette(light);
  assert.notEqual(colours(o), darkColours, 'colours moved');
  assert.deepEqual(parts(o).map(part => part.material.color.getHexString()).sort(),
    ['087354', 'b0541c', 'c9733a', 'f4f8f9'].sort(), 'fill, its outline, the point ring (bg) and the point (mint) each take their role from the light palette');
  parts(o).forEach((part, i) => {
    assert.equal(part, before[i][0], 'same object'); assert.equal(part.geometry, before[i][1], 'same geometry');
    assert.deepEqual([...part.geometry.getAttribute('position').array], [...before[i][2]], 'same drape');
    assert.equal(part.renderOrder, before[i][3], 'same draw order'); assert.equal(part.material.opacity, before[i][4], 'same opacity');
  });
  o.setPalette(dark);
  assert.equal(colours(o), darkColours, 'switching back restores the first colours');
});

// Contract: an overlay added after a switch must already carry the new theme. Bug: the palette frozen at mount.
test('an overlay set after setPalette resolves its roles from the new palette', () => {
  const o = new CoastOverlays(dark);
  o.setPalette(light);
  o.set('late', marks);
  assert.deepEqual(parts(o).map(part => part.material.color.getHexString()).sort(), ['087354', 'f4f8f9']);
});

// Contract: a bad palette changes nothing (the stage logs it and keeps the old look), never half a theme.
test('setPalette refuses an unusable role colour before touching any part, and is inert once disposed', () => {
  const o = new CoastOverlays(dark);
  o.set('zones', fill);
  const before = parts(o).map(hex);
  assert.throws(() => o.setPalette({...light, mpaLine: 'not a colour'}), /mpaLine/);
  assert.deepEqual(parts(o).map(hex), before, 'no part was recoloured');
  o.dispose();
  assert.doesNotThrow(() => o.setPalette(light));
});

const {CoastViewer} = await import('../packages/coast/src/coast3d/viewer.ts');
const sky = {sky: '#cfe3ee', horizon: '#eef5f8', fog: '#eef5f8', ground: '#f4f8f9'};
const bytes = texture => [...texture.image.data];
const near = (a, b) => a.every((v, i) => Math.abs(v - b[i]) <= 1);
const rgb = value => { const h = new T.Color(value).getHex(); return [h >> 16 & 255, h >> 8 & 255, h & 255]; };
const viewer = (options = {}) => {
  const clears = [], v = Object.create(CoastViewer.prototype);
  Object.assign(v, {alive: true, options, scene: new T.Scene(), overlays: new CoastOverlays(dark), renderer: {setClearColor: c => clears.push(c)}});
  v.sky = v.skyTexture(); v.scene.background = v.sky; v.scene.fog = new T.Fog(v.skyColors.fog, 1, 2);
  return {v, clears};
};

// Contract: setTheme is paint-only. Bug it catches: replacing the sky texture or fog (a leak, and a frame of the old theme),
// or touching overlays/camera: the sky is rewritten in place and the same Fog/Texture/background objects stay.
test('setTheme repaints the sky gradient, fog, clear colour and drapes in place', () => {
  const {v, clears} = viewer({sky: {sky: '#0b1a26', horizon: '#13283a', fog: '#0b1a26', ground: '#07131d'}, overlayPalette: dark});
  const texture = v.sky, data = texture.image.data, fog = v.scene.fog, background = v.scene.background;
  const darkBytes = bytes(texture);
  assert.ok(near(darkBytes.slice(0, 3), rgb('#13283a')), 'row 0 is the horizon');
  assert.ok(near(darkBytes.slice(63 * 4, 63 * 4 + 3), rgb('#0b1a26')), 'the last row is the sky top');
  v.overlays.set('marks', marks);
  const geometry = parts(v.overlays)[0].geometry;
  v.setTheme({sky, overlayPalette: light});
  assert.equal(v.sky, texture); assert.equal(texture.image.data, data, 'same data array'); assert.equal(v.scene.background, background); assert.equal(v.scene.fog, fog);
  assert.notDeepEqual(bytes(texture), darkBytes);
  assert.ok(near(bytes(texture).slice(0, 3), rgb('#eef5f8')) && near(bytes(texture).slice(63 * 4, 63 * 4 + 3), rgb('#cfe3ee')), 'light horizon and top');
  assert.equal(texture.version > 0, true, 'the texture is flagged for upload');
  assert.equal('#' + fog.color.getHexString(), '#eef5f8'); assert.equal(clears.at(-1), '#f4f8f9');
  assert.equal(parts(v.overlays)[0].geometry, geometry, 'the drape was not rebuilt');
  assert.deepEqual(parts(v.overlays).map(part => part.material.color.getHexString()).sort(), ['087354', 'f4f8f9']);
  // Without a sky only the overlays move; a destroyed viewer ignores the call; an unusable overlay palette changes nothing.
  const sky2 = bytes(texture);
  v.setTheme({overlayPalette: dark}); assert.deepEqual(bytes(texture), sky2);
  assert.throws(() => v.setTheme({sky: {...sky, sky: '#000000'}, overlayPalette: {...dark, mint: 'x'}}), /mint/);
  assert.deepEqual(bytes(texture), sky2, 'the sky did not move with a refused palette');
  v.alive = false; v.setTheme({sky: {...sky, sky: '#000000'}}); assert.deepEqual(bytes(texture), sky2);
});

// Contract: without the host's options the renderer keeps v1's palette-derived sky and fog.
test('without a host sky the viewer keeps its palette sky top, ground and fog', () => {
  const v = Object.create(CoastViewer.prototype);
  v.options = {palette: {skyTop: '#111111', ground: '#222222'}};
  assert.deepEqual(v.skyColors, {top: '#111111', horizon: '#222222', fog: '#222222', ground: '#222222'});
  v.options = {palette: {skyTop: '#111111', ground: '#222222'}, sky};
  assert.deepEqual(v.skyColors, {top: sky.sky, horizon: sky.horizon, fog: sky.fog, ground: sky.ground});
});

// Contract: a host cap applies in degrees and is validated; anything else keeps the renderer's own cap (standalone unchanged).
test('maxPitch is a 5 to 90 degree cap, and orbit requests clamp to it', () => {
  const v = Object.create(CoastViewer.prototype);
  const cap = options => { v.options = options; return v.maxPolar; };
  assert.equal(cap({maxPitch: 75}), T.MathUtils.degToRad(75));
  for (const bad of [undefined, NaN, 4.9, 90.1, '75', Infinity]) assert.equal(cap({maxPitch: bad}), Math.PI * .46, String(bad));
  v.options = {maxPitch: 75};
  Object.assign(v, {camera: new T.PerspectiveCamera(42, 1, 2, 1e6), controls: {target: new T.Vector3(), update() {}}});
  v.camera.position.set(1000, 1000, 1000);
  v.applyOrbit(10, 85);
  assert.ok(Math.abs(v.orbitAngles().pitch - 75) < 1e-6, 'an 85 degree request lands on the 75 degree cap');
  v.applyOrbit(10, 60);
  assert.ok(Math.abs(v.orbitAngles().pitch - 60) < 1e-6, 'a request under the cap is kept');
});

// Contract: onFrame fires once per completed frame with a performance.now() stamp, after the render; no callback, no cost.
test('every completed frame reports its time to onFrame', () => {
  const order = [], saved = globalThis.requestAnimationFrame;
  globalThis.requestAnimationFrame = () => 1;
  try {
    const v = Object.create(CoastViewer.prototype);
    Object.assign(v, {alive: true, visible: true, controls: {update() {}, target: new T.Vector3()}, renderer: {render: () => order.push('render')}, scene: new T.Scene(),
      camera: new T.PerspectiveCamera(42, 1, 2, 1e6), labels: [], pins: [], habitat: new T.Group(), host: {dataset: {}, clientWidth: 800, clientHeight: 600},
      options: {onFrame: at => order.push(typeof at)}, $: () => ({textContent: ''})});
    v.camera.position.set(0, 1000, 1000);
    v.animate();
    assert.deepEqual(order, ['render', 'number']);
    v.options = {}; v.animate();
    assert.equal(order.length, 3, 'only the render ran without a callback');
  } finally { globalThis.requestAnimationFrame = saved; }
});

// Contract: the embed passes the new options through and exposes setTheme; a destroyed handle ignores it.
test('mountCoast forwards maxPitch, sky and onFrame, and setTheme reaches the viewer until destroy', async () => {
  const {mountCoast} = await import('../packages/coast/src/embed.ts');
  const node = () => ({hidden: false, textContent: '', dataset: {}, append() {}, remove() {}, setAttribute() {}, closest: () => node()});
  const root = {append() {}, getElementById: () => node(), querySelector: () => node(), querySelectorAll: () => []}, host = {shadowRoot: null, attachShadow: () => root};
  const saved = {document: globalThis.document, DOMParser: globalThis.DOMParser};
  Object.assign(globalThis, {document: {createElement: () => node(), importNode: n => n}, DOMParser: class { parseFromString() { return {getElementById: () => node()}; } }});
  try {
    const calls = [], onFrame = () => {};
    let seen;
    const handle = mountCoast(host, {maxPitch: 75, sky, onFrame}, (_scene, options) => { seen = options; return {setTheme: theme => calls.push(theme), destroy: () => {}}; });
    assert.deepEqual([seen.maxPitch, seen.sky, seen.onFrame], [75, sky, onFrame]);
    handle.setTheme({sky}); assert.deepEqual(calls, [{sky}]);
    handle.destroy(); handle.setTheme({sky}); assert.equal(calls.length, 1, 'inert after destroy');
  } finally { Object.assign(globalThis, saved); }
});

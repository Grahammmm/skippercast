import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {test} from 'node:test';
import * as T from 'three';
import {CoastViewer} from '../packages/coast/src/coast3d/viewer.ts';

const asset = (id, body) => ({url: `/data/sca-068/${id}`, bytes: body.length,
  sha256: createHash('sha256').update(body).digest('hex')});

function viewerFixture(t) {
  // Use real Three geometry, materials and textures without constructing a WebGL context.
  const noop = () => {};
  t.mock.method(globalThis, 'fetch', path => assert.fail(`Unexpected fetch: ${path}`));
  for (const [name, value] of Object.entries({window: {removeEventListener: noop}, cancelAnimationFrame: noop, createImageBitmap: noop})) {
    const prior = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, {configurable: true, writable: true, value});
    t.after(() => prior ? Object.defineProperty(globalThis, name, prior) : delete globalThis[name]);
  }
  const viewer = Object.assign(Object.create(CoastViewer.prototype), {
    alive: true, visible: true, revision: 0, host: {clientWidth: 800, clientHeight: 600}, options: {},
    renderer: {capabilities: {getMaxAnisotropy: () => 1}, dispose: noop, forceContextLoss: noop, domElement: {remove: noop}},
    resize: {disconnect: noop}, controls: {target: new T.Vector3(), dispose: noop}, scene: new T.Scene(),
    terrain: new T.Group(), waters: new T.Group(), seams: new T.Group(), habitat: new T.Group(), currents: new T.Group(),
    loaded: new Map(), textures: new Map(), textureValues: [], textureRetries: new Map(), pending: new Set(), pins: [],
    allowedSources: new Set([2]), visualClasses: new Uint8Array(256), relief: {value: 1},
    cols: 2, rows: 1, span: () => 9000, $: () => ({}), updateShading: noop,
  });
  viewer.coverage = viewer.coverageTexture(2, 1);
  return viewer;
}

function surfacePhoto(mesh) {
  const shader = {uniforms: {}, vertexShader: '', fragmentShader: ''};
  mesh.material.onBeforeCompile(shader);
  return shader.uniforms.landImage.value;
}

test('view refinement retries verified detail once per URL without dropping fallback terrain', async t => {
  const viewer = viewerFixture(t);
  const terrain = Buffer.alloc(20);
  terrain.fill(2, 16); // Four synthetic land source IDs following the four float heights.
  const lod = {...asset('tile.bin', terrain), size: 2, spacing: 4096};
  const detail = {...asset('detail.jpg', 'detail'), kind: 'detail', bounds: [0, 0, 8192, 4096]};
  const fallback = {...asset('fallback.jpg', 'fallback'), kind: 'harbor', bounds: detail.bounds};
  viewer.manifest = {bounds: detail.bounds, waterReferenceM: 0, imagery: [detail, fallback],
    tiles: [0, 4096].map(x => ({x, z: 0, width: 4096, lods: [lod]})), harborTiles: []};
  let now = 0, detailReads = 0, fallbackReads = 0;
  t.mock.method(performance, 'now', () => now);
  let releaseDetail;
  const successfulRead = new Promise(resolve => { releaseDetail = resolve; });
  globalThis.fetch = async path => {
    switch (path) {
      case '/coast-data' + lod.url: return new Response(terrain);
      case '/coast-data' + fallback.url: fallbackReads++; return new Response('fallback');
      case '/coast-data' + detail.url:
        detailReads++;
        if (detailReads === 1) return new Response(null, {status: 503});
        if (detailReads === 2) return new Response('forged'); // Same byte length, wrong digest.
        return successfulRead;
      default: assert.fail(`Unexpected fetch: ${path}`);
    }
  };
  const decoded = [], closed = [];
  globalThis.createImageBitmap = async blob => {
    const id = await blob.text(); decoded.push(id);
    return {close: () => closed.push(id)};
  };

  await viewer.refine();
  const meshes = [...viewer.terrain.children];
  assert.deepEqual(meshes.map(mesh => surfacePhoto(mesh).name), [fallback.url, fallback.url]);
  assert.equal(fallbackReads, 1);
  now = 999;
  await viewer.refine();
  assert.equal(detailReads, 1, 'interaction inside the cooldown does not refetch');
  now = 1000;
  await viewer.refine();
  assert.equal(detailReads, 2, 'a later interaction retries the rejected detail in the same viewer');
  assert.deepEqual(decoded, ['fallback'], 'same-length unverified bytes never reach decoding');
  now = 2999;
  await viewer.refine();
  assert.equal(detailReads, 2, 'repeated failure backs off before another interaction can retry');
  assert.deepEqual(viewer.terrain.children, meshes, 'cooldown and another failure retain the fallback meshes');

  now = 3000;
  const recovery = viewer.refine();
  try {
    assert.equal(detailReads, 3, 'both tiles share one in-flight detail request');
    assert.deepEqual(viewer.terrain.children, meshes, 'old meshes remain attached while verification is pending');
  } finally {
    releaseDetail(new Response('detail'));
    await recovery;
  }
  const photos = viewer.terrain.children.map(surfacePhoto);
  assert.deepEqual(photos.map(photo => photo.name), [detail.url, detail.url]);
  assert.equal(photos[0], photos[1]);
  assert.deepEqual(decoded, ['fallback', 'detail']);
  assert.equal(detailReads, 3);
  viewer.destroy();
  viewer.destroy();
  assert.deepEqual(closed, ['fallback', 'detail']);
});

test('destroy closes a bitmap decoded after destruction without staging a texture', async t => {
  const viewer = viewerFixture(t);
  const image = asset('late.jpg', 'late');
  globalThis.fetch = async path => {
    assert.equal(path, '/coast-data' + image.url);
    return new Response('late');
  };
  let finishDecode, startDecode, closed = 0;
  const started = new Promise(resolve => { startDecode = resolve; });
  globalThis.createImageBitmap = () => new Promise(resolve => {
    finishDecode = () => resolve({close: () => closed++});
    startDecode();
  });
  const rejected = assert.rejects(viewer.texture(image), /Viewer disposed/);
  await Promise.race([started, rejected]);
  viewer.destroy();
  finishDecode();
  await rejected;
  assert.equal(closed, 1);
  assert.equal(viewer.textureValues.length, 0);
});

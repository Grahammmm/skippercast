import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {localAsset, validateMvpManifest} from '../packages/coast/src/coast3d/mvp.ts';
const fixture = JSON.parse(readFileSync(new URL('../research/scripts/coast_mvp/fixtures/viewer-demo/manifest.json', import.meta.url)));
test('C3 fixture is explicit synthetic terrain with complete source rights', () => {
  const m = validateMvpManifest(fixture);
  assert.equal(m.synthetic, true); assert.equal(m.tileZoom, 12);
  assert.equal(m.sources.length, 1); assert.match(m.sources[0].datum, /synthetic/);
});
test('C3 rejects missing attribution, malformed bounds and duplicate source ids', () => {
  for (const change of [m=>delete m.sources[0].license, m=>m.sources[0].url='javascript:alert(1)',
    m=>m.sources.push(m.sources[0]), m=>m.bounds.reverse(), m=>m.center=[0,0],
    m=>m.tileZoom=NaN, m=>m.sources[0].resolutionM=0, m=>delete m.synthetic]) {
    const m=structuredClone(fixture); change(m); assert.throws(()=>validateMvpManifest(m));
  }
});
test('C3 tile reads stay under the local manifest directory', () => {
  const base=new URL('http://localhost:5173/fixtures/demo/');
  assert.equal(localAsset('{z}/{x}/{y}.png', base),base+'{z}/{x}/{y}.png');
  assert.equal(localAsset('terrain.png', base),base+'terrain.png');
  for(const path of ['../private.png','https://remote.example/tiles','//remote.example/x','/absolute',
    '%2e%2e/private','nested%2f..%2fprivate','%252e%252e/private','terrain.png?url=https://x','terrain.png#fragment','..\\private']) assert.throws(()=>localAsset(path,base),path);
});
import {decodeMapboxElevation as dec, encodeMapboxElevation as enc, maskTerrainRgba} from '../packages/coast/src/coast3d/mvp-mask.ts';
function tile(size, hole) {
  const d = new Uint8ClampedArray(size * size * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const i = (y * size + x) * 4, inHole = hole(x, y);
    const [r, g, b] = inHole ? [0, 0, 0] : enc(-(30 + 5 * x + y));
    d.set([r, g, b, inHole ? 0 : 255], i);
  }
  return d;
}
const elevations = (d) => Array.from({length: d.length / 4}, (_, i) => dec(d[i * 4], d[i * 4 + 1], d[i * 4 + 2]));
test('C3 regression: raw RGB decode of an alpha=0 cell is a false -10000 m cliff', () => {
  const raw = tile(16, (x, y) => x > 5 && x < 10 && y > 5 && y < 10);
  assert.equal(Math.min(...elevations(raw)), -10000);
});
test('C3 masked path: alpha=0 hole never yields elevation below the real minimum', () => {
  const size = 16, raw = tile(size, (x, y) => x > 5 && x < 10 && y > 5 && y < 10 || x === 0);
  const real = Math.min(...elevations(raw).filter((_, i) => raw[i * 4 + 3] === 255));
  const out = maskTerrainRgba(raw, size, size);
  assert.ok(out.unsupported > 0);
  const e = elevations(out.data);
  assert.ok(Math.min(...e) >= real - 1e-6, `min ${Math.min(...e)} < ${real}`);
  assert.ok(Math.max(...e) <= Math.max(...elevations(raw).filter((_, i) => raw[i * 4 + 3] === 255)) + 1e-6);
  for (let i = 0; i < size * size; i++) assert.equal(out.data[i * 4 + 3], 255);
  for (let i = 0; i < size * size; i++) if (raw[i * 4 + 3] === 255) assert.deepEqual(out.data.slice(i * 4, i * 4 + 3), raw.slice(i * 4, i * 4 + 3));
});
test('C3 masked path: partially transparent cells are unsupported; fully empty tile is rejected', () => {
  const raw = tile(4, () => false); raw[3] = 128;
  assert.equal(maskTerrainRgba(raw, 4, 4).unsupported, 1);
  assert.equal(maskTerrainRgba(tile(4, () => true), 4, 4), null);
  assert.throws(() => maskTerrainRgba(new Uint8ClampedArray(8), 4, 4));
});

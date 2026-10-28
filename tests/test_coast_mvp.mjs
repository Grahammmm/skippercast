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

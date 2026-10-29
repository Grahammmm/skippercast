import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as mvp from '../packages/coast/src/coast3d/mvp.ts';
import {localAsset, validateMvpManifest} from '../packages/coast/src/coast3d/mvp.ts';
const fixture = JSON.parse(readFileSync(new URL('../research/scripts/coast_mvp/fixtures/viewer-demo/manifest.json', import.meta.url)));
test('C3 fixture is explicit synthetic terrain with complete source rights', () => {
  const m = validateMvpManifest(fixture);
  assert.equal(m.synthetic, true); assert.equal(m.tileZoom, 12);
  assert.equal(m.sources.length, 1); assert.match(m.sources[0].datum, /synthetic/);
});
test('Measured manifests fail closed even without the W11A group', () => {
  const measured=structuredClone(fixture); measured.synthetic=false;
  measured.sources[0].permissionRequired=false;
  assert.throws(()=>validateMvpManifest(measured));
  measured.sources[0].permissionRequired=true;
  assert.equal(validateMvpManifest(measured), measured);
  assert.ok(mvp.manifestHoldLines(measured).some(line=>line.includes('Publication held')));
});
const w11a = JSON.parse(readFileSync(new URL('../research/scripts/coast_mvp/fixtures/w11a-viewer-manifest.json', import.meta.url)));
test('Held source and manifest copy preserves exact rights and datum caveats', () => {
  const s=w11a.sources[0];
  assert.equal(mvp.sourceRightsText(s), 'Rights review required — publication held. '+s.datumNote);
  assert.equal(mvp.sourceRightsText({...s, rightsStatus:'needs_permission', csumbInvolved:true}),
    'Permission required — CSUMB involved; publication held. '+s.datumNote);
  const lines=mvp.manifestHoldLines(w11a);
  assert.ok(lines.includes(w11a.navigation));
  for (const line of w11a.limitations) assert.ok(lines.includes(line));
});
test('Preview manifest selection confines JSON to a repo-relative local path', () => {
  const root=new URL('http://localhost:5179/'), fallback='./fixtures/viewer-demo/manifest.json';
  assert.equal(mvp.previewManifestUrl('', root, fallback), fallback);
  const valid='var/w11b/c2/viewer-manifest.json';
  assert.equal(mvp.previewManifestUrl('?manifest='+valid, root, fallback), root+valid);
  for (const path of ['/abs.json','../x.json','%2e%2e/x.json','https://remote.example/m.json',
    '//remote.example/m.json','m.json?x=1','m.txt','nested/../x.json','x%2fy.json','m.json#hash','',
    '\t../x.json','nested/\t../x.json']) {
    assert.throws(()=>mvp.previewManifestUrl('?manifest='+encodeURIComponent(path), root, fallback),path);
  }
});
test('W11A additive group validates atomically and keeps publication held', () => {
  const m = validateMvpManifest(w11a);
  assert.equal(m.sources[0].permissionRequired, true);
  assert.equal(m.sources[0].rightsStatus, 'review_required');
  assert.equal(validateMvpManifest(fixture).status, undefined);
  for (const change of [m=>m.publicationHeld=false, m=>delete m.publicationHeld,
    m=>m.status='accepted', m=>m.sources[0].sha256='A'.repeat(64),
    m=>m.sources[0].sha256='a'.repeat(63), m=>m.sources[0].termsUrl='http://example.org',
    m=>m.sources[0].termsUrl='javascript:alert(1)', m=>m.sources[0].termsUrl='https://a:b@example.org',
    m=>m.sources[0].rightsStatus='cleared', m=>m.sources[0].csumbInvolved=true,
    m=>m.sources[0].contributedCells=0, m=>m.limitations=[],
    m=>m.provenance.assets={'../x.png':'a'.repeat(64)},
    m=>m.provenance.assets={'https://x/y.png':'a'.repeat(64)}, m=>delete m.provenance]) {
    const invalid=structuredClone(w11a); change(invalid);
    assert.throws(()=>validateMvpManifest(invalid));
  }
  for (const field of ['status','publicationHeld','navigation','limitations','provenance']) {
    const invalid=structuredClone(w11a); delete invalid[field];
    assert.throws(()=>validateMvpManifest(invalid),field);
  }
  for (const field of ['sha256','termsUrl','contributedCells','datumNote','csumbInvolved','rightsStatus']) {
    const invalid=structuredClone(w11a); delete invalid.sources[0][field];
    assert.throws(()=>validateMvpManifest(invalid),field);
  }
  for (const field of ['sha256','termsUrl','rightsStatus']) {
    const partial=structuredClone(fixture); partial.sources[0][field]=w11a.sources[0][field];
    assert.throws(()=>validateMvpManifest(partial),field);
  }
  const csumb=structuredClone(w11a);
  csumb.sources[0].csumbInvolved=true; csumb.sources[0].rightsStatus='needs_permission';
  assert.equal(validateMvpManifest(csumb),csumb);
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

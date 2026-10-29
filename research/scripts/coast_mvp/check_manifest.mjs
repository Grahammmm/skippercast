// Offline schema/relative-asset check against the unchanged C3 viewer contract.
// This does not load a map, fetch tiles, or attest science/publication acceptance.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {localAsset, validateMvpManifest} from '../../../packages/coast/src/coast3d/mvp.ts';

if (process.argv.length !== 3) throw Error('Usage: node research/scripts/coast_mvp/check_manifest.mjs MANIFEST');
const manifest = validateMvpManifest(JSON.parse(readFileSync(process.argv[2], 'utf8')));
const base = new URL('http://localhost/preview/');
for (const path of [manifest.terrain, manifest.contours]) {
  assert.ok(localAsset(path, base).startsWith(base.href));
}
assert.equal(manifest.status, 'review_required');
assert.equal(manifest.publicationHeld, true);
assert.ok(manifest.sources.every(s => s.permissionRequired && /^[0-9a-f]{64}$/.test(s.sha256)));
console.log('MvpManifest accepted; both tile templates confined; all contributors held.');

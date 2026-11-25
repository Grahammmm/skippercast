import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {scopeRoute, previewContourDigest, previewOrigin} from '../scripts/relief/central_isolated_preview.mjs';

const region = 'cambria-san-simeon';
const overview = `/regions/${region}/depth-contours-overview.geojson`;
const detail = `/regions/${region}/depth-contours.geojson`;
const body = Buffer.from('{"band":"overview"}');
const hash = value => createHash('sha256').update(value).digest('hex');
const style = 'a'.repeat(64);
const rows = {[region]: {style, contours: {[overview]: hash(body), [detail]: hash('detail')}}};
const local = 'http://127.0.0.1:48000';

// A producer and renderer can agree on the region while disagreeing on which band arrived.
// Verify exact response bytes against the build binding, not parsed JSON or a source's expiry.
test('only the exact locally bound contour band supplies a style digest', async () => {
  assert.equal(await previewContourDigest(rows, local, region, overview, body), style);
  for (const [origin, id, path, bytes] of [
    [local, region, detail, body], [local, region, overview, Buffer.concat([body, Buffer.from('\n')])],
    [local, 'morro-bay', overview, body], [local, 'monterey-point-sur', overview, body],
    ['https://skippercast.com', region, overview, body],
  ]) assert.equal(await previewContourDigest(rows, origin, id, path, bytes), null);
});

// A deployed copy, generic static-file fallback or an unlisted region must not activate the local preview.
test('rejects production origins, release pointers, unknown regions and unlisted routes', () => {
  const files = new Set(['client/regions/index.json', `client${overview}`, 'client/regions/morro-bay/region.json', 'client/sw.js']);
  const bindings = new Set([region]);
  assert.equal(previewOrigin(local), true);
  for (const site of ['http://127.0.0.1.evil.test:5000', 'https://127.0.0.1:5000', 'http://localhost:5000']) assert.equal(previewOrigin(site), false);
  assert.equal(scopeRoute(overview, 'aabbccddee', files, bindings), `client${overview}`);
  for (const path of ['/regions/morro-bay/region.json', '/catalog/relief/cambria-san-simeon.json', '/sw.js', '/not-here', '/regions/%2e%2e/foo', detail]) {
    assert.equal(scopeRoute(path, 'aabbccddee', files, bindings), null, path);
  }
});

import assert from 'node:assert/strict';
import {test} from 'node:test';
import {clientAsset, problems} from '../scripts/relief/central_built_navigation.mjs';

const cambria = 'cambria-san-simeon', monterey = 'monterey-point-sur';
const resource = (region, kind) => kind === 'pointer' ? `/catalog/relief/${region}.json` : `/regions/${region}/depth-contours.geojson`;
const read = (region, kind) => ({path:resource(region, kind),status:200});

// A false app-shell fallback can look like a successful static resource read at HTTP 200.
test('the stable page aliases alone select fingerprinted shells', () => {
  const build = '1124a2e85b';
  assert.equal(clientAsset('/map', build), 'client/app.1124a2e85b.html');
  assert.equal(clientAsset('/sources', build), 'client/sources.1124a2e85b.html');
  assert.equal(clientAsset(resource(monterey, 'contour'), build), `client${resource(monterey, 'contour')}`);
  for (const invalid of ['/../map', '/%2e%2e/map', '//map']) assert.equal(clientAsset(invalid, build), null);
  assert.throws(() => clientAsset('/map', 'main'), /fingerprint/);
});

// A correct URL with stale Chart state or a foreign fetch must not pass history validation.
test('terrain-only Back rejects a stale line, credit, resource or displayed region', () => {
  const restored = {urlRegion:monterey,shownRegion:monterey,shading:true,drawn:0,contourRows:0,requests:[read(monterey, 'pointer')]};
  assert.deepEqual(problems(monterey, restored), []);
  assert.ok(problems(monterey, {...restored,drawn:3,contourCredit:'old Cambria source'}).includes('stale contour on terrain-only Chart'));
  assert.ok(problems(monterey, {...restored,shownRegion:cambria}).includes('wrong region in URL or Chart'));
  assert.ok(problems(monterey, {...restored,requests:[...restored.requests,read(cambria, 'contour')]}).includes('unexpected region resource requested'));
});

// A correctly pinned pointer and shading are insufficient when the build fails to load its published pair.
test('contour arrival needs both visible lines and an own-region resource read', () => {
  const seen = {urlRegion:cambria,shownRegion:cambria,shading:true,diagnostic:true,drawn:3,contourRows:1,requests:[read(cambria, 'pointer'),read(cambria, 'contour')]};
  assert.deepEqual(problems(cambria, seen), []);
  assert.ok(problems(cambria, {...seen,diagnostic:false}).includes('expected contour absent from Chart'));
  assert.ok(problems(cambria, {...seen,requests:[read(cambria, 'pointer')]}).includes('no own-region contour read'));
});

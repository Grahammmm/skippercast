import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {regionList} from '../server/catch-region.ts';
import {watchCoverage} from '../server/spot-watch-coverage.ts';

const {regions} = regionList([
  {id: 'other', bounds: [-30, 60, -24, 64]},
  {id: 'target', bounds: [-40, 50, -34, 54]},
]);
const inside = {lat: 52, lon: -37};

// C1: exercise the exported API with the resolver's parsed regions; typecheck covers its signature.
test('C1: the named export accepts parsed regions and returns the inside verdict', () => {
  assert.equal(watchCoverage(inside, 'target', regions), 'inside');
});

for (const [edge, spot] of [
  ['west', {...inside, lon: -40}],
  ['south', {...inside, lat: 50}],
  ['east', {...inside, lon: -34}],
  ['north', {...inside, lat: 54}],
]) {
  test(`C2: equality at the ${edge} edge is inside`, () => {
    assert.equal(watchCoverage(spot, 'target', regions), 'inside');
  });
}

for (const [edge, spot] of [
  ['west', {...inside, lon: -40.01}],
  ['south', {...inside, lat: 49.99}],
  ['east', {...inside, lon: -33.99}],
  ['north', {...inside, lat: 54.01}],
]) {
  test(`C2: just beyond the ${edge} edge is outside`, () => {
    assert.equal(watchCoverage(spot, 'target', regions), 'outside-region');
  });
}

test('C2: another region cannot supply coverage for the requested region', () => {
  assert.equal(watchCoverage({lat: 62, lon: -27}, 'target', regions), 'outside-region');
});

test('C2: a missing region id does not fall back to the region containing the point', () => {
  assert.equal(watchCoverage(inside, 'missing', regions), 'unknown-region');
});

for (const [reason, spot] of [
  ['numeric-string latitude', {...inside, lat: '52'}],
  ['numeric-string longitude', {...inside, lon: '-37'}],
  ['NaN latitude', {...inside, lat: NaN}],
  ['infinite longitude', {...inside, lon: Infinity}],
  ['north pole', {...inside, lat: 90}],
  ['south pole', {...inside, lat: -90}],
  ['positive antimeridian', {...inside, lon: 180}],
  ['negative antimeridian', {...inside, lon: -180}],
]) {
  test(`C2: ${reason} is a bad position`, () => {
    assert.equal(watchCoverage(spot, 'target', regions), 'bad-position');
  });
}

test('C2: a bad position is reported before an unknown region', () => {
  assert.equal(watchCoverage({...inside, lat: null}, 'missing', regions), 'bad-position');
});

test('C3: coverage has only a type dependency and no private storage or route references', () => {
  const source = readFileSync(new URL('../server/spot-watch-coverage.ts', import.meta.url), 'utf8');
  const imports = source.match(/^\s*import\b[^;]*/gm) ?? [];
  assert.deepEqual(imports.map(statement => /^\s*import\s+(type)\b.*\bfrom\s+['"]([^'"]+)['"]/s.exec(statement)?.slice(1)), [
    ['type', './catch-region.ts'],
  ]);
  assert.equal(/saved_spots|api\/spots|routes\/spots/.test(source), false);
});

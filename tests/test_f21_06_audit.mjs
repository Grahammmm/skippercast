import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {copyFileSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {gzipSync} from 'node:zlib';
import {boundaryFingerprint, geometryCoveredByBounds, screenPlace} from '../dist/geo-screen.js';
import {assetURL, getRegion} from '../dist/region.js';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const box = (x, y, d) => ({type: 'Polygon', coordinates: [[[x-d,y-d], [x+d,y-d], [x+d,y+d], [x-d,y+d], [x-d,y-d]]]});
const region = 'morro-bay';
const {bounds, minimum_features} = getRegion().mpa;
const [west, south, east, north] = bounds;
const x = (west+east)/2, y = (south+north)/2;
const closures = Array.from({length: minimum_features}, (_, i) => ({type: 'Feature',
  properties: {NAME: `Synthetic closure ${i}`}, geometry: box(x, y+(north-south)/4, .01)}));
const features = assetURL('closures') ? [...closures, ...closures] : closures;
const fingerprint = boundaryFingerprint(features.map(f => f.geometry), bounds, features.map(f => f.properties.NAME));
const screen = {coversGeometry: g => geometryCoveredByBounds(g, bounds), exportExclusions: () => ({features})};
const last = 'synthetic-outside-top-50';
const reef = (id, longitude, latitude, score) => {
  const geometry = box(longitude, latitude, .001), waypoint = {longitude, latitude};
  return {type: 'Feature', geometry, properties: {id, region, tier: 2, status: 'habitat', exportable: true,
    screen: {status: 'pass'}, waypoint, depth_min_ft: 20, depth_max_ft: 40, terrain: {score, grade: 'A'},
    fit: {lingcod: 3, 'rockfish-reef': 3}, resolution_m: 2, source_ids: ['synthetic'], metric_support_fraction: 1,
    protected_place: screenPlace(screen, {...waypoint, geometries: [geometry]})}};
};
const full = [...Array.from({length: 51}, (_, i) => reef(i === 50 ? last : `synthetic-${i}`,
  x+.006*(i%8), y+.006*Math.floor(i/8), 100-i)), reef('synthetic-refused', x, y+(north-south)/4, 100)];
// Put the refused target first in slim, not last: an index-based join must fail the positive control.
const slim = full.map(f => ({...f, geometry: null})).reverse();

function stage(t) {
  const root = mkdtempSync(join(tmpdir(), 'reef-slim-parity-'));
  t.after(() => rmSync(root, {recursive: true, force: true}));
  const script = join(root, 'scripts/reef_slim_parity.mjs');
  const write = (path, value) => writeFileSync(join(root, path), JSON.stringify(value));
  for (const dir of ['scripts', 'dist/data', `dist/regions/${region}`]) mkdirSync(join(root, dir), {recursive: true});
  // Run the unchanged CLI entry point and real code, with only synthetic files beside it.
  copyFileSync(new URL('../scripts/reef_slim_parity.mjs', import.meta.url), script);
  for (const path of ['dist/protected-areas.js', 'dist/reef-trip-data.js', 'dist/geo-screen.js', 'web']) {
    symlinkSync(fileURLToPath(new URL(`../${path}`, import.meta.url)), join(root, path));
  }
  write('dist/data/protected-areas.geojson', {type: 'FeatureCollection', region_id: region, features: closures});
  write('dist/data/atlas.json', {targets: []});
  write(`dist/regions/${region}/region.json`, {harbor: {name: 'Synthetic harbor', longitude: x, latitude: y}});
  return (targets, fullTargets = full) => {
    const now = Date.now(), expires_at = new Date(now+2*3600000).toISOString();
    const base = {type: 'FeatureCollection', region, expires_at, protected_screen: {fingerprint}};
    const fullBytes = Buffer.from(JSON.stringify({...base, features: fullTargets}));
    const export_sha256 = sha(fullBytes);
    const raw = Buffer.from(JSON.stringify({...base, slim_of: export_sha256, features: targets}));
    const slimBytes = gzipSync(raw), slim_sha256 = sha(slimBytes), slim_file = `habitat-slim-${slim_sha256.slice(0, 16)}.geojson.gz`;
    const export_file = 'habitat-export.geojson';
    writeFileSync(join(root, export_file), fullBytes);
    writeFileSync(join(root, slim_file), slimBytes);
    write('manifest.json', {region, status: 'ready', archive_sha256: 'a'.repeat(64), expires_at, built_at: new Date(now).toISOString(),
      export_file, export_sha256, export_bytes: fullBytes.length, slim_file, slim_sha256, slim_bytes: slimBytes.length, slim_decoded_bytes: raw.length});
    const result = spawnSync(process.execPath, [script, root, '1'], {encoding: 'utf8', timeout: 10000});
    assert.ifError(result.error);
    return result;
  };
}

const output = result => result.stdout + result.stderr;

test('the parity CLI catches a wrong slim verdict even when all top-50 rankings match', t => {
  const run = stage(t), positive = run(slim);
  assert.equal(positive.status, 0, output(positive));
  assert.match(positive.stdout, /52 checked, 1 refused by the run-time outline check, eligibility mismatches 0/);
  assert.match(positive.stdout, /cases 18, picks compared 900, reefs 52, differences 0/);

  // Keep full geometry/verdicts and the content-addressed publication valid; flip only the lowest-ranked clear reef's slim verdict.
  const flipped = slim.map(f => f.properties.id === last
    ? {...f, properties: {...f.properties, protected_place: {...f.properties.protected_place, screened: false}}} : f);
  const negative = run(flipped);
  assert.doesNotMatch(negative.stdout, /^DIFFERENT /m, output(negative));
  assert.equal(negative.status, 1, output(negative));
  assert.match(negative.stdout, /ELIGIBILITY DIFFERS synthetic-outside-top-50 /);
  assert.match(negative.stdout, /cases 18, picks compared 900, reefs 52, differences 1\b/);
});

test('the parity CLI requires one target with each stable ID in both exports', t => {
  const run = stage(t), [refused, ...rest] = slim;
  for (const [name, result, diagnostic] of [
    ['missing slim target', run(rest), /Missing slim target ID: synthetic-refused/],
    ['extra slim target', run([...slim, {...refused, properties: {...refused.properties, id: 'slim-only'}}]), /Unexpected slim target ID: slim-only/],
    ['missing ID field', run([{...refused, properties: {...refused.properties, id: undefined}}, ...rest]), /the brief did not get the slim file/],
    ['duplicate slim ID', run([...slim, refused]), /the brief did not get the slim file/],
    ['duplicate full ID', run(slim, [...full, full[0]]), /unqualified or duplicate area/],
  ]) {
    assert.equal(result.status, 1, `${name}: ${output(result)}`);
    assert.match(output(result), diagnostic, name);
  }
});

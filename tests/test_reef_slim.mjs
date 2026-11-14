// SC-PERF-REEFDIET-1: the brief reads the slim reef file (attributes + publish-time protected-area verdicts, no outlines) instead of the 15 MB export.
// Covers: the slim load equals the full load; the loader reads only the properties slim_fields.json lists (a reader asking for a dropped field fails
// here); every listed property is needed; any unusable slim file falls back to the full export; the ranking is identical from old / full / slim over the
// fixture set; a screen holding other boundary data reloads the full export; the feed serves the slim file under the manifest's gate.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {gzipSync} from 'node:zlib';
import test from 'node:test';
import {boundaryFingerprint, closureHits, geometryCoveredByBounds, pointGeometry, pointInGeometry, screenPlace} from '../dist/geo-screen.js';
import {loadReefTrip, loadReefTripBrief} from '../dist/reef-trip-data.js';
import {ranking, reefPublication, settleReefPublication} from '../web/ranking.ts';
import {serveFeed, useBucket} from '../server/feeds.ts';

const readJSON = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const CASES = readJSON('./fixtures/protected_screen_cases.json');
const LISTED = readJSON('../src/skippercast/seafloor/slim_fields.json').properties;
const nameOf = f => f.properties?.FULLNAME || f.properties?.NAME || null;
const sha = async bytes => Buffer.from(await crypto.subtle.digest('SHA-256', bytes)).toString('hex');

/** The planner's screen (dist/protected-areas.js `initProtectedAreas`) over `features`, as that code answers. */
const plannerScreen = (features = CASES.boundary, bounds = CASES.bounds) => {
  const covers = g => geometryCoveredByBounds(g, bounds);
  return {ready: () => true, coversGeometry: covers, exportExclusions: () => ({checked_at: 'x', features}),
    fingerprint: () => boundaryFingerprint(features.map(f => f.geometry), bounds, features.map(nameOf)),
    pointAllowed: p => covers(pointGeometry(p.longitude, p.latitude)) && !closureHits([pointGeometry(p.longitude, p.latitude)], features).length,
    geometryAllowed: g => covers(g) && !closureHits([g], features).length};
};
const box = (lon, lat, d = .0015) => ({type: 'Polygon', coordinates: [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]]});

// The export's features, as src/skippercast/seafloor/publish.py writes them (verdicts from the browser's own screenPlace, standing in for protected_screen.py).
const outline = r => pointInGeometry([r.longitude, r.latitude], r.geometry) ? r.geometry : box(r.longitude, r.latitude);
const properties = (r, i, verdict) => ({id: r.id, region: 'morro-bay', tier: 2, status: 'habitat', exportable: true, screen: {status: 'pass', checks: ['land', 'depth', 'x'.repeat(40)]},
  waypoint: {longitude: r.longitude, latitude: r.latitude, basis: 'Interior reference point'}, source_ids: ['survey'], source_urls: ['https://example.test/s'],
  source_year: 2008, resolution_m: 2, metric_support_fraction: .9, interpolation_mask: 'measured',
  substrate: {known_fraction: .5, same_survey_as_depth: true, independent_confirmation: true}, independent_evidence: [{family: 'other'}],
  source_rights: [{source_id: 'survey', attribution: 'Test Survey', notice: 'Credit the survey.', policy_url: 'https://example.test/terms'}], depth_min_ft: 40 + i, depth_max_ft: 90 + i, vertical_datum: 'MLLW', terrain: {score: 70 + i, grade: 'A', relief_210m_m: 3 + i}, fit: {lingcod: 3, 'rockfish-reef': 3},
  area_ha: 2 + i / 10, extra_ignored: 'only the full export carries this', protected_place: verdict});
const features = (screen = plannerScreen()) => CASES.reefs.map((r, i) => {
  const geometry = outline(r);
  return {type: 'Feature', geometry, properties: properties(r, i, screenPlace(screen, {latitude: r.latitude, longitude: r.longitude, geometries: [geometry]}))};
});
const slimOf = (feats, drop = []) => feats.map(f => ({type: 'Feature', geometry: null,
  properties: Object.fromEntries(LISTED.filter(k => k in f.properties && !drop.includes(k)).map(k => [k, k === 'screen' ? {status: f.properties.screen.status} : f.properties[k]]))}));

/** A served publication: the manifest and the files, with `change` to break pieces. */
async function publication({feats = features(), fingerprint = plannerScreen().fingerprint(), slim = slimOf(feats), change = () => {}} = {}) {
  const expires = new Date(Date.now() + 36e5).toISOString();
  const doc = {type: 'FeatureCollection', schema_version: 1, region: 'morro-bay', expires_at: expires, features: feats, protected_screen: {fingerprint}};
  const full = gzipSync(JSON.stringify(doc), {mtime: 0}), fullSha = await sha(full);
  const slimDoc = {type: 'FeatureCollection', schema_version: 1, region: 'morro-bay', expires_at: expires, slim_of: fullSha, protected_screen: {fingerprint}, features: slim};
  const slimRaw = Buffer.from(JSON.stringify(slimDoc)), slimGz = gzipSync(slimRaw, {mtime: 0});
  const manifest = {region: 'morro-bay', status: 'ready', archive_sha256: 'a'.repeat(64), expires_at: expires, built_at: new Date().toISOString(),
    export_file: 'habitat-export.geojson.gz', export_sha256: fullSha, export_bytes: full.length, export_decoded_bytes: JSON.stringify(doc).length,
    slim_file: `habitat-slim-${(await sha(slimGz)).slice(0, 16)}.geojson.gz`, slim_sha256: await sha(slimGz), slim_bytes: slimGz.length, slim_decoded_bytes: slimRaw.length};
  const files = {'habitat-export.geojson.gz': full, [manifest.slim_file]: slimGz};
  change({manifest, files, slimDoc});
  const asked = [];
  const fetchImpl = async url => { const name = String(url).split('/').at(-1); asked.push(name); return String(url).includes('manifest-') ? new Response(JSON.stringify(manifest)) : new Response(files[name]); };
  return {manifest, files, fetchImpl, asked, opts: {fetchImpl}};
}

test('the slim load gives the full load\'s targets, no outlines, and the same fingerprint', async () => {
  const p = await publication(), full = await loadReefTrip('morro-bay', p.opts), slim = await loadReefTripBrief('morro-bay', p.opts);
  assert.equal(slim.slim, true); assert.equal(full.slim, undefined);
  assert.deepEqual(slim.targets, full.targets);
  assert.deepEqual(slim.areas, []); assert.equal(full.areas.length, CASES.reefs.length);
  assert.equal(slim.protected_fingerprint, full.protected_fingerprint);
  assert.ok(slim.targets.every(t => t.protected_place), 'every target carries its verdict');
  assert.equal(p.asked.filter(n => n === 'habitat-export.geojson.gz').length, 1, 'the brief load did not fetch the full export');
});

test('a reader asking for a dropped field fails: the loader reads only the listed properties', async () => {
  const p = await publication(), reads = new Set(), parse = JSON.parse;
  JSON.parse = (text, reviver) => {
    const v = parse(text, reviver);
    if (v?.type === 'FeatureCollection') for (const f of v.features) f.properties = new Proxy(f.properties, {get: (o, k, r) => { if (typeof k === 'string') reads.add(k); return Reflect.get(o, k, r); }});
    return v;
  };
  try { await loadReefTrip('morro-bay', {...p.opts, slim: true}); } finally { JSON.parse = parse; }
  assert.ok(reads.size > 10, 'the probe saw the loader read the properties');
  const dropped = [...reads].filter(k => !LISTED.includes(k));
  assert.deepEqual(dropped, [], `the loader reads properties the slim file drops: ${dropped}`);
  // The check itself: a reader of a property the list does not name is caught.
  const unlisted = [...reads, 'geometry_hash'].filter(k => !LISTED.includes(k));
  assert.deepEqual(unlisted, ['geometry_hash']);
  // And the fixture's full-only property is not in the slim file.
  assert.ok(!('extra_ignored' in slimOf(features())[0].properties));
});

test('every listed property is needed: without it the slim load fails or differs from the full load', async () => {
  const full = await loadReefTrip('morro-bay', (await publication()).opts);
  for (const key of LISTED) {
    if (key === 'tier' || key === 'region' || key === 'exportable') continue;   // checked for acceptance only (a missing one throws, below)
    const p = await publication({slim: slimOf(features(), [key])});
    let same;
    try { same = JSON.stringify((await loadReefTrip('morro-bay', {...p.opts, slim: true})).targets) === JSON.stringify(full.targets); } catch { same = false; }
    assert.equal(same, false, `${key} is listed but nothing reads it`);
  }
  for (const key of ['tier', 'region', 'exportable', 'protected_place']) {
    const p = await publication({slim: slimOf(features(), [key])});
    await assert.rejects(loadReefTrip('morro-bay', {...p.opts, slim: true}), /unqualified|verdict/, key);
  }
});

test('any unusable slim file falls back to the full export (outlines, run-time check)', async () => {
  const breaks = {
    'no slim file in the manifest': ({manifest}) => { for (const k of ['slim_file', 'slim_sha256', 'slim_bytes', 'slim_decoded_bytes']) delete manifest[k]; },
    'slim bytes changed': ({manifest, files}) => { const n = manifest.slim_file; files[n] = Buffer.from(files[n]); files[n][20] ^= 1; },
    'slim hash is not the file\'s': ({manifest}) => { manifest.slim_sha256 = 'f'.repeat(64); },
    'slim file name is not the published one': ({manifest}) => { manifest.slim_file = 'other.geojson.gz'; },
    'slim file name is not its own hash': ({manifest, files}) => { files['habitat-slim-0000000000000000.geojson.gz'] = files[manifest.slim_file]; manifest.slim_file = 'habitat-slim-0000000000000000.geojson.gz'; },
    'the old fixed slim name': ({manifest, files}) => { files['habitat-slim.geojson.gz'] = files[manifest.slim_file]; manifest.slim_file = 'habitat-slim.geojson.gz'; },
  };
  for (const [name, change] of Object.entries(breaks)) {
    const p = await publication({change}), got = await loadReefTripBrief('morro-bay', p.opts);
    assert.equal(got.slim, undefined, name); assert.equal(got.areas.length, CASES.reefs.length, name);
  }
  const noVerdict = slimOf(features()); delete noVerdict[3].properties.protected_place;
  const p1 = await publication({slim: noVerdict}), a = await loadReefTripBrief('morro-bay', p1.opts);
  assert.equal(a.slim, undefined, 'one reef without a verdict'); assert.equal(a.areas.length, CASES.reefs.length);
  // A slim file made for another export (its `slim_of` is not this export's hash), served under a manifest that names its bytes.
  const other = await publication({feats: features().slice(1)}), here = await publication();
  const swapped = {...here.manifest, slim_file: other.manifest.slim_file, slim_sha256: other.manifest.slim_sha256, slim_bytes: other.manifest.slim_bytes, slim_decoded_bytes: other.manifest.slim_decoded_bytes};
  const b = await loadReefTripBrief('morro-bay', {fetchImpl: async url => String(url).includes('manifest-') ? new Response(JSON.stringify(swapped))
    : new Response(String(url).endsWith(other.manifest.slim_file) ? other.files[other.manifest.slim_file] : here.files['habitat-export.geojson.gz'])});
  assert.equal(b.slim, undefined, 'a slim file made for another export'); assert.equal(b.areas.length, CASES.reefs.length);
});

const DATA = {region: {...readJSON('../dist/regions/morro-bay/region.json'), id: 'morro-bay'}, atlas: readJSON('../dist/data/atlas.json'), survey: null, geology: null};
const rank = (loaded, screen, c = {}) => ranking({region: 'morro-bay', profile: c.profile ?? 'boat', target: c.coast ?? 'lingcod', coast: c.coast ?? 'lingcod', data: DATA,
  screen: {status: 'ready', note: '', source: 't', boundaries: [], until: Infinity}, terrain: {state: 'idle'}, now: Date.now(), reachNm: c.reachNm ?? null, place: () => ({state: 'water'}),
  publication: {state: 'ready', region: 'morro-bay', loaded}, plannerScreen: {state: 'loaded', region: 'morro-bay', screen}, top: 50});
const withoutVerdicts = l => { const {protected_fingerprint, ...rest} = l; return {...rest, targets: l.targets.map(({protected_place, ...t}) => t)}; };

test('parity: the ranking is identical from the old check, the full export with verdicts, and the slim file (fixture set)', async () => {
  const p = await publication(), screen = plannerScreen(), full = await loadReefTrip('morro-bay', p.opts), slim = await loadReefTripBrief('morro-bay', p.opts);
  let compared = 0;
  for (const coast of ['lingcod', 'rockfish-reef', 'all']) for (const profile of ['boat', 'kayak', 'spear']) for (const reachNm of [null, 8]) {
    const c = {coast, profile, reachNm}, old = rank(withoutVerdicts(full), screen, c), now = rank(full, screen, c), lean = rank(slim, screen, c);
    assert.deepEqual(now, old, JSON.stringify(c)); assert.deepEqual(lean, old, JSON.stringify(c));
    compared += lean.picks.length;
  }
  const picks = rank(slim, screen).picks.map(p => p.id), refused = CASES.reefs.filter(r => full.targets.find(t => t.id === r.id).protected_place.inside).map(r => r.id);
  assert.ok(refused.length >= 3 && compared > 20, 'the fixture has reefs inside a closure and reefs that pass');
  for (const id of refused) assert.ok(!picks.includes(id), `${id} is inside a closure and must not be listed`);
  assert.ok(picks.length > 3);
});

test('parity at the edge: a reef within the 70 m margin is refused by the old check and by the slim file', async () => {
  const screen = plannerScreen(), p = await publication(), full = await loadReefTrip('morro-bay', p.opts), slim = await loadReefTripBrief('morro-bay', p.opts);
  const near = full.targets.filter(t => t.protected_place.distanceM !== null && t.protected_place.distanceM > 0 && t.protected_place.distanceM <= 70);
  const oldIds = rank(withoutVerdicts(full), screen).picks.map(p => p.id), slimIds = rank(slim, screen).picks.map(p => p.id);
  assert.deepEqual(slimIds, oldIds);
  for (const t of near) assert.ok(!slimIds.includes(t.id), `${t.id} is within the planning margin`);
});

test('a screen holding other boundary data: the slim file is not used; the full export is loaded and the old check runs', async () => {
  const p = await publication(), slim = await loadReefTripBrief('morro-bay', p.opts), other = plannerScreen(CASES.boundary.slice(1));
  assert.notEqual(other.fingerprint(), slim.protected_fingerprint);
  const held = rank(slim, other);
  assert.deepEqual(held.picks, []); assert.match(JSON.stringify(held), /Loading ranked reef places/);
  reefPublication.value = {state: 'ready', region: 'morro-bay', loaded: slim};
  let calls = 0;
  const loader = async region => { calls++; return loadReefTrip(region, p.opts); };
  const ps = screen => ({state: 'loaded', region: 'morro-bay', screen});
  await settleReefPublication('morro-bay', ps(plannerScreen()), loader);   // same data: nothing to do
  assert.equal(calls, 0); assert.equal(reefPublication.value.loaded, slim);
  await settleReefPublication('morro-bay', {state: 'idle'}, loader);        // no screen yet: nothing to do
  assert.equal(calls, 0);
  await settleReefPublication('morro-bay', ps(other), loader);
  assert.equal(calls, 1); const now = reefPublication.value;
  assert.equal(now.state, 'ready'); assert.equal(now.loaded.slim, undefined); assert.equal(now.loaded.areas.length, CASES.reefs.length);
  const full = await loadReefTrip('morro-bay', p.opts);
  assert.deepEqual(rank(now.loaded, other), rank(withoutVerdicts(full), other));
  await settleReefPublication('morro-bay', ps(other), loader);              // already the full export: once only
  assert.equal(calls, 1);
  reefPublication.value = {state: 'idle'};
});

test('the feed serves the slim file under the manifest\'s gate, with the export\'s headers', async () => {
  const p = await publication(), base = '/feeds/tiles/seafloor/regions/morro-bay/', path = base + p.manifest.slim_file;
  const make = (manifest, digest) => ({async get(key) { return key.endsWith('manifest-morro-bay.json') ? {json: async () => manifest}
    : {body: new Blob([p.files[p.manifest.slim_file]]).stream(), size: p.manifest.slim_bytes, httpEtag: '"s"', customMetadata: {sha256: digest}}; }});
  try {
    useBucket({FEEDS: make(p.manifest, p.manifest.slim_sha256)});
    const r = await serveFeed(new Request('https://s' + path), path);
    assert.equal(r.status, 200); assert.equal(r.headers.get('Cache-Control'), 'no-store'); assert.equal(r.headers.get('Content-Type'), 'application/gzip');
    assert.equal(r.headers.get('Content-Encoding'), null); assert.equal(r.headers.get('X-Content-Type-Options'), 'nosniff'); assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
    assert.equal(r.headers.get('Content-Length'), String(p.manifest.slim_bytes));
    for (const m of [{...p.manifest, status: 'held'}, {...p.manifest, expires_at: '2000-01-01'}, {...p.manifest, slim_sha256: null}, {...p.manifest, slim_file: undefined}]) {
      useBucket({FEEDS: make(m, p.manifest.slim_sha256)});
      assert.equal((await serveFeed(new Request('https://s' + path), path)).status, 503);
    }
    useBucket({FEEDS: make(p.manifest, 'd'.repeat(64))});   // object written for another revision
    assert.equal((await serveFeed(new Request('https://s' + path), path)).status, 503);
    useBucket({FEEDS: make(p.manifest, p.manifest.slim_sha256)});
    for (const stray of [base + 'habitat-slim.geojson', base + 'habitat-slim.geojson.gz', base + 'habitat-slim-ABC.geojson.gz'])
      assert.equal((await serveFeed(new Request('https://s' + stray), stray)).status, 404, stray);
    // Another content-addressed slim object (an earlier or a staged one) is not served: only the file the live manifest names.
    const staged = base + 'habitat-slim-0123456789abcdef.geojson.gz';
    assert.equal((await serveFeed(new Request('https://s' + staged), staged)).status, 503);
  } finally { useBucket({}); }
});

test('during and after a slim publication the Worker serves a whole release: the staged file only once the manifest names it', async () => {
  const old = await publication(), next = await publication({feats: features().slice(1).concat(features()[0])});
  const base = 'tiles/seafloor/regions/morro-bay/', oldSlim = old.manifest.slim_file, newSlim = next.manifest.slim_file;
  assert.notEqual(oldSlim, newSlim);
  const switched = {...old.manifest, slim_file: newSlim, slim_sha256: next.manifest.slim_sha256, slim_bytes: next.manifest.slim_bytes, slim_decoded_bytes: next.manifest.slim_decoded_bytes};
  const objects = {[base + 'habitat-export.geojson.gz']: [old.files['habitat-export.geojson.gz'], old.manifest.export_sha256],
    [base + oldSlim]: [old.files[oldSlim], old.manifest.slim_sha256], [base + newSlim]: [next.files[newSlim], next.manifest.slim_sha256]};
  const bucketFor = manifest => ({async get(key) {
    if (key === 'tiles/seafloor/manifest-morro-bay.json') return {json: async () => manifest};
    const [bytes, digest] = objects[key] ?? [];
    return bytes ? {body: new Blob([bytes]).stream(), size: bytes.length, httpEtag: '"e"', customMetadata: {sha256: digest}} : null;
  }});
  const status = async name => (await serveFeed(new Request('https://s/feeds/' + base + name), '/feeds/' + base + name)).status;
  try {
    useBucket({FEEDS: bucketFor(old.manifest)});   // staged and read back; the live manifest is untouched
    assert.deepEqual([await status('habitat-export.geojson.gz'), await status(oldSlim), await status(newSlim)], [200, 200, 503]);
    useBucket({FEEDS: bucketFor(switched)});       // the one manifest write
    assert.deepEqual([await status('habitat-export.geojson.gz'), await status(newSlim), await status(oldSlim)], [200, 200, 503]);
  } finally { useBucket({}); }
});

test('default wiring: the angler\'s explicit load (Load on Wi-Fi, Try again) fetches the slim file, and the offer quotes its size', async () => {
  const { acceptReefLoad, requestReefPublication } = await import('../web/reef-lazy.ts');
  const { loadReefPublication } = await import('../web/ranking.ts');
  const pub = await publication();
  const realFetch = globalThis.fetch;
  globalThis.fetch = async url => {
    const match = String(url).match(/manifest-([^/]+)\.json$/);
    if (match && match[1] !== 'morro-bay') return new Response(JSON.stringify({...pub.manifest, region: match[1]}));
    return pub.fetchImpl(url);
  };
  try {
    reefPublication.value = {state: 'idle'};
    await requestReefPublication('morro-bay', {link: () => ({slow: true, why: 'save-data'})});
    assert.equal(reefPublication.value.state, 'offer');
    assert.equal(reefPublication.value.bytes, pub.manifest.slim_bytes, 'the offer quotes the file that will be fetched');
    pub.asked.length = 0;
    await acceptReefLoad('morro-bay');   // production defaults, no injected loader
    assert.equal(reefPublication.value.state, 'ready');
    assert.equal(reefPublication.value.loaded.slim, true);
    assert.ok(!pub.asked.includes('habitat-export.geojson.gz'), `full export was fetched: ${pub.asked}`);
    assert.ok(pub.asked.includes(pub.manifest.slim_file));
  } finally { globalThis.fetch = realFetch; reefPublication.value = {state: 'idle'}; }
});

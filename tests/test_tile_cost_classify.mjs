// BF-tile-cost: unit checks for e2e/tile-cost.ts. The Playwright audit
// (e2e/tile-cost.spec.ts) feeds these same functions the page's performance
// entries; here the entries are synthetic, so the rules are checked alone.
import test from 'node:test';
import assert from 'node:assert/strict';

const {classify, aggregate, sumBytes, KINDS} = await import('../e2e/tile-cost.ts');

const ORIGIN = 'http://localhost:8787';
const kind = url => classify(url, ORIGIN)?.kind ?? null;
const remote = url => classify(url, ORIGIN)?.remote ?? null;

test('classify: kinds by path and origin', () => {
  assert.equal(kind(ORIGIN + '/assets/app-123.js'), 'script');
  assert.equal(kind(ORIGIN + '/assets/app-123.js?ver=2#top'), 'script');       // query and hash parsed
  assert.equal(kind(ORIGIN + '/assets/site.css'), 'style');
  assert.equal(kind(ORIGIN + '/fonts/ibm-sans.woff2'), 'font');
  assert.equal(kind(ORIGIN + '/images/crest.svg'), 'image');
  assert.equal(kind(ORIGIN + '/feeds/data/regions/morro-bay/latest.json'), 'feed');
  assert.equal(kind(ORIGIN + '/api/om/gfs_global/manifest.json'), 'api');
  assert.equal(kind(ORIGIN + '/index.html'), 'other');
  assert.equal(kind('https://gis.charttools.noaa.gov/arcgis/rest/services/MCS/NOAAChartDisplay/MapServer/exts/MaritimeChartService/WMSServer?service=WMS&request=GetMap&width=256'), 'tile');
  assert.equal(kind(ORIGIN + '/feeds/tiles/basemap/ca-coast-20261008.pmtiles'), 'tile');
  assert.equal(kind(ORIGIN + '/tiles/morro-bay-reef-outlines.pmtiles'), 'tile');
  assert.equal(kind(ORIGIN + '/feeds/tiles/basemap/9/134/70.png'), 'tile');     // raster under a tile feed
  assert.equal(kind(ORIGIN + '/feeds/data/sst.png'), 'tile');                    // png under /feeds/
  assert.equal(kind(ORIGIN + '/logo.png'), 'image');                             // png outside map sources
  assert.equal(remote(ORIGIN + '/assets/app.js'), false);
  assert.equal(remote('https://gis.charttools.noaa.gov/x?request=GetMap'), true);
});

test('classify: data: and blob: never touch the network; junk parses to null', () => {
  assert.equal(classify('data:image/png;base64,AAAA', ORIGIN), null);
  assert.equal(classify('blob:http://localhost:8787/1c3f9b1b-0000', ORIGIN), null);
  assert.equal(classify('not a url', ORIGIN), null);
});

test('aggregate: duplicates count twice and remote nulls never become 0 bytes', () => {
  const js = {url: ORIGIN + '/assets/app.js', transfer_bytes: 100, body_bytes: 200};
  const tile = {url: 'https://gis.charttools.noaa.gov/tile?request=GetMap', transfer_bytes: null, body_bytes: null};
  const row = aggregate(ORIGIN, 'coast', 'phone', 'cold', [js, js, tile, {url: 'data:text/plain,x', transfer_bytes: 99, body_bytes: 99}], true);
  assert.equal(row.requests, 3);                                                // the data: URL is ignored
  assert.equal(row.transfer_bytes, 200);                                        // remote tile excluded, not added as 0
  assert.equal(row.body_bytes, 400);
  assert.deepEqual(row.by_kind.script, {requests: 2, transfer_bytes: 200});
  assert.deepEqual(row.by_kind.tile, {requests: 1, transfer_bytes: null});
  assert.deepEqual(row.remote, {'gis.charttools.noaa.gov': 1});
  assert.equal(row.settled, true);
});

test('aggregate: an all-remote row has null transfer bytes', () => {
  const row = aggregate(ORIGIN, 'fleet', 'laptop', 'warm', [{url: 'https://nowcoast.noaa.gov/wms?request=GetMap&width=256', transfer_bytes: null, body_bytes: null}], false);
  assert.equal(row.requests, 1);
  assert.equal(row.transfer_bytes, null);
  assert.deepEqual(row.by_kind.tile, {requests: 1, transfer_bytes: null});
  assert.equal(row.settled, false);
});

test('sumBytes: null is not 0', () => {
  assert.deepEqual(sumBytes([{transfer_bytes: null, body_bytes: null}, {transfer_bytes: 5, body_bytes: 7}]), {transfer_bytes: 5, body_bytes: 7});
  assert.deepEqual(sumBytes([{transfer_bytes: null, body_bytes: null}]), {transfer_bytes: null, body_bytes: 0});
});

test('the tile-cost-v1 document validates its own small schema', () => {
  const rows = [
    aggregate(ORIGIN, 'coast', 'phone', 'cold', [{url: ORIGIN + '/a.js', transfer_bytes: 1, body_bytes: 2}], true),
    aggregate(ORIGIN, 'coast', 'phone', 'warm', [], false),
    aggregate(ORIGIN, 'fleet', 'laptop', 'cold', [{url: 'https://x.test/t?request=GetMap', transfer_bytes: null, body_bytes: null}], true),
  ];
  const doc = {schema: 'tile-cost-v1', commit: 'local', rows};
  assert.equal(doc.schema, 'tile-cost-v1');
  assert.equal(typeof doc.commit, 'string');
  for (const row of doc.rows) {
    assert.equal(typeof row.view, 'string');
    assert.equal(typeof row.project, 'string');
    assert.ok(row.pass === 'cold' || row.pass === 'warm');
    assert.ok(Number.isInteger(row.requests) && row.requests >= 0);
    for (const bytes of [row.transfer_bytes, row.body_bytes]) assert.ok(bytes === null || (Number.isInteger(bytes) && bytes >= 0));
    assert.ok(row.transfer_bytes === null || row.transfer_bytes >= 0);
    for (const [name, bucket] of Object.entries(row.by_kind)) {
      assert.ok(KINDS.includes(name), name);
      assert.ok(Number.isInteger(bucket.requests) && bucket.requests >= 0);
      assert.ok(bucket.transfer_bytes === null || bucket.transfer_bytes >= 0);
      assert.ok(bucket.transfer_bytes === null || (row.transfer_bytes !== null && bucket.transfer_bytes <= row.transfer_bytes));
    }
    for (const count of Object.values(row.remote)) assert.ok(Number.isInteger(count) && count >= 0);
    assert.equal(typeof row.settled, 'boolean');
  }
});

// SC1737-02: the Kayak launch list and the Spear shore distance forget a transient read failure (thrown
// fetch, 429, 5xx), so the next visit asks again; a 404 or an invalid file stays remembered.
import assert from 'node:assert/strict';
import test from 'node:test';
import {publishedChartFiles} from '../web/chart-files.ts';
import {launchPoints, loadLaunchPoints, resetLaunchPoints} from '../web/launches.ts';
import {loadShoreLines, resetShoreLines, shoreLines} from '../web/shore-distance.ts';

const PAGE = 'https://example.test/';
const launchBody = region => JSON.stringify({region_id: region, launch_points: [{id: 'ramp', name: 'Ramp', latitude: 35.3, longitude: -120.8}]});
const shoreBody = () => JSON.stringify({type: 'FeatureCollection', features: [{type: 'Feature', geometry: {type: 'LineString', coordinates: [[-120.8, 35.3], [-120.81, 35.31]]}}]});

const LOADERS = [
  {name: 'launch list', load: loadLaunchPoints, reset: resetLaunchPoints, body: launchBody,
    shown: () => launchPoints.value, real: v => v.points.length === 1, empty: v => v.points.length === 0},
  {name: 'shore lines', load: loadShoreLines, reset: resetShoreLines, body: shoreBody,
    shown: () => shoreLines.value, real: v => v.lines?.length === 1, empty: v => v.lines === null},
];

/** A fetch that answers from `answers` in order (a function is called; an Error is thrown) and counts calls. */
function scripted(answers) {
  const f = async url => { const a = answers[f.calls++]; if (a instanceof Error) throw a; return typeof a === 'function' ? a(url) : a; };
  f.calls = 0;
  return f;
}
const deferred = () => { let resolve, reject; const promise = new Promise((y, n) => { resolve = y; reject = n; }); return {promise, resolve, reject}; };

for (const L of LOADERS) {
  const ok = region => new Response(L.body(region));

  test(`${L.name}: a thrown fetch publishes empty, and the next visit fetches again and shows the real data`, async () => {
    L.reset();
    const f = scripted([new Error('offline'), ok('r')]);
    await L.load('r', PAGE, f);
    assert.equal(f.calls, 1);
    assert.equal(L.shown().region, 'r');
    assert.ok(L.empty(L.shown()), 'empty after a throw');
    await L.load('r', PAGE, f);
    assert.equal(f.calls, 2, 'asked again');
    assert.ok(L.real(L.shown()), 'real data after the retry');
    await L.load('r', PAGE, f);
    assert.equal(f.calls, 2, 'the good read is remembered');
    L.reset();
  });

  for (const status of [429, 500, 503, 599]) {
    test(`${L.name}: HTTP ${status} is asked again on the next visit`, async () => {
      L.reset();
      const f = scripted([new Response('', {status}), ok('r')]);
      await L.load('r', PAGE, f);
      assert.ok(L.empty(L.shown()));
      await L.load('r', PAGE, f);
      assert.equal(f.calls, 2);
      assert.ok(L.real(L.shown()));
      L.reset();
    });
  }

  for (const [label, first] of [['404', () => new Response('', {status: 404})], ['403', () => new Response('', {status: 403})],
    ['200 with invalid JSON', () => new Response('{not json')], ['200 with a valid file', () => ok('r')]]) {
    test(`${L.name}: ${label} is remembered (no second fetch)`, async () => {
      L.reset();
      const f = scripted([first(), ok('r')]);
      await L.load('r', PAGE, f);
      const before = L.shown();
      await L.load('r', PAGE, f);
      assert.equal(f.calls, 1, 'not asked again');
      assert.equal(L.shown(), before, 'nothing republished');
      L.reset();
    });
  }

  test(`${L.name}: concurrent calls share one failing read; a call after it settles fetches once more`, async () => {
    L.reset();
    const d = deferred();
    const f = scripted([() => d.promise, ok('r')]);
    const a = L.load('r', PAGE, f), b = L.load('r', PAGE, f);
    assert.equal(f.calls, 1, 'shared while in flight');
    d.reject(new Error('dropped'));
    await Promise.all([a, b]);
    assert.equal(f.calls, 1);
    await L.load('r', PAGE, f);
    assert.equal(f.calls, 2, 'asked again after settling');
    assert.ok(L.real(L.shown()));
    L.reset();
  });

  test(`${L.name}: a late failure for an old read keeps the newer read and does not publish over another region`, async () => {
    L.reset();
    const old = deferred(), newer = deferred();
    const f = scripted([() => old.promise, () => newer.promise, ok('b'), ok('a')]);
    const lateOld = L.load('a', PAGE, f);
    L.reset();
    const pendingNew = L.load('a', PAGE, f);
    assert.equal(f.calls, 2, 'a new read after the reset');
    await L.load('b', PAGE, f);
    assert.equal(L.shown().region, 'b');
    old.reject(new Error('late'));
    await lateOld;
    assert.equal(L.shown().region, 'b', 'the late failure does not publish over b');
    const again = L.load('a', PAGE, f);
    assert.equal(f.calls, 3, 'the newer read for a is still shared, not removed');
    newer.resolve(ok('a'));
    await Promise.all([pendingNew, again]);
    assert.equal(L.shown().region, 'a');
    assert.ok(L.real(L.shown()));
    L.reset();
  });
}

test('shore lines: an overview the region does not list still makes no request', async () => {
  resetShoreLines();
  publishedChartFiles.value = {region: 'r', files: ['bathymetry.geojson']};
  try {
    const f = scripted([new Error('should not fetch')]);
    await loadShoreLines('r', PAGE, f);
    await loadShoreLines('r', PAGE, f);
    assert.equal(f.calls, 0);
    assert.deepEqual(shoreLines.value, {region: 'r', lines: null});
  } finally { publishedChartFiles.value = null; resetShoreLines(); }
});

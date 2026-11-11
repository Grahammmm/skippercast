// RF0115-6 (web/map/poster.ts): a poster asked while its region's chart_files list is pending waits for the
// list, then asks once (listed, or the read failed and the list is unknown), never when the list omits it,
// and never after the wait was superseded or the Chart has drawn. Real loader, injected fetch, no timers.
import assert from 'node:assert/strict';
import test from 'node:test';
import {loadPoster, poster} from '../web/map/poster.ts';
import {publishedChartFiles} from '../web/chart-files.ts';

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" data-zoom="12" data-west="-121" data-north="35"><path d="M0 0l1 1"/></svg>';
const PAGE = 'https://s.test/map';
const publish = (region, files, pending) => { publishedChartFiles.value = pending ? {region, files, pending: true} : {region, files}; };
const ticks = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

/** A recording fetch whose answer is `reply` (a function giving the response, or throwing). */
function recorder(reply = async () => ({ok: true, text: async () => SVG})) {
  const urls = [];
  return {urls, fetch: async url => { urls.push(String(url)); return reply(); }};
}
/** Run `body` with the signals restored afterwards. */
async function clean(body) {
  const before = publishedChartFiles.peek();
  poster.value = null;
  try { await body(); } finally { publishedChartFiles.value = before; poster.value = null; }
}
/** Start a load and report whether it has settled yet. */
function start(region, done, fetchFn) {
  const state = {settled: false};
  state.promise = loadPoster(region, PAGE, done, fetchFn).then(() => { state.settled = true; });
  return state;
}

test('pending_then_omitted_never_fetches', async () => {
  for (const settled of [[], ['land-water.json'], ['Poster.svg', 'poster.svg.bak', 'poster.SVG', 'xposter.svg']]) await clean(async () => {
    const r = recorder();
    publish('cambria-san-simeon', null, true);
    const load = start('cambria-san-simeon', () => false, r.fetch);
    await ticks();
    assert.deepEqual(r.urls, [], 'no request while the list is pending');
    assert.equal(load.settled, false, 'still waiting');
    publish('cambria-san-simeon', settled);
    await load.promise;
    assert.deepEqual(r.urls, [], `no request for ${JSON.stringify(settled)}`);
    assert.equal(poster.value, null);
  });
});

test('pending_then_listed_fetches_once', async () => clean(async () => {
  const r = recorder();
  publish('morro-bay', null, true);
  const load = start('morro-bay', () => false, r.fetch);
  await ticks();
  assert.deepEqual(r.urls, []);
  publish('morro-bay', ['poster.svg', 'land-water.json']);
  await load.promise;
  assert.deepEqual(r.urls, ['https://s.test/regions/morro-bay/poster.svg']);
  assert.equal(poster.value?.region, 'morro-bay');
  publish('morro-bay', ['poster.svg']); publish('morro-bay', null, true); publish('morro-bay', ['poster.svg']);
  await ticks();
  assert.equal(r.urls.length, 1, 'later publications ask nothing more');
}));

test('pending_then_listed_encodes_the_region', async () => clean(async () => {
  const r = recorder();
  publish('a b/c', null, true);
  const load = start('a b/c', () => false, r.fetch);
  await ticks();
  assert.deepEqual(r.urls, [], 'nothing asked while pending');
  publish('a b/c', ['poster.svg']);
  await load.promise;
  assert.deepEqual(r.urls, ['https://s.test/regions/a%20b%2Fc/poster.svg']);
}));

test('pending_then_failed_metadata_fails_open', async () => {
  // The region read failed: App.tsx publishes the matching region with files null and no pending flag.
  await clean(async () => {
    const r = recorder();
    publish('cambria-san-simeon', null, true);
    const load = start('cambria-san-simeon', () => false, r.fetch);
    await ticks();
    publish('cambria-san-simeon', null);
    await load.promise;
    assert.equal(r.urls.length, 1, 'one legacy request');
    assert.equal(poster.value?.region, 'cambria-san-simeon');
  });
  const bad = [
    ['404', async () => ({ok: false})],
    ['thrown fetch', async () => { throw new Error('offline'); }],
    ['malformed svg', async () => ({ok: true, text: async () => '<html></html>'})],
    ['invalid numeric svg', async () => ({ok: true, text: async () => SVG.replace('data-zoom="12"', `data-zoom="${'9'.repeat(400)}"`)})],
  ];
  for (const [name, reply] of bad) await clean(async () => {
    const r = recorder(reply);
    publish('r', null, true);
    const load = start('r', () => false, r.fetch);
    publish('r', null);
    await load.promise;
    assert.equal(r.urls.length, 1, name);
    assert.equal(poster.value, null, name);
  });
});

test('unknown_list_keeps_the_original_immediate_request', async () => {
  const other = [['no list', () => publish('r', null)], ['null signal', () => { publishedChartFiles.value = null; }],
    ['another region pending', () => publish('other', null, true)], ['listed', () => publish('r', ['poster.svg'])]];
  for (const [name, setup] of other) await clean(async () => {
    const r = recorder();
    setup();
    await loadPoster('r', PAGE, () => false, r.fetch);
    assert.equal(r.urls.length, 1, name);
  });
  await clean(async () => {
    const r = recorder();
    publish('r', ['land-water.json']);
    await loadPoster('r', PAGE, () => false, r.fetch);
    assert.deepEqual(r.urls, [], 'a settled list without the poster still skips it');
  });
});

test('superseded_wait_cannot_revive', async () => {
  await clean(async () => {
    const r = recorder();
    publish('A', null, true);
    const load = start('A', () => false, r.fetch);
    publish('B', null, true);
    publish('A', null, true);
    publish('A', ['poster.svg']);
    await load.promise;
    assert.deepEqual(r.urls, [], 'the old A call settled without a request');
    // A fresh A call is independent: it sees the settled list and asks.
    await loadPoster('A', PAGE, () => false, r.fetch);
    assert.equal(r.urls.length, 1);
  });
  await clean(async () => {
    const r = recorder();
    publish('A', null, true);
    const load = start('A', () => false, r.fetch);
    publishedChartFiles.value = null;
    await load.promise;
    publish('A', ['poster.svg']); publish('A', null, true); publish('A', ['poster.svg']);
    await ticks();
    assert.deepEqual(r.urls, [], 'a null replacement ends the wait for good');
    assert.equal(poster.value, null);
  });
  await clean(async () => {
    const r = recorder();
    publish('A', null, true);
    const fresh = start('A', () => false, r.fetch);
    publish('B', ['poster.svg']);
    await fresh.promise;
    assert.deepEqual(r.urls, [], 'another region published: nothing asked for A');
  });
});

test('paint_move_destroy_before_settlement', async () => {
  await clean(async () => {
    const r = recorder();
    publish('r', null, true);
    const load = start('r', () => true, r.fetch);
    await ticks();
    assert.equal(load.settled, true, 'drawn already: the deferred attempt is abandoned at once');
    publish('r', ['poster.svg']);
    await load.promise;
    assert.deepEqual(r.urls, []);
  });
  await clean(async () => {
    const r = recorder();
    let drawn = false;
    publish('r', null, true);
    const load = start('r', () => drawn, r.fetch);
    await ticks();
    drawn = true;
    publish('r', ['poster.svg']);
    await load.promise;
    assert.deepEqual(r.urls, [], 'drawn while waiting: no request at settlement');
    assert.equal(poster.value, null);
  });
  await clean(async () => {
    let release, drawn = false;
    const body = new Promise(resolve => { release = resolve; });
    const r = recorder(async () => ({ok: true, text: () => body}));
    publish('r', null, true);
    const load = start('r', () => drawn, r.fetch);
    publish('r', ['poster.svg']);
    await ticks();
    assert.equal(r.urls.length, 1, 'asked after settlement');
    drawn = true;
    release(SVG);
    await load.promise;
    assert.equal(poster.value, null, 'drawn before the body arrived: the existing final check holds');
  });
});

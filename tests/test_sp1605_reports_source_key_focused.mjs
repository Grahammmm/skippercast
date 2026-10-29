import './fixtures/sp1605_reports_source_key/offline.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import {load, transport, labels, grounds, response, flush, A, B} from './fixtures/sp1605_reports_source_key/harness.mjs';

function deferredTransport() {
  const waiting = [], calls = [];
  const fetchFn = async url => {
    calls.push(String(url));
    if (url === A || url === B) return new Promise(resolve => waiting.push({url, resolve}));
    return transport()(url);
  };
  return {waiting, calls, fetchFn};
}
async function start(m, source, fetchFn) {
  // Attach rejection handling immediately, before any controlled completion.
  const result = m.openReports('synthetic-region', 'reef', source, fetchFn).then(() => null, error => error);
  await flush();
  return {result};
}
function finish(slot, label) { slot.resolve(response(grounds(label))); }
function view(m) {
  m.effects.length = 0;
  return m.render(m.h(m.Reports));
}

test('A2: A to B to null uses only matching settled source; structured identities do not collide', async () => {
  const m = await load(), calls = [], fetchFn = transport(calls);
  await m.openReports('synthetic-region', 'reef', A, fetchFn);
  assert.deepEqual(labels(m), ['Synthetic A']);
  await m.openReports('synthetic-region', 'reef', B, fetchFn);
  assert.deepEqual(labels(m), ['Synthetic B']);
  await m.openReports('synthetic-region', 'reef', null, fetchFn);
  assert.equal(labels(m), null);
  assert.equal(calls.length, 8);
  await m.openReports('x:y', 'z', A, fetchFn);
  const previous = m.reportsData.peek().key;
  await m.openReports('x', 'y:z', A, fetchFn);
  assert.notEqual(m.reportsData.peek().key, previous);
});

test('A2: identical settled and pending inputs coalesce', async () => {
  const m = await load(), d = deferredTransport();
  const first = await start(m, A, d.fetchFn);
  await m.openReports('synthetic-region', 'reef', A, d.fetchFn);
  assert.equal(d.waiting.length, 1);
  finish(d.waiting[0], 'Synthetic A');
  assert.equal(await first.result, null);
  const total = d.calls.length;
  await m.openReports('synthetic-region', 'reef', A, d.fetchFn);
  assert.equal(d.calls.length, total);
});

test('A3: obsolete successes in both orders, ABA and return to settled data cannot publish', async () => {
  for (const oldFirst of [true, false]) {
    const m = await load(), d = deferredTransport();
    const old = await start(m, A, d.fetchFn), current = await start(m, B, d.fetchFn);
    assert.equal(d.waiting.length, 2);
    if (oldFirst) {
      finish(d.waiting[0], 'Obsolete A');
      assert.equal(await old.result, null);
      assert.equal(m.reportsData.peek(), null);
    }
    finish(d.waiting[1], 'Current B');
    assert.equal(await current.result, null);
    const snapshot = m.reportsData.peek();
    if (!oldFirst) { finish(d.waiting[0], 'Obsolete A'); assert.equal(await old.result, null); }
    assert.strictEqual(m.reportsData.peek(), snapshot);
    assert.deepEqual(labels(m), ['Current B']);
  }
  // Null participates in pending identity too, in both directions/orders.
  for (const [before, after] of [[null, A], [A, null]]) {
    for (const oldFirst of [true, false]) {
      const n = await load(), waiting = [];
      const fetchFn = async url => String(url).endsWith('/latest.json')
        ? new Promise(resolve => waiting.push(resolve)) : transport()(url);
      const previous = await start(n, before, fetchFn), next = await start(n, after, fetchFn);
      assert.equal(waiting.length, 2);
      if (oldFirst) {
        waiting[0](new Response('unavailable', {status: 503}));
        assert.equal(await previous.result, null);
        assert.equal(n.reportsData.peek(), null);
      }
      waiting[1](new Response('unavailable', {status: 503}));
      assert.equal(await next.result, null);
      const currentSnapshot = n.reportsData.peek();
      if (!oldFirst) { waiting[0](new Response('unavailable', {status: 503})); assert.equal(await previous.result, null); }
      assert.strictEqual(n.reportsData.peek(), currentSnapshot);
      assert.deepEqual(labels(n), after === A ? ['Synthetic A'] : null);
    }
  }
  const m = await load(), d = deferredTransport();
  const a1 = await start(m, A, d.fetchFn), b = await start(m, B, d.fetchFn), a2 = await start(m, A, d.fetchFn);
  finish(d.waiting[0], 'Obsolete same-key A');
  assert.equal(await a1.result, null);
  assert.equal(m.reportsData.peek(), null, 'same key does not establish current request instance');
  finish(d.waiting[2], 'Current A');
  assert.equal(await a2.result, null);
  finish(d.waiting[1], 'Obsolete B');
  assert.equal(await b.result, null);
  assert.deepEqual(labels(m), ['Current A']);
  const pendingB = await start(m, B, d.fetchFn);
  const settled = m.reportsData.peek();
  await m.openReports('synthetic-region', 'reef', A, d.fetchFn);
  finish(d.waiting[3], 'Obsolete B after return');
  assert.equal(await pendingB.result, null);
  assert.strictEqual(m.reportsData.peek(), settled);
});

test('A3: obsolete rejection in both orders cannot clear or overwrite current-source work', async () => {
  for (const oldFirst of [true, false]) {
    const m = await load(), d = deferredTransport();
    const old = await start(m, A, d.fetchFn), current = await start(m, B, d.fetchFn);
    // A malformed synthetic source causes the REAL mapper to reject the old
    // load. Transport failures themselves are handled per-section, below.
    const rejectOld = () => d.waiting[0].resolve(response({audit_date: '2026-10-01', grounds: [{label: 'Broken synthetic', reports: null}]}));
    if (oldFirst) {
      rejectOld();
      assert.ok(await old.result instanceof TypeError);
      await m.openReports('synthetic-region', 'reef', B, d.fetchFn);
      assert.equal(d.waiting.length, 2, 'old finally cannot clear current pending identity');
    }
    finish(d.waiting[1], 'Current B');
    assert.equal(await current.result, null);
    const snapshot = m.reportsData.peek();
    if (!oldFirst) { rejectOld(); assert.ok(await old.result instanceof TypeError); }
    assert.strictEqual(m.reportsData.peek(), snapshot);
    assert.deepEqual(labels(m), ['Current B']);
  }
});

test('A3/A4: a current charter source failure stays unavailable without reviving old evidence', async () => {
  const m = await load();
  await m.openReports('synthetic-region', 'reef', A, transport());
  await m.openReports('synthetic-region', 'reef', B, async url => {
    if (url === B) throw new Error('synthetic source failure');
    return transport()(url);
  });
  assert.equal(labels(m), null);
  const data = m.reportsData.peek().data;
  assert.equal(data.evidence, null);
  assert.equal(data.discussions.status, 'unavailable');
  assert.equal(data.watch, null);
  const html = m.render(m.h(m.ReportsBody, {data, catches: null}));
  assert.match(html, /No catch score is assumed/);
  assert.match(html, /Recent discussion search is unavailable/);
  assert.match(html, /seasonal watch for this coast is unavailable/);
  assert.match(html, /No geographically specific charter evidence/);
  assert.doesNotMatch(html, /Synthetic A/);
});

test('A4: legacy source-less preloaded data renders and its effect starts zero fetches', async () => {
  const m = await load(), calls = [], original = globalThis.fetch;
  globalThis.fetch = transport(calls);
  try {
    m.region.value = 'synthetic-region'; m.species.value = 'reef';
    m.regionInfo.value = null;
    const loaded = {key: 'synthetic-region:reef', data: {evidence: null,
      discussions: {status: 'unavailable', candidates: [], checkedQueries: 0, totalQueries: 0},
      watch: null, charters: null}};
    m.reportsData.value = loaded;
    const html = view(m);
    assert.doesNotMatch(html, /Loading dated reports/);
    assert.match(html, /Recent discussion search is unavailable/);
    assert.match(html, /No geographically specific charter evidence/);
    assert.equal(m.effects.length, 1);
    m.effects.shift()(); await flush();
    assert.strictEqual(m.reportsData.peek(), loaded);
    assert.deepEqual(calls, [], 'matching legacy cache prevents any Reports fetch');
  } finally { globalThis.fetch = original; }
});

test('A4: actual Reports admission and effect use current region, target and source before/after loading', async () => {
  const m = await load(), calls = [], original = globalThis.fetch;
  const synthetic = transport(calls);
  globalThis.fetch = async url => url === 'data/coasts.json' ? new Response('no', {status: 503}) : synthetic(url);
  try {
    m.region.value = 'synthetic-region'; m.species.value = 'reef';
    m.regionInfo.value = {id: 'synthetic-region', charters: null};
    let html = view(m);
    assert.match(html, /Loading dated reports/);
    assert.equal(m.effects.length, 1);
    m.effects.shift()(); await flush();
    assert.match(view(m), /No geographically specific charter evidence/);
    for (const [source, shown, stale] of [[A, 'Synthetic A', null], [B, 'Synthetic B', 'Synthetic A'], [null, null, 'Synthetic B']]) {
      m.regionInfo.value = {id: 'synthetic-region', charters: source};
      html = view(m);
      assert.match(html, /Loading dated reports/, 'stale data withheld BEFORE effect');
      if (stale) assert.ok(!html.includes(stale));
      m.effects.shift()(); await flush();
      html = view(m);
      if (shown) assert.ok(html.includes(shown));
      else assert.match(html, /No geographically specific charter evidence/);
      if (stale) assert.ok(!html.includes(stale));
    }
    // Mismatched region metadata cannot contribute a source path.
    m.regionInfo.value = {id: 'other-region', charters: A};
    assert.match(view(m), /No geographically specific charter evidence/);
    m.species.value = 'halibut';
    assert.match(view(m), /Loading dated reports/);
    m.region.value = 'other-region';
    assert.match(view(m), /Loading dated reports/);
    assert.equal(calls.filter(url => url === A).length, 1);
    assert.equal(calls.filter(url => url === B).length, 1);
    // Seasonal policy stays in the actual watch mapper, including stale links.
    const catalog = {regions: [], target_names: {yellowtail: 'Yellowtail'}};
    const coast = {id: 'central', name: 'Central', watch: ['yellowtail']};
    const status = {completed_at: '2026-10-01T00:00:00Z', regions: {central: {watch: [{target: 'yellowtail', status: 'recent-located-reports', evidence: [{url: 'https://news.example/synthetic', date: '2026-10-01', publisher: 'Synthetic'}]}]}}};
    assert.equal(m.watchFrom(catalog, coast, status, Date.parse('2026-10-01T01:00:00Z')).items[0].located, true);
    const stale = m.watchFrom(catalog, coast, status, Date.parse('2026-10-04T00:00:00Z'));
    assert.equal(stale.items[0].located, false);
    assert.deepEqual(stale.items[0].links, []);
    assert.match(m.render(m.h(m.WatchSection, {watch: stale})), /does not establish fish presence/);
  } finally { globalThis.fetch = original; }
});

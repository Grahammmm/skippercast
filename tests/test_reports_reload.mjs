// SC1737-06: reopening Reports reads its sections again when one failed or the
// loaded data is 30 minutes old; the shown data stays until the new read publishes.
// Reuses the sp1605 harness (real Reports, loader and section modules, offline).
import './fixtures/sp1605_reports_source_key/offline.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import {load, transport, labels, grounds, response, flush, A, B} from './fixtures/sp1605_reports_source_key/harness.mjs';

const MIN = 60_000, T = Date.parse('2026-10-31T12:00:00Z');
const ID = 'synthetic-region', TARGET = 'reef';
const healthy = charters => ({
  discussions: {status: 'current', candidates: [], checkedQueries: 1, totalQueries: 1},
  evidence: {confidence: 'low', reason: 'synthetic', start: '2026-09-01', end: '2026-09-30', boats: 1, days: 1, trips: 1,
    generatedAt: '2026-10-01T00:00:00Z', rows: []},
  watch: {coast: 'Synthetic', items: [], checked: true}, charters,
});
// Deferred transport: charter sources A and B wait for the test; everything else answers like the harness.
function deferred() {
  const waiting = [], calls = [];
  const fetchFn = async url => {
    calls.push(String(url));
    if (url === A || url === B) return new Promise(resolve => waiting.push({url, resolve}));
    return transport()(url);
  };
  return {waiting, calls, fetchFn};
}
const start = async (m, source, fetchFn, now) => {
  const result = m.openReports(ID, TARGET, source, fetchFn, now).then(() => null, error => error);
  await flush();
  return {result};
};
const settle = (slot, label) => slot.resolve(response(grounds(label)));
const failing = async url => {
  if (url === A) throw new Error('synthetic source failure');
  return transport()(url);
};

test('a failed first load is fetched again on reopen and a now-OK read publishes the real sections', async () => {
  const m = await load(), calls = [];
  await m.openReports(ID, TARGET, A, async url => { calls.push(String(url)); return failing(url); }, T);
  assert.equal(labels(m), null);
  assert.equal(m.reportsData.peek().data.evidence, null);
  const first = calls.length;
  await m.openReports(ID, TARGET, A, async url => { calls.push(String(url)); return transport()(url); }, T + MIN);
  assert.ok(calls.length > first, 'the failed sections are read again');
  assert.deepEqual(labels(m), ['Synthetic A']);
  assert.equal(m.reportsData.peek().loadedAt, T + MIN);
});

test('healthy data is reused until it is 30 minutes old, then read again', async () => {
  const m = await load(), calls = [];
  const fetchFn = async url => { calls.push(String(url)); return transport()(url); };
  const key = `${ID}:${TARGET}`;
  m.reportsData.value = {key, data: healthy(null), loadedAt: T};
  assert.equal(m.REPORTS_MAX_AGE_MS, 30 * MIN);
  await m.openReports(ID, TARGET, null, fetchFn, T + 29 * MIN);
  assert.deepEqual(calls, [], 'no fetch at 29 minutes');
  await m.openReports(ID, TARGET, null, fetchFn, T + 30 * MIN);
  assert.ok(calls.length > 0, 'fetched at 30 minutes');
  assert.equal(m.reportsData.peek().loadedAt, T + 30 * MIN);
});

test('the old data stays on screen during a reload and a second reopen shares the one read', async () => {
  const m = await load(), d = deferred();
  await m.openReports(ID, TARGET, A, failing, T);
  const old = m.reportsData.peek();
  const reload = await start(m, A, d.fetchFn, T + MIN);
  const total = d.calls.length;
  await m.openReports(ID, TARGET, A, d.fetchFn, T + MIN);
  assert.equal(d.calls.length, total, 'a concurrent reopen starts no second set of fetches');
  assert.equal(d.waiting.length, 1);
  assert.strictEqual(m.reportsData.peek(), old, 'old value is not blanked');
  assert.ok(m.reportsData.peek().data);
  settle(d.waiting[0], 'Reloaded A');
  assert.equal(await reload.result, null);
  assert.deepEqual(labels(m), ['Reloaded A']);
});

test('no charter source with no charter data is not a failure; a missing charter read is', async () => {
  const m = await load(), calls = [];
  const fetchFn = async url => { calls.push(String(url)); return transport()(url); };
  const entry = {data: healthy(null), loadedAt: T};
  assert.equal(m.needsReload(entry, null, T + MIN), false);
  assert.equal(m.needsReload(entry, A, T + MIN), true);
  m.reportsData.value = {key: `${ID}:${TARGET}`, ...entry};
  await m.openReports(ID, TARGET, null, fetchFn, T + MIN);
  assert.deepEqual(calls, []);
  for (const bad of [{discussions: {status: 'unavailable', candidates: [], checkedQueries: 0, totalQueries: 0}},
    {evidence: null}, {watch: null}]) {
    assert.equal(m.needsReload({data: {...healthy(null), ...bad}, loadedAt: T}, null, T + MIN), true, JSON.stringify(Object.keys(bad)));
  }
});

test('a reload for an old key that settles after a switch does not publish over the new key', async () => {
  const m = await load(), d = deferred();
  await m.openReports(ID, TARGET, A, failing, T);
  const reloadA = await start(m, A, d.fetchFn, T + MIN);
  const openB = await start(m, B, d.fetchFn, T + MIN);
  assert.equal(d.waiting.length, 2);
  settle(d.waiting[0], 'Obsolete reload A');
  assert.equal(await reloadA.result, null);
  assert.deepEqual(labels(m), null, 'the superseded reload did not publish');
  settle(d.waiting[1], 'Current B');
  assert.equal(await openB.result, null);
  assert.deepEqual(labels(m), ['Current B']);
});

test('a hand-set entry without loadedAt is read again on the next open and renders unchanged', async () => {
  const m = await load(), calls = [];
  const fetchFn = async url => { calls.push(String(url)); return transport()(url); };
  const data = healthy(null), key = `${ID}:${TARGET}`;
  assert.equal(m.needsReload({data}, null, T), true);
  const html = m.render(m.h(m.ReportsBody, {data, catches: null}));
  assert.match(html, /Recent fishing evidence/);
  assert.equal(html, m.render(m.h(m.ReportsBody, {data: {...data}, catches: null})));
  m.reportsData.value = {key, data};
  await m.openReports(ID, TARGET, null, fetchFn, T);
  assert.ok(calls.length > 0, 'reloaded');
  assert.equal(m.reportsData.peek().loadedAt, T);
});

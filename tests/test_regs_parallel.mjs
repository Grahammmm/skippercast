// SC1938-16: loadRegs starts the committed registry and the daily regulations part together (the phone shell's rules line
// waits for the later of the two, not their sum) and still applies them in the old order: registry first, daily part last.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {loadRegs, regsData, resetRegs} from '../web/regs.ts';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const MORRO = fixture.region, NOW = Date.parse('2026-09-21T18:00:00Z');
const COMMITTED = 'data/regulations.json', daily = id => `/api/daily?region=${id}&part=regulations`;
const regs = (mark, at = NOW) => {
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(at - 3600000).toISOString(); d.rules_review_status = 'reviewed'; d.mark = mark;
  for (const [id, s] of Object.entries(d.sources)) {
    s.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: s.url, normalization: s.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: new Date(at).toISOString()};
  }
  return d;
};
const part = (id, mark, at = NOW) => ({schema_version: 1, part: 'regulations', region_id: id, generated_at: new Date(at).toISOString(), catch_probability: null, bite_score: null, regulations: regs(mark, at)});
/** Every request waits on a deferred the test settles, in the order it chooses. */
function held() {
  const urls = [], gates = {};
  const fetchFn = url => { urls.push(url); return new Promise((resolve, reject) => { gates[url] = {resolve, reject}; }); };
  return {urls, fetchFn, ok: (url, body) => gates[url].resolve(Response.json(body)), status: (url, n) => gates[url].resolve(new Response('', {status: n})), drop: url => gates[url].reject(new TypeError('Failed to fetch'))};
}
const fresh = () => { resetRegs(); regsData.value = null; };
const tick = () => new Promise(r => setTimeout(r, 0));

test('1: both requests are issued before either resolves; with no registry asset only the daily part is asked (7)', async () => {
  fresh(); const s = held();
  const p = loadRegs(MORRO, s.fetchFn);
  assert.deepEqual(s.urls, [COMMITTED, daily('morro-bay')]);
  s.ok(COMMITTED, regs('registry')); s.ok(daily('morro-bay'), part('morro-bay', 'daily')); await p;
  fresh(); const t = held();
  const q = loadRegs({...MORRO, assets: {}}, t.fetchFn);
  assert.deepEqual(t.urls, [daily('morro-bay')]);
  t.ok(daily('morro-bay'), part('morro-bay', 'daily')); await q;
  assert.equal(regsData.value.data.mark, 'daily');
});

test('2: the daily part answering first, with an equal reviewed_at, still ends on the daily part', async () => {
  fresh(); const s = held();
  const p = loadRegs(MORRO, s.fetchFn);
  s.ok(daily('morro-bay'), part('morro-bay', 'daily')); await tick();
  assert.equal(regsData.value, null, 'nothing is applied before the registry has answered');
  s.ok(COMMITTED, regs('registry')); await p;
  assert.equal(regsData.value.data.mark, 'daily');
});

test('3: a daily part older than the registry keeps the registry, whichever answers first', async () => {
  for (const dailyFirst of [true, false]) {
    fresh(); const s = held();
    const p = loadRegs(MORRO, s.fetchFn);
    const steps = [() => s.ok(COMMITTED, regs('registry')), () => s.ok(daily('morro-bay'), part('morro-bay', 'daily', NOW - 86400000))];
    for (const step of dailyFirst ? steps.reverse() : steps) step();
    await p;
    assert.equal(regsData.value.data.mark, 'registry', `daily first: ${dailyFirst}`);
  }
});

test('4: a registry 404 still accepts the daily part, and a registry 503 asks again', async () => {
  for (const [status, retry] of [[404, false], [503, true]]) {
    fresh(); const s = held();
    const p = loadRegs(MORRO, s.fetchFn);
    s.status(COMMITTED, status); s.ok(daily('morro-bay'), part('morro-bay', 'daily')); await p;
    assert.equal(regsData.value.data.mark, 'daily');
    const before = s.urls.length; const again = loadRegs(MORRO, s.fetchFn);
    assert.equal(s.urls.length > before, retry, `${status}: asked again ${retry}`);
    if (retry) { s.ok(COMMITTED, regs('registry')); s.ok(daily('morro-bay'), part('morro-bay', 'daily')); }
    await again;
  }
});

test('5: both failing leaves regsData alone and raises no unhandled rejection, whichever fails first', async () => {
  const seen = []; const on = e => seen.push(e); process.on('unhandledRejection', on);
  try {
    for (const order of [[COMMITTED, daily('morro-bay')], [daily('morro-bay'), COMMITTED]]) {
      fresh(); const s = held();
      const p = loadRegs(MORRO, s.fetchFn);
      for (const url of order) s.drop(url);
      await p; await tick();
      assert.equal(regsData.value, null);
    }
  } finally { process.off('unhandledRejection', on); }
  assert.deepEqual(seen, []);
});

test('6: region A\'s late answers never land once region B has started reading', async () => {
  fresh(); const a = held(), b = held();
  const A = loadRegs(MORRO, a.fetchFn);
  const OTHER = {...MORRO, id: 'other-bay'};
  const B = loadRegs(OTHER, b.fetchFn);
  a.ok(COMMITTED, regs('A')); a.ok(daily('morro-bay'), part('morro-bay', 'A')); await A;
  assert.equal(regsData.value, null, 'A is not shown while B reads');
  b.ok(COMMITTED, regs('B')); b.ok(daily('other-bay'), part('other-bay', 'B')); await B;
  assert.equal(regsData.value?.data.mark, "B", "and B shows its own");
});

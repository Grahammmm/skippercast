// SC1938-16: loadRegs starts the committed registry and the daily regulations part together (the phone shell's rules line
// waits for the later of the two, not their sum) and still applies them in the old order: registry first, daily part last.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {isDeepStrictEqual} from 'node:util';
import test from 'node:test';
import {loadRegs, regsData, resetRegs} from '../web/regs.ts';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const MORRO = fixture.region, NOW = Date.parse('2026-09-21T18:00:00Z');
const COPY = 'regions/morro-bay/regulations-startup.json', FALLBACK = 'data/regulations.json', daily = id => `/api/daily?region=${id}&part=regulations`;
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
function held(holdFallback = false) {
  const urls = [], gates = {};
  const fetchFn = url => { urls.push(url); return url === FALLBACK && !holdFallback ? Promise.resolve(new Response('', {status: 404})) : new Promise((resolve, reject) => { gates[url] = {resolve, reject}; }); };
  const release = () => { for (const g of Object.values(gates)) g.reject(new TypeError('released')); };
  return {urls, fetchFn, release, ok: (url, body) => gates[url].resolve(Response.json(body)), status: (url, n) => gates[url].resolve(new Response('', {status: n})), drop: url => gates[url].reject(new TypeError('Failed to fetch'))};
}
const fresh = () => { resetRegs(); regsData.value = null; };
const tick = () => new Promise(r => setTimeout(r, 0));

test('1: both requests are issued before either resolves; with no registry asset only the daily part is asked (7)', async () => {
  fresh(); const s = held();
  const p = loadRegs(MORRO, s.fetchFn);
  assert.deepEqual(s.urls, [COPY, daily('morro-bay')]);
  s.ok(COPY, regs('registry')); s.ok(daily('morro-bay'), part('morro-bay', 'daily')); await p;
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
  s.ok(COPY, regs('registry')); await p;
  assert.equal(regsData.value.data.mark, 'daily');
});

test('3: a daily part older than the registry keeps the registry, whichever answers first', async () => {
  for (const dailyFirst of [true, false]) {
    fresh(); const s = held();
    const p = loadRegs(MORRO, s.fetchFn);
    const steps = [() => s.ok(COPY, regs('registry')), () => s.ok(daily('morro-bay'), part('morro-bay', 'daily', NOW - 86400000))];
    for (const step of dailyFirst ? steps.reverse() : steps) step();
    await p;
    assert.equal(regsData.value.data.mark, 'registry', `daily first: ${dailyFirst}`);
  }
});

test('4: a registry 404 still accepts the daily part, and a registry 503 asks again', async () => {
  for (const [status, retry] of [[404, false], [503, true]]) {
    fresh(); const s = held();
    const p = loadRegs(MORRO, s.fetchFn);
    s.status(COPY, status); s.ok(daily('morro-bay'), part('morro-bay', 'daily')); await p;
    assert.equal(regsData.value.data.mark, 'daily');
    const before = s.urls.length; const again = loadRegs(MORRO, s.fetchFn);
    assert.equal(s.urls.length > before, retry, `${status}: asked again ${retry}`);
    if (retry) { s.ok(COPY, regs('registry')); s.ok(daily('morro-bay'), part('morro-bay', 'daily')); }
    await again;
  }
});

test('5: both failing leaves regsData alone and raises no unhandled rejection, whichever fails first', async () => {
  const seen = []; const on = e => seen.push(e); process.on('unhandledRejection', on);
  try {
    for (const order of [[COPY, daily('morro-bay')], [daily('morro-bay'), COPY]]) {
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
  a.ok(COPY, regs('A')); a.ok(daily('morro-bay'), part('morro-bay', 'A')); await A;
  assert.equal(regsData.value, null, 'A is not shown while B reads');
  b.ok('regions/other-bay/regulations-startup.json', regs('B')); b.ok(daily('other-bay'), part('other-bay', 'B')); await B;
  assert.equal(regsData.value?.data.mark, "B", "and B shows its own");
});

test('7: a successful fallback clears only the copy failure, not an early daily failure', async () => {
  for (const dailyFails of [false, true]) {
    fresh(); const s = held(true);
    const p = loadRegs(MORRO, s.fetchFn);
    if (dailyFails) s.drop(daily('morro-bay'));
    else s.ok(daily('morro-bay'), part('morro-bay', 'daily'));
    await tick();
    s.status(COPY, 503); await tick();
    assert.deepEqual(s.urls, [COPY, daily('morro-bay'), FALLBACK]);
    assert.equal(regsData.value, null, 'daily still waits for the fallback registry');
    s.ok(FALLBACK, regs('fallback')); await p;
    assert.equal(regsData.value.data.mark, dailyFails ? 'fallback' : 'daily');
    const before = s.urls.length, again = loadRegs(MORRO, s.fetchFn);
    assert.equal(s.urls.length > before, dailyFails, 'retry only for the daily failure, not the recovered copy');
    if (dailyFails) { s.ok(COPY, regs('copy')); s.ok(daily('morro-bay'), part('morro-bay', 'daily')); }
    await again;
  }
});

// RF1050-17: after A -> B -> A only the replacement A's read may publish; the first A is obsolete whatever it carries.
globalThis.fetch = () => { throw new Error('unexpected network: every read here is injected'); };
const OTHER = {...MORRO, id: 'other-bay'}, DAILY_ONLY = {...MORRO, assets: {}}, OTHER_DAILY_ONLY = {...OTHER, assets: {}};
const OTHER_COPY = 'regions/other-bay/regulations-startup.json';
const OPTS = {timeout: 5000};
/** The same reviewed_at as `regs(mark)` with a different check record (or, when newer, a later reviewed_at as well). */
const obsolete = (mark, newer) => {
  const d = regs(mark, newer ? NOW + 7200000 : NOW);
  for (const c of Object.values(d.checks)) c.data_retrieved_at = new Date(NOW - 60000).toISOString();
  if (!newer) d.reviewed_at = regs('current').reviewed_at;
  return d;
};
const sameData = (a, b) => isDeepStrictEqual(a, b);
/** Run `body` and always release every request the servers still hold. */
async function guarded(servers, body) { try { await body(); } finally { for (const s of servers) s.release(); } }

test('8: regs_round_trip_latest_request_wins - the first A, resolving last, never replaces the replacement A', OPTS, async () => {
  for (const newer of [false, true]) {
    fresh(); const a1 = held(), b = held(), a2 = held();
    await guarded([a1, b, a2], async () => {
      const A1 = loadRegs(DAILY_ONLY, a1.fetchFn), B = loadRegs(OTHER_DAILY_ONLY, b.fetchFn);
      b.ok(daily('other-bay'), part('other-bay', 'B')); await B;
      assert.equal(regsData.value.data.mark, 'B');
      const A2 = loadRegs(DAILY_ONLY, a2.fetchFn);
      assert.deepEqual(a2.urls, [daily('morro-bay')], 'the replacement A starts its own read');
      a2.ok(daily('morro-bay'), part('morro-bay', 'current')); await A2;
      const current = structuredClone(regsData.value.data);
      assert.equal(current.mark, 'current');
      const late = part('morro-bay', 'obsolete', NOW); late.regulations = obsolete('obsolete', newer);
      assert.ok(!sameData(late.regulations.checks, current.checks), 'the late answer really carries different source checks');
      a1.ok(daily('morro-bay'), late); await A1; await tick();
      assert.equal(regsData.value.region, 'morro-bay');
      assert.ok(sameData(regsData.value.data, current), `the replacement stays byte-for-byte current (newer reviewed_at: ${newer})`);
    });
  }
});

test('9: regs_obsolete_startup_fallback_and_daily_are_all_refused - each late source on its own, and the replacement still applies its daily after its registry', OPTS, async () => {
  for (const source of ['copy', 'fallback', 'daily']) for (const newer of [false, true]) {
    fresh(); const a1 = held(source === 'fallback'), b = held(), a2 = held();
    await guarded([a1, b, a2], async () => {
      const A1 = loadRegs(MORRO, a1.fetchFn);
      if (source !== 'daily') a1.status(daily('morro-bay'), 404);
      if (source === 'daily') a1.status(COPY, 404);
      if (source === 'fallback') { a1.status(COPY, 503); await tick(); assert.deepEqual(a1.urls, [COPY, daily('morro-bay'), FALLBACK]); }
      const B = loadRegs(OTHER, b.fetchFn);
      b.ok(OTHER_COPY, regs('B')); b.ok(daily('other-bay'), part('other-bay', 'B')); await B;
      assert.equal(regsData.value.data.mark, 'B', 'A -> B stays protected');
      const A2 = loadRegs(MORRO, a2.fetchFn);
      a2.ok(COPY, regs('current-registry')); await tick();
      assert.equal(regsData.value.data.mark, 'current-registry', 'the replacement applies its registry first');
      a2.ok(daily('morro-bay'), part('morro-bay', 'current-daily')); await A2;
      const current = structuredClone(regsData.value.data);
      assert.equal(current.mark, 'current-daily', 'and its own daily last');
      const late = obsolete('obsolete', newer);
      if (source === 'copy') a1.ok(COPY, late);
      if (source === 'fallback') a1.ok(FALLBACK, late);
      if (source === 'daily') { const p = part('morro-bay', 'obsolete'); p.regulations = late; a1.ok(daily('morro-bay'), p); }
      await A1; await tick();
      assert.ok(sameData(regsData.value.data, current), `a late ${source} answer is refused (newer reviewed_at: ${newer})`);
    });
  }
});

test('10: regs_obsolete_completion_does_not_unshare_current_read - finishing the first A leaves the replacement shared and pending', OPTS, async () => {
  fresh(); const a1 = held(), b = held(), a2 = held(), extra = held();
  await guarded([a1, b, a2, extra], async () => {
    const A1 = loadRegs(MORRO, a1.fetchFn), B = loadRegs(OTHER, b.fetchFn);
    b.ok(OTHER_COPY, regs('B')); b.ok(daily('other-bay'), part('other-bay', 'B')); await B;
    const A2 = loadRegs(MORRO, a2.fetchFn);
    a1.ok(COPY, obsolete('obsolete', false)); a1.ok(daily('morro-bay'), part('morro-bay', 'obsolete')); await A1; await tick();
    assert.equal(regsData.value.data.mark, 'B', 'the finished first A published nothing');
    let settled = false;
    const sharer = loadRegs(MORRO, extra.fetchFn).then(() => { settled = true; });
    await tick();
    assert.deepEqual(extra.urls, [], 'another A caller issues no duplicate fetch');
    assert.equal(settled, false, 'and waits for the replacement');
    a2.ok(COPY, regs('current')); a2.ok(daily('morro-bay'), part('morro-bay', 'current')); await A2; await sharer;
    assert.equal(settled, true);
    assert.equal(regsData.value.data.mark, 'current');
    const before = extra.urls.length; await loadRegs(MORRO, extra.fetchFn);
    assert.equal(extra.urls.length, before, 'a clean read stays memoized');
  });
});

test('11: regs_reset_invalidates_pending_read - a read pending across resetRegs never publishes', OPTS, async () => {
  fresh(); const a1 = held(), a2 = held();
  await guarded([a1, a2], async () => {
    const A1 = loadRegs(MORRO, a1.fetchFn);
    resetRegs();
    const A2 = loadRegs(MORRO, a2.fetchFn);
    assert.deepEqual(a2.urls, [COPY, daily('morro-bay')], 'the replacement reads for itself');
    a2.ok(COPY, regs('current')); a2.ok(daily('morro-bay'), part('morro-bay', 'current')); await A2;
    a1.ok(COPY, obsolete('obsolete', true)); a1.ok(daily('morro-bay'), part('morro-bay', 'obsolete', NOW + 7200000)); await A1; await tick();
    assert.equal(regsData.value.data.mark, 'current');
  });
  fresh(); const c = held(), d = held();
  await guarded([c, d], async () => {
    const C = loadRegs(MORRO, c.fetchFn);
    resetRegs();
    c.ok(COPY, regs('obsolete')); c.ok(daily('morro-bay'), part('morro-bay', 'obsolete')); await C; await tick();
    assert.equal(regsData.value, null, 'nothing is published after a reset with no replacement');
    const D = loadRegs(MORRO, d.fetchFn);
    d.ok(COPY, regs('later')); d.ok(daily('morro-bay'), part('morro-bay', 'later')); await D;
    assert.equal(regsData.value.data.mark, 'later', 'a normal load still works');
  });
});

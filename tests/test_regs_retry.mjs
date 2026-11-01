// SC1737-01: the mark card's "Rules at a glance" line. A registry read that showed nothing for the
// region, or met a dropped connection, HTTP 429 or 5xx, is asked again by the next card instead of
// reading "Check rules" for the rest of the session. A good read is still made once, and cards opened
// together share one read. Synthetic registry from the frozen FE-61 fixture, as test_regs_wrapper.mjs builds it.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {loadRegs, regsData, resetRegs} from '../web/regs.ts';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const MORRO = fixture.region;
const NOW = Date.parse('2026-09-21T18:00:00Z');
const COMMITTED = 'data/regulations.json';
const daily = id => `/api/daily?region=${id}&part=regulations`;
function data(at = NOW) {
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(at - 3600000).toISOString();
  d.rules_review_status = 'reviewed';
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: new Date(at).toISOString()};
  }
  return d;
}
const part = (id, at = NOW) => ({schema_version: 1, part: 'regulations', region_id: id, generated_at: new Date(at).toISOString(), catch_probability: null, bite_score: null, regulations: data(at)});
/** answers: url -> 'throw' | HTTP status | 'bad-json' | body | () => Promise<Response>; every call is logged. */
function server(answers) {
  const urls = [];
  const fetchFn = async url => {
    urls.push(url);
    const a = answers[url];
    if (typeof a === 'function') return a();
    if (a === 'throw') throw new TypeError('Failed to fetch');
    if (a === 'bad-json') return new Response('{not json', {status: 200});
    if (typeof a === 'number') return new Response('', {status: a});
    return a === undefined ? new Response('', {status: 404}) : Response.json(a);
  };
  return {urls, fetchFn, set: (url, a) => { answers[url] = a; }};
}
const fresh = () => { resetRegs(); regsData.value = null; };
const shown = id => regsData.value?.region === id;

test('1: a read that throws on both files is asked again by the next card, which shows the registry', async () => {
  fresh();
  const s = server({[COMMITTED]: 'throw', [daily('morro-bay')]: 'throw'});
  await loadRegs(MORRO, s.fetchFn);
  assert.equal(regsData.value, null, 'nothing loaded: Check rules');
  assert.equal(s.urls.length, 2);
  s.set(COMMITTED, data()); s.set(daily('morro-bay'), part('morro-bay'));
  await loadRegs(MORRO, s.fetchFn);
  assert.equal(s.urls.length, 4, 'the next card reads again');
  assert.ok(shown('morro-bay'), 'and shows the registry');
  await loadRegs(MORRO, s.fetchFn);
  assert.equal(s.urls.length, 4, 'then it is read once');
});

test('2: committed 5xx/429 with the daily feed OK shows the rules but asks again until a clean read', async () => {
  for (const status of [503, 500, 599, 429]) {
    fresh();
    const s = server({[COMMITTED]: status, [daily('morro-bay')]: part('morro-bay')});
    await loadRegs(MORRO, s.fetchFn);
    assert.ok(shown('morro-bay'), `${status}: the daily registry shows`);
    await loadRegs(MORRO, s.fetchFn);
    assert.equal(s.urls.length, 4, `${status}: a transient failure is asked again`);
    s.set(COMMITTED, data());
    await loadRegs(MORRO, s.fetchFn);
    assert.equal(s.urls.length, 6, `${status}: still transient on the second read`);
    await loadRegs(MORRO, s.fetchFn);
    assert.equal(s.urls.length, 6, `${status}: after a clean read, no further fetch`);
    assert.ok(shown('morro-bay'));
  }
});

test('2b: a daily feed that drops after a good committed file is asked again', async () => {
  fresh();
  const s = server({[COMMITTED]: data(), [daily('morro-bay')]: 'throw'});
  await loadRegs(MORRO, s.fetchFn);
  assert.ok(shown('morro-bay'));
  await loadRegs(MORRO, s.fetchFn);
  assert.equal(s.urls.length, 4);
});

test('3: both files OK: a second card makes zero fetches', async () => {
  fresh();
  const s = server({[COMMITTED]: data(), [daily('morro-bay')]: part('morro-bay')});
  await loadRegs(MORRO, s.fetchFn);
  await loadRegs(MORRO, s.fetchFn);
  await loadRegs(MORRO, s.fetchFn);
  assert.equal(s.urls.length, 2);
  assert.ok(shown('morro-bay'));
});

test('4: nothing accepted (both 404, invalid JSON, another jurisdiction) means the next card asks again', async () => {
  const wrong = {...data(), jurisdiction_id: 'california-other'};
  for (const [committed, day] of [[404, 404], ['bad-json', 'bad-json'], [wrong, 404]]) {
    fresh();
    const s = server({[COMMITTED]: committed, [daily('morro-bay')]: day});
    await loadRegs(MORRO, s.fetchFn);
    assert.equal(regsData.value, null, 'Check rules');
    await loadRegs(MORRO, s.fetchFn);
    assert.equal(s.urls.length, 4, `${JSON.stringify(committed).slice(0, 20)}: asked again`);
  }
});

test('5: committed OK and the daily feed 404 or invalid is kept: no further fetch', async () => {
  for (const day of [404, 'bad-json', {...part('morro-bay'), region_id: 'other'}]) {
    fresh();
    const s = server({[COMMITTED]: data(), [daily('morro-bay')]: day});
    await loadRegs(MORRO, s.fetchFn);
    await loadRegs(MORRO, s.fetchFn);
    assert.equal(s.urls.length, 2, `${JSON.stringify(day).slice(0, 20)}: memoized`);
    assert.ok(shown('morro-bay'));
  }
});

test('6: two cards opened together share one read: one fetch per file, both resolve after it', async () => {
  fresh();
  let release;
  const gate = new Promise(r => { release = r; });
  const s = server({[COMMITTED]: async () => { await gate; return Response.json(data()); }, [daily('morro-bay')]: part('morro-bay')});
  const done = [];
  const a = loadRegs(MORRO, s.fetchFn).then(() => done.push('a'));
  const b = loadRegs(MORRO, s.fetchFn).then(() => done.push('b'));
  await new Promise(r => setTimeout(r, 10));
  assert.deepEqual(s.urls, [COMMITTED], 'the second card waits on the first read');
  assert.equal(done.length, 0, 'neither resolves before the read');
  release();
  await Promise.all([a, b]);
  assert.deepEqual(s.urls, [COMMITTED, daily('morro-bay')], 'one fetch per file');
  assert.ok(shown('morro-bay'), 'both resolve after the registry shows');
});

test('7: a late answer for region A never shows after region B\'s read started', async () => {
  fresh();
  const OTHER = {...MORRO, id: 'other-bay'};
  let release;
  const gate = new Promise(r => { release = r; });
  const s = server({[COMMITTED]: async () => { await gate; return Response.json(data()); }, [daily('morro-bay')]: part('morro-bay'), [daily('other-bay')]: 404});
  const lateA = loadRegs(MORRO, s.fetchFn);
  await new Promise(r => setTimeout(r, 10));
  const readB = loadRegs(OTHER, s.fetchFn);
  release();
  await Promise.all([lateA, readB]);
  assert.ok(!shown('morro-bay'), 'region A\'s late registry is refused');
  assert.ok(regsData.value === null || shown('other-bay'));
  const before = s.urls.length;
  await loadRegs(MORRO, s.fetchFn);
  assert.equal(s.urls.length, before + 2, 'back on region A, the card reads again');
  assert.ok(shown('morro-bay'));
});

// SC2037-05: the browser is asked to keep saved packs once, only after a save resolved; the dialog's words and
// the estimate line. A stubbed navigator.storage counts every call.
import assert from 'node:assert/strict';
import test from 'node:test';

const {keepSaved, storageLine, savePackKept, KEEP_WORDS, estimateWords} = await import('../web/trip.ts');

function stub({persisted = false, grant = true, missing = [], throws = false} = {}) {
  const calls = {persist: 0, persisted: 0, estimate: 0};
  const storage = {
    persist: async () => { calls.persist++; return grant; },
    persisted: async () => { calls.persisted++; return persisted; },
    estimate: async () => { calls.estimate++; if (throws) throw new Error('blocked'); return {usage: 1_500_000, quota: 2_000_000_000}; },
  };
  for (const m of missing) delete storage[m];
  return {nav: {storage}, calls};
}
const META = {region_id: 'x', region_name: 'X', saved_at: '2026-11-04T00:00:00Z', bytes: 1, missing: [], tiles: {saved: 0, planned: 0, min_zoom: 0, max_zoom: null}};

test('a successful save, not persisted: exactly one persist call, agreed or refused per the stub', async () => {
  for (const [grant, want] of [[true, 'agreed'], [false, 'refused']]) {
    const {nav, calls} = stub({grant});
    const r = await savePackKept(async () => META, nav);
    assert.equal(r.keep, want);
    assert.equal(r.meta, META);
    assert.equal(calls.persist, 1);
  }
});

test('already persisted: no persist call, "already keeps" words', async () => {
  const {nav, calls} = stub({persisted: true});
  assert.equal((await savePackKept(async () => META, nav)).keep, 'already');
  assert.equal(calls.persist, 0);
  assert.match(KEEP_WORDS.already, /already keeps saved packs/);
});

test('a save that fails or is cancelled makes no storage call at all', async () => {
  const controller = new AbortController();
  for (const save of [async () => { throw new Error('region config missing'); }, async () => { controller.abort(); throw new DOMException('aborted', 'AbortError'); }]) {
    const {nav, calls} = stub();
    await assert.rejects(savePackKept(save, nav));
    assert.deepEqual(calls, {persist: 0, persisted: 0, estimate: 0});
  }
});

test('API missing or throwing: unavailable, no words, no estimate line', async () => {
  for (const missing of [['persist'], ['persisted']]) {
    const {nav, calls} = stub({missing});
    assert.equal(await keepSaved(nav), 'unavailable');
    assert.equal(calls.persist, 0);
  }
  assert.equal(await keepSaved({}), 'unavailable');
  assert.equal(KEEP_WORDS.unavailable, '');
  assert.equal(await storageLine({}), null);
  assert.equal(await storageLine(stub({missing: ['estimate']}).nav), null);
  assert.equal(await storageLine(stub({throws: true}).nav), null);
  const bad = {storage: {persist: async () => { throw new Error('x'); }, persisted: async () => false}};
  assert.equal(await keepSaved(bad), 'unavailable');
});

test('the refused words and the estimate line', async () => {
  assert.equal(KEEP_WORDS.refused, 'This browser may clear saved packs when space is low.');
  assert.equal(KEEP_WORDS.agreed, 'This browser agreed to keep saved packs.');
  const line = await storageLine(stub().nav);
  assert.deepEqual(line, {used: 1_500_000, quota: 2_000_000_000});
  assert.equal(estimateWords(line), "Browser's estimate: 1.5 MB used of 2000.0 MB available");
});

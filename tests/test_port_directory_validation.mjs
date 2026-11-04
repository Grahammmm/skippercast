// RF1050-21: a malformed port directory takes the unavailable/retry path and never poisons the
// per-page cache; the next valid response is fetched once and reused. One ordered sequence in its
// own process, because loadPorts caches in module state. Offline: fetch is injected, never global.
import assert from 'node:assert/strict';
import test from 'node:test';
import {loadPorts} from '../web/ports.ts';

const port = (id, name, match, status = 'active') => ({id, name, region: id, status, forecast_point: id, forecast_name: name, match});
const valid = () => ({schema_version: 1, ports: [port('morro-bay', 'Morro Bay', [35.3667, -120.868]), port('san-pedro', 'San Pedro', [33.73, -118.27], 'preview')]});
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };
const reply = body => ({ok: true, json: async () => body});

test('directory_invalid_load_retries_without_poisoning_cache', async () => {
  const realFetch = globalThis.fetch;
  globalThis.fetch = () => { throw Error('network is blocked in tests'); };
  try {
    // A synthetic invalid 200 (incomplete forecast_name, impossible position): both concurrent callers share one failed fetch.
    const gate = deferred();
    let calls = 0;
    const invalid = async () => { calls++; await gate.promise; return reply({schema_version: 1, ports: [{...port('a', 'A', [95, 240]), forecast_name: undefined}]}); };
    const first = loadPorts(invalid), second = loadPorts(invalid);
    assert.equal(first, second, 'concurrent callers share one promise');
    gate.resolve();
    const outcomes = await Promise.allSettled([first, second]);
    for (const o of outcomes) { assert.equal(o.status, 'rejected'); assert.equal(o.reason.message, 'Invalid port directory'); }
    assert.equal(calls, 1, 'one failed fetch');

    // A not-ok response keeps its own message and also clears the cache.
    let notOk = 0;
    await assert.rejects(loadPorts(async () => { notOk++; return {ok: false, json: async () => valid()}; }), {message: 'Port choices are unavailable'});
    assert.equal(notOk, 1);

    // The next valid response is fetched once, with original values and order, and then reused.
    let good = 0;
    const body = valid();
    const fetchValid = async () => { good++; return reply(body); };
    const loaded = await loadPorts(fetchValid);
    assert.equal(good, 1);
    assert.deepEqual(loaded.map(p => p.id), ['morro-bay', 'san-pedro']);
    assert.deepEqual(loaded[0].match, [35.3667, -120.868]);
    assert.equal(loaded[1].status, 'preview');
    assert.equal(await loadPorts(fetchValid), loaded, 'later callers get the cached directory');
    assert.equal(await loadPorts(invalid), loaded, 'a cached success is not refetched, even by a different fetch');
    assert.equal(good, 1);
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = realFetch;
  }
});

import assert from 'node:assert/strict';
import test from 'node:test';
import {attach, SEAFLOOR_ID} from '../web/map/preview/seafloor.ts';

// A Range request can still receive a full 200 or an unrelated 206. Neither may
// mount relief or leave its response streaming; a matching 206 must still work.
for (const [name, status, range, ready] of [
  ['full response', 200, null, false],
  ['partial without Content-Range', 206, null, false],
  ['partial for another byte', 206, 'bytes 1-1/16', false],
  ['partial for multiple bytes', 206, 'bytes 0-1/16', false],
  ['partial with impossible total', 206, 'bytes 0-0/0', false],
  ['matching one-byte partial', 206, 'bytes 0-0/16', true],
]) {
  test(`relief probe: ${name}`, async () => {
    const events = [];
    const signal = new AbortController().signal;
    const archive = 'https://fixture.invalid/relief.pmtiles';
    const body = new ReadableStream({
      start(controller) { controller.enqueue(new Uint8Array(status === 200 ? 16 : range === 'bytes 0-1/16' ? 2 : 1)); },
      cancel() { events.push('cancel'); },
    });
    const ctx = {
      url: () => archive,
      signal,
      fetchFn: async (url, init) => {
        assert.equal(url, archive);
        assert.equal(new Headers(init.headers).get('Range'), 'bytes=0-0');
        assert.equal(init.signal, signal);
        return new Response(body, {status, headers: range ? {'Content-Range': range} : {}});
      },
      engine: {setOverlay(id) { events.push(`mount:${id}`); }},
      report({state}) { events.push(state); },
    };
    if (ready) {
      assert.ok(await attach(ctx));
      assert.deepEqual(events, ['cancel', `mount:${SEAFLOOR_ID}`, 'ready']);
    } else {
      await assert.rejects(attach(ctx), /one-byte range/);
      assert.deepEqual(events, ['cancel']);
    }
  });
}

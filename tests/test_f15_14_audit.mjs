import assert from 'node:assert/strict';
import test from 'node:test';
import {attach, SEAFLOOR_ID} from '../web/map/preview/seafloor.ts';

// Checking only status and Content-Range can mistake an empty or oversized
// reply for one byte. Cancel every probe and mount only a consistent 206.
for (const [name, status, range, length, ready] of [
  ['full response', 200, null, null, false],
  ['partial without Content-Range', 206, null, null, false],
  ['partial for another byte', 206, 'bytes 1-1/16', null, false],
  ['partial for multiple bytes', 206, 'bytes 0-1/16', null, false],
  ['partial with impossible total', 206, 'bytes 0-0/0', null, false],
  ['matching range with Content-Length 2', 206, 'bytes 0-0/16', '2', false],
  ['matching range with Content-Length 0', 206, 'bytes 0-0/16', '0', false],
  ['matching range with Content-Length 1', 206, 'bytes 0-0/16', '1', true],
  ['matching one-byte partial', 206, 'bytes 0-0/16', null, true],
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
        const headers = new Headers();
        if (range !== null) headers.set('Content-Range', range);
        if (length !== null) headers.set('Content-Length', length);
        return new Response(body, {status, headers});
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

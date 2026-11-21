import assert from 'node:assert/strict';
import test from 'node:test';
import {setImmediate} from 'node:timers/promises';
import {shareStatic} from '../web/shared-fetch.ts';

// F16-08: a fetch that never settles must not keep its cache key forever,
// even if one caller gives up and the transport does not honor cancellation.
test('a stalled static transfer expires before and after headers, and the retry fetches fresh', async t => {
  for (const phase of ['headers', 'body']) await t.test(phase, async t => {
    t.mock.timers.enable({apis: ['setTimeout']});
    const file = '/data/synthetic.json';
    const stall = Promise.withResolvers();
    const signals = [];
    let readingBody = false;
    const shared = shareStatic(async (_input, init) => {
      signals.push(init.signal);
      if (signals.length > 1) return Response.json({fresh: true});
      if (phase === 'headers') return stall.promise;
      return {ok: true, body: {}, clone: () => ({arrayBuffer: () => {
        readingBody = true;
        return stall.promise;
      }})};
    });

    const caller = new AbortController();
    const early = shared(file, {signal: caller.signal});
    const waiting = shared(file).catch(error => error);
    caller.abort(new Error('caller left'));
    await assert.rejects(early, /caller left/);
    assert.equal(signals.length, 1, 'two callers joined one transfer');
    assert.equal(readingBody, phase === 'body');

    t.mock.timers.tick(30_000);
    // A turn of the event loop bounds the negative control without a real sleep.
    const outcome = await Promise.race([waiting, setImmediate('still stalled')]);
    assert.equal(outcome?.name, 'TimeoutError', `expected timeout, got ${outcome}`);
    assert.equal(signals[0].aborted, true, 'the shared transport is asked to stop');
    assert.deepEqual(await (await shared(file)).json(), {fresh: true});
    assert.equal(signals.length, 2);
  });
});

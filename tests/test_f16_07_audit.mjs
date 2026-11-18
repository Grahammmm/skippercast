// F16-07: exercise the real regulation admission signal with synthetic, offline responses.
import assert from 'node:assert/strict';
import {setImmediate as nextTurn} from 'node:timers/promises';
import test from 'node:test';
import {loadRegs, regsData, resetRegs} from '../web/regs.ts';

const region = {id: 'test-bay', jurisdiction_id: 'test-coast', species: ['test-fish'], assets: {regulations: 'data/test-rules.json'}};
const startup = 'regions/test-bay/regulations-startup.json', registry = region.assets.regulations;
const daily = '/api/daily?region=test-bay&part=regulations';
const reviewed = '2026-01-02T00:00:00Z';
const rules = (name, reviewed_at = reviewed) => ({
  schema_version: 1, jurisdiction_id: region.jurisdiction_id, reviewed_at,
  valid_from: '2026-01-01', valid_through: '2026-01-31', common_notes: [], checks: {},
  sources: {test: {url: 'https://authority.invalid/rules'}},
  species: {'test-fish': {name, season: '', bag: '', size: '', details: [], source_ids: ['test'], windows: []}},
});
const part = (regulations = rules('daily')) => ({
  schema_version: 1, region_id: region.id, part: 'regulations', generated_at: reviewed,
  catch_probability: null, bite_score: null, regulations,
});
const shown = () => regsData.value?.data.species['test-fish'].name;
function fresh() { resetRegs(); regsData.value = null; }

for (const [label, at, winner] of [
  ['equal', reviewed, 'daily'], ['older', '2026-01-01T00:00:00Z', 'daily'], ['newer', '2026-01-03T00:00:00Z', 'registry'],
]) {
  test(`F16-07: daily shows while the startup body is held; a late ${label} registry leaves ${winner} displayed`, {timeout: 5000}, async () => {
    fresh();
    let startupBody;
    const held = new Response(new ReadableStream({start(body) { startupBody = body; }}));
    const calls = [];
    const loading = loadRegs(region, async url => {
      calls.push(url);
      if (url === startup) return held;
      if (url === daily) return Response.json(part());
      assert.equal(url, registry);
      return Response.json(rules('registry', at));
    });
    try {
      await nextTurn();
      assert.deepEqual(calls, [startup, daily]);
      assert.equal(regsData.value?.region, region.id, 'daily is visible before releasing the startup body');
      assert.equal(shown(), 'daily');
    } finally {
      // The startup copy is missing/invalid, so the full registry is only reached after this release.
      startupBody.enqueue(new TextEncoder().encode('{}'));
      startupBody.close();
      await loading;
    }
    assert.deepEqual(calls, [startup, daily, registry]);
    assert.equal(shown(), winner);
  });
}

test('F16-07: invalid daily candidates leave the valid full registry alone', async () => {
  for (const data of [
    {...part(), region_id: 'other-bay'}, {...part(), schema_version: 2},
    part({...rules('daily'), jurisdiction_id: 'other-coast'}), part({...rules('daily'), schema_version: 2}),
    part(rules('daily', 'not a review date')),
  ]) {
    fresh();
    await loadRegs(region, async url => url === daily ? Response.json(data)
      : url === startup ? new Response(null, {status: 404}) : Response.json(rules('registry')));
    assert.equal(shown(), 'registry', JSON.stringify(data));
  }
});

test('F16-07: a stalled fallback body reaches its deadline and a later retry safely admits daily', {timeout: 5000}, async t => {
  fresh();
  // Control the timeout without waiting for wall time; the fetch stub models an abortable response body.
  const deadlines = [];
  t.mock.method(AbortSignal, 'timeout', ms => {
    const controller = new AbortController();
    deadlines.push({ms, controller});
    return controller.signal;
  });
  let stalled, rejectBody;
  const loading = loadRegs(region, async (url, options) => {
    if (url === daily) return Response.json({...part(), region_id: 'other-bay'});
    if (url === startup) return new Response(null, {status: 404});
    stalled = options.signal;
    return new Response(new ReadableStream({start(body) {
      rejectBody = () => body.error(new DOMException('body deadline', 'TimeoutError'));
      stalled?.addEventListener('abort', rejectBody, {once: true});
    }}));
  });
  try {
    await nextTurn();
    const deadline = deadlines.find(({controller}) => controller.signal === stalled);
    assert.ok(deadline?.ms > 0 && Number.isFinite(deadline.ms), 'fallback has its own finite deadline');
    deadline.controller.abort();
    await loading;
    assert.equal(regsData.value, null, 'neither timed-out nor wrong-region data is shown');
  } finally {
    if (!stalled?.aborted) rejectBody?.();
    await loading;
  }
  await loadRegs(region, async url => url === daily ? Response.json(part()) : Response.json(rules('startup')));
  assert.equal(shown(), 'daily', 'the next read is not stuck on the failed attempt');
});

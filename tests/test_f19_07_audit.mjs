import test from 'node:test';
import assert from 'node:assert/strict';
import {PILOT_JURISDICTION, PILOT_SPECIES, runPreflight} from '../scripts/advisor/preflight.mjs';

const now = Date.parse('2026-10-20T16:00:00Z');
const emptyQueue = {stale_queued: 0, held_outbound: 0};
const recent = '2026-10-10T00:00:00Z';

async function checkRows(queue, reviewedAt) {
  const base = 'https://example.test';
  const rules = PILOT_SPECIES.map((species_key, index) => ({
    species_key, status: 'active', due: false, source_url: `${base}/rules`,
    reviewed_at: index === 0 ? reviewedAt : recent,
  }));
  const fetcher = async url => {
    if (url === `${base}/api/admin/health`) return Response.json({replies_enabled: true, queue});
    if (url === `${base}/api/admin/rules?jurisdiction=${PILOT_JURISDICTION}`) return Response.json({rules});
    return new Response(null, {status: 404});
  };
  return runPreflight({base, cookie: 'synthetic-session', fetcher, now});
}

// Protect the checklist from false passes when truthiness stands in for queue
// counts or a lexical comparison stands in for elapsed review time.
test('F19-07: preflight requires explicit empty counts and a review in the last 30 days', async t => {
  for (const [label, queue, reviewedAt, expectedQueue, expectedRules] of [
    ['explicit zeros and recent UTC review', emptyQueue, recent, 'pass', 'pass'],
    ['missing queue', undefined, recent, 'fail', 'pass'],
    ['empty queue object', {}, recent, 'fail', 'pass'],
    ['one missing counter', {stale_queued: 0}, recent, 'fail', 'pass'],
    ['null count', {...emptyQueue, stale_queued: null}, recent, 'fail', 'pass'],
    ['boolean count', {...emptyQueue, held_outbound: false}, recent, 'fail', 'pass'],
    ['string zero', {...emptyQueue, stale_queued: '0'}, recent, 'fail', 'pass'],
    ['negative count', {...emptyQueue, held_outbound: -1}, recent, 'fail', 'pass'],
    ['fractional count', {...emptyQueue, stale_queued: 0.5}, recent, 'fail', 'pass'],
    ['nonempty queue', {...emptyQueue, held_outbound: 1}, recent, 'fail', 'pass'],
    ['missing review timestamp', emptyQueue, undefined, 'pass', 'fail'],
    ['null review timestamp', emptyQueue, null, 'pass', 'fail'],
    ['unparseable review timestamp', emptyQueue, 'not a date', 'pass', 'fail'],
    ['future review timestamp', emptyQueue, '2026-10-20T16:00:00.001Z', 'pass', 'fail'],
    ['stale review timestamp', emptyQueue, '2026-09-20T15:59:59.999Z', 'pass', 'fail'],
    ['exactly 30 days ago with offset', emptyQueue, '2026-09-20T09:00:00-07:00', 'pass', 'pass'],
  ]) {
    await t.test(label, async () => {
      const rows = await checkRows(queue, reviewedAt);
      assert.equal(rows.find(r => r.id === '5' && r.title.startsWith('Queue healthy'))?.status, expectedQueue, 'queue check');
      assert.equal(rows.find(r => r.id === '6' && r.status !== 'manual')?.status, expectedRules, 'rules check');
    });
  }
});

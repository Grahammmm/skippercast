import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase} from './_advisor_d1.mjs';

// The health handlers need no deployed region data or transport.
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {activityDeps, health} = await import('../server/fleet/activity.ts');
const {aisHealth} = await import('../server/fleet/admin/ais-health.ts');
const NOW = new Date('2026-10-05T12:00:00.000Z');
const BEAT = '2026-10-05T11:59:00.000Z';
const DONE = '2026-10-05T11:59:30.000Z';

// F03-14: the job view used to clamp a future last-message age to zero,
// masking it as fresh while the admin view reported it as unknown/stale.
for (const [name, lastMessage, age, stale] of [
  ['future by 1 ms', '2026-10-05T12:00:00.001Z', null, true],
  ['current', '2026-10-05T12:00:00.000Z', 0, false],
  ['exactly three hours old', '2026-10-05T09:00:00.000Z', 10800, false],
  ['old', '2026-10-05T08:59:59.000Z', 10801, true],
]) {
  test(`AIS job and admin freshness agree when the last message is ${name}`, async t => {
    const {sql, db} = advisorDatabase();
    const saved = activityDeps.now;
    activityDeps.now = () => NOW;
    t.after(() => { activityDeps.now = saved; sql.close(); });
    const put = sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)');
    put.run('fleet.ais.CA.heartbeat', JSON.stringify({written_at: BEAT, last_message_at: lastMessage}), DONE);
    put.run('fleet.ais.CA.processed', JSON.stringify({at: DONE}), DONE);

    const {status, body} = await health(db, 'CA');
    const [admin] = (await aisHealth(db, 'CA', NOW)).regions;
    assert.equal(status, 200);
    assert.deepEqual(body.checks.heartbeat, {age_s: 60, stale: false});
    assert.deepEqual(body.checks.processed, {age_s: 30, stale: false});
    assert.equal(admin.last_message_age_s, age);
    assert.equal(admin.stale, stale);
    assert.deepEqual(body.checks.last_message, {age_s: age, stale});
    assert.equal(body.stale, stale);
    assert.equal(body.cause, stale ? 'no-messages' : 'none');
  });
}

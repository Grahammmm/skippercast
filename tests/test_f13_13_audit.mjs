// F13-13: a one-shot load latch leaves skill UNKNOWN after a transient read failure.
import assert from 'node:assert/strict';
import test from 'node:test';

const NOW = Date.parse('2026-11-05T12:00:00Z');
const PORT = 'fixture-port';
const scorecard = {
  schema_version: 1, generated_at: '2026-11-05T11:00:00Z', minimum: {valid_times: 30},
  scores: [{port: PORT, station: 'fixture-buoy', variable: 'wind_speed_10m', lead_hours: 24,
    window_days: 30, n: 50, within: 41, enough: true}],
};
const settle = () => new Promise(resolve => setImmediate(resolve));
const offline = () => { throw new TypeError('synthetic outage'); };
const unavailable = () => new Response(null, {status: 503});
const fresh = () => Response.json(scorecard);

for (const [name, replies] of [
  ['HTTP failure recovers on the delayed retry', [unavailable, fresh]],
  ['rejection and failed retry leave a later load eligible', [offline, unavailable, fresh]],
]) {
  test(name, async t => {
    const {loadSkill, skillFile, skillSummary, skillLine} = await import(`../web/brief/skill.ts?${encodeURIComponent(name)}`);
    const read = () => skillSummary(skillFile.value, PORT, NOW);
    t.mock.timers.enable({apis: ['setTimeout']});
    let count = 0;
    t.mock.method(globalThis, 'fetch', async () => replies[count++]());

    loadSkill();
    loadSkill();
    await settle();
    assert.equal(count, 1, 'overlapping loads share the same read');
    assert.equal(read().state, 'unknown');
    loadSkill();
    await settle();
    assert.equal(count, 1, 'loads during backoff do not start a second read');

    t.mock.timers.tick(5_000);
    await settle();
    assert.equal(count, 2, 'the first failure schedules a retry without remounting');
    if (replies.length === 3) {
      assert.equal(read().state, 'unknown');
      t.mock.timers.tick(60_000);
      await settle();
      assert.equal(count, 2, 'a failed retry does not start a polling loop');
      loadSkill();
      await settle();
    }
    assert.equal(read().state, 'known');
    assert.equal(read().parts[0].pct, 82);
    loadSkill();
    await settle();
    assert.equal(count, replies.length, 'a successfully read scorecard is reused');

    const aged = skillSummary(skillFile.value, PORT, NOW + 15 * 86_400_000);
    assert.equal(aged.state, 'unknown');
    assert.doesNotMatch(skillLine(aged), /%/);
  });
}

// RF1058-2: GET /api/fleet/jobs/health names the likely stale cause (server/fleet/activity.ts staleCause;
// docs/operations/runbooks/fleet-ais-down.md). The pure cases need no SQLite; the end-to-end case uses the
// real migrations (tests/_advisor_d1.mjs) and is skipped where SQLite is unavailable. Fixture clocks only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {staleCause, health, activityDeps, CAUSE_TOLERANCE_S, STALE_HOURS} = await import('../server/fleet/activity.ts');

const LIMIT = STALE_HOURS * 3600;
const c = ageS => ({age_s: ageS, stale: ageS === null || ageS > LIMIT});
const cause = (heartbeat, message, processed) => staleCause({heartbeat: c(heartbeat), last_message: c(message), processed: c(processed)}, {});
const H = 3600;

test('all fresh is none', () => {
  assert.equal(cause(60, 90, 30), 'none');
  assert.equal(cause(LIMIT, LIMIT, LIMIT), 'none', 'exactly at the threshold is not stale');
});

test('nothing pushed, or a missing clock, is no-data', () => {
  assert.equal(cause(null, null, null), 'no-data');
  assert.equal(cause(60, 60, null), 'no-data', 'heartbeat present but processed missing');
  assert.equal(cause(null, 60, 60), 'no-data', 'processed present but heartbeat missing');
});

test('the diagnostic shape (all three ages 4.48 h, equal) is processor-not-delivered', () => {
  const age = Math.round(4.48 * H);
  assert.equal(cause(age, age, age), 'processor-not-delivered');
  assert.equal(cause(age + 30, age + 20, age), 'processor-not-delivered', 'within 0.01 h of each other');
});

test('the tolerance boundary is 600 s', () => {
  assert.equal(CAUSE_TOLERANCE_S, 600);
  const p = 4 * H;
  assert.equal(cause(p + 600, p + 600, p), 'processor-not-delivered');
  assert.equal(cause(p + 601, p + 601, p), 'listener-stale');
  assert.equal(cause(p + 600, p + 601, p), 'no-messages', 'heartbeat current at the push, message older than the tolerance');
});

test('a fresh processor carrying an old heartbeat is listener-stale', () => {
  assert.equal(cause(4 * H, 4 * H, 600), 'listener-stale');
  assert.equal(cause(4 * H, null, 600), 'listener-stale', 'no last message either');
});

test('a heartbeat current at the push with an old last message is no-messages, never processor-not-delivered', () => {
  assert.equal(cause(4 * H, 5 * H, 4 * H), 'no-messages', 'processed stale');
  assert.equal(cause(60, 5 * H, 30), 'no-messages', 'processed fresh');
  assert.equal(cause(4 * H, null, 4 * H), 'no-messages', 'last_message_at missing');
  assert.notEqual(cause(4 * H, null, 4 * H), 'processor-not-delivered');
});

test('end to end: unparseable times are no-data; the body has six keys and no messages', {skip: sqliteUnavailable ?? false}, async () => {
  const {sql, db} = advisorDatabase();
  const saved = activityDeps.now;
  const put = (key, value) => sql.prepare('INSERT OR REPLACE INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(key, JSON.stringify(value), '2026-10-05T00:00:00Z');
  try {
    activityDeps.now = () => new Date('2026-10-05T12:00:00.000Z');
    let {status, body} = await health(db, 'CA');
    assert.equal(status, 200);
    assert.equal(body.cause, 'no-data', 'nothing pushed yet');

    put('fleet.ais.CA.heartbeat', {written_at: '2026-10-05T11:50:00Z', last_message_at: '2026-10-05T11:49:00Z', messages_24h: 47000});
    put('fleet.ais.CA.processed', {at: '2026-10-05T11:51:00.000Z', run_id: 'ais-1', counts: {}});
    ({body} = await health(db, 'CA'));
    assert.equal(body.stale, false);
    assert.equal(body.cause, 'none');

    activityDeps.now = () => new Date('2026-10-05T16:20:00.000Z');   // no push for 4.48 h: every clock aged together
    ({body} = await health(db, 'CA'));
    assert.equal(body.stale, true);
    assert.equal(body.cause, 'processor-not-delivered');
    assert.deepEqual(Object.keys(body).sort(), ['cause', 'checked_at', 'checks', 'region', 'stale', 'stale_after_s']);
    assert.equal(JSON.stringify(body).includes('messages'), false, 'no counters or listener state in the health answer');

    put('fleet.ais.CA.heartbeat', {written_at: 'soon', last_message_at: '2026-10-05T11:49:00Z'});
    ({body} = await health(db, 'CA'));
    assert.equal(body.checks.heartbeat.age_s, null);
    assert.equal(body.cause, 'no-data', 'an unparseable written_at does not throw');
  } finally { activityDeps.now = saved; sql.close(); }
});

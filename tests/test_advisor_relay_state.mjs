// RF1100-6: relayState (server/advisor/relay.ts) returns only the four known
// fields. A stored failure count that is not a non-negative whole number reads
// as 0 and an unreadable last_ok_at as null, so a damaged record can no longer
// keep the relay "up" for good: the watchdog's count restarts and still reaches
// down, and a stored down still holds the consumer.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

// cron.ts and consumer.ts reach the Worker config through the channel adapters, as in tests/test_advisor_cron.mjs.
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {relayState, RELAY_KEY} = await import('../server/advisor/relay.ts');
const {relayWatchdog} = await import('../server/advisor/cron.ts');
const {releaseHeld} = await import('../server/advisor/consumer.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const ON = {TEXT_ADVISOR_ENABLED: 'true'};
const RELAY = {BLUEBUBBLES_URL: 'https://relay.example.test/', BLUEBUBBLES_PASSWORD: 'pw', CF_ACCESS_CLIENT_ID: 'id.access', CF_ACCESS_CLIENT_SECRET: 'not-a-secret'};
const TICK = 15 * 60000, T0 = Date.parse('2026-10-03T15:00:00Z'), OK_AT = '2026-10-03T14:00:00.000Z';
const iso = ms => new Date(ms).toISOString();
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}; console.log = console.warn = console.error = () => {}; try { return await fn(); } finally { Object.assign(console, saved); } };

/** A fresh database with job_state advisor.relay set to `raw` (a string, stored as is) unless raw is undefined. */
function stored(raw) {
  const {sql, db} = advisorDatabase();
  if (raw !== undefined) sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run(RELAY_KEY, raw, OK_AT);
  return {sql, db, env: {...ON, ...RELAY, DB: db}};
}
const json = v => JSON.stringify(v);
const failingFetch = async () => new Response('', {status: 503});

dbTest('a stored text failure count restarts at 0: three failed pings mark the relay down, and the stored count is a number', async () => {
  const {sql, env} = stored(json({state: 'up', failures: 'x', checked_at: OK_AT, last_ok_at: OK_AT}));
  const outcomes = [];
  for (let i = 0; i < 3; i++) outcomes.push(await quiet(() => relayWatchdog(env, {fetcher: failingFetch}, T0 + i * TICK)));
  assert.deepEqual(outcomes, ['failing', 'failing', 'down'], 'down on the third failure, not never');
  const value = JSON.parse(sql.prepare('SELECT value FROM job_state WHERE key=?').get(RELAY_KEY).value);
  assert.deepEqual(value, {state: 'down', failures: 3, checked_at: iso(T0 + 2 * TICK), last_ok_at: OK_AT});
  assert.equal(typeof value.failures, 'number');
});

dbTest('other damaged counts (negative, fractional, huge, null, missing) also restart the watchdog at 0', async () => {
  for (const failures of [-4, 1.5, 2 ** 60, null, undefined, true, '2']) {
    const {env} = stored(json({state: 'up', failures, checked_at: OK_AT, last_ok_at: OK_AT}));
    assert.equal((await relayState(env)).failures, 0, `failures ${String(failures)} reads 0`);
    assert.equal(await quiet(() => relayWatchdog(env, {fetcher: failingFetch}, T0)), 'failing', `failures ${String(failures)}: one failure is not down`);
    assert.equal((await relayState(env)).failures, 1);
  }
});

dbTest('a stored down with a negative count stays down, reads failures 0, and the held release still sees down', async () => {
  const {env} = stored(json({state: 'down', failures: -4, checked_at: OK_AT, last_ok_at: OK_AT}));
  assert.deepEqual(await relayState(env), {state: 'down', failures: 0, checked_at: OK_AT, last_ok_at: OK_AT});
  const released = await quiet(() => releaseHeld(env, {}, T0));
  assert.equal(released.skipped, 'relay-down', 'the consumer hold check still sees down');
});

dbTest('well-formed values are kept; a fractional count reads 0 and an unreadable last_ok_at reads null', async () => {
  const good = {state: 'up', failures: 2, checked_at: OK_AT, last_ok_at: OK_AT};
  assert.deepEqual(await relayState(stored(json(good)).env), good, 'a well-formed record round-trips unchanged');
  const never = {state: 'down', failures: 0, checked_at: OK_AT, last_ok_at: null};
  assert.deepEqual(await relayState(stored(json(never)).env), never);
  assert.equal((await relayState(stored(json({...good, failures: 1.5})).env)).failures, 0);
  for (const last_ok_at of ['nope', '', 12345, {}, ['2026-10-03']]) {
    assert.equal((await relayState(stored(json({...good, last_ok_at})).env)).last_ok_at, null, `last_ok_at ${json(last_ok_at)} reads null`);
  }
  for (const checked_at of [7, null, undefined]) {
    assert.equal((await relayState(stored(json({...good, checked_at})).env)).checked_at, '', `checked_at ${json(checked_at)} reads ''`);
  }
});

dbTest('extra stored keys are not in the returned object', async () => {
  const state = await relayState(stored(json({state: 'up', failures: 1, checked_at: OK_AT, last_ok_at: OK_AT, secret: 'canary', __proto__x: 1})).env);
  assert.deepEqual(Object.keys(state).sort(), ['checked_at', 'failures', 'last_ok_at', 'state']);
  assert.ok(!json(state).includes('canary'));
});

dbTest('unchanged nulls: no row, bad JSON, an unknown state, JSON null or a non-object, and no DB', async () => {
  assert.equal(await relayState(stored().env), null, 'no row');
  for (const raw of ['{bad json', json({state: 'sideways', failures: 0}), 'null', '"up"', '3', '[]', json({failures: 1})]) {
    assert.equal(await relayState(stored(raw).env), null, `${raw} reads null`);
  }
  assert.equal(await relayState({}), null, 'no DB');
});

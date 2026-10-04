// Text Advisor cron hooks (server/advisor/cron.ts): local-time slots claimed in
// job_state (once per local day, never before their time, across the
// 1 Nov 2026 DST change, released when the job throws), the relay watchdog's
// state machine with a fake fetcher, and advisorCron's one-word outcome.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

// cron.ts reaches the Worker config (server/http.ts) through the held release and the channel adapters,
// which need the build-time globals, as in tests/test_advisor_consumer.mjs.
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {runSlot, localClock, relayWatchdog, relayState, advisorCron, SLOTS, SLOT_PREFIX, RELAY_KEY} = await import('../server/advisor/cron.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const ON = {TEXT_ADVISOR_ENABLED: 'true'};
const TICK = 15 * 60000;
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const iso = ms => new Date(ms).toISOString();

/** Run the slot on every 15-minute UTC tick in [from, to); returns the UTC times it ran. */
async function ticks(env, name, time, from, to) {
  const ran = [];
  for (let t = Date.parse(from); t < Date.parse(to); t += TICK) if (await runSlot(env, name, time, async () => {}, t) === 'ran') ran.push(iso(t));
  return ran;
}

test('localClock reads the local date, 24-hour time and weekday in the zone', () => {
  assert.deepEqual(localClock(Date.parse('2026-10-31T14:00:00Z')), {date: '2026-10-31', time: '07:00', weekday: 'Sat'});   // PDT, UTC-7
  assert.deepEqual(localClock(Date.parse('2026-11-01T15:00:00Z')), {date: '2026-11-01', time: '07:00', weekday: 'Sun'});   // PST, UTC-8
  assert.deepEqual(localClock(Date.parse('2026-11-02T07:30:00Z')), {date: '2026-11-01', time: '23:30', weekday: 'Sun'});
  assert.deepEqual(localClock(Date.parse('2026-11-02T08:05:00Z')), {date: '2026-11-02', time: '00:05', weekday: 'Mon'}, 'midnight is 00, not 24');
  assert.equal(localClock(Date.parse('2026-11-01T15:00:00Z'), 'UTC').time, '15:00');
});

test('the slot table is one exported array; TA-A1 added the daily answers at 05:30 Pacific', () => {
  assert.ok(Array.isArray(SLOTS));
  assert.deepEqual(SLOTS.map(s => [s.name, s.time.local, s.time.tz]), [['daily-answers', '05:30', 'America/Los_Angeles'], ['rules-watch', '06:15', 'America/Los_Angeles']]);
  assert.equal(new Set(SLOTS.map(s => s.name)).size, SLOTS.length, 'names are unique (they are job_state keys)');
  for (const s of SLOTS) assert.equal(typeof s.run, 'function', s.name);
});

dbTest('a slot runs once per local day, at its first tick at or after the local time, across the Nov 2026 DST change', async () => {
  const {sql, db} = advisorDatabase(), env = {DB: db};
  const ran = await ticks(env, 'daily-answers', {local: '07:00', tz: 'America/Los_Angeles'}, '2026-10-30T07:00:00Z', '2026-11-03T08:00:00Z');
  assert.deepEqual(ran, ['2026-10-30T14:00:00.000Z', '2026-10-31T14:00:00.000Z', '2026-11-01T15:00:00.000Z', '2026-11-02T15:00:00.000Z'],
    '07:00 PDT is 14:00 UTC, 07:00 PST is 15:00 UTC (window: local midnight 30 Oct to local midnight 3 Nov)');
  assert.equal(sql.prepare('SELECT value FROM job_state WHERE key=?').get(SLOT_PREFIX + 'daily-answers').value, '2026-11-02');
});

dbTest('a slot inside the repeated hour (01:30 on 1 Nov 2026) still runs once', async () => {
  const {db} = advisorDatabase();
  const ran = await ticks({DB: db}, 'repeated-hour', {local: '01:30'}, '2026-11-01T07:00:00Z', '2026-11-01T12:00:00Z');
  assert.deepEqual(ran, ['2026-11-01T08:30:00.000Z'], 'the first 01:30 (PDT); the second 01:30 (PST) finds the claim');
});

dbTest('a slot past its time when first deployed runs on the next tick, then not before tomorrow', async () => {
  const {db} = advisorDatabase(), env = {DB: db}, slot = {local: '06:00'};
  assert.equal(await runSlot(env, 'late', slot, async () => {}, Date.parse('2026-10-03T12:59:00Z')), 'not-yet', '05:59 PDT');
  assert.equal(await runSlot(env, 'late', slot, async () => {}, Date.parse('2026-10-03T20:00:00Z')), 'ran', '13:00 PDT');
  assert.equal(await runSlot(env, 'late', slot, async () => {}, Date.parse('2026-10-04T06:59:00Z')), 'done-today', '23:59 PDT, same local day');
  assert.equal(await runSlot(env, 'late', slot, async () => {}, Date.parse('2026-10-04T07:00:00Z')), 'not-yet', '00:00 next day, before 06:00');
});

dbTest('weekly slots run only on their weekday', async () => {
  const {db} = advisorDatabase();
  const ran = await ticks({DB: db}, 'retention', {local: '02:00', tz: 'UTC', weekday: 'Sun'}, '2026-10-26T00:00:00Z', '2026-11-10T00:00:00Z');
  assert.deepEqual(ran, ['2026-11-01T02:00:00.000Z', '2026-11-08T02:00:00.000Z']);
});

dbTest('a job that throws releases its claim, so the next tick retries; a second runner never runs it twice', async () => {
  const {sql, db} = advisorDatabase(), env = {DB: db}, time = {local: '07:00'}, t = Date.parse('2026-10-03T14:00:00Z');
  let calls = 0;
  const {value} = await quiet(() => runSlot(env, 'flaky', time, async () => { calls++; throw Error('upstream down'); }, t));
  assert.equal(value, 'failed'); assert.equal(calls, 1);
  assert.equal(sql.prepare('SELECT COUNT(*) n FROM job_state WHERE key=?').get(SLOT_PREFIX + 'flaky').n, 0, 'first-ever claim deleted');
  assert.equal(await runSlot(env, 'flaky', time, async () => { calls++; }, t + TICK), 'ran'); assert.equal(calls, 2);
  // A failure on a later day restores the previous day's value.
  const next = t + 86400000;
  await quiet(() => runSlot(env, 'flaky', time, async () => { throw Error('again'); }, next));
  assert.equal(sql.prepare('SELECT value FROM job_state WHERE key=?').get(SLOT_PREFIX + 'flaky').value, '2026-10-03');
  // Two concurrent ticks: the UPSERT-with-WHERE lets only one claim the day.
  let runs = 0;
  const job = async () => { runs++; await new Promise(r => setTimeout(r, 5)); };
  const results = await Promise.all([runSlot(env, 'race', time, job, t), runSlot(env, 'race', time, job, t)]);
  assert.equal(runs, 1); assert.ok(results.includes('ran'));
  assert.ok(results.some(r => r === 'claimed-elsewhere' || r === 'done-today'), `the other tick backs off: ${results}`);
});

dbTest('runSlot rejects bad names and times, and does nothing without D1', async () => {
  await assert.rejects(runSlot({}, 'Bad Name', {local: '07:00'}, async () => {}), /invalid slot/);
  await assert.rejects(runSlot({}, 'ok', {local: '7:00'}, async () => {}), /invalid slot/);
  assert.equal(await runSlot({}, 'ok', {local: '07:00'}, async () => {}), 'no-db');
});

/** A fetcher that answers from a script: true = 200, a number = that status, an Error = thrown. */
function fetcher(script) {
  const calls = [];
  return {calls, fetch: async (url, init) => {
    calls.push({url, headers: init.headers, signal: init.signal});
    const next = script.shift();
    if (next instanceof Error) throw next;
    return new Response('{"status":200,"message":"pong"}', {status: next === true ? 200 : next});
  }};
}
const RELAY = {BLUEBUBBLES_URL: 'https://relay.example.test/', BLUEBUBBLES_PASSWORD: 'pw&x', CF_ACCESS_CLIENT_ID: 'id.access', CF_ACCESS_CLIENT_SECRET: 'secret'};

dbTest('relay watchdog: ping with password and Access headers; three failures mark it down, one success brings it up', async () => {
  const {db} = advisorDatabase(), env = {...ON, ...RELAY, DB: db};
  const f = fetcher([true, 502, Error('connect ECONNREFUSED'), 503, 500, true]);
  const t0 = Date.parse('2026-10-03T15:00:00Z'), outcomes = [], logs = [];
  for (let i = 0; i < 6; i++) { const {value, lines} = await quiet(() => relayWatchdog(env, {fetcher: f.fetch}, t0 + i * TICK)); outcomes.push(value); logs.push(...lines); }
  assert.deepEqual(outcomes, ['up', 'failing', 'failing', 'down', 'down', 'up']);
  const url = new URL(f.calls[0].url);
  assert.equal(url.origin + url.pathname, 'https://relay.example.test/api/v1/ping');
  assert.equal(url.searchParams.get('password'), 'pw&x');
  assert.equal(f.calls[0].headers['CF-Access-Client-Id'], 'id.access'); assert.equal(f.calls[0].headers['CF-Access-Client-Secret'], 'secret');
  assert.ok(f.calls[0].signal instanceof AbortSignal);
  assert.equal(logs.filter(l => l.includes('advisor_relay_down')).length, 1, 'logged once, when it goes down');
  assert.ok(logs.some(l => l.includes('advisor_relay_up')));
  assert.ok(!logs.join('\n').includes('pw&x'), 'the password never reaches a log line');
  const state = await relayState(env);
  assert.deepEqual(state, {state: 'up', failures: 0, checked_at: iso(t0 + 5 * TICK), last_ok_at: iso(t0 + 5 * TICK)});
});

dbTest('relay watchdog keeps last_ok_at while failing and stores the JSON shape in job_state', async () => {
  const {sql, db} = advisorDatabase(), env = {...ON, ...RELAY, DB: db}, t0 = Date.parse('2026-10-03T15:00:00Z');
  const f = fetcher([true, 500, 500, 500]);
  for (let i = 0; i < 4; i++) await quiet(() => relayWatchdog(env, {fetcher: f.fetch}, t0 + i * TICK));
  const stored = JSON.parse(sql.prepare('SELECT value FROM job_state WHERE key=?').get(RELAY_KEY).value);
  assert.deepEqual(stored, {state: 'down', failures: 3, checked_at: iso(t0 + 3 * TICK), last_ok_at: iso(t0)});
});

dbTest('relay watchdog does nothing unless the channel is bluebubbles and BLUEBUBBLES_URL is set', async () => {
  const {db} = advisorDatabase(), f = fetcher([true]);
  assert.equal(await relayWatchdog({...ON, DB: db}, {fetcher: f.fetch}), 'not-configured');
  assert.equal(await relayWatchdog({...ON, ...RELAY, ADVISOR_CHANNEL: 'twilio', DB: db}, {fetcher: f.fetch}), 'not-configured');
  assert.equal(f.calls.length, 0);
});

dbTest('advisorCron: disabled, no-db, ok, partial on a failed slot or a failing relay', async () => {
  const {db} = advisorDatabase(), now = Date.parse('2026-10-03T15:00:00Z');
  assert.equal(await advisorCron({DB: db}, now), 'disabled');
  assert.equal(await advisorCron({...ON}, now), 'no-db');
  assert.equal(await advisorCron({...ON, DB: db}, now), 'ok', 'no relay configured, no slots');
  let ran = 0;
  const slots = [{name: 'good', time: {local: '07:00'}, run: async () => { ran++; }}, {name: 'bad', time: {local: '07:00'}, run: async () => { throw Error('x'); }}];
  assert.equal((await quiet(() => advisorCron({...ON, DB: db}, now, {slots}))).value, 'partial');
  assert.equal(ran, 1);
  assert.equal((await quiet(() => advisorCron({...ON, DB: db}, now, {slots: slots.slice(0, 1)}))).value, 'ok', 'good already ran today');
  assert.equal(ran, 1);
  assert.equal((await quiet(() => advisorCron({...ON, ...RELAY, DB: db}, now, {fetcher: fetcher([500]).fetch}))).value, 'partial');
  const broken = {prepare() { throw Error('D1 down'); }};
  assert.equal((await quiet(() => advisorCron({...ON, DB: broken}, now, {slots}))).value, 'error');
});

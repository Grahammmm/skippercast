import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {registerHooks} from 'node:module';
import {DatabaseSync} from 'node:sqlite';
import test from 'node:test';

const ORIGIN = 'https://fixture.invalid';
const DAY = '2026-11-12', SAVED = '2026-11-10T12:00:00.000Z';
const FINAL = Date.parse('2026-11-11T19:00:00Z');
const HOUR = 3_600_000;
globalThis.REGIONS = {fixture: {
  id: 'fixture', timezone: 'UTC', forecast_points: [{id: 'point', name: 'Fixture point'}],
  intelligence_feed: ORIGIN + '/forecast', daily_feed: ORIGIN + '/daily',
  marine_zones: {coastal: 'TEST', offshore: 'TEST2'}, harbor: {information_url: ORIGIN},
}};
globalThis.DEPLOYMENT = {public_origin: ORIGIN, allowed_origins: [ORIGIN]};
// Exercise the real sender/status handling without generating keys, encrypting or using any live transport.
const hooks = registerHooks({resolve(specifier, context, next) {
  if (specifier === '@block65/webcrypto-web-push') {
    return {url: 'data:text/javascript,export const buildPushPayload = ({data}) => ({method:"POST",body:data})', shortCircuit: true};
  }
  return next(specifier, context);
}});
const {checkOwnerTrips, checkTrips, ownersWithDueTrips} = await import('../server/trips.ts').finally(() => hooks.deregister());
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const migrations = JSON.parse(read('../drizzle/meta/_journal.json')).entries;

function setup(t, replies) {
  t.mock.timers.enable({apis: ['Date'], now: FINAL});
  const sql = new DatabaseSync(':memory:');
  t.after(() => sql.close());
  for (const {tag} of migrations) sql.exec(read(`../drizzle/${tag}.sql`));
  const DB = {
    prepare(query) {
      const statement = sql.prepare(query);
      let args = [];
      return {
        bind(...values) { args = values; return this; },
        async first() { return statement.get(...args) ?? null; },
        async all() { return {results: statement.all(...args)}; },
        async run() { return {meta: {changes: Number(statement.run(...args).changes)}}; },
      };
    },
    async batch(statements) { return Promise.all(statements.map(statement => statement.run())); },
  };
  const owner = 'synthetic-owner', trip = 'synthetic-trip';
  const env = {DB, VAPID_PUBLIC_KEY: 'mock', VAPID_PRIVATE_KEY: 'mock'};
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)')
    .run(trip, owner, 'fixture', 'point', 'reef', DAY, 7, 13, 8, 12, 3, SAVED);
  const addDevice = device => sql.prepare('INSERT INTO subscriptions(id,owner,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)')
    .run(device, owner, ORIGIN + '/push/' + device, 'mock', 'mock', SAVED);
  for (const device of Object.keys(replies)) addDevice(device);
  const pushes = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    if (options?.method !== 'POST') return new Response(null, {status: 503});
    const device = String(url).split('/').at(-1);
    const reply = replies[device]?.[pushes.filter(push => push.device === device).length];
    pushes.push({device, ...JSON.parse(options.body)});
    if (!reply) throw new Error('synthetic transport timeout');
    return new Response(null, {status: reply});
  });
  return {sql, owner, addDevice, pushes, devices: () => pushes.map(push => push.device),
    check: now => { t.mock.timers.setTime(now); return checkOwnerTrips(env, owner, now); },
    manual: now => { t.mock.timers.setTime(now); return checkTrips(env); },
    dueOwners: () => ownersWithDueTrips(env),
    event: () => sql.prepare('SELECT id,status,delivered_at FROM alert_events').get(),
    trip: () => sql.prepare('SELECT last_assessment,final_delivered_at FROM trips').get(),
    receipts: device => sql.prepare('SELECT status FROM delivery_receipts WHERE subscription_id=? ORDER BY rowid').all(device).map(row => row.status),
  };
}

test('a finalized mixed 201/503 alert is due until just the phone recovers', async t => {
  const f = setup(t, {home: [201], phone: [503, 201], uncertain: [null]});
  assert.equal((await f.check(FINAL)).delivered, 1);
  const before = f.event(), tripBefore = f.trip();
  assert.equal(before.status, 'delivered');
  assert.ok(tripBefore.final_delivered_at);
  assert.deepEqual(f.devices().sort(), ['home', 'phone', 'uncertain']);
  const due = await f.dueOwners();
  f.addDevice('new-device');
  await f.check(FINAL + HOUR);
  assert.deepEqual(f.devices().slice(3), ['phone']);
  assert.deepEqual(due, [f.owner], 'queue still admits the finalized trip’s owner');
  assert.deepEqual(f.receipts('phone'), ['failed', 'accepted']);
  assert.deepEqual(f.receipts('uncertain'), ['uncertain']);
  assert.deepEqual(f.event(), before, 'retry preserves the event and first delivery time');
  assert.deepEqual(f.trip(), tripBefore, 'retry does not re-assess or re-finalize the trip');
  assert.equal(f.pushes.at(-1).eventId, before.id);
  assert.match(f.pushes.at(-1).body, /recheck current conditions/i);
  assert.doesNotMatch(f.pushes.at(-1).body, /Day-before assessment|unverified/i, 'retry does not replay old forecast text');
  assert.deepEqual(await f.dueOwners(), []);
  assert.equal((await f.check(FINAL + 2 * HOUR)).checked, 0);
});

test('manual checks retry a read alert without reopening it and stop at three attempts', async t => {
  const f = setup(t, {home: [201], phone: [503, 429, 503, 201], uncertain: [503, null, 201]});
  await f.check(FINAL);
  f.sql.prepare("UPDATE alert_events SET status='read'").run();
  const before = f.event();
  await f.manual(FINAL + HOUR);
  assert.deepEqual(f.devices().slice(3).sort(), ['phone', 'uncertain']);
  await f.manual(FINAL + 2 * HOUR);
  assert.equal((await f.manual(FINAL + 3 * HOUR)).checked, 0);
  assert.deepEqual(f.devices().slice(5), ['phone']);
  assert.deepEqual(f.receipts('uncertain'), ['failed', 'uncertain']);
  assert.deepEqual(f.receipts('phone'), ['failed', 'failed', 'failed']);
  assert.deepEqual(f.event(), before);
});

test('a prior nonfinal alert retries even when no new assessment alert is due', async t => {
  const f = setup(t, {home: [201], phone: [503, 201]});
  await f.check(FINAL - 3 * HOUR);
  const before = f.event();
  assert.equal((await f.check(FINAL - 2 * HOUR)).changes, 0);
  assert.deepEqual(f.devices().slice(2), ['phone']);
  assert.deepEqual(f.event(), before);
});

test('positive control: a lone pending 503 still recovers on the next check', async t => {
  const f = setup(t, {phone: [503, 201]});
  await f.check(FINAL);
  assert.equal(f.event().status, 'pending');
  assert.equal((await f.check(FINAL + HOUR)).delivered, 1);
  assert.deepEqual(f.devices(), ['phone', 'phone']);
  assert.deepEqual(f.receipts('phone'), ['failed', 'accepted']);
});

test('finalized alerts outside the retry window are not replayed', async t => {
  const f = setup(t, {home: [201], phone: [503, 201]});
  await f.check(FINAL);
  assert.equal((await f.manual(FINAL + 25 * HOUR)).checked, 0);
  assert.deepEqual(await f.dueOwners(), []);
  assert.deepEqual(f.receipts('phone'), ['failed']);
});

// RF1510-19: a catch-log timestamp is stored as UTC and paged by a cursor that only knows four-digit years.
// A written time whose zone conversion leaves 0000-9999 is refused at admission, before any lookup or write.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.BUILD_ID = 'build-test';
globalThis.SHELLS = {'/': '/index.0123456789.html', '/index.html': '/index.0123456789.html', '/landing.html': '/landing.0123456789.html', '/app.html': '/app.0123456789.html'};
const {default: deployed} = await import('../server/index.ts');
const {encodeLogCursor, decodeLogCursor} = await import('../server/routes/catch-log.ts');
const worker = withSessions(deployed), ORIGIN = 'https://skippercast.com';

function database() {
  const sql = new DatabaseSync(':memory:');
  for (const {tag} of [...read('../drizzle/meta/_journal.json').entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { const out = []; for (const q of queries) out.push(await q.run()); return out; }};
  return {sql, adapter};
}
const call = (env, path, {owner, method = 'GET', body} = {}) => {
  const headers = {'Content-Type': 'application/json', 'CF-Connecting-IP': '203.0.113.9'};
  if (owner) headers['x-test-owner'] = owner;
  if (method !== 'GET') headers.Origin = ORIGIN;
  return worker.fetch(new Request(ORIGIN + path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)}), env);
};
// Network blocked and the database closed even when an assertion fails; every request is its own account (30 writes a minute each).
async function withLog(fn) {
  const {sql, adapter} = database(), original = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error('offline'); };
  try { await fn(sql, {DB: adapter}); } finally { globalThis.fetch = original; sql.close(); }
}
let accounts = 0;
const fresh = () => 'rf1510-19-' + accounts++;
const BLANK = {started_at: '2026-11-02T14:00:00Z', outcome: 'blank'};
const post = async (env, entry, owner = fresh()) => { const r = await call(env, '/api/catch-log', {owner, method: 'POST', body: entry}); return {status: r.status, data: await r.json()}; };
const patch = async (env, owner, id, change) => { const r = await call(env, '/api/catch-log/' + id, {owner, method: 'PATCH', body: change}); return {status: r.status, data: await r.json()}; };
const ISO_ERROR = name => `${name} must be an ISO date and time with a zone`;
const rows = sql => sql.prepare('SELECT COUNT(*) AS n FROM catch_log').get().n;

// Converting to UTC leaves 0000-9999 on the high side (start 9999-12-31T23:30-01:00 is 10000-01-01) or the low side.
const HIGH = ['9999-12-31T23:30:00-01:00', '9999-12-31T23:00:00.000-01:00', '9999-12-31T23:59:59-14:00'];
const LOW = ['0000-01-01T00:30:00+01:00', '0000-01-01T00:59:59.999+01:00', '0000-01-01T00:00:00+14:00', '0000-01-01T00:00:00.000+00:01'];

test('catch_log_refuses_utc_year_overflow_on_post_before_any_lookup_or_write', async () => withLog(async (sql, env) => {
  for (const value of [...HIGH, ...LOW]) {
    for (const field of ['started_at', 'ended_at']) {
      const entry = field === 'started_at' ? {...BLANK, started_at: value} : {...BLANK, started_at: '0000-01-01T12:00:00Z', ended_at: value};
      const r = await post(env, entry);
      assert.deepEqual([r.status, r.data.error], [400, ISO_ERROR(field)], `${field} ${value}`);
    }
    // The owner's trip is looked up only after validation: an unknown trip id must not turn an overflow into a 404.
    const r = await post(env, {...BLANK, started_at: value, trip_id: 'no-such-trip'});
    assert.deepEqual([r.status, r.data.error], [400, ISO_ERROR('started_at')], `trip ${value}`);
  }
  assert.equal(rows(sql), 0, 'no row saved');
}));

test('catch_log_later_end_beyond_the_domain_is_refused_as_a_bad_time_never_as_earlier', async () => withLog(async (sql, env) => {
  // 9999-12-31T23:30-01:00 is genuinely later than the start; before the fix it sorted as a "+010000" string and read as earlier.
  const r = await post(env, {...BLANK, started_at: '9999-12-31T23:00:00Z', ended_at: '9999-12-31T23:30:00-01:00'});
  assert.deepEqual([r.status, r.data.error], [400, ISO_ERROR('ended_at')]);
  assert.equal(rows(sql), 0);
  // A later end inside the domain is accepted, and so is an equal one.
  const later = await post(env, {...BLANK, started_at: '9999-12-31T23:00:00Z', ended_at: '9999-12-31T23:59:59.999Z'});
  assert.deepEqual([later.status, later.data.ended_at], [201, '9999-12-31T23:59:59.999Z']);
  assert.equal((await post(env, {...BLANK, started_at: '9999-12-31T23:00:00Z', ended_at: '9999-12-31T23:00:00Z'})).status, 201);
  // A true reversal keeps its own message.
  const reversed = await post(env, {...BLANK, started_at: '9999-12-31T23:00:00Z', ended_at: '9999-12-31T22:59:59Z'});
  assert.deepEqual([reversed.status, reversed.data.error], [400, 'ended_at is before started_at']);
}));

test('catch_log_accepts_the_exact_domain_boundaries_and_every_started_at_round_trips_the_cursor', async () => withLog(async (sql, env) => {
  const cases = [['0000-01-01T00:00:00.000Z', '0000-01-01T00:00:00.000Z'], ['9999-12-31T23:59:59.999Z', '9999-12-31T23:59:59.999Z'],
    ['0000-01-01T01:00:00+01:00', '0000-01-01T00:00:00.000Z'], ['0000-01-01T14:00:00+14:00', '0000-01-01T00:00:00.000Z'],
    ['9999-12-31T22:59:59.999-01:00', '9999-12-31T23:59:59.999Z'], ['9999-12-31T09:59:59.999-14:00', '9999-12-31T23:59:59.999Z'],
    ['2026-12-31T23:59:59-08:00', '2027-01-01T07:59:59.000Z']];
  for (const [written, stored] of cases) {
    const r = await post(env, {...BLANK, started_at: written});
    assert.deepEqual([r.status, r.data.started_at], [201, stored], written);
    assert.deepEqual(decodeLogCursor(encodeLogCursor(r.data.started_at, r.data.id)), {started_at: stored, id: r.data.id}, `cursor ${written}`);
  }
  assert.equal(rows(sql), cases.length);
  // Optional end: omitted and null stay allowed.
  assert.equal((await post(env, {...BLANK, ended_at: null})).status, 201);
  assert.equal((await post(env, {...BLANK})).status, 201);
}));

test('catch_log_keeps_its_existing_time_refusals', async () => withLog(async (sql, env) => {
  for (const [entry, error] of [[{outcome: 'blank'}, 'started_at is required'], [{...BLANK, started_at: null}, 'started_at is required'], [{...BLANK, started_at: '2026-11-02T14:00:00'}, ISO_ERROR('started_at')],
    [{...BLANK, started_at: '2026-02-30T14:00:00Z'}, ISO_ERROR('started_at')], [{...BLANK, started_at: '2026-11-02T24:00:00Z'}, ISO_ERROR('started_at')], [{...BLANK, ended_at: '2026-11-02T24:00:00Z'}, ISO_ERROR('ended_at')]]) {
    const r = await post(env, entry);
    assert.deepEqual([r.status, r.data.error], [400, error], JSON.stringify(entry));
  }
  assert.equal(rows(sql), 0);
}));

test('catch_log_patch_refuses_utc_year_overflow_and_leaves_the_row_alone', async () => withLog(async (sql, env) => {
  const owner = fresh(), made = await post(env, {...BLANK, started_at: '9999-12-31T22:00:00Z', ended_at: '9999-12-31T22:30:00Z'}, owner);
  assert.equal(made.status, 201);
  const before = JSON.stringify(sql.prepare('SELECT * FROM catch_log WHERE id=?').get(made.data.id));
  for (const [change, field] of [[{started_at: HIGH[0]}, 'started_at'], [{started_at: LOW[0]}, 'started_at'], [{ended_at: HIGH[0]}, 'ended_at'], [{ended_at: HIGH[1]}, 'ended_at'], [{ended_at: LOW[0]}, 'ended_at']]) {
    const r = await patch(env, owner, made.data.id, change);
    assert.deepEqual([r.status, r.data.error], [400, ISO_ERROR(field)], JSON.stringify(change));
  }
  assert.equal(JSON.stringify(sql.prepare('SELECT * FROM catch_log WHERE id=?').get(made.data.id)), before, 'row unchanged');
  // Boundary values inside the domain are accepted by PATCH.
  const ok = await patch(env, owner, made.data.id, {ended_at: '9999-12-31T22:59:59.999-01:00'});
  assert.deepEqual([ok.status, ok.data.ended_at], [200, '9999-12-31T23:59:59.999Z']);
}));

test('catch_log_patch_missing_foreign_and_anonymous_requests_keep_their_status_before_body_validation', async () => withLog(async (sql, env) => {
  const owner = fresh(), made = await post(env, BLANK, owner), overflow = {started_at: HIGH[0]};
  assert.equal((await patch(env, owner, 'no-such-id', overflow)).status, 404, 'missing');
  assert.equal((await patch(env, fresh(), made.data.id, overflow)).status, 404, 'foreign');
  assert.equal((await call(env, '/api/catch-log/' + made.data.id, {method: 'PATCH', body: overflow})).status, 401, 'anonymous');
  assert.equal(sql.prepare('SELECT started_at FROM catch_log WHERE id=?').get(made.data.id).started_at, '2026-11-02T14:00:00.000Z');
}));

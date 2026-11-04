// POST /api/jobs/check: only an absent cursor means the first page. Any explicit non-string cursor is
// refused as 400 'invalid cursor' after the token is verified and before budget or trip-query work.
import test, {beforeEach, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {Hono} from 'hono';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
const {jobs} = await import('../server/routes/jobs.ts');
const {onError} = await import('../server/middleware/error.ts');
const {resetJwksCacheForTests} = await import('../server/job-auth.ts');

const policy = globalThis.DEPLOYMENT, s = policy.scheduler;
const app = new Hono();
app.route('/', jobs);
app.onError(onError);

const b64 = x => Buffer.from(JSON.stringify(x)).toString('base64url');
const pair = await crypto.subtle.generateKey({name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256'}, true, ['sign', 'verify']);
const jwk = {...await crypto.subtle.exportKey('jwk', pair.publicKey), kid: 'cursor-test', alg: 'RS256', use: 'sig'};
async function token(jti = 'cursor-test-run') {
  const now = Math.floor(Date.now() / 1000);
  const claims = {iss: 'https://token.actions.githubusercontent.com', aud: policy.public_origin + '/api/jobs/check', sub: `repo:${s.repository}:ref:${s.ref}`, repository: s.repository, repository_id: s.repository_id, repository_owner_id: s.owner_id, ref: s.ref, workflow_ref: s.repository + '/' + s.workflow + '@' + s.ref, event_name: 'schedule', iat: now, nbf: now, exp: now + 300, jti};
  const head = b64({alg: 'RS256', typ: 'JWT', kid: 'cursor-test'}) + '.' + b64(claims);
  return head + '.' + Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5', pair.privateKey, new TextEncoder().encode(head))).toString('base64url');
}

// A fixed local key set; any other outbound fetch fails the test.
const realFetch = globalThis.fetch, realError = console.error, realWarn = console.warn;
let jwksFetches, stray;
beforeEach(() => {
  resetJwksCacheForTests(); jwksFetches = 0; stray = [];
  console.error = () => {}; console.warn = () => {};
  globalThis.fetch = async url => {
    if (String(url) === 'https://token.actions.githubusercontent.com/.well-known/jwks') { jwksFetches++; return Response.json({keys: [jwk]}); }
    stray.push(String(url)); throw Error('unexpected fetch');
  };
});
afterEach(() => { globalThis.fetch = realFetch; console.error = realError; console.warn = realWarn; resetJwksCacheForTests(); assert.deepEqual(stray, []); });

// An in-memory database that counts budget writes and trip queries.
function harness(trips = []) {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const seen = {budget: 0, trips: 0, other: 0, cursors: []};
  const wrap = (query, statement) => { let args = []; return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { if (/SELECT \* FROM trips/.test(query)) seen.cursors.push(args[0]); return {results: statement.all(...args)}; }, async run() { return {meta: {changes: Number(statement.run(...args).changes)}}; }}; };
  const adapter = {prepare(query) { seen[/request_limits\(/.test(query) ? 'budget' : /SELECT \* FROM trips/.test(query) ? 'trips' : 'other']++; return wrap(query, sql.prepare(query)); },
    async batch(queries) { for (const q of queries) await q.run(); return []; }};
  return {env: {DB: adapter}, seen, sql};
}
const post = async (env, bodyText, headers) => {
  const res = await app.request('https://skippercast.com/api/jobs/check', {method: 'POST', headers: headers ?? {Authorization: 'Bearer ' + await token(), 'Content-Type': 'application/json'}, body: bodyText}, env);
  return {status: res.status, json: await res.json().catch(() => null)};
};
const INVALID = {error: 'invalid cursor'};

test('job_cursor_rejects_every_explicit_nonstring_before_budget', async () => {
  for (const value of [null, false, true, 0, -1, 1, 17, 1.5, [], ['a'], {}, {a: 'b'}]) {
    const {env, seen} = harness();
    const {status, json} = await post(env, JSON.stringify({cursor: value}));
    assert.equal(status, 400, JSON.stringify(value));
    assert.deepEqual(json, INVALID, JSON.stringify(value));
    assert.equal(seen.budget, 0, 'no budget write for ' + JSON.stringify(value));
    assert.equal(seen.trips, 0, 'no trip query for ' + JSON.stringify(value));
    assert.equal(seen.other, 0, 'no storage work for ' + JSON.stringify(value));
  }
});

test('job_cursor_missing_and_empty_start_first_page', async () => {
  for (const text of ['{}', '{"cursor":""}', '{"other":1}']) {
    const {env, seen} = harness();
    const {status, json} = await post(env, text);
    assert.equal(status, 200, text);
    assert.equal(json.checked, 0); assert.equal(json.next_cursor, null);
    assert.equal(seen.budget, 1, 'one budget write for ' + text);
    assert.equal(seen.trips, 1, 'one first-page lookup for ' + text);
    assert.deepEqual(seen.cursors, [''], 'first page starts after the empty cursor');
  }
});

test('job_cursor_preserves_valid_string_and_length_boundary', async () => {
  for (const cursor of ['trip-000123', ' ', ' x ', 'a'.repeat(50), '😀'.repeat(25)]) {
    const {env, seen} = harness();
    const {status} = await post(env, JSON.stringify({cursor}));
    assert.equal(status, 200, JSON.stringify(cursor));
    assert.deepEqual(seen.cursors, [cursor], 'the string is passed on unchanged');
    assert.equal(seen.budget, 1);
  }
  for (const cursor of ['a'.repeat(51), '😀'.repeat(26), '😀'.repeat(25) + 'a']) { // UTF-16 length counts: a surrogate pair is 2
    const {env, seen} = harness();
    const {status, json} = await post(env, JSON.stringify({cursor}));
    assert.equal(status, 400); assert.deepEqual(json, INVALID);
    assert.equal(seen.budget + seen.trips + seen.other, 0, 'refused before storage');
  }
});

test('job_cursor_authentication_precedes_validation', async () => {
  const bad = JSON.stringify({cursor: false});
  for (const headers of [{}, {Authorization: 'Bearer'}, {Authorization: 'Bearer not.a.token'}, {Authorization: 'Bearer ' + (await token()).slice(0, -4) + 'AAAA'}]) {
    const {env, seen} = harness();
    const {status, json} = await post(env, bad, headers);
    assert.equal(status, 401); assert.deepEqual(json, {error: 'Unauthorized'});
    assert.equal(seen.budget + seen.trips + seen.other, 0, 'no storage call for an unauthorised caller');
  }
  // No token at all never fetches the key set; a malformed body is not reached either.
  resetJwksCacheForTests(); jwksFetches = 0;
  const {env} = harness();
  assert.equal((await post(env, 'not json', {})).status, 401);
  assert.equal(jwksFetches, 0, 'no JWKS request for a missing token');
});

test('job_cursor_invalid_json_still_uses_body_error', async () => {
  for (const text of ['not json', '[]', '[{"cursor":"a"}]', 'null', '"cursor"', '']) {
    const {env, seen} = harness();
    const {status, json} = await post(env, text);
    assert.equal(status, 400, JSON.stringify(text));
    assert.ok(['invalid JSON body', 'invalid empty body'].includes(json.error), json.error);
    assert.notEqual(json.error, 'invalid cursor');
    assert.equal(seen.budget + seen.trips + seen.other, 0);
  }
});

// SCA-610 / F02-11. A Page create may commit before its HTTP 503 arrives.
// Contract: one create attempt, explicit durable uncertainty (not confirmed
// posted), and no second create on the next tick. An ordinary acknowledged
// create still works. The Graph client's GET retries have their own coverage
// in test_advisor_meta.mjs; this fixture exercises the missing write lifecycle.
//   node --test tests/test_f02_11_audit.mjs        (reference and healthy controls)
//   node tests/test_f02_11_audit.mjs --baseline     (also print real-path gaps)
// The baseline is diagnostic, not an assertion that replaying a create is OK.
import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase} from './_advisor_d1.mjs';

// Synthetic build bindings; no deployment configuration is loaded.
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {publishDue} = await import('../server/advisor/social/publish.ts');
const {fbFeed, fbPhoto, MetaError, GRAPH_BASE} = await import('../server/advisor/social/meta.ts');

const T0 = Date.parse('2026-01-01T00:00:00Z');
const AT = new Date(T0).toISOString();
const NEXT = T0 + 15 * 60_000;
const PAGE = 'fixture-page';
const IMAGE = 'https://example.invalid/image.jpg';

function setup(t, edge, ambiguous) {
  const {sql, db} = advisorDatabase();
  t.after(() => sql.close());
  const media = edge === 'photos' ? ['image-a'] : ['image-a', 'image-b'];
  const insert = sql.prepare(`INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,has_person,publish_state,derived_at,created_at)
    VALUES(?, 'fixture-only', 'image', 'image/jpeg', 1, 'fixture-key', 'fixture-hash', 0, 'approved', ?, ?)`);
  for (const id of media) insert.run(id, AT, AT);
  sql.prepare(`INSERT INTO advisor_posts(id,kind,region,media_json,caption,targets_json,status,scheduled_for,created_by,created_at,updated_at)
    VALUES('post', ?, 'fixture-region', ?, '', '["facebook"]', 'approved', ?, 'engine', ?, ?)`)
    .run(edge === 'photos' ? 'photo' : 'carousel', JSON.stringify(media), AT, AT, AT);

  const unexpected = [];
  t.mock.method(globalThis, 'fetch', async () => {
    unexpected.push('uninjected fetch');
    throw new Error('real transport forbidden in F02-11');
  });
  const accepted = [];
  const staged = [];
  const env = {DB: db, TEXT_ADVISOR_ENABLED: 'true', ADVISOR_SOCIAL_ENABLED: 'true', ADVISOR_REPLIES_ENABLED: 'false',
    ADVISOR_PUBLIC_BASE: 'https://example.invalid', META_PAGE_ID: PAGE, META_IG_USER_ID: 'unused',
    META_PAGE_TOKEN: 'fixture-token', META_APP_SECRET: 'fixture-secret'};
  const fetcher = async (url, init) => {
    if (edge === 'feed' && init.method === 'POST' && url === `${GRAPH_BASE}/${PAGE}/photos`
      && new URLSearchParams(init.body).get('published') === 'false') {
      const id = `staged-${staged.length + 1}`;
      staged.push(id);
      return Response.json({id});
    }
    if (init.method !== 'POST' || url !== `${GRAPH_BASE}/${PAGE}/${edge}`) {
      unexpected.push('unexpected mock request');
      throw new Error('unexpected mock request');
    }
    // The fake accepts *every* create. Only the first acknowledgement is lost.
    const id = `created-${accepted.length + 1}`;
    accepted.push(id);
    if (ambiguous && accepted.length === 1) return Response.json({error: {}}, {status: 503});
    return Response.json({id});
  };
  const deps = {fetcher, sleep: async () => {}, dispatch: async () => {
    unexpected.push('media dispatch');
    throw new Error('media dispatch forbidden in F02-11');
  }};
  const post = () => sql.prepare("SELECT status,error,fb_post_id,posted_at FROM advisor_posts WHERE id='post'").get();
  return {sql, env, deps, post, accepted, staged, unexpected};
}

// A stand-in for the desired policy, NOT a product patch. Use the same Graph
// wrappers and store, but stop at the first ambiguous reply and persist a hold.
async function referenceTick(f, edge) {
  if (f.post().status !== 'approved') return;
  const cfg = {fetcher: f.deps.fetcher, token: 'fixture-token', appSecret: 'fixture-secret', attempts: 1};
  const uploads = [];
  if (edge === 'feed') {
    for (const name of ['a', 'b']) uploads.push((await fbPhoto(cfg, PAGE, {url: `${IMAGE}?${name}`, published: false})).id);
  }
  await assert.rejects(edge === 'photos' ? fbPhoto(cfg, PAGE, {url: IMAGE}) : fbFeed(cfg, PAGE, {photo_ids: uploads}),
    error => error instanceof MetaError && error.status === 503);
  f.sql.prepare("UPDATE advisor_posts SET status='uncertain',error='Page create outcome uncertain; reconcile before retrying' WHERE id='post'").run();
}

async function observe(t, edge, ambiguous, tick) {
  const f = setup(t, edge, ambiguous);
  const snapshot = () => ({creates: f.accepted.length, ...f.post()});
  await tick(f, T0);
  const first = snapshot();
  await tick(f, NEXT);
  assert.deepEqual(f.unexpected, [], 'only the injected fake provider may be called');
  assert.ok(first.creates > 0, 'the due post reached the fake create edge on the first tick');
  assert.ok(edge !== 'feed' || f.staged.length >= 2, 'feed had unpublished inputs');
  return {first, next: snapshot()};
}

const realTick = async (f, now) => {
  const result = await publishDue(f.env, now, {...f.deps, now: () => now});
  assert.equal(result.status, 'ran');
  assert.ok(!result.outcomes.includes('error'), 'publisher did not hit an internal error');
};

function gaps({first, next}) {
  const issues = [];
  if (first.creates !== 1) issues.push('first tick replayed the ambiguous create');
  if (next.creates !== first.creates) issues.push('next tick repeated the create');
  for (const [tick, row] of [['first', first], ['next', next]]) {
    if (!/\b(?:uncertain|reconcil\w*)\b/i.test(`${row.status} ${row.error ?? ''}`)
      || row.fb_post_id !== null || row.posted_at !== null || row.status === 'posted') {
      issues.push(`${tick} tick lacks an inspectable unconfirmed outcome`);
    }
  }
  return issues;
}

for (const edge of ['photos', 'feed']) {
  test(`F02-11 ${edge}: valid ambiguity control and independent defect signals`, async t => {
    const {first, next} = await observe(t, edge, true, f => referenceTick(f, edge));
    assert.deepEqual(gaps({first, next}), []);
    assert.deepEqual(gaps({first: {...first, creates: 2}, next: {...next, creates: 2}}), ['first tick replayed the ambiguous create']);
    assert.deepEqual(gaps({first, next: {...next, creates: 2}}), ['next tick repeated the create']);
    assert.deepEqual(gaps({first: {...first, status: 'failed', error: 'HTTP 503'}, next}), ['first tick lacks an inspectable unconfirmed outcome']);
    assert.deepEqual(gaps({first, next: {...next, status: 'failed', error: 'HTTP 503'}}), ['next tick lacks an inspectable unconfirmed outcome']);
  });

  test(`F02-11 ${edge}: a normal acknowledgement persists the id and isn't replayed`, async t => {
    const {first, next} = await observe(t, edge, false, realTick);
    assert.deepEqual(first, {creates: 1, status: 'posted', error: null, fb_post_id: 'created-1', posted_at: AT});
    assert.deepEqual(next, first);
  });

  if (process.argv.includes('--baseline')) {
    test(`F02-11 ${edge}: read-only baseline receipt (mock provider, in-memory D1)`, async t => {
      const observation = await observe(t, edge, true, realTick);
      t.diagnostic(JSON.stringify({edge, ...observation, gaps: gaps(observation)}));
    });
  }
}

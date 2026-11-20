// SCA-610 / F02-11. A Page create may commit before its HTTP 503 arrives.
// Contract: one create attempt, explicit durable uncertainty (not confirmed
// posted), and no second create on the next tick. An ordinary acknowledged
// create still works. The Graph client's GET retries have their own coverage
// in test_advisor_meta.mjs; this fixture exercises the missing write lifecycle.
//   node --test tests/test_f02_11_audit.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase} from './_advisor_d1.mjs';

// Synthetic build bindings; no deployment configuration is loaded.
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {publish, publishDue} = await import('../server/advisor/social/publish.ts');
const {GRAPH_BASE} = await import('../server/advisor/social/meta.ts');

const T0 = Date.parse('2026-01-01T00:00:00Z');
const AT = new Date(T0).toISOString();
const NEXT = T0 + 15 * 60_000;
const PAGE = 'fixture-page';

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
    if (ambiguous === true && accepted.length === 1) return Response.json({error: {}}, {status: 503});
    if (ambiguous === 'invalid-id') return Response.json({id: true});
    return Response.json({id});
  };
  const deps = {fetcher, sleep: async () => {}, dispatch: async () => {
    unexpected.push('media dispatch');
    throw new Error('media dispatch forbidden in F02-11');
  }};
  const post = () => sql.prepare("SELECT status,error,fb_post_id,posted_at FROM advisor_posts WHERE id='post'").get();
  return {env, deps, post, accepted, staged, unexpected};
}

async function observe(t, edge, ambiguous) {
  const f = setup(t, edge, ambiguous);
  const snapshot = () => ({creates: f.accepted.length, ...f.post()});
  await realTick(f, T0);
  const first = snapshot();
  await realTick(f, NEXT);
  assert.deepEqual(f.unexpected, [], 'only the injected fake provider may be called');
  assert.ok(first.creates > 0, 'the due post reached the fake create edge on the first tick');
  assert.equal(f.staged.length, edge === 'feed' ? 2 : 0, 'only the expected unpublished inputs were created');
  return {f, first, next: snapshot()};
}

const realTick = async (f, now) => {
  const result = await publishDue(f.env, now, {...f.deps, now: () => now});
  assert.equal(result.status, 'ran');
  assert.ok(!result.outcomes.includes('error'), 'publisher did not hit an internal error');
};

for (const edge of ['photos', 'feed']) {
  test(`F02-11 ${edge}: an accepted create with a lost acknowledgement is held for reconciliation`, async t => {
    const {f, first, next} = await observe(t, edge, true);
    assert.equal(first.creates, 1, 'first tick did not replay the ambiguous create');
    assert.equal(first.fb_post_id, null);
    assert.equal(first.posted_at, null);
    assert.notEqual(first.status, 'posted');
    assert.match(first.error, /uncertain; reconcile before retrying.*HTTP 503/);
    assert.deepEqual(next, first, 'next tick neither replayed the create nor erased the uncertainty');

    // The ordinary failed-post retry must not clear a reconciliation hold.
    const retry = await publish(f.env, 'post', {...f.deps, now: () => NEXT}, {retry: true});
    assert.match(retry.error, /uncertain; reconcile before retrying/);
    assert.deepEqual({creates: f.accepted.length, ...f.post()}, first);
    assert.equal(f.staged.length, edge === 'feed' ? 2 : 0);
    assert.deepEqual(f.unexpected, []);
  });

  test(`F02-11 ${edge}: a non-string acknowledgement id is held for reconciliation`, async t => {
    const {f, first, next} = await observe(t, edge, 'invalid-id');
    assert.equal(first.creates, 1);
    assert.equal(first.fb_post_id, null);
    assert.equal(first.posted_at, null);
    assert.notEqual(first.status, 'posted');
    assert.match(first.error, /uncertain; reconcile before retrying.*HTTP 200/);
    assert.deepEqual(next, first);
    const retry = await publish(f.env, 'post', {...f.deps, now: () => NEXT}, {retry: true});
    assert.match(retry.error, /uncertain; reconcile before retrying/);
    assert.deepEqual({creates: f.accepted.length, ...f.post()}, first);
  });

  test(`F02-11 ${edge}: a normal acknowledgement persists the id and isn't replayed`, async t => {
    const {first, next} = await observe(t, edge, false);
    assert.deepEqual(first, {creates: 1, status: 'posted', error: null, fb_post_id: 'created-1', posted_at: AT});
    assert.deepEqual(next, first);
  });
}

// SCA-443: the first 500 noneligible rows must not starve the next draft.
// All rows share a timestamp so a timestamp-only cursor would also fail.
import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase} from './_advisor_d1.mjs';
import {backfill} from '../scripts/advisor/backfill-drafts.mjs';

// Synthetic build globals, not deployment files.
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};

const now = Date.parse('2026-10-08T18:00:00Z');
const tail = 'media-0501';
const noTransport = () => assert.fail('offline draft backfill must not use a transport');

for (const apply of [false, true]) {
  test(`SCA-443: ${apply ? 'apply' : 'dry-run'} reaches the 501st row exactly once`, async t => {
    const {db, sql} = advisorDatabase();
    t.after(() => sql.close());
    t.mock.method(globalThis, 'fetch', noTransport);
    // The required media association is synthetic; no contacts or accounts are seeded.
    const insert = sql.prepare(`INSERT INTO advisor_media
      (id, contact_id, kind, mime, bytes, r2_key, sha256, publish_state, created_at)
      VALUES (?, 'fixture-no-contact', 'image', 'image/jpeg', 1, 'fixture', 'fixture', ?, ?)`);
    const at = new Date(now).toISOString();
    for (let i = 1; i <= 500; i++) insert.run(`media-${String(i).padStart(4, '0')}`, 'queued', at);
    insert.run(tail, 'approved', at);

    const logs = [];
    const run = () => backfill({DB: db}, {
      apply, now, log: line => logs.push(line), fetcher: noTransport,
    });
    const result = await run();
    const posts = () => sql.prepare('SELECT id, status, media_json FROM advisor_posts').all();
    const reviews = () => sql.prepare('SELECT kind, ref_id, status FROM advisor_reviews').all();
    assert.deepEqual(sql.prepare("SELECT publish_state, count(*) AS n FROM advisor_media GROUP BY publish_state ORDER BY publish_state").all()
      .map(r => [r.publish_state, r.n]), [['approved', 1], ['queued', 500]], 'no media is published or promoted');
    assert.equal(result.eligible, 1, 'eligible media after 500 queued rows must be reached');
    assert.equal(result.candidates, 501, 'the keyset boundary does not repeat or omit a row');
    assert.equal(result.created, Number(apply));
    if (!apply) {
      assert.deepEqual(logs, [`would draft a post for media ${tail} (angler)`]);
      assert.deepEqual(posts(), [], 'dry-run does not create a post');
      assert.deepEqual(reviews(), [], 'dry-run does not create a review');
    } else {
      const firstPosts = posts(), firstReviews = reviews();
      assert.deepEqual(firstPosts.map(p => [p.status, JSON.parse(p.media_json)]), [['draft', [tail]]]);
      assert.deepEqual(firstReviews.map(r => [r.kind, r.ref_id, r.status]), [['post', firstPosts[0].id, 'open']]);
      const retry = await run();
      assert.equal(retry.created, 0, 'apply retry cannot create a second draft');
      assert.equal(retry.eligible, 0, 'the existing draft is no longer eligible');
      assert.deepEqual(posts(), firstPosts);
      assert.deepEqual(reviews(), firstReviews);
    }
  });
}

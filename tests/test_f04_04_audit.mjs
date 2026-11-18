import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase} from './_advisor_d1.mjs';
import {memoryBucket} from './_advisor_r2.mjs';
// Worker build constants are not needed by these routes.
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {};
const {advisorPublic} = await import('../server/routes/advisor.ts');
const {decideReview} = await import('../server/advisor/admin/decisions.ts');

// A caching client repeating one GET (including its Range, if any) immediately.
// No time advances: a positive max-age permits reuse unless caching or reuse
// without revalidation is forbidden. Model 206 reuse for the identical range.
function repeatGet(env, path, range) {
  let fresh;
  return async () => {
    if (fresh) return fresh.clone();
    const response = await advisorPublic.request(`https://example.test${path}`, {
      headers: range ? {Range: range} : {},
    }, env);
    const directives = (response.headers.get('Cache-Control') ?? '').toLowerCase().split(',').map(s => s.trim());
    if (response.ok && directives.some(s => /^max-age=[1-9]\d*$/.test(s)) &&
        !directives.some(s => s === 'no-store' || s === 'no-cache')) fresh = response.clone();
    return response;
  };
}

const AT = '2026-01-01T00:00:00.000Z';
const REVIEW = 'a'.repeat(32);
const GRAPHIC = 'advisor/posts/card/roundup.jpg';

for (const [name, path, type, body, range, contentRange] of [
  ['stripped image', '/media/photo.jpg', 'image/jpeg', 'photo bytes'],
  ['full stripped video', '/media/clip.mp4', 'video/mp4', '0123456789'],
  ['stripped video range', '/media/clip.mp4', 'video/mp4', '234', 'bytes=2-4', 'bytes 2-4/10'],
  ['generated graphic', '/media/post/card/roundup.jpg', 'image/jpeg', 'card bytes'],
]) {
  test(`${name}: an identical GET must not reuse approved bytes after rejection`, async t => {
    const {sql, db} = advisorDatabase();
    t.after(() => sql.close());
    const bucket = memoryBucket({
      'fixture/original.jpg': 'photo bytes',
      'fixture/original.mov': 'not the stripped video',
      'advisor/derived/clip/video.mp4': '0123456789',
      [GRAPHIC]: 'card bytes',
    });
    const env = {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_MEDIA: bucket};
    // Only media, review and graphic fixtures; no account or contact rows.
    const video = type === 'video/mp4';
    const media = video ? 'clip' : 'photo';
    sql.prepare(`INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,exif_stripped,publish_state,created_at,derived_at)
      VALUES(?,'fixture',?,?,?,?, 'synthetic','1','approved',?,?)`)
      .run(media, video ? 'video' : 'image', video ? 'video/quicktime' : type, 10,
        video ? 'fixture/original.mov' : 'fixture/original.jpg', AT, video ? AT : null);
    sql.prepare("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,'media',?,'has_person','open',?)")
      .run(REVIEW, media, AT);
    if (path.startsWith('/media/post/')) {
      sql.prepare(`INSERT INTO advisor_posts(id,kind,region,media_json,caption,targets_json,status,created_by,created_at,updated_at)
        VALUES('card','roundup','fixture','["photo"]','Synthetic card','[]','approved','engine',?,?)`).run(AT, AT);
      sql.prepare("INSERT INTO job_state(key,value,updated_at) VALUES('advisor.graphic.card',?,?)")
        .run(JSON.stringify({status: 'done', keys: {public: GRAPHIC}}), AT);
    }

    const get = repeatGet(env, path, range);
    const approved = await get();
    assert.equal(approved.status, range ? 206 : 200);
    assert.equal(approved.headers.get('Content-Type'), type);
    assert.equal(approved.headers.get('Content-Length'), String(body.length));
    if (video) assert.equal(approved.headers.get('Accept-Ranges'), 'bytes');
    if (range) assert.equal(approved.headers.get('Content-Range'), contentRange);
    assert.equal(await approved.text(), body);

    const decision = await decideReview(env, {reviewId: REVIEW, decision: 'reject', by: null, inId: REVIEW, key: 'fixture'}, {
      now: Date.parse(AT), sendsEnabled: false, send: () => assert.fail('fixture must not send'),
    });
    assert.equal(decision.status, 'applied');
    const reads = bucket.calls.get.length;
    const rejected = await get();
    assert.equal(rejected.status, 404, 'the caching client must reach the current approval gate');
    assert.deepEqual(await rejected.json(), {error: 'Not found'});
    assert.equal(bucket.calls.get.length, reads, 'withdrawn bytes must not be read from storage');
  });
}

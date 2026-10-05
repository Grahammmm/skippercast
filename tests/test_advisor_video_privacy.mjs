// Video privacy (00 principle 7: a video never leaks a position;
// docs/plans/text-advisor/09-social.md § As built (video privacy)): every stored
// video is listed for the media job, which strips its container metadata to
// advisor/derived/<id>/video.mp4; /media/<id>.mp4 serves only that copy, never
// the original; a media review or a post with a video cannot be approved until
// the copy exists, and the publisher waits for it. Offline: real migrations in
// node:sqlite and an in-memory R2.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {memoryBucket} from './_advisor_r2.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const {mediaJobWork, mediaJobPending, mediaJobDone, videoHold, derivedVideoKey} = await import('../server/advisor/media.ts');
const {decideReview} = await import('../server/advisor/admin/decisions.ts');
const {listReviews} = await import('../server/advisor/admin/queue.ts');
const {postDetail} = await import('../server/advisor/admin/posts.ts');
const {reviewId} = await import('../server/advisor/contacts.ts');
const P = await import('../server/advisor/social/publish.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-04T18:00:00Z');
const HOUR = 3600000;
const iso = ms => new Date(ms).toISOString();
const ORIGIN = 'https://skippercast.com';
const ADMIN = 'admin-user-1';
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

function setup() {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(ADMIN, iso(T0));
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,status,last_seen_at,created_at,updated_at) VALUES('c1','h-c1','ENC-c1','imessage','skipper','en','b1','active',?,?,?)`)
    .run(iso(T0), iso(T0), iso(T0));
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,instagram,owner_contact_id,status,consent_photos_at,created_at,updated_at) VALUES('b1','sea-example','Sea Example','morro-bay','morro-bay','seaexample','c1','verified',?,?,?)`)
    .run(iso(T0 - 48 * HOUR), iso(T0), iso(T0));
  const bucket = memoryBucket();
  return {sql, db, bucket, env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_MEDIA: bucket}};
}
function addVideo(sql, id, {state = 'approved', derived = null, error = null, mime = 'video/quicktime', at = T0 - 2 * HOUR} = {}) {
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,has_person,publish_state,derived_at,derived_error,created_at) VALUES(?,'c1','b1','video',?,5000,?,?,0,0,?,?,?,?)`)
    .run(id, mime, `advisor/media/c1/${id}.${mime === 'video/mp4' ? 'mp4' : 'mov'}`, `sha-${id}`, state, derived, error, iso(at));
}
function addReview(sql, kind, ref, reason) {
  const id = `${kind === 'media' ? 'a' : 'b'}${ref.replace(/[^0-9a-f]/g, '').padEnd(31, '0')}`.slice(0, 32);
  sql.prepare("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,?,?,?,'open',?)").run(id, kind, ref, reason, iso(T0 - HOUR));
  return id;
}
const decide = (env, id, decision = 'approve') => decideReview(env, {reviewId: id, decision, by: ADMIN, inId: id, key: 'admin'}, {now: T0, send: async () => 0, dispatch: async () => 204});
const media = (sql, id) => ({...sql.prepare('SELECT * FROM advisor_media WHERE id=?').get(id)});

dbTest('every stored video without its stripped copy is pending, private ones too; rejected and done ones are not', async () => {
  const {sql, db} = setup();
  addVideo(sql, 'private', {state: 'private', at: T0 - 5 * HOUR});
  addVideo(sql, 'queued', {state: 'queued', at: T0 - 4 * HOUR});
  addVideo(sql, 'rejected', {state: 'rejected'});
  addVideo(sql, 'done', {derived: iso(T0)});
  addVideo(sql, 'failed', {derived: iso(T0), error: 'no-ffmpeg'});
  const work = await mediaJobWork(db);
  assert.deepEqual(work.videos.map(v => v.id), ['private', 'queued']);
  assert.deepEqual(work.videos[0], {id: 'private', r2_key: 'advisor/media/c1/private.mov', mime: 'video/quicktime', sha256: 'sha-private', bytes: 5000,
    keys: {video: 'advisor/derived/private/video.mp4'}});
  assert.deepEqual(work.media, [], 'videos never go to the image list');
  assert.equal(await mediaJobPending(db), 2);
  assert.deepEqual((await mediaJobWork(db, {media: 25, graphics: 10, videos: 1})).videos.map(v => v.id), ['private'], 'paged, oldest first');
});

dbTest('media-done for a video: exactly its video.mp4 key (size optional) stamps derived_at; image keys, other keys or an error are handled', async () => {
  const {sql, env} = setup();
  addVideo(sql, 'v1', {state: 'private'}); addVideo(sql, 'v2', {state: 'private'}); addVideo(sql, 'v3', {state: 'private'});
  const run = payload => quiet(() => mediaJobDone(env, payload, T0)).then(r => r.value);
  assert.deepEqual(await run({media_id: 'v1', keys: {public: 'advisor/derived/v1/public.jpg', thumb: 'advisor/derived/v1/thumb.jpg'}, width: 10, height: 10}), {ok: false, error: 'invalid'});
  assert.deepEqual(await run({media_id: 'v1', keys: {video: 'advisor/media/c1/v1.mov'}}), {ok: false, error: 'invalid'}, 'never the original');
  assert.deepEqual(await run({media_id: 'v1', keys: {video: derivedVideoKey('v1'), extra: 'x'}}), {ok: false, error: 'invalid'});
  assert.deepEqual(await run({media_id: 'v1', keys: {video: derivedVideoKey('v1')}, width: -1, height: 10}), {ok: false, error: 'invalid'});
  assert.equal(media(sql, 'v1').derived_at, null);
  assert.deepEqual(await run({media_id: 'v1', keys: {video: derivedVideoKey('v1')}, width: 1080, height: 1920}), {ok: true, kind: 'media', status: 'done'});
  assert.deepEqual([media(sql, 'v1').derived_at, media(sql, 'v1').derived_error, media(sql, 'v1').width], [iso(T0), null, 1080]);
  assert.deepEqual(await run({media_id: 'v2', keys: {video: derivedVideoKey('v2')}}), {ok: true, kind: 'media', status: 'done'}, 'size optional');
  assert.deepEqual(await run({media_id: 'v3', error: 'no-ffmpeg'}), {ok: true, kind: 'media', status: 'failed'});
  assert.deepEqual([media(sql, 'v3').derived_at, media(sql, 'v3').derived_error], [iso(T0), 'no-ffmpeg']);
  assert.deepEqual(await run({media_id: 'missing', keys: {video: derivedVideoKey('missing')}}), {ok: false, error: 'not-found'});
});

test('videoHold: waiting, no ffmpeg, another failure, ready; images are never held by it', () => {
  assert.match(videoHold({kind: 'video', derived_at: null, derived_error: null}), /waiting for the media job to remove its location metadata/);
  assert.match(videoHold({kind: 'video', derived_at: iso(T0), derived_error: 'no-ffmpeg'}), /no ffmpeg/);
  assert.match(videoHold({kind: 'video', derived_at: iso(T0), derived_error: 'location-left: xyz-atom'}), /removing it failed \(location-left: xyz-atom\)/);
  assert.equal(videoHold({kind: 'video', derived_at: iso(T0), derived_error: null}), null);
  assert.equal(videoHold({kind: 'image', derived_at: null, derived_error: null}), null);
});

dbTest('a media review of a video cannot be approved (or edited) until its stripped copy exists; rejecting it always works; the card shows the hold', async () => {
  const {sql, db, env} = setup();
  addVideo(sql, 'v1', {state: 'private'}); addVideo(sql, 'v2', {state: 'private', derived: iso(T0), error: 'no-ffmpeg'}); addVideo(sql, 'v3', {state: 'private'});
  const r1 = addReview(sql, 'media', 'v1', 'has_person'), r2 = addReview(sql, 'media', 'v2', 'has_person'), r3 = addReview(sql, 'media', 'v3', 'has_person');
  const waiting = await decide(env, r1);
  assert.equal(waiting.status, 'conflict');
  assert.match(waiting.error, /waiting for the media job to remove its location metadata/);
  const edit = await decideReview(env, {reviewId: r1, decision: 'edit', patch: {credit: 'Sea Example'}, by: ADMIN, inId: r1, key: 'admin'}, {now: T0, send: async () => 0, dispatch: async () => 204});
  assert.equal(edit.status, 'conflict');
  assert.deepEqual([media(sql, 'v1').publish_state, media(sql, 'v1').credit], ['private', null], 'nothing applied');
  const card = (await listReviews(db, {status: 'open', kind: 'media'})).items.find(i => i.id === r1);
  assert.match(card.detail.media.hold, /location metadata/);
  const noFfmpeg = await decide(env, r2);
  assert.equal(noFfmpeg.status, 'conflict');
  assert.match(noFfmpeg.error, /no ffmpeg/);
  // Stripped: the approval goes through.
  sql.prepare("UPDATE advisor_media SET derived_at=? WHERE id='v1'").run(iso(T0));
  assert.equal((await quiet(() => decide(env, r1))).value.status, 'applied');
  assert.equal(media(sql, 'v1').publish_state, 'approved');
  assert.equal((await listReviews(db, {status: 'all', kind: 'media'})).items.find(i => i.id === r1).detail.media.hold, null);
  // Rejecting never waits.
  assert.equal((await quiet(() => decide(env, r3, 'reject'))).value.status, 'applied');
  assert.equal(media(sql, 'v3').publish_state, 'rejected');
});

dbTest('a post with a video cannot be approved until the video is stripped; the post card names why', async () => {
  const {sql, db, env} = setup();
  addVideo(sql, 'v1', {state: 'queued'});
  sql.prepare(`INSERT INTO advisor_posts(id,kind,region,boat_id,media_json,caption,targets_json,status,created_by,created_at,updated_at) VALUES('p1','reel','morro-bay','b1','["v1"]','Reel','["instagram","facebook"]','draft','engine',?,?)`)
    .run(iso(T0), iso(T0));
  const review = await reviewId('post', 'p1', 'social_draft');
  sql.prepare("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,'post','p1','social_draft','open',?)").run(review, iso(T0));
  const held = await decide(env, review);
  assert.equal(held.status, 'conflict');
  assert.match(held.error, /location metadata/);
  assert.equal(sql.prepare("SELECT status FROM advisor_posts WHERE id='p1'").get().status, 'draft');
  assert.match((await postDetail(db, 'p1')).post.hold, /location metadata/);
  sql.prepare("UPDATE advisor_media SET derived_at=?,derived_error='ffmpeg-failed' WHERE id='v1'").run(iso(T0));
  assert.match((await decide(env, review)).error, /removing it failed \(ffmpeg-failed\)/);
  sql.prepare("UPDATE advisor_media SET derived_error=NULL WHERE id='v1'").run();
  assert.equal((await quiet(() => decide(env, review))).value.status, 'applied');
  assert.equal(sql.prepare("SELECT status FROM advisor_posts WHERE id='p1'").get().status, 'approved');
});

dbTest('the publisher waits for an approved video\'s stripped copy (the job is dispatched) and fails the post when stripping failed', async () => {
  const {sql, env} = setup();
  addVideo(sql, 'v1'); addVideo(sql, 'v2', {derived: iso(T0), error: 'no-ffmpeg'});
  for (const [id, video] of [['p1', 'v1'], ['p2', 'v2']]) {
    sql.prepare(`INSERT INTO advisor_posts(id,kind,region,boat_id,media_json,caption,targets_json,status,created_by,approved_at,created_at,updated_at) VALUES(?,'reel','morro-bay','b1',?,'Reel','["instagram","facebook"]','approved','engine',?,?,?)`)
      .run(id, JSON.stringify([video]), iso(T0), iso(T0), iso(T0));
  }
  const meta = {ADVISOR_SOCIAL_ENABLED: 'true', META_APP_SECRET: 'app-secret-PLACEHOLDER', META_PAGE_TOKEN: 'EAAB-PLACEHOLDER-TOKEN', META_IG_USER_ID: '17841400000000000', META_PAGE_ID: '100000000000001', GITHUB_TOKEN: 't'};
  const calls = [], dispatched = [];
  const deps = {now: () => T0, fetcher: async url => { calls.push(url); return new Response('{}', {status: 500}); }, sleep: async () => {}, dispatch: async (_, file) => { dispatched.push(file); return 204; }};
  const waiting = await quiet(() => P.publish({...env, ...meta}, 'p1', deps));
  assert.deepEqual(waiting.value, {outcome: 'deferred'});
  assert.deepEqual(dispatched, ['advisor-media.yml']);
  assert.equal(sql.prepare("SELECT status FROM advisor_posts WHERE id='p1'").get().status, 'approved', 'still approved, tried again next tick');
  const failed = await quiet(() => P.publish({...env, ...meta}, 'p2', deps));
  assert.equal(failed.value.outcome, 'held');
  assert.match(failed.value.error, /no ffmpeg/);
  assert.equal(sql.prepare("SELECT status FROM advisor_posts WHERE id='p2'").get().status, 'failed');
  assert.deepEqual(calls, [], 'Meta is never called with an unstripped video');
});

const call = (path, env, init) => worker.fetch(new Request(ORIGIN + path, init), {ASSETS: {fetch: async () => new Response('other', {status: 299})}, ...env});

dbTest('GET /media/<id>.mp4 never serves an original: only the stripped copy of an approved video, as video/mp4', async () => {
  const {sql, bucket, env} = setup();
  const original = new TextEncoder().encode('ORIGINAL WITH ©xyz +35.3658-120.8499/'), stripped = new TextEncoder().encode('STRIPPED COPY');
  addVideo(sql, 'v1');                                                         // approved, not stripped yet
  addVideo(sql, 'v2', {derived: iso(T0), error: 'no-ffmpeg'});                 // given up
  addVideo(sql, 'v3', {derived: iso(T0)});                                     // approved and stripped (a MOV original)
  addVideo(sql, 'v4', {derived: iso(T0), state: 'private'});                   // stripped but private
  for (const id of ['v1', 'v2', 'v3', 'v4']) bucket.objects.set(`advisor/media/c1/${id}.mov`, {bytes: original, httpMetadata: {}});
  for (const id of ['v2', 'v3', 'v4']) bucket.objects.set(derivedVideoKey(id), {bytes: stripped, httpMetadata: {}});
  for (const id of ['v1', 'v2', 'v4']) {
    const r = await call(`/media/${id}.mp4`, env);
    assert.equal(r.status, 404, id);
    assert.ok(!(await r.text()).includes('ORIGINAL'), id);
  }
  const ok = await call('/media/v3.mp4', env);
  assert.deepEqual([ok.status, ok.headers.get('Content-Type'), ok.headers.get('Content-Length')], [200, 'video/mp4', String(stripped.length)]);
  assert.equal(await ok.text(), 'STRIPPED COPY');
  const part = await call('/media/v3.mp4', env, {headers: {Range: 'bytes=0-7'}});
  assert.deepEqual([part.status, await part.text()], [206, 'STRIPPED']);
  // The derived row exists but the object is gone: still never the original.
  bucket.objects.delete(derivedVideoKey('v3'));
  assert.equal((await call('/media/v3.mp4', env)).status, 404);
});

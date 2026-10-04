// Publishing approved posts (TA-S2; docs/plans/text-advisor/09-social.md §
// Publishing, § Media that Meta fetches): a photo, a carousel, a Reel whose
// container is IN_PROGRESS across two cron ticks, a Story, the quota used up, a
// partial failure and the retry of the failed surface only, an idempotent rerun
// that never makes a second container, the skipper's "Posted:" text (once), the
// switch off, the media job's derived files, the admin's post now / schedule /
// retry, the cron hook and GET /media/<id>.story.jpg and <id>.mp4 with ranges.
// TA-S3: collaborators and user tags on the containers, collab_status invited
// on publish and the hourly read of the invites (GET /<media>/collaborators).
// Offline: real migrations in node:sqlite, recorded Graph API responses from
// tests/fixtures/advisor/meta/ (placeholder ids and tokens only).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {memoryBucket} from './_advisor_r2.mjs';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {Hono} = await import('hono');
const {context} = await import('../server/middleware/context.ts');
const {requireUser} = await import('../server/middleware/auth.ts');
const {onError} = await import('../server/middleware/error.ts');
const {adminRoutes} = await import('../server/routes/admin.ts');
const {default: worker} = await import('../server/index.ts');
const P = await import('../server/advisor/social/publish.ts');
const meta = await import('../server/advisor/social/meta.ts');
const {advisorCron} = await import('../server/advisor/cron.ts');
const {byteRange} = await import('../server/routes/advisor.ts');
const {outboundId} = await import('../server/advisor/ids.ts');
const {publishedTo} = await import('../web/admin/posts-form.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/advisor/meta/${name}.json`, import.meta.url)));
const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {status, headers: {'content-type': 'application/json'}});
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const ORIGIN = 'https://skippercast.com';
const ADMIN = 'admin-user-1';
const IG = '17841400000000000', PAGE = '100000000000001';
const T0 = Date.parse('2026-10-04T18:00:00Z');
const HOUR = 3600000;
const iso = ms => new Date(ms).toISOString();
const PERMALINK = 'https://www.instagram.com/p/PLACEHOLDER0001/';
const CAPTION = 'Big lings came up off the reef.\nAboard Rita G (@ritag) out of Morro Bay.\n\n#skippercast';

/**
 * A recorded Graph API: answers each call by its method and path from the
 * fixtures (container ids count up), records method, host, path, params and
 * headers. `status` is the sequence of container status fixtures (the last
 * repeats; default FINISHED); `on['POST /<page>/photos']` overrides one edge.
 */
function graphFake({status = ['container-finished'], limit = 'publishing-limit', on = {}} = {}) {
  const calls = [], queue = [...status];
  let containers = 0, photos = 0;
  const fetcher = async (url, init = {}) => {
    const u = new URL(url), method = init.method ?? 'GET';
    const params = Object.fromEntries((method === 'POST' && typeof init.body === 'string' ? new URLSearchParams(init.body) : u.searchParams).entries());
    const path = u.host === 'rupload.facebook.com' ? `/rupload/${u.pathname.split('/').at(-1)}` : u.pathname.replace(/^\/v\d+\.0/, '');
    const call = {method, host: u.host, path, params, headers: {...(init.headers ?? {})}};
    calls.push(call);
    const key = `${method} ${path}`;
    if (on[key]) { const answer = on[key](call); if (answer) return answer; }
    if (path.startsWith('/rupload/')) return jsonResponse(fixture('reel-upload'));
    if (key === `GET /${IG}/content_publishing_limit`) return jsonResponse(fixture(limit));
    if (key === `POST /${IG}/media`) return jsonResponse({id: `17890000000000${101 + containers++}`});
    if (key === `POST /${IG}/media_publish`) return jsonResponse(fixture('media-published'));
    if (method === 'GET' && params.fields === 'status_code,status') return jsonResponse({...fixture(queue.length > 1 ? queue.shift() : queue[0]), id: path.slice(1)});
    if (method === 'GET' && params.fields === 'permalink') return jsonResponse(fixture('permalink'));
    if (method === 'GET' && path.endsWith('/collaborators')) return jsonResponse(fixture('collaborators'));
    if (key === `POST /${PAGE}/photos`) {
      photos++;
      return jsonResponse(params.published === 'false' ? {id: `1000000000003${10 + photos}`} : fixture('page-photo'));
    }
    if (key === `POST /${PAGE}/feed`) return jsonResponse(fixture('page-feed'));
    if (key === `POST /${PAGE}/photo_stories`) return jsonResponse(fixture('photo-story'));
    if (key === `POST /${PAGE}/video_reels`) return jsonResponse(fixture(params.upload_phase === 'start' ? 'reel-start' : 'reel-finish'));
    return jsonResponse({error: {code: 100, message: 'unexpected call in test'}}, 400);
  };
  const count = (method, path) => calls.filter(c => c.method === method && c.path === path).length;
  return {fetcher, calls, count};
}

function recorder() { const sent = []; return {sent, name: 'bluebubbles', async send(m) { sent.push(structuredClone(m)); return {providerId: `p${sent.length}`, status: 'sent'}; }}; }
function analytics() { const points = []; return {points, writeDataPoint(p) { points.push(p); }}; }

function setup({env = {}, boat = {}} = {}) {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(ADMIN, iso(T0));
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,status,last_seen_at,created_at,updated_at) VALUES('c1','h-c1','ENC-c1','imessage','skipper',?,'b1',?,?,?,?)`)
    .run(boat.language ?? 'en', boat.contactStatus ?? 'active', iso(T0), iso(T0), iso(T0));
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,instagram,owner_contact_id,status,consent_photos_at,consent_revoked_at,created_at,updated_at) VALUES('b1','rita-g','Rita G','morro-bay','morro-bay',?,'c1',?,?,?,?,?)`)
    .run(boat.instagram === undefined ? 'ritag' : boat.instagram, boat.status ?? 'verified', iso(T0 - 2 * 86400000), boat.revoked ?? null, iso(T0), iso(T0));
  const points = analytics(), channel = recorder(), bucket = memoryBucket();
  return {sql, db, points, channel, bucket, env: {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_SOCIAL_ENABLED: 'true', DB: db, ADVISOR_MEDIA: bucket, ANALYTICS: points,
    META_APP_SECRET: 'app-secret-PLACEHOLDER', META_PAGE_TOKEN: 'EAAB-PLACEHOLDER-TOKEN', META_IG_USER_ID: IG, META_PAGE_ID: PAGE, ...env}};
}
function addMedia(sql, id, {kind = 'image', derived = true, state = 'approved', derivedError = null} = {}) {
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,has_person,publish_state,derived_at,derived_error,created_at) VALUES(?,'c1','b1',?,?,1000,?,'sha',1,0,?,?,?,?)`)
    .run(id, kind, kind === 'video' ? 'video/mp4' : 'image/jpeg', `advisor/media/c1/${id}.${kind === 'video' ? 'mp4' : 'jpg'}`, state, derived ? iso(T0 - HOUR) : null, derivedError, iso(T0 - 2 * HOUR));
}
function addPost(sql, {id = 'p1', kind = 'photo', media = ['m1'], status = 'approved', caption = CAPTION, targets, scheduled = null, collaborators = null, userTags = null, extra = {}} = {}) {
  const t = targets ?? (kind === 'story' ? ['instagram_story', 'facebook_story'] : ['instagram', 'facebook']);
  sql.prepare(`INSERT INTO advisor_posts(id,kind,region,boat_id,media_json,caption,collaborators_json,user_tags_json,targets_json,status,scheduled_for,created_by,approved_by,approved_at,created_at,updated_at,ig_container_id)
    VALUES(?,?,'morro-bay','b1',?,?,?,?,?,?,?,'engine',?,?,?,?,?)`)
    .run(id, kind, JSON.stringify(media), kind === 'story' ? '' : caption, collaborators ? JSON.stringify(collaborators) : null, userTags ? JSON.stringify(userTags) : null,
      JSON.stringify(t), status, scheduled, ADMIN, iso(T0 - HOUR), iso(T0 - 2 * HOUR), iso(T0 - HOUR), extra.ig_container_id ?? null);
  return id;
}
const postRow = (sql, id = 'p1') => sql.prepare('SELECT * FROM advisor_posts WHERE id=?').get(id);
const outbound = sql => sql.prepare("SELECT id,contact_id,body,in_reply_to,status FROM advisor_messages WHERE direction='out'").all().map(r => ({...r}));
const publishPoints = points => points.points.filter(p => p.indexes[0] === 'publish').map(p => p.blobs.slice(1, 3));

/** Deps with a fake clock that sleeps advance, the recorded Graph API and the skipper's channel. */
function deps(s, fake, extra = {}) {
  const clock = {t: T0, sleeps: []};
  return {clock, deps: {now: () => clock.t, sleep: async ms => { clock.sleeps.push(ms); clock.t += ms; }, fetcher: fake.fetcher, consumer: {channelFor: () => s.channel},
    dispatch: async () => 204, ...extra}};
}

// ---- photo ------------------------------------------------------------------------------------

dbTest('a photo: one image container with the caption, media_publish, the Page photo; posted, its media posted, the skipper texted once with the permalink', async () => {
  const s = setup(), fake = graphFake();
  addMedia(s.sql, 'm1'); addPost(s.sql);
  const {deps: d} = deps(s, fake);
  const {value} = await quiet(() => P.publish(s.env, 'p1', d));
  assert.deepEqual(value, {outcome: 'posted'});
  const container = fake.calls.find(c => c.method === 'POST' && c.path === `/${IG}/media`);
  assert.deepEqual({image_url: container.params.image_url, caption: container.params.caption, media_type: container.params.media_type},
    {image_url: 'https://skippercast.com/media/m1.jpg', caption: CAPTION, media_type: undefined});
  assert.equal(fake.calls.find(c => c.path === `/${IG}/media_publish`).params.creation_id, '17890000000000101');
  const photo = fake.calls.find(c => c.path === `/${PAGE}/photos`);
  assert.deepEqual([photo.params.url, photo.params.message, photo.params.published], ['https://skippercast.com/media/m1.jpg', CAPTION, 'true']);
  // The order 09 gives: quota, container, status, publish, permalink, then the Page.
  assert.deepEqual(fake.calls.map(c => `${c.method} ${c.path.replace(/\/\d+$/, '/<id>')}${c.params.fields ? `?${c.params.fields}` : ''}`), [
    `GET /${IG}/content_publishing_limit?quota_usage,config`, `POST /${IG}/media`, 'GET /<id>?status_code,status', `POST /${IG}/media_publish`, 'GET /<id>?permalink', `POST /${PAGE}/photos`]);
  const row = postRow(s.sql);
  assert.deepEqual([row.status, row.posted_at, row.ig_container_id, row.ig_media_id, row.fb_post_id, row.error], ['posted', iso(T0), '17890000000000101', '17890000000000202', '100000000000001_100000000000302', null]);
  assert.equal(s.sql.prepare("SELECT publish_state FROM advisor_media WHERE id='m1'").get().publish_state, 'posted');
  assert.equal(s.sql.prepare("SELECT COUNT(*) n FROM job_state WHERE key LIKE 'advisor.publish.%'").get().n, 0, 'no progress state or lease left behind');
  assert.deepEqual(outbound(s.sql).map(m => [m.contact_id, m.body, m.in_reply_to, m.status]), [['c1', `Posted: ${PERMALINK}. Tagged @ritag.`, 'p1', 'sent']]);
  assert.equal(outbound(s.sql)[0].id, await outboundId('p1', 'posted'), 'a deterministic outbound id: texted once per post');
  assert.deepEqual(publishPoints(s.points), [['photo', 'posted']]);
  // A second run changes nothing and calls nothing.
  const before = fake.calls.length;
  assert.deepEqual(await P.publish(s.env, 'p1', d), {outcome: 'skipped', error: 'the post is posted'});
  assert.equal(fake.calls.length, before);
  assert.equal(outbound(s.sql).length, 1);
});

dbTest('the skipper text: Spanish for a Spanish skipper, untagged without a handle, nothing for a stopped skipper or with replies off', async () => {
  for (const [boat, env, expected] of [
    [{language: 'es'}, {}, `Publicado: ${PERMALINK}. Etiquetamos a @ritag.`],
    [{instagram: null}, {}, `Posted: ${PERMALINK}`],
    [{contactStatus: 'stopped'}, {}, null],
    [{}, {ADVISOR_REPLIES_ENABLED: 'false'}, null],
  ]) {
    const s = setup({boat, env}), fake = graphFake();
    addMedia(s.sql, 'm1'); addPost(s.sql, {caption: boat.instagram === null ? 'Big lings.' : CAPTION});
    const {value} = await quiet(() => P.publish(s.env, 'p1', deps(s, fake).deps));
    assert.equal(value.outcome, 'posted');
    assert.deepEqual(outbound(s.sql).map(m => m.body), expected ? [expected] : [], JSON.stringify(boat));
  }
});

// ---- carousel ----------------------------------------------------------------------------------

dbTest('a carousel: one is_carousel_item container per photo, then CAROUSEL with the children and caption; the Page gets unpublished photos and one /feed post', async () => {
  const s = setup(), fake = graphFake();
  for (const id of ['m1', 'm2', 'm3']) addMedia(s.sql, id);
  addPost(s.sql, {kind: 'carousel', media: ['m1', 'm2', 'm3']});
  const {value} = await quiet(() => P.publish(s.env, 'p1', deps(s, fake).deps));
  assert.equal(value.outcome, 'posted');
  const containers = fake.calls.filter(c => c.method === 'POST' && c.path === `/${IG}/media`);
  assert.deepEqual(containers.slice(0, 3).map(c => [c.params.is_carousel_item, c.params.image_url, c.params.caption]),
    ['m1', 'm2', 'm3'].map(id => ['true', `https://skippercast.com/media/${id}.jpg`, undefined]));
  assert.deepEqual([containers[3].params.media_type, containers[3].params.children, containers[3].params.caption],
    ['CAROUSEL', '17890000000000101,17890000000000102,17890000000000103', CAPTION]);
  assert.equal(fake.calls.find(c => c.path === `/${IG}/media_publish`).params.creation_id, '17890000000000104');
  const photos = fake.calls.filter(c => c.path === `/${PAGE}/photos`);
  assert.deepEqual(photos.map(c => [c.params.url, c.params.published, c.params.message]), ['m1', 'm2', 'm3'].map(id => [`https://skippercast.com/media/${id}.jpg`, 'false', undefined]));
  const feed = fake.calls.find(c => c.path === `/${PAGE}/feed`);
  assert.equal(feed.params.message, CAPTION);
  assert.deepEqual([0, 1, 2].map(i => JSON.parse(feed.params[`attached_media[${i}]`])), [{media_fbid: '100000000000311'}, {media_fbid: '100000000000312'}, {media_fbid: '100000000000313'}]);
  assert.deepEqual([postRow(s.sql).status, postRow(s.sql).ig_container_id, postRow(s.sql).fb_post_id], ['posted', '17890000000000104', '100000000000001_100000000000601']);
});

// ---- reel across two ticks ------------------------------------------------------------------------

dbTest('a reel: REELS with the .mp4 URL, IN_PROGRESS through the first tick (stored, still publishing), FINISHED on the next tick; one container in all; the Page Reel by 3-phase upload', async () => {
  const s = setup(), fake = graphFake({status: ['container-in-progress', 'container-in-progress', 'container-in-progress', 'container-in-progress', 'container-in-progress', 'container-in-progress', 'container-finished']});
  addMedia(s.sql, 'v1', {kind: 'video'}); addPost(s.sql, {kind: 'reel', media: ['v1']});
  const {clock, deps: d} = deps(s, fake);
  const tick1 = await quiet(() => P.publishDue(s.env, clock.t, d));
  assert.deepEqual(tick1.value, {status: 'ran', outcomes: ['pending']});
  const reel = fake.calls.find(c => c.path === `/${IG}/media`);
  assert.deepEqual([reel.params.media_type, reel.params.video_url, reel.params.share_to_feed, reel.params.caption], ['REELS', 'https://skippercast.com/media/v1.mp4', 'true', CAPTION]);
  assert.equal(fake.calls.filter(c => c.params.fields === 'status_code,status').length, P.CRON_POLL_TRIES, 'the cron polls a bounded number of times');
  assert.deepEqual(clock.sleeps, Array(P.CRON_POLL_TRIES - 1).fill(P.POLL_EVERY_MS), 'once per 10 s');
  let row = postRow(s.sql);
  assert.deepEqual([row.status, row.ig_container_id, row.ig_media_id], ['publishing', '17890000000000101', null]);
  // The Page's Reel went out in the same tick: start, the upload with file_url (OAuth header, no proof), finish.
  const phases = fake.calls.filter(c => c.path === `/${PAGE}/video_reels` || c.path.startsWith('/rupload/'));
  assert.deepEqual(phases.map(c => c.params.upload_phase ?? c.headers.file_url), ['start', 'https://skippercast.com/media/v1.mp4', 'finish']);
  assert.equal(phases[2].params.description, CAPTION);
  assert.equal(row.fb_post_id, '100000000000402');
  assert.equal(outbound(s.sql).length, 0, 'no text before Instagram has it');
  // The next tick, 15 minutes later: no second container, the status is read again, published.
  clock.t = T0 + 15 * 60000;
  const tick2 = await quiet(() => P.publishDue(s.env, clock.t, d));
  assert.deepEqual(tick2.value, {status: 'ran', outcomes: ['posted']});
  assert.equal(fake.count('POST', `/${IG}/media`), 1, 'never a second container while one is stored');
  assert.equal(fake.count('POST', `/${PAGE}/video_reels`), 2, 'the Page Reel is not posted again');
  row = postRow(s.sql);
  assert.deepEqual([row.status, row.ig_media_id, row.fb_post_id], ['posted', '17890000000000202', '100000000000402']);
  assert.equal(outbound(s.sql).length, 1);
  assert.deepEqual(publishPoints(s.points), [['reel', 'pending'], ['reel', 'posted']]);
});

dbTest('a video still processing past the deadline, or a container in ERROR, fails Instagram and drops the container so a retry makes a new one', async () => {
  const s = setup(), fake = graphFake({status: ['container-error']});
  addMedia(s.sql, 'v1', {kind: 'video'}); addPost(s.sql, {kind: 'reel', media: ['v1']});
  const {value} = await quiet(() => P.publish(s.env, 'p1', deps(s, fake).deps));
  assert.equal(value.outcome, 'partial');
  let row = postRow(s.sql);
  assert.deepEqual([row.status, row.ig_container_id, row.error], ['partial', null, 'instagram: the Instagram container failed to process']);
  // Past the deadline while IN_PROGRESS.
  const s2 = setup(), slow = graphFake({status: ['container-in-progress']});
  addMedia(s2.sql, 'v1', {kind: 'video'}); addPost(s2.sql, {kind: 'reel', media: ['v1'], targets: ['instagram'], extra: {ig_container_id: '17890000000000999'}});
  s2.sql.prepare("UPDATE advisor_posts SET status='publishing' WHERE id='p1'").run();
  s2.sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run('advisor.publish.p1', JSON.stringify({ig_started_at: iso(T0 - 31 * 60000)}), iso(T0));
  const late = await quiet(() => P.publish(s2.env, 'p1', {...deps(s2, slow).deps, pollTries: 1}));
  assert.equal(late.value.outcome, 'failed');
  row = postRow(s2.sql);
  assert.deepEqual([row.status, row.ig_container_id, row.error], ['failed', null, 'instagram: the Instagram video was still processing after 30 minutes']);
  assert.equal(slow.count('POST', `/${IG}/media`), 0);
});

// ---- story -----------------------------------------------------------------------------------------

dbTest('a story: STORIES with the derived story.jpg and no caption; the Page photo Story from an unpublished photo; fb_story_id stored', async () => {
  const s = setup(), fake = graphFake();
  addMedia(s.sql, 'm1'); addPost(s.sql, {kind: 'story'});
  const {value} = await quiet(() => P.publish(s.env, 'p1', deps(s, fake).deps));
  assert.equal(value.outcome, 'posted');
  const container = fake.calls.find(c => c.path === `/${IG}/media`);
  assert.deepEqual([container.params.media_type, container.params.image_url, container.params.caption], ['STORIES', 'https://skippercast.com/media/m1.story.jpg', undefined]);
  const photo = fake.calls.find(c => c.path === `/${PAGE}/photos`);
  assert.deepEqual([photo.params.url, photo.params.published, photo.params.message], ['https://skippercast.com/media/m1.story.jpg', 'false', undefined]);
  assert.equal(fake.calls.find(c => c.path === `/${PAGE}/photo_stories`).params.photo_id, '100000000000311');
  const row = postRow(s.sql);
  assert.deepEqual([row.status, row.fb_story_id, row.fb_post_id], ['posted', '100000000000501', null]);
});

// ---- quota -------------------------------------------------------------------------------------------

dbTest('quota used up: no container, back to approved an hour later (from now for a past time, from the time when it is later), recorded', async () => {
  const s = setup(), fake = graphFake({limit: 'publishing-limit-exhausted'});
  addMedia(s.sql, 'm1'); addPost(s.sql, {scheduled: iso(T0 - 2 * HOUR)});
  const {value} = await quiet(() => P.publish(s.env, 'p1', deps(s, fake).deps));
  assert.deepEqual(value, {outcome: 'quota'});
  assert.equal(fake.count('POST', `/${IG}/media`), 0);
  assert.equal(fake.count('POST', `/${PAGE}/photos`), 0, 'the post waits whole: the Page goes with Instagram');
  assert.deepEqual([postRow(s.sql).status, postRow(s.sql).scheduled_for], ['approved', iso(T0 + HOUR)]);
  assert.deepEqual(publishPoints(s.points), [['photo', 'quota']]);
  // Due again only after the hour.
  const early = await quiet(() => P.publishDue(s.env, T0 + 30 * 60000, deps(s, fake).deps));
  assert.deepEqual(early.value.outcomes, []);
  const s2 = setup(), fake2 = graphFake({limit: 'publishing-limit-exhausted'});
  addMedia(s2.sql, 'm1'); addPost(s2.sql, {scheduled: iso(T0 + 2 * HOUR)});
  await quiet(() => P.publish(s2.env, 'p1', deps(s2, fake2).deps));
  assert.equal(postRow(s2.sql).scheduled_for, iso(T0 + 3 * HOUR), 'scheduled_for += 1 h');
});

// ---- partial and retry ------------------------------------------------------------------------------------------

/** The admin app on `env` with the recorded Graph API and the skipper's channel. */
function app(s, fake) {
  const a = new Hono({getPath: request => new URL(request.url).pathname});
  a.use('*', context);
  a.use('/api/*', requireUser);
  a.route('/', adminRoutes({now: () => T0, dispatchWorkflow: async () => 204, metaFetcher: fake.fetcher, metaSleep: async () => {}, channelFor: () => s.channel}));
  a.onError(onError);
  const w = withSessions({fetch: (request, e, ctx) => a.fetch(request, e, ctx)});
  return {
    get: path => w.fetch(new Request(ORIGIN + path, {headers: {'x-test-owner': ADMIN}}), s.env),
    post: (path, body) => w.fetch(new Request(ORIGIN + path, {method: 'POST', headers: {'Content-Type': 'application/json', Origin: ORIGIN, 'x-test-owner': ADMIN}, body: JSON.stringify(body ?? {})}), s.env),
  };
}

dbTest('one surface failing leaves the post partial with the error; the cron does not retry it; the admin retry runs the failed surface only', async () => {
  let failPage = true;
  const s = setup(), fake = graphFake({on: {[`POST /${PAGE}/photos`]: () => (failPage ? jsonResponse(fixture('error-page-photo'), 400) : null)}});
  addMedia(s.sql, 'm1'); addPost(s.sql);
  const first = await quiet(() => P.publish(s.env, 'p1', deps(s, fake).deps));
  assert.deepEqual(first.value, {outcome: 'partial', error: 'facebook: meta photos failed: HTTP 400 code 100 subcode 2069019'});
  let row = postRow(s.sql);
  assert.deepEqual([row.status, row.ig_media_id, row.fb_post_id, row.posted_at], ['partial', '17890000000000202', null, null]);
  assert.ok(!first.lines.join('\n').includes('EAAB-PLACEHOLDER-TOKEN'), 'no token in a log line');
  assert.equal(outbound(s.sql).length, 1, 'Instagram went out, so the skipper has the link');
  // The cron leaves a partial post alone.
  const tick = await quiet(() => P.publishDue(s.env, T0 + 15 * 60000, deps(s, fake).deps));
  assert.deepEqual(tick.value.outcomes, []);
  // The retry: Meta works again; only the Page is called.
  failPage = false;
  const before = fake.calls.length;
  const {get, post} = app(s, fake);
  const response = await quiet(() => post('/api/admin/posts/p1/retry'));
  assert.equal(response.value.status, 200);
  const body = await response.value.json();
  assert.deepEqual([body.outcome, body.post.status, body.post.fb_post_id, body.post.ig_media_id], ['posted', 'posted', '100000000000001_100000000000302', '17890000000000202']);
  assert.deepEqual(fake.calls.slice(before).map(c => `${c.method} ${c.path}`), [`POST /${PAGE}/photos`], 'only the failed surface');
  assert.equal(outbound(s.sql).length, 1, 'the skipper is texted once');
  // A posted post cannot be retried; an unknown one is 404.
  assert.equal((await post('/api/admin/posts/p1/retry')).status, 409);
  assert.equal((await post('/api/admin/posts/nope/retry')).status, 404);
  row = postRow(s.sql);
  assert.equal(row.error, null);
  const listed = (await (await get('/api/admin/posts?status=posted')).json()).posts[0];
  assert.deepEqual([listed.ig_media_id, listed.fb_post_id, listed.fb_story_id], ['17890000000000202', '100000000000001_100000000000302', null]);
  assert.equal(publishedTo(listed), 'Instagram feed, Facebook Page');
  assert.equal(publishedTo({kind: 'story', ig_media_id: 'x', fb_post_id: null, fb_story_id: null}), 'Instagram Story');
});

dbTest('both surfaces failing is failed; a retry tries both again', async () => {
  const s = setup(), fake = graphFake({limit: 'publishing-limit', on: {[`POST /${IG}/media`]: () => jsonResponse(fixture('error-unknown-field'), 400), [`POST /${PAGE}/photos`]: () => jsonResponse(fixture('error-page-photo'), 400)}});
  addMedia(s.sql, 'm1'); addPost(s.sql);
  const {value} = await quiet(() => P.publish(s.env, 'p1', deps(s, fake).deps));
  assert.equal(value.outcome, 'failed');
  assert.match(postRow(s.sql).error, /^instagram: meta media failed: HTTP 400 code 100.*; facebook: meta photos failed/);
  await quiet(() => P.publish(s.env, 'p1', deps(s, fake).deps, {retry: true}));
  assert.equal(fake.count('POST', `/${IG}/media`), 2);
  assert.equal(fake.count('POST', `/${PAGE}/photos`), 2);
});

// ---- idempotency --------------------------------------------------------------------------------------------------

dbTest('idempotent: a stored container is polled and published, never created again; a concurrent run is busy; a carousel keeps its children', async () => {
  const s = setup(), fake = graphFake();
  addMedia(s.sql, 'm1'); addPost(s.sql, {targets: ['instagram'], extra: {ig_container_id: '17890000000000555'}});
  s.sql.prepare("UPDATE advisor_posts SET status='publishing' WHERE id='p1'").run();
  const {value} = await quiet(() => P.publish(s.env, 'p1', deps(s, fake).deps));
  assert.equal(value.outcome, 'posted');
  assert.equal(fake.count('POST', `/${IG}/media`), 0);
  assert.equal(fake.calls.find(c => c.path === `/${IG}/media_publish`).params.creation_id, '17890000000000555');
  // The lease: a second run while one holds it does nothing.
  const s2 = setup(), fake2 = graphFake();
  addMedia(s2.sql, 'm1'); addPost(s2.sql);
  s2.sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run('advisor.publish.lock.p1', iso(T0 + 60000), iso(T0));
  assert.deepEqual(await P.publish(s2.env, 'p1', deps(s2, fake2).deps), {outcome: 'busy'});
  assert.equal(fake2.calls.length, 0);
  // An expired lease is taken over.
  s2.sql.prepare("UPDATE job_state SET value=? WHERE key='advisor.publish.lock.p1'").run(iso(T0 - 1));
  assert.equal((await quiet(() => P.publish(s2.env, 'p1', deps(s2, fake2).deps))).value.outcome, 'posted');
  // A carousel interrupted after two children reuses them.
  const s3 = setup(), fake3 = graphFake();
  for (const id of ['m1', 'm2', 'm3']) addMedia(s3.sql, id);
  addPost(s3.sql, {kind: 'carousel', media: ['m1', 'm2', 'm3'], targets: ['instagram']});
  s3.sql.prepare("UPDATE advisor_posts SET status='publishing' WHERE id='p1'").run();
  s3.sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run('advisor.publish.p1', JSON.stringify({ig_children: ['17890000000000901', '17890000000000902'], ig_started_at: iso(T0)}), iso(T0));
  await quiet(() => P.publish(s3.env, 'p1', deps(s3, fake3).deps));
  const made = fake3.calls.filter(c => c.path === `/${IG}/media`);
  assert.deepEqual(made.map(c => c.params.image_url ?? c.params.children), ['https://skippercast.com/media/m3.jpg', '17890000000000901,17890000000000902,17890000000000101']);
});

// ---- off, holds, derived files ----------------------------------------------------------------------------------------

dbTest('nothing is published while ADVISOR_SOCIAL_ENABLED is off or Meta is not configured; post now and retry answer 409', async () => {
  for (const env of [{ADVISOR_SOCIAL_ENABLED: 'false'}, {ADVISOR_SOCIAL_ENABLED: undefined}, {META_PAGE_TOKEN: undefined}]) {
    const s = setup({env}), fake = graphFake();
    addMedia(s.sql, 'm1'); addPost(s.sql);
    assert.deepEqual(await P.publishDue(s.env, T0, deps(s, fake).deps), {status: 'off', outcomes: []});
    const {post} = app(s, fake);
    const now = await post('/api/admin/posts/p1/publish');
    assert.equal(now.status, 409);
    assert.match((await now.json()).error, /ADVISOR_SOCIAL_ENABLED|Meta secrets/);
    assert.equal(fake.calls.length, 0);
    assert.equal(postRow(s.sql).status, 'approved');
  }
});

dbTest('a photo not derived yet: the media job is dispatched and the post waits (approved, no Graph call); a photo the job gave up on fails the post', async () => {
  const s = setup(), fake = graphFake();
  addMedia(s.sql, 'm1', {derived: false}); addPost(s.sql);
  let dispatched = 0;
  const {value} = await quiet(() => P.publish({...s.env, GITHUB_TOKEN: 'gh-PLACEHOLDER'}, 'p1', {...deps(s, fake).deps, dispatch: async () => { dispatched++; return 204; }}));
  assert.deepEqual(value, {outcome: 'deferred'});
  assert.equal(dispatched, 1);
  assert.equal(fake.calls.length, 0);
  assert.equal(postRow(s.sql).status, 'approved');
  const s2 = setup(), fake2 = graphFake();
  addMedia(s2.sql, 'm1', {derivedError: 'decode-failed: x'}); addPost(s2.sql);
  const broken = await quiet(() => P.publish(s2.env, 'p1', deps(s2, fake2).deps));
  assert.deepEqual(broken.value, {outcome: 'failed', error: 'a photo of this post could not be prepared for posting'});
  assert.equal(postRow(s2.sql).status, 'failed');
});

dbTest('consent revoked or the boat unverified after approval: the post is held (failed with the reason), nothing goes to Meta', async () => {
  const s = setup({boat: {revoked: iso(T0 - 1000)}}), fake = graphFake();
  addMedia(s.sql, 'm1'); addPost(s.sql);
  const {value} = await quiet(() => P.publish(s.env, 'p1', deps(s, fake).deps));
  assert.equal(value.outcome, 'held');
  assert.deepEqual([postRow(s.sql).status, postRow(s.sql).error], ['failed', 'the boat has not given (or has revoked) photo consent']);
  assert.equal(fake.calls.length, 0);
});

// ---- admin: post now, schedule -------------------------------------------------------------------------------------------

dbTest('admin: schedule checks the time (future, within 60 days, approved posts only) and clears it; post now publishes and clears the schedule', async () => {
  const s = setup(), fake = graphFake();
  addMedia(s.sql, 'm1'); addPost(s.sql);
  const {post} = app(s, fake);
  const later = iso(T0 + 26 * HOUR);
  let r = await post('/api/admin/posts/p1/schedule', {scheduled_for: later});
  assert.equal(r.status, 200);
  assert.equal((await r.json()).post.scheduled_for, later);
  assert.equal(postRow(s.sql).scheduled_for, later);
  for (const [body, status] of [[{scheduled_for: iso(T0 - 1000)}, 400], [{scheduled_for: iso(T0 + 61 * 24 * HOUR)}, 400], [{scheduled_for: 'soon'}, 400], [{}, 400]])
    assert.equal((await post('/api/admin/posts/p1/schedule', body)).status, status, JSON.stringify(body));
  r = await post('/api/admin/posts/p1/schedule', {scheduled_for: null});
  assert.equal((await r.json()).post.scheduled_for, null);
  s.sql.prepare("UPDATE advisor_posts SET scheduled_for=? WHERE id='p1'").run(later);
  // Due only at its time.
  assert.deepEqual((await P.publishDue(s.env, T0, deps(s, fake).deps)).outcomes, []);
  r = await quiet(() => post('/api/admin/posts/p1/publish'));
  const body = await r.value.json();
  assert.deepEqual([r.value.status, body.outcome, body.post.status, body.post.scheduled_for], [200, 'posted', 'posted', null]);
  assert.equal((await post('/api/admin/posts/p1/publish')).status, 409, 'only an approved post');
  assert.equal((await post('/api/admin/posts/p1/schedule', {scheduled_for: later})).status, 409);
});

dbTest('publishDue: publishing posts first, then due approved posts oldest first, at most five a tick; drafts, rejected and future posts wait', async () => {
  const s = setup(), fake = graphFake();
  for (let i = 1; i <= 8; i++) { addMedia(s.sql, `m${i}`); addPost(s.sql, {id: `p${i}`, media: [`m${i}`], targets: ['facebook'], scheduled: i === 2 ? iso(T0 + HOUR) : iso(T0 - i * 60000)}); }
  s.sql.prepare("UPDATE advisor_posts SET status='draft' WHERE id='p3'").run();
  s.sql.prepare("UPDATE advisor_posts SET status='rejected' WHERE id='p4'").run();
  s.sql.prepare("UPDATE advisor_posts SET status='publishing' WHERE id='p1'").run();
  const {value} = await quiet(() => P.publishDue(s.env, T0, deps(s, fake).deps));
  assert.equal(value.outcomes.length, P.PUBLISH_PER_TICK);
  const posted = s.sql.prepare("SELECT id FROM advisor_posts WHERE status='posted' ORDER BY id").all().map(r => r.id);
  assert.deepEqual(posted, ['p1', 'p5', 'p6', 'p7', 'p8']);
});

dbTest('the cron tick runs publishDue (not a daily slot)', async () => {
  const s = setup(), fake = graphFake();
  addMedia(s.sql, 'm1'); addPost(s.sql);
  const {value} = await quiet(() => advisorCron(s.env, T0, {slots: [], consumer: {channelFor: () => s.channel}, publish: {fetcher: fake.fetcher, sleep: async () => {}, now: () => T0}}));
  assert.equal(value, 'ok');
  assert.equal(postRow(s.sql).status, 'posted');
  assert.equal(s.channel.sent.length, 1);
});

// ---- GET /media for Meta: story.jpg and the video with ranges ---------------------------------------------------------------

const call = (path, env, init) => worker.fetch(new Request(ORIGIN + path, init), {ASSETS: {fetch: async () => new Response('other', {status: 299})}, ...env});

test('byteRange: a-b, a-, -n; past the end is unsatisfiable; anything else is served whole', () => {
  assert.deepEqual(byteRange('bytes=0-9', 100), {offset: 0, length: 10});
  assert.deepEqual(byteRange('bytes=90-', 100), {offset: 90, length: 10});
  assert.deepEqual(byteRange('bytes=-5', 100), {offset: 95, length: 5});
  assert.deepEqual(byteRange('bytes=50-500', 100), {offset: 50, length: 50});
  assert.deepEqual(byteRange('bytes=-500', 100), {offset: 0, length: 100});
  assert.equal(byteRange('bytes=100-', 100), 'unsatisfiable');
  assert.equal(byteRange('bytes=9-3', 100), 'unsatisfiable');
  for (const h of [null, '', 'bytes=0-1,5-6', 'items=0-1', 'bytes=-']) assert.equal(byteRange(h, 100), null, String(h));
});

dbTest('GET /media/<id>.story.jpg serves the derived story.jpg only; /media/<id>.mp4 serves an approved video\'s stripped copy with Range support (206, 416) and 404 otherwise', async () => {
  const s = setup();
  addMedia(s.sql, 'm1'); addMedia(s.sql, 'v1', {kind: 'video'}); addMedia(s.sql, 'v2', {kind: 'video', state: 'queued'});
  const video = new Uint8Array(Array.from({length: 100}, (_, i) => i));
  s.bucket.objects.set('advisor/derived/v1/video.mp4', {bytes: video, httpMetadata: {}});
  s.bucket.objects.set('advisor/derived/v2/video.mp4', {bytes: video, httpMetadata: {}});
  s.bucket.objects.set('advisor/media/c1/m1.jpg', {bytes: new Uint8Array([1, 2, 3]), httpMetadata: {}});
  const env = {TEXT_ADVISOR_ENABLED: 'true', DB: s.db, ADVISOR_MEDIA: s.bucket};
  assert.equal((await call('/media/m1.story.jpg', env)).status, 404, 'no fallback to the original for a story');
  s.bucket.objects.set('advisor/derived/m1/story.jpg', {bytes: new TextEncoder().encode('STORY'), httpMetadata: {}});
  const story = await call('/media/m1.story.jpg', env);
  assert.deepEqual([story.status, story.headers.get('Content-Type'), await story.text()], [200, 'image/jpeg', 'STORY']);
  for (const path of ['/media/m1.story.png', '/media/m1.story.mp4', '/media/v2.mp4', '/media/m1.mp4', '/media/v1.story.jpg', '/media/v1.jpg'])
    assert.equal((await call(path, env)).status, 404, path);
  const whole = await call('/media/v1.mp4', env);
  assert.deepEqual([whole.status, whole.headers.get('Content-Type'), whole.headers.get('Content-Length'), whole.headers.get('Accept-Ranges'), whole.headers.get('X-Robots-Tag')],
    [200, 'video/mp4', '100', 'bytes', 'noindex']);
  assert.deepEqual(new Uint8Array(await whole.arrayBuffer()), video);
  const part = await call('/media/v1.mp4', env, {headers: {Range: 'bytes=10-19'}});
  assert.deepEqual([part.status, part.headers.get('Content-Range'), part.headers.get('Content-Length')], [206, 'bytes 10-19/100', '10']);
  assert.deepEqual([...new Uint8Array(await part.arrayBuffer())], [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]);
  const tail = await call('/media/v1.mp4', env, {headers: {Range: 'bytes=-3'}});
  assert.deepEqual([tail.status, [...new Uint8Array(await tail.arrayBuffer())]], [206, [97, 98, 99]]);
  const beyond = await call('/media/v1.mp4', env, {headers: {Range: 'bytes=200-'}});
  assert.deepEqual([beyond.status, beyond.headers.get('Content-Range')], [416, 'bytes */100']);
  assert.equal((await call('/media/v1.mp4', {DB: s.db, ADVISOR_MEDIA: s.bucket})).status, 404, 'dark while the advisor is off');
});

// ---- TA-S3: collaborators, user tags, collab status -------------------------------------------------------------------------

const TAGS = [{username: 'ritag', x: 0.5, y: 0.5}];

dbTest('collaborators and user tags go on the containers: a photo gets both, a reel collaborators only, a carousel collaborators on the parent and tags on the first image; a story neither', async () => {
  const s = setup(), fake = graphFake();
  addMedia(s.sql, 'm1'); addMedia(s.sql, 'm2'); addMedia(s.sql, 'v1', {kind: 'video'}); addMedia(s.sql, 'm3'); addMedia(s.sql, 'm4');
  addPost(s.sql, {id: 'photo', media: ['m1'], collaborators: ['ritag', 'deckhand.example'], userTags: TAGS, targets: ['instagram']});
  addPost(s.sql, {id: 'reel', kind: 'reel', media: ['v1'], collaborators: ['ritag'], userTags: TAGS, targets: ['instagram']});
  addPost(s.sql, {id: 'carousel', kind: 'carousel', media: ['m2', 'm3'], collaborators: ['ritag'], userTags: TAGS, targets: ['instagram']});
  addPost(s.sql, {id: 'story', kind: 'story', media: ['m4'], collaborators: ['ritag'], userTags: TAGS, targets: ['instagram_story']});
  for (const id of ['photo', 'reel', 'carousel', 'story']) {
    const before = fake.calls.length;
    const {value} = await quiet(() => P.publish(s.env, id, deps(s, fake).deps));
    assert.equal(value.outcome, 'posted', id);
    const made = fake.calls.slice(before).filter(c => c.method === 'POST' && c.path === `/${IG}/media`).map(c => ({collaborators: c.params.collaborators, user_tags: c.params.user_tags}));
    const expected = {
      photo: [{collaborators: '["ritag","deckhand.example"]', user_tags: JSON.stringify(TAGS)}],
      reel: [{collaborators: '["ritag"]', user_tags: undefined}],
      carousel: [{collaborators: undefined, user_tags: JSON.stringify(TAGS)}, {collaborators: undefined, user_tags: undefined}, {collaborators: '["ritag"]', user_tags: undefined}],
      story: [{collaborators: undefined, user_tags: undefined}],
    }[id];
    assert.deepEqual(made, expected, id);
    assert.equal(postRow(s.sql, id).collab_status, id === 'story' ? null : 'invited', id);
  }
  // Bad values in the stored JSON never reach Meta; more than 3 collaborators are cut to 3.
  assert.deepEqual(P.tagsOf({kind: 'photo', collaborators_json: '["a","b","c","d","Bad Name"]', user_tags_json: '[{"username":"a","x":2,"y":0},{"username":"b","x":0.1,"y":0.9},"x"]'}),
    {collaborators: ['a', 'b', 'c'], user_tags: [{username: 'b', x: 0.1, y: 0.9}]});
  assert.deepEqual(P.tagsOf({kind: 'story', collaborators_json: '["a"]', user_tags_json: '[{"username":"a","x":0.5,"y":0.5}]'}), {collaborators: [], user_tags: []});
  assert.deepEqual(P.tagsOf({kind: 'photo', collaborators_json: 'not json', user_tags_json: null}), {collaborators: [], user_tags: []});
});

dbTest('a post without collaborators, or published to the Page only, has no collab status', async () => {
  const s = setup(), fake = graphFake();
  addMedia(s.sql, 'm1'); addMedia(s.sql, 'm2');
  addPost(s.sql, {id: 'p1', media: ['m1']});
  addPost(s.sql, {id: 'p2', media: ['m2'], collaborators: ['ritag'], targets: ['facebook']});
  for (const id of ['p1', 'p2']) await quiet(() => P.publish(s.env, id, deps(s, fake).deps));
  assert.deepEqual([postRow(s.sql, 'p1').collab_status, postRow(s.sql, 'p2').collab_status], [null, null]);
});

test('igCollaborators parses the edge: lower-case usernames, invite_status mapped, junk dropped', async () => {
  const calls = [];
  const fetcher = async (url, init) => { calls.push(url); return jsonResponse({data: [...fixture('collaborators').data, {username: 'Bad Name', invite_status: 'Accepted'}, {username: 'X.y', invite_status: 'Weird'}]}); };
  const list = await meta.igCollaborators({token: 'EAAB-PLACEHOLDER-TOKEN', appSecret: 'app-secret-PLACEHOLDER', fetcher, sleep: async () => {}}, '17890000000000202');
  assert.deepEqual(list, [{id: '17841400000000101', username: 'ritag', invite_status: 'accepted'}, {id: '17841400000000102', username: 'deckhand.example', invite_status: 'pending'},
    {id: null, username: 'x.y', invite_status: null}]);
  const u = new URL(calls[0]);
  assert.equal(u.pathname, `/${meta.GRAPH_VERSION}/17890000000000202/collaborators`);
  assert.equal(u.searchParams.get('fields'), 'id,username,invite_status');
});

test('collabStatusOf: pending or unlisted -> invited; else declined wins over accepted; all accepted -> accepted', () => {
  const A = 'accepted', D = 'declined', W = 'pending';
  assert.equal(P.collabStatusOf(['ritag'], [{username: 'ritag', invite_status: A}]), 'accepted');
  assert.equal(P.collabStatusOf(['RitaG'], [{username: 'ritag', invite_status: A}]), 'accepted');
  assert.equal(P.collabStatusOf(['ritag'], [{username: 'ritag', invite_status: D}]), 'declined');
  assert.equal(P.collabStatusOf(['ritag', 'b'], [{username: 'ritag', invite_status: A}, {username: 'b', invite_status: W}]), 'invited');
  assert.equal(P.collabStatusOf(['ritag', 'b'], [{username: 'ritag', invite_status: A}]), 'invited', 'not listed is still waiting');
  assert.equal(P.collabStatusOf(['ritag', 'b'], [{username: 'ritag', invite_status: A}, {username: 'b', invite_status: D}]), 'declined');
  assert.equal(P.collabStatusOf(['ritag'], [{username: 'ritag', invite_status: null}]), 'invited');
});

dbTest('collabTick: at most hourly, reads GET /<media>/collaborators for invited posts of the last 14 days and stores accepted or declined; a failed read changes nothing; off with the switch', async () => {
  const s = setup();
  const fake = graphFake({on: {'GET /17890000000000301/collaborators': () => jsonResponse({data: [{id: '17841400000000101', username: 'ritag', invite_status: 'Accepted'}]})}});
  for (const [id, media, posted, collab] of [['p1', '17890000000000301', T0 - HOUR, ['ritag']], ['p2', '17890000000000302', T0 - 2 * HOUR, ['ritag', 'deckhand.example']],
    ['old', '17890000000000303', T0 - 15 * 86400000, ['ritag']], ['done', '17890000000000304', T0 - HOUR, ['ritag']]]) {
    addMedia(s.sql, `m-${id}`);
    addPost(s.sql, {id, media: [`m-${id}`], collaborators: collab, status: 'posted'});
    s.sql.prepare('UPDATE advisor_posts SET ig_media_id=?,posted_at=?,collab_status=? WHERE id=?').run(media, iso(posted), id === 'done' ? 'accepted' : 'invited', id);
  }
  const first = await quiet(() => P.collabTick(s.env, T0, {fetcher: fake.fetcher, sleep: async () => {}}));
  assert.deepEqual(first.value, {status: 'ran', read: 2, changed: 1});
  const reads = fake.calls.filter(c => c.path.endsWith('/collaborators'));
  assert.deepEqual(reads.map(c => [c.path, c.params.fields]), [['/17890000000000302/collaborators', 'id,username,invite_status'], ['/17890000000000301/collaborators', 'id,username,invite_status']],
    'oldest first; the 15-day-old and the answered post are not read');
  assert.deepEqual(['p1', 'p2', 'old', 'done'].map(id => postRow(s.sql, id).collab_status), ['accepted', 'invited', 'invited', 'accepted'],
    'p2 has one collaborator still pending (the fixture)');
  // Within the hour: nothing.
  assert.deepEqual(await P.collabTick(s.env, T0 + 30 * 60000, {fetcher: fake.fetcher}), {status: 'throttled', read: 0, changed: 0});
  // An hour later p2's other collaborator declined; a failing read leaves a post as it was.
  s.sql.prepare("UPDATE advisor_posts SET collab_status='invited' WHERE id='p1'").run();
  const fake2 = graphFake({on: {'GET /17890000000000301/collaborators': () => jsonResponse(fixture('error-server'), 500),
    'GET /17890000000000302/collaborators': () => jsonResponse({data: [{username: 'ritag', invite_status: 'Accepted'}, {username: 'deckhand.example', invite_status: 'Declined'}]})}});
  const second = await quiet(() => P.collabTick(s.env, T0 + HOUR, {fetcher: fake2.fetcher, sleep: async () => {}}));
  assert.deepEqual(second.value, {status: 'ran', read: 1, changed: 1});
  assert.ok(!second.lines.join('\n').includes('EAAB-PLACEHOLDER-TOKEN'));
  assert.deepEqual(['p1', 'p2'].map(id => postRow(s.sql, id).collab_status), ['invited', 'declined']);
  // Off: no read at all.
  const off = setup({env: {ADVISOR_SOCIAL_ENABLED: 'false'}});
  assert.deepEqual(await P.collabTick(off.env, T0, {fetcher: fake.fetcher}), {status: 'off', read: 0, changed: 0});
});

dbTest('the cron tick reads collab status; the admin card carries collab_status', async () => {
  const s = setup(), fake = graphFake();
  addMedia(s.sql, 'm1');
  addPost(s.sql, {media: ['m1'], collaborators: ['ritag'], status: 'posted'});
  s.sql.prepare("UPDATE advisor_posts SET ig_media_id='17890000000000202',posted_at=?,collab_status='invited' WHERE id='p1'").run(iso(T0 - HOUR));
  await quiet(() => advisorCron(s.env, T0, {slots: [], consumer: {channelFor: () => s.channel}, publish: {fetcher: fake.fetcher, sleep: async () => {}, now: () => T0}}));
  assert.equal(postRow(s.sql).collab_status, 'accepted', 'the fixture lists ritag as Accepted');
  const {get} = app(s, fake);
  const card = (await (await get('/api/admin/posts?status=posted')).json()).posts[0];
  assert.equal(card.collab_status, 'accepted');
});

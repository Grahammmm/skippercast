// Text Advisor media runner job, Worker side (TA-M1; docs/plans/text-advisor/09-social.md
// § Derived images and graphics): the two job endpoints behind a GitHub Actions
// identity (a fake verifier here; tests/test_job_auth.mjs covers the real one),
// the pending work list, the media-done handler, the dispatch throttle, the
// cron's re-dispatch, the consumer's wait for public.jpg and the vision chain
// reading it. Offline, against the real migrations.
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
const {advisorJobs, ADVISOR_JOB_SCOPE} = await import('../server/routes/advisor.ts');
const media = await import('../server/advisor/media.ts');
const {mediaJobWork, mediaJobPending, mediaJobDone, requestMediaJob, requestGraphic, graphicState, awaitingDerived, derivedKeys,
  MEDIA_JOB_KEY, VISION_MAX_BYTES, DISPATCH_EVERY_MS, CRON_DISPATCH_EVERY_MS, ingestMedia} = media;
const {consumeAdvisor, runInline, ADVISOR_QUEUE_NAME, DERIVED_WAITS, DERIVED_RETRY_SECONDS} = await import('../server/advisor/consumer.ts');
const {mediaJobTick, advisorCron} = await import('../server/advisor/cron.ts');
const {visionChain, THRESHOLDS, MediaTooLarge} = await import('../server/advisor/vision/index.ts');
const {dispatchWorkflow} = await import('../server/watchdog.ts');
const {ADVISOR_QUEUES} = await import('../scripts/wrangler_config.mjs');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-04T15:00:00Z');
const ON = {TEXT_ADVISOR_ENABLED: 'true'};
const ORIGIN = 'https://skippercast.com';
const BIG = VISION_MAX_BYTES + 1;
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

/** One contact and the given media rows (all stored unless r2_key is ''). */
function setup(rows = []) {
  const {sql, db} = advisorDatabase(), at = new Date(T0).toISOString();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,status,last_seen_at,created_at,updated_at) VALUES('c1','h1','ENC','imessage','active',?,?,?)`).run(at, at, at);
  rows.forEach((r, i) => sql.prepare(`INSERT INTO advisor_media(id,contact_id,message_id,kind,mime,bytes,width,height,r2_key,sha256,publish_state,derived_at,orientation,created_at)
    VALUES(?,'c1',?,?,?,?,?,?,?,?,?,?,?,?)`).run(r.id, r.message_id ?? null, r.kind ?? 'image', r.mime ?? 'image/jpeg', r.bytes ?? 1000, r.width ?? null, r.height ?? null,
    r.r2_key ?? `advisor/media/c1/${r.id}.jpg`, r.sha ?? `sha-${r.id}`, r.state ?? 'private', r.derived_at ?? null, r.orientation ?? null, new Date(T0 + i * 1000).toISOString()));
  return {sql, db};
}
const row = (sql, id) => ({...sql.prepare('SELECT * FROM advisor_media WHERE id=?').get(id)});
const dispatcher = (status = 204) => { const calls = []; return {calls, dispatch: async (env, file) => { calls.push(file); return status; }}; };

// ---- endpoints -------------------------------------------------------------------

const call = (path, env, init) => worker.fetch(new Request(ORIGIN + path, init), env);
const withVerifier = async (verify, fn) => { const saved = advisorJobs.verify; advisorJobs.verify = verify; try { return await fn(); } finally { advisorJobs.verify = saved; } };
const accept = async token => token === 'good' ? {jti: 'run-1'} : false;
const auth = (token = 'good') => ({Authorization: `Bearer ${token}`});
const post = (payload, token) => ({method: 'POST', headers: {...auth(token), 'Content-Type': 'application/json'}, body: JSON.stringify(payload)});

test('the job scope is the advisor audience and advisor-media.yml only', () => {
  assert.deepEqual(ADVISOR_JOB_SCOPE, {audiencePath: '/api/advisor/jobs', workflows: ['advisor-media.yml']});
  assert.ok(DEPLOYMENT.scheduler.workflows.includes('advisor-media.yml'));
});

dbTest('the job endpoints are gated, and need a job identity: no token, a bad one or a refused one is 401', async () => {
  const {sql, db} = setup([{id: 'big', bytes: BIG}]), env = {...ON, DB: db};
  await withVerifier(accept, async () => {
    assert.equal((await call('/api/advisor/jobs/media', {DB: db}, {headers: auth()})).status, 404, 'dark until TEXT_ADVISOR_ENABLED');
    assert.equal((await call('/api/advisor/jobs/media', env)).status, 401);
    assert.equal((await call('/api/advisor/jobs/media', env, {headers: auth('bad')})).status, 401);
    assert.equal((await call('/api/advisor/jobs/media-done', env, post({media_id: 'big', error: 'x'}, 'bad'))).status, 401);
    assert.equal(row(sql, 'big').derived_at, null, 'a refused report changes nothing');
    const ok = await call('/api/advisor/jobs/media', env, {headers: auth()});
    assert.equal(ok.status, 200);
    assert.equal(ok.headers.get('Cache-Control'), 'no-store');
    assert.deepEqual((await ok.json()).media.map(m => m.id), ['big']);
  });
  // The default verifier is the real one: an unsigned token never passes.
  assert.equal((await call('/api/advisor/jobs/media', env, {headers: auth('a.b.c')})).status, 401);
});

dbTest('GET /api/advisor/jobs/media lists images vision cannot read as stored, HEIC, and photos headed for review or pages, plus pending graphics', async () => {
  const {sql, db} = setup([
    {id: 'small', bytes: 1000},                                  // private everyday photo: left alone
    {id: 'big', bytes: BIG},                                     // too large for vision
    {id: 'heic', mime: 'image/heic', r2_key: 'advisor/media/c1/heic.heic'},
    {id: 'queued', state: 'queued'}, {id: 'approved', state: 'approved'}, {id: 'posted', state: 'posted'},
    {id: 'rejected', bytes: BIG, state: 'rejected'},
    {id: 'done', bytes: BIG, derived_at: new Date(T0).toISOString()},
    {id: 'video', kind: 'video', mime: 'video/mp4', bytes: BIG, state: 'approved', r2_key: 'advisor/media/c1/video.mp4'},
    {id: 'placeholder', bytes: BIG, r2_key: ''},
  ]);
  const env = {...ON, DB: db, GITHUB_TOKEN: 't'};
  const {calls, dispatch} = dispatcher();
  await quiet(() => requestGraphic(env, 'g1', {kind: 'daily', data: {port: 'Morro Bay', lines: [{label: 'Rockfish', value: 'limits'}]}, out_key: 'advisor/posts/p1/daily.jpg'}, T0, {dispatch}));
  await quiet(() => requestGraphic(env, 'g2', {kind: 'story', media_ids: ['approved', 'missing'], data: {title: 'Today'}, out_key: 'advisor/posts/p2/story.jpg'}, T0 + 1, {dispatch}));
  assert.deepEqual(calls, ['advisor-media.yml'], 'the second request is inside the minute');
  assert.equal(await mediaJobPending(db), 7, 'five images and two graphics');
  const work = await withVerifier(accept, async () => (await call('/api/advisor/jobs/media', {...ON, DB: db}, {headers: auth()})).json());
  assert.deepEqual(work.media.map(m => m.id), ['big', 'heic', 'queued', 'approved', 'posted']);
  assert.deepEqual(work.media[1], {id: 'heic', r2_key: 'advisor/media/c1/heic.heic', mime: 'image/heic', sha256: 'sha-heic', bytes: 1000, orientation: null,
    keys: {public: 'advisor/derived/heic/public.jpg', thumb: 'advisor/derived/heic/thumb.jpg', story: 'advisor/derived/heic/story.jpg'}});
  assert.deepEqual(work.graphics, [
    {id: 'g1', kind: 'daily', out_key: 'advisor/posts/p1/daily.jpg', data: {port: 'Morro Bay', lines: [{label: 'Rockfish', value: 'limits'}]}, media: []},
    {id: 'g2', kind: 'story', out_key: 'advisor/posts/p2/story.jpg', data: {title: 'Today'},
      media: [{id: 'approved', r2_key: 'advisor/media/c1/approved.jpg', mime: 'image/jpeg', orientation: null, public_key: 'advisor/derived/approved/public.jpg'}]},
  ]);
  assert.deepEqual((await mediaJobWork(db, {media: 2, graphics: 1})).media.map(m => m.id), ['big', 'heic'], 'paged, oldest first');
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM job_state WHERE key LIKE 'advisor.graphic.%'").get().n, 2);
});

dbTest('a private JPEG stored sideways (orientation 2-8) is pending with its orientation; an upright one is not', async () => {
  const {db} = setup([{id: 'upright', orientation: 1}, {id: 'none'}, {id: 'turned', orientation: 6}, {id: 'mirrored', orientation: 2},
    {id: 'turned-done', orientation: 8, derived_at: new Date(T0).toISOString()}, {id: 'turned-rejected', orientation: 6, state: 'rejected'}]);
  const work = await mediaJobWork(db);
  assert.deepEqual(work.media.map(m => [m.id, m.orientation]), [['turned', 6], ['mirrored', 2]]);
  assert.equal(await mediaJobPending(db), 2);
});

dbTest('/media never serves a sideways original; it serves the upright public.jpg once the job made it', async () => {
  const {sql, db} = setup([{id: 'side', orientation: 6, state: 'approved'}, {id: 'flat', orientation: 1, state: 'approved'}]);
  sql.prepare("UPDATE advisor_media SET exif_stripped=1").run();
  const bucket = memoryBucket({'advisor/media/c1/side.jpg': 'SIDEWAYS', 'advisor/media/c1/flat.jpg': 'UPRIGHT-ORIGINAL'});
  const env = {...ON, DB: db, ADVISOR_MEDIA: bucket};
  assert.equal((await call('/media/side.jpg', env)).status, 404, 'no derived file yet: not the sideways original');
  assert.equal(await (await call('/media/flat.jpg', env)).text(), 'UPRIGHT-ORIGINAL');
  await bucket.put(derivedKeys('side').public, 'UPRIGHT-DERIVED');
  assert.equal(await (await call('/media/side.jpg', env)).text(), 'UPRIGHT-DERIVED');
});

dbTest('requestGraphic validates the request shape and a rerun with the same id renders again', async () => {
  const {db} = setup([]), env = {DB: db};
  const ok = {kind: 'roundup', media_ids: ['a', 'b'], data: {title: 'Week'}, out_key: 'advisor/posts/w1/roundup.jpg'};
  for (const [bad, why] of [[{...ok, kind: 'banner'}, 'kind'], [{...ok, out_key: 'advisor/media/c1/x.jpg'}, 'out_key'], [{...ok, out_key: 'advisor/posts/../x.jpg'}, 'out_key'],
    [{...ok, media_ids: ['bad id']}, 'media_ids'], [{...ok, media_ids: Array.from({length: 11}, (_, i) => `m${i}`)}, 'media_ids'],
    [{...ok, data: []}, 'data'], [{...ok, data: {big: 'x'.repeat(17000)}}, 'data']]) await assert.rejects(requestGraphic(env, 'g1', bad, T0), new RegExp(why), why);
  await assert.rejects(requestGraphic(env, 'bad id', ok, T0), /graphic id/);
  assert.equal(await requestGraphic(env, 'g1', ok, T0), 'no-token', 'no GITHUB_TOKEN: stored, not dispatched');
  assert.equal((await graphicState(db, 'g1')).status, 'pending');
  await mediaJobDone(env, {graphic_id: 'g1', keys: {public: ok.out_key}, width: 1080, height: 1350}, T0);
  assert.equal((await graphicState(db, 'g1')).status, 'done');
  await requestGraphic(env, 'g1', {...ok, data: {title: 'Week, again'}}, T0 + 1000);
  const again = await graphicState(db, 'g1');
  assert.deepEqual([again.status, again.data.title, again.keys], ['pending', 'Week, again', undefined]);
});

dbTest('POST /api/advisor/jobs/media-done stamps derived_at, fills HEIC dimensions, and takes the item off the list', async () => {
  const {sql, db} = setup([{id: 'heic', mime: 'image/heic'}, {id: 'big', bytes: BIG, width: 4032, height: 3024}]), env = {...ON, DB: db};
  await withVerifier(accept, async () => {
    const k = derivedKeys('heic');
    const done = await call('/api/advisor/jobs/media-done', env, post({media_id: 'heic', keys: k, width: 1440, height: 1080, source_width: 4032, source_height: 3024}));
    assert.equal(done.status, 200);
    assert.deepEqual(await done.json(), {ok: true, kind: 'media', status: 'done'});
    const r = row(sql, 'heic');
    assert.ok(r.derived_at); assert.equal(r.derived_error, null);
    assert.deepEqual([r.width, r.height], [4032, 3024], 'the original size, read by the job');
    // A known size is never overwritten; story is optional.
    await call('/api/advisor/jobs/media-done', env, post({media_id: 'big', keys: {public: derivedKeys('big').public, thumb: derivedKeys('big').thumb}, width: 1440, height: 1080, source_width: 1, source_height: 1}));
    assert.deepEqual([row(sql, 'big').width, row(sql, 'big').height], [4032, 3024]);
    assert.deepEqual((await mediaJobWork(db)).media, []);
  });
});

dbTest('media-done refuses keys that are not the item\'s own, bad dimensions and unknown ids; an error marks the item given up', async () => {
  const {sql, db} = setup([{id: 'a', bytes: BIG}, {id: 'b', bytes: BIG}]), env = {...ON, DB: db};
  const k = derivedKeys('a');
  await withVerifier(accept, async () => {
    for (const payload of [
      {media_id: 'a', keys: {...k, public: 'advisor/derived/b/public.jpg'}, width: 10, height: 10},
      {media_id: 'a', keys: {...k, public: 'advisor/media/c1/a.jpg'}, width: 10, height: 10},
      {media_id: 'a', keys: {...k, extra: 'advisor/derived/a/x.jpg'}, width: 10, height: 10},
      {media_id: 'a', keys: k, width: 0, height: 10},
      {media_id: 'a', keys: k, width: 1.5, height: 10},
      {media_id: 'a', keys: k},
      {media_id: 'bad id', keys: k, width: 10, height: 10},
      {media_id: 'a', graphic_id: 'g', keys: k, width: 10, height: 10},
      {media_id: 'a', error: '<script>'},
      {},
    ]) assert.equal((await call('/api/advisor/jobs/media-done', env, post(payload))).status, 400, JSON.stringify(payload));
    assert.equal(row(sql, 'a').derived_at, null, 'nothing was stamped');
    assert.equal((await call('/api/advisor/jobs/media-done', env, post({media_id: 'nope', keys: derivedKeys('nope'), width: 10, height: 10}))).status, 404);
    const failed = await call('/api/advisor/jobs/media-done', env, post({media_id: 'b', error: 'decode-failed: cannot identify image file'}));
    assert.deepEqual(await failed.json(), {ok: true, kind: 'media', status: 'failed'});
  });
  assert.deepEqual([Boolean(row(sql, 'b').derived_at), row(sql, 'b').derived_error], [true, 'decode-failed: cannot identify image file']);
  assert.deepEqual((await mediaJobWork(db)).media.map(m => m.id), ['a'], 'a given-up item is not pending any more');
});

dbTest('a graphic is done with its out_key (roundup slides beside it) or failed; anything else is refused', async () => {
  const {db} = setup([]), env = {...ON, DB: db};
  await requestGraphic(env, 'r1', {kind: 'roundup', data: {title: 'Week'}, out_key: 'advisor/posts/w1/roundup.jpg'}, T0);
  await requestGraphic(env, 'd1', {kind: 'daily', data: {}, out_key: 'advisor/posts/d1/daily.jpg'}, T0);
  for (const keys of [{public: 'advisor/posts/w1/other.jpg'}, {public: 'advisor/posts/w1/roundup.jpg', slides: ['advisor/posts/x/roundup-1.jpg']},
    {public: 'advisor/posts/w1/roundup.jpg', slides: 'advisor/posts/w1/roundup-1.jpg'}, {public: 'advisor/posts/w1/roundup.jpg', thumb: 'x'}])
    assert.deepEqual(await mediaJobDone(env, {graphic_id: 'r1', keys, width: 1080, height: 1350}, T0), {ok: false, error: 'invalid'}, JSON.stringify(keys));
  assert.deepEqual(await mediaJobDone(env, {graphic_id: 'zz', keys: {public: 'advisor/posts/zz/a.jpg'}, width: 1, height: 1}, T0), {ok: false, error: 'not-found'});
  const slides = ['advisor/posts/w1/roundup-1.jpg', 'advisor/posts/w1/roundup-2.jpg'];
  assert.deepEqual(await mediaJobDone(env, {graphic_id: 'r1', keys: {public: 'advisor/posts/w1/roundup.jpg', slides}, width: 1080, height: 1350}, T0), {ok: true, kind: 'graphic', status: 'done'});
  const done = await graphicState(db, 'r1');
  assert.deepEqual([done.status, done.keys, done.width, done.height, done.done_at], ['done', {public: 'advisor/posts/w1/roundup.jpg', slides}, 1080, 1350, new Date(T0).toISOString()]);
  await mediaJobDone(env, {graphic_id: 'd1', error: 'render-failed'}, T0);
  assert.deepEqual([(await graphicState(db, 'd1')).status, (await graphicState(db, 'd1')).error], ['failed', 'render-failed']);
  assert.deepEqual((await mediaJobWork(db)).graphics, []);
});

// ---- dispatch --------------------------------------------------------------------

dbTest('requestMediaJob dispatches advisor-media.yml at most once a minute; a failed dispatch keeps the claim', async () => {
  assert.equal(DISPATCH_EVERY_MS, 60000);
  const {sql, db} = setup([]);
  const {calls, dispatch} = dispatcher();
  assert.equal(await requestMediaJob({DB: db}, T0, {dispatch}), 'no-token');
  const env = {DB: db, GITHUB_TOKEN: 't'};
  assert.equal((await quiet(() => requestMediaJob(env, T0, {dispatch}))).value, 'dispatched');
  assert.equal(await requestMediaJob(env, T0 + 30000, {dispatch}), 'throttled');
  assert.equal(await requestMediaJob(env, T0 + 59999, {dispatch}), 'throttled');
  assert.equal((await quiet(() => requestMediaJob(env, T0 + 60000, {dispatch}))).value, 'dispatched');
  assert.deepEqual(calls, ['advisor-media.yml', 'advisor-media.yml']);
  assert.equal(sql.prepare('SELECT value FROM job_state WHERE key=?').get(MEDIA_JOB_KEY).value, new Date(T0 + 60000).toISOString());
  const failing = dispatcher(404);
  const {value, lines} = await quiet(() => requestMediaJob(env, T0 + 200000, {dispatch: failing.dispatch}));
  assert.equal(value, 'failed-404'); assert.ok(lines.some(l => /advisor_media_dispatch_failed/.test(l)));
  assert.equal(await requestMediaJob(env, T0 + 210000, {dispatch: failing.dispatch}), 'throttled', 'no hammering after a failure');
  const thrown = await quiet(() => requestMediaJob(env, T0 + 300000, {dispatch: async () => { throw new TypeError('network'); }}));
  assert.equal(thrown.value, 'error', 'never throws');
});

test('dispatchWorkflow POSTs the workflow_dispatch with the watchdog token; no token is 0; a bad file name throws', async () => {
  const real = globalThis.fetch, seen = [];
  globalThis.fetch = async (url, init) => { seen.push({url, method: init.method, body: init.body, auth: init.headers.Authorization}); return new Response(null, {status: 204}); };
  try {
    assert.equal(await dispatchWorkflow({GITHUB_TOKEN: 'tok'}, 'advisor-media.yml'), 204);
    assert.deepEqual(seen, [{url: 'https://api.github.com/repos/Grahammmm/skippercast/actions/workflows/advisor-media.yml/dispatches', method: 'POST', body: '{"ref":"main"}', auth: 'Bearer tok'}]);
    assert.equal(await dispatchWorkflow({}, 'advisor-media.yml'), 0);
    await assert.rejects(dispatchWorkflow({GITHUB_TOKEN: 'tok'}, '../ci.yml'), /invalid workflow/);
    assert.equal(seen.length, 1);
  } finally { globalThis.fetch = real; }
});

dbTest('ingesting an image over 4.5 MB or a HEIC starts the job; a small JPEG does not', async () => {
  const {db} = setup([]), bucket = memoryBucket(), env = {DB: db, ADVISOR_MEDIA: bucket, GITHUB_TOKEN: 't'};
  const real = globalThis.fetch, dispatched = [];
  globalThis.fetch = async url => { dispatched.push(String(url)); return new Response(null, {status: 204}); };
  const heic = new Uint8Array(64); heic.set([0, 0, 0, 24], 0); heic.set(new TextEncoder().encode('ftypheic'), 4);
  const jpeg = Uint8Array.from([0xff, 0xd8, 0xff, 0xe0, 0, 16, 74, 70, 73, 70, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 0xff, 0xc0, 0, 11, 8, 0, 10, 0, 10, 1, 1, 0x11, 0, 0xff, 0xd9]);
  const input = (id, bytes, mime) => ({mediaId: id, contactId: 'c1', messageId: null, boatId: null, providerRef: null, fetchBytes: async () => new Response(bytes), claimedMime: mime, name: null});
  try {
    await quiet(() => ingestMedia(env, input('j1', jpeg, 'image/jpeg'), T0));
    assert.deepEqual(dispatched, [], 'a small JPEG needs nothing derived for vision');
    await quiet(() => ingestMedia(env, input('h1', heic, 'image/heic'), T0));
    assert.deepEqual(dispatched, ['https://api.github.com/repos/Grahammmm/skippercast/actions/workflows/advisor-media.yml/dispatches']);
  } finally { globalThis.fetch = real; }
  assert.deepEqual((await mediaJobWork(db)).media.map(m => m.id), ['h1']);
});

dbTest('ingesting a small JPEG stored sideways (EXIF orientation 6) starts the job for its upright public.jpg', async () => {
  const {db} = setup([]), bucket = memoryBucket(), env = {DB: db, ADVISOR_MEDIA: bucket, GITHUB_TOKEN: 't'};
  const real = globalThis.fetch, dispatched = [];
  globalThis.fetch = async url => { dispatched.push(String(url)); return new Response(null, {status: 204}); };
  // SOI, APP1 "Exif\0\0" + big-endian TIFF with IFD0 {Orientation SHORT 6}, SOF0 10x10, EOI.
  const exif = [0x45, 0x78, 0x69, 0x66, 0, 0, 0x4d, 0x4d, 0, 42, 0, 0, 0, 8, 0, 1, 0x01, 0x12, 0, 3, 0, 0, 0, 1, 0, 6, 0, 0, 0, 0, 0, 0];
  const jpeg = Uint8Array.from([0xff, 0xd8, 0xff, 0xe1, 0, exif.length + 2, ...exif, 0xff, 0xc0, 0, 11, 8, 0, 10, 0, 10, 1, 1, 0x11, 0, 0xff, 0xd9]);
  try {
    const {value} = await quiet(() => ingestMedia(env, {mediaId: 's1', contactId: 'c1', messageId: null, boatId: null, providerRef: null, fetchBytes: async () => new Response(jpeg), claimedMime: 'image/jpeg', name: null}, T0));
    assert.equal(value.orientation, 6);
    assert.equal(dispatched.length, 1);
  } finally { globalThis.fetch = real; }
  assert.deepEqual((await mediaJobWork(db)).media.map(m => [m.id, m.orientation]), [['s1', 6]]);
});

dbTest('the cron re-dispatches while anything is pending, at most once per 15 minutes, and idles otherwise', async () => {
  assert.ok(CRON_DISPATCH_EVERY_MS > 14 * 60000 && CRON_DISPATCH_EVERY_MS < 15 * 60000, 'a tick 15 minutes later is never skipped');
  const {sql, db} = setup([{id: 'small'}]), env = {...ON, DB: db, GITHUB_TOKEN: 't'};
  const {calls, dispatch} = dispatcher();
  assert.equal(await mediaJobTick(env, T0, {dispatchWorkflow: dispatch}), 'idle');
  assert.equal(await mediaJobTick({...env, GITHUB_TOKEN: undefined}, T0, {dispatchWorkflow: dispatch}), 'idle');
  sql.prepare("UPDATE advisor_media SET publish_state='approved' WHERE id='small'").run();
  assert.equal((await quiet(() => mediaJobTick(env, T0, {dispatchWorkflow: dispatch}))).value, 'dispatched');
  assert.equal(await mediaJobTick(env, T0 + 5 * 60000, {dispatchWorkflow: dispatch}), 'throttled');
  assert.equal((await quiet(() => mediaJobTick(env, T0 + 15 * 60000 - 2000, {dispatchWorkflow: dispatch}))).value, 'dispatched', 'the next tick, a little early');
  assert.equal(calls.length, 2);
  // advisorCron runs the tick (no relay configured, no slots).
  const {value} = await quiet(() => advisorCron(env, T0 + 30 * 60000, {slots: [], dispatchWorkflow: dispatch}));
  assert.equal(value, 'ok'); assert.equal(calls.length, 3);
});

// ---- the consumer waits for public.jpg -------------------------------------------

function batchOf(attempts) {
  const message = {id: 'q0', body: {message_id: 'in1'}, attempts, timestamp: new Date(T0), outcome: null, delay: undefined,
    ack() { this.outcome = 'ack'; }, retry(o) { this.outcome = 'retry'; this.delay = o?.delaySeconds; }};
  return {queue: ADVISOR_QUEUE_NAME, messages: [message], ackAll() { message.ack(); }, retryAll() { message.retry(); }};
}
const silent = {name: 'test', async send() { return {providerId: 'p', status: 'sent'}; }};
function inbound(sql, ids) {
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,media_json,status,created_at) VALUES('in1','c1','in','imessage','g1',NULL,?,'queued',?)`)
    .run(JSON.stringify(ids), new Date(T0).toISOString());
}

dbTest('a message with a photo over 4.5 MB waits for public.jpg (retry 30 s, job dispatched) on its first three attempts, then runs', async () => {
  assert.equal(DERIVED_WAITS, ADVISOR_QUEUES.consumers[0].max_retries, 'the last delivery always runs the handler');
  assert.equal(DERIVED_RETRY_SECONDS, 30);
  const {sql, db} = setup([{id: 'big', bytes: BIG, message_id: 'in1'}]);
  inbound(sql, ['big']);
  const env = {...ON, DB: db, ADVISOR_MEDIA: memoryBucket(), GITHUB_TOKEN: 't'};
  const {calls, dispatch} = dispatcher();
  let ran = 0;
  const handler = async () => { ran++; return {actions: [], intent: 'test'}; };
  for (const attempt of [1, 2, 3]) {
    const batch = batchOf(attempt);
    await quiet(() => consumeAdvisor(batch, env, {channel: silent, handler, now: () => T0 + attempt * 30000, dispatchWorkflow: dispatch}));
    assert.deepEqual([batch.messages[0].outcome, batch.messages[0].delay, ran], ['retry', 30, 0], `attempt ${attempt}`);
    assert.deepEqual({...sql.prepare("SELECT status,error FROM advisor_messages WHERE id='in1'").get()}, {status: 'queued', error: 'media-derive'});
  }
  assert.deepEqual(calls, ['advisor-media.yml', 'advisor-media.yml'], 'at 30 s and 90 s: at most once a minute while it waits');
  const last = batchOf(4);
  await quiet(() => consumeAdvisor(last, env, {channel: silent, handler, now: () => T0 + 120000, dispatchWorkflow: dispatch}));
  assert.deepEqual([last.messages[0].outcome, ran], ['ack', 1], 'the fourth delivery runs the handler (upload link if still too large)');
});

dbTest('no wait once public.jpg exists (or the job gave up), without GITHUB_TOKEN, for small photos, or inline', async () => {
  const handler = async () => ({actions: [], intent: 'test'});
  const run = async (rows, extra = {}, deps = {}) => {
    const {sql, db} = setup(rows.map(r => ({...r, message_id: 'in1'})));
    inbound(sql, rows.map(r => r.id));
    const batch = batchOf(1), env = {...ON, DB: db, ADVISOR_MEDIA: memoryBucket(), GITHUB_TOKEN: 't', ...extra};
    await quiet(() => consumeAdvisor(batch, env, {channel: silent, handler, now: () => T0, dispatchWorkflow: dispatcher().dispatch, ...deps}));
    return {outcome: batch.messages[0].outcome, db, sql};
  };
  assert.equal((await run([{id: 'big', bytes: BIG, derived_at: new Date(T0).toISOString()}])).outcome, 'ack', 'derived');
  assert.equal((await run([{id: 'small'}])).outcome, 'ack', 'small JPEG');
  assert.equal((await run([{id: 'side', orientation: 6}])).outcome, 'ack', 'a sideways JPEG does not wait: vision gets the orientation in its prompt');
  assert.equal((await run([{id: 'big', bytes: BIG}], {GITHUB_TOKEN: undefined})).outcome, 'ack', 'no way to start the job');
  assert.equal((await run([{id: 'v', kind: 'video', mime: 'video/mp4', bytes: BIG}])).outcome, 'ack', 'videos are never derived');
  assert.equal((await run([{id: 'h', mime: 'image/heic'}])).outcome, 'retry', 'a HEIC waits too');
  // runInline cannot be re-delivered, so it never waits.
  const {sql, db} = setup([{id: 'big', bytes: BIG, message_id: 'in1'}]);
  inbound(sql, ['big']);
  let ran = 0;
  await quiet(() => runInline({...ON, DB: db, ADVISOR_MEDIA: memoryBucket(), GITHUB_TOKEN: 't'}, 'in1', {channel: silent, handler: async () => { ran++; return {actions: [], intent: 'test'}; }, dispatchWorkflow: dispatcher().dispatch}));
  assert.equal(ran, 1);
  assert.equal(await awaitingDerived(db, 'not json'), 0);
  assert.equal(await awaitingDerived(db, JSON.stringify(['big', 'bad id', 7])), 1);
});

// ---- vision reads public.jpg -------------------------------------------------------

test('the vision limit and the job\'s threshold are the same number', () => assert.equal(VISION_MAX_BYTES, THRESHOLDS.maxImageBytes));

dbTest('the vision chain reads public.jpg for an original over 4.5 MB or a HEIC, and still throws MediaTooLarge without it', async () => {
  const {db} = setup([{id: 'big', bytes: BIG}, {id: 'heic', mime: 'image/heic'}]);
  const bucket = memoryBucket({'advisor/media/c1/big.jpg': new Uint8Array(BIG), 'advisor/media/c1/heic.heic': new Uint8Array(100)});
  const env = {...ON, DB: db, ADVISOR_MEDIA: bucket, ADVISOR_VISION_PROVIDERS: 'claude'};
  const seen = [];
  const classification = {kind: 'fish', kind_confidence: 0.9, has_person: false, person_confidence: 0, has_fish: true, text_present: false, nsfw: false, provider: 'claude', model: 'm', ms: 1};
  const fake = {name: 'claude', async classify(image) { seen.push({mime: image.mime, bytes: (await image.bytes()).byteLength}); return classification; },
    async readCountBoard() { throw Error('unused'); }, async identifyFish() { throw Error('unused'); }, async health() { return {ok: true, detail: ''}; }};
  const chain = visionChain(env, {providers: {claude: fake}});
  const image = (id, mime, key) => ({media_id: id, mime, bytes: async () => (await bucket.get(key)).arrayBuffer()});
  const {lines} = await quiet(() => assert.rejects(chain.classify(image('big', 'image/jpeg', 'advisor/media/c1/big.jpg')), MediaTooLarge));
  assert.ok(lines.some(l => /advisor_vision_too_large/.test(l)));
  bucket.objects.set('advisor/derived/big/public.jpg', {bytes: new Uint8Array(300000), httpMetadata: {}});
  bucket.objects.set('advisor/derived/heic/public.jpg', {bytes: new Uint8Array(200000), httpMetadata: {}});
  await chain.classify(image('big', 'image/jpeg', 'advisor/media/c1/big.jpg'));
  await chain.classify(image('heic', 'image/heic', 'advisor/media/c1/heic.heic'));
  assert.deepEqual(seen, [{mime: 'image/jpeg', bytes: 300000}, {mime: 'image/jpeg', bytes: 200000}]);
});

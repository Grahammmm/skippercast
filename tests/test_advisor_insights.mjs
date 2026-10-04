// Post insights (TA-S7; docs/plans/text-advisor/09-social.md § Insights, SP-10):
// the 03:00 slot reads every post published in the last 30 days (Instagram media
// insights by kind, the Page post's reach, reactions, comments and shares) into
// advisor_post_stats by day; Stories are read hourly while they are up and never
// after; a metric Meta does not support counts 0 with a note; any other failure
// writes nothing. "Chats started" per post from the per-post link
// /text?s=ig&p=<post_id> (advisor_contacts.source_post_id); the Posts card and the
// Funnel's social rows. Offline: real migrations in node:sqlite and recorded Graph
// API responses from tests/fixtures/advisor/meta/ (placeholder ids and tokens only).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const I = await import('../server/advisor/social/insights.ts');
const {parseInsights} = await import('../server/advisor/social/meta.ts');
const {advisorCron} = await import('../server/advisor/cron.ts');
const {storeInbound} = await import('../server/advisor/inbound.ts');
const {parseSourceMarker} = await import('../server/advisor/intents.ts');
const {textBody} = await import('../server/routes/advisor.ts');
const {listPosts} = await import('../server/advisor/admin/posts.ts');
const {adminFunnel} = await import('../server/advisor/admin/funnel.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const fixture = name => read(`./fixtures/advisor/meta/${name}.json`);
const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {status, headers: {'content-type': 'application/json'}});
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const iso = ms => new Date(ms).toISOString();
const HOUR = 3600000, DAY = 86400000;
const T0 = Date.parse('2026-10-05T10:05:00Z');   // 03:05 in Morro Bay (PDT)
const IG = '17841400000000000', PAGE = '100000000000001';
const META = {META_APP_SECRET: 'app-secret-PLACEHOLDER', META_PAGE_TOKEN: 'EAAB-PLACEHOLDER-TOKEN', META_IG_USER_ID: IG, META_PAGE_ID: PAGE};
const FB_POST = '100000000000001_200000000000001';
const POST_ID = 'a'.repeat(32);   // the shape of a deterministic advisor_posts id

const MEDIA = {photo: '17890000000000202', carousel: '17890000000000203', reel: '17890000000000301', story: '17890000000000401', old: '17890000000000999', expired: '17890000000000402'};
const one = (name, value) => ({data: [{name, period: 'lifetime', values: [{value}]}]});

/** A recorded Graph API for insights: by media id and requested metrics; records every call. */
function graphFake() {
  const calls = [];
  const fetcher = async (url, init = {}) => {
    const u = new URL(url), path = u.pathname.replace(/^\/v\d+\.0/, ''), params = Object.fromEntries(u.searchParams.entries());
    calls.push({method: init.method ?? 'GET', path, metric: params.metric ?? null, fields: params.fields ?? null});
    const [, id, edge] = path.split('/');
    if (edge === 'insights' && id === FB_POST) return jsonResponse(fixture('fb-post-insights'));
    if (!edge && id === FB_POST) return jsonResponse(fixture('fb-post-counts'));
    if (edge === 'insights') {
      const metrics = (params.metric ?? '').split(',');
      if (id === MEDIA.photo) return jsonResponse(fixture('insights-feed'));
      if (id === MEDIA.reel) return jsonResponse(fixture('insights-reel'));
      if (id === MEDIA.story) return jsonResponse(fixture('insights-story'));
      if (id === MEDIA.expired) return jsonResponse(fixture('error-insights-story-expired'), 400);
      if (id === MEDIA.carousel) {
        // A carousel without profile_activity: Meta refuses the set, and that metric alone.
        if (metrics.includes('profile_activity')) return jsonResponse(fixture('error-insights-unsupported'), 400);
        const feed = parseInsights(fixture('insights-feed'));
        return jsonResponse({data: metrics.map(m => one(m, feed[m]).data[0])});
      }
    }
    return jsonResponse({error: {code: 803, message: 'unexpected call in test'}}, 400);
  };
  return {fetcher, calls, reads: id => calls.filter(c => c.path.startsWith(`/${id}`))};
}

function setup(env = {}) {
  const {sql, db} = advisorDatabase();
  return {sql, db, env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ...META, ...env}};
}
function addPost(sql, id, {kind = 'photo', status = 'posted', ago = 2 * DAY, ig = null, fb = null, fbStory = null} = {}) {
  sql.prepare(`INSERT INTO advisor_posts(id,kind,region,media_json,caption,targets_json,status,ig_media_id,fb_post_id,fb_story_id,created_by,posted_at,created_at,updated_at)
    VALUES(?,?,'morro-bay','[]','A caption',?,?,?,?,?,'engine',?,?,?)`)
    .run(id, kind, JSON.stringify(kind === 'story' ? ['instagram_story', 'facebook_story'] : ['instagram', 'facebook']), status, ig, fb, fbStory,
      status === 'posted' || status === 'partial' ? iso(T0 - ago) : null, iso(T0 - ago - HOUR), iso(T0 - ago));
}
const stats = (sql, id) => sql.prepare('SELECT * FROM advisor_post_stats WHERE post_id=? ORDER BY platform, day').all(id).map(r => ({...r}));
const deps = fake => ({fetcher: fake.fetcher, sleep: async () => {}});

test('parseInsights reads values[0].value and total_value.value; anything else is left out', () => {
  assert.deepEqual(parseInsights(fixture('insights-feed')),
    {views: 1840, reach: 1203, likes: 96, comments: 7, saved: 12, shares: 5, follows: 3, profile_visits: 21, profile_activity: 9});
  assert.deepEqual(parseInsights({data: [{name: 'reach', values: [{value: 'x'}]}, {name: 'Bad Name', values: [{value: 1}]}, {name: 'views', values: []}, {name: 'saved', values: [{value: -1}]}]}), {});
  assert.deepEqual(parseInsights(null), {});
  assert.deepEqual(I.metricsFor('story'), ['views', 'reach', 'replies', 'follows', 'profile_visits']);
  assert.deepEqual(I.metricsFor('reel').at(-1), 'ig_reels_avg_watch_time');
  for (const kind of ['photo', 'carousel', 'daily', 'roundup']) assert.deepEqual(I.metricsFor(kind), I.FEED_METRICS);
});

dbTest('the 03:00 slot reads the last 30 days of posted posts: Instagram by kind and the Page post; drafts, older posts and expired Stories are not read', async () => {
  const s = setup(), fake = graphFake();
  addPost(s.sql, 'p-photo', {ig: MEDIA.photo, fb: FB_POST});
  addPost(s.sql, 'p-reel', {kind: 'reel', status: 'partial', ago: 5 * DAY, ig: MEDIA.reel});
  addPost(s.sql, 'p-story', {kind: 'story', ago: 30 * HOUR, ig: MEDIA.story, fbStory: '100000000000001_300000000000001'});
  addPost(s.sql, 'p-old', {ago: 40 * DAY, ig: MEDIA.old});
  addPost(s.sql, 'p-draft', {status: 'draft'});
  const {value} = await quiet(() => I.collectInsights(s.env, T0, deps(fake)));
  assert.deepEqual(value, {posts: 3, instagram: 2, facebook: 1, failed: 0});
  assert.deepEqual(fake.reads(MEDIA.photo).map(c => c.metric), [I.FEED_METRICS.join(',')]);
  assert.deepEqual(fake.reads(MEDIA.reel).map(c => c.metric), [I.REELS_METRICS.join(',')]);
  assert.equal(fake.reads(MEDIA.story).length, 0, 'a Story past 24 hours has no insights left to read');
  assert.equal(fake.reads(MEDIA.old).length, 0, 'older than 30 days');
  assert.deepEqual(fake.reads(FB_POST).map(c => [c.path, c.metric ?? c.fields]), [[`/${FB_POST}/insights`, 'post_impressions_unique'],
    [`/${FB_POST}`, 'shares,reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)']]);
  const [fb, ig] = stats(s.sql, 'p-photo');
  assert.deepEqual([ig.platform, ig.day, ig.views, ig.reach, ig.likes, ig.comments, ig.saved, ig.shares, ig.follows, ig.profile_visits, ig.link_taps],
    ['instagram', '2026-10-05', 1840, 1203, 96, 7, 12, 5, 3, 21, 0]);
  assert.deepEqual(JSON.parse(ig.raw_json), {metrics: parseInsights(fixture('insights-feed'))}, 'raw_json keeps the metric values only');
  assert.deepEqual([fb.platform, fb.views, fb.reach, fb.likes, fb.comments, fb.shares], ['facebook', 0, 812, 57, 6, 4]);
  const reel = stats(s.sql, 'p-reel');
  assert.equal(reel.length, 1);
  assert.equal(JSON.parse(reel[0].raw_json).metrics.ig_reels_avg_watch_time, 6840);
  assert.deepEqual(JSON.parse(s.sql.prepare("SELECT value FROM job_state WHERE key='advisor.insights.last_run'").get().value), {at: iso(T0), posts: 3, instagram: 2, facebook: 1, failed: 0});
  // A rerun the same local day replaces the numbers; the next day adds a row (the post's growth).
  await quiet(() => I.collectInsights(s.env, T0 + HOUR, deps(fake)));
  assert.equal(stats(s.sql, 'p-photo').length, 2);
  await quiet(() => I.collectInsights(s.env, T0 + DAY, deps(fake)));
  assert.deepEqual(stats(s.sql, 'p-photo').map(r => [r.platform, r.day]), [['facebook', '2026-10-05'], ['facebook', '2026-10-06'], ['instagram', '2026-10-05'], ['instagram', '2026-10-06']]);
});

dbTest('a metric Meta does not support for the media counts 0 with a note; the others are read one by one', async () => {
  const s = setup(), fake = graphFake();
  addPost(s.sql, 'p-carousel', {kind: 'carousel', ig: MEDIA.carousel});
  const {value} = await quiet(() => I.collectInsights(s.env, T0, deps(fake)));
  assert.deepEqual(value, {posts: 1, instagram: 1, facebook: 0, failed: 0});
  const calls = fake.reads(MEDIA.carousel).map(c => c.metric);
  assert.equal(calls[0], I.FEED_METRICS.join(','), 'the whole set first');
  assert.deepEqual(calls.slice(1), [...I.FEED_METRICS], 'then each metric alone');
  const [row] = stats(s.sql, 'p-carousel');
  assert.deepEqual([row.views, row.reach, row.likes, row.saved, row.profile_visits], [1840, 1203, 96, 12, 21]);
  const raw = JSON.parse(row.raw_json);
  assert.deepEqual(raw.notes, ['profile_activity: unavailable']);
  assert.equal(raw.metrics.profile_activity, 0);
});

dbTest('a Story is read hourly while it is up and not after 24 hours; an expired read writes nothing and keeps the last numbers', async () => {
  const s = setup(), fake = graphFake();
  addPost(s.sql, 'p-story', {kind: 'story', ago: 23 * HOUR + 50 * 60000, ig: MEDIA.story});   // 10 minutes before it expires
  addPost(s.sql, 'p-feed', {ig: MEDIA.photo});
  const first = await quiet(() => I.storyInsightsTick(s.env, T0, deps(fake)));
  assert.deepEqual(first.value, {posts: 1, instagram: 1, facebook: 0, failed: 0});
  assert.deepEqual(fake.reads(MEDIA.story).map(c => c.metric), [I.STORY_METRICS.join(',')]);
  assert.equal(fake.reads(MEDIA.photo).length, 0, 'the tick reads Stories only');
  const [row] = stats(s.sql, 'p-story');
  assert.deepEqual([row.views, row.reach, row.comments, row.follows, row.profile_visits, row.likes], [412, 377, 4, 1, 9, 0], 'replies are the Story\'s comments column');
  // Within the hour: nothing.
  assert.equal((await I.storyInsightsTick(s.env, T0 + 5 * 60000, deps(fake))), 'idle');
  // After it expired: no Story is younger than 24 hours, so nothing is called.
  const later = await I.storyInsightsTick(s.env, T0 + HOUR, deps(fake));
  assert.equal(later, 'idle');
  assert.equal(fake.reads(MEDIA.story).length, 1);
  assert.deepEqual(stats(s.sql, 'p-story').map(r => r.views), [412], 'the last reading stays');
  // A Story Meta refuses at its last read (expired on Meta's clock): counted failed, nothing written, the earlier row kept.
  addPost(s.sql, 'p-expired', {kind: 'story', ago: 22 * HOUR, ig: MEDIA.expired});   // 23.5 hours old at the read below
  s.sql.prepare('INSERT INTO advisor_post_stats(post_id,platform,day,views,raw_json,fetched_at) VALUES(?,?,?,?,?,?)').run('p-expired', 'instagram', '2026-10-05', 300, '{}', iso(T0 - HOUR));
  const {value: refused} = await quiet(() => I.storyInsightsTick(s.env, T0 + 2 * HOUR - 30 * 60000, deps(fake)));
  assert.deepEqual(refused, {posts: 1, instagram: 0, facebook: 0, failed: 1});
  assert.deepEqual(stats(s.sql, 'p-expired').map(r => [r.views, r.raw_json]), [[300, '{}']]);
});

dbTest('without the Meta secrets nothing is read; the cron runs the 03:00 slot and the Story tick with the Graph fetcher', async () => {
  const off = setup({META_PAGE_TOKEN: undefined});
  assert.deepEqual(await I.collectInsights(off.env, T0, deps(graphFake())), {posts: 0, instagram: 0, facebook: 0, failed: 0, skipped: 'not-configured'});
  assert.equal(await I.storyInsightsTick(off.env, T0, deps(graphFake())), 'idle');
  const s = setup(), fake = graphFake();
  addPost(s.sql, 'p-photo', {ig: MEDIA.photo, fb: FB_POST});
  addPost(s.sql, 'p-story', {kind: 'story', ago: 2 * HOUR, ig: MEDIA.story});
  const {value} = await quiet(() => advisorCron(s.env, T0, {slots: undefined, publish: {fetcher: fake.fetcher, sleep: async () => {}}, consumer: {channelFor: () => ({name: 'x', send: async () => ({providerId: null, status: 'failed'})})}}));
  assert.ok(['ok', 'partial'].includes(value));
  assert.equal(s.sql.prepare("SELECT value FROM job_state WHERE key='advisor.slot.insights'").get().value, '2026-10-05');
  assert.equal(stats(s.sql, 'p-photo').length, 2);
  assert.equal(stats(s.sql, 'p-story').length, 1);
  assert.equal(fake.reads(MEDIA.story).length, 2, 'once by the tick and once by the slot, the same day row');
});

// ---- chats started and the admin -----------------------------------------------------------------

test('the per-post link: /text?s=ig&p=<post_id> pre-fills [via ig:<post_id>]; a bad p is dropped; a long post id parses', async () => {
  assert.equal(textBody('hi', 'ig', POST_ID), `hi [via ig:${POST_ID}]`);
  assert.deepEqual(parseSourceMarker(textBody('hi', 'ig', POST_ID)), {text: 'hi', source: 'ig', postId: POST_ID});
  assert.equal(textBody('hi', 'ig', 'bad id!'), 'hi [via ig]');
  assert.equal(textBody('hi', 'qr', POST_ID), 'hi [via qr]', 'p only with s=ig');
  assert.equal(textBody('hi', 'ig', 'x'.repeat(65)), 'hi [via ig]');
  assert.deepEqual(parseSourceMarker(`hi [via ig:${'x'.repeat(65)}]`), {text: `hi [via ig:${'x'.repeat(65)}]`, source: null}, 'over 64 is not a marker');
  const response = await worker.fetch(new Request(`https://skippercast.com/text?s=ig&p=${POST_ID}&m=hi`), {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_NUMBER: '+15555550100',
    ASSETS: {fetch: async () => new Response('', {status: 404})}});
  assert.equal(response.status, 302);
  assert.equal(decodeURIComponent(response.headers.get('Location').split('body=')[1]), `hi [via ig:${POST_ID}]`);
});

dbTest('chats started: the first message\'s post id is kept on the contact and counted on the post card and in the Funnel', async () => {
  const s = setup({ADVISOR_PHONE_KEY: Buffer.alloc(32, 7).toString('base64')}), fake = graphFake();
  addPost(s.sql, POST_ID, {ig: MEDIA.photo, fb: FB_POST, ago: 2 * DAY});
  addPost(s.sql, 'p-reel', {kind: 'reel', ig: MEDIA.reel, ago: 3 * DAY});
  await quiet(() => I.collectInsights(s.env, T0, deps(fake)));
  const msg = (body, from) => ({channel: 'sms', providerId: `sid-${from}`, from, to: '+15555550100', text: body, media: [], receivedAt: iso(T0), isGroup: false});
  await storeInbound(s.env, msg(`what's biting? [via ig:${POST_ID}]`, '+15555550161'), new Date(T0 - HOUR));
  await storeInbound(s.env, msg(`hi [via ig:${MEDIA.reel}]`, '+15555550162'), new Date(T0 - HOUR));   // the Instagram media id in the link counts too
  await storeInbound(s.env, msg('hi [via ig]', '+15555550163'), new Date(T0 - HOUR));                 // the bio link: Instagram, no post
  await storeInbound(s.env, msg(`again [via ig:${POST_ID}]`, '+15555550161'), new Date(T0));         // a later marker never changes first touch
  const contacts = s.sql.prepare('SELECT source, source_post_id FROM advisor_contacts ORDER BY source_post_id').all().map(r => ({...r}));
  assert.deepEqual(contacts, [{source: 'ig', source_post_id: null}, {source: 'ig', source_post_id: MEDIA.reel}, {source: 'ig', source_post_id: POST_ID}]);
  const {posts} = await listPosts(s.db, {status: 'posted'});
  const card = posts.find(p => p.id === POST_ID);
  assert.equal(card.stats.chats, 1);
  assert.deepEqual([card.stats.instagram.views, card.stats.instagram.day, card.stats.facebook.reach, card.stats.facebook.likes], [1840, '2026-10-05', 812, 57]);
  assert.equal(posts.find(p => p.id === 'p-reel').stats.chats, 1);
  const {posts: drafts} = await listPosts(s.db, {status: 'all'});
  assert.ok(drafts.every(p => p.status === 'posted' ? p.stats : p.stats === null));
  const f = await adminFunnel(s.env, 7, {now: T0, sql: null});
  assert.equal(f.social.posts, 2);
  assert.deepEqual(f.social.instagram, {views: 1840 + 5210, reach: 1203 + 3988, likes: 96 + 240, comments: 7 + 18, saved: 12 + 44, shares: 5 + 31, follows: 3 + 11, profile_visits: 21 + 63});
  assert.deepEqual(f.social.facebook, {views: 0, reach: 812, likes: 57, comments: 6, shares: 4, saved: 0, follows: 0, profile_visits: 0});
  assert.deepEqual(f.social.by_kind.map(k => [k.kind, k.posts, k.views, k.chats]), [['photo', 1, 1840, 1], ['reel', 1, 5210, 1]]);
  assert.equal(f.social.chats_from_posts, 2);
  assert.equal(f.social.chats_from_instagram, 3);
  assert.equal(f.social.site_visits_per_post, null);
  assert.ok(!JSON.stringify(f).includes(POST_ID), 'the funnel carries no post id');
});

// TA-S4 (docs/plans/text-advisor/09-social.md § Daily post and roundup, § Content
// calendar): the daily "what's biting" draft from yesterday's verified reports
// (deterministic id, reruns update, superseded by the next day's, the card's
// graphic request, a template caption with the confidence word and never a
// probability), the Sunday roundup (catch photos spread by port and species, 3
// collaborators and the rest mentioned), the content calendar (slot times in
// the region's zone, the oldest approved post per slot, dated kinds, empty
// slots, the week grid), publishing from the generated graphics and
// GET /media/post/<id>/<name>. Offline: real migrations in node:sqlite, the
// committed feed fixtures, an in-memory R2 and a recorded Graph API.
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
const S = await import('../server/advisor/social/daily-post.ts');
const C = await import('../server/advisor/social/calendar.ts');
const G = await import('../server/advisor/social/graphics.ts');
const P = await import('../server/advisor/social/publish.ts');
const {graphicState, mediaJobDone} = await import('../server/advisor/media.ts');
const {decideReview} = await import('../server/advisor/admin/decisions.ts');
const {postDetail} = await import('../server/advisor/admin/posts.ts');
const {reviewId} = await import('../server/advisor/contacts.ts');
const {SLOTS, advisorCron, SLOT_PREFIX} = await import('../server/advisor/cron.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const iso = ms => new Date(ms).toISOString();
const HOUR = 3600000, DAY = 86400000;
const TZ = 'America/Los_Angeles';
const MON = Date.parse('2026-09-28T13:35:00Z');      // Mon 28 Sep, 06:35 in Morro Bay: the feed fixtures' day
const SUN = Date.parse('2026-09-28T00:05:00Z');      // Sun 27 Sep, 17:05 in Morro Bay
const ORIGIN = 'https://skippercast.com';
const ADMIN = 'admin-user-1';
const IG = '17841400000000000', PAGE = '100000000000001';
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

// The intelligence fixture's hours moved into 28 Sep's 06:00-14:00 window (as tests/test_advisor_daily.mjs does).
function intelInWindow() {
  const intel = read('./fixtures/feeds/intelligence.json');
  const delta = Date.parse('2026-09-28T14:00:00Z') / 1000 - intel.forecast.models.gfs_global.data[0].hourly.time[0];
  const walk = o => {
    if (Array.isArray(o)) { o.forEach(walk); return; }
    if (!o || typeof o !== 'object') return;
    for (const [k, v] of Object.entries(o)) if (k === 'time' && Array.isArray(v) && v.every(Number.isFinite)) o[k] = v.map(x => x + delta); else walk(v);
  };
  walk(intel.forecast);
  return intel;
}
function feeds({fail = false} = {}) {
  const daily = read('./fixtures/feeds/daily-latest.json'), intel = intelInWindow();
  return async url => {
    if (fail) throw Error('down');
    if (/intelligence\.json$/.test(url)) return intel;
    if (/latest\.json$/.test(url)) return daily;
    throw Error(`no fixture for ${url}`);
  };
}
const CLASSIFY = kind => JSON.stringify({classify: {kind, kind_confidence: 0.9, has_person: false, person_confidence: 0.05, has_fish: kind === 'fish', text_present: false, nsfw: false}});
const FISH = key => JSON.stringify({classify: {kind: 'fish', kind_confidence: 0.9, has_person: false, person_confidence: 0.05, has_fish: true, text_present: false, nsfw: false},
  fish_id: {candidates: [{species_key: key, label: key, confidence: 0.9, cues: []}]}});

function setup(env = {}) {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(ADMIN, iso(MON));
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,home_port,status,last_seen_at,created_at,updated_at) VALUES('c1','h-c1','ENC-c1','imessage','skipper','en',NULL,'active',?,?,?)`).run(iso(MON), iso(MON), iso(MON));
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,home_port,status,last_seen_at,created_at,updated_at) VALUES('a1','h-a1','ENC-a1','imessage','angler','en','morro-bay','active',?,?,?)`).run(iso(MON), iso(MON), iso(MON));
  const bucket = memoryBucket();
  return {sql, db, bucket, env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_MEDIA: bucket, ADVISOR_NUMBER: '+18055550100', ...env}};
}
function boat(sql, id, name, {port = 'morro-bay', status = 'verified', instagram = null, consent = iso(MON - 30 * DAY), revoked = null} = {}) {
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,instagram,owner_contact_id,status,consent_photos_at,consent_revoked_at,created_at,updated_at) VALUES(?,?,?,?,'morro-bay',?,'c1',?,?,?,?,?)`)
    .run(id, id, name, port, instagram, status, consent, revoked, iso(MON - 60 * DAY), iso(MON - 60 * DAY));
}
function report(sql, id, boatId, date, counts, {port = 'morro-bay', verified = 1, status = 'published', anglers = 20, source = 'text'} = {}) {
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,published_at,created_at,updated_at)
    VALUES(?,?,'morro-bay',?,?,'half-day',?,?,?,?,?,?,?,?)`).run(id, boatId, port, date, anglers, JSON.stringify(counts), `${source}-${id}`, status, verified, `${date}T22:00:00Z`, iso(MON - DAY), iso(MON - DAY));
}
const VERMILION = (kept, extra = []) => [{species_key: 'vermilion', label: 'vermilion', kept, released: 0}, ...extra];
const LINGS = kept => ({species_key: 'lingcod', label: 'lingcod', kept, released: 1});
function photo(sql, id, {boatId = 'b1', contact = 'c1', state = 'approved', classification = FISH('lingcod'), at = SUN - 2 * DAY, credit = null} = {}) {
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,classification_json,has_person,publish_state,credit,derived_at,created_at)
    VALUES(?,?,?,'image','image/jpeg',1000,?,'sha',1,?,0,?,?,?,?)`).run(id, contact, boatId, `advisor/media/${contact}/${id}.jpg`, classification, state, credit, iso(at), iso(at));
}
const post = (sql, id) => sql.prepare('SELECT * FROM advisor_posts WHERE id=?').get(id);
const dispatcher = () => { const calls = []; return {calls, dispatch: async (_, file) => { calls.push(file); return 204; }}; };

// ---- the daily post ----------------------------------------------------------------------------------

dbTest('the daily post: yesterday\'s verified reports of the region -> one draft with its review, the card requested, a template caption with the ladder word and no probability', async () => {
  const s = setup({GITHUB_TOKEN: 't'});
  boat(s.sql, 'b1', 'Sea Example'); boat(s.sql, 'b2', 'Test Boat', {port: 'port-san-luis'}); boat(s.sql, 'b3', 'Unverified', {status: 'pending'});
  report(s.sql, 'r1', 'b1', '2026-09-27', VERMILION(45, [LINGS(12)]), {anglers: 22});
  report(s.sql, 'r2', 'b2', '2026-09-27', VERMILION(30, [LINGS(3)]), {port: 'port-san-luis', anglers: null});
  report(s.sql, 'r3', 'b3', '2026-09-27', VERMILION(99), {verified: 0});              // an unverified boat: never in the post
  report(s.sql, 'r4', 'b1', '2026-09-26', VERMILION(77));                              // two days ago
  report(s.sql, 'r5', 'b2', '2026-09-27', VERMILION(55), {status: 'draft', source: 'photo'});
  const {calls, dispatch} = dispatcher();
  const {value} = await quiet(() => S.draftDailyPosts(s.env, MON, {feeds: feeds(), dispatch}));
  const id = await C.dailyPostId('morro-bay', '2026-09-28');
  assert.deepEqual(value, [{region: 'morro-bay', status: 'created', postId: id}]);
  assert.equal(id, (await import('../server/advisor/ids.ts').then(m => m.sha256('daily:morro-bay:2026-09-28'))).slice(0, 32), '02: sha256(daily:<region>:<date>)[:32]');
  const row = post(s.sql, id);
  assert.deepEqual([row.kind, row.region, row.boat_id, row.media_json, row.status, row.created_by, JSON.parse(row.targets_json)], ['daily', 'morro-bay', null, '[]', 'draft', 'engine', ['instagram', 'facebook']]);
  const lines = row.caption.split('\n');
  assert.equal(lines[0], "What's biting out of Morro Bay & Avila, Sun Sep 27:");
  assert.equal(lines[1], 'Sea Example: 45 vermilion, 12 lingcod for 22 anglers.');
  assert.equal(lines[2], 'Test Boat: 30 vermilion, 3 lingcod.');
  assert.match(lines[3], /^SMALL CRAFT ADVISORY posted for today\. Conditions: seas 7 ft at 17 s, wind 15-19 kt from the NW, rough/, 'today\'s advisory and conditions line');
  assert.match(lines[4], /^Landing reports, last 7 days: (Insufficient|Low|Moderate)\.$/, 'the ladder word');
  assert.equal(lines[5], "Text SkipperCast for today's report: (805) 555-0100");
  assert.match(row.caption, /\n\n#skippercast #fishreport #morrobay .*#vermilion.*#lingcod/);
  assert.doesNotMatch(row.caption, /%|probab|chance|odds|hotspot|Unverified|99/i);
  const review = s.sql.prepare('SELECT * FROM advisor_reviews WHERE ref_id=?').get(id);
  assert.deepEqual([review.kind, review.reason, review.status, review.id], ['post', 'social_draft', 'open', await reviewId('post', id, 'social_draft')]);
  const graphic = await graphicState(s.db, id);
  assert.deepEqual([graphic.kind, graphic.status, graphic.out_key, graphic.media_ids], ['daily', 'pending', `advisor/posts/${id}/daily.jpg`, undefined]);
  assert.equal(graphic.data.title, "What's biting · Morro Bay & Avila");
  assert.equal(graphic.data.date, 'Sun Sep 27');
  assert.deepEqual(graphic.data.lines, [{label: 'Top counts', value: '75 vermilion, 15 lingcod'}, {label: 'Sea Example', value: '45 vermilion, 12 lingcod'}, {label: 'Test Boat', value: '30 vermilion, 3 lingcod'}]);
  assert.match(graphic.data.conditions, /Conditions: seas 7 ft/);
  assert.match(graphic.data.confidence, /^Landing reports: (Insufficient|Low|Moderate)$/);
  assert.deepEqual(calls, ['advisor-media.yml'], 'the media job is dispatched for the card');
});

dbTest('a rerun the same day updates the one draft (the card again only when its data changed); no report, no post; an approved post is never changed', async () => {
  const s = setup();
  boat(s.sql, 'b1', 'Sea Example');
  const none = await quiet(() => S.draftDailyPosts(s.env, MON, {feeds: feeds()}));
  assert.deepEqual(none.value, [{region: 'morro-bay', status: 'skipped', reason: 'no published verified report yesterday'}]);
  assert.equal(s.sql.prepare('SELECT COUNT(*) AS n FROM advisor_posts').get().n, 0);
  report(s.sql, 'r1', 'b1', '2026-09-27', VERMILION(45));
  await quiet(() => S.draftDailyPosts(s.env, MON, {feeds: feeds()}));
  const id = await C.dailyPostId('morro-bay', '2026-09-28');
  const first = (await graphicState(s.db, id)).requested_at;
  const again = await quiet(() => S.draftDailyPosts(s.env, MON + HOUR, {feeds: feeds()}));
  assert.equal(again.value[0].status, 'updated');
  assert.equal((await graphicState(s.db, id)).requested_at, first, 'same data: the card is not rendered again');
  // A late report changes the caption and the card.
  boat(s.sql, 'b2', 'Test Boat');
  report(s.sql, 'r2', 'b2', '2026-09-27', VERMILION(10));
  await quiet(() => S.draftDailyPosts(s.env, MON + 2 * HOUR, {feeds: feeds()}));
  assert.equal(s.sql.prepare("SELECT COUNT(*) AS n FROM advisor_posts WHERE kind='daily'").get().n, 1, 'never a second draft for the day');
  assert.match(post(s.sql, id).caption, /Test Boat: 10 vermilion/);
  assert.equal((await graphicState(s.db, id)).requested_at, iso(MON + 2 * HOUR));
  assert.equal(s.sql.prepare("SELECT COUNT(*) AS n FROM advisor_reviews WHERE kind='post'").get().n, 1);
  // Approved: a rerun keeps it as it is.
  s.sql.prepare("UPDATE advisor_posts SET status='approved',caption='kept' WHERE id=?").run(id);
  const kept = await quiet(() => S.draftDailyPosts(s.env, MON + 3 * HOUR, {feeds: feeds()}));
  assert.deepEqual(kept.value, [{region: 'morro-bay', status: 'kept', postId: id, reason: 'the post is approved'}]);
  assert.equal(post(s.sql, id).caption, 'kept');
});

dbTest('the next day\'s draft supersedes a daily post still in draft or approved without a time; a feed that fails leaves out the conditions and the word', async () => {
  const s = setup();
  boat(s.sql, 'b1', 'Sea Example');
  report(s.sql, 'r1', 'b1', '2026-09-27', VERMILION(45));
  report(s.sql, 'r2', 'b1', '2026-09-28', VERMILION(20));
  await quiet(() => S.draftDailyPosts(s.env, MON, {feeds: feeds()}));
  const monday = await C.dailyPostId('morro-bay', '2026-09-28'), tuesday = await C.dailyPostId('morro-bay', '2026-09-29');
  await quiet(() => S.draftDailyPosts(s.env, MON + DAY, {feeds: feeds({fail: true})}));
  assert.deepEqual([post(s.sql, monday).status, post(s.sql, monday).error], ['rejected', 'superseded']);
  assert.equal(s.sql.prepare('SELECT status FROM advisor_reviews WHERE ref_id=?').get(monday).status, 'rejected');
  const caption = post(s.sql, tuesday).caption;
  assert.match(caption, /^What's biting out of Morro Bay, Mon Sep 28:\nSea Example: 20 vermilion for 20 anglers\.\nText SkipperCast/, 'one port: its name; no conditions or word without the feeds');
});

dbTest('the daily card holds approval until the media job has rendered it; the card shows the graphic preview', async () => {
  const s = setup();
  boat(s.sql, 'b1', 'Sea Example');
  report(s.sql, 'r1', 'b1', '2026-09-27', VERMILION(45));
  await quiet(() => S.draftDailyPosts(s.env, MON, {feeds: feeds()}));
  const id = await C.dailyPostId('morro-bay', '2026-09-28'), review = await reviewId('post', id, 'social_draft');
  const decide = () => decideReview(s.env, {reviewId: review, decision: 'approve', by: ADMIN, inId: review, key: 'admin'}, {now: MON, send: async () => 0, dispatch: async () => 204});
  const held = await decide();
  assert.equal(held.status, 'conflict');
  assert.match(held.error, /graphic is still being made/);
  assert.deepEqual((await postDetail(s.db, id)).post.graphics, []);
  await quiet(() => mediaJobDone(s.env, {graphic_id: id, keys: {public: `advisor/posts/${id}/daily.jpg`}, width: 1080, height: 1350}, MON));
  const detail = (await postDetail(s.db, id)).post;
  assert.deepEqual(detail.graphics, [`/api/admin/posts/${id}/graphics/daily.jpg`]);
  assert.equal(detail.hold, null);
  assert.equal((await quiet(decide)).value.status, 'applied');
  assert.equal(post(s.sql, id).status, 'approved');
});

// ---- the roundup ----------------------------------------------------------------------------------------

dbTest('the roundup: the week\'s approved catch photos of verified, consenting boats and anglers of the region; 3 collaborators and the rest mentioned; the carousel graphic', async () => {
  const s = setup();
  boat(s.sql, 'b1', 'Sea Example', {instagram: 'seaexample'}); boat(s.sql, 'b2', 'Test Boat', {port: 'port-san-luis', instagram: 'testboat.example'});
  boat(s.sql, 'b3', 'Third Boat', {instagram: 'thirdboat.example'}); boat(s.sql, 'b4', 'Fourth Boat', {instagram: 'fourthboat_example'});
  boat(s.sql, 'b5', 'Pending Boat', {status: 'pending', instagram: 'pendingboat.example'}); boat(s.sql, 'b6', 'Revoked Boat', {consent: iso(MON - 30 * DAY), revoked: iso(MON - 3 * DAY)});
  photo(s.sql, 'p1', {boatId: 'b1', classification: FISH('lingcod'), at: SUN - DAY});
  photo(s.sql, 'p2', {boatId: 'b1', classification: FISH('vermilion'), at: SUN - 2 * DAY});
  photo(s.sql, 'p3', {boatId: 'b1', classification: FISH('lingcod'), at: SUN - 3 * DAY});
  photo(s.sql, 'p4', {boatId: 'b2', classification: FISH('vermilion'), at: SUN - 2 * DAY});
  photo(s.sql, 'p5', {boatId: 'b2', classification: FISH('lingcod'), at: SUN - 4 * DAY});
  photo(s.sql, 'p6', {boatId: 'b3', at: SUN - DAY});
  photo(s.sql, 'p7', {boatId: 'b4', at: SUN - DAY});
  photo(s.sql, 'p8', {boatId: null, contact: 'a1', classification: FISH('vermilion'), credit: 'Sam', at: SUN - DAY});
  // Never in it:
  photo(s.sql, 'x1', {boatId: 'b1', classification: CLASSIFY('count_board')});
  photo(s.sql, 'x2', {boatId: 'b1', state: 'private'});
  photo(s.sql, 'x3', {boatId: 'b1', at: SUN - 8 * DAY});
  photo(s.sql, 'x4', {boatId: 'b5'}); photo(s.sql, 'x5', {boatId: 'b6'});
  photo(s.sql, 'x6', {boatId: 'b1', classification: CLASSIFY('scenery')});
  photo(s.sql, 'x7', {boatId: 'b1'});
  s.sql.prepare("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','media','x7','has_person','open',?)").run(iso(SUN));
  const {value} = await quiet(() => S.draftRoundups(s.env, SUN, {}));
  const id = await C.roundupPostId('morro-bay', '2026-09-27');
  assert.deepEqual(value, [{region: 'morro-bay', status: 'created', postId: id}]);
  const row = post(s.sql, id), media = JSON.parse(row.media_json);
  assert.deepEqual(new Set(media), new Set(['p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8']));
  assert.equal(row.kind, 'roundup');
  assert.deepEqual(JSON.parse(row.collaborators_json), ['seaexample', 'testboat.example', 'fourthboat_example'], 'the boats with the most photos (ties by name), three at most');
  const lines = row.caption.split('\n');
  assert.equal(lines[0], 'This week out of Morro Bay & Avila: 8 catches from 4 boats.');
  assert.ok(lines.includes('Aboard: Sea Example, Test Boat, Fourth Boat, Third Boat.'));
  assert.ok(lines.includes('Also aboard: @thirdboat.example.'), 'the fourth handle is mentioned');
  assert.ok(lines.includes('Photos: Sam.'));
  assert.match(row.caption, /#angler/);
  const graphic = await graphicState(s.db, id);
  assert.deepEqual([graphic.kind, graphic.out_key, graphic.media_ids], ['roundup', `advisor/posts/${id}/roundup.jpg`, media]);
  assert.equal(graphic.data.title, 'This week · Morro Bay & Avila');
  assert.equal(graphic.data.captions.length, 8);
  assert.equal(graphic.data.captions[media.indexOf('p8')], 'Sam · Morro Bay · Vermilion rockfish');
  // A rerun the same Sunday updates the same draft.
  await quiet(() => S.draftRoundups(s.env, SUN + HOUR, {}));
  assert.equal(s.sql.prepare("SELECT COUNT(*) AS n FROM advisor_posts WHERE kind='roundup'").get().n, 1);
});

dbTest('the roundup takes at most 9 photos (with the cover, Meta\'s 10), spread over ports and species; no photo, no roundup', async () => {
  const s = setup();
  assert.equal((await quiet(() => S.draftRoundups(s.env, SUN, {}))).value[0].status, 'skipped');
  boat(s.sql, 'b1', 'Sea Example'); boat(s.sql, 'b2', 'Test Boat', {port: 'port-san-luis'});
  for (let i = 0; i < 10; i++) photo(s.sql, `l${i}`, {boatId: 'b1', classification: FISH('lingcod'), at: SUN - DAY - i * HOUR});
  photo(s.sql, 'v1', {boatId: 'b1', classification: FISH('vermilion'), at: SUN - 5 * DAY});
  photo(s.sql, 's1', {boatId: 'b2', classification: FISH('lingcod'), at: SUN - 6 * DAY});
  const picked = await S.roundupPhotos(s.db, 'morro-bay', SUN);
  assert.equal(picked.length, S.ROUNDUP_PHOTOS_MAX);
  assert.ok(picked.some(p => p.id === 'v1') && picked.some(p => p.id === 's1'), 'every port and species group gets a photo');
  assert.equal(picked[0].id, 'l0', 'the largest group first, newest first');
});

// ---- the calendar ---------------------------------------------------------------------------------------

test('calendar times are local in the region\'s zone, across DST; the catalog is checked', () => {
  assert.equal(C.zonedInstant('2026-10-05', '11:00', TZ), '2026-10-05T18:00:00.000Z');
  assert.equal(C.zonedInstant('2026-12-07', '11:00', TZ), '2026-12-07T19:00:00.000Z');
  assert.equal(C.zonedInstant('2026-03-08', '02:30', TZ), '2026-03-08T10:30:00.000Z', 'a skipped time lands an hour later');
  assert.equal(C.zonedInstant('2026-11-01', '01:30', TZ), '2026-11-01T08:30:00.000Z', 'a repeated time is the first one');
  const cal = C.loadCalendar();
  assert.deepEqual(cal.slots.map(x => [x.id, x.kind, x.time_local]), [['stories', 'story', '07:00'], ['daily-post', 'daily', '08:00'], ['photo-late-morning', 'photo', '11:00'],
    ['photo-evening', 'photo', '17:00'], ['reel', 'reel', '12:00'], ['roundup', 'roundup', '18:30']]);
  assert.equal(cal.lead_hours, 48);
  assert.deepEqual(C.calendarPairs().sort(), ['daily|morro-bay', 'photo|morro-bay', 'reel|morro-bay', 'roundup|morro-bay', 'story|morro-bay']);
  const checked = C.loadCalendar({lead_hours: 9999, slots: [{id: 'a', weekdays: ['Xyz'], time_local: '07:00', kind: 'photo', region: 'r'}, {id: 'b', weekdays: ['Mon'], time_local: '25:00', kind: 'photo', region: 'r'},
    {id: 'c', weekdays: ['Mon'], time_local: '09:00', kind: 'photo', region: 'r'}, {id: 'c', weekdays: ['Tue'], time_local: '09:00', kind: 'photo', region: 'r'}]});
  assert.deepEqual([checked.lead_hours, checked.slots.map(x => [x.id, x.capacity])], [48, [['c', 1]]]);
  // Friday 2 Oct 08:00 to Sunday 4 Oct 08:00: the Friday photos and Reel, the daily posts, the Stories, Sunday's roundup is past the window.
  const from = Date.parse('2026-10-02T15:00:00Z');
  const ids = C.slotInstances(from, from + 48 * HOUR).map(i => `${i.date} ${i.time} ${i.slot}`);
  assert.deepEqual(ids, ['2026-10-02 08:00 daily-post', '2026-10-02 11:00 photo-late-morning', '2026-10-02 12:00 reel', '2026-10-02 17:00 photo-evening',
    '2026-10-03 07:00 stories', '2026-10-03 08:00 daily-post', '2026-10-04 07:00 stories']);
});

function approvedPost(sql, id, {kind = 'photo', approvedAt = MON, scheduled = null, status = 'approved', media = '["m"]'} = {}) {
  sql.prepare(`INSERT INTO advisor_posts(id,kind,region,boat_id,media_json,caption,targets_json,status,scheduled_for,created_by,approved_at,created_at,updated_at)
    VALUES(?,?,'morro-bay',NULL,?,'c','["instagram","facebook"]',?,?,'engine',?,?,?)`).run(id, kind, media, status, scheduled, iso(approvedAt), iso(approvedAt), iso(approvedAt));
}

dbTest('calendarTick: each slot in the next 48 h takes the oldest approved post of its kind without a time; a dated kind only its own date; empty slots are reported once', async () => {
  const s = setup();
  const now = Date.parse('2026-10-05T15:00:00Z');          // Mon 5 Oct, 08:00 in Morro Bay
  approvedPost(s.sql, 'new-photo', {approvedAt: now - HOUR}); approvedPost(s.sql, 'old-photo', {approvedAt: now - 5 * HOUR}); approvedPost(s.sql, 'mid-photo', {approvedAt: now - 3 * HOUR});
  approvedPost(s.sql, 'draft-photo', {status: 'draft'});
  approvedPost(s.sql, 'carousel', {kind: 'carousel'});    // no slot for carousels: left alone (publishDue posts it)
  approvedPost(s.sql, 'old-daily', {kind: 'daily', media: '[]', approvedAt: now - DAY});
  const tuesdayDaily = await C.dailyPostId('morro-bay', '2026-10-06');
  approvedPost(s.sql, tuesdayDaily, {kind: 'daily', media: '[]'});
  const {value, lines} = await quiet(() => C.calendarTick(s.env, now));
  const at = id => post(s.sql, id).scheduled_for;
  assert.equal(at('old-photo'), '2026-10-05T18:00:00.000Z', 'Mon 11:00: the oldest approved photo');
  assert.equal(at('mid-photo'), '2026-10-06T00:00:00.000Z', 'Mon 17:00');
  assert.equal(at('new-photo'), '2026-10-06T18:00:00.000Z', 'Tue 11:00');
  assert.equal(at('draft-photo'), null);
  assert.equal(at('carousel'), null);
  assert.equal(at(tuesdayDaily), '2026-10-06T15:00:00.000Z', 'Tuesday\'s daily post in Tuesday\'s 08:00 slot');
  assert.equal(at('old-daily'), null, 'another date\'s daily post never takes a slot');
  assert.deepEqual(value.empty.map(e => `${e.date} ${e.time} ${e.slot}`), ['2026-10-05 08:00 daily-post', '2026-10-06 07:00 stories', '2026-10-06 17:00 photo-evening',
    '2026-10-07 07:00 stories']);
  assert.ok(lines.some(l => l.includes('advisor_calendar_empty')));
  const second = await quiet(() => C.calendarTick(s.env, now));
  assert.deepEqual(second.value.scheduled, [], 'nothing moves twice');
  assert.ok(!second.lines.some(l => l.includes('advisor_calendar_empty')), 'the same empty slots are not logged again');
});

dbTest('a dated post approved after its slot passed the same day goes out now; the stories slot takes up to its capacity', async () => {
  const s = setup();
  const now = Date.parse('2026-10-05T17:00:00Z');          // Mon 10:00, after the 08:00 daily slot
  const mondayDaily = await C.dailyPostId('morro-bay', '2026-10-05');
  approvedPost(s.sql, mondayDaily, {kind: 'daily', media: '[]'});
  for (let i = 0; i < 12; i++) approvedPost(s.sql, `story${String(i).padStart(2, '0')}`, {kind: 'story', approvedAt: now - (20 - i) * 60000});
  await quiet(() => C.calendarTick(s.env, now));
  assert.equal(post(s.sql, mondayDaily).scheduled_for, iso(now));
  const tuesday = s.sql.prepare("SELECT COUNT(*) AS n FROM advisor_posts WHERE kind='story' AND scheduled_for='2026-10-06T14:00:00.000Z'").get().n;
  const wednesday = s.sql.prepare("SELECT COUNT(*) AS n FROM advisor_posts WHERE kind='story' AND scheduled_for='2026-10-07T14:00:00.000Z'").get().n;
  assert.deepEqual([tuesday, wednesday], [10, 2], 'ten Stories a morning, oldest first');
  assert.equal(post(s.sql, 'story00').scheduled_for, '2026-10-06T14:00:00.000Z');
});

dbTest('publishDue holds an unscheduled approved post of a calendared kind for its slot and posts any other kind at once', async () => {
  const s = setup({ADVISOR_SOCIAL_ENABLED: 'true', META_APP_SECRET: 'app-secret-PLACEHOLDER', META_PAGE_TOKEN: 'EAAB-PLACEHOLDER-TOKEN', META_IG_USER_ID: IG, META_PAGE_ID: PAGE});
  const seen = [];
  approvedPost(s.sql, 'photo'); approvedPost(s.sql, 'carousel', {kind: 'carousel'}); approvedPost(s.sql, 'due', {scheduled: iso(MON - HOUR)});
  const {value} = await quiet(() => P.publishDue(s.env, MON, {fetcher: async url => { seen.push(url); return new Response('{}', {status: 500}); }, sleep: async () => {}, now: () => MON}));
  assert.equal(value.outcomes.length, 2, 'the carousel (no slot) and the scheduled photo; the unscheduled photo waits for the calendar');
  assert.equal(post(s.sql, 'photo').status, 'approved');
});

dbTest('the week grid: every slot instance with its posts, empty ones marked, other scheduled or posted posts beside them; GET /api/admin/posts/calendar', async () => {
  const s = setup();
  const now = Date.parse('2026-10-07T19:00:00Z');          // Wed 12:00
  approvedPost(s.sql, 'in-slot', {scheduled: '2026-10-05T18:00:00.000Z', status: 'posted'});
  approvedPost(s.sql, 'by-hand', {scheduled: '2026-10-08T20:30:00.000Z'});
  approvedPost(s.sql, 'next-week', {scheduled: '2026-10-13T18:00:00.000Z'});
  const week = await C.calendarWeek(s.db, null, now);
  assert.deepEqual([week.tz, week.start, week.end, week.days.length], [TZ, '2026-10-05', '2026-10-11', 7]);
  const monday = week.days[0];
  assert.deepEqual(monday.slots.map(x => [x.slot, x.time, x.empty, x.past, x.posts.map(p => p.id)]), [['stories', '07:00', true, true, []], ['daily-post', '08:00', true, true, []],
    ['photo-late-morning', '11:00', false, true, ['in-slot']], ['photo-evening', '17:00', true, true, []]]);
  assert.deepEqual(week.days[3].others.map(p => p.id), ['by-hand'], 'Thursday\'s post outside any slot');
  assert.deepEqual(week.days[6].slots.map(x => x.slot), ['stories', 'daily-post', 'roundup']);
  assert.ok(!week.days.some(d => [...d.slots.flatMap(x => x.posts), ...d.others].some(p => p.id === 'next-week')));
  assert.deepEqual(await C.calendarWeek(s.db, 'soon', now), {error: 'start must be YYYY-MM-DD'});
  assert.equal((await C.calendarWeek(s.db, '2026-10-14', now)).start, '2026-10-12', 'any day of a week starts on its Monday');
  // Through the admin API.
  const a = new Hono({getPath: request => new URL(request.url).pathname});
  a.use('*', context); a.use('/api/*', requireUser);
  a.route('/', adminRoutes({now: () => now}));
  a.onError(onError);
  const w = withSessions({fetch: (request, e, ctx) => a.fetch(request, e, ctx)});
  const get = path => w.fetch(new Request(ORIGIN + path, {headers: {'x-test-owner': ADMIN}}), s.env);
  const r = await get('/api/admin/posts/calendar?start=2026-10-05');
  assert.equal(r.status, 200);
  assert.equal((await r.json()).days[0].slots[2].posts[0].id, 'in-slot');
  assert.equal((await get('/api/admin/posts/calendar?start=x')).status, 400);
});

// ---- graphics: serving and publishing ------------------------------------------------------------------

const call = (path, env) => worker.fetch(new Request(ORIGIN + path), {ASSETS: {fetch: async () => new Response('other', {status: 299})}, ...env});

dbTest('GET /media/post/<id>/<name> serves a rendered graphic of an approved (or published) post only, and only names its state lists; the admin preview serves a draft\'s', async () => {
  const s = setup();
  approvedPost(s.sql, 'p1', {kind: 'roundup', status: 'draft'});
  s.sql.prepare("INSERT INTO job_state(key,value,updated_at) VALUES('advisor.graphic.p1',?,?)").run(JSON.stringify({kind: 'roundup', data: {}, out_key: 'advisor/posts/p1/roundup.jpg',
    status: 'done', keys: {public: 'advisor/posts/p1/roundup.jpg', slides: ['advisor/posts/p1/roundup-1.jpg']}, width: 1080, height: 1350}), iso(MON));
  for (const key of ['advisor/posts/p1/roundup.jpg', 'advisor/posts/p1/roundup-1.jpg', 'advisor/posts/p1/other.jpg']) s.bucket.objects.set(key, {bytes: new TextEncoder().encode(key), httpMetadata: {}});
  assert.equal((await call('/media/post/p1/roundup.jpg', s.env)).status, 404, 'a draft is not public');
  const a = new Hono({getPath: request => new URL(request.url).pathname});
  a.use('*', context); a.use('/api/*', requireUser); a.route('/', adminRoutes({now: () => MON})); a.onError(onError);
  const w = withSessions({fetch: (request, e, ctx) => a.fetch(request, e, ctx)});
  const preview = await w.fetch(new Request(`${ORIGIN}/api/admin/posts/p1/graphics/roundup-1.jpg`, {headers: {'x-test-owner': ADMIN}}), s.env);
  assert.deepEqual([preview.status, preview.headers.get('Cache-Control'), await preview.text()], [200, 'private, no-store', 'advisor/posts/p1/roundup-1.jpg']);
  s.sql.prepare("UPDATE advisor_posts SET status='approved' WHERE id='p1'").run();
  const cover = await call('/media/post/p1/roundup.jpg', s.env);
  assert.deepEqual([cover.status, cover.headers.get('Content-Type'), cover.headers.get('X-Robots-Tag'), await cover.text()], [200, 'image/jpeg', 'noindex', 'advisor/posts/p1/roundup.jpg']);
  assert.equal((await call('/media/post/p1/roundup-1.jpg', s.env)).status, 200);
  for (const path of ['/media/post/p1/other.jpg', '/media/post/p1/roundup.png', '/media/post/p1/..%2Fx.jpg', '/media/post/nope/roundup.jpg'])
    assert.equal((await call(path, s.env)).status, 404, path);
  s.sql.prepare("UPDATE advisor_posts SET status='rejected' WHERE id='p1'").run();
  assert.equal((await call('/media/post/p1/roundup.jpg', s.env)).status, 404);
  assert.equal((await call('/media/post/p1/roundup.jpg', {DB: s.db, ADVISOR_MEDIA: s.bucket})).status, 404, 'dark while the advisor is off');
});

function graphFake() {
  const calls = [];
  let containers = 0, photos = 0;
  const json = body => new Response(JSON.stringify(body), {status: 200, headers: {'content-type': 'application/json'}});
  const fetcher = async (url, init = {}) => {
    const u = new URL(url), method = init.method ?? 'GET';
    const params = Object.fromEntries((method === 'POST' && typeof init.body === 'string' ? new URLSearchParams(init.body) : u.searchParams).entries());
    const path = u.pathname.replace(/^\/v\d+\.0/, '');
    calls.push({method, path, params});
    if (path === `/${IG}/content_publishing_limit`) return json({data: [{quota_usage: 1, config: {quota_total: 50}}]});
    if (method === 'POST' && path === `/${IG}/media`) return json({id: `1789000000000${100 + ++containers}`});
    if (path === `/${IG}/media_publish`) return json({id: '17890000000009999'});
    if (params.fields === 'status_code,status') return json({status_code: 'FINISHED', id: path.slice(1)});
    if (params.fields === 'permalink') return json({permalink: 'https://www.instagram.com/p/PLACEHOLDER/'});
    if (path === `/${PAGE}/photos`) { photos++; return json(params.published === 'false' ? {id: `100000000000${300 + photos}`} : {id: '100000000000201', post_id: `${PAGE}_100000000000501`}); }
    if (path === `/${PAGE}/feed`) return json({id: `${PAGE}_100000000000601`});
    if (path === `/${PAGE}/photo_stories`) return json({post_id: '100000000000701', success: true});
    return new Response(JSON.stringify({error: {code: 100}}), {status: 400});
  };
  return {fetcher, calls};
}

dbTest('publishing a daily post sends its card; a roundup goes out as a carousel of the cover and slides with its collaborators; a card still rendering waits', async () => {
  const s = setup({ADVISOR_SOCIAL_ENABLED: 'true', META_APP_SECRET: 'app-secret-PLACEHOLDER', META_PAGE_TOKEN: 'EAAB-PLACEHOLDER-TOKEN', META_IG_USER_ID: IG, META_PAGE_ID: PAGE});
  boat(s.sql, 'b1', 'Sea Example', {instagram: 'seaexample'});
  approvedPost(s.sql, 'd1', {kind: 'daily', media: '[]'});
  const state = (id, kind, keys, status = 'done') => s.sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value')
    .run(`advisor.graphic.${id}`, JSON.stringify({kind, data: {}, out_key: keys.public, status, keys, width: 1080, height: 1350}), iso(MON));
  state('d1', 'daily', {public: 'advisor/posts/d1/daily.jpg'}, 'pending');
  const fake = graphFake(), deps = {now: () => MON, sleep: async () => {}, fetcher: fake.fetcher, dispatch: async () => 204, consumer: {channelFor: () => ({send: async () => ({status: 'sent'})})}};
  assert.deepEqual((await quiet(() => P.publish(s.env, 'd1', deps))).value, {outcome: 'deferred'});
  assert.equal(fake.calls.length, 0);
  state('d1', 'daily', {public: 'advisor/posts/d1/daily.jpg'});
  assert.deepEqual((await quiet(() => P.publish(s.env, 'd1', deps))).value, {outcome: 'posted'});
  const image = fake.calls.find(c => c.method === 'POST' && c.path === `/${IG}/media`);
  assert.deepEqual([image.params.image_url, image.params.caption], ['https://skippercast.com/media/post/d1/daily.jpg', 'c']);
  assert.equal(fake.calls.find(c => c.path === `/${PAGE}/photos`).params.url, 'https://skippercast.com/media/post/d1/daily.jpg');
  // The roundup: its photos are held like any post's and go posted with it; Meta gets the slides.
  photo(s.sql, 'm1', {boatId: 'b1'}); photo(s.sql, 'm2', {boatId: 'b1'});
  approvedPost(s.sql, 'w1', {kind: 'roundup', media: '["m1","m2"]'});
  s.sql.prepare(`UPDATE advisor_posts SET collaborators_json='["seaexample"]' WHERE id='w1'`).run();
  state('w1', 'roundup', {public: 'advisor/posts/w1/roundup.jpg', slides: ['advisor/posts/w1/roundup-1.jpg', 'advisor/posts/w1/roundup-2.jpg']});
  const before = fake.calls.length;
  assert.deepEqual((await quiet(() => P.publish(s.env, 'w1', deps))).value, {outcome: 'posted'});
  const mine = fake.calls.slice(before), containers = mine.filter(c => c.method === 'POST' && c.path === `/${IG}/media`);
  assert.deepEqual(containers.slice(0, 3).map(c => [c.params.is_carousel_item, c.params.image_url]), [['true', 'https://skippercast.com/media/post/w1/roundup.jpg'],
    ['true', 'https://skippercast.com/media/post/w1/roundup-1.jpg'], ['true', 'https://skippercast.com/media/post/w1/roundup-2.jpg']]);
  assert.deepEqual([containers[3].params.media_type, containers[3].params.collaborators], ['CAROUSEL', '["seaexample"]']);
  assert.equal(mine.filter(c => c.path === `/${PAGE}/photos` && c.params.published === 'false').length, 3, 'the Page gets the same three images');
  assert.deepEqual(s.sql.prepare("SELECT publish_state FROM advisor_media WHERE id IN ('m1','m2')").all().map(r => r.publish_state), ['posted', 'posted']);
});

dbTest('the cron runs the daily post at 06:30 and the roundup on Sundays at 17:00, once each', async () => {
  const s = setup();
  boat(s.sql, 'b1', 'Sea Example');
  report(s.sql, 'r1', 'b1', '2026-09-27', VERMILION(45));
  photo(s.sql, 'm1', {boatId: 'b1', at: SUN - DAY});
  const slots = SLOTS.filter(x => x.name === 'daily-post' || x.name === 'weekly-roundup');
  const deps = {slots, daily: {feeds: feeds()}};
  // Sunday 27 Sep, 16:45 to 17:30 local: the roundup at 17:00.
  for (let tick = Date.parse('2026-09-27T23:45:00Z'); tick <= Date.parse('2026-09-28T00:30:00Z'); tick += 15 * 60000) assert.equal((await quiet(() => advisorCron(s.env, tick, deps))).value, 'ok');
  assert.equal(s.sql.prepare("SELECT COUNT(*) AS n FROM advisor_posts WHERE kind='roundup'").get().n, 1);
  assert.equal(s.sql.prepare('SELECT value FROM job_state WHERE key=?').get(`${SLOT_PREFIX}weekly-roundup`).value, '2026-09-27');
  // Monday 28 Sep, 06:00 to 07:00 local: the daily post at 06:30.
  for (let tick = Date.parse('2026-09-28T13:00:00Z'); tick <= Date.parse('2026-09-28T14:00:00Z'); tick += 15 * 60000) assert.equal((await quiet(() => advisorCron(s.env, tick, deps))).value, 'ok');
  assert.equal(s.sql.prepare("SELECT COUNT(*) AS n FROM advisor_posts WHERE kind='daily'").get().n, 1);
  assert.equal(s.sql.prepare('SELECT value FROM job_state WHERE key=?').get(`${SLOT_PREFIX}daily-post`).value, '2026-09-28');
  assert.ok(G.usesGraphic({kind: 'daily', media_json: '[]'}) && G.usesGraphic({kind: 'story', media_json: '[]'}) && !G.usesGraphic({kind: 'story', media_json: '["m1"]'}));
});

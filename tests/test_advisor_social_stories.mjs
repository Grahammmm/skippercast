// TA-S5 (docs/plans/text-advisor/09-social.md § Stories, SP-4, § Instagram
// profile, SP-1): the 07:00 morning Stories. Each verified, consenting boat's
// count board from the day before becomes an approved Story without an admin
// decision when its photo has no hold; the day's conditions card is a Story
// with a generated graphic; both fill the calendar's Stories slot and go out
// through the existing publisher. Nothing while social publishing is off. The
// profile copy in 09 fits Instagram's limits. Offline: real migrations in
// node:sqlite, the committed feed fixtures, a recorded Graph API.
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
const ST = await import('../server/advisor/social/stories.ts');
const P = await import('../server/advisor/social/publish.ts');
const C = await import('../server/advisor/social/calendar.ts');
const {postIdForMedia} = await import('../server/advisor/social/drafts.ts');
const {graphicState} = await import('../server/advisor/media.ts');
const {reviewId} = await import('../server/advisor/contacts.ts');
const {SLOTS, advisorCron, SLOT_PREFIX} = await import('../server/advisor/cron.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const iso = ms => new Date(ms).toISOString();
const HOUR = 3600000, DAY = 86400000;
const NOW = Date.parse('2026-09-28T14:05:00Z');      // Mon 28 Sep, 07:05 in Morro Bay (the feed fixtures' day)
const SLOT = '2026-09-28T14:00:00.000Z';              // the 07:00 Stories slot
const YESTERDAY = Date.parse('2026-09-27T21:00:00Z'); // Sun 14:00 local
const IG = '17841400000000000', PAGE = '100000000000001';
const META = {ADVISOR_SOCIAL_ENABLED: 'true', META_APP_SECRET: 'app-secret-PLACEHOLDER', META_PAGE_TOKEN: 'EAAB-PLACEHOLDER-TOKEN', META_IG_USER_ID: IG, META_PAGE_ID: PAGE};
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

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
const BOARD = JSON.stringify({classify: {kind: 'count_board', kind_confidence: 0.95, has_person: false, person_confidence: 0.02, has_fish: false, text_present: true, nsfw: false}});

function setup(env = META) {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,status,last_seen_at,created_at,updated_at) VALUES('c1','h-c1','ENC-c1','imessage','skipper','en','active',?,?,?)`).run(iso(NOW), iso(NOW), iso(NOW));
  return {sql, db, env: {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_MEDIA: memoryBucket(), ADVISOR_NUMBER: '+18055550100', ...env}};
}
function boat(sql, id, name, {status = 'verified', consent = iso(NOW - 30 * DAY), revoked = null, region = 'morro-bay'} = {}) {
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,instagram,owner_contact_id,status,consent_photos_at,consent_revoked_at,created_at,updated_at) VALUES(?,?,?,'morro-bay',?,'ritag','c1',?,?,?,?,?)`)
    .run(id, id, name, region, status, consent, revoked, iso(NOW - 60 * DAY), iso(NOW - 60 * DAY));
}
function board(sql, id, boatId, {at = YESTERDAY, state = 'queued', hasPerson = 0, classification = BOARD} = {}) {
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,classification_json,has_person,publish_state,derived_at,created_at)
    VALUES(?,'c1',?,'image','image/jpeg',1000,?,'sha',1,?,?,?,?,?)`).run(id, boatId, `advisor/media/c1/${id}.jpg`, classification, hasPerson, state, iso(at), iso(at));
}
const post = (sql, id) => sql.prepare('SELECT * FROM advisor_posts WHERE id=?').get(id);
const media = (sql, id) => sql.prepare('SELECT * FROM advisor_media WHERE id=?').get(id);

dbTest('each verified, consenting boat\'s count board from yesterday becomes an approved Story with no admin decision, at the 07:00 slot; its review is closed as auto', async () => {
  const s = setup();
  boat(s.sql, 'b1', 'Rita G'); boat(s.sql, 'b2', 'Patriot'); boat(s.sql, 'b3', 'Pending', {status: 'pending'}); boat(s.sql, 'b4', 'Revoked', {revoked: iso(NOW - DAY)});
  board(s.sql, 'm-old', 'b1', {at: YESTERDAY - 3 * HOUR}); board(s.sql, 'm1', 'b1');          // the boat's latest board wins
  board(s.sql, 'm2', 'b2', {state: 'approved'});
  board(s.sql, 'm3', 'b3'); board(s.sql, 'm4', 'b4');                                        // never: unverified, consent revoked
  board(s.sql, 'm5', 'b2', {at: YESTERDAY - DAY});                                             // two days ago
  board(s.sql, 'm6', 'b2', {at: NOW - 10 * 60000});                                            // today
  board(s.sql, 'm7', 'b2', {state: 'private'});                                                // never queued (no consent at the time)
  const {value} = await quiet(() => ST.morningStories(s.env, NOW, {feeds: feeds()}));
  const id1 = await postIdForMedia('m1'), id2 = await postIdForMedia('m2');
  assert.deepEqual(value.filter(o => o.kind === 'count_board').map(o => [o.postId, o.status]), [[id1, 'approved'], [id2, 'approved']]);
  for (const [id, m] of [[id1, 'm1'], [id2, 'm2']]) {
    const row = post(s.sql, id);
    assert.deepEqual([row.kind, row.status, row.approved_by, row.scheduled_for, row.caption, row.collaborators_json, JSON.parse(row.targets_json)],
      ['story', 'approved', null, SLOT, '', null, ['instagram_story', 'facebook_story']], id);
    assert.equal(media(s.sql, m).publish_state, 'approved', 'public for Meta\'s fetch of its story.jpg');
    const review = s.sql.prepare('SELECT status,decided_by,note FROM advisor_reviews WHERE id=?').get(await reviewId('post', id, 'social_draft'));
    assert.deepEqual({...review}, {status: 'approved', decided_by: null, note: 'auto: story'});
  }
  for (const m of ['m-old', 'm3', 'm4', 'm5', 'm6', 'm7']) assert.equal(post(s.sql, await postIdForMedia(m)), undefined, m);
  // A rerun changes nothing.
  const again = await quiet(() => ST.morningStories(s.env, NOW + 15 * 60000, {feeds: feeds()}));
  assert.deepEqual(again.value.map(o => o.status), ['exists', 'exists', 'exists']);
});

dbTest('a has_person count board waits for its photo review; once approved it goes; an open review holds it as a draft', async () => {
  const s = setup();
  boat(s.sql, 'b1', 'Rita G'); boat(s.sql, 'b2', 'Patriot');
  board(s.sql, 'p1', 'b1', {hasPerson: 1});
  board(s.sql, 'p2', 'b2', {hasPerson: 1, state: 'approved'});
  s.sql.prepare("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','media','p1','has_person','open',?)").run(iso(NOW - HOUR));
  const {value} = await quiet(() => ST.morningStories(s.env, NOW, {feeds: feeds({fail: true})}));
  const id1 = await postIdForMedia('p1'), id2 = await postIdForMedia('p2');
  const byId = Object.fromEntries(value.filter(o => o.kind === 'count_board').map(o => [o.postId, o]));
  assert.equal(byId[id1].status, 'held');
  assert.match(byId[id1].reason, /waiting for its photo review/);
  assert.equal(post(s.sql, id1).status, 'draft', 'left for the team');
  assert.equal(media(s.sql, 'p1').publish_state, 'queued');
  assert.equal(byId[id2].status, 'approved', 'a person photo whose review approved it goes');
  assert.deepEqual(value.find(o => o.kind === 'conditions'), {region: 'morro-bay', kind: 'conditions', status: 'skipped', reason: 'no forecast'}, 'no forecast, no card');
});

dbTest('the conditions card: an approved Story with no photo and its story graphic (title, conditions, the word), once a day', async () => {
  const s = setup({...META, GITHUB_TOKEN: 't'});
  const dispatched = [];
  const {value} = await quiet(() => ST.morningStories(s.env, NOW, {feeds: feeds(), dispatch: async (_, f) => { dispatched.push(f); return 204; }}));
  const id = await ST.conditionsStoryId('morro-bay', '2026-09-28');
  assert.deepEqual(value, [{region: 'morro-bay', kind: 'conditions', status: 'approved', postId: id}]);
  const row = post(s.sql, id);
  assert.deepEqual([row.kind, row.status, row.media_json, row.caption, row.scheduled_for, row.approved_by, row.boat_id], ['story', 'approved', '[]', '', SLOT, null, null]);
  assert.equal(s.sql.prepare('SELECT COUNT(*) AS n FROM advisor_reviews WHERE ref_id=?').get(id).n, 0, 'nothing to review');
  const graphic = await graphicState(s.db, id);
  assert.deepEqual([graphic.kind, graphic.status, graphic.out_key], ['story', 'pending', `advisor/posts/${id}/story.jpg`]);
  assert.equal(graphic.data.title, 'Today out of Morro Bay & Avila');
  assert.match(graphic.data.lines[0], /^SMALL CRAFT ADVISORY posted for today\. Conditions: seas 7 ft/);
  assert.match(graphic.data.lines[1], /^Landing reports: (Insufficient|Low|Moderate)$/);
  assert.doesNotMatch(JSON.stringify(graphic.data), /%|probab|chance|odds/i);
  assert.deepEqual(dispatched, ['advisor-media.yml']);
  await quiet(() => ST.morningStories(s.env, NOW + HOUR, {feeds: feeds()}));
  assert.equal(s.sql.prepare("SELECT COUNT(*) AS n FROM advisor_posts WHERE kind='story'").get().n, 1, 'once a day');
});

dbTest('nothing while social publishing is off or Meta is not configured', async () => {
  for (const env of [{}, {ADVISOR_SOCIAL_ENABLED: 'true'}, {...META, ADVISOR_SOCIAL_ENABLED: 'false'}]) {
    const s = setup(env);
    boat(s.sql, 'b1', 'Rita G'); board(s.sql, 'm1', 'b1');
    assert.deepEqual(await ST.morningStories(s.env, NOW, {feeds: feeds()}), []);
    assert.equal(s.sql.prepare('SELECT COUNT(*) AS n FROM advisor_posts').get().n, 0);
  }
});

function graphFake() {
  const calls = [];
  let containers = 0;
  const json = body => new Response(JSON.stringify(body), {status: 200, headers: {'content-type': 'application/json'}});
  const fetcher = async (url, init = {}) => {
    const u = new URL(url), method = init.method ?? 'GET';
    const params = Object.fromEntries((method === 'POST' && typeof init.body === 'string' ? new URLSearchParams(init.body) : u.searchParams).entries());
    const path = u.pathname.replace(/^\/v\d+\.0/, '');
    calls.push({method, path, params});
    if (path === `/${IG}/content_publishing_limit`) return json({data: [{quota_usage: 1, config: {quota_total: 50}}]});
    if (method === 'POST' && path === `/${IG}/media`) return json({id: `1789000000000${100 + ++containers}`});
    if (path === `/${IG}/media_publish`) return json({id: `1789000000000${900 + containers}`});
    if (params.fields === 'status_code,status') return json({status_code: 'FINISHED', id: path.slice(1)});
    if (params.fields === 'permalink') return json({permalink: 'https://www.instagram.com/stories/PLACEHOLDER/'});
    if (path === `/${PAGE}/photos`) return json({id: '100000000000301'});
    if (path === `/${PAGE}/photo_stories`) return json({post_id: '100000000000701', success: true});
    return new Response(JSON.stringify({error: {code: 100}}), {status: 400});
  };
  return {fetcher, calls};
}

dbTest('the cron makes them at 07:00 and the next ticks publish them through the publisher: the count board\'s story.jpg, the card once rendered', async () => {
  const s = setup();
  boat(s.sql, 'b1', 'Rita G'); board(s.sql, 'm1', 'b1');
  const fake = graphFake();
  const slots = SLOTS.filter(x => x.name === 'morning-stories');
  const deps = {slots, daily: {feeds: feeds()}, consumer: {channelFor: () => ({name: 'test', send: async () => ({providerId: 'x', status: 'sent'})})},
    publish: {fetcher: fake.fetcher, sleep: async () => {}}};
  for (let tick = Date.parse('2026-09-28T13:45:00Z'); tick <= Date.parse('2026-09-28T14:15:00Z'); tick += 15 * 60000) {
    deps.publish.now = () => tick;
    assert.equal((await quiet(() => advisorCron(s.env, tick, deps))).value, 'ok', iso(tick));
  }
  assert.equal(s.sql.prepare('SELECT value FROM job_state WHERE key=?').get(`${SLOT_PREFIX}morning-stories`).value, '2026-09-28');
  const board1 = await postIdForMedia('m1'), card = await ST.conditionsStoryId('morro-bay', '2026-09-28');
  assert.equal(post(s.sql, board1).status, 'posted', 'published on the tick after the slot');
  const stories = fake.calls.filter(c => c.method === 'POST' && c.path === `/${IG}/media`);
  assert.deepEqual(stories.map(c => [c.params.media_type, c.params.image_url, c.params.caption]), [['STORIES', 'https://skippercast.com/media/m1.story.jpg', undefined]]);
  assert.equal(post(s.sql, card).status, 'approved', 'the card waits for its graphic');
  // The job renders the card; the next tick posts it.
  s.sql.prepare('UPDATE job_state SET value=? WHERE key=?').run(JSON.stringify({kind: 'story', data: {}, out_key: `advisor/posts/${card}/story.jpg`, status: 'done',
    keys: {public: `advisor/posts/${card}/story.jpg`}, width: 1080, height: 1920}), `advisor.graphic.${card}`);
  const tick = Date.parse('2026-09-28T14:30:00Z');
  deps.publish.now = () => tick;
  assert.equal((await quiet(() => advisorCron(s.env, tick, deps))).value, 'ok');
  assert.equal(post(s.sql, card).status, 'posted');
  const last = fake.calls.filter(c => c.method === 'POST' && c.path === `/${IG}/media`).at(-1);
  assert.deepEqual([last.params.media_type, last.params.image_url], ['STORIES', `https://skippercast.com/media/post/${card}/story.jpg`]);
  assert.equal(fake.calls.filter(c => c.path === `/${PAGE}/photos` && c.params.url === `https://skippercast.com/media/post/${card}/story.jpg`).length, 1, 'the Page photo Story from the same card');
  // Both sit in the Stories slot of the week grid.
  const week = await C.calendarWeek(s.db, '2026-09-28', tick);
  assert.deepEqual(week.days[0].slots.find(x => x.slot === 'stories').posts.map(p => p.id).sort(), [board1, card].sort());
});

test('09 § Instagram profile: the bio fits Instagram\'s 150 characters, links the text page with the ig source, and names the three highlights with their scripts', () => {
  const doc = readFileSync(new URL('../docs/plans/text-advisor/09-social.md', import.meta.url), 'utf8');
  const section = doc.slice(doc.indexOf('## Instagram profile (SP-1; TA-S5)'), doc.indexOf('## Content calendar (SP-6)'));
  assert.ok(section.length > 500, 'the section exists');
  const bio = /\*\*Bio\*\*[^\n]*\n\n> ([^\n]+)\n/.exec(section)?.[1];
  assert.ok(bio && Array.from(bio).length <= 150, bio);
  assert.match(section, /\*\*Link:\*\* `https:\/\/skippercast\.com\/text\?s=ig`/);
  for (const name of ['Reports', 'Fish ID', 'Tips']) assert.match(section, new RegExp(`\\*${name}\\* \\(\\d frames\\)`), name);
  assert.doesNotMatch(section, /%|probabilit|guarantee|hotspot/i, 'no odds or hotspot language');
});

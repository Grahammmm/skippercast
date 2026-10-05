// Text Advisor weekly retention prune (server/advisor/retention.ts, 02 § Retention
// and deletion): every rule seeded on both sides of its boundary in the in-memory
// D1 (tests/_advisor_d1.mjs) and an in-memory R2 with upload times, the bound per
// run, a rerun that changes nothing, a counts-only log line, a failing rule, and
// the `retention` slot (Sunday 09:00 UTC, also while the advisor is off).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

// cron.ts reaches the Worker config through the channel adapters, as in tests/test_advisor_cron.mjs.
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {runRetention, RETENTION_DAYS, KEEP_POST_STATUSES} = await import('../server/advisor/retention.ts');
const {advisorCron, SLOTS, RETENTION_SLOT, runSlot} = await import('../server/advisor/cron.ts');
const {approvalHold} = await import('../server/advisor/admin/posts.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const DAY = 86400000, MIN = 60000;
const NOW = Date.parse('2026-10-11T09:00:00Z');   // a Sunday, 09:00 UTC
const ago = (days, extraMs = 0) => new Date(NOW - days * DAY - extraMs).toISOString();
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };

/** R2 with list(prefix, cursor, limit) pages that carry `uploaded`, and delete; `fail` makes list throw for a prefix. */
function bucket(entries = {}) {
  const objects = new Map(Object.entries(entries).map(([k, uploaded]) => [k, uploaded === null ? null : new Date(uploaded)]));
  const deleted = [];
  return {
    objects, deleted, failList: null,
    async list({prefix = '', cursor, limit = 1000} = {}) {
      if (this.failList && prefix === this.failList) throw Error('R2 list failed');
      const all = [...objects.keys()].filter(k => k.startsWith(prefix)).sort(), start = cursor ? Number(cursor) : 0;
      const page = all.slice(start, start + limit), truncated = start + limit < all.length;
      return {objects: page.map(key => ({key, ...(objects.get(key) ? {uploaded: objects.get(key)} : {})})), truncated, cursor: truncated ? String(start + limit) : undefined};
    },
    async delete(keys) { for (const key of [].concat(keys)) { deleted.push(key); objects.delete(key); } },
  };
}

function seed() {
  const {sql, db} = advisorDatabase();
  const run = (q, ...a) => sql.prepare(q).run(...a);
  const contact = (id, {phone = true, ig = null, web = null, seen = ago(1)} = {}) =>
    run('INSERT INTO advisor_contacts(id,phone_hash,phone_enc,web_session,ig_sid,channel,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
      id, phone ? `hash-${id}` : null, phone ? `enc-${id}` : null, web, ig, web ? 'web' : ig ? 'instagram_dm' : 'sms', seen, ago(400), seen);
  const message = (id, contactId, created, body = 'what is biting') =>
    run("INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES(?,?,'in','sms',?,'done',?)", id, contactId, body, created);
  const media = (id, contactId, created, {key = `advisor/media/${contactId}/${id}.jpg`, state = 'private', derived = ago(1)} = {}) =>
    run("INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,publish_state,derived_at,created_at) VALUES(?,?,'image','image/jpeg',100,?,?,?,?,?)",
      id, contactId, key, `sha-${key}`, state, derived, created);
  const post = (id, status, mediaJson, kind = 'photo') =>
    run("INSERT INTO advisor_posts(id,kind,region,media_json,caption,targets_json,status,created_by,created_at,updated_at) VALUES(?,?,'morro-bay',?,'c','[\"instagram\"]',?,'engine',?,?)",
      id, kind, mediaJson, status, ago(100), ago(100));
  const state = (key, updated, value = '{}') => run('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)', key, value, updated);
  const boat = id => run("INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,created_at,updated_at) VALUES(?,?,?,'morro-bay','morro-bay','skipper',?,?)", id, id, `Boat ${id}`, ago(300), ago(300));

  contact('skipper'); contact('angler');
  contact('web-old', {phone: false, web: 'w-old', seen: ago(RETENTION_DAYS.contacts, MIN)});
  contact('web-new', {phone: false, web: 'w-new', seen: ago(RETENTION_DAYS.contacts - 1)});
  contact('phone-old', {seen: ago(200)});
  contact('ig-old', {phone: false, ig: '17841400000000001', seen: ago(200)});
  boat('boat-1');

  // Message bodies: 180 days.
  message('msg-old', 'angler', ago(RETENTION_DAYS.bodies, MIN));
  message('msg-new', 'angler', ago(RETENTION_DAYS.bodies - 1));
  message('msg-web-old', 'web-old', ago(100));

  // Media: 90 days unless referenced.
  media('m-old', 'angler', ago(RETENTION_DAYS.media, MIN));
  media('m-new', 'angler', ago(RETENTION_DAYS.media - 1));
  media('m-report', 'skipper', ago(120));
  media('m-report-draft', 'skipper', ago(120));
  media('m-posted', 'skipper', ago(120), {state: 'posted'});
  media('m-scheduled', 'skipper', ago(120), {state: 'queued'});
  media('m-draft-post', 'skipper', ago(120), {state: 'queued'});
  media('m-approved', 'skipper', ago(120), {state: 'approved'});
  media('m-dup-first', 'angler', ago(120), {key: 'advisor/media/angler/shared.jpg'});
  media('m-dup-second', 'angler', ago(10), {key: 'advisor/media/angler/shared.jpg'});
  media('m-web', 'web-old', ago(100));
  run("INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,publish_state,created_at) VALUES('m-rejected-file','angler','unknown','application/octet-stream',1,'','','rejected',?)", ago(200));
  run("INSERT INTO advisor_reports(id,boat_id,region,port,report_date,counts_json,source,media_id,status,created_at,updated_at) VALUES('r-pub','boat-1','morro-bay','morro-bay','2026-06-01','[]','count-board','m-report','published',?,?)", ago(120), ago(120));
  run("INSERT INTO advisor_reports(id,boat_id,region,port,report_date,counts_json,source,media_id,status,created_at,updated_at) VALUES('r-draft','boat-1','morro-bay','morro-bay','2026-06-02','[]','count-board','m-report-draft','withdrawn',?,?)", ago(120), ago(120));
  post('p-posted', 'posted', '["m-posted"]');
  post('p-scheduled', 'scheduled', '["m-scheduled"]');
  post('p-draft', 'draft', '["m-draft-post"]');
  post('p-broken', 'posted', 'not json');
  state('advisor.caption.m-old', ago(120), '{"line":"x","language":"en"}');
  state('advisor.caption.m-posted', ago(120), '{"line":"y","language":"en"}');

  // Reviews: 90 days after the decision; open ones stay.
  run("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at,decided_at) VALUES('rv-old','media','m-new','has_person','approved',?,?)", ago(200), ago(RETENTION_DAYS.reviews, MIN));
  run("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at,decided_at) VALUES('rv-new','media','m-new','has_person','rejected',?,?)", ago(200), ago(RETENTION_DAYS.reviews - 1));
  run("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES('rv-open','skipper','boat-1','new_skipper','open',?)", ago(300));

  // Daily answers: 30 days. Post stats: 2 years.
  run("INSERT INTO advisor_daily_answers(key,text_en,text_es,inputs_hash,generated_at) VALUES('morro-bay:2026-09-10','a','b','h',?)", ago(RETENTION_DAYS.daily, MIN));
  run("INSERT INTO advisor_daily_answers(key,text_en,text_es,inputs_hash,generated_at) VALUES('morro-bay:2026-09-12','a','b','h',?)", ago(RETENTION_DAYS.daily - 1));
  run("INSERT INTO advisor_post_stats(post_id,platform,day,raw_json,fetched_at) VALUES('p-posted','instagram',?,'{}',?)", ago(RETENTION_DAYS.stats + 1).slice(0, 10), ago(RETENTION_DAYS.stats + 1));
  run("INSERT INTO advisor_post_stats(post_id,platform,day,raw_json,fetched_at) VALUES('p-posted','facebook',?,'{}',?)", ago(RETENTION_DAYS.stats - 1).slice(0, 10), ago(RETENTION_DAYS.stats - 1));

  // job_state: 30 days for flows, link codes, share offers and crew invitations; once-markers and graphics by their rules.
  const old = ago(RETENTION_DAYS.jobState, MIN), recent = ago(1);
  state('advisor.flow.angler', old); state('advisor.flow.skipper', recent);
  state('advisor.link.web-new', old); state('advisor.share.angler', old); state('advisor.share.skipper', recent);
  // Hardening: crew invitations (72 h) and declines (30 days of silence) age out with the rest.
  state('advisor.crewinvite.angler', old); state('advisor.crewdecline.boat-1.angler', old); state('advisor.crewdecline.boat-1.skipper', recent);
  state('advisor.once.noconsent.boat-1', old);
  state('advisor.once.instagram.boat-1', old); state('advisor.once.autopub.boat-gone', old);
  state('advisor.once.homeport.angler', old); state('advisor.once.homeport.contact-gone', old);
  post('p-graphic-rejected', 'rejected', '[]', 'daily'); post('p-graphic-posted', 'posted', '[]', 'daily');
  state('advisor.graphic.p-graphic-rejected', old, '{"status":"done"}');
  state('advisor.graphic.p-graphic-posted', old, '{"status":"done"}');
  state('advisor.graphic.p-gone', old, '{"status":"done"}');
  state('advisor.graphic.p-gone-recent', recent, '{"status":"pending"}');
  state('advisor.relay', old, '{"state":"up"}'); state('advisor.slot.daily-answers', old, '2026-09-01');

  const r2 = bucket({
    'advisor/media/angler/m-old.jpg': ago(100), 'advisor/derived/m-old/public.jpg': ago(100), 'advisor/derived/m-old/thumb.jpg': ago(100),
    'advisor/media/angler/m-new.jpg': ago(80), 'advisor/media/skipper/m-report.jpg': ago(120), 'advisor/derived/m-report/public.jpg': ago(120),
    'advisor/media/skipper/m-report-draft.jpg': ago(120), 'advisor/media/skipper/m-posted.jpg': ago(120), 'advisor/derived/m-posted/public.jpg': ago(120),
    'advisor/media/skipper/m-scheduled.jpg': ago(120), 'advisor/media/skipper/m-draft-post.jpg': ago(120), 'advisor/derived/m-draft-post/story.jpg': ago(120),
    'advisor/media/skipper/m-approved.jpg': ago(120), 'advisor/media/angler/shared.jpg': ago(120), 'advisor/derived/m-dup-first/public.jpg': ago(120),
    'advisor/media/web-old/m-web.jpg': ago(100),
    'advisor/posts/p-graphic-rejected/daily.jpg': ago(40), 'advisor/posts/p-gone/daily.jpg': ago(40), 'advisor/posts/p-graphic-posted/daily.jpg': ago(40),
    'advisor/exports/angler/2026-10-02.json': ago(RETENTION_DAYS.exports, MIN), 'advisor/exports/angler/2026-10-05.json': ago(RETENTION_DAYS.exports - 1),
    'advisor/exports/skipper/2026-09-30.json': null,   // no upload time: the key's date decides
    'advisor/exports/skipper/2026-10-10.json': null,
  });
  return {sql, db, r2, env: {DB: db, ADVISOR_MEDIA: r2}};
}

const one = (sql, q, ...a) => sql.prepare(q).get(...a);
const count = (sql, q, ...a) => Object.values(sql.prepare(q).get(...a))[0];

dbTest('every rule in 02 § Retention and deletion, on both sides of its boundary', async () => {
  const {sql, r2, env} = seed();
  const {value: result} = await quiet(() => runRetention(env, NOW));

  // Message bodies: nulled after 180 days; the row stays for counts.
  assert.equal(one(sql, "SELECT body FROM advisor_messages WHERE id='msg-old'").body, null);
  assert.equal(one(sql, "SELECT body FROM advisor_messages WHERE id='msg-new'").body, 'what is biting');
  assert.equal(result.bodies, 1);

  // Media: unreferenced originals and their derived files deleted after 90 days; the row stays, marked.
  const m = id => one(sql, 'SELECT r2_key,derived_at,derived_error FROM advisor_media WHERE id=?', id);
  assert.deepEqual({...m('m-old')}, {r2_key: '', derived_at: null, derived_error: 'expired'});
  for (const k of ['advisor/media/angler/m-old.jpg', 'advisor/derived/m-old/public.jpg', 'advisor/derived/m-old/thumb.jpg']) assert.ok(!r2.objects.has(k), k);
  assert.equal(count(sql, "SELECT COUNT(*) FROM job_state WHERE key='advisor.caption.m-old'"), 0, 'the cached caption line goes with it');
  assert.equal(count(sql, "SELECT COUNT(*) FROM job_state WHERE key='advisor.caption.m-posted'"), 1);
  assert.equal(m('m-new').r2_key, 'advisor/media/angler/m-new.jpg', '89 days: kept');
  assert.ok(r2.objects.has('advisor/media/angler/m-new.jpg'));
  for (const id of ['m-report', 'm-posted', 'm-scheduled', 'm-approved']) assert.notEqual(m(id).r2_key, '', `${id} is referenced: kept`);
  assert.ok(r2.objects.has('advisor/derived/m-report/public.jpg') && r2.objects.has('advisor/derived/m-posted/public.jpg'), 'derived files of referenced media kept');
  for (const id of ['m-report-draft', 'm-draft-post']) assert.equal(m(id).r2_key, '', `${id}: a withdrawn report or a draft post does not keep it`);
  assert.ok(!r2.objects.has('advisor/derived/m-draft-post/story.jpg'));
  assert.deepEqual([...KEEP_POST_STATUSES], ['approved', 'scheduled', 'publishing', 'posted', 'partial']);
  // A duplicate shares the first row's object: the old row is cleared, the object stays for the young one.
  assert.equal(m('m-dup-first').r2_key, '');
  assert.equal(m('m-dup-second').r2_key, 'advisor/media/angler/shared.jpg');
  assert.ok(r2.objects.has('advisor/media/angler/shared.jpg'), 'the shared object stays while a kept row uses it');
  assert.ok(!r2.objects.has('advisor/derived/m-dup-first/public.jpg'));
  assert.equal(result.media, 4);
  // A draft post whose photo expired cannot be approved any more (admin/posts.ts approvalHold).
  const draft = one(sql, "SELECT id,kind,boat_id,media_json FROM advisor_posts WHERE id='p-draft'");
  assert.equal(await approvalHold(env.DB, draft), 'a photo of this post is no longer stored');

  // Reviews: 90 days after the decision; open reviews stay.
  assert.deepEqual(sql.prepare('SELECT id FROM advisor_reviews ORDER BY id').all().map(r => r.id), ['rv-new', 'rv-open']);
  // Daily answers 30 days; post stats 2 years.
  assert.deepEqual(sql.prepare('SELECT key FROM advisor_daily_answers').all().map(r => r.key), ['morro-bay:2026-09-12']);
  assert.deepEqual(sql.prepare('SELECT platform FROM advisor_post_stats').all().map(r => r.platform), ['facebook']);

  // Web-only contacts inactive 90 days: deleted through forgetContact (messages, media and R2 too).
  const contacts = sql.prepare('SELECT id FROM advisor_contacts ORDER BY id').all().map(r => r.id);
  assert.deepEqual(contacts, ['angler', 'ig-old', 'phone-old', 'skipper', 'web-new'], 'phone and Instagram contacts are never pruned for inactivity');
  assert.equal(count(sql, "SELECT COUNT(*) FROM advisor_messages WHERE contact_id='web-old'"), 0);
  assert.equal(count(sql, "SELECT COUNT(*) FROM advisor_media WHERE contact_id='web-old'"), 0);
  assert.ok(!r2.objects.has('advisor/media/web-old/m-web.jpg'));
  assert.equal(result.contacts, 1);

  // job_state: the advisor's expired keys.
  const keys = sql.prepare("SELECT key FROM job_state WHERE key NOT LIKE 'advisor.caption.%' ORDER BY key").all().map(r => r.key);
  assert.deepEqual(keys, ['advisor.crewdecline.boat-1.skipper', 'advisor.flow.skipper', 'advisor.graphic.p-gone-recent', 'advisor.graphic.p-graphic-posted', 'advisor.once.homeport.angler',
    'advisor.once.instagram.boat-1', 'advisor.relay', 'advisor.share.skipper', 'advisor.slot.daily-answers']);
  assert.ok(!r2.objects.has('advisor/posts/p-graphic-rejected/daily.jpg') && !r2.objects.has('advisor/posts/p-gone/daily.jpg'), 'graphic files of a rejected or deleted post go');
  assert.ok(r2.objects.has('advisor/posts/p-graphic-posted/daily.jpg'), 'a posted post keeps its graphic');
  assert.equal(result.graphicObjects, 2);

  // Exports older than 7 days (upload time, else the key's date).
  assert.deepEqual([...r2.objects.keys()].filter(k => k.startsWith('advisor/exports/')).sort(), ['advisor/exports/angler/2026-10-05.json', 'advisor/exports/skipper/2026-10-10.json']);
  assert.equal(result.exports, 2);
  assert.deepEqual(result.more, []); assert.deepEqual(result.failed, []);
});

dbTest('a second run changes nothing (idempotent)', async () => {
  const {sql, r2, env} = seed();
  await quiet(() => runRetention(env, NOW));
  const before = sql.prepare("SELECT (SELECT COUNT(*) FROM advisor_messages WHERE body IS NULL) a, (SELECT COUNT(*) FROM job_state) b, (SELECT COUNT(*) FROM advisor_media WHERE r2_key='') c").get();
  const objects = r2.objects.size;
  const {value: again} = await quiet(() => runRetention(env, NOW));
  assert.deepEqual({...again, more: [], failed: []}, {bodies: 0, media: 0, mediaObjects: 0, reviews: 0, daily: 0, stats: 0, contacts: 0, jobState: 0, graphicObjects: 0, exports: 0, more: [], failed: []});
  assert.deepEqual(sql.prepare("SELECT (SELECT COUNT(*) FROM advisor_messages WHERE body IS NULL) a, (SELECT COUNT(*) FROM job_state) b, (SELECT COUNT(*) FROM advisor_media WHERE r2_key='') c").get(), before);
  assert.equal(r2.objects.size, objects);
});

dbTest('each rule is bounded per run and the rest waits for the next run', async () => {
  const {sql, db} = advisorDatabase(), r2 = bucket();
  for (let i = 0; i < 5; i++) sql.prepare("INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES(?,'c','in','sms','x','done',?)").run(`m${i}`, ago(200));
  for (let i = 0; i < 3; i++) {
    sql.prepare("INSERT INTO advisor_media(id,contact_id,kind,mime,bytes,r2_key,sha256,publish_state,created_at) VALUES(?,'c','image','image/jpeg',1,?,?,'private',?)").run(`md${i}`, `advisor/media/c/md${i}.jpg`, `s${i}`, ago(100));
    r2.objects.set(`advisor/media/c/md${i}.jpg`, new Date(ago(100)));
  }
  const env = {DB: db, ADVISOR_MEDIA: r2}, deps = {limits: {bodies: 3, media: 2}, chunk: 2};
  const first = (await quiet(() => runRetention(env, NOW, deps))).value;
  assert.equal(first.bodies, 3); assert.equal(first.media, 2);
  assert.deepEqual(first.more.sort(), ['bodies', 'media']);
  assert.equal(count(sql, 'SELECT COUNT(*) FROM advisor_messages WHERE body IS NOT NULL'), 2);
  const second = (await quiet(() => runRetention(env, NOW + 7 * DAY, deps))).value;
  assert.equal(second.bodies, 2); assert.equal(second.media, 1); assert.deepEqual(second.more, []);
  assert.equal(count(sql, 'SELECT COUNT(*) FROM advisor_messages WHERE body IS NOT NULL'), 0);
  assert.equal(r2.objects.size, 0);
});

dbTest('the log line is counts only: no ids, keys, bodies or numbers from the rows', async () => {
  const {env} = seed();
  const {lines} = await quiet(() => runRetention(env, NOW));
  assert.equal(lines.length, 1);
  const line = JSON.parse(lines[0]);
  assert.equal(line.event, 'advisor_retention');
  for (const [k, v] of Object.entries(line)) if (!['level', 'event', 'scope', 'more'].includes(k)) assert.equal(typeof v, 'number', k);
  for (const leak of ['angler', 'web-old', 'm-old', 'what is biting', 'advisor/', 'hash-', 'p-gone']) assert.ok(!lines[0].includes(leak), leak);
});

dbTest('a failing rule is logged by name, the others still run, and the job throws so the slot retries', async () => {
  const {sql, r2, env} = seed();
  r2.failList = 'advisor/exports/';
  const {value, lines} = await quiet(() => runRetention(env, NOW).then(() => 'resolved', e => e.message));
  assert.equal(value, 'retention failed: exports');
  assert.equal(one(sql, "SELECT body FROM advisor_messages WHERE id='msg-old'").body, null, 'the other rules ran');
  assert.ok(lines.some(l => JSON.parse(l).event === 'advisor_retention_rule_failed' && JSON.parse(l).rule === 'exports'));
  assert.ok(!lines.join('\n').includes('advisor/exports/angler'), 'no keys in the failure line');
});

dbTest('without the R2 binding only the D1-only rules run (nothing that would orphan an object)', async () => {
  const {sql, db} = seed();
  const {value} = await quiet(() => runRetention({DB: db}, NOW));
  assert.equal(value.bodies, 1); assert.equal(value.reviews, 1);
  assert.equal(value.media, 0); assert.equal(value.contacts, 0); assert.equal(value.exports, 0);
  assert.equal(one(sql, "SELECT r2_key FROM advisor_media WHERE id='m-old'").r2_key, 'advisor/media/angler/m-old.jpg');
  assert.equal(count(sql, "SELECT COUNT(*) FROM job_state WHERE key='advisor.graphic.p-gone'"), 1, 'graphic files cannot be deleted, so the request stays');
  assert.equal(count(sql, "SELECT COUNT(*) FROM job_state WHERE key='advisor.flow.angler'"), 0);
});

test('the retention slot is weekly, Sunday 09:00 UTC (02), in the slot table', () => {
  assert.deepEqual(RETENTION_SLOT.time, {local: '09:00', tz: 'UTC', weekday: 'Sun'});
  assert.equal(RETENTION_SLOT.name, 'retention');
  assert.ok(SLOTS.includes(RETENTION_SLOT));
});

dbTest('the slot runs once on Sunday at 09:00 UTC, also while the advisor is switched off but deployed; a failure is a partial cron', async () => {
  const {sql, env} = seed();
  assert.equal(await runSlot(env, RETENTION_SLOT.name, RETENTION_SLOT.time, async () => {}, Date.parse('2026-10-11T08:45:00Z')), 'not-yet');
  assert.equal(await runSlot(env, RETENTION_SLOT.name, RETENTION_SLOT.time, async () => {}, Date.parse('2026-10-10T09:00:00Z')), 'not-today', 'Saturday');
  // Off and never deployed (no ADVISOR_MEDIA binding): nothing runs.
  assert.equal(await advisorCron({DB: env.DB}, NOW), 'disabled');
  assert.equal(one(sql, "SELECT body FROM advisor_messages WHERE id='msg-old'").body, 'what is biting');
  assert.equal(count(sql, "SELECT COUNT(*) FROM job_state WHERE key='advisor.slot.retention'"), 0);
  // Off but deployed (the bucket is bound): advisorCron still runs the prune.
  const {value: off} = await quiet(() => advisorCron(env, NOW));
  assert.equal(off, 'disabled');
  assert.equal(one(sql, "SELECT body FROM advisor_messages WHERE id='msg-old'").body, null);
  assert.equal(one(sql, "SELECT value FROM job_state WHERE key='advisor.slot.retention'").value, '2026-10-11');

  // On, with a failing rule: the slot fails and the cron reports partial; the claim is released for the next tick.
  const second = seed();
  second.r2.failList = 'advisor/exports/';
  const {value: on} = await quiet(() => advisorCron({...second.env, TEXT_ADVISOR_ENABLED: 'true'}, NOW, {slots: [RETENTION_SLOT]}));
  assert.equal(on, 'partial');
  assert.equal(second.sql.prepare("SELECT value FROM job_state WHERE key='advisor.slot.retention'").get(), undefined);
});

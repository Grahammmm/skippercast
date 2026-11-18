// F02-07 / SCA-575: a post that reached one surface (Instagram ok, Facebook failed) is really published, so the first
// successful surface time must be kept (posted_at), used by the insights and collaborator scans, and never reset by a
// retry; with no success there is no timestamp. Offline: real migrations in node:sqlite, recorded Graph responses.
//
// Controls (all pass; this file never asserts the defect is desired):
//   valid control     a partial post that carries its first-success time is selected by collectInsights and collabTick.
//   affected control  the same partial post with posted_at NULL (what publish() writes today) is not selected, and
//                     `contractGaps` reports it. The synthetic defective observation is detected too.
//   baseline receipt  the real publish() observation is printed as a diagnostic (gaps listed, not asserted), so the
//                     fixture stays green before and after the product fix.
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
const P = await import('../server/advisor/social/publish.ts');
const I = await import('../server/advisor/social/insights.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const fixture = name => read(`./fixtures/advisor/meta/${name}.json`);
const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {status, headers: {'content-type': 'application/json'}});
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}; console.log = console.warn = console.error = () => {}; try { return await fn(); } finally { Object.assign(console, saved); } };
const iso = ms => new Date(ms).toISOString();
const IG = '17841400000000000', PAGE = '100000000000001';
const T0 = Date.parse('2026-10-04T18:00:00Z'), HOUR = 3600000;

/** Recorded Graph API: Instagram publishes; the Page photo fails until `fb.ok`; insights/collaborators answer from fixtures. */
function graph(fb) {
  const fetcher = async (url, init = {}) => {
    const u = new URL(url), method = init.method ?? 'GET', path = u.pathname.replace(/^\/v\d+\.0/, '');
    const params = Object.fromEntries((method === 'POST' && typeof init.body === 'string' ? new URLSearchParams(init.body) : u.searchParams).entries());
    const key = `${method} ${path}`;
    if (key === `GET /${IG}/content_publishing_limit`) return jsonResponse(fixture('publishing-limit'));
    if (key === `POST /${IG}/media`) return jsonResponse({id: '17890000000000101'});
    if (key === `POST /${IG}/media_publish`) return jsonResponse(fixture('media-published'));
    if (method === 'GET' && params.fields === 'status_code,status') return jsonResponse({...fixture('container-finished'), id: path.slice(1)});
    if (method === 'GET' && params.fields === 'permalink') return jsonResponse(fixture('permalink'));
    if (method === 'GET' && path.endsWith('/collaborators')) return jsonResponse(fixture('collaborators'));
    if (method === 'GET' && path.endsWith('/insights')) return jsonResponse(fixture('insights-feed'));
    if (key === `POST /${PAGE}/photos`) return fb.ok ? jsonResponse(fixture('page-photo')) : jsonResponse(fixture('error-page-photo'), 400);
    return jsonResponse({error: {code: 100, message: 'unexpected call in test'}}, 400);
  };
  return {fetcher};
}

function setup(targets = ['instagram', 'facebook']) {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES('admin-user-1',?,'admin')").run(iso(T0));
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,status,last_seen_at,created_at,updated_at) VALUES('c1','h-c1','ENC-c1','imessage','skipper','en','b1','active',?,?,?)`).run(iso(T0), iso(T0), iso(T0));
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,instagram,owner_contact_id,status,consent_photos_at,consent_revoked_at,created_at,updated_at) VALUES('b1','sea-example','Sea Example','morro-bay','morro-bay','seaexample','c1','verified',?,NULL,?,?)`).run(iso(T0 - 2 * 86400000), iso(T0), iso(T0));
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,has_person,publish_state,derived_at,derived_error,created_at) VALUES('m1','c1','b1','image','image/jpeg',1000,'advisor/media/c1/m1.jpg','sha',1,0,'approved',?,NULL,?)`).run(iso(T0 - HOUR), iso(T0 - 2 * HOUR));
  sql.prepare(`INSERT INTO advisor_posts(id,kind,region,boat_id,media_json,caption,collaborators_json,targets_json,status,created_by,approved_by,approved_at,created_at,updated_at)
    VALUES('p1','photo','morro-bay','b1','["m1"]','Caption #skippercast','["seaexample"]',?, 'approved','engine','admin-user-1',?,?,?)`).run(JSON.stringify(targets), iso(T0 - HOUR), iso(T0 - 2 * HOUR), iso(T0 - HOUR));
  const env = {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_SOCIAL_ENABLED: 'true', DB: db, ADVISOR_MEDIA: memoryBucket(),
    META_APP_SECRET: 'app-secret-PLACEHOLDER', META_PAGE_TOKEN: 'EAAB-PLACEHOLDER-TOKEN', META_IG_USER_ID: IG, META_PAGE_ID: PAGE};
  return {sql, env};
}
const depsAt = (fb, clock) => ({now: () => clock.t, sleep: async ms => { clock.t += ms; }, fetcher: graph(fb).fetcher,
  consumer: {channelFor: () => ({name: 'bluebubbles', async send() { return {providerId: 'p', status: 'sent'}; }})}, dispatch: async () => 204});
const posted = s => s.sql.prepare('SELECT status,ig_media_id,fb_post_id,posted_at FROM advisor_posts WHERE id=?').get('p1');

/** What the real scans select for the stored post row (read-only against the in-memory copy). */
async function scans(s, now) {
  const fetcher = graph({ok: false}).fetcher, deps = {fetcher, sleep: async () => {}};
  const insights = await quiet(() => I.collectInsights(s.env, now, deps));
  const collab = await quiet(() => P.collabTick(s.env, now, deps));
  return {insights: insights.posts, collab: collab.read};
}

/**
 * The contract, over one observation. `partial`: Instagram ok, Facebook failed. `retry`: the same post after Facebook later
 * succeeds. `failed`: no surface succeeded. `scan`: how many partial posts the insights / collaborator scans selected.
 */
function contractGaps({partial, retry, failed, scan}) {
  const gaps = [];
  if (!partial.postedAt) gaps.push('partial post has no first-success timestamp');
  if (partial.postedAt && retry.postedAt !== partial.postedAt) gaps.push('retry reset the first-success timestamp');
  if (failed.postedAt) gaps.push('a post with no success has a timestamp');
  if (scan.insights !== 1) gaps.push('insights scan does not select the partial post');
  if (scan.collab !== 1) gaps.push('collaborator scan does not select the partial post');
  return gaps;
}

// A synthetic model of the contract's valid outcome (an offline stand-in, not product code).
const FIRST = iso(T0), LATER = iso(T0 + 3 * HOUR);
const compliant = {partial: {postedAt: FIRST}, retry: {postedAt: FIRST}, failed: {postedAt: null}, scan: {insights: 1, collab: 1}};
const defective = {partial: {postedAt: null}, retry: {postedAt: LATER}, failed: {postedAt: null}, scan: {insights: 0, collab: 0}};

test('F02-07 contract: the compliant model has no gaps; the defective model reports each one', () => {
  assert.deepEqual(contractGaps(compliant), []);
  assert.deepEqual(contractGaps(defective), ['partial post has no first-success timestamp', 'insights scan does not select the partial post', 'collaborator scan does not select the partial post']);
  assert.deepEqual(contractGaps({...compliant, retry: {postedAt: LATER}}), ['retry reset the first-success timestamp']);
  assert.deepEqual(contractGaps({...compliant, failed: {postedAt: FIRST}}), ['a post with no success has a timestamp']);
});

dbTest('valid control: an Instagram-only partial post that carries its first-success time is selected by both scans', async () => {
  const s = setup(), clock = {t: T0};
  const first = await quiet(() => P.publish(s.env, 'p1', depsAt({ok: false}, clock)));
  assert.equal(first.outcome, 'partial');
  assert.equal(posted(s).fb_post_id, null);
  s.sql.prepare('UPDATE advisor_posts SET posted_at=? WHERE id=?').run(FIRST, 'p1');   // the contract's state, seeded
  const scan = await scans(s, T0 + HOUR);
  assert.deepEqual(scan, {insights: 1, collab: 1});
});

dbTest('affected control: the same partial post with posted_at NULL is skipped by both scans (the gap is detected)', async () => {
  const s = setup(), clock = {t: T0};
  await quiet(() => P.publish(s.env, 'p1', depsAt({ok: false}, clock)));
  s.sql.prepare('UPDATE advisor_posts SET posted_at=NULL WHERE id=?').run('p1');
  const scan = await scans(s, T0 + HOUR);
  assert.deepEqual(scan, {insights: 0, collab: 0});
  assert.deepEqual(contractGaps({...compliant, partial: {postedAt: null}, scan}), ['partial post has no first-success timestamp', 'insights scan does not select the partial post', 'collaborator scan does not select the partial post']);
});

dbTest('no success means no timestamp: both surfaces failing leaves posted_at NULL', async () => {
  const s = setup(), clock = {t: T0}, bad = depsAt({ok: false}, clock);
  const fetcher = bad.fetcher;
  bad.fetcher = async (url, init) => new URL(url).pathname.endsWith('/media') && init?.method === 'POST' ? jsonResponse(fixture('container-error'), 400) : fetcher(url, init);
  const out = await quiet(() => P.publish(s.env, 'p1', bad));
  assert.equal(out.outcome, 'failed');
  assert.equal(posted(s).posted_at, null);
});

dbTest('baseline receipt: the real publish() observation against the contract (diagnostic; not asserted)', async t => {
  const s = setup(), clock = {t: T0};
  const first = await quiet(() => P.publish(s.env, 'p1', depsAt({ok: false}, clock)));
  assert.equal(first.outcome, 'partial');
  const partial = {postedAt: posted(s).posted_at};
  const scan = await scans(s, T0 + HOUR);
  clock.t = T0 + 3 * HOUR;
  const second = await quiet(() => P.publish(s.env, 'p1', depsAt({ok: true}, clock), {retry: true}));
  const retry = {postedAt: posted(s).posted_at};
  const f = setup(), fclock = {t: T0}, bad = depsAt({ok: false}, fclock), inner = bad.fetcher;
  bad.fetcher = async (url, init) => new URL(url).pathname.endsWith('/media') && init?.method === 'POST' ? jsonResponse(fixture('container-error'), 400) : inner(url, init);
  await quiet(() => P.publish(f.env, 'p1', bad));
  const failed = {postedAt: posted(f).posted_at};
  const observation = {partial, retry, failed, scan};
  t.diagnostic(`outcomes partial=${first.outcome} retry=${second.outcome}; observation=${JSON.stringify(observation)}; gaps=${JSON.stringify(contractGaps(observation))}`);
  assert.equal(second.outcome, 'posted');
  assert.equal(failed.postedAt, null, 'no success, no timestamp holds in the real code');
});

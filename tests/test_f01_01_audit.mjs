// F01-01 (SCA-539): a moderation decision and its side effects must agree.
// decideReview() applies a post's effects (admin/posts.ts decidePost) and only
// then closes the review with a conditional UPDATE (admin/decisions.ts), so
// opposite decisions can both act before one loses, and an interruption between
// the post change and the close leaves an approved post under a review that
// stays open (a retry stops at decidePost's draft-only check).
//
// Offline fixture, three parts:
//   1. one invariant checker over (review, post, media, audit lines);
//   2. a valid control, a small model that persists ONE winning intent before
//      any effect and resumes it idempotently: it must satisfy the invariants
//      for every interleaving and every interruption point;
//   3. a negative control (synthetic bad states the checker must flag), and a
//      read-only baseline of the CURRENT code under the same scenarios. The
//      baseline is a receipt: it is reported as test diagnostics, never
//      asserted as desired or required behaviour, so this file passes whether
//      or not the gap is present at the tested head.
// Real migrations in node:sqlite; synthetic rows only; no sends, jobs or posts.
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
const {decideReview} = await import('../server/advisor/admin/decisions.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const iso = ms => new Date(ms).toISOString();
const T0 = Date.parse('2026-10-04T18:00:00Z');
const REVIEW = 'b' + 'p1'.replace(/[^0-9a-f]/g, '').padEnd(31, '0');
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}; console.log = console.warn = console.error = () => {}; try { return await fn(); } finally { Object.assign(console, saved); } };

/** What every decision outcome must satisfy. `state` = {review, post, media, audits}. */
export function violations({review, post, media, audits}) {
  const out = [];
  const wanted = {approved: 'approved', edited: 'approved', rejected: 'rejected'}[review.status];
  if (post.status === 'approved' && review.status === 'open') out.push('approved post under an open review');
  if (post.status === 'rejected' && review.status === 'open') out.push('rejected post under an open review');
  if (wanted && post.status !== wanted) out.push(`review ${review.status} but post ${post.status}`);
  if (post.status === 'rejected' && media.publish_state === 'approved') out.push('rejected post published its photo');
  if (post.status === 'approved' && media.publish_state !== 'approved') out.push('approved post without its photo approved');
  if (review.status !== 'open' && audits.length !== 1) out.push(`${audits.length} audit results for a closed review`);
  if (review.status === 'open' && audits.length) out.push('audit result for an open review');
  if (audits.length === 1 && wanted && audits[0] !== wanted) out.push(`audit says ${audits[0]}, post is ${post.status}`);
  return out;
}

// ---- valid control: persist the winning intent first, then resume it idempotently ----
const STAGES = ['intent', 'post', 'media', 'close'];
function model() {
  const s = {intent: null, post: 'draft', media: 'queued', review: 'open', audits: [], effects: []};
  const interrupted = new Error('interrupted');
  /** Run (or resume) a decision; `stopAfter` interrupts once that stage has completed. */
  function decide(decision, stopAfter) {
    s.intent ??= decision;                       // first writer wins; later decisions adopt the stored intent
    const win = s.intent;
    const stop = stage => { if (stage === stopAfter) throw interrupted; };
    stop('intent');
    if (s.post === 'draft') { s.post = win === 'reject' ? 'rejected' : 'approved'; s.effects.push(`post:${win}`); }
    stop('post');
    if (win !== 'reject' && s.media !== 'approved') { s.media = 'approved'; s.effects.push('media:approved'); }
    stop('media');
    if (s.review === 'open') { s.review = win === 'reject' ? 'rejected' : 'approved'; s.audits.push(s.review); }
    stop('close');
    return s.review;
  }
  const view = () => ({review: {status: s.review}, post: {status: s.post}, media: {publish_state: s.media}, audits: [...s.audits]});
  return {s, decide, view, interrupted};
}

test('F01-01 valid control: one persisted intent, resumed idempotently, passes every interleaving and interruption', () => {
  for (const [a, b] of [['approve', 'reject'], ['reject', 'approve'], ['approve', 'approve']]) {
    for (const stage of [undefined, ...STAGES]) {
      const m = model();
      try { m.decide(a, stage); } catch (e) { if (e !== m.interrupted) throw e; }
      m.decide(b);                   // the competing / retried request
      m.decide(a);                   // and a repeat of the first one
      assert.deepEqual(violations(m.view()), [], `${a}/${b} interrupted after ${stage}`);
      assert.equal(m.s.intent, a, 'the first persisted intent wins');
      assert.equal(m.s.audits.length, 1);
      if (a === 'reject') assert.deepEqual(m.s.effects, ['post:reject'], 'a losing decision has no effects');
    }
  }
});

// ---- negative control: the stated gap, synthesised ----
test('F01-01 negative control: the checker flags the stated gaps', () => {
  const ok = {review: {status: 'approved'}, post: {status: 'approved'}, media: {publish_state: 'approved'}, audits: ['approved']};
  assert.deepEqual(violations(ok), []);
  // interruption after the post changed, before the review closed
  assert.deepEqual(violations({...ok, review: {status: 'open'}, audits: []}), ['approved post under an open review']);
  // the loser acted before it lost: review says approved, post rejected, photo published
  assert.deepEqual(violations({...ok, post: {status: 'rejected'}}),
    ['review approved but post rejected', 'rejected post published its photo']);
  assert.ok(violations({...ok, audits: ['rejected']}).includes('audit says rejected, post is approved'));
  // two audit results for one review
  assert.ok(violations({...ok, audits: ['approved', 'rejected']}).includes('2 audit results for a closed review'));
});

// ---- baseline: the CURRENT decideReview, read-only observations (receipt, not assertions of the gap) ----
function setup() {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,role,language,boat_id,status,last_seen_at,created_at,updated_at) VALUES('c1','h-c1','ENC-c1','imessage','skipper','en','b1','active',?,?,?)`).run(iso(T0), iso(T0), iso(T0));
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,instagram,owner_contact_id,status,consent_photos_at,created_at,updated_at) VALUES('b1','sea-example','Sea Example','morro-bay','morro-bay','seaexample','c1','verified',?,?,?)`).run(iso(T0 - 172800000), iso(T0), iso(T0));
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,has_person,publish_state,created_at) VALUES('m1','c1','b1','image','image/jpeg',1000,'advisor/media/c1/m1.jpg','sha',1,0,'queued',?)`).run(iso(T0));
  sql.prepare(`INSERT INTO advisor_posts(id,kind,region,boat_id,media_json,caption,targets_json,status,created_by,created_at,updated_at) VALUES('p1','photo','morro-bay','b1','["m1"]','Synthetic','["instagram"]','draft','engine',?,?)`).run(iso(T0), iso(T0));
  sql.prepare("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,'post','p1','social_draft','open',?)").run(REVIEW, iso(T0));
  const lines = [];
  const env = {TEXT_ADVISOR_ENABLED: 'true', DB: db, ADVISOR_MEDIA: memoryBucket()};
  return {sql, db, env, lines};
}
const observe = sql => ({
  review: {...sql.prepare('SELECT status FROM advisor_reviews WHERE id=?').get(REVIEW)},
  post: {...sql.prepare("SELECT status FROM advisor_posts WHERE id='p1'").get()},
  media: {...sql.prepare("SELECT publish_state FROM advisor_media WHERE id='m1'").get()},
});
const decide = (env, decision, lines, db = env.DB) => decideReview({...env, DB: db}, {reviewId: REVIEW, decision, by: 'admin-user-1', inId: 'x', key: 'admin'},
  {now: T0, send: async () => { lines.push('send'); return 0; }, dispatch: async () => 204});
/** The decision's audit lines: advisor_review_decided is logged once per applied close. */
async function audited(lines, fn) {
  const saved = console.log, log = []; console.log = (...a) => log.push(a.join(' '));
  try { return await fn(); } finally { console.log = saved; lines.push(...log.filter(l => l.includes('advisor_review_decided'))); }
}
const auditsOf = (lines, sql) => {
  const status = sql.prepare('SELECT status FROM advisor_reviews WHERE id=?').get(REVIEW).status;
  return lines.filter(l => l.includes('advisor_review_decided')).map(() => status);
};

dbTest('F01-01 baseline: a lone decision on a valid draft satisfies the invariants (positive control on the real code)', async () => {
  for (const decision of ['approve', 'reject']) {
    const {sql, env} = setup(), lines = [];
    const outcome = await audited(lines, () => decide(env, decision, []));
    assert.equal(outcome.status, 'applied');
    assert.deepEqual(violations({...observe(sql), audits: auditsOf(lines, sql)}), [], decision);
  }
});

dbTest('F01-01 baseline receipt: opposite decisions interleaved on the current code', async t => {
  for (const order of [['approve', 'reject'], ['reject', 'approve']]) {
    const {sql, env} = setup(), lines = [];
    const results = await audited(lines, () => Promise.all(order.map(d => decide(env, d, []))));
    const v = violations({...observe(sql), audits: auditsOf(lines, sql)});
    t.diagnostic(`interleave ${order.join('+')}: statuses=${results.map(r => r.status).join(',')} state=${JSON.stringify(observe(sql))} audits=${auditsOf(lines, sql).length} violations=${JSON.stringify(v)}`);
    assert.ok(Array.isArray(v));
  }
});

dbTest('F01-01 baseline receipt: interruption before the review closes, then a retry, on the current code', async t => {
  for (const decision of ['approve', 'reject']) {
    const {sql, db, env} = setup(), lines = [];
    // Interrupt exactly when the review's closing UPDATE is prepared, i.e. after the post's effects.
    const cut = {prepare: q => { if (/^UPDATE advisor_reviews SET status=/.test(q)) throw new Error('interrupted before close'); return db.prepare(q); }, batch: qs => db.batch(qs)};
    await audited(lines, () => quiet(() => decide(env, decision, [], cut)).catch(e => assert.match(e.message, /interrupted before close/)));
    const retry = await audited(lines, () => decide(env, decision, []));
    const v = violations({...observe(sql), audits: auditsOf(lines, sql)});
    t.diagnostic(`interrupt ${decision}: retry=${retry.status}${retry.error ? ` (${retry.error})` : ''} state=${JSON.stringify(observe(sql))} violations=${JSON.stringify(v)}`);
    assert.ok(Array.isArray(v));
  }
});

// F01-01: only one decision may take effect; a lost acknowledgement at any
// boundary must not strand a post review or create/lose an audit result.
// Real migrations, in-memory SQLite, no users, network, jobs, or publication.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

Object.assign(globalThis, {REGIONS: {}, DEPLOYMENT: {}, SHELLS: {}, BUILD_ID: 'synthetic'});
const {decideReview} = await import('../server/advisor/admin/decisions.ts');
const {teamSender} = await import('../server/advisor/consumer.ts');
const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, async () => {
  const {fetch} = globalThis, {log} = console;
  globalThis.fetch = forbidden;
  console.log = () => {};
  try { await fn(); } finally { globalThis.fetch = fetch; console.log = log; }
});
const forbidden = async () => { throw new Error('unexpected real effect'); };
const T0 = Date.parse('2026-10-04T18:00:00Z');
const at = new Date(T0).toISOString();
const REVIEW = 'a'.repeat(32);
const decided = {approve: 'approved', edit: 'edited', reject: 'rejected'};
const cut = new Error('synthetic interruption');

function violations({review, post, media, audit}) {
  const wanted = {approved: 'approved', edited: 'approved', rejected: 'rejected'}[review];
  const out = [];
  if (review === 'open' && post !== 'draft') out.push(`${post} post under an open review`);
  if (wanted && post !== wanted) out.push(`review ${review} but post ${post}`);
  if (post === 'rejected' && media === 'approved') out.push('rejected post published its photo');
  if (post === 'approved' && media !== 'approved') out.push('approved post without its photo approved');
  if (audit.length !== (review === 'open' ? 0 : 1)) out.push('wrong audit result count');
  if (audit.length === 1 && audit[0] !== review) out.push('wrong audit decision');
  return out;
}

test('F01-01 control: mismatched, missing or duplicate audit results and partial effects all fail', () => {
  const ok = {review: 'approved', post: 'approved', media: 'approved', audit: ['approved']};
  assert.deepEqual(violations(ok), []);
  assert.deepEqual(violations({...ok, review: 'open', audit: []}), ['approved post under an open review']);
  assert.deepEqual(violations({...ok, post: 'rejected'}), ['review approved but post rejected', 'rejected post published its photo']);
  assert.deepEqual(violations({...ok, review: 'edited'}), ['wrong audit decision']);
  for (const audit of [[], ['approved', 'rejected']]) assert.deepEqual(violations({...ok, audit}), ['wrong audit result count']);
});

function setup(kind = 'post') {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO advisor_contacts(id,channel,web_session,role,language,status,last_seen_at,created_at,updated_at) VALUES('c1','web','fixture-session','angler','en','active',?,?,?)").run(at, at, at);
  if (kind !== 'conversation' && kind !== 'rule') {
    sql.prepare("INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,status,consent_photos_at,created_at,updated_at) VALUES('b1','fixture-boat','Fixture Boat','fixture','fixture','c1','verified',?,?,?)").run(at, at, at);
    sql.prepare("INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,has_person,publish_state,created_at) VALUES('m1','c1','b1','image','image/jpeg',1000,'advisor/media/c1/m1.jpg','fixture-hash',1,0,'queued',?)").run(at);
    sql.prepare(`INSERT INTO advisor_posts(id,kind,region,boat_id,media_json,caption,targets_json,status,created_by,created_at,updated_at) VALUES('p1','photo','fixture','b1','["m1"]','Original','["instagram"]','draft','engine',?,?)`).run(at, at);
  }
  const [ref, reason] = {post: ['p1', 'social_draft'], media: ['m1', 'has_person'], conversation: ['c1', 'refused'], rule: ['fixture', 'rule_source_changed']}[kind];
  sql.prepare("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,?,?,?,'open',?)").run(REVIEW, kind, ref, reason, at);
  const env = {DB: db};
  const invoke = (decision, input = {}, deps = {}, handle = db) => decideReview({...env, DB: handle}, {reviewId: REVIEW, decision, by: null, inId: REVIEW, key: 'fixture', ...input},
    {now: T0, send: forbidden, dispatch: forbidden, fetcher: forbidden, ...deps});
  const audit = () => sql.prepare('SELECT id,kind,decision,actor,decided_at FROM advisor_review_events WHERE review_id=? AND decided_at IS NOT NULL').all(REVIEW).map(row => ({...row}));
  const status = () => sql.prepare('SELECT status FROM advisor_reviews WHERE id=?').get(REVIEW).status;
  const post = () => sql.prepare("SELECT status,caption FROM advisor_posts WHERE id='p1'").get();
  const media = () => sql.prepare("SELECT publish_state FROM advisor_media WHERE id='m1'").get().publish_state;
  const pages = () => sql.prepare("SELECT value FROM job_state WHERE key='advisor.pages.version'").get()?.value;
  const view = () => ({review: status(), post: post().status, media: media(), audit: audit().map(a => a.decision)});
  return {sql, db, env, invoke, audit, status, post, media, pages, view};
}

// Both requests read the same open review and draft. Pause the eventual loser
// at the database boundary, not in the fake domain logic.
dbTest('F01-01 opposite post decisions: winner alone changes caption, media, cache, review and audit', async () => {
  for (const [winner, loser] of [['reject', 'approve'], ['approve', 'reject'], ['edit', 'reject']]) {
    const s = setup();
    const reached = Promise.withResolvers(), release = Promise.withResolvers();
    const late = {...s.db, async batch(qs) { reached.resolve(); await release.promise; return s.db.batch(qs); }};
    const stale = s.invoke(loser, {}, {}, late);
    try {
      await Promise.race([reached.promise, stale.then(r => assert.fail(`loser never reached write: ${r.status}`))]);
      assert.equal((await s.invoke(winner, {patch: winner === 'edit' ? {caption: 'Edited'} : null})).status, 'applied');
    } finally { release.resolve(); }
    assert.equal((await stale).status, 'repeated');
    assert.equal(s.status(), decided[winner]);
    assert.equal(s.post().caption, winner === 'edit' ? 'Edited' : 'Original');
    assert.equal(s.pages(), winner === 'reject' ? undefined : '1');
    assert.deepEqual(violations(s.view()), []);
    s.sql.close();
  }
});

dbTest('F01-01 interruption inside every post-decision write rolls back; lost commit acknowledgement resumes the winner', async () => {
  for (const decision of ['approve', 'reject']) {
    const s = setup();
    const untouched = s.view();
    let steps = 0;
    // Stop in each write, including intent/audit, review close, post, media and
    // cache (some don't exist for reject). The real adapter rolls back the batch.
    for (let i = 0; ; i++) {
      const broken = {...s.db, batch(qs) {
        steps = qs.length;
        return s.db.batch(qs.map((q, n) => ({async run() {
          const result = await q.run();
          if (i === n) throw cut;
          return result;
        }})));
      }};
      await assert.rejects(s.invoke(decision, {}, {}, broken), e => e === cut);
      assert.deepEqual(s.view(), untouched, `interruption after statement ${i}`);
      assert.equal(s.pages(), undefined);
      if (i === steps - 1) break;
    }
    const lostAck = {...s.db, async batch(qs) { await s.db.batch(qs); throw cut; }};
    await assert.rejects(s.invoke(decision, {}, {}, lostAck), e => e === cut);
    const audit = s.audit();
    assert.equal(s.status(), decided[decision]);
    assert.deepEqual(violations(s.view()), []);
    assert.equal((await s.invoke(decision === 'approve' ? 'reject' : 'approve')).status, 'repeated');
    assert.equal((await s.invoke(decision)).status, 'repeated');
    assert.deepEqual(s.audit(), audit, 'same stable event ID even after lost commit acknowledgement');
    assert.equal(s.pages(), decision === 'approve' ? '1' : undefined);
    s.sql.close();
  }
});

dbTest('F01-01 consent revoked between validation and commit leaves every decision write untouched', async () => {
  const s = setup();
  const revoked = {...s.db, batch(qs) {
    s.sql.prepare("UPDATE advisor_boats SET consent_revoked_at=? WHERE id='b1'").run(at);
    return s.db.batch(qs);
  }};
  const initial = s.view();
  assert.equal((await s.invoke('approve', {}, {}, revoked)).status, 'conflict');
  assert.deepEqual(s.view(), initial);
  assert.equal(s.pages(), undefined);
  assert.equal((await s.invoke('reject')).status, 'applied', 'a held approval must not reserve a winning decision');
  assert.deepEqual(violations(s.view()), []);
  s.sql.close();
});

dbTest('F01-01 audit is independent of lost console telemetry; deleting a review removes its audit', async () => {
  for (const accepts of [false, true]) {
    const s = setup('rule'), telemetry = [];
    console.log = line => {
      if (accepts) telemetry.push(JSON.parse(line));
      throw cut;
    };
    await assert.rejects(s.invoke('approve'), e => e === cut);
    const audit = s.audit();
    assert.equal(audit.length, 1);
    assert.deepEqual({kind: audit[0].kind, actor: audit[0].actor, decision: audit[0].decision, at: audit[0].decided_at},
      {kind: 'rule', actor: 'text', decision: 'approved', at});
    assert.equal((await s.invoke('approve')).status, 'repeated');
    assert.deepEqual(s.audit(), audit);
    assert.deepEqual(telemetry.map(({kind, decision, by, sends}) => ({kind, decision, by, sends})), accepts ? [{kind: 'rule', decision: 'approved', by: 'text', sends: 0}] : []);
    s.sql.prepare('DELETE FROM advisor_reviews WHERE id=?').run(REVIEW);
    assert.deepEqual(s.audit(), [], 'foreign key keeps the review’s retention boundary');
    s.sql.close();
  }
});

function cutWrite(db, pattern, afterWrite) {
  return {...db, prepare(q) {
    const stmt = db.prepare(q);
    if (!pattern.test(q)) return stmt;
    return {bind(...args) { stmt.bind(...args); return this; }, async run() {
      if (afterWrite) await stmt.run();
      throw cut;
    }};
  }};
}

dbTest('F01-01 the winning reply survives interruption and cannot be replaced by reject or another reply', async () => {
  for (const stage of ['before intent', 'after intent', 'before send acknowledgement', 'after send acknowledgement']) {
    const s = setup('conversation'), delivered = [];
    const reply = {reply: 'Synthetic reply'};
    const run = (decision, input = {}, db = s.db) => s.invoke(decision, input, {send: teamSender({DB: db}, {
      channelFor: () => ({name: 'web', send: async m => { delivered.push(m.id); return {providerId: null, status: 'sent'}; }}),
      now: () => T0,
    })}, db);
    const intent = stage.endsWith('intent');
    const fail = cutWrite(s.db, intent ? /^INSERT INTO advisor_review_events/ : /^UPDATE advisor_messages SET status=\?,provider_id=/,
      stage.startsWith('after'));
    await assert.rejects(run('approve', reply, fail), e => e === cut);
    assert.equal(s.status(), 'open');
    assert.deepEqual(s.audit(), []);
    if (stage === 'before intent') {
      assert.equal((await run('reject')).status, 'applied');
      assert.equal((await run('approve', reply)).status, 'repeated');
      assert.deepEqual(delivered, []);
      assert.deepEqual(s.audit().map(a => a.decision), ['rejected']);
    } else {
      assert.equal((await run('reject')).status, 'conflict');
      assert.equal((await run('approve', {reply: 'Another reply'})).status, 'conflict');
      const persisted = s.sql.prepare('SELECT id, intent FROM advisor_review_events WHERE decided_at IS NULL').get();
      assert.match(persisted.intent, /^[a-f0-9]{64}$/);
      assert.equal((await run('approve', reply)).status, 'applied');
      assert.equal((await run('approve', reply)).status, 'repeated');
      assert.equal(delivered.length, 1);
      assert.deepEqual(s.audit().map(a => [a.id, a.decision]), [[persisted.id, 'approved']]);
      assert.equal(s.sql.prepare('SELECT intent FROM advisor_review_events WHERE id=?').get(persisted.id).intent, null);
    }
    s.sql.close();
  }
});

dbTest('F01-01 lost acknowledgement after the winner’s job nudge cannot repeat it or its database effects', async () => {
  const s = setup(), dispatches = [];
  const run = (decision, db = s.db) => decideReview({DB: db, GITHUB_TOKEN: 'synthetic'}, {
    reviewId: REVIEW, decision, by: null, inId: REVIEW, key: 'fixture',
  }, {now: T0, send: forbidden, fetcher: forbidden, dispatch: async (_env, file) => { dispatches.push(file); return 204; }});
  const lost = cutWrite(s.db, /^UPDATE advisor_review_events SET followup=NULL,intent=NULL WHERE id=/, false);
  await assert.rejects(run('approve', lost), e => e === cut);
  assert.deepEqual(violations(s.view()), []);
  assert.equal((await run('reject')).status, 'repeated');
  assert.equal((await run('approve')).status, 'repeated');
  assert.deepEqual(dispatches, ['advisor-media.yml']);
  assert.equal(s.pages(), '1');
  assert.deepEqual(violations(s.view()), []);
  s.sql.close();
});

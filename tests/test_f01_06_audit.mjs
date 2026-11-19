// SCA-574 / F01-06. Default: qualify the desired contract against a fixture-only
// reference. Opt-in: `node tests/test_f01_06_audit.mjs --baseline` runs the same
// observations against the unchanged production readers and exits 1 on a gap.
// These are D1 statement counts, not timing, SQL query plans, or fleet size.
import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase} from './_advisor_d1.mjs';

const baseline = process.argv.includes('--baseline');
const AT = '2026-10-03T18:00:00.000Z', NOW = Date.parse(AT);
const PAGE = 500, MANY = 12;
const boatId = i => `boat-${String(i).padStart(3, '0')}`;
const reviewId = i => i.toString(16).padStart(32, '0');
const NOTE = 'fixture-only consent note', REPORT = 'fixture-only report notes', CAPTION = 'fixture-only draft caption';
const noteKey = id => `advisor.boat-note.${id}`;
Object.assign(globalThis, {REGIONS: {}, DEPLOYMENT: {allowed_origins: []}, fetch: () => assert.fail('offline fixture must not fetch')});
const {listBoats, boatView} = await import('../server/advisor/admin/skippers.ts');
const {listReviews, reviewDetail} = await import('../server/advisor/admin/queue.ts');
const {listPosts, postDetail, preparePostDecision} = await import('../server/advisor/admin/posts.ts');
const {requireAdmin} = await import('../server/middleware/admin.ts');

function fixture(t, boats, cards = 0) {
  const {sql, db} = advisorDatabase();
  t.after(() => sql.close());
  const seed = (query, ...args) => sql.prepare(query).run(...args);
  // Only an opaque display projection for the crew join. No account, user or
  // contact records, addresses, messages, or real object keys are seeded.
  sql.exec(`CREATE TEMP VIEW advisor_contacts AS SELECT 'fixture-crew' AS id, 'Crew marker' AS display_name,
    'fixture' AS channel, 'active' AS status, 'en' AS language, 'crew' AS role`);
  for (let i = 1; i <= boats; i++) {
    const id = boatId(i);
    seed(`INSERT INTO advisor_boats(id,slug,name,port,region,status,consent_photos_at,created_at,updated_at)
      VALUES(?,?,?,'fixture','fixture','verified',?,?,?)`, id, id, id, AT, AT, AT);
  }
  // Put joined facts on each side of a page boundary, including the lookahead row.
  for (const i of new Set([1, boats])) {
    const id = boatId(i);
    seed("INSERT INTO advisor_crew(boat_id,contact_id,added_by,added_at) VALUES(?,'fixture-crew','fixture',?)", id, AT);
    seed('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)', noteKey(id), JSON.stringify({note: NOTE, at: AT}), AT);
    seed("INSERT INTO advisor_reviews(id,ref_id,kind,reason,opened_at) VALUES(?,?,'skipper','new_skipper',?)", `skipper-${id}`, id, AT);
  }
  for (let i = 1; i <= cards; i++) {
    seed(`INSERT INTO advisor_reports(id,boat_id,port,region,report_date,counts_json,source,status,notes,created_at,updated_at)
      VALUES(?,?,'fixture','fixture','2026-10-03','[]',?,'published',?,?,?)`, `report-${i}`, boatId(1), `source-${i}`, REPORT, AT, AT);
    seed("INSERT INTO advisor_reviews(id,ref_id,kind,reason,opened_at) VALUES(?,?,'report','fixture',?)", reviewId(i), `report-${i}`, AT);
    seed(`INSERT INTO advisor_media(id,boat_id,contact_id,kind,mime,bytes,r2_key,sha256,publish_state,created_at)
      VALUES(?,?,'fixture-crew','image','image/jpeg',1,'synthetic-object','fixture','queued',?)`, `media-${i}`, boatId(1), AT);
    seed(`INSERT INTO advisor_posts(id,boat_id,kind,region,media_json,caption,targets_json,created_by,created_at,updated_at)
      VALUES(?,?,'photo','fixture',?,?,'[]','fixture',?,?)`, `post-${i}`, boatId(1), JSON.stringify([`media-${i}`]), CAPTION, AT, AT);
  }
  // Count executions, not prepare() or round trips: wrapping N statements in a
  // D1 batch would still count N. The app binding cannot write even in memory.
  const reads = [];
  const counted = {prepare(query) {
    assert.match(query.trim(), /^SELECT\b/i, 'app binding is read-only');
    const statement = db.prepare(query);
    const record = rows => { reads.push({query, rows}); };
    return {
      bind(...args) { statement.bind(...args); return this; },
      async all() { const result = await statement.all(); record(result.results); return result; },
      async first() { const row = await statement.first(); record(row ? [row] : []); return row; },
      run() { assert.fail('unexpected write'); },
    };
  }, batch: statements => Promise.all(statements.map(statement => statement.all()))};
  return {db: counted, reads, sql, seed};
}
const all = async (db, query, ...args) => (await db.prepare(query).bind(...args).all()).results;

// Small reference for the contract, not a proposed production API. All test
// boats share status and time to exercise the id tie-break at the boundary.
async function referenceBoats(db, cursor) {
  const rows = await all(db, 'SELECT id FROM advisor_boats WHERE id>? ORDER BY id LIMIT ?', cursor ?? '', PAGE + 1);
  const page = rows.slice(0, PAGE), ids = JSON.stringify(page.map(r => r.id));
  const inPage = 'IN (SELECT value FROM json_each(?))';
  const [crew, notes, reviews, reports, posts] = await Promise.all([
    all(db, `SELECT boat_id, count(*) n FROM advisor_crew WHERE removed_at IS NULL AND boat_id ${inPage} GROUP BY boat_id`, ids),
    all(db, `SELECT key FROM job_state WHERE key ${inPage}`, JSON.stringify(page.map(r => noteKey(r.id)))),
    all(db, `SELECT ref_id FROM advisor_reviews WHERE kind='skipper' AND reason='new_skipper' AND status='open' AND ref_id ${inPage}`, ids),
    all(db, `SELECT boat_id,count(*) n FROM advisor_reports WHERE status='published' AND report_date>=? AND boat_id ${inPage} GROUP BY boat_id`, '2026-09-03', ids),
    all(db, `SELECT boat_id,count(*) n FROM advisor_posts WHERE status<>'rejected' AND boat_id ${inPage} GROUP BY boat_id`, ids),
  ]);
  return {boats: page.map(({id}) => ({id, crew_count: crew.find(r => r.boat_id === id)?.n ?? 0,
    has_note: notes.some(r => r.key === noteKey(id)), review_open: reviews.some(r => r.ref_id === id),
    reports_30d: reports.find(r => r.boat_id === id)?.n ?? 0, posts: posts.find(r => r.boat_id === id)?.n ?? 0})),
  next: rows.length > PAGE ? page.at(-1).id : null};
}
async function referenceReviews(db) {
  return {items: await all(db, "SELECT id,kind,ref_id,status FROM advisor_reviews WHERE kind='report' ORDER BY opened_at DESC,id DESC LIMIT 50")};
}
async function referencePosts(db) {
  const posts = await all(db, "SELECT id,status,media_json FROM advisor_posts WHERE status='draft' ORDER BY updated_at DESC,id DESC LIMIT 50");
  const media = await all(db, 'SELECT id FROM advisor_media WHERE id IN (SELECT value FROM json_each(?))',
    JSON.stringify(posts.flatMap(p => JSON.parse(p.media_json))));
  return {posts: posts.map(p => ({id: p.id, status: p.status, media_count: media.filter(m => JSON.parse(p.media_json).includes(m.id)).length}))};
}
const boatsPage = (db, cursor) => baseline ? listBoats(db, NOW, {cursor}) : referenceBoats(db, cursor);
const reviewsPage = db => baseline ? listReviews(db, {kind: 'report', status: 'open'}) : referenceReviews(db);
const postsPage = db => baseline ? listPosts(db, {status: 'draft'}) : referencePosts(db);
const label = baseline ? 'baseline' : 'reference';

// Collect independent mismatches before asserting, so an absent cursor does
// not hide an N+1 or an out-of-page read on the same request.
function check(t, observations, conditions) {
  t.diagnostic(JSON.stringify(observations));
  assert.deepEqual(conditions.filter(([, ok]) => !ok).map(([name]) => name), [], 'contract gaps');
}

test(`${label}: boat continuation and page-scoped reads`, async t => {
  const one = fixture(t, 1, 1), large = fixture(t, PAGE + 1, 1);
  await boatsPage(one.db);
  const first = await boatsPage(large.db);
  const firstReads = large.reads.splice(0);
  const second = first.next ? await boatsPage(large.db, first.next) : {boats: []};
  const reached = [...first.boats, ...second.boats].map(r => r.id);
  const scoped = (reads, page) => {
    const ids = new Set(page.boats.map(r => r.id));
    return reads.flatMap(({query, rows}) => rows.flatMap(row => {
      if (/^SELECT (?:cr\.)?boat_id\b/i.test(query)) return [row.boat_id];
      if (/FROM advisor_reviews/i.test(query)) return [row.ref_id];
      return row.key?.startsWith('advisor.boat-note.') ? [row.key.slice('advisor.boat-note.'.length)] : [];
    })).every(id => ids.has(id));
  };
  const facts = row => [row?.crew_count ?? row?.crew?.length, row?.has_note ?? Boolean(row?.consent_note), row?.review_open, row?.reports_30d, row?.posts];
  const local = scoped(firstReads, first) && scoped(large.reads, second);
  check(t, {boats: [first.boats.length, second.boats.length], continuation: Boolean(first.next),
    reads: [one.reads.length, firstReads.length, large.reads.length], pageScoped: local}, [
    ['501 distinct boats in order with a terminal continuation', reached.length === PAGE + 1 && reached.every((id, i) => id === boatId(i + 1)) && second.next === null],
    ['boat statement count stays bounded as the page fills', firstReads.length <= 8 && firstReads.length <= one.reads.length + 2 && large.reads.length <= 8],
    ['crew, notes and open reviews stay on-page', local],
    ['summary facts survive batching on both pages', JSON.stringify(facts(first.boats[0])) === '[1,true,true,1,1]' &&
      JSON.stringify(facts(first.boats[1])) === '[0,false,false,0,0]' && JSON.stringify(facts(second.boats[0])) === '[1,true,true,0,0]'],
    ['no private consent note or crew display detail in summaries', !JSON.stringify(first.boats).includes(NOTE) && !JSON.stringify(first.boats).includes('Crew marker')],
  ]);
});

for (const [kind, list, key, sentinel] of [['reviews', reviewsPage, 'items', REPORT], ['posts', postsPage, 'posts', CAPTION]]) {
  test(`${label}: ${kind} list is bounded and leaves private detail for expansion`, async t => {
    const one = fixture(t, 1, 1), many = fixture(t, 1, MANY);
    await list(one.db);
    const items = (await list(many.db))[key];
    const mediaReads = reads => reads.filter(r => /FROM advisor_media\b/i.test(r.query)).length;
    const expectedIds = Array.from({length: MANY}, (_, i) => kind === 'reviews' ? reviewId(i + 1) : `post-${i + 1}`);
    check(t, {cards: items.length, reads: [one.reads.length, many.reads.length], mediaReads: [mediaReads(one.reads), mediaReads(many.reads)]}, [
      ['all card identities and statuses preserved', JSON.stringify(items.map(r => r.id).sort()) === JSON.stringify(expectedIds.sort()) &&
        items.every(r => r.status === (kind === 'reviews' ? 'open' : 'draft'))],
      ['list statement count does not grow per card', many.reads.length <= 6 && many.reads.length <= one.reads.length + 2],
      ['no eager private detail', !JSON.stringify(items).includes(sentinel)],
      ['draft list does not repeat the media read per card and can show a media count', kind !== 'posts' ||
        (mediaReads(many.reads) <= 1 && items.every(p => (p.media_count ?? p.media?.length) === 1))],
    ]);
  });
}

test('expansion keeps private detail behind admin; approval rechecks consent after expansion and at decision time', async t => {
  const f = fixture(t, 1, 1), {db, sql, seed} = f;
  const expand = () => Promise.all([boatView(db, boatId(1), NOW), reviewDetail(db, {kind: 'report', ref_id: 'report-1'}), postDetail(db, 'post-1')]);
  // Exercise the real role middleware in-process with a role answer only (no
  // login/session rows). This is not a new route or a browser auth replay.
  let detailRows;
  function requestAs(role) {
    const roleDb = {prepare(query) {
      assert.match(query, /^SELECT role FROM users WHERE id=\?$/);
      return {bind: () => ({first: async () => ({role})})};
    }};
    return requireAdmin({env: {DB: roleDb, TEXT_ADVISOR_ENABLED: 'true'}, var: {owner: 'fixture'}}, async () => {
      detailRows = await expand();
    });
  }
  assert.equal((await requestAs('member')).status, 404);
  assert.equal(f.reads.length, 0, 'a denied expansion must not touch any private rows');
  await requestAs('admin');
  assert.ok(detailRows, 'admin reaches the detail readers');
  const [boat, review, detail] = detailRows;
  assert.equal(boat.consent_note.note, NOTE);
  assert.equal(boat.crew[0].display_name, 'Crew marker');
  assert.equal(review.report.notes, REPORT);
  assert.equal(detail.post.caption, CAPTION);
  assert.match(detail.post.media[0].original, /^\/api\/admin\/media\/media-1\?v=original$/);
  assert.equal(detail.post.hold, null, 'the expanded card looked eligible');

  const approve = () => preparePostDecision(db, 'post-1', 'approve', null, null, NOW);
  const pending = await approve();
  assert.equal(pending.status, 'ok');
  const eligible = () => sql.prepare(`SELECT ${pending.check.sql} AS eligible`).get(...pending.check.args).eligible;
  assert.equal(eligible(), 1);
  seed('UPDATE advisor_boats SET consent_revoked_at=? WHERE id=?', AT, boatId(1));
  const refused = await approve();
  assert.equal(refused.status, 'conflict');
  assert.match(refused.error, /revoked.*consent/);
  assert.equal(eligible(), 0, 'a prepared approval predicate must catch the revocation too');
  assert.equal(sql.prepare('SELECT status FROM advisor_posts').get().status, 'draft');
});

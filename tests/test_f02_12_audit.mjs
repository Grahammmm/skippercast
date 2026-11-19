// F02-12 / SCA-611: an existing draft ID is not proof that auto-publication
// finished. A replay can publish the same authorized, unedited pending report
// once or report its actual state. It must not reopen a rejected or edited
// report, publish after authorization is lost, or republish an existing post.
// Default: reference and synthetic affected controls. To observe unchanged
// product behavior without making the known gap a CI assertion, run:
//   node tests/test_f02_12_audit.mjs --baseline
import assert from 'node:assert/strict';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {advisorDatabase} from './_advisor_d1.mjs';

// Build-time globals, with no deployment config or location data.
Object.assign(globalThis, {REGIONS: {}, DEPLOYMENT: {}, SHELLS: {}, BUILD_ID: 'audit'});
const {ADVISOR_QUEUE_NAME, consumeAdvisor} = await import('../server/advisor/consumer.ts');
const {draftActions, postsFor, publishReport} = await import('../server/advisor/intake/reports.ts');

const T0 = Date.parse('2026-01-01T12:00:00Z');
const AT = new Date(T0).toISOString();
const CONTACT = {id: 'audit-actor', channel: 'web', status: 'active', web_session: 'audit-sink'};
const BOAT = {id: 'audit-boat', slug: 'audit-boat', name: 'Fixture Boat', auto_publish: 1};
const MESSAGE = 'audit-message';
const INTERRUPT = 'audit interrupted after report insert';
const READ_STATE = {
  pending_confirm: 'The report is still pending.',
  rejected: 'The report was rejected.',
};
const reportPayload = ({status, published_at, updated_at, ...payload}) => payload;

// The oracle is shared by all modes. Observe the row and cache generation, not
// just the action result; a second publication can leave status unchanged.
function gaps(before, after, replies, mayPublish) {
  const issues = [];
  if (mayPublish && after.row?.status === 'published') {
    if (!after.row.published_at || after.pages !== before.pages + 1 ||
        !isDeepStrictEqual(reportPayload(before.row), reportPayload(after.row))) issues.push('original pending version did not publish exactly once');
  } else if (!isDeepStrictEqual(after, before)) {
    issues.push('replay changed a report or publication generation that should stay unchanged');
  }
  if (replies.length !== 1 || replies[0].claimed !== after.row?.status || replies[0].stored !== replies[0].claimed) {
    issues.push('reply did not report the actual state at delivery');
  }
  return issues;
}

async function replay(t, state, mode) {
  const {sql, db} = advisorDatabase();
  t.after(() => sql.close());
  let interrupted = false;
  const fixtureDb = {...db, prepare(query) {
    // Stub the actor lookup; the actual boat authorization SQL still runs.
    // No contact or account rows are inserted and no real transport is bound.
    if (query === 'SELECT * FROM advisor_contacts WHERE id=?') {
      return {bind(id) { return {first: async () => id === CONTACT.id ? CONTACT : null}; }};
    }
    const statement = db.prepare(query);
    if (!/^INSERT INTO advisor_reports\(/.test(query)) return statement;
    const run = statement.run;
    statement.run = async () => {
      const result = await run();
      if (!interrupted && result.meta.changes === 1) {
        interrupted = true;
        throw Error(INTERRUPT);
      }
      return result;
    };
    return statement;
  }};
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,auto_publish,created_at,updated_at)
    VALUES(?,?,?,'fixture-port','fixture-region',?,1,?,?)`).run(BOAT.id, BOAT.slug, BOAT.name, CONTACT.id, AT, AT);
  sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,status,created_at)
    VALUES(?,?,'in','web','queued',?)`).run(MESSAGE, CONTACT.id, AT);

  const {actions, reportId} = await draftActions({db, settings: {publicBase: 'https://example.test'}, boat: BOAT,
    contact: CONTACT, messageId: MESSAGE, language: 'en', now: T0, source: 'text', mediaId: null,
    fields: {report_date: '2026-01-01', trip_type: null, anglers: null, notes: 'original',
      counts: [{species_key: 'lingcod', label: 'lingcod', kept: 3, released: null}]}});
  const read = () => ({row: sql.prepare('SELECT * FROM advisor_reports WHERE id=?').get(reportId),
    pages: Number(sql.prepare("SELECT value FROM job_state WHERE key='advisor.pages.version'").get()?.value ?? 0)});
  const posted = actions[1];
  assert.equal(actions[0].type, 'report_draft');
  assert.equal(actions[0].publish, true);
  assert.equal(posted.type, 'send_text');
  assert.match(posted.text, /\bposted\b/i);
  const replies = [];
  const channel = {async send({text}) {
    const claimed = text === posted.text ? 'published' : Object.keys(READ_STATE).find(key => READ_STATE[key] === text);
    replies.push({claimed, stored: read().row?.status});
    return {status: 'sent', providerId: 'memory-only'};
  }};
  const env = {DB: fixtureDb, TEXT_ADVISOR_ENABLED: 'true'};
  const deliver = (attempts, handler) => consumeAdvisor({queue: ADVISOR_QUEUE_NAME, messages: [
    {body: {message_id: MESSAGE}, attempts, ack() {}, retry() {}},
  ]}, env, {handler, channel, now: () => T0 + attempts * 1000});
  const plan = actions => async () => ({intent: 'audit', actions});
  // In the reference controls, stage a pending row independent of how a
  // future automatic path implements its writes. Baseline runs the real plan.
  const first = await deliver(1, plan(mode === 'baseline' ? actions : [{...actions[0], publish: false}]));
  const pending = read();
  assert.deepEqual([first.retried, interrupted, pending.row?.status, pending.row?.version, pending.row?.published_at, pending.pages, replies.length],
    [1, true, 'pending_confirm', 1, null, 0, 0]);
  assert.equal(sql.prepare('SELECT error FROM advisor_messages WHERE id=?').get(MESSAGE).error, INTERRUPT);

  if (state === 'edited') sql.prepare("UPDATE advisor_reports SET version=2,notes='edited' WHERE id=?").run(reportId);
  if (state === 'rejected') sql.prepare("UPDATE advisor_reports SET status='rejected' WHERE id=?").run(reportId);
  if (state === 'published') assert.equal(await publishReport(db, CONTACT, reportId, T0 + 1500, {auto: true}), true);
  if (state === 'revoked') sql.prepare('UPDATE advisor_boats SET owner_contact_id=NULL WHERE id=?').run(BOAT.id);
  const before = read();
  const handler = mode === 'baseline' ? plan(actions) : async ({now}) => {
    // Reference only: the real auto publisher plus an honest state reply.
    // The affected control deliberately substitutes a false "posted" reply.
    const {status, version} = read().row;
    if (status === 'pending_confirm' && (mode === 'blind-resume' ||
        (mode === 'resume' && version === 1 && await postsFor(db, CONTACT.id, BOAT.id)))) {
      assert.equal(await publishReport(db, CONTACT, reportId, now, {auto: true}), true);
    }
    const current = read().row.status;
    return {intent: 'audit', actions: [mode === 'affected' || current === 'published' ? posted : {type: 'send_text', text: READ_STATE[current]}]};
  };
  const second = await deliver(2, handler);
  assert.equal(second.done, 1, 'the replay reached completion');
  const after = read();
  const issues = gaps(before, after, replies, state === 'pending');
  // Run the same request again past the inbound completion check; this probes
  // re-application, not merely the queue's already-done fast path.
  sql.prepare("UPDATE advisor_messages SET status='queued' WHERE id=?").run(MESSAGE);
  const third = await deliver(3, handler);
  assert.equal(third.done, 1);
  if (!isDeepStrictEqual(read(), after) || replies.length !== 1) issues.push('repeated replay wrote again');
  assert.equal(sql.prepare('SELECT count(*) AS n FROM advisor_reports').get().n, 1);
  return {before: [before.row.status, before.row.version, before.pages], after: [after.row.status, after.row.version, after.pages], replies, gaps: issues};
}

const states = ['pending', 'edited', 'rejected', 'published', 'revoked'];
if (process.argv.includes('--baseline')) {
  for (const state of states) test(`baseline: ${state} (diagnostic only)`, async t => {
    t.diagnostic(JSON.stringify(await replay(t, state, 'baseline')));
  });
} else {
  test('valid control: resume the pending version once', async t => {
    assert.deepEqual((await replay(t, 'pending', 'resume')).gaps, []);
  });
  for (const state of states) test(`valid control: report the real state without rewriting ${state}`, async t => {
    assert.deepEqual((await replay(t, state, state === 'pending' ? 'honest' : 'resume')).gaps, []);
  });
  test('affected control: already-inserted pending row does not justify a posted reply', async t => {
    assert.deepEqual((await replay(t, 'pending', 'affected')).gaps, ['reply did not report the actual state at delivery']);
  });
  test('affected control: blindly resuming publishes a later edit', async t => {
    assert.deepEqual((await replay(t, 'edited', 'blind-resume')).gaps,
      ['replay changed a report or publication generation that should stay unchanged']);
  });
}

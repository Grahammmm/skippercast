// F01-07 / SCA-214: the admin Funnel's replies-per-contact must count only confirmed
// ('sent') outbound rows and their distinct recipients. Held, sending and unknown
// attempts (a relay outage, a crash mid-send) are reported as unconfirmed, never as replies.
// 'sent' means the adapter accepted the message, not that it was delivered or read.
// Contract protected: replies.{outbound,contacts,per_contact} exclude everything but 'sent'.
// Bug that fails it: the old `status<>'failed'` predicate, which made an all-held relay outage
// look like successful engagement (the negative control below replays that predicate).
import assert from 'node:assert/strict';
import test from 'node:test';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {adminFunnel} = await import('../server/advisor/admin/funnel.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const T0 = Date.parse('2026-10-04T18:00:00Z'), DAY = 86400000;
const iso = ms => new Date(ms).toISOString();

/** Synthetic rows only: contacts and outbound messages with the given statuses. */
function fixture(statuses) {
  const {sql, db} = advisorDatabase();
  const contacts = new Set();
  let n = 0;
  for (const [contact, status, at = T0 - DAY] of statuses) {
    if (!contacts.has(contact)) {
      contacts.add(contact);
      sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,channel,source,status,last_seen_at,created_at,updated_at) VALUES(?,?,'imessage','qr','active',?,?,?)`)
        .run(contact, `HASH-${contact}`, iso(T0), iso(T0), iso(T0));
    }
    sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES(?,?,'out','imessage','x',?,?)`)
      .run(`m${++n}`, contact, status, iso(at));
  }
  return {sql, db};
}

const funnel = db => adminFunnel({DB: db}, 7, {now: T0, sql: null});
const legacyReplies = sql => sql.prepare(`SELECT COUNT(*) AS n, COUNT(DISTINCT contact_id) AS contacts FROM advisor_messages WHERE direction='out' AND status<>'failed' AND created_at>=?`)
  .get(iso(T0 - 7 * DAY));

dbTest('negative control: an all-held relay outage has no confirmed replies, a null ratio and a visible pending count', async () => {
  const {sql, db} = fixture([['c1', 'held'], ['c1', 'held'], ['c2', 'held'], ['c3', 'sending'], ['c3', 'unknown'], ['c4', 'failed']]);
  // The fixture discriminates: the old predicate would have called five of these six rows replies.
  assert.deepEqual({...legacyReplies(sql)}, {n: 5, contacts: 3});
  const f = await funnel(db);
  assert.deepEqual(f.replies, {outbound: 0, contacts: 0, per_contact: null});
  assert.deepEqual(f.unconfirmed_replies, {held: 3, sending: 1, unknown: 1, other: 0, pending: 5}, 'failed rows are neither a reply nor pending');
});

dbTest('positive control: sent rows and their distinct recipients are the replies; held and unknown are reported beside them', async () => {
  const {db} = fixture([
    ['c1', 'sent'], ['c1', 'sent'], ['c2', 'sent'], ['c2', 'sent'],
    ['c3', 'held'], ['c3', 'unknown'], ['c4', 'sending'], ['c4', 'failed'],
    ['c5', 'sent', T0 - 20 * DAY], ['c5', 'held', T0 - 20 * DAY],   // outside the 7-day window
  ]);
  const f = await funnel(db);
  assert.deepEqual(f.replies, {outbound: 4, contacts: 2, per_contact: 2}, 'only the in-window sent rows, over the contacts that received them');
  assert.deepEqual(f.unconfirmed_replies, {held: 1, sending: 1, unknown: 1, other: 0, pending: 3});
});

dbTest('a contact with only unconfirmed rows is not a recipient of a confirmed reply', async () => {
  const {db} = fixture([['c1', 'sent'], ['c2', 'held'], ['c3', 'unknown']]);
  const f = await funnel(db);
  assert.deepEqual(f.replies, {outbound: 1, contacts: 1, per_contact: 1}, 'the legacy count would have been 3 rows over 3 contacts');
  assert.equal(f.unconfirmed_replies.pending, 2);
});

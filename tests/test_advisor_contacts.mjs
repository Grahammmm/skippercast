// Text Advisor contacts (server/advisor/contacts.ts): HKDF subkeys, the keyed
// phone hash, AES-GCM phone encryption, E.164 normalisation, the contact
// UPSERT, STOP/START, "forget me" and "send me my data" against the real
// migrations in an in-memory SQLite (tests/_advisor_d1.mjs). Numbers are the
// fictional 555 series only (02 § privacy invariants).
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac, hkdfSync} from 'node:crypto';
import {deriveKeys, phoneHash, encryptPhone, decryptPhone, e164, findOrCreateContact, applyStop, applyStart, forgetContact, exportContact, reviewId} from '../server/advisor/contacts.ts';
import {advisorDatabase, fakeBucket, sqliteUnavailable, journal, migrationSql} from './_advisor_d1.mjs';

const MASTER = Buffer.alloc(32, 7).toString('base64'), OTHER = Buffer.alloc(32, 9).toString('base64');
const NUMBER = '+18055550100', SECOND = '+18055550199';
const fixedIv = () => new Uint8Array(12).fill(1);
const T0 = new Date('2026-10-03T15:00:00Z'), T1 = new Date('2026-10-03T16:30:00Z');
const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);

test('deriveKeys is deterministic and matches HKDF-SHA256 with empty salt and info hash/enc', async () => {
  const a = await deriveKeys(MASTER), b = await deriveKeys(MASTER);
  assert.equal(await phoneHash(a, NUMBER), await phoneHash(b, NUMBER));
  const kHash = Buffer.from(hkdfSync('sha256', Buffer.from(MASTER, 'base64'), Buffer.alloc(0), 'hash', 32));
  assert.equal(await phoneHash(a, NUMBER), createHmac('sha256', kHash).update(NUMBER).digest('hex'), 'K_hash = HKDF(master, info "hash")');
  assert.equal(a.hashKey.extractable, false); assert.equal(a.encKey.extractable, false);
  await assert.rejects(deriveKeys(Buffer.alloc(16).toString('base64')), /32 bytes/);
  await assert.rejects(deriveKeys('not base64!'), /base64/);
});

test('phoneHash is 64 hex, deterministic, keyed and per number', async () => {
  const k = await deriveKeys(MASTER), other = await deriveKeys(OTHER), h = await phoneHash(k, NUMBER);
  assert.match(h, /^[0-9a-f]{64}$/);
  assert.equal(await phoneHash(k, NUMBER), h);
  assert.notEqual(await phoneHash(other, NUMBER), h, 'a different master key gives a different hash');
  assert.notEqual(await phoneHash(k, SECOND), h);
  await assert.rejects(phoneHash(k, '8055550100'), /E\.164/, 'only normalised numbers are hashed');
});

test('encryptPhone/decryptPhone round trip; iv is 12 bytes and random by default; tampering fails', async () => {
  const k = await deriveKeys(MASTER);
  const fixed = await encryptPhone(k, NUMBER, fixedIv);
  assert.equal(fixed, await encryptPhone(k, NUMBER, fixedIv), 'same iv, same blob');
  const bytes = Buffer.from(fixed, 'base64');
  assert.equal(bytes.length, 12 + NUMBER.length + 16, 'iv ‖ ciphertext ‖ 16-byte tag');
  assert.deepEqual([...bytes.subarray(0, 12)], [...fixedIv()]);
  assert.ok(!bytes.toString('latin1').includes('8055550100'), 'ciphertext does not contain the number');
  assert.equal(await decryptPhone(k, fixed), NUMBER);
  const r1 = await encryptPhone(k, NUMBER), r2 = await encryptPhone(k, NUMBER);
  assert.notEqual(r1, r2, 'fresh iv each time'); assert.equal(await decryptPhone(k, r2), NUMBER);
  bytes[bytes.length - 1] ^= 1;
  await assert.rejects(decryptPhone(k, bytes.toString('base64')));
  await assert.rejects(decryptPhone(await deriveKeys(OTHER), fixed), 'another key cannot decrypt');
  await assert.rejects(encryptPhone(k, NUMBER, () => new Uint8Array(8)), /12 bytes/);
});

test('e164 normalises US formats and rejects everything else', () => {
  for (const input of ['(805) 555-0100', '805-555-0100', '805.555.0100', '8055550100', '1 805 555 0100', '1-805-555-0100', '+18055550100', '+1 (805) 555-0100', '  805 555 0100 '])
    assert.equal(e164(input), NUMBER, input);
  for (const input of ['55501', '555-0100', '72975', '+44 20 7946 0958', '+5255555501000', '805555010', '80555501000', '+8055550100',
    '805-555-01OO', '805-555-0100 x12', 'call 8055550100', '(055) 555-0100', '(805) 155-0100', '', '+', null, undefined, 8055550100, '1'.repeat(40)])
    assert.equal(e164(input), null, String(input));
  assert.equal(e164('805-555-0100', 'MX'), null, 'only US is supported');
});

dbTest('findOrCreateContact upserts by phone hash, never stores the number and refreshes last_seen_at', async () => {
  const {sql, db} = advisorDatabase(), k = await deriveKeys(MASTER);
  const first = await findOrCreateContact(db, k, {e164: NUMBER}, T0);
  assert.equal(first.phone_hash, await phoneHash(k, NUMBER));
  assert.equal(await decryptPhone(k, first.phone_enc), NUMBER);
  assert.deepEqual([first.channel, first.role, first.language, first.status, first.messages_today], ['sms', 'angler', 'en', 'active', 0]);
  assert.equal(first.last_seen_at, T0.toISOString());
  const again = await findOrCreateContact(db, k, {e164: NUMBER, channel: 'imessage'}, T1);
  assert.equal(again.id, first.id, 'same contact');
  assert.equal(again.created_at, T0.toISOString()); assert.equal(again.last_seen_at, T1.toISOString());
  assert.equal(again.channel, 'imessage', 'last channel used');
  assert.equal(again.phone_enc, first.phone_enc, 'the stored blob is not rewritten');
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM advisor_contacts').get().n, 1);
  const dump = JSON.stringify(sql.prepare('SELECT * FROM advisor_contacts').all());
  assert.ok(!dump.includes('8055550100'), 'no clear number in any column');
  await findOrCreateContact(db, k, {e164: SECOND}, T1);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM advisor_contacts').get().n, 2);
  await assert.rejects(findOrCreateContact(db, k, {e164: '805-555-0100'}, T0), /E\.164/);
  await assert.rejects(findOrCreateContact(db, k, {}, T0), /exactly one/);
});

dbTest('findOrCreateContact keys web visitors by sha256 of the cookie', async () => {
  const {sql, db} = advisorDatabase(), k = await deriveKeys(MASTER), cookie = 'web-session-cookie-value-0001';
  const a = await findOrCreateContact(db, k, {webSession: cookie}, T0), b = await findOrCreateContact(db, k, {webSession: cookie}, T1);
  assert.equal(a.id, b.id); assert.equal(a.channel, 'web'); assert.equal(a.phone_hash, null);
  assert.match(a.web_session, /^[0-9a-f]{64}$/); assert.notEqual(a.web_session, cookie);
  assert.equal(b.last_seen_at, T1.toISOString());
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM advisor_contacts').get().n, 1);
  await assert.rejects(findOrCreateContact(db, k, {webSession: 'short'}, T0), /web session/);
});

dbTest('STOP stops, START restarts, and neither touches an admin block', async () => {
  const {sql, db} = advisorDatabase(), k = await deriveKeys(MASTER), c = await findOrCreateContact(db, k, {e164: NUMBER}, T0);
  const status = () => sql.prepare('SELECT status FROM advisor_contacts WHERE id=?').get(c.id).status;
  assert.equal(await applyStop(db, c.id, T1), true); assert.equal(status(), 'stopped');
  assert.equal(await applyStop(db, c.id, T1), false, 'idempotent');
  assert.equal(await applyStart(db, c.id, T1), true); assert.equal(status(), 'active');
  assert.equal(await applyStart(db, c.id, T1), false);
  sql.prepare("UPDATE advisor_contacts SET status='blocked' WHERE id=?").run(c.id);
  assert.equal(await applyStop(db, c.id, T1), false); assert.equal(await applyStart(db, c.id, T1), false);
  assert.equal(status(), 'blocked');
  await assert.rejects(applyStop(db, "x' OR 1=1 --", T1), /contact id/);
});

/** A skipper with a boat, crew, messages, media, reports, an edit and reviews; plus an unrelated contact. */
async function seeded() {
  const {sql, db} = advisorDatabase(), k = await deriveKeys(MASTER), at = T0.toISOString();
  const skipper = await findOrCreateContact(db, k, {e164: NUMBER}, T0), other = await findOrCreateContact(db, k, {e164: SECOND}, T0);
  const run = (q, ...a) => sql.prepare(q).run(...a);
  run(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,created_at,updated_at) VALUES('boat1','test-boat','Test Boat','morro-bay','morro-bay',?,?,?)`, skipper.id, at, at);
  run(`INSERT INTO advisor_boats(id,slug,name,port,region,owner_contact_id,created_at,updated_at) VALUES('boat2','other-boat','Other Boat','morro-bay','morro-bay',?,?,?)`, other.id, at, at);
  run(`INSERT INTO advisor_crew(boat_id,contact_id,added_by,added_at) VALUES('boat2',?,?,?)`, skipper.id, other.id, at);
  run(`INSERT INTO advisor_crew(boat_id,contact_id,added_by,added_at) VALUES('boat1',?,?,?)`, other.id, skipper.id, at);
  for (const [id, contact, dir] of [['m1', skipper.id, 'in'], ['m2', skipper.id, 'out'], ['m3', other.id, 'in']])
    run(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES(?,?,?,'sms','hello','done',?)`, id, contact, dir, at);
  for (const [id, contact] of [['media1', skipper.id], ['media2', other.id]])
    run(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,created_at) VALUES(?,?,'boat1','image','image/jpeg',10,?,'00',?)`, id, contact, `advisor/media/${contact}/${id}.jpg`, at);
  run(`INSERT INTO advisor_reports(id,boat_id,contact_id,region,port,report_date,counts_json,source,media_id,status,created_at,updated_at) VALUES('r1','boat1',?,'morro-bay','morro-bay','2026-10-03','[]','count-board','media1','published',?,?)`, skipper.id, at, at);
  run(`INSERT INTO advisor_reports(id,boat_id,contact_id,region,port,report_date,counts_json,source,status,created_at,updated_at) VALUES('r2','boat1',?,'morro-bay','morro-bay','2026-10-03','[]','text','draft',?,?)`, other.id, at, at);
  run(`INSERT INTO advisor_report_edits(id,report_id,contact_id,message_id,patch_json,created_at) VALUES('e1','r1',?,'m1','[]',?)`, skipper.id, at);
  run(`INSERT INTO advisor_report_edits(id,report_id,contact_id,message_id,patch_json,created_at) VALUES('e2','r2',?,'m3','[]',?)`, other.id, at);
  for (const [id, kind, ref, reason] of [['v1', 'media', 'media1', 'has_person'], ['v2', 'conversation', 'm1', 'refused'], ['v3', 'skipper', skipper.id, 'new_skipper'], ['v4', 'media', 'media2', 'angler_photo'], ['v5', 'report', 'r1', 'unverified_boat']])
    run(`INSERT INTO advisor_reviews(id,kind,ref_id,reason,opened_at) VALUES(?,?,?,?,?)`, id, kind, ref, reason, at);
  const bucket = fakeBucket([`advisor/media/${skipper.id}/media1.jpg`, `advisor/media/${skipper.id}/media9.mp4`, 'advisor/derived/media1/public.jpg', 'advisor/derived/media1/thumb.jpg',
    `advisor/exports/${skipper.id}/2026-10-01.json`, `advisor/media/${other.id}/media2.jpg`, 'advisor/derived/media2/public.jpg']);
  return {sql, db, k, skipper, other, bucket};
}
const count = (sql, q, ...a) => sql.prepare(`SELECT COUNT(*) AS n FROM ${q}`).get(...a).n;

dbTest('forget me removes every row about the contact, keeps the boat and its reports, and opens owner_forgotten', async () => {
  const {sql, db, skipper, other, bucket} = await seeded();
  const result = await forgetContact(db, bucket, skipper.id, T1);
  assert.deepEqual(result, {reviews: 3, reportEdits: 1, crew: 1, media: 1, messages: 2, reportsDetached: 1, boatsOrphaned: 1, contact: 1, r2Objects: 5});
  // Nothing references the contact any more, in any table.
  for (const [table, column] of [['advisor_contacts', 'id'], ['advisor_messages', 'contact_id'], ['advisor_media', 'contact_id'], ['advisor_crew', 'contact_id'],
    ['advisor_report_edits', 'contact_id'], ['advisor_reports', 'contact_id'], ['advisor_boats', 'owner_contact_id'], ['advisor_reviews', 'ref_id']])
    assert.equal(count(sql, `${table} WHERE ${column}=?`, skipper.id), 0, `${table}.${column}`);
  assert.equal(count(sql, "advisor_reviews WHERE ref_id IN ('media1','m1')"), 0, 'reviews about its media and messages are gone');
  // The boat's record stays.
  const r1 = sql.prepare("SELECT contact_id,media_id,status FROM advisor_reports WHERE id='r1'").get();
  assert.deepEqual({...r1}, {contact_id: null, media_id: null, status: 'published'});
  assert.equal(sql.prepare("SELECT owner_contact_id FROM advisor_boats WHERE id='boat1'").get().owner_contact_id, null);
  const review = sql.prepare("SELECT * FROM advisor_reviews WHERE reason='owner_forgotten'").get();
  assert.deepEqual([review.kind, review.ref_id, review.status, review.id], ['skipper', 'boat1', 'open', await reviewId('skipper', 'boat1', 'owner_forgotten')]);
  // The other contact is untouched.
  assert.equal(count(sql, 'advisor_contacts WHERE id=?', other.id), 1);
  assert.equal(count(sql, 'advisor_messages WHERE contact_id=?', other.id), 1);
  assert.equal(count(sql, 'advisor_media WHERE contact_id=?', other.id), 1);
  assert.equal(count(sql, "advisor_reports WHERE id='r2' AND contact_id=?", other.id), 1);
  assert.equal(count(sql, "advisor_reviews WHERE id IN ('v4','v5')"), 2, 'reviews about other rows stay');
  assert.equal(sql.prepare("SELECT added_by FROM advisor_crew WHERE boat_id='boat1'").get().added_by, skipper.id, 'audit row of who added crew stays (opaque id only)');
  assert.deepEqual([...bucket.store].sort(), ['advisor/derived/media2/public.jpg', `advisor/media/${other.id}/media2.jpg`]);
  // Idempotent: a second call finds nothing and re-opens nothing new.
  const again = await forgetContact(db, bucket, skipper.id, T1);
  assert.equal(again.contact, 0); assert.equal(count(sql, "advisor_reviews WHERE reason='owner_forgotten'"), 1);
  // A later text from the same number starts fresh.
  const fresh = await findOrCreateContact(db, await deriveKeys(MASTER), {e164: NUMBER}, T1);
  assert.notEqual(fresh.id, skipper.id);
});

dbTest('forget me is one transaction: a failing statement leaves every row in place', async () => {
  const {sql, db, skipper} = await seeded();
  const failing = {...db, async batch(qs) { return db.batch([...qs, db.prepare('INSERT INTO no_such_table VALUES(1)')]); }};
  await assert.rejects(forgetContact(failing, undefined, skipper.id, T1));
  assert.equal(count(sql, 'advisor_contacts WHERE id=?', skipper.id), 1);
  assert.equal(count(sql, 'advisor_messages WHERE contact_id=?', skipper.id), 2);
});

dbTest('export returns the contact\'s rows without the number', async () => {
  const {db, k, skipper} = await seeded();
  const data = await exportContact(db, skipper.id), text = JSON.stringify(data);
  assert.equal(data.contact.id, skipper.id);
  assert.equal(data.contact.phone_hash_prefix, (await phoneHash(k, NUMBER)).slice(0, 8));
  assert.ok(!('phone_enc' in data.contact) && !('phone_hash' in data.contact));
  assert.ok(!text.includes('8055550100'), 'no number'); assert.ok(!text.includes(skipper.phone_enc), 'no ciphertext');
  assert.ok(!text.includes(skipper.phone_hash), 'no full hash');
  assert.deepEqual(data.messages.map(m => m.id), ['m1', 'm2']);
  assert.deepEqual(data.media.map(m => m.id), ['media1']); assert.ok(!('r2_key' in data.media[0]));
  assert.deepEqual(data.reports.map(r => r.id), ['r1']); assert.deepEqual(data.report_edits.map(r => r.id), ['e1']);
  assert.deepEqual(data.crew.map(r => r.boat_id), ['boat2']); assert.deepEqual(data.boats.map(b => b.id), ['boat1']);
  assert.equal(await exportContact(db, 'nobody'), null);
});

test('migration 0006 creates every advisor table and index on a fresh database', {skip: sqliteUnavailable || false}, async () => {
  const {DatabaseSync} = await import('node:sqlite'), sql = new DatabaseSync(':memory:');
  const entry = journal().entries.find(e => e.tag.startsWith('0006_'));
  assert.equal(entry?.tag, '0006_advisor_core');
  // Up to 0007 (0007 only adds a column): later migrations add the later tables.
  for (const {tag} of journal().entries.filter(e => e.idx <= 7)) sql.exec(migrationSql(tag));
  const names = type => sql.prepare('SELECT name FROM sqlite_master WHERE type=?').all(type).map(r => r.name);
  const tables = names('table'), indexes = names('index');
  for (const t of ['advisor_contacts', 'advisor_boats', 'advisor_crew', 'advisor_messages', 'advisor_media', 'advisor_reports', 'advisor_report_edits', 'advisor_reviews'])
    assert.ok(tables.includes(t), t);
  for (const t of ['advisor_rules', 'advisor_daily_answers', 'advisor_posts', 'advisor_post_stats']) assert.ok(!tables.includes(t), `${t} belongs to a later migration`);
  for (const i of ['contact_phone_hash', 'contact_web_session', 'contact_boat', 'contact_seen', 'boat_slug', 'boat_port', 'boat_owner', 'crew_contact',
    'message_contact_time', 'message_status', 'message_provider', 'media_contact', 'media_publish', 'media_boat', 'report_port_date', 'report_boat_date',
    'report_status', 'report_boat_day_source', 'edit_report', 'review_open']) assert.ok(indexes.includes(i), i);
  const unique = name => sql.prepare(`PRAGMA index_list(${name.split(':')[0]})`).all().find(r => r.name === name.split(':')[1])?.unique;
  for (const u of ['advisor_contacts:contact_phone_hash', 'advisor_contacts:contact_web_session', 'advisor_boats:boat_slug', 'advisor_messages:message_provider', 'advisor_reports:report_boat_day_source'])
    assert.equal(unique(u), 1, u);
  const columns = t => sql.prepare(`PRAGMA table_info(${t})`).all().map(c => c.name);
  assert.ok(columns('users').includes('role')); assert.ok(columns('advisor_boats').includes('status')); assert.ok(columns('advisor_messages').includes('created_by'));
  assert.ok(!columns('advisor_contacts').includes('ig_sid'), 'ig_sid is migration 0009');
  assert.deepEqual(sql.prepare("SELECT name, pk FROM pragma_table_info('advisor_crew') WHERE pk>0 ORDER BY pk").all().map(r => r.name), ['boat_id', 'contact_id']);
});

dbTest('grant-admin.mjs prints SQL that sets and revokes users.role, refuses odd ids, and runs wrangler only with --apply', async () => {
  const {roleSql, parseArgs, main, wranglerArgs} = await import('../scripts/advisor/grant-admin.mjs');
  const {sql} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at) VALUES('user_A-1','2026-10-03T00:00:00Z'),('user_B','2026-10-03T00:00:00Z')").run();
  const role = id => sql.prepare('SELECT role FROM users WHERE id=?').get(id).role;
  sql.exec(roleSql('user_A-1')); assert.equal(role('user_A-1'), 'admin'); assert.equal(role('user_B'), null);
  sql.exec(roleSql('user_A-1', {revoke: true})); assert.equal(role('user_A-1'), null);
  for (const bad of ["x' OR '1'='1", 'a b', '', 'a'.repeat(65), 'é', 'id;DROP']) assert.throws(() => roleSql(bad), /must match/, bad);
  assert.throws(() => parseArgs([]), /usage/); assert.throws(() => parseArgs(['a', 'b']), /usage/); assert.throws(() => parseArgs(['a', '--force']), /unknown option/);
  assert.deepEqual(parseArgs(['--revoke', 'u1', '--apply']), {userId: 'u1', revoke: true, apply: true});
  const calls = [], out = [], run = (cmd, args) => { calls.push([cmd, args]); return {status: 0}; };
  assert.equal(main(['u1'], {run, log: l => out.push(l)}), 0); assert.equal(calls.length, 0, 'dry run by default');
  assert.equal(out[0], "UPDATE users SET role='admin' WHERE id='u1';");
  assert.equal(main(['u1', '--apply'], {run, log: () => {}}), 0);
  assert.deepEqual(calls, [['npx', wranglerArgs("UPDATE users SET role='admin' WHERE id='u1';")]]);
  assert.deepEqual(calls[0][1].slice(0, 7), ['--yes', 'wrangler', 'd1', 'execute', 'skippercast', '--remote', '--command']);
});

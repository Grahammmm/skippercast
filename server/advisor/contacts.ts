// Text Advisor contacts: phone identity, STOP/START, "forget me" and "send me my
// data" (docs/plans/text-advisor/02-data-model.md § advisor_contacts and
// § Retention and deletion). No phone number is stored or returned in clear:
// phone_hash = HMAC-SHA256(K_hash, e164) finds a contact, phone_enc =
// base64(iv ‖ AES-GCM(K_enc, e164)) is decrypted only by a channel's send().
// K_hash and K_enc come from ADVISOR_PHONE_KEY through HKDF-SHA256 (empty salt,
// info 'hash' / 'enc'), so one secret serves both and neither subkey is stored.
// A third subkey (info 'upload', TA-C4) signs upload-link tokens (media.ts).
// Storage is raw D1 statements, like server/auth.ts.
import type {AdvisorContactRow, PhoneKeys} from './types.ts';
import {hex, sha256, randomId} from './ids.ts';

const encoder = new TextEncoder(), decoder = new TextDecoder();
const E164 = /^\+[1-9]\d{6,14}$/;
const ID = /^[\w-]{1,64}$/;

const toBase64 = (bytes: Uint8Array): string => { let s = ''; for (const b of bytes) s += String.fromCharCode(b); return btoa(s); };
function fromBase64(text: string): Uint8Array<ArrayBuffer> {
  const clean = text.trim().replaceAll('-', '+').replaceAll('_', '/').replace(/=+$/, '');
  if (!/^[A-Za-z0-9+/]*$/.test(clean) || clean.length % 4 === 1) throw Error('invalid base64');
  return Uint8Array.from(atob(clean + '='.repeat((4 - clean.length % 4) % 4)), c => c.charCodeAt(0));
}
function requireE164(value: string): string { if (typeof value !== 'string' || !E164.test(value)) throw Error('not an E.164 number'); return value; }
function requireId(value: string): string { if (typeof value !== 'string' || !ID.test(value)) throw Error('invalid contact id'); return value; }

/** The subkeys (hash, enc, upload) from the base64 32-byte master key ADVISOR_PHONE_KEY. Throws on any other length. */
export async function deriveKeys(masterB64: string): Promise<PhoneKeys> {
  const master = fromBase64(masterB64);
  if (master.length !== 32) throw Error('ADVISOR_PHONE_KEY must be 32 bytes, base64');
  const base = await crypto.subtle.importKey('raw', master, 'HKDF', false, ['deriveKey']);
  const params = (info: string) => ({name: 'HKDF', hash: 'SHA-256', salt: new Uint8Array(0), info: encoder.encode(info)});
  const [hashKey, encKey, uploadKey] = await Promise.all([
    crypto.subtle.deriveKey(params('hash'), base, {name: 'HMAC', hash: 'SHA-256', length: 256}, false, ['sign']),
    crypto.subtle.deriveKey(params('enc'), base, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']),
    crypto.subtle.deriveKey(params('upload'), base, {name: 'HMAC', hash: 'SHA-256', length: 256}, false, ['sign', 'verify']),
  ]);
  return {hashKey, encKey, uploadKey};
}

/** HMAC-SHA256(K_hash, e164) as lowercase hex: the lookup key in advisor_contacts.phone_hash. */
export async function phoneHash(keys: PhoneKeys, e164: string): Promise<string> {
  return hex(await crypto.subtle.sign('HMAC', keys.hashKey, encoder.encode(requireE164(e164))));
}

/** base64(iv ‖ AES-GCM ciphertext+tag) with a fresh 12-byte iv; `iv` is injectable for tests only. */
export async function encryptPhone(keys: PhoneKeys, e164: string, iv: () => Uint8Array = () => crypto.getRandomValues(new Uint8Array(12))): Promise<string> {
  const nonce = iv();
  if (nonce.length !== 12) throw Error('AES-GCM iv must be 12 bytes');
  const sealed = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv: nonce as Uint8Array<ArrayBuffer>}, keys.encKey, encoder.encode(requireE164(e164))));
  const out = new Uint8Array(12 + sealed.length); out.set(nonce); out.set(sealed, 12);
  return toBase64(out);
}

/** The number in a phone_enc blob. Throws if the blob was altered or sealed under another key. */
export async function decryptPhone(keys: PhoneKeys, blob: string): Promise<string> {
  const bytes = fromBase64(blob);
  if (bytes.length < 12 + 16 + 1) throw Error('invalid phone_enc');
  const plain = await crypto.subtle.decrypt({name: 'AES-GCM', iv: bytes.slice(0, 12)}, keys.encKey, bytes.slice(12));
  return requireE164(decoder.decode(plain));
}

/**
 * A North American number in E.164 (+1NXXNXXXXXX), or null. Accepts the usual
 * ways people write one: "(805) 555-0100", "805.555.0100", "1 805 555 0100",
 * "+1 805-555-0100". Rejects letters, short codes, other lengths and any other
 * country code: the advisor's number is US-only (00 § D1), so a non-NANP sender
 * cannot be texted back. `defaultCountry` exists for the interface; only 'US'.
 */
export function e164(input: unknown, defaultCountry: 'US' = 'US'): string | null {
  if (defaultCountry !== 'US' || typeof input !== 'string' || input.length > 32) return null;
  const text = input.trim();
  if (!/^\+?[\d\s().-]+$/.test(text)) return null;          // letters, extensions, anything else
  const plus = text.startsWith('+'), digits = text.replace(/\D/g, '');
  let national: string;
  if (digits.length === 11 && digits.startsWith('1')) national = digits.slice(1);
  else if (digits.length === 10 && !plus) national = digits;
  else return null;
  // NANP: area code and exchange both start 2-9.
  return /^[2-9]\d{2}[2-9]\d{6}$/.test(national) ? '+1' + national : null;
}

/** Who a message is from: a phone number (E.164) or a web visitor's sc_adv cookie value (hashed here). */
export interface ContactIdentity {e164?: string; webSession?: string; channel?: string}

/**
 * The contact for this number or web session, created on first contact. One
 * UPSERT on the unique phone_hash / web_session, so concurrent first messages
 * cannot create two rows. Sets last_seen_at, updated_at and the last channel.
 * Channel defaults to 'sms' for a number and 'web' for a session.
 */
// TA-C3: `keys` may be null for a web session, which needs no phone key.
export async function findOrCreateContact(db: D1Database, keys: PhoneKeys | null, who: ContactIdentity, now: Date = new Date()): Promise<AdvisorContactRow> {
  const at = now.toISOString();
  if ((who.e164 == null) === (who.webSession == null)) throw Error('exactly one of e164 or webSession');
  if (who.e164 != null) {
    if (!keys) throw Error('phone keys are required for a number');
    const number = requireE164(who.e164), channel = who.channel || 'sms';
    const row = await db.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)
      ON CONFLICT(phone_hash) DO UPDATE SET last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at,channel=excluded.channel RETURNING *`)
      .bind(randomId(), await phoneHash(keys, number), await encryptPhone(keys, number), channel, at, at, at).first<AdvisorContactRow>();
    return row!;
  }
  const cookie = who.webSession!;
  if (typeof cookie !== 'string' || !/^[\w-]{16,128}$/.test(cookie)) throw Error('invalid web session');
  const row = await db.prepare(`INSERT INTO advisor_contacts(id,web_session,channel,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?)
    ON CONFLICT(web_session) DO UPDATE SET last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at,channel=excluded.channel RETURNING *`)
    .bind(randomId(), await sha256(cookie), who.channel || 'web', at, at, at).first<AdvisorContactRow>();
  return row!;
}

/** STOP (FC-4): no outbound of any kind from now on. A blocked contact stays blocked. True if it changed. */
export async function applyStop(db: D1Database, contactId: string, now: Date = new Date()): Promise<boolean> {
  const r = await db.prepare("UPDATE advisor_contacts SET status='stopped',updated_at=? WHERE id=? AND status='active'").bind(now.toISOString(), requireId(contactId)).run();
  return (r.meta.changes ?? 0) > 0;
}
/** START reactivates a stopped contact. It never lifts an admin block. True if it changed. */
export async function applyStart(db: D1Database, contactId: string, now: Date = new Date()): Promise<boolean> {
  const r = await db.prepare("UPDATE advisor_contacts SET status='active',updated_at=? WHERE id=? AND status='stopped'").bind(now.toISOString(), requireId(contactId)).run();
  return (r.meta.changes ?? 0) > 0;
}

/** The deterministic advisor_reviews id: sha256(kind:ref_id:reason)[:32] (02 § advisor_reviews). */
export const reviewId = async (kind: string, refId: string, reason: string): Promise<string> => (await sha256(`${kind}:${refId}:${reason}`)).slice(0, 32);

/** What "forget me" removed: counts only, never ids or content. */
export interface ForgetResult {
  contact: number; messages: number; media: number; reviews: number; reportEdits: number; crew: number;
  reportsDetached: number; boatsOrphaned: number; r2Objects: number;
}

async function deletePrefix(bucket: R2Bucket, prefix: string): Promise<number> {
  let deleted = 0, cursor: string | undefined;
  do {
    const page = await bucket.list({prefix, cursor, limit: 1000});
    const keys = page.objects.map(o => o.key);
    if (keys.length) { await bucket.delete(keys); deleted += keys.length; }
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  return deleted;
}

/**
 * "Forget me" (02 § Retention and deletion, FC-4). R2 first, so a failure
 * leaves the D1 rows in place and the whole call can be retried: the contact's
 * originals (advisor/media/<id>/), the derived files of each of its media rows
 * and any data export. Then one D1 batch: reviews about its messages, media or
 * itself, report edits, crew rows, media and messages are deleted; its reports
 * stay as the boat's record with contact_id (and a count-board media_id that is
 * being deleted) set to null; a boat it owns keeps its page but loses
 * owner_contact_id, and the admin queue gets a 'skipper' review 'owner_forgotten'.
 * The contact row goes last. The caller sends the confirmation text before this.
 */
export async function forgetContact(db: D1Database, bucket: R2Bucket | undefined, contactId: string, now: Date = new Date()): Promise<ForgetResult> {
  const id = requireId(contactId), at = now.toISOString();
  const mediaIds = (await db.prepare('SELECT id FROM advisor_media WHERE contact_id=?').bind(id).all<{id: string}>()).results.map(r => r.id);
  const boats = (await db.prepare('SELECT id FROM advisor_boats WHERE owner_contact_id=?').bind(id).all<{id: string}>()).results.map(r => r.id);
  let r2Objects = 0;
  if (bucket) {
    r2Objects += await deletePrefix(bucket, `advisor/media/${id}/`);
    r2Objects += await deletePrefix(bucket, `advisor/exports/${id}/`);
    for (const media of mediaIds) if (ID.test(media)) r2Objects += await deletePrefix(bucket, `advisor/derived/${media}/`);
  }
  const statements = [
    db.prepare(`DELETE FROM advisor_reviews WHERE ref_id=? OR ref_id IN (SELECT id FROM advisor_messages WHERE contact_id=?) OR ref_id IN (SELECT id FROM advisor_media WHERE contact_id=?)`).bind(id, id, id),
    db.prepare('DELETE FROM advisor_report_edits WHERE contact_id=?').bind(id),
    db.prepare('DELETE FROM advisor_crew WHERE contact_id=?').bind(id),
    db.prepare('UPDATE advisor_reports SET media_id=NULL,updated_at=? WHERE media_id IN (SELECT id FROM advisor_media WHERE contact_id=?)').bind(at, id),
    db.prepare('DELETE FROM advisor_media WHERE contact_id=?').bind(id),
    db.prepare('DELETE FROM advisor_messages WHERE contact_id=?').bind(id),
    db.prepare('UPDATE advisor_reports SET contact_id=NULL,updated_at=? WHERE contact_id=?').bind(at, id),
    db.prepare('UPDATE advisor_boats SET owner_contact_id=NULL,updated_at=? WHERE owner_contact_id=?').bind(at, id),
    db.prepare('DELETE FROM advisor_contacts WHERE id=?').bind(id),
    // TA-I3: the AC-1 share offer names one of the contact's photos (intake/anglers.ts shareKey).
    db.prepare('DELETE FROM job_state WHERE key=?').bind(`advisor.share.${id}`),
    // TA-A1: the one-time home-port question after a daily answer (answers/reports.ts homePortOnceKey).
    db.prepare('DELETE FROM job_state WHERE key=?').bind(`advisor.once.homeport.${id}`),
  ];
  for (const boat of boats) {
    statements.push(db.prepare(`INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,'skipper',?,'owner_forgotten','open',?)
      ON CONFLICT(id) DO UPDATE SET status='open',opened_at=excluded.opened_at,decided_at=NULL,decided_by=NULL`).bind(await reviewId('skipper', boat, 'owner_forgotten'), boat, at));
  }
  const changes = (await db.batch(statements)).map(r => r.meta.changes ?? 0);
  const n = (i: number) => changes[i] ?? 0;
  return {reviews: n(0), reportEdits: n(1), crew: n(2), media: n(4), messages: n(5), reportsDetached: n(6), boatsOrphaned: n(7), contact: n(8), r2Objects};
}

/**
 * "Send me my data": every row about the contact, or null if there is none.
 * The number itself is never included (phone_enc is omitted and not decrypted);
 * the contact shows only the first 8 hex characters of its phone_hash, and
 * whether it has a web session, not the session hash.
 */
export async function exportContact(db: D1Database, contactId: string) {
  const id = requireId(contactId);
  const contact = await db.prepare('SELECT * FROM advisor_contacts WHERE id=?').bind(id).first<AdvisorContactRow>();
  if (!contact) return null;
  const {phone_enc: _enc, phone_hash, web_session, ...rest} = contact;
  const all = async (sql: string) => (await db.prepare(sql).bind(id).all()).results;
  return {
    contact: {...rest, phone_hash_prefix: phone_hash ? phone_hash.slice(0, 8) : null, web_session: web_session != null},
    messages: await all('SELECT id,direction,channel,body,media_json,intent,status,in_reply_to,created_at,sent_at FROM advisor_messages WHERE contact_id=? ORDER BY created_at'),
    media: await all('SELECT id,message_id,boat_id,kind,mime,bytes,width,height,publish_state,credit,created_at FROM advisor_media WHERE contact_id=? ORDER BY created_at'),
    reports: await all('SELECT id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,notes,version,confirmed_at,published_at,created_at,updated_at FROM advisor_reports WHERE contact_id=? ORDER BY report_date'),
    report_edits: await all('SELECT id,report_id,message_id,patch_json,created_at FROM advisor_report_edits WHERE contact_id=? ORDER BY created_at'),
    crew: await all('SELECT boat_id,added_at,removed_at FROM advisor_crew WHERE contact_id=?'),
    boats: await all('SELECT id,slug,name,landing,port,region,instagram,booking_url,phone_public,status,verified_at,consent_photos_at,consent_revoked_at,auto_publish,created_at,updated_at FROM advisor_boats WHERE owner_contact_id=?'),
  };
}

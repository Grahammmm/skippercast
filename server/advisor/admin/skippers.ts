// The admin Skippers and Contacts views' data (docs/plans/text-advisor/08-website.md
// § Admin, Skippers and Contacts; 05 § Crew, § Verification; TA-W3): the pilot's
// recruiting tool.
//
//   listBoats       every boat with its status, owner channel, last published report,
//                   published reports in the last 30 days, posts (TA-S1: not rejected), photo
//                   consent, active crew and the admin's consent note
//   editBoat        boat fields with the registration's parsers (intake/skippers.ts), a
//                   verify or reject (the open new_skipper review is decided when there is
//                   one, else decisions.ts setBoatVerification), and the consent note
//   removeCrew      ends a crew link like the skipper's remove_crew (05 § Crew)
//   inviteSkipper   a number the admin types: hashed and encrypted on receipt and never
//                   returned; the contact is found or created (source 'skipper-invite'), the
//                   registration flow is started (intake/skippers.ts startRegistration, the
//                   TA-I1 path) and the invite goes out through the contact's channel; 20 a day
//   contactView     one contact by id (from a review or a boat; there is no search by number):
//                   its fields, boats, last 50 messages and the export link
//   setBlocked      block or unblock; unblocking restores the status the contact had
//
// Phone numbers never leave the server: contacts are shown by id, channel,
// language, display name, role and status (queue.ts ContactView).
import {advisorSettings} from '../settings.ts';
import {deriveKeys, e164, encryptPhone, phoneHash, reviewId} from '../contacts.ts';
import {outboundId, randomId, sha256} from '../ids.ts';
import {advisorLog} from '../log.ts';
import {t} from '../strings.ts';
import {portRegion} from '../links.ts';
import {localDate} from '../answers/time.ts';
import {bumpPagesVersion} from '../intake/reports.ts';
import {consentState, flowKey, parseBooking, parseInstagram, parseLanding, parseName, parsePort, startRegistration} from '../intake/skippers.ts';
import {takeDaily} from '../tools/offer_text_link.ts';
import {checkOutbound, RECIPIENT_PER_DAY, RECIPIENT_PER_WEEK, ORIGIN_PER_DAY} from '../outbound-guard.ts';
import type {OutboundRefusal} from '../outbound-guard.ts';
import {decideReview, reviewRow, setBoatVerification, NOTE_MAX} from './decisions.ts';
import type {DecisionDeps, TeamSend} from './decisions.ts';
import type {ContactView} from './queue.ts';
import type {Env} from '../../env.ts';
import type {AdvisorContactRow, Language} from '../types.ts';

export const BOATS_MAX = 500;
export const REPORT_DAYS = 30;
export const CONTACT_MESSAGES = 50;
export const INVITES_PER_DAY = 20;
export const INVITE_LIMIT_KEY = 'admin:skipper-invite';
/** Why the outbound guard refused an invite, for the admin (the admin may know; a requester on the web never does). */
export const OUTBOUND_REFUSED: Readonly<Record<OutboundRefusal, string>> = Object.freeze({
  stopped: 'that number has opted out or is blocked',
  recipient: `at most ${RECIPIENT_PER_DAY} invitations or codes a day, and ${RECIPIENT_PER_WEEK} a week, go to one number`,
  origin: `at most ${ORIGIN_PER_DAY.admin_invite} invites a day per admin`,
  ip: 'too many requests from this address today',
  global: 'the daily limit for texts to new numbers (ADVISOR_GLOBAL_DAILY_COLD) is reached',
});
export const NOTE_PREFIX = 'advisor.boat-note.';      // job_state: the admin's consent note per boat
export const BLOCK_PREFIX = 'advisor.block.';         // job_state: the status a blocked contact had
const ID = /^[\w-]{1,64}$/;
const DAY = 86400000;
const iso = (ms: number): string => new Date(ms).toISOString();
const clean = (value: unknown, max: number): string | null => {
  if (typeof value !== 'string') return null;
  const v = value.replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim();
  return v ? Array.from(v).slice(0, max).join('') : null;
};
export const validId = (id: string): boolean => ID.test(id);

export interface CrewView {contact_id: string; display_name: string | null; channel: string; status: string; added_at: string}
export interface BoatView {
  id: string; slug: string; name: string; landing: string | null; port: string; region: string; instagram: string | null;
  booking_url: string | null; phone_public: string | null; status: string; verified_at: string | null; created_at: string;
  owner: ContactView | null; last_report_date: string | null; reports_30d: number; posts: number;
  consent: 'given' | 'revoked' | 'not given'; consent_photos_at: string | null; consent_revoked_at: string | null;
  consent_note: {note: string; at: string} | null; crew: CrewView[]; review_open: boolean;
}

interface BoatJoin {
  id: string; slug: string; name: string; landing: string | null; port: string; region: string; instagram: string | null; booking_url: string | null;
  phone_public: string | null; status: string; verified_at: string | null; created_at: string; consent_photos_at: string | null; consent_revoked_at: string | null;
  owner_contact_id: string | null; o_channel: string | null; o_language: string | null; o_display_name: string | null; o_role: string | null; o_status: string | null;
  last_report_date: string | null; reports_30d: number; posts: number;
}
const BOAT_SQL = `SELECT b.id,b.slug,b.name,b.landing,b.port,b.region,b.instagram,b.booking_url,b.phone_public,b.status,b.verified_at,b.created_at,
    b.consent_photos_at,b.consent_revoked_at,b.owner_contact_id,
    o.channel AS o_channel,o.language AS o_language,o.display_name AS o_display_name,o.role AS o_role,o.status AS o_status,
    (SELECT MAX(r.report_date) FROM advisor_reports r WHERE r.boat_id=b.id AND r.status='published') AS last_report_date,
    (SELECT COUNT(*) FROM advisor_reports r WHERE r.boat_id=b.id AND r.status='published' AND r.report_date>=?) AS reports_30d,
    (SELECT COUNT(*) FROM advisor_posts p WHERE p.boat_id=b.id AND p.status<>'rejected') AS posts
  FROM advisor_boats b LEFT JOIN advisor_contacts o ON o.id=b.owner_contact_id`;

async function noteOf(db: D1Database, boatId: string): Promise<BoatView['consent_note']> {
  const raw = (await db.prepare('SELECT value FROM job_state WHERE key=?').bind(NOTE_PREFIX + boatId).first<{value: string}>())?.value;
  try { const v = raw ? JSON.parse(raw) : null; return v && typeof v.note === 'string' ? {note: v.note, at: String(v.at ?? '')} : null; } catch { return null; }
}

async function view(db: D1Database, row: BoatJoin, crew: CrewView[], openReviews: Set<string>): Promise<BoatView> {
  return {
    id: row.id, slug: row.slug, name: row.name, landing: row.landing, port: row.port, region: row.region, instagram: row.instagram,
    booking_url: row.booking_url, phone_public: row.phone_public, status: row.status, verified_at: row.verified_at, created_at: row.created_at,
    owner: row.owner_contact_id && row.o_channel ? {id: row.owner_contact_id, channel: row.o_channel, language: row.o_language ?? 'en', display_name: row.o_display_name,
      role: row.o_role ?? 'angler', status: row.o_status ?? 'active'} : null,
    last_report_date: row.last_report_date, reports_30d: Number(row.reports_30d) || 0,
    posts: Number(row.posts) || 0,   // TA-S1: the boat's social posts that were not rejected (drafts, approved, posted)
    consent: consentState(row), consent_photos_at: row.consent_photos_at, consent_revoked_at: row.consent_revoked_at,
    consent_note: await noteOf(db, row.id), crew, review_open: openReviews.has(row.id),
  };
}

async function crewOf(db: D1Database, boatId: string | null): Promise<Map<string, CrewView[]>> {
  const rows = (await db.prepare(`SELECT cr.boat_id,cr.contact_id,cr.added_at,c.display_name,c.channel,c.status FROM advisor_crew cr JOIN advisor_contacts c ON c.id=cr.contact_id
      WHERE cr.removed_at IS NULL${boatId ? ' AND cr.boat_id=?' : ''} ORDER BY cr.added_at`).bind(...(boatId ? [boatId] : []))
    .all<{boat_id: string; contact_id: string; added_at: string; display_name: string | null; channel: string; status: string}>()).results;
  const out = new Map<string, CrewView[]>();
  for (const r of rows) {
    const list = out.get(r.boat_id) ?? [];
    list.push({contact_id: r.contact_id, display_name: r.display_name, channel: r.channel, status: r.status, added_at: r.added_at});
    out.set(r.boat_id, list);
  }
  return out;
}

async function openSkipperReviews(db: D1Database): Promise<Set<string>> {
  return new Set((await db.prepare("SELECT ref_id FROM advisor_reviews WHERE kind='skipper' AND reason='new_skipper' AND status='open'").all<{ref_id: string}>()).results.map(r => r.ref_id));
}

/** Every boat, pending first, then verified, then rejected; newest first within each. */
export async function listBoats(db: D1Database, now: number = Date.now()): Promise<{boats: BoatView[]}> {
  const since = localDate(now - REPORT_DAYS * DAY);
  const rows = (await db.prepare(`${BOAT_SQL} ORDER BY CASE b.status WHEN 'pending' THEN 0 WHEN 'verified' THEN 1 ELSE 2 END, b.created_at DESC, b.id LIMIT ?`)
    .bind(since, BOATS_MAX).all<BoatJoin>()).results;
  const crew = await crewOf(db, null), open = await openSkipperReviews(db);
  return {boats: await Promise.all(rows.map(row => view(db, row, crew.get(row.id) ?? [], open)))};
}

/** One boat, as listBoats shows it, or null. */
export async function boatView(db: D1Database, boatId: string, now: number = Date.now()): Promise<BoatView | null> {
  if (!validId(boatId)) return null;
  const row = await db.prepare(`${BOAT_SQL} WHERE b.id=?`).bind(localDate(now - REPORT_DAYS * DAY), boatId).first<BoatJoin>();
  if (!row) return null;
  return view(db, row, (await crewOf(db, boatId)).get(boatId) ?? [], await openSkipperReviews(db));
}

// ---- edit -------------------------------------------------------------------------------

export type AdminOutcome<T> = {status: 'ok'; value: T} | {status: 'not-found'} | {status: 'invalid'; error: string} | {status: 'conflict'; error: string} | {status: 'unavailable'; error: string};

const EDITABLE = ['name', 'port', 'landing', 'instagram', 'booking_url', 'phone_public'] as const;
type BoatField = typeof EDITABLE[number];

/** The boat fields an edit sets, each through the registration's parser (05 § Becoming a skipper); null clears an optional one. */
export function boatPatch(input: unknown): {fields: Partial<Record<BoatField | 'region', string | null>>} | {error: string} {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return {error: 'fields must be an object'};
  const fields: Partial<Record<BoatField | 'region', string | null>> = {};
  for (const [key, raw] of Object.entries(input)) {
    if (!(EDITABLE as readonly string[]).includes(key)) return {error: `unknown field ${key.slice(0, 40)}`};
    const empty = raw === null || (typeof raw === 'string' && !raw.trim());
    if (typeof raw !== 'string' && raw !== null) return {error: `${key} must be text`};
    switch (key as BoatField) {
      case 'name': { const v = empty ? null : parseName(raw as string); if (!v) return {error: 'name must be 1-60 characters'}; fields.name = v; break; }
      case 'port': {
        const v = empty ? null : parsePort(raw as string);
        if (!v || !portRegion(v)) return {error: 'port must be a catalog port'};
        fields.port = v; fields.region = portRegion(v); break;
      }
      case 'landing': { const v = empty ? null : parseLanding(raw as string); if (!empty && !v) return {error: 'landing must be at most 60 characters'}; fields.landing = v; break; }
      case 'instagram': { const v = empty ? null : parseInstagram(raw as string); if (!empty && !v) return {error: 'instagram must be a handle (letters, digits, . and _)'}; fields.instagram = v; break; }
      case 'booking_url': {
        const v = empty ? null : parseBooking(raw as string)?.booking_url ?? null;
        if (!empty && !v) return {error: 'booking_url must be an https link'}; fields.booking_url = v; break;
      }
      case 'phone_public': {
        const v = empty ? null : e164(raw);
        if (!empty && !v) return {error: 'phone_public must be a phone number'}; fields.phone_public = v; break;
      }
    }
  }
  return {fields};
}

export interface EditInput {fields?: unknown; status?: unknown; consent_note?: unknown; by: string; now: number}

/**
 * Edit a boat: its fields (the slug stays, so links already texted keep working),
 * a verify or reject, and the consent note (the note is the admin's record only:
 * photo consent itself changes only by the skipper's own text, 05 § Consent).
 */
export async function editBoat(env: Env, boatId: string, input: EditInput, deps: Pick<DecisionDeps, 'send' | 'sendsEnabled' | 'dispatch'>): Promise<AdminOutcome<{boat: BoatView; sends: number; held?: 'replies-off'}>> {
  const db = env.DB!;
  if (!validId(boatId)) return {status: 'not-found'};
  const boat = await db.prepare('SELECT id,status FROM advisor_boats WHERE id=?').bind(boatId).first<{id: string; status: string}>();
  if (!boat) return {status: 'not-found'};
  const patch = input.fields === undefined ? {fields: {}} : boatPatch(input.fields);
  if ('error' in patch) return {status: 'invalid', error: patch.error};
  const status = input.status;
  if (status !== undefined && status !== 'verified' && status !== 'rejected') return {status: 'invalid', error: 'status must be verified or rejected'};
  const note = input.consent_note === undefined ? undefined : input.consent_note === null ? null : clean(input.consent_note, NOTE_MAX);
  if (input.consent_note !== undefined && input.consent_note !== null && !note) return {status: 'invalid', error: 'consent_note must be text'};
  const at = iso(input.now);

  const entries = Object.entries(patch.fields);
  if (entries.length) {
    const r = await db.prepare(`UPDATE advisor_boats SET ${entries.map(([k]) => `${k}=?`).join(',')},updated_at=? WHERE id=?`).bind(...entries.map(([, v]) => v), at, boatId).run();
    if (r.meta.changes) { await bumpPagesVersion(db, input.now); advisorLog('info', 'advisor_admin_boat_edited', {fields: entries.length}); }
  }
  if (note !== undefined) {
    if (note === null) await db.prepare('DELETE FROM job_state WHERE key=?').bind(NOTE_PREFIX + boatId).run();
    else await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
      .bind(NOTE_PREFIX + boatId, JSON.stringify({note, at, by: input.by}), at).run();
  }

  let sends = 0, held: 'replies-off' | undefined;
  if (status !== undefined) {
    const ok = status === 'verified';
    const review = await reviewRow(db, await reviewId('skipper', boatId, 'new_skipper'));
    if (review?.status === 'open') {
      // The registration's review is decided too, through the queue's one decision path.
      const outcome = await decideReview(env, {reviewId: review.id, decision: ok ? 'approve' : 'reject', note: 'skippers view', by: input.by, inId: review.id, key: 'admin'},
        {now: input.now, send: deps.send, ...(deps.sendsEnabled !== undefined ? {sendsEnabled: deps.sendsEnabled} : {}), ...(deps.dispatch ? {dispatch: deps.dispatch} : {})});
      if (outcome.status === 'invalid' || outcome.status === 'conflict') return outcome;
      if (outcome.status === 'applied') { sends += outcome.sends; held = outcome.held; }
    } else if (boat.status !== status) {
      // No open review (decided already, or an invited boat): the same effect when the status changes (a repeat is a no-op, so the
      // owner is never told twice what the queue already told them); the text is keyed by the status, so it goes out once per status.
      const inId = await reviewId('skipper', boatId, 'new_skipper');
      await setBoatVerification(env, {boatId, ok, by: input.by, now: input.now, text: async (owner, body) => {
        if (deps.sendsEnabled === false) { held = 'replies-off'; return; }
        sends += await deps.send(owner, inId, `admin.skipper.${status}`, body, input.by);
      }});
    }
  }
  return {status: 'ok', value: {boat: (await boatView(db, boatId, input.now))!, sends, ...(held ? {held} : {})}};
}

/** End a crew link (05 § Crew, as remove_crew does): removed_at kept for audit, the contact loses the boat and a crew role becomes angler. */
export async function removeCrew(db: D1Database, boatId: string, contactId: string, now: number): Promise<AdminOutcome<{boat: BoatView}>> {
  if (!validId(boatId) || !validId(contactId)) return {status: 'not-found'};
  const at = iso(now);
  const r = await db.prepare('UPDATE advisor_crew SET removed_at=? WHERE boat_id=? AND contact_id=? AND removed_at IS NULL').bind(at, boatId, contactId).run();
  if (!r.meta.changes && !await db.prepare('SELECT 1 AS x FROM advisor_crew WHERE boat_id=? AND contact_id=?').bind(boatId, contactId).first()) return {status: 'not-found'};
  await db.prepare(`UPDATE advisor_contacts SET boat_id=NULL,role=CASE WHEN role='crew' THEN 'angler' ELSE role END,updated_at=? WHERE id=? AND boat_id=?`).bind(at, contactId, boatId).run();
  if (r.meta.changes) advisorLog('info', 'advisor_admin_crew_removed', {count: 1});
  return {status: 'ok', value: {boat: (await boatView(db, boatId, now))!}};
}

// ---- invite -------------------------------------------------------------------------------

export interface InviteInput {phone?: unknown; boat_name?: unknown; language?: unknown; by: string; now: number}

/**
 * Invite a skipper (05 § Becoming a skipper: "an admin creates the boat and
 * sends the invite"). The number is hashed and encrypted at once and never
 * returned or logged. Refused for a stopped or blocked contact, a contact that
 * already owns a boat, while replies are off, and past 20 invites a day.
 * The invite starts the registration flow, so the reply answers its first
 * question; the text's outbound id is per contact and day, so a double click
 * texts once.
 */
export async function inviteSkipper(env: Env, input: InviteInput, deps: {send: TeamSend; sendsEnabled: boolean}): Promise<AdminOutcome<{contact_id: string; sends: number; created: boolean}>> {
  const db = env.DB!, settings = advisorSettings(env);
  const phone = e164(input.phone);
  if (!phone) return {status: 'invalid', error: 'phone must be a US mobile number'};
  const boatName = input.boat_name === undefined || input.boat_name === null || input.boat_name === '' ? null : parseName(String(input.boat_name));
  if (input.boat_name && !boatName) return {status: 'invalid', error: 'boat_name must be 1-60 characters'};
  const language: Language = input.language === 'es' ? 'es' : 'en';
  if (!env.ADVISOR_PHONE_KEY) return {status: 'unavailable', error: 'ADVISOR_PHONE_KEY is not set'};
  if (!deps.sendsEnabled) return {status: 'conflict', error: 'replies are switched off (ADVISOR_REPLIES_ENABLED)'};
  if (!await takeDaily(db, INVITE_LIMIT_KEY, INVITES_PER_DAY, input.now)) return {status: 'conflict', error: `at most ${INVITES_PER_DAY} invites a day`};
  const keys = await deriveKeys(env.ADVISOR_PHONE_KEY);
  const hash = await phoneHash(keys, phone), enc = await encryptPhone(keys, phone);
  const at = iso(input.now);
  const existed = await db.prepare('SELECT id FROM advisor_contacts WHERE phone_hash=?').bind(hash).first<{id: string}>();
  // Hardening (outbound-guard.ts): the per-number, per-admin and global limits on texts we start; the owner may see why.
  const outbound = existed && await db.prepare('SELECT 1 AS x FROM advisor_messages WHERE id=?').bind(await inviteOutboundId(existed.id, input.now)).first()
    ? null : await checkOutbound(db, settings, {kind: 'admin_invite', recipientHash: hash, origin: input.by, now: input.now});
  if (outbound && !outbound.ok) {
    advisorLog('warn', 'advisor_outbound_refused', {kind: 'admin_invite', reason: outbound.reason});
    return {status: 'conflict', error: OUTBOUND_REFUSED[outbound.reason]};
  }
  const contact = await db.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,language,source,last_seen_at,created_at,updated_at) VALUES(?,?,?,'sms',?,'skipper-invite',?,?,?)
    ON CONFLICT(phone_hash) DO UPDATE SET updated_at=advisor_contacts.updated_at RETURNING *`).bind(randomId(), hash, enc, language, at, at, at).first<AdvisorContactRow>();
  if (!contact) return {status: 'unavailable', error: 'the contact could not be stored'};
  if (contact.status !== 'active') return {status: 'conflict', error: `the contact is ${contact.status}`};
  if (await db.prepare('SELECT 1 AS x FROM advisor_boats WHERE owner_contact_id=?').bind(contact.id).first()) return {status: 'conflict', error: 'that number already has a boat'};

  const l: Language = contact.language === 'es' ? 'es' : 'en';
  const inId = (await sha256(`invite:${contact.id}:${localDate(input.now)}`)).slice(0, 32);
  // The TA-I1 path: the registration flow starts now (with the boat name when the admin gave one), so the reply is its first answer.
  const start = await startRegistration({db, settings, contact, messageId: inId, language: l, now: input.now, draft: boatName ? {name: boatName} : {}});
  const ask = start.actions.find(a => a.type === 'send_text');
  const flow = start.actions.find(a => a.type === 'flow_set');
  if (flow?.type === 'flow_set' && flow.state) await db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
    .bind(flowKey(contact.id), JSON.stringify(flow.state), at).run();
  const intro = boatName ? t(l, 'skipper_invite_boat', {boat: boatName}) : t(l, 'skipper_invite');
  const text = ask?.type === 'send_text' ? `${intro} ${ask.text}` : intro;
  if (outbound?.ok) await outbound.commit();
  const sends = await deps.send(contact, inId, 'admin.invite', text, input.by);
  advisorLog('info', 'advisor_admin_invite', {created: !existed, sends});
  return {status: 'ok', value: {contact_id: contact.id, sends, created: !existed}};
}

/** The outbound row id of an invite (tests): per contact and Pacific day. */
export const inviteOutboundId = async (contactId: string, now: number): Promise<string> => outboundId((await sha256(`invite:${contactId}:${localDate(now)}`)).slice(0, 32), 'admin.invite');

// ---- contacts -----------------------------------------------------------------------------

export interface ContactDetail {
  contact: ContactView & {source: string | null; home_port: string | null; created_at: string; last_seen_at: string; messages_today: number; blocked_from: string | null};
  boats: {id: string; name: string; slug: string; status: string; relation: 'owner' | 'crew'}[];
  messages: {direction: 'in' | 'out'; body: string | null; intent: string | null; status: string; created_at: string; team: boolean; media: number}[];
  export: string;
}

/** One contact by id: no number, no hash; its boats, its last 50 messages oldest first and the export link. */
export async function contactView(db: D1Database, id: string): Promise<ContactDetail | null> {
  if (!validId(id)) return null;
  const c = await db.prepare('SELECT * FROM advisor_contacts WHERE id=?').bind(id).first<AdvisorContactRow>();
  if (!c) return null;
  const boats = (await db.prepare(`SELECT id,name,slug,status,CASE WHEN owner_contact_id=? THEN 'owner' ELSE 'crew' END AS relation FROM advisor_boats
      WHERE owner_contact_id=? OR id IN (SELECT boat_id FROM advisor_crew WHERE contact_id=? AND removed_at IS NULL) ORDER BY relation DESC, created_at`)
    .bind(id, id, id).all<ContactDetail['boats'][number]>()).results;
  const rows = (await db.prepare('SELECT direction,body,intent,status,media_json,created_at,created_by FROM advisor_messages WHERE contact_id=? ORDER BY created_at DESC, id DESC LIMIT ?')
    .bind(id, CONTACT_MESSAGES).all<{direction: 'in' | 'out'; body: string | null; intent: string | null; status: string; media_json: string | null; created_at: string; created_by: string | null}>()).results.reverse();
  const media = (json: string | null): number => { try { const v = JSON.parse(json ?? '[]'); return Array.isArray(v) ? v.length : 0; } catch { return 0; } };
  const blocked = c.status === 'blocked' ? (await db.prepare('SELECT value FROM job_state WHERE key=?').bind(BLOCK_PREFIX + id).first<{value: string}>())?.value ?? null : null;
  return {
    contact: {id: c.id, channel: c.channel, language: c.language, display_name: c.display_name, role: c.role, status: c.status, source: c.source, home_port: c.home_port,
      created_at: c.created_at, last_seen_at: c.last_seen_at, messages_today: c.messages_today, blocked_from: blocked},
    boats,
    messages: rows.map(m => ({direction: m.direction, body: m.body, intent: m.intent, status: m.status, created_at: m.created_at, team: m.created_by !== null, media: media(m.media_json)})),
    export: `/api/admin/contacts/${encodeURIComponent(id)}/export`,
  };
}

/**
 * Block (no outbound of any kind, START does not lift it) or unblock. The
 * status before the block is kept in job_state, so unblocking a contact that
 * had texted STOP leaves it stopped.
 */
export async function setBlocked(db: D1Database, id: string, blocked: boolean, now: number): Promise<AdminOutcome<{status: string}>> {
  if (!validId(id)) return {status: 'not-found'};
  const c = await db.prepare('SELECT status FROM advisor_contacts WHERE id=?').bind(id).first<{status: string}>();
  if (!c) return {status: 'not-found'};
  const at = iso(now);
  if (blocked && c.status !== 'blocked') {
    await db.batch([
      db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at').bind(BLOCK_PREFIX + id, c.status, at),
      db.prepare("UPDATE advisor_contacts SET status='blocked',updated_at=? WHERE id=?").bind(at, id),
    ]);
    advisorLog('info', 'advisor_admin_block', {blocked: true});
  } else if (!blocked && c.status === 'blocked') {
    const prior = (await db.prepare('SELECT value FROM job_state WHERE key=?').bind(BLOCK_PREFIX + id).first<{value: string}>())?.value;
    const status = prior === 'stopped' ? 'stopped' : 'active';
    await db.batch([
      db.prepare("UPDATE advisor_contacts SET status=?,updated_at=? WHERE id=? AND status='blocked'").bind(status, at, id),
      db.prepare('DELETE FROM job_state WHERE key=?').bind(BLOCK_PREFIX + id),
    ]);
    advisorLog('info', 'advisor_admin_block', {blocked: false});
  }
  return {status: 'ok', value: {status: (await db.prepare('SELECT status FROM advisor_contacts WHERE id=?').bind(id).first<{status: string}>())!.status}};
}

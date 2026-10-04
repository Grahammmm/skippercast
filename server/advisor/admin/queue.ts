// The admin review queue's read side (docs/plans/text-advisor/08-website.md
// § Admin, Queue; TA-W2): GET /api/admin/reviews lists review items newest
// first, 50 a page, each joined with what its kind needs to be decided. Phone
// numbers never leave the server: a contact is shown by id, channel, language
// and display name only (CONTRIBUTING: no chat identifiers in casual reach).
import {countsOf} from '../intake/reports.ts';
import {conversationContact} from './decisions.ts';
import {ruleChange} from './rules.ts';
import type {ReviewRow} from './decisions.ts';
import type {ReviewKind} from '../types.ts';

export const PAGE_SIZE = 50;
export const REVIEW_KINDS: readonly ReviewKind[] = ['media', 'report', 'post', 'skipper', 'conversation', 'rule'];
export const REVIEW_STATUSES = ['open', 'approved', 'edited', 'rejected'] as const;
export type ReviewStatus = typeof REVIEW_STATUSES[number];
export const FIRST_MESSAGES = 3;
export const LAST_MESSAGES = 6;

/** The admin's view of a media item's bytes (server/routes/admin.ts serves it to admins only). */
export const adminMediaUrl = (id: string, variant: 'thumb' | 'original' = 'thumb'): string => `/api/admin/media/${encodeURIComponent(id)}${variant === 'original' ? '?v=original' : ''}`;

export interface QueueQuery {status?: string | null; kind?: string | null; cursor?: string | null; limit?: number}
export interface QueuePage {items: QueueItem[]; next: string | null}
export interface ContactView {id: string; channel: string; language: string; display_name: string | null; role: string; status: string}
export interface MessageView {direction: 'in' | 'out'; body: string | null; created_at: string; team: boolean}
export type QueueItem = Pick<ReviewRow, 'id' | 'kind' | 'ref_id' | 'reason' | 'status' | 'note' | 'opened_at' | 'decided_at'> & {detail: Record<string, unknown> | null};

/** The paging cursor: "<opened_at>|<id>" of the last item, base64url. */
export const encodeCursor = (row: {opened_at: string; id: string}): string => btoa(`${row.opened_at}|${row.id}`).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
export function decodeCursor(cursor: string | null | undefined): {opened_at: string; id: string} | null {
  if (!cursor || !/^[\w-]{1,200}$/.test(cursor)) return null;
  try {
    const [opened_at, id] = atob(cursor.replaceAll('-', '+').replaceAll('_', '/')).split('|');
    return opened_at && id && /^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/.test(opened_at) && /^[0-9a-f]{32}$/.test(id) ? {opened_at, id} : null;
  } catch { return null; }
}

/** Review items, newest first, with their kind's detail. Unknown status/kind values are refused by the route before this. */
export async function listReviews(db: D1Database, query: QueueQuery = {}): Promise<QueuePage> {
  const limit = Math.min(Math.max(1, query.limit ?? PAGE_SIZE), PAGE_SIZE);
  const where: string[] = [], args: unknown[] = [];
  if (query.status && query.status !== 'all') { where.push('status=?'); args.push(query.status); }
  if (query.kind) { where.push('kind=?'); args.push(query.kind); }
  const after = decodeCursor(query.cursor);
  if (after) { where.push('(opened_at<? OR (opened_at=? AND id<?))'); args.push(after.opened_at, after.opened_at, after.id); }
  const rows = (await db.prepare(`SELECT * FROM advisor_reviews${where.length ? ` WHERE ${where.join(' AND ')}` : ''} ORDER BY opened_at DESC, id DESC LIMIT ?`)
    .bind(...args, limit + 1).all<ReviewRow>()).results;
  const page = rows.slice(0, limit);
  const items = await Promise.all(page.map(async row => ({
    id: row.id, kind: row.kind, ref_id: row.ref_id, reason: row.reason, status: row.status, note: row.note, opened_at: row.opened_at, decided_at: row.decided_at,
    detail: await reviewDetail(db, row),
  })));
  return {items, next: rows.length > limit ? encodeCursor(page.at(-1)!) : null};
}

const contactView = (c: Record<string, unknown> | null): ContactView | null => c ? {
  id: String(c.id), channel: String(c.channel), language: String(c.language), display_name: (c.display_name as string | null) ?? null, role: String(c.role), status: String(c.status),
} : null;

async function contactById(db: D1Database, id: string | null): Promise<ContactView | null> {
  return id ? contactView(await db.prepare('SELECT id,channel,language,display_name,role,status FROM advisor_contacts WHERE id=?').bind(id).first()) : null;
}

/** The vision labels an admin needs to decide a photo (07 § result schema), from classification_json's classify result. */
export function visionLabels(json: string | null): Record<string, unknown> | null {
  try {
    const all = JSON.parse(json ?? 'null');
    const c = all && typeof all === 'object' ? all.classify : null;
    if (!c || typeof c !== 'object') return null;
    const pick: Record<string, unknown> = {};
    for (const key of ['kind', 'kind_confidence', 'has_person', 'person_confidence', 'has_fish', 'text_present', 'nsfw', 'provider']) if (key in c) pick[key] = c[key];
    const fish = all.fish_id?.candidates;
    if (Array.isArray(fish)) pick.fish = fish.slice(0, 3).map((f: {label?: unknown; confidence?: unknown}) => ({label: String(f?.label ?? ''), confidence: Number(f?.confidence) || 0}));
    return pick;
  } catch { return null; }
}

async function mediaDetail(db: D1Database, id: string): Promise<Record<string, unknown> | null> {
  const m = await db.prepare(`SELECT m.id,m.contact_id,m.kind,m.mime,m.bytes,m.width,m.height,m.r2_key,m.has_person,m.publish_state,m.credit,m.classification_json,m.created_at,
      b.id AS boat_id,b.name AS boat_name,b.slug AS boat_slug FROM advisor_media m LEFT JOIN advisor_boats b ON b.id=m.boat_id WHERE m.id=?`).bind(id)
    .first<{id: string; contact_id: string; kind: string; mime: string; bytes: number; width: number | null; height: number | null; r2_key: string; has_person: number | null;
      publish_state: string; credit: string | null; classification_json: string | null; created_at: string; boat_id: string | null; boat_name: string | null; boat_slug: string | null}>();
  if (!m) return null;
  return {media: {id: m.id, kind: m.kind, mime: m.mime, bytes: m.bytes, width: m.width, height: m.height, has_person: m.has_person === null ? null : m.has_person === 1,
    publish_state: m.publish_state, credit: m.credit, created_at: m.created_at, stored: m.r2_key !== '',
    thumb: m.r2_key ? adminMediaUrl(m.id) : null, original: m.r2_key ? adminMediaUrl(m.id, 'original') : null, labels: visionLabels(m.classification_json),
    boat: m.boat_id ? {id: m.boat_id, name: m.boat_name, slug: m.boat_slug} : null}};
}

async function reportDetail(db: D1Database, id: string): Promise<Record<string, unknown> | null> {
  const r = await db.prepare(`SELECT r.*,b.name AS boat_name,b.slug AS boat_slug,b.status AS boat_status FROM advisor_reports r LEFT JOIN advisor_boats b ON b.id=r.boat_id WHERE r.id=?`).bind(id)
    .first<{id: string; boat_id: string; boat_name: string | null; boat_slug: string | null; boat_status: string | null; port: string; region: string; report_date: string; trip_type: string | null;
      anglers: number | null; counts_json: string; source: string; media_id: string | null; status: string; verified: number; notes: string | null; version: number; published_at: string | null}>();
  if (!r) return null;
  const edits = await db.prepare('SELECT COUNT(*) AS n FROM advisor_report_edits WHERE report_id=?').bind(id).first<{n: number}>();
  return {report: {id: r.id, port: r.port, region: r.region, report_date: r.report_date, trip_type: r.trip_type, anglers: r.anglers, counts: countsOf(r.counts_json),
    notes: r.notes, source: r.source, status: r.status, verified: r.verified === 1, version: r.version, edits: edits?.n ?? 0, published_at: r.published_at,
    media: r.media_id ? adminMediaUrl(r.media_id) : null, boat: {id: r.boat_id, name: r.boat_name, slug: r.boat_slug, status: r.boat_status}}};
}

async function skipperDetail(db: D1Database, boatId: string): Promise<Record<string, unknown> | null> {
  const b = await db.prepare('SELECT id,slug,name,landing,port,region,instagram,booking_url,phone_public,owner_contact_id,status,verified_at,consent_photos_at,consent_revoked_at,created_at FROM advisor_boats WHERE id=?')
    .bind(boatId).first<Record<string, unknown> & {owner_contact_id: string | null}>();
  if (!b) return null;
  const {owner_contact_id: owner, ...boat} = b;
  const contact = await contactById(db, owner);
  // 05 § Verification: the contact's first messages, bodies only.
  const first = owner ? (await db.prepare("SELECT body FROM advisor_messages WHERE contact_id=? AND direction='in' AND body IS NOT NULL ORDER BY created_at,id LIMIT ?")
    .bind(owner, FIRST_MESSAGES).all<{body: string}>()).results.map(m => m.body) : [];
  return {boat, contact, messages: first};
}

async function conversationDetail(db: D1Database, refId: string): Promise<Record<string, unknown> | null> {
  const contact = await conversationContact(db, refId);
  if (!contact) return null;
  const last = (await db.prepare('SELECT direction,body,created_at,created_by FROM advisor_messages WHERE contact_id=? ORDER BY created_at DESC, id DESC LIMIT ?')
    .bind(contact.id, LAST_MESSAGES).all<{direction: 'in' | 'out'; body: string | null; created_at: string; created_by: string | null}>()).results.reverse();
  return {contact: contactView(contact as unknown as Record<string, unknown>), flagged_message: contact.message_id,
    messages: last.map((m): MessageView => ({direction: m.direction, body: m.body, created_at: m.created_at, team: m.created_by !== null}))};
}

async function ruleDetail(db: D1Database, refId: string): Promise<Record<string, unknown> | null> {
  // TA-A4: a change-watch review's ref is "<jurisdiction>:<fingerprint>" (admin/rules.ts watchRuleSources);
  // its summary is the stored finding (the changed pages, their links and hashes) and the jurisdiction's rows by status.
  const change = await ruleChange(db, refId);
  if (change) {
    const rows = await db.prepare("SELECT SUM(CASE WHEN status='review' THEN 1 ELSE 0 END) AS review, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active FROM advisor_rules WHERE jurisdiction=?")
      .bind(change.jurisdiction).first<{review: number | null; active: number | null}>();
    return {rule: null, summary: {...change, rules: {review: rows?.review ?? 0, active: rows?.active ?? 0}}};
  }
  // A ref that is a rule id shows that row.
  const rule = await db.prepare('SELECT id,region,jurisdiction,species_key,species_label,size_min_in,bag_limit,bag_notes,season_open,season_close,source_name,source_url,reviewed_at,review_due,status FROM advisor_rules WHERE id=?')
    .bind(refId).first().catch(() => null);
  return rule ? {rule, summary: null} : null;
}

/** What one review item's card needs, by kind; null when the referenced row is gone (or for kinds rendered generically). */
export async function reviewDetail(db: D1Database, row: Pick<ReviewRow, 'kind' | 'ref_id'>): Promise<Record<string, unknown> | null> {
  switch (row.kind) {
    case 'media': return mediaDetail(db, row.ref_id);
    case 'report': return reportDetail(db, row.ref_id);
    case 'skipper': return skipperDetail(db, row.ref_id);
    case 'conversation': return conversationDetail(db, row.ref_id);
    case 'rule': return ruleDetail(db, row.ref_id);
    default: return null;   // post: TA-S1 adds the draft editor
  }
}

// Texts we start (docs/legal/threat-model.md § 9.3, hardening): the web
// phone-link code, a crew invitation and the admin's skipper invite go to a
// number the requester typed. Every one passes this guard first, so the
// advisor cannot be used to text strangers in bulk (spam reports put the
// number and its Apple Account at risk, § 9.9):
//
//   refused  a stopped or blocked contact (STOP means no outbound of any kind)
//   recipient  at most 2 a day and 5 in any 7 days to one number (by phone_hash), whoever asks
//   origin   per requester a day: 3 link codes per web visitor, 10 crew invitations per
//            skipper, 20 skipper invites per admin
//   ip       per client address a day (web only, hashed): 5
//   global   ADVISOR_GLOBAL_DAILY_COLD (default 50) a day to numbers that have never
//            texted us (no inbound message from that contact)
//
// Counts live in request_limits (the routes/boat.ts idiom) as one row per key
// and UTC day; the 7-day count sums the last seven. checkOutbound reads only;
// the caller commits the counts right before it sends, so a refusal later in
// its own checks spends nothing. Callers never tell the requester why a text
// did not go out, so the answer never says whether a number is known to us.
import type {AdvisorSettings} from './types.ts';

export type OutboundKind = 'link_code' | 'crew_invite' | 'admin_invite';
export const RECIPIENT_PER_DAY = 2;
export const RECIPIENT_PER_WEEK = 5;
export const ORIGIN_PER_DAY: Readonly<Record<OutboundKind, number>> = Object.freeze({link_code: 3, crew_invite: 10, admin_invite: 20});
export const IP_PER_DAY = 5;
const DAY = 86400000;
const KEEP_DAYS = 8;     // request_limits rows outlive the 7-day window

export interface OutboundRequest {
  kind: OutboundKind;
  recipientHash: string;            // advisor_contacts.phone_hash of the number
  origin: string;                   // who asked: the web contact, the skipper's contact or the admin's users.id
  ipHash?: string | null;           // the web visitor's hashed address (web only)
  now: number;
}
export type OutboundRefusal = 'stopped' | 'recipient' | 'origin' | 'ip' | 'global';
export type OutboundVerdict = {ok: false; reason: OutboundRefusal} | {ok: true; cold: boolean; commit: () => Promise<void>};

const day = (now: number): number => Math.floor(now / DAY);
export const recipientKey = (hash: string, d: number): string => `advisor-out:to:${hash}:${d}`;
const originKey = (kind: OutboundKind, origin: string, d: number): string => `advisor-out:from:${kind}:${origin}:${d}`;
const ipKey = (ipHash: string, d: number): string => `advisor-out:ip:${ipHash}:${d}`;
export const coldKey = (d: number): string => `global:advisor-cold:${d}`;

async function counts(db: D1Database, ids: string[]): Promise<Map<string, number>> {
  const rows = (await db.prepare(`SELECT id,count FROM request_limits WHERE id IN (${ids.map(() => '?').join(',')})`).bind(...ids).all<{id: string; count: number}>()).results;
  return new Map(rows.map(r => [r.id, r.count]));
}

/** May we start a text to this number now? Reads only; `commit()` counts it. */
export async function checkOutbound(db: D1Database, settings: Pick<AdvisorSettings, 'globalDailyCold'>, request: OutboundRequest): Promise<OutboundVerdict> {
  const contact = await db.prepare('SELECT id,status FROM advisor_contacts WHERE phone_hash=?').bind(request.recipientHash).first<{id: string; status: string}>();
  if (contact && contact.status !== 'active') return {ok: false, reason: 'stopped'};
  const cold = !contact || !await db.prepare("SELECT 1 AS x FROM advisor_messages WHERE contact_id=? AND direction='in' LIMIT 1").bind(contact.id).first();
  const today = day(request.now);
  const week = Array.from({length: 7}, (_, i) => recipientKey(request.recipientHash, today - i));
  const origin = originKey(request.kind, request.origin, today), ip = request.ipHash ? ipKey(request.ipHash, today) : null, global = coldKey(today);
  const seen = await counts(db, [...week, origin, ...(ip ? [ip] : []), global]);
  const n = (id: string | null): number => id ? seen.get(id) ?? 0 : 0;
  if (n(week[0]!) >= RECIPIENT_PER_DAY || week.reduce((sum, id) => sum + n(id), 0) >= RECIPIENT_PER_WEEK) return {ok: false, reason: 'recipient'};
  if (n(origin) >= ORIGIN_PER_DAY[request.kind]) return {ok: false, reason: 'origin'};
  if (ip && n(ip) >= IP_PER_DAY) return {ok: false, reason: 'ip'};
  if (cold && n(global) >= settings.globalDailyCold) return {ok: false, reason: 'global'};
  const expires = (today + KEEP_DAYS) * 86400;
  const commit = async (): Promise<void> => {
    const ids = [week[0]!, origin, ...(ip ? [ip] : []), ...(cold ? [global] : [])];
    await db.batch(ids.map(id => db.prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,1,?) ON CONFLICT(id) DO UPDATE SET count=count+1').bind(id, expires)));
  };
  return {ok: true, cold, commit};
}

/**
 * A client address as the guard and the web budget key it: SHA-256 of the
 * address under ADVISOR_PHONE_KEY (so the stored key cannot be reversed by
 * trying every IPv4 address), 32 hex characters. Never logged.
 */
export async function ipHash(secret: string | undefined, ip: string): Promise<string> {
  const bytes = new TextEncoder().encode(`advisor-ip|${secret ?? ''}|${ip}`);
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(digest.slice(0, 16), b => b.toString(16).padStart(2, '0')).join('');
}

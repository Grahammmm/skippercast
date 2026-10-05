// offer_text_link (04 § Tools, 03 § web, WH-2): a web chat visitor gives a
// phone number; we text a 6-digit code to it, and when the visitor types the
// code back here the web conversation is merged into the phone contact
// (engine.ts linkCodeFlow, consumer.ts link_merge). Web only. At most 3 codes
// per web visitor per day (request_limits); the code is stored only as its
// SHA-256 in job_state advisor.link.<web contact id>, valid 10 minutes.
// Hardening: the consumer sends the code only past outbound-guard.ts (a stopped
// number, 2 a day and 5 a week per number, 5 a day per client address, the
// global ADVISOR_GLOBAL_DAILY_COLD), and the answer never depends on the number.
import type {AdvisorTool, ToolContext, ToolOutput} from './tool.ts';
import {deriveKeys, e164, encryptPhone, phoneHash} from '../contacts.ts';
import {sha256} from '../ids.ts';

export const LINK_KEY_PREFIX = 'advisor.link.';
export const LINK_CODE_TTL_MS = 10 * 60000;
export const LINK_CODES_PER_DAY = 3;
export const LINK_GUESSES_PER_DAY = 5;
/** What the model hears for any valid number, whether or not the code can go out. */
export const CODE_OFFERED = Object.freeze({sent: true, note: 'A code is texted to that number if it can receive one; ask them to type it here. If nothing arrives, they can text us instead.'});

/** The job_state key holding a web contact's pending code. */
export const linkKey = (webContactId: string): string => LINK_KEY_PREFIX + webContactId;
/** What job_state stores for a pending link (never the code or the number). */
export interface PendingLink {code_hash: string; expires_at: number; phone_contact_hash: string}

/** A six-digit code from `random` (tests) or the platform CSPRNG. */
export function linkCode(random?: () => number): string {
  const n = random ? Math.floor(random() * 1e6) : crypto.getRandomValues(new Uint32Array(1))[0]! % 1e6;
  return String(Math.min(999999, Math.max(0, n))).padStart(6, '0');
}

/** Count one use of a daily counter (the routes/boat.ts request_limits idiom); true while within `limit`. */
export async function takeDaily(db: D1Database, key: string, limit: number, now: number): Promise<boolean> {
  const day = Math.floor(now / 86400000);
  const row = await db.prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,1,?) ON CONFLICT(id) DO UPDATE SET count=count+1 RETURNING count')
    .bind(`${key}:${day}`, (day + 2) * 86400).first<{count: number}>();
  return (row?.count ?? Infinity) <= limit;
}

export const offerTextLink: AdvisorTool = {
  name: 'offer_text_link',
  description: "Web chat only. When the visitor gives you their mobile number so you can text them, call this with the number. It texts them a 6-digit code; tell them to type the code here. Never repeat the number back.",
  input_schema: {type: 'object', additionalProperties: false, required: ['phone'], properties: {
    phone: {type: 'string', description: 'The US mobile number exactly as the visitor typed it.'},
  }},
  roles: ['web'],
  intent: 'link',
  async run(input, ctx: ToolContext): Promise<ToolOutput> {
    const number = e164(input.phone);
    if (!number) return {result: {sent: false, reason: 'not a US mobile number'}};
    if (!ctx.env.ADVISOR_PHONE_KEY) return {result: {sent: false, reason: 'texting is not set up yet'}};
    if (!await takeDaily(ctx.db, `advisor-link:${ctx.contact.id}`, LINK_CODES_PER_DAY, ctx.now)) return {result: {sent: false, reason: 'too many codes today; try tomorrow'}};
    const keys = await deriveKeys(ctx.env.ADVISOR_PHONE_KEY);
    const hash = await phoneHash(keys, number);
    // Hardening: the consumer's outbound guard decides whether the code goes out (a stopped number, the per-number,
    // per-address and global limits); the answer here is the same either way, so it never says whether a number is known.
    const code = linkCode(ctx.deps.random);
    return {result: {...CODE_OFFERED}, actions: [{type: 'link_start', phoneHash: hash, phoneEnc: await encryptPhone(keys, number),
      codeHash: await sha256(code), expiresAt: ctx.now + LINK_CODE_TTL_MS, codeText: code}]};
  },
};

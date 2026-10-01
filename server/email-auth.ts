// Email sign-in: a single-use link sent to an address signs that browser in,
// creating an account the first time. A signed-in person can also add one
// address to an existing account, which gives a passkey account a way back in
// if every passkey is lost (ADR 0006's main drawback).
//
// The link carries its token in the URL fragment (/#email-sign-in=<token>), which
// browsers never send to a server, so mail scanners that fetch links cannot use
// it up; the page posts the token to /api/auth/email/verify. The server stores
// only sha256(token). Links expire after 15 minutes and work once.
//
// Mail goes through Resend when RESEND_API_KEY and MAIL_FROM are set. Without
// them the feature is off (503, and /api/session says emailSignIn: false), except
// that MAIL_TRANSPORT=log on a localhost address prints the link to the Worker
// log for `wrangler dev`.
import {AuthError, startSession, sha256, b64url, SIGN_IN_PATH} from './auth.ts';
import type {SessionUser, RelyingParty} from './auth.ts';
import type {Env} from './env.ts';

export const LINK_SECONDS = 15 * 60;
export const LINKS_PER_HOUR = 5;          // per address, so nobody can flood an inbox
export const LINK_HASH = 'email-sign-in';
const HOUR = 3600;
const RESEND = 'https://api.resend.com/emails';

export interface MailMessage {to: string; subject: string; text: string; html: string}
export interface Mailer {send(message: MailMessage): Promise<void>}

const now = () => Math.floor(Date.now() / 1000);
const iso = () => new Date().toISOString();
const esc = (s: string) => s.replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]!);

/** A lower-cased address, or an AuthError. Deliberately simple: the link proves the rest. */
export function normalizeEmail(value: unknown): string {
  if (typeof value !== 'string') throw new AuthError('enter an email address');
  const email = value.trim().toLowerCase();
  if (email.length > 254 || !/^[^\s@<>()",;:\\[\]\u0000-\u001f\u007f]+@[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(email)) throw new AuthError('enter a valid email address');
  return email;
}

/** "SkipperCast <sign-in@example.com>" or a bare address; anything else is not used. */
const validFrom = (from: string) => /^([\w .'-]{1,60} <)?[^\s@<>]+@[a-z0-9-]+(\.[a-z0-9-]+)+>?$/i.test(from) && from.includes('<') === from.endsWith('>');

/** The configured mail transport for this request, or null when email sign-in is off. */
export function mailer(env: Env, url: URL, fetcher: typeof fetch = (...args) => fetch(...args)): Mailer | null {
  const key = env.RESEND_API_KEY, from = env.MAIL_FROM?.trim();
  if (key && from && validFrom(from)) return {
    async send({to, subject, text, html}) {
      const response = await fetcher(RESEND, {method: 'POST', signal: AbortSignal.timeout(10000),
        headers: {Authorization: `Bearer ${key}`, 'Content-Type': 'application/json'},
        body: JSON.stringify({from, to: [to], subject, text, html})});
      if (!response.ok) throw Error(`mail provider answered ${response.status}`);
    },
  };
  if (env.MAIL_TRANSPORT === 'log' && (url.hostname === 'localhost' || url.hostname === '127.0.0.1')) return {
    // A warning, so it shows under `wrangler dev --log-level warn` (e2e/serve.mjs).
    async send({to, subject, text}) { console.warn(`[email-sign-in] not sent (MAIL_TRANSPORT=log) to ${to}: ${subject}\n${text}`); },
  };
  return null;
}

/** The email for a link: plain text and a minimal HTML copy with the same words. */
export function linkMessage(to: string, link: string, adding: boolean): MailMessage {
  const subject = adding ? 'Confirm your email for SkipperCast' : 'Your SkipperCast sign-in link';
  const lead = adding ? 'Open this link within 15 minutes to add this email address to your SkipperCast account:' : 'Open this link within 15 minutes to sign in to SkipperCast:';
  const after = 'The link works once. If you did not ask for it, ignore this email: nothing changes until the link is opened.';
  return {to, subject, text: `${lead}\n\n${link}\n\n${after}\n`,
    html: `<p>${esc(lead)}</p><p><a href="${esc(link)}">${adding ? 'Add this email address' : 'Sign in to SkipperCast'}</a></p><p>${esc(after)}</p>`};
}

interface LinkRow {email: string; user_id: string | null; expires_at: number}
export interface EmailContext {
  path: string; db: D1Database; rp: RelyingParty; current: SessionUser | null; mail: Mailer | null;
  body: (request: Request) => Promise<Record<string, unknown>>;
  json: (data: unknown, status?: number) => Response;
}

/** Handles /api/auth/email*. Returns a Response, or null for any other path. */
export async function emailRoute(request: Request, {path, db, rp, current, mail, body, json}: EmailContext): Promise<Response | null> {
  if (path !== '/api/auth/email' && !path.startsWith('/api/auth/email/')) return null;
  const method = request.method;
  const withCookie = (response: Response, cookie: string) => { response.headers.append('Set-Cookie', cookie); return response; };
  const endCurrent = async () => { if (current) await db.prepare('DELETE FROM sessions WHERE id=?').bind(current.sessionId).run(); };
  const unavailable = () => json({error: 'Email sign-in is not available on this site'}, 503);

  // Issues and mails a link to `email`; `userId` is the account it adds the address to.
  const sendLink = async (email: string, userId: string | null) => {
    if (!mail) return unavailable();
    const t = now();
    await db.prepare('DELETE FROM email_links WHERE expires_at<?').bind(t - HOUR).run();
    const sent = await db.prepare('SELECT COUNT(*) AS n FROM email_links WHERE email=? AND created_at>?').bind(email, t - HOUR).first<{n: number}>();
    if ((sent?.n ?? 0) >= LINKS_PER_HOUR) return json({error: 'Too many links sent to this address. Try again in an hour.'}, 429);
    const token = b64url(crypto.getRandomValues(new Uint8Array(32))), id = await sha256(token);
    await db.prepare('INSERT INTO email_links(id,email,user_id,created_at,expires_at) VALUES(?,?,?,?,?)').bind(id, email, userId, t, t + LINK_SECONDS).run();
    try { await mail.send(linkMessage(email, `${rp.origin}/#${LINK_HASH}=${token}`, !!userId)); }
    catch {
      await db.prepare('DELETE FROM email_links WHERE id=?').bind(id).run();
      return json({error: 'The email could not be sent. Try again in a few minutes.'}, 503);
    }
    // The same answer whether or not the address has an account.
    return json({sent: true, expires_in: LINK_SECONDS});
  };

  if (path === '/api/auth/email/start' && method === 'POST') return sendLink(normalizeEmail((await body(request)).email), null);

  if (path === '/api/auth/email/verify' && method === 'POST') {
    const token = (await body(request)).token;
    if (typeof token !== 'string' || !/^[\w-]{43}$/.test(token)) throw new AuthError('this sign-in link is not valid');
    // Deleting first makes the link single-use even when two tabs race.
    const link = await db.prepare('DELETE FROM email_links WHERE id=? RETURNING email,user_id,expires_at').bind(await sha256(token)).first<LinkRow>();
    if (!link || link.expires_at < now()) throw new AuthError('this link has expired or was already used; ask for a new one');
    const owner = await db.prepare('SELECT u.id,u.display_name FROM user_emails e JOIN users u ON u.id=e.user_id WHERE e.email=?').bind(link.email).first<{id: string; display_name: string | null}>();
    let user: {id: string; display_name: string | null} | null, created = false;
    if (link.user_id) {
      user = await db.prepare('SELECT id,display_name FROM users WHERE id=?').bind(link.user_id).first();
      if (!user) throw new AuthError('this account no longer exists');
      if (owner && owner.id !== user.id) throw new AuthError('that email address belongs to another SkipperCast account');
      await db.batch([db.prepare('DELETE FROM user_emails WHERE user_id=?').bind(user.id),
        db.prepare('INSERT INTO user_emails(email,user_id,verified_at) VALUES(?,?,?)').bind(link.email, user.id, iso())]);
      if (current?.id === user.id) return json({signedIn: true, user, email: link.email});
    } else if (owner) {
      user = owner;
    } else {
      user = {id: b64url(crypto.getRandomValues(new Uint8Array(16))), display_name: null}; created = true;
      await db.batch([db.prepare('INSERT INTO users(id,created_at,display_name) VALUES(?,?,?)').bind(user.id, iso(), null),
        db.prepare('INSERT INTO user_emails(email,user_id,verified_at) VALUES(?,?,?)').bind(link.email, user.id, iso())]);
    }
    await endCurrent();
    return withCookie(json({signedIn: true, created, user, email: link.email}, created ? 201 : 200), await startSession(db, user.id, request));
  }

  // The signed-in person's own address.
  if (path !== '/api/auth/email') return null;
  if (!current) return json({error: 'Sign in to manage your email', signIn: SIGN_IN_PATH}, 401);
  if (method === 'GET') {
    const row = await db.prepare('SELECT email,verified_at FROM user_emails WHERE user_id=?').bind(current.id).first<{email: string; verified_at: string}>();
    return json({email: row?.email ?? null, verified_at: row?.verified_at ?? null, available: !!mail});
  }
  if (method === 'POST') return sendLink(normalizeEmail((await body(request)).email), current.id);
  if (method === 'DELETE') {
    // Kept when it is the only way to sign in; the count is checked in the same statement.
    const removed = await db.prepare('DELETE FROM user_emails WHERE user_id=? AND EXISTS(SELECT 1 FROM passkeys WHERE user_id=?)').bind(current.id, current.id).run();
    if (!removed?.meta?.changes) {
      const has = await db.prepare('SELECT 1 AS x FROM user_emails WHERE user_id=?').bind(current.id).first();
      return has ? json({error: 'Email is your only way to sign in. Add a passkey before removing it, or delete the account.'}, 409) : json({error: 'Not found'}, 404);
    }
    return json({removed: true});
  }
  return null;
}

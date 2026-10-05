// "Send me my data" (docs/plans/text-advisor/02-data-model.md § Retention and
// deletion; TA-E1): the export JSON goes to R2 at
// advisor/exports/<contact_id>/<date>.json (the weekly retention prune,
// retention.ts, removes it after 7 days; forgetContact removes it at once) and the contact gets a
// signed link, valid 24 hours. Hardening (threat model § 9.3): the link is
// <base>/my-data#<token>; the token rides in the fragment, which browsers never
// send, and the page POSTs it to /api/advisor/export in a header, so it is in
// no request URL and no log. The old GET /api/advisor/export/<token> answers 410. The token is
// base64url("<contact_id>|<key>|<expiry epoch s>|<hex HMAC-SHA256(upload key,
// contact_id|key|expiry)>"), the same subkey and shape as upload links
// (media.ts), verified statelessly.
import {hex} from './ids.ts';

export const EXPORT_TTL_MS = 24 * 3600000;
const ID = /^[\w-]{1,64}$/;
const KEY = /^advisor\/exports\/([\w-]{1,64})\/\d{4}-\d{2}-\d{2}(?:-\d+)?\.json$/;
const encoder = new TextEncoder(), decoder = new TextDecoder();
const b64url = (bytes: Uint8Array): string => { let s = ''; for (const b of bytes) s += String.fromCharCode(b); return btoa(s).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, ''); };
function fromB64url(text: string): Uint8Array | null {
  if (!/^[\w-]{1,600}$/.test(text) || text.length % 4 === 1) return null;
  try { return Uint8Array.from(atob(text.replaceAll('-', '+').replaceAll('_', '/') + '='.repeat((4 - text.length % 4) % 4)), c => c.charCodeAt(0)); } catch { return null; }
}

/** The page the export link opens; the token is the fragment (never sent to the server in the URL). */
export const EXPORT_PAGE = '/my-data';
export const exportLink = (publicBase: string, token: string): string => `${publicBase}${EXPORT_PAGE}#${token}`;

/** The R2 key of a contact's export for a local date. */
export function exportKey(contactId: string, date: string): string {
  if (!ID.test(contactId) || !/^\d{4}-\d{2}-\d{2}$/.test(date)) throw Error('invalid export key');
  return `advisor/exports/${contactId}/${date}.json`;
}

/** A 24-hour signed token for one export object of one contact. */
export async function mintExportToken(keys: {uploadKey: CryptoKey}, contactId: string, key: string, now: number | Date = Date.now()): Promise<string> {
  const match = KEY.exec(key);
  if (!ID.test(contactId) || !match || match[1] !== contactId) throw Error('invalid export');
  const expiry = Math.floor((new Date(now).getTime() + EXPORT_TTL_MS) / 1000), signed = `${contactId}|${key}|${expiry}`;
  return b64url(encoder.encode(`${signed}|${hex(await crypto.subtle.sign('HMAC', keys.uploadKey, encoder.encode(signed)))}`));
}

/** A genuine token's contact, key and expiry (epoch ms), expired or not; null when malformed or tampered with. */
export async function readExportToken(keys: {uploadKey: CryptoKey}, token: string): Promise<{contactId: string; key: string; expiresAt: number} | null> {
  const raw = typeof token === 'string' ? fromB64url(token) : null;
  if (!raw) return null;
  const parts = decoder.decode(raw).split('|');
  if (parts.length !== 4) return null;
  const [contactId, key, expiry, mac] = parts as [string, string, string, string];
  const match = KEY.exec(key);
  if (!ID.test(contactId) || !match || match[1] !== contactId || !/^\d{1,12}$/.test(expiry) || !/^[0-9a-f]{64}$/.test(mac)) return null;
  const macBytes = Uint8Array.from(mac.match(/../g)!, h => parseInt(h, 16));
  if (!await crypto.subtle.verify('HMAC', keys.uploadKey, macBytes, encoder.encode(`${contactId}|${key}|${expiry}`))) return null;
  return {contactId, key, expiresAt: Number(expiry) * 1000};
}

/** {contactId, key} for a valid, unexpired token whose key belongs to that contact; otherwise null. */
export async function verifyExportToken(keys: {uploadKey: CryptoKey}, token: string, now: number | Date = Date.now()): Promise<{contactId: string; key: string} | null> {
  const read = await readExportToken(keys, token);
  return read && read.expiresAt > new Date(now).getTime() ? {contactId: read.contactId, key: read.key} : null;
}

// Inbound store-and-dispatch (docs/plans/text-advisor/01-architecture.md
// § request flow, steps 2-4), shared by every way a message arrives: the
// provider webhooks and the upload link (TA-C4 moved it here from
// server/routes/advisor.ts so both use one path).
import {deriveKeys, findOrCreateContact} from './contacts.ts';
import {runInline, MAX_BODY} from './consumer.ts';
import {channelFor} from './channels/index.ts';
import type {InboundMessage} from './channels/index.ts';
import {advisorLog} from './log.ts';
import {randomId} from './ids.ts';
// TA-C6: the deep link's source marker is stripped from the stored body.
import {parseSourceMarker} from './intents.ts';
import type {Env} from '../env.ts';

const MEDIA_KIND = (mime: string | null): 'image' | 'video' | 'audio' => mime?.startsWith('video/') ? 'video' : mime?.startsWith('audio/') ? 'audio' : 'image';

/**
 * Store one normalized inbound message (01 § request flow, steps 2-3): the
 * contact (created on first contact), the advisor_messages row ('queued') and
 * one placeholder advisor_media row per attachment (r2_key '' and the
 * provider's reference in provider_ref until the consumer downloads it). The
 * message and its media go in one batch; a second delivery of the same
 * provider id changes nothing. Returns the new message id, or null for a duplicate.
 *
 * TA-C6: a trailing `[via <source>]` marker (the /text deep link's, 03 § contact
 * card and deep links) is removed from the stored body, and its source becomes
 * advisor_contacts.source when this is the contact's first inbound message and
 * no source is set yet; a later marker never replaces the first value.
 *
 * TA-C3: a web chat message (channel 'web', `from` the sc_adv cookie value)
 * finds its contact by session, needs no phone key, records source 'web' when
 * it has no marker, and attaches `mediaIds` (stored uploads of that contact
 * not yet used by a message) to the new message.
 */
export async function storeInbound(env: Env, message: InboundMessage, now: Date = new Date()): Promise<string | null> {
  const db = env.DB!;
  const seen = await db.prepare('SELECT id FROM advisor_messages WHERE channel=? AND provider_id=?').bind(message.channel, message.providerId).first<{id: string}>();
  if (seen) return null;
  // TA-C3: a web chat message is from a session cookie, not a number, and needs no phone key.
  const web = message.channel === 'web';
  if (!web && !env.ADVISOR_PHONE_KEY) throw Error('ADVISOR_PHONE_KEY is not set');
  const contact = web
    ? await findOrCreateContact(db, null, {webSession: message.from, channel: 'web'}, now)
    : await findOrCreateContact(db, await deriveKeys(env.ADVISOR_PHONE_KEY!), {e164: message.from, channel: message.channel}, now);
  const id = randomId(), at = now.toISOString();
  const media = message.media.map(m => ({id: randomId(), ...m}));
  // TA-C3: already stored media (web uploads) are attached by id, after the media placeholders.
  const attached = [...new Set(message.mediaIds ?? [])];
  const mediaIds = [...media.map(m => m.id), ...attached];
  const marker = parseSourceMarker(message.text);
  // TA-C3: a web chat contact without a marker started from the site ('web', 02 § advisor_contacts).
  const source = marker.source ?? (web ? 'web' : null);
  const statements = [
    // TA-C6: first-touch attribution, before the message row so "first inbound" excludes this one.
    ...(source && !contact.source ? [db.prepare(`UPDATE advisor_contacts SET source=? WHERE id=? AND source IS NULL
      AND NOT EXISTS (SELECT 1 FROM advisor_messages WHERE contact_id=? AND direction='in')`).bind(source, contact.id, contact.id)] : []),
    db.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,media_json,status,created_at) VALUES(?,?,'in',?,?,?,?,'queued',?) ON CONFLICT DO NOTHING`)
      .bind(id, contact.id, message.channel, message.providerId, marker.text.slice(0, MAX_BODY) || null, mediaIds.length ? JSON.stringify(mediaIds) : null, at),
    // Only if this call's message row exists, i.e. it was not a concurrent duplicate.
    ...media.map(m => db.prepare(`INSERT INTO advisor_media(id,contact_id,message_id,boat_id,kind,mime,bytes,width,height,r2_key,sha256,publish_state,provider_ref,created_at)
      SELECT ?,?,?,?,?,?,?,?,?,'','','private',?,? WHERE EXISTS (SELECT 1 FROM advisor_messages WHERE id=?)`)
      .bind(m.id, contact.id, id, contact.boat_id, MEDIA_KIND(m.mime), m.mime ?? 'application/octet-stream', m.bytes ?? 0, m.width ?? null, m.height ?? null, m.providerRef, at, id)),
    // TA-C3: only this contact's media that no message has claimed yet.
    ...attached.map(mediaId => db.prepare('UPDATE advisor_media SET message_id=? WHERE id=? AND contact_id=? AND message_id IS NULL AND EXISTS (SELECT 1 FROM advisor_messages WHERE id=?)')
      .bind(id, mediaId, contact.id, id)),
  ];
  const results = await db.batch(statements);
  const inserted = results[statements.length - media.length - attached.length - 1];
  return inserted?.meta.changes ? id : null;
}

/**
 * Hand a stored inbound message to ADVISOR_QUEUE, or run it inline when there
 * is no queue (or the send fails): under `waitUntil` when the caller has an
 * execution context, otherwise awaited before returning (tests).
 */
export async function dispatchInbound(env: Env, id: string, waitUntil?: (promise: Promise<unknown>) => void): Promise<void> {
  if (env.ADVISOR_QUEUE) {
    try { await env.ADVISOR_QUEUE.send({message_id: id}); return; }
    catch (error) { advisorLog('error', 'advisor_enqueue_failed', {reason: String((error as Error)?.message).slice(0, 200)}); }
  }
  const run = runInline(env, id, {channelFor}).catch(error => { advisorLog('error', 'advisor_inline_failed', {reason: String((error as Error)?.message).slice(0, 200)}); });
  if (waitUntil) waitUntil(run); else await run;
}

/**
 * TA-C4: the synthetic inbound message for a file that came through the upload
 * link (03 § Uploads for compressed channels): body '', media_json [media_id],
 * the contact's channel, provider_id 'upload:<media_id>' (so one upload is one
 * message), and the media row attached to it. Returns the message id, or null
 * when that upload already has its message.
 */
export async function storeUpload(env: Env, contact: {id: string; channel: string}, mediaId: string, now: Date = new Date()): Promise<string | null> {
  const db = env.DB!, id = randomId(), at = now.toISOString();
  const [inserted] = await db.batch([
    db.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,media_json,status,created_at) VALUES(?,?,'in',?,?,'',?,'queued',?) ON CONFLICT DO NOTHING`)
      .bind(id, contact.id, contact.channel, `upload:${mediaId}`, JSON.stringify([mediaId]), at),
    db.prepare('UPDATE advisor_media SET message_id=? WHERE id=? AND message_id IS NULL AND EXISTS (SELECT 1 FROM advisor_messages WHERE id=?)').bind(id, mediaId, id),
  ]);
  return inserted?.meta.changes ? id : null;
}

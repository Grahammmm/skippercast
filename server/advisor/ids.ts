// Deterministic ids for the Text Advisor (docs/plans/text-advisor/02-data-model.md).
// Rows a retried queue message could write twice get an id derived from what
// produced them, so a second write lands on the same row instead of a new one.

const encoder = new TextEncoder();
export const hex = (buffer: ArrayBuffer): string => Array.from(new Uint8Array(buffer), b => b.toString(16).padStart(2, '0')).join('');
/** Lowercase hex SHA-256 of the UTF-8 text. */
export const sha256 = async (text: string): Promise<string> => hex(await crypto.subtle.digest('SHA-256', encoder.encode(text)));

/**
 * An outbound advisor_messages id: sha256(in_message_id + ':' + action_index)[:32]
 * (02 § advisor_messages). `index` is the action's position in the engine
 * result, or a fixed word for the consumer's own texts ('still-working',
 * 'error'), so each of those is sent at most once per inbound message.
 */
export const outboundId = async (inMessageId: string, index: number | string): Promise<string> => (await sha256(`${inMessageId}:${index}`)).slice(0, 32);

/** A random 16-byte id, base64url (user-facing rows: contacts, inbound messages, media). */
export function randomId(): string {
  let s = ''; for (const b of crypto.getRandomValues(new Uint8Array(16))) s += String.fromCharCode(b);
  return btoa(s).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
}

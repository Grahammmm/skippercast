// The reply length rule (docs/plans/text-advisor/04-advisor-engine.md § stage 3,
// 00 principle 2): three SMS segments. Shared by the model turn (engine.ts) and
// the deterministic answers that can run long (the fish ID with its rules).
export const REPLY_MAX = 480;

/**
 * At most three SMS segments (480 characters) unless the reply is a list: cut
 * at sentence boundaries; a link that would be cut is kept at the end.
 */
export function capReply(text: string, links: readonly string[], max = REPLY_MAX): string {
  if (text.length <= max) return text;
  const link = links[0];
  const body = link ? text.replace(link, '').replace(/\s{2,}/g, ' ').trim() : text;
  const room = link ? max - link.length - 1 : max;
  const sentences = body.split(/(?<=[.!?])\s+/);
  let out = '';
  for (const s of sentences) { if ((out ? out.length + 1 : 0) + s.length > room) break; out = out ? `${out} ${s}` : s; }
  if (!out) out = body.slice(0, Math.max(0, room - 1)).replace(/\s+\S*$/, '') + '…';
  return link ? `${out} ${link}` : out;
}


// The engine's cheap pre-router (docs/plans/text-advisor/01-architecture.md
// § module layout, 04 § stages 0-1). TA-C6 adds the first piece: the source
// marker a deep link pre-fills (03 § contact card and deep links): the body
// "<message> [via <source>]" says where a first message came from. TA-E1 adds
// commands, language detection and keyword routing here.

/** Sources the /text deep link accepts (`s=`): lowercase letters, digits, ':', '_' and '-', 1 to 32 characters. */
export const SOURCE_PATTERN = /^[a-z0-9:_-]{1,32}$/;
const MARKER = /\s*\[via ([a-z0-9:_-]{1,32})\]\s*$/;
const POST_ID = /^[\w-]{1,64}$/;

export interface SourceMarker {
  text: string;                 // the message without the marker (trimmed at the end only)
  source: string | null;        // 'qr', 'ig', 'web', ... (lowercase); null when there is no marker
  postId?: string;              // `[via ig:<post_id>]`: the Instagram post a per-post CTA came from (09 § SP-10)
}

/**
 * Strip a trailing `[via <source>]` marker, exactly as /text writes it (one
 * space after "via", a source matching SOURCE_PATTERN). `[via ig:<post_id>]`
 * gives source 'ig' and the post id. A marker anywhere but the end, or in any
 * other shape, is left in the text (a person typed it).
 */
export function parseSourceMarker(text: string): SourceMarker {
  const value = typeof text === 'string' ? text : '';
  const match = MARKER.exec(value);
  if (!match) return {text: value, source: null};
  const raw = match[1]!;
  const rest = value.slice(0, match.index).replace(/\s+$/, '');
  const ig = /^ig:(.+)$/.exec(raw);
  if (ig && POST_ID.test(ig[1]!)) return {text: rest, source: 'ig', postId: ig[1]!};
  return {text: rest, source: raw};
}

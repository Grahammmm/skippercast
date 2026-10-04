// The engine's cheap pre-router (docs/plans/text-advisor/01-architecture.md
// § module layout, 04 § stages 0-1). TA-C6 adds the first piece: the source
// marker a deep link pre-fills (03 § contact card and deep links): the body
// "<message> [via <source>]" says where a first message came from. TA-E1 adds
// the Stage 1 commands table (en and es) and the language detection below.

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

// ---- TA-E1: commands and language (04 § stage 1) ---------------------------------

/** The Stage 1 commands. `delete` is only a command right after "forget me" asked for it. */
export type Command = 'stop' | 'start' | 'help' | 'forget' | 'delete' | 'export' | 'upload_link';

/**
 * Exact matches after trimming, lower-casing and dropping trailing punctuation,
 * in either language (04 § stage 1 table). `yes` is START only for a stopped
 * contact; the engine checks that. `borrar` confirms like `delete` (the Spanish
 * forget-me prompt asks for it).
 */
export const COMMANDS: Readonly<Record<string, Command>> = Object.freeze({
  stop: 'stop', stopall: 'stop', unsubscribe: 'stop', cancel: 'stop', end: 'stop', quit: 'stop', alto: 'stop', parar: 'stop',
  start: 'start', unstop: 'start', yes: 'start', empezar: 'start',
  help: 'help', ayuda: 'help', '?': 'help',
  'forget me': 'forget', 'delete my data': 'forget', 'olvídame': 'forget', 'olvidame': 'forget', 'borra mis datos': 'forget',
  delete: 'delete', borrar: 'delete',
  'send me my data': 'export', export: 'export', 'mis datos': 'export',
  // 04 § stage 2: the upload-link request.
  'send me a link': 'upload_link', link: 'upload_link', 'mándame un enlace': 'upload_link', 'mandame un enlace': 'upload_link', enlace: 'upload_link',
});

/** The text as commands compare it: trimmed, lower-cased, inner spaces collapsed, trailing . ! removed. */
export const normalizeCommand = (text: string): string => String(text ?? '').normalize('NFC').trim().toLowerCase().replace(/\s+/g, ' ').replace(/[.!¡]+$/u, '').replace(/^¡/u, '').trim();

/** The command this message is, or null. */
export function parseCommand(text: string): Command | null {
  const key = normalizeCommand(text);
  return key && Object.hasOwn(COMMANDS, key) ? COMMANDS[key]! : null;
}

// Function words only: frequent, short, and rarely shared between the two
// languages (shared ones such as "a", "no", "me" and "de"... are left out of
// English; "de" is Spanish-only here).
const ES = new Set(['el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 'de', 'del', 'que', 'qué', 'y', 'en', 'por', 'para', 'con', 'es', 'está', 'están',
  'hay', 'como', 'cómo', 'pero', 'mi', 'mis', 'tu', 'tus', 'su', 'sus', 'yo', 'tú', 'usted', 'se', 'lo', 'le', 'les', 'al', 'muy', 'más', 'sí', 'cuándo',
  'dónde', 'donde', 'cuál', 'cual', 'este', 'esta', 'esto', 'ese', 'esa', 'hoy', 'mañana', 'ayer', 'también', 'quiero', 'puedo', 'tengo', 'hola', 'gracias', 'buenos', 'buenas', 'o', 'sin', 'sobre']);
const EN = new Set(['the', 'a', 'an', 'of', 'and', 'in', 'on', 'for', 'with', 'is', 'are', 'was', 'what', "what's", 'how', "how's", 'where', 'when', 'which', 'to',
  'it', "it's", 'this', 'that', 'my', 'your', 'you', 'i', "i'm", 'we', 'they', 'do', 'does', 'can', 'will', 'there', 'any', 'at', 'from', 'be', 'have', 'has',
  'today', 'tomorrow', 'yesterday', 'hello', 'hi', 'thanks', 'please', 'or', 'but', 'about', 'out', 'up', 'just']);
/** Spanish function words needed before a message counts as Spanish (04 § stage 1). */
export const ES_MIN_WORDS = 3;

/**
 * 'es' when the text has at least three Spanish function words and more
 * Spanish than English ones, 'en' when it has more English ones, otherwise
 * null (too short or mixed to tell; the caller keeps the stored language).
 */
export function detectLanguage(text: string): 'en' | 'es' | null {
  const words = String(text ?? '').toLowerCase().normalize('NFC').match(/[\p{L}']+/gu) ?? [];
  let es = 0, en = 0;
  for (const w of words) { if (ES.has(w)) es++; if (EN.has(w)) en++; }
  if (es >= ES_MIN_WORDS && es > en) return 'es';
  // A couple of strong Spanish markers in a short text ("¿qué pica hoy?") still count, when English has none.
  if (/[¿¡ñ]/u.test(text) && es >= 1 && en === 0) return 'es';
  if (en >= 2 && en > es) return 'en';
  return null;
}

/**
 * The reply language and whether the stored one should change (FC-6): a
 * message detected in the other language is answered in it; the contact's
 * stored language changes only when the previous inbound message was in that
 * language too (two in a row). Undetected text (and a media-only message)
 * keeps the stored language.
 */
export function chooseLanguage(stored: string, current: 'en' | 'es' | null, previous: 'en' | 'es' | null): {reply: 'en' | 'es'; store: 'en' | 'es' | null} {
  const base: 'en' | 'es' = stored === 'es' ? 'es' : 'en';
  if (!current || current === base) return {reply: base, store: null};
  return {reply: current, store: previous === current ? current : null};
}

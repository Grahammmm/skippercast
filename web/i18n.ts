// BF-spanish-app: the app's string catalogue reader and language choice. The strings live in
// catalog/app/strings.json (en + es, written, never generated at run time); this file is the one reader
// every covered surface uses, so a later surface is a catalogue addition, not a new design. Pure
// functions first; only `language` and the init/set helpers touch the page.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {signal} from '@preact/signals';
import catalog from '../catalog/app/strings.json' with {type: 'json'};

export const LANGUAGES = ['en', 'es'] as const;
export type Language = typeof LANGUAGES[number];
export type StringId = keyof typeof catalog.strings;
export interface Entry { en: string; es?: string }
export type Table = Readonly<Record<string, Entry>>;
export const STRINGS: Table = catalog.strings;

/** Under Node (tests, tools) a missing id throws so CI catches the gap; in the browser it falls back so a visitor never sees a blank. */
const STRICT = !!(globalThis as {process?: {versions?: {node?: string}}}).process?.versions?.node;

/**
 * The text of `id` in `lang` with `{name}` variables filled. A missing `es` value renders the English
 * (scripts/check_copy.mjs reports the gap). An id missing entirely throws when `strict`, else renders the
 * id itself: never an empty string.
 */
export function lookup(table: Table, id: string, lang: Language | string | null | undefined, vars: Readonly<Record<string, string | number>> = {}, strict = STRICT): string {
  const entry = Object.hasOwn(table, id) ? table[id] : undefined;
  if (!entry || typeof entry.en !== 'string' || entry.en === '') {
    if (strict) throw Error(`unknown string id ${id}`);
    return id;
  }
  const text = (lang === 'es' && entry.es) || entry.en;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) => Object.hasOwn(vars, name) ? String(vars[name]) : whole);
}

/** The covered surfaces' string for `id` in `lang` (English by default). */
export const t = (id: StringId, lang: Language | string | null | undefined = 'en', vars: Readonly<Record<string, string | number>> = {}): string => lookup(STRINGS, id, lang, vars);

/** The supported language a tag names ("es", "es-MX", "ES_419"), else null. */
export function supported(tag: unknown): Language | null {
  const primary = String(tag ?? '').trim().toLowerCase().split(/[-_]/)[0] ?? '';
  return (LANGUAGES as readonly string[]).includes(primary) ? primary as Language : null;
}

/**
 * The first supported language of an Accept-Language header by weight (then by position); null when the
 * header is absent or names none. An entry whose tag or weight is malformed, or whose weight is 0, is dropped.
 */
export function acceptedLanguage(header: unknown): Language | null {
  if (typeof header !== 'string') return null;
  const ranked = header.split(',').flatMap((part, position) => {
    const [tag = '', ...params] = part.split(';').map(s => s.trim()), weight = params.find(p => /^q=/i.test(p));
    const q = weight === undefined ? 1 : /^q=(?:0(?:\.\d{0,3})?|1(?:\.0{0,3})?)$/i.test(weight) ? Number(weight.slice(2)) : NaN;
    return /^(?:[a-z]{1,8}(?:-[a-z0-9]{1,8})*|\*)$/i.test(tag) && q > 0 ? [{tag, q, position}] : [];
  }).sort((a, b) => b.q - a.q || a.position - b.position);
  for (const {tag} of ranked) { const found = supported(tag); if (found) return found; }
  return null;
}

/** The user's own preference, else Accept-Language, else English. A preference naming an unsupported language reads English, not the header. */
export function resolveLanguage(preference: unknown, acceptLanguage: unknown): Language {
  if (preference !== null && preference !== undefined && preference !== '') return supported(preference) ?? 'en';
  return acceptedLanguage(acceptLanguage) ?? 'en';
}

/** The platform formatter's locale for `lang`. */
export const localeOf = (lang: Language | string): string => lang === 'es' ? 'es' : 'en-US';

/** A number in `lang`'s format, at most `digits` decimals, no grouping ("1.5" / "1,5"). */
export const num = (n: number, lang: Language | string, digits = 1): string => new Intl.NumberFormat(localeOf(lang), {maximumFractionDigits: digits, useGrouping: false}).format(n);

/** A short date ("Sat Oct 10" / "sáb 10 oct") in `tz`. */
export const shortDate = (at: Date | number | string, lang: Language | string, tz = 'UTC', opts: Intl.DateTimeFormatOptions = {weekday: 'short', month: 'short', day: 'numeric'}): string =>
  new Date(at).toLocaleDateString(localeOf(lang), {timeZone: tz, ...opts}).replace(',', '');

/** localStorage key of the explicit language preference (device only, like the profile). */
export const LANGUAGE_KEY = 'skippercast-language-v1';
/** The page's language; the covered components read it, so they re-render when it changes. */
export const language = signal<Language>('en');

export interface LanguageEnv {
  /** location.search; ?lang=es|en is an explicit choice and is remembered. */
  search?: string;
  storage?: Pick<Storage, 'getItem' | 'setItem'> | null;
  /** navigator.languages: the browser's Accept-Language list, most preferred first. */
  languages?: readonly string[];
  doc?: {documentElement: {lang: string}} | null;
}

const browser = (): LanguageEnv => ({
  search: globalThis.location?.search, storage: globalThis.localStorage ?? null,
  languages: globalThis.navigator?.languages, doc: globalThis.document ?? null,
});

/** Resolve the language from ?lang=, the stored preference, then the browser's Accept-Language, and apply it (signal and document lang). */
export function initLanguage(env: LanguageEnv = browser()): Language {
  let preference: string | null = null;
  try {
    const linked = supported(new URLSearchParams(env.search ?? '').get('lang'));
    if (linked) { preference = linked; env.storage?.setItem(LANGUAGE_KEY, linked); }
    else preference = env.storage?.getItem(LANGUAGE_KEY) ?? null;
  } catch { /* storage blocked: no preference */ }
  const lang = resolveLanguage(preference, env.languages?.join(',') ?? null);
  language.value = lang;
  if (env.doc) env.doc.documentElement.lang = lang;
  return lang;
}
